"""
MARK-XX — Gemini LLM Wrapper
Uses google-genai SDK. Supports automatic API key rotation on 429 quota errors.
"""

import json
import re
import time
from typing import List, Dict, Optional, Tuple, Any

from core.logger import get_logger
log = get_logger("llm")

try:
    from google import genai
    from google.genai import types as genai_types
    NEW_SDK = True
except ImportError:
    import google.generativeai as genai_legacy
    NEW_SDK = False


# ── Safety settings to prevent over-filtering of code/technical content ───────
def _build_safety_settings():
    """Build permissive safety settings to avoid silent content blocking."""
    if NEW_SDK:
        categories = [
            "HARM_CATEGORY_HARASSMENT",
            "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "HARM_CATEGORY_DANGEROUS_CONTENT",
            "HARM_CATEGORY_CIVIC_INTEGRITY",
        ]
        settings = []
        for cat in categories:
            try:
                settings.append(genai_types.SafetySetting(
                    category=cat, threshold="OFF",
                ))
            except Exception:
                # Some models/API versions don't support all categories
                try:
                    settings.append(genai_types.SafetySetting(
                        category=cat, threshold="BLOCK_NONE",
                    ))
                except Exception:
                    pass
        return settings
    else:
        # Legacy SDK uses dict-based safety settings
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        return {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

SAFETY_SETTINGS = _build_safety_settings()

SAFETY_BLOCKED_MSG = (
    "I'm sorry, my response was blocked by safety filters. "
    "Please try rephrasing your request."
)


# ── Tool declarations (lazy import to avoid circular dependency) ──────────────
_tool_declarations_cache = None

def _get_tool_declarations():
    """Lazy-load native Gemini function declarations."""
    global _tool_declarations_cache
    if _tool_declarations_cache is not None:
        return _tool_declarations_cache
    try:
        from agent.tool_declarations import build_tool_declarations
        _tool_declarations_cache = build_tool_declarations()
        log.info(f"Loaded {sum(len(t.function_declarations) for t in _tool_declarations_cache)} native tool declarations")
    except Exception as e:
        log.warning(f"Could not load tool declarations: {e}")
        _tool_declarations_cache = []
    return _tool_declarations_cache



def normalize_key_pool(api_key: str, extra_keys: List[str] = None) -> List[str]:
    """Build deduplicated pool: primary first, then extras (stable order)."""
    seen: set = set()
    pool: List[str] = []
    for k in ([api_key] + (extra_keys or [])):
        k = (k or "").strip()
        if k and k not in seen:
            seen.add(k)
            pool.append(k)
    return pool


# ── Key Rotator ────────────────────────────────────────────────────────────────
class KeyRotator:
    """
    Manages a pool of API keys. On 429, rotates to the next key automatically.
    Signals the caller so the UI can display which key slot is active.
    """

    def __init__(self, keys: List[str]):
        self._keys = [k.strip() for k in keys if k.strip()]
        self._idx = 0
        self.on_rotate = None   # optional callback: fn(new_key: str, slot: int, total: int)

    def load(self, keys: List[str]):
        self._keys = [k.strip() for k in keys if k.strip()]
        self._idx = 0

    @property
    def current(self) -> str:
        if not self._keys:
            return ""
        return self._keys[self._idx]

    @property
    def count(self) -> int:
        return len(self._keys)

    @property
    def slot(self) -> int:
        return self._idx + 1

    def rotate(self) -> bool:
        """Move to next key. Returns False if we've cycled through all keys."""
        if len(self._keys) <= 1:
            return False
        next_idx = (self._idx + 1) % len(self._keys)
        if next_idx == 0:
            # Wrapped around — all keys exhausted this cycle
            return False
        self._idx = next_idx
        if self.on_rotate:
            self.on_rotate(self.current, self.slot, self.count)
        return True

    def reset(self):
        self._idx = 0


# ── LLM Client ────────────────────────────────────────────────────────────────
class LLMClient:
    def __init__(self, api_key: str, model: str = "gemini-3.1-flash-lite",
                 system_prompt: str = "", extra_keys: List[str] = None,
                 temperature: float = 0.7, max_tokens: int = 2048):
        self.model_name   = model
        self.system_prompt = system_prompt
        self.temperature  = temperature
        self.max_tokens   = max_tokens
        self._chat = None
        self._history_cache = []  # Preserve history when session is reset

        # Build key pool (dedupe — duplicates waste rotation slots)
        self.rotator = KeyRotator(normalize_key_pool(api_key, extra_keys))
        self._client = None
        if self.rotator.current:
            self._init_client(self.rotator.current)

        # Callback for key-rotation notifications (set by UI)
        self.on_key_rotated = None   # fn(new_key, slot, total, reason)

    # ── Setup ──────────────────────────────────────────────────────────────────
    def _init_client(self, api_key: str):
        if NEW_SDK:
            self._client = genai.Client(api_key=api_key)
        else:
            genai_legacy.configure(api_key=api_key)
        
        # Save current history before resetting chat session
        if self._chat:
            try:
                self._history_cache = list(self._chat.history)
            except Exception:
                pass
        self._chat = None

    def configure(self, api_key: str, model: str = None, extra_keys: List[str] = None):
        if model:
            self.model_name = model
        self.rotator.load(normalize_key_pool(api_key, extra_keys))
        if self.rotator.current:
            self._init_client(self.rotator.current)

    def reset_chat(self):
        self._chat = None
        self._history_cache = []

    def update_system_prompt(self, prompt: str):
        if prompt != self.system_prompt:
            self.system_prompt = prompt
            if self._chat:
                try:
                    self._history_cache = list(self._chat.history)
                except Exception:
                    pass
            self._chat = None

    # ── Internal: retry + rotate on 429 ───────────────────────────────────────
    def _call_with_rotation(self, fn, *args, **kwargs):
        """
        Calls fn(*args, **kwargs). On 429:
        1. Tries to rotate to next API key and retries immediately.
        2. If no more keys, waits the server-suggested delay and retries.
        3. Gives up after exhausting all keys + one backoff wait.
        """
        MAX_ATTEMPTS = max(4, self.rotator.count * 2)
        backoff = 5

        for attempt in range(MAX_ATTEMPTS):
            try:
                return fn(*args, **kwargs)

            except Exception as e:
                msg = str(e)
                # Robust matching for 429 / rate limits across different SDK versions
                is_rate_limit = (
                    "429" in msg 
                    or "RESOURCE_EXHAUSTED" in msg.upper() 
                    or "RESOURCE_EXHAUSTED" in getattr(e, "message", "").upper()
                    or "RATE_LIMIT" in msg.upper()
                    or "RATE_LIMIT" in getattr(e, "message", "").upper()
                    or "QUOTA" in msg.upper()
                    or getattr(e, "code", 0) == 429
                    or getattr(e, "status_code", 0) == 429
                )

                if not is_rate_limit:
                    log.error(f"LLM error (attempt {attempt+1}): {msg[:200]}")
                    raise

                log.warning(f"Rate limit hit on key slot {self.rotator.slot}/{self.rotator.count} (attempt {attempt+1})")

                # Parse server-suggested wait time
                m = re.search(r"retry[^0-9]*(\d+)", msg, re.I)
                suggested_wait = int(m.group(1)) + 1 if m else backoff

                # Save history before rotating
                if self._chat:
                    try:
                        self._history_cache = list(self._chat.history)
                    except Exception:
                        pass

                # Try rotating to next key first (instant, no wait)
                rotated = self.rotator.rotate()
                if rotated:
                    log.info(f"Key rotated → slot {self.rotator.slot}/{self.rotator.count}")
                    self._init_client(self.rotator.current)
                    # _init_client already sets self._chat = None
                    if self.on_key_rotated:
                        self.on_key_rotated(
                            self.rotator.current,
                            self.rotator.slot,
                            self.rotator.count,
                            "quota exhausted",
                        )
                    continue

                if self.rotator.count <= 1 and self.on_key_rotated:
                    self.on_key_rotated(
                        self.rotator.current,
                        self.rotator.slot,
                        self.rotator.count,
                        "single key — add more keys for rotation",
                    )

                # All keys tried — wait then loop back to key 0
                log.warning(f"All keys rate-limited. Waiting {suggested_wait}s…")
                time.sleep(suggested_wait)
                self.rotator.reset()
                self._init_client(self.rotator.current)
                # _init_client already sets self._chat = None
                if self.on_key_rotated:
                    self.on_key_rotated(
                        self.rotator.current,
                        self.rotator.slot,
                        self.rotator.count,
                        "cooldown retry",
                    )
                backoff = min(backoff * 2, 60)

        raise RuntimeError("All API keys exhausted. Please add more keys or wait.")

    # ── Response safety check ─────────────────────────────────────────────────
    @staticmethod
    def _extract_text_safe(resp) -> str:
        """Extract text from a Gemini response, detecting safety blocks."""
        # Try direct .text access first
        try:
            text = resp.text
            if text:
                return text.strip()
        except ValueError as e:
            # resp.text raises ValueError when content is blocked
            err_msg = str(e)
            log.warning(f"Cannot read response text (likely blocked): {err_msg}")
            # The error message itself often contains the reason
            if "SAFETY" in err_msg.upper() or "BLOCKED" in err_msg.upper():
                log.warning("Detected safety block from ValueError message")
                return SAFETY_BLOCKED_MSG
        except AttributeError:
            pass

        # ── Helper: check a finish_reason value for blocking reasons ──
        def _is_blocked(finish_reason) -> bool:
            """Return True if finish_reason indicates a safety/recitation block."""
            if finish_reason is None:
                return False
            # String check (e.g. "SAFETY", "FinishReason.SAFETY")
            fr_str = str(finish_reason).upper()
            if "SAFETY" in fr_str:
                return True
            if "RECITATION" in fr_str:
                return True
            if "OTHER" in fr_str:   # "FinishReason.OTHER" = blocked content
                return True
            # Integer/Enum value check
            #   SAFETY=3, RECITATION=4, OTHER/blocked=5
            try:
                fr_val = int(finish_reason.value if hasattr(finish_reason, "value") else finish_reason)
                if fr_val in (3, 4, 5):
                    return True
            except (ValueError, TypeError):
                pass
            return False

        # ── Check candidate-level finish reasons ──────────────────────
        try:
            candidates = resp.candidates
            if candidates is not None:
                if len(candidates) == 0:
                    # Empty candidates list → blocked by safety filters
                    log.warning("Response blocked: no candidates returned (empty list)")
                    # Check prompt_feedback for more context
                    try:
                        pf2 = resp.prompt_feedback
                        if pf2 is not None:
                            for attr in ("block_reason", "block_reason_message", "blocked_reason"):
                                try:
                                    val = getattr(pf2, attr, None)
                                    if val is not None:
                                        log.warning(f"Prompt feedback: {attr}={val}")
                                except Exception:
                                    continue
                    except (AttributeError, TypeError):
                        pass
                    return SAFETY_BLOCKED_MSG

                finish_reason = candidates[0].finish_reason
                if _is_blocked(finish_reason):
                    log.warning(f"Response blocked by safety filter. finish_reason={finish_reason}")
                    return SAFETY_BLOCKED_MSG
                else:
                    log.warning(f"Empty response from candidate. finish_reason={finish_reason}")
                    return ""
            else:
                log.warning("Response has no candidates attribute")
        except (AttributeError, IndexError, TypeError) as e:
            log.debug(f"Candidate check failed: {e}")

        # ── Check prompt-level blocking ───────────────────────────────
        try:
            pf = resp.prompt_feedback
            if pf is not None:
                for attr in ("block_reason", "block_reason_message", "blocked_reason"):
                    try:
                        val = getattr(pf, attr, None)
                        if val is not None:
                            log.warning(f"Prompt blocked by safety filter: {attr}={val}")
                            return SAFETY_BLOCKED_MSG
                    except Exception:
                        continue
        except (AttributeError, TypeError):
            pass

        log.warning("LLM returned empty/None response with no detected safety block.")
        return ""

    def _extract_response_parts(self, resp) -> Tuple[str, Optional[Dict]]:
        """Extract text AND native function_call from response parts.

        Returns (text, tool_call_dict_or_None).
        Handles both:
          1. Native Gemini function_call parts (SDK-level tool calling)
          2. Text-based TOOL_CALL: {...} format (prompt-level tool calling)

        This replaces the pattern of calling resp.text (which silently drops
        function_call parts with a warning) followed by _parse_tool_call().
        """
        text_parts: List[str] = []
        function_call: Optional[Dict] = None

        try:
            candidates = getattr(resp, 'candidates', None)

            # No candidates → safety block or empty response
            if not candidates or len(candidates) == 0:
                return self._extract_text_safe(resp), None

            # Check finish reason for safety blocks before inspecting parts
            finish_reason = getattr(candidates[0], 'finish_reason', None)
            fr_str = str(finish_reason).upper() if finish_reason else ""
            if any(kw in fr_str for kw in ("SAFETY", "RECITATION")):
                log.warning(f"Response blocked by safety filter: {finish_reason}")
                return SAFETY_BLOCKED_MSG, None

            content = getattr(candidates[0], 'content', None)
            if content is None:
                return self._extract_text_safe(resp), None

            parts = getattr(content, 'parts', None)
            if not parts:
                return self._extract_text_safe(resp), None

            for part in parts:
                # Check for native function_call
                fc = getattr(part, 'function_call', None)
                if fc and getattr(fc, 'name', None):
                    fc_args = dict(fc.args) if getattr(fc, 'args', None) else {}
                    function_call = {"action": fc.name, "args": fc_args}
                    log.info(f"Native function_call detected: {fc.name}({list(fc_args.keys())})")
                # Check for text
                elif hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)

        except Exception as e:
            log.warning(f"Failed to extract response parts: {e}, falling back")
            return self._extract_text_safe(resp), None

        text = "\n".join(text_parts).strip()

        # If no native function_call found, try text-based TOOL_CALL: parsing
        if not function_call and text:
            function_call = self._parse_tool_call(text)
            if function_call:
                text = self._strip_tool_call(text)

        return text, function_call
    
    def _generate_config(self, **extra) -> "genai_types.GenerateContentConfig":
        """Build SDK config with native tool declarations."""
        kwargs = {
            "temperature": self.temperature,
            "safety_settings": SAFETY_SETTINGS,
            **extra,
        }
        if self.max_tokens is not None:
            kwargs["max_output_tokens"] = self.max_tokens
        # Inject native tool declarations if available
        if "tools" not in kwargs:
            decls = _get_tool_declarations()
            if decls:
                kwargs["tools"] = decls
        return genai_types.GenerateContentConfig(**kwargs)

    # ── Chat session ──────────────────────────────────────────────────────────
    def _get_chat(self):
        if self._chat is None and self._client:
            if NEW_SDK:
                self._chat = self._client.chats.create(
                    model=self.model_name,
                    config=self._generate_config(
                        system_instruction=self.system_prompt,
                    ),
                    history=self._history_cache
                )
        return self._chat

    def chat(self, message: str) -> Tuple[str, Optional[Dict]]:
        """Send text message, return (response_text, tool_call_or_None)."""
        if not self.rotator.count:
            return "Please add a Gemini API key in Settings.", None

        log.debug(f"chat → {message[:100]}")
        t0 = time.time()

        def _do():
            if NEW_SDK:
                ch = self._get_chat()
                if ch is None:
                    raise RuntimeError("Client not initialised.")
                resp = ch.send_message(message)
                return resp  # Return raw response for part-level inspection
            else:
                model = genai_legacy.GenerativeModel(
                    self.model_name, system_instruction=self.system_prompt,
                    safety_settings=SAFETY_SETTINGS)
                if self._chat is None:
                    self._chat = model.start_chat()
                resp = self._chat.send_message(message)
                return self._extract_text_safe(resp)  # Legacy: text-only

        try:
            result = self._call_with_rotation(_do)
            elapsed = time.time() - t0

            if isinstance(result, str):
                # Legacy SDK path — result is already extracted text
                text = result
                tool_call = self._parse_tool_call(text)
                if tool_call:
                    text = self._strip_tool_call(text)
            else:
                # New SDK path — result is the raw response object
                text, tool_call = self._extract_response_parts(result)

            log.info(f"LLM response in {elapsed:.2f}s | tool={tool_call.get('action') if tool_call else None} | {len(text)} chars")
            return text, tool_call
        except Exception as e:
            err_str = str(e).lower()
            # Detect safety filter blocks
            if any(kw in err_str for kw in ['safety', 'blocked', 'filter', 'civic', 'recitation']):
                log.warning(f"Safety filter triggered: {e}")
                # Auto-retry with a softened prompt
                try:
                    retry_msg = (
                        f"[System: previous response was safety-filtered. "
                        f"Please provide a helpful, safe response to the user's request. "
                        f"The user asked: {message[:500]}]"
                    )
                    result = self._call_with_rotation(lambda: (
                        self._get_chat().send_message(retry_msg) if NEW_SDK
                        else self._chat.send_message(retry_msg)
                    ))
                    if isinstance(result, str):
                        return result, self._parse_tool_call(result)
                    else:
                        text, tool_call = self._extract_response_parts(result)
                        return text, tool_call
                except Exception:
                    pass
                return SAFETY_BLOCKED_MSG, None
            log.error(f"chat failed: {e}")
            return f"Error: {e}", None

    def chat_tool_result(self, tool_name: str, result: str) -> Tuple[str, Optional[Dict]]:
        """Send a FunctionResponse back to the chat after executing a tool.

        This maintains proper function_call → function_response pairing in the
        chat history, so the LLM sees structured tool results instead of plain text.
        Falls back to a regular chat message if native calling isn't available.
        """
        if not self.rotator.count:
            return "Please add a Gemini API key in Settings.", None

        t0 = time.time()

        def _do():
            if NEW_SDK:
                ch = self._get_chat()
                if ch is None:
                    raise RuntimeError("Client not initialised.")
                # Send as a proper FunctionResponse part
                try:
                    func_response = genai_types.Part.from_function_response(
                        name=tool_name,
                        response={"result": result[:3000]},
                    )
                    resp = ch.send_message(func_response)
                    return resp
                except (AttributeError, TypeError) as e:
                    # SDK version may not support Part.from_function_response
                    log.warning(f"FunctionResponse not supported: {e}, falling back to text")
                    fallback_msg = (
                        f"Tool `{tool_name}` returned:\n```\n{result}\n```\n"
                        f"Continue with the task. If done, give the final response."
                    )
                    resp = ch.send_message(fallback_msg)
                    return resp
            else:
                # Legacy SDK — send as text
                fallback_msg = (
                    f"Tool `{tool_name}` returned:\n```\n{result}\n```\n"
                    f"Continue with the task. If done, give the final response."
                )
                if self._chat is None:
                    raise RuntimeError("No active chat session.")
                resp = self._chat.send_message(fallback_msg)
                return self._extract_text_safe(resp)

        try:
            resp = self._call_with_rotation(_do)
            elapsed = time.time() - t0

            if isinstance(resp, str):
                text = resp
                tool_call = self._parse_tool_call(text)
                if tool_call:
                    text = self._strip_tool_call(text)
            else:
                text, tool_call = self._extract_response_parts(resp)

            log.info(f"Tool result response in {elapsed:.2f}s | tool={tool_call.get('action') if tool_call else None} | {len(text)} chars")
            return text, tool_call
        except Exception as e:
            log.error(f"chat_tool_result failed: {e}")
            return f"Error: {e}", None

    # ── Streaming variants ─────────────────────────────────────────────────────

    def chat_stream(self, message: str, on_chunk=None) -> Tuple[str, Optional[Dict]]:
        """Send text message with streaming. Calls on_chunk(text_delta) per chunk.

        Returns (full_text, tool_call_or_None) — same contract as chat().
        Falls back to non-streaming chat() on any streaming error.
        """
        if not self.rotator.count:
            return "Please add a Gemini API key in Settings.", None

        if not NEW_SDK:
            # Legacy SDK has no streaming chat support — fall back
            return self.chat(message)

        log.debug(f"chat_stream → {message[:100]}")
        t0 = time.time()

        def _do():
            ch = self._get_chat()
            if ch is None:
                raise RuntimeError("Client not initialised.")
            return ch.send_message_stream(message)

        try:
            stream = self._call_with_rotation(_do)
            text_parts: List[str] = []
            last_chunk = None

            for chunk in stream:
                last_chunk = chunk
                # Extract incremental text from this chunk
                delta = ""
                try:
                    delta = chunk.text or ""
                except (ValueError, AttributeError):
                    # chunk.text may raise ValueError if blocked; try parts
                    try:
                        for part in chunk.candidates[0].content.parts:
                            if hasattr(part, 'text') and part.text:
                                delta += part.text
                    except Exception:
                        pass

                if delta:
                    text_parts.append(delta)
                    if on_chunk:
                        on_chunk(delta)

            # Reconstruct final text
            full_text = "".join(text_parts).strip()

            # Extract function_call from the accumulated response.
            # After streaming completes, the chat history is updated by the SDK.
            # We inspect the last chunk for function_call parts.
            function_call = None
            try:
                if last_chunk and hasattr(last_chunk, 'candidates') and last_chunk.candidates:
                    content = getattr(last_chunk.candidates[0], 'content', None)
                    if content and hasattr(content, 'parts') and content.parts:
                        for part in content.parts:
                            fc = getattr(part, 'function_call', None)
                            if fc and getattr(fc, 'name', None):
                                fc_args = dict(fc.args) if getattr(fc, 'args', None) else {}
                                function_call = {"action": fc.name, "args": fc_args}
                                log.info(f"Stream: native function_call detected: {fc.name}")
                                break
            except Exception as e:
                log.debug(f"Stream function_call extraction failed: {e}")

            # Fallback: check text-based TOOL_CALL: pattern
            if not function_call and full_text:
                function_call = self._parse_tool_call(full_text)
                if function_call:
                    full_text = self._strip_tool_call(full_text)

            elapsed = time.time() - t0
            log.info(f"LLM stream response in {elapsed:.2f}s | tool={function_call.get('action') if function_call else None} | {len(full_text)} chars")
            return full_text, function_call

        except Exception as e:
            log.warning(f"chat_stream failed ({e}), falling back to chat()")
            return self.chat(message)

    def chat_tool_result_stream(self, tool_name: str, result: str,
                                on_chunk=None) -> Tuple[str, Optional[Dict]]:
        """Send a FunctionResponse with streaming. Same contract as chat_tool_result().

        Falls back to non-streaming chat_tool_result() on error.
        """
        if not self.rotator.count:
            return "Please add a Gemini API key in Settings.", None

        if not NEW_SDK:
            return self.chat_tool_result(tool_name, result)

        t0 = time.time()

        def _do():
            ch = self._get_chat()
            if ch is None:
                raise RuntimeError("Client not initialised.")
            try:
                func_response = genai_types.Part.from_function_response(
                    name=tool_name,
                    response={"result": result[:3000]},
                )
                return ch.send_message_stream(func_response)
            except (AttributeError, TypeError) as e:
                log.warning(f"FunctionResponse not supported for stream: {e}, text fallback")
                fallback_msg = (
                    f"Tool `{tool_name}` returned:\n```\n{result}\n```\n"
                    f"Continue with the task. If done, give the final response."
                )
                return ch.send_message_stream(fallback_msg)

        try:
            stream = self._call_with_rotation(_do)
            text_parts: List[str] = []
            last_chunk = None

            for chunk in stream:
                last_chunk = chunk
                delta = ""
                try:
                    delta = chunk.text or ""
                except (ValueError, AttributeError):
                    try:
                        for part in chunk.candidates[0].content.parts:
                            if hasattr(part, 'text') and part.text:
                                delta += part.text
                    except Exception:
                        pass

                if delta:
                    text_parts.append(delta)
                    if on_chunk:
                        on_chunk(delta)

            full_text = "".join(text_parts).strip()

            # Extract function_call from last chunk
            function_call = None
            try:
                if last_chunk and hasattr(last_chunk, 'candidates') and last_chunk.candidates:
                    content = getattr(last_chunk.candidates[0], 'content', None)
                    if content and hasattr(content, 'parts') and content.parts:
                        for part in content.parts:
                            fc = getattr(part, 'function_call', None)
                            if fc and getattr(fc, 'name', None):
                                fc_args = dict(fc.args) if getattr(fc, 'args', None) else {}
                                function_call = {"action": fc.name, "args": fc_args}
                                log.info(f"Stream tool result: native function_call: {fc.name}")
                                break
            except Exception as e:
                log.debug(f"Stream tool result function_call extraction failed: {e}")

            if not function_call and full_text:
                function_call = self._parse_tool_call(full_text)
                if function_call:
                    full_text = self._strip_tool_call(full_text)

            elapsed = time.time() - t0
            log.info(f"Tool result stream in {elapsed:.2f}s | tool={function_call.get('action') if function_call else None} | {len(full_text)} chars")
            return full_text, function_call

        except Exception as e:
            log.warning(f"chat_tool_result_stream failed ({e}), falling back")
            return self.chat_tool_result(tool_name, result)

    def chat_with_image(self, message: str, image_bytes: bytes,
                        mime_type: str = "image/png") -> Tuple[str, Optional[Dict]]:
        """Send message + image via chat session for context-aware analysis."""
        if not self.rotator.count:
            return "Please add a Gemini API key in Settings.", None

        def _do():
            if NEW_SDK and self._client:
                # Use chat session for context awareness (P4 fix)
                ch = self._get_chat()
                if ch:
                    try:
                        parts = [
                            genai_types.Part.from_text(text=message),
                            genai_types.Part.from_bytes(
                                data=image_bytes, mime_type=mime_type),
                        ]
                        resp = ch.send_message(parts)
                        return resp
                    except Exception as e:
                        log.warning(f"Chat session image failed: {e}, falling back to stateless")
                # Fallback: stateless generate_content
                resp = self._client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        genai_types.Part.from_text(
                            text=self.system_prompt + "\n\n" + message),
                        genai_types.Part.from_bytes(
                            data=image_bytes, mime_type=mime_type),
                    ],
                    config=self._generate_config(),
                )
                return resp
            else:
                model = genai_legacy.GenerativeModel(
                    self.model_name, system_instruction=self.system_prompt,
                    safety_settings=SAFETY_SETTINGS)
                resp = model.generate_content(
                    [message, {"mime_type": mime_type, "data": image_bytes}]
                )
                return self._extract_text_safe(resp)  # Legacy: text-only

        try:
            result = self._call_with_rotation(_do)
            if isinstance(result, str):
                text = result
                tool_call = self._parse_tool_call(text)
                if tool_call:
                    text = self._strip_tool_call(text)
            else:
                text, tool_call = self._extract_response_parts(result)
            return text, tool_call
        except Exception as e:
            return f"Error: {e}", None

    def analyze_file(self, prompt: str, file_content: str) -> str:
        """Analyze extracted text from a file."""
        if not self.rotator.count:
            return "Please add a Gemini API key in Settings."

        full_prompt = f"{prompt}\n\n--- FILE CONTENT ---\n{file_content[:50000]}"

        def _do():
            if NEW_SDK and self._client:
                resp = self._client.models.generate_content(
                    model=self.model_name,
                    contents=full_prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        temperature=self.temperature,
                        max_output_tokens=min(self.max_tokens, 4096) if self.max_tokens is not None else 4096,
                        safety_settings=SAFETY_SETTINGS,
                    )
                )
                return self._extract_text_safe(resp)
            else:
                model = genai_legacy.GenerativeModel(
                    self.model_name, system_instruction=self.system_prompt,
                    safety_settings=SAFETY_SETTINGS)
                resp = model.generate_content(full_prompt)
                return self._extract_text_safe(resp)

        try:
            return self._call_with_rotation(_do)
        except Exception as e:
            return f"Error analyzing file: {e}"

    # ── Tool call parsing ─────────────────────────────────────────────────────
    def _parse_tool_call(self, text: str) -> Optional[Dict]:
        """Extract a tool call from LLM response.

        Handles two formats:
        1. TOOL_CALL: {...} on its own line (primary format)
        2. ```json\n{...}\n``` code block (fallback)
        Returns None if no valid tool call found.
        """
        # Format 1: TOOL_CALL: prefix
        tc_idx = text.find("TOOL_CALL:")
        if tc_idx != -1:
            json_start = text.find("{", tc_idx)
            if json_start != -1:
                result = self._parse_json_balanced(text, json_start)
                if result is not None:
                    return result

        # Format 2: ```json code block (fallback)
        return self._parse_json_code_block(text)

    def _parse_json_balanced(self, text: str, start: int) -> Optional[Dict]:
        """Parse a JSON object starting at the first '{' at position start,
        handling nested braces correctly."""
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict) and "action" in obj:
                            return obj
                        return None
                    except json.JSONDecodeError:
                        return None
        return None

    def _parse_json_code_block(self, text: str) -> Optional[Dict]:
        """Scan for ```json ... ``` code blocks and return the first
        valid tool call found."""
        search_start = 0
        while True:
            fence_start = text.find("```json", search_start)
            if fence_start == -1:
                return None

            # Content starts after the fence and optional newline
            content_start = fence_start + 7  # len("```json")
            if content_start < len(text) and text[content_start] == "\n":
                content_start += 1  # skip the newline after ```json

            # Find closing fence
            fence_end = text.find("```", content_start)
            if fence_end == -1:
                return None

            json_str = text[content_start:fence_end].strip()

            # Must start with '{' - otherwise skip this code block
            if not json_str.startswith("{"):
                search_start = fence_end + 3
                continue

            # Check this isn't inside a tool result message
            prefix = text[max(0, fence_start - 60):fence_start].strip()
            if prefix.endswith("returned:") or "Tool `" in prefix:
                # This is a tool result being quoted, not a new tool call
                search_start = fence_end + 3
                continue

            try:
                obj = json.loads(json_str)
                if isinstance(obj, dict) and "action" in obj:
                    return obj
            except json.JSONDecodeError:
                pass

            search_start = fence_end + 3

    def _strip_tool_call(self, text: str) -> str:
        """Remove the tool call portion from response text, leaving only
        the natural language part."""
        # Try Format 1: TOOL_CALL: prefix
        idx = text.find("TOOL_CALL:")
        if idx != -1:
            # Find the end of the JSON object
            json_start = text.find("{", idx)
            if json_start != -1:
                depth = 0
                for i, ch in enumerate(text[json_start:], json_start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            # Strip from TOOL_CALL to end of JSON
                            before = text[:idx].strip()
                            after = text[i + 1:].strip()
                            combined = f"{before} {after}".strip()
                            return combined if combined else before
            return text[:idx].strip()

        # Try Format 2: ```json code block (fallback)
        fence_start = text.find("```json")
        if fence_start != -1:
            before = text[:fence_start].strip()
            # Find closing fence
            fence_end = text.find("```", fence_start + 7)
            if fence_end != -1:
                after = text[fence_end + 3:].strip()
                combined = f"{before} {after}".strip()
                return combined if combined else before
            return before

        return text.strip()

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def is_configured(self) -> bool:
        return bool(self.rotator.current)

    @property
    def active_key_display(self) -> str:
        """Short display string for current key."""
        k = self.rotator.current
        if not k:
            return "No key set"
        return f"Key {self.rotator.slot}/{self.rotator.count}  ({k[:8]}…)"

    def list_models(self) -> List[str]:
        return [
            "gemini-3.1-pro-preview",
            "gemini-2.5-pro",
            "gemini-1.5-pro",
            "gemini-3.5-flash",
            "gemini-3-flash",
            "gemini-2.5-flash",
            "gemini-1.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
        ]
