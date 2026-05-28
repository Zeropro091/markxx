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
        return [
            genai_types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="OFF",
            ),
            genai_types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="OFF",
            ),
            genai_types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="OFF",
            ),
            genai_types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="OFF",
            ),
        ]
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


SYSTEM_PROMPT_TEMPLATE = """You are MARK, an advanced personal AI assistant — calm, precise, and highly capable. You are like J.A.R.V.I.S. from Iron Man. You run entirely on the user's machine.

{memory_context}

## Capabilities
You can:
- Have natural conversations and answer questions
- Control the computer: open apps, manage files, run commands
- Take screenshots and analyze what's on screen
- Analyze uploaded files (PDFs, images, documents)
- Remember user preferences and projects persistently
- Execute multi-step tasks autonomously

## Tool Calling
When you need to perform a computer action, emit EXACTLY one JSON block on its own line like this (no markdown fences):
TOOL_CALL: {{"action": "open_app", "args": {{"app": "notepad"}}}}

Available actions:
- open_app: {{"app": "string"}} — open an application by name
- run_command: {{"cmd": "string", "shell": true/false}} — run a terminal command
- type_text: {{"text": "string"}} — type text at cursor
- take_screenshot: {{}} — capture the current screen
- capture_webcam: {{}} — capture from webcam
- open_file: {{"path": "string"}} — open a file
- create_file: {{"path": "string", "content": "string"}} — create/write a file
- delete_file: {{"path": "string"}} — delete a file
- list_files: {{"path": "string"}} — list directory contents
- move_file: {{"src": "string", "dst": "string"}} — move/rename a file
- web_search: {{"query": "string"}} — search the web
- remember: {{"key": "string", "value": "string"}} — store a preference
- recall: {{"key": "string"}} — recall a stored preference

## Rules
- Be concise but complete
- When performing actions, briefly confirm what you're doing
- If a task needs multiple steps, list them then execute
- Never make up file paths — ask if unsure
- Use the user's name when you know it
"""


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

        # Build key pool
        all_keys = [api_key] + (extra_keys or [])
        self.rotator = KeyRotator(all_keys)
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
        self._chat = None   # reset chat session

    def configure(self, api_key: str, model: str = None, extra_keys: List[str] = None):
        if model:
            self.model_name = model
        all_keys = [api_key] + (extra_keys or [])
        self.rotator.load(all_keys)
        if self.rotator.current:
            self._init_client(self.rotator.current)

    def reset_chat(self):
        self._chat = None

    def update_system_prompt(self, prompt: str):
        self.system_prompt = prompt
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
                is_rate_limit = "429" in msg or "RESOURCE_EXHAUSTED" in msg

                if not is_rate_limit:
                    log.error(f"LLM error (attempt {attempt+1}): {msg[:200]}")
                    raise

                log.warning(f"Rate limit hit on key slot {self.rotator.slot}/{self.rotator.count} (attempt {attempt+1})")

                # Parse server-suggested wait time
                m = re.search(r"retry[^0-9]*(\d+)", msg, re.I)
                suggested_wait = int(m.group(1)) + 1 if m else backoff

                # Try rotating to next key first (instant, no wait)
                rotated = self.rotator.rotate()
                if rotated:
                    log.info(f"Key rotated → slot {self.rotator.slot}/{self.rotator.count}")
                    self._init_client(self.rotator.current)
                    if self.on_key_rotated:
                        self.on_key_rotated(
                            self.rotator.current,
                            self.rotator.slot,
                            self.rotator.count,
                            "quota exhausted"
                        )
                    continue

                # All keys tried — wait then loop back to key 0
                log.warning(f"All keys rate-limited. Waiting {suggested_wait}s…")
                time.sleep(suggested_wait)
                self.rotator.reset()
                self._init_client(self.rotator.current)
                self._chat = None
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
    
    # ── Chat session ──────────────────────────────────────────────────────────
    def _get_chat(self):
        if self._chat is None and self._client:
            if NEW_SDK:
                self._chat = self._client.chats.create(
                    model=self.model_name,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        temperature=self.temperature,
                        max_output_tokens=self.max_tokens,
                        safety_settings=SAFETY_SETTINGS,
                    )
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
                return self._extract_text_safe(resp)
            else:
                model = genai_legacy.GenerativeModel(
                    self.model_name, system_instruction=self.system_prompt,
                    safety_settings=SAFETY_SETTINGS)
                if self._chat is None:
                    self._chat = model.start_chat()
                resp = self._chat.send_message(message)
                return self._extract_text_safe(resp)

        try:
            text = self._call_with_rotation(_do)
            elapsed = time.time() - t0
            tool_call = self._parse_tool_call(text)
            log.info(f"LLM response in {elapsed:.2f}s | tool={tool_call.get('action') if tool_call else None} | {len(text)} chars")
            if tool_call:
                text = self._strip_tool_call(text)
            return text, tool_call
        except Exception as e:
            log.error(f"chat failed: {e}")
            return f"Error: {e}", None

    def chat_with_image(self, message: str, image_bytes: bytes,
                        mime_type: str = "image/png") -> Tuple[str, Optional[Dict]]:
        """Send message + image."""
        if not self.rotator.count:
            return "Please add a Gemini API key in Settings.", None

        def _do():
            if NEW_SDK and self._client:
                resp = self._client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        genai_types.Part.from_text(
                            text=self.system_prompt + "\n\n" + message),
                        genai_types.Part.from_bytes(
                            data=image_bytes, mime_type=mime_type),
                    ],
                    config=genai_types.GenerateContentConfig(
                        temperature=self.temperature,
                        max_output_tokens=self.max_tokens,
                        safety_settings=SAFETY_SETTINGS,
                    )
                )
                return self._extract_text_safe(resp)
            else:
                model = genai_legacy.GenerativeModel(
                    self.model_name, system_instruction=self.system_prompt,
                    safety_settings=SAFETY_SETTINGS)
                resp = model.generate_content(
                    [message, {"mime_type": mime_type, "data": image_bytes}]
                )
                return self._extract_text_safe(resp)

        try:
            text = self._call_with_rotation(_do)
            tool_call = self._parse_tool_call(text)
            if tool_call:
                text = self._strip_tool_call(text)
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
