"""
MARK — Agentic Planner (ReAct Loop)
Observe → Think → Act → Observe → … until task complete or max steps reached.

Integration:
  - Loads GEMINI.md persona + user profile from Nemesi at startup
  - Reads SHARED_SESSION.json for cross-instance context
  - Multi-step tool calls with full result feedback loop
"""

import json
import time
from pathlib import Path
from typing import Optional, List, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

from core.logger import get_logger
from core.llm import LLMClient
from core.memory import Memory
from agent.tools import (
    TOOL_DESCRIPTIONS, execute_tool,
    GEMINI_DIR, NEMESI_DIR, MEMORY_DIR, SHARED_SESSION
)
from actions.screen import capture_screen, capture_webcam, get_screen_thumbnail
from actions.file_handler import extract_text, get_image_bytes, get_image_mime, detect_file_type

log = get_logger("planner")

MAX_STEPS       = 10   # max tool calls per request
MAX_RESULT_LEN  = 3000  # truncate long tool results


# ── Load .gemini context once at import ───────────────────────────────────────
def _load_gemini_context() -> str:
    """Load GEMINI.md persona and user profile for injection into system prompt."""
    parts = []

    gemini_md = GEMINI_DIR / "GEMINI.md"
    if gemini_md.exists():
        try:
            parts.append("## Your Configuration (from GEMINI.md)\n" +
                         gemini_md.read_text(encoding="utf-8", errors="replace")[:3000])
        except Exception:
            pass

    profile = NEMESI_DIR / "AI-Synthesized-User-Profile.md"
    if profile.exists():
        try:
            parts.append("## User Profile (from Nemesi)\n" +
                         profile.read_text(encoding="utf-8", errors="replace")[:2000])
        except Exception:
            pass

    session = {}
    if SHARED_SESSION.exists():
        try:
            session = json.loads(SHARED_SESSION.read_text())
            if session:
                s = json.dumps({k: v for k, v in session.items()
                                if not k.startswith("_")}, indent=2)
                parts.append(f"## Shared Session State\n```json\n{s}\n```")
        except Exception:
            pass

    return "\n\n---\n\n".join(parts) if parts else ""


GEMINI_CONTEXT = _load_gemini_context()
log.info(f"Loaded .gemini context: {len(GEMINI_CONTEXT)} chars")


# ── System Prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are MARK, an advanced agentic AI assistant running on the user's computer.
You have direct access to their system and can execute tools to complete tasks.

{gemini_context}

## Memory Context
{memory_context}

## How You Work
You operate in a ReAct loop:
1. THINK about what needs to be done
2. ACT by calling one tool at a time (emit JSON)
3. OBSERVE the result
4. Repeat until the task is complete
5. Give a final natural language response

## Tool Calling
When you need to perform an action, emit EXACTLY one JSON object on its own line starting with TOOL_CALL: like this (no markdown fences):
TOOL_CALL: {{"action": "tool_name", "args": {{"key": "value"}}}}
Only emit ONE tool call per response. After seeing the result, decide the next step.
When done, respond naturally without a TOOL_CALL: line.

## Rules
- Be autonomous: don't ask for confirmation on simple tasks, just do them
- Be efficient: chain tools to complete complex tasks
- Be transparent: briefly explain what you're doing before each tool call
- When writing files, use absolute paths
- For commands, prefer PowerShell on Windows

## Voice Output (TTS)
Your text responses are read aloud by a text-to-speech engine. Follow these rules:
- Speak conversationally, like you're talking to a friend — not writing a textbook
- Never write code examples in your final response unless the user explicitly asks for code
- Instead of "An SDK (Software Development Kit) is...", say "An SDK is basically a developer's toolkit that..."
- Don't use parenthetical abbreviations like (API) or (SDK) — just use the term naturally
- Avoid bullet-point lists when a short paragraph works
- If you need to explain something technical, use analogies and simple language
- Keep responses concise — long responses are painful to listen to

{tool_descriptions}
"""


class PlannerWorker(QThread):
    response_ready  = pyqtSignal(str)
    tool_executed   = pyqtSignal(str, str)   # (icon+name, result_summary)
    thinking        = pyqtSignal(bool)
    step_update     = pyqtSignal(str)         # live "Thinking step N…" updates
    error_occurred  = pyqtSignal(str)

    def __init__(self, llm: LLMClient, memory: Memory, parent=None):
        super().__init__(parent)
        self.llm     = llm
        self.memory  = memory
        self._pending: list = []
        self._running = True
        self._refresh_system_prompt()

    def _refresh_system_prompt(self):
        """Rebuild system prompt with fresh memory + .gemini context."""
        # Reload shared session on each request
        gemini_ctx = _load_gemini_context()
        memory_ctx = self.memory.build_context_summary()
        prompt = SYSTEM_PROMPT.format(
            gemini_context=gemini_ctx,
            memory_context=memory_ctx or "No prior context.",
            tool_descriptions=TOOL_DESCRIPTIONS,
        )
        self.llm.update_system_prompt(prompt)

    def submit(self, text: str, image_bytes: bytes = None, mime: str = "image/png"):
        self._pending.append((text, image_bytes, mime))

    def run(self):
        while self._running:
            if self._pending:
                task = self._pending.pop(0)
                self._process(*task)
            else:
                self.msleep(50)

    # ── Core agentic loop ──────────────────────────────────────────────────────
    def _process(self, text: str, image_bytes: Optional[bytes], mime: str):
        self.thinking.emit(True)
        log.info(f"User: \"{text[:120]}\"")

        self._refresh_system_prompt()
        self.memory.add_message("user", text)

        # Auto-capture screen/webcam if mentioned
        low = text.lower()
        if image_bytes is None:
            if any(w in low for w in ["screenshot","screen","what do you see","look at my screen","describe what"]):
                image_bytes = get_screen_thumbnail()
                mime = "image/png"
                self.tool_executed.emit("📸 Screenshot", "Captured screen.")
            elif any(w in low for w in ["webcam","camera","see me","my face","look at me"]):
                image_bytes = capture_webcam()
                mime = "image/jpeg"
                self.tool_executed.emit("📷 Webcam", "Captured webcam.")

        # Build the conversation for this turn
        # First call includes the user message (+ image if any)
        current_message = text
        current_image   = image_bytes
        current_mime    = mime
        accumulated_response = ""
        steps = 0

        try:
            while steps < MAX_STEPS:
                steps += 1
                self.step_update.emit(f"Thinking… (step {steps})" if steps > 1 else "Thinking…")

                # Call LLM
                if current_image:
                    raw, tool_call = self.llm.chat_with_image(current_message, current_image, current_mime)
                    current_image = None   # image only on first call
                else:
                    raw, tool_call = self.llm.chat(current_message)

                log.info(f"Step {steps}: tool={tool_call.get('action') if tool_call else None} | {len(raw)} chars")

                # Handle empty/blocked responses
                if not raw and not tool_call:
                    log.warning(f"Step {steps}: empty response (possible safety filter)")
                    accumulated_response = (
                        "I'm sorry, my response was blocked by safety filters. "
                        "Please try rephrasing your request."
                    )
                    break

                if not tool_call:
                    # No more tools — this is the final answer
                    accumulated_response = raw
                    break

                # ── Execute the tool ──────────────────────────────────────────
                action = tool_call.get("action", "")
                args   = tool_call.get("args", {})

                # Memory shortcuts handled locally
                if action == "remember":
                    key, val = args.get("key",""), args.get("value","")
                    self.memory.set_pref(key, val)
                    tool_result = f"Stored: {key} = {val}"
                    self.tool_executed.emit("🧠 Remember", tool_result)

                elif action == "recall":
                    key = args.get("key","")
                    val = self.memory.get_pref(key, "(not found)")
                    tool_result = f"{key}: {val}"
                    self.tool_executed.emit("🧠 Recall", tool_result)

                elif action == "take_screenshot":
                    img = get_screen_thumbnail()
                    if img:
                        # Feed screenshot back to LLM in next step
                        tool_result = "[screenshot captured — analyzing…]"
                        current_image = img
                        current_mime  = "image/png"
                    else:
                        tool_result = "Could not capture screenshot."
                    self.tool_executed.emit("📸 Screenshot", "Captured.")

                elif action == "capture_webcam":
                    img = capture_webcam()
                    if img:
                        tool_result = "[webcam captured — analyzing…]"
                        current_image = img
                        current_mime  = "image/jpeg"
                    else:
                        tool_result = "Could not capture webcam."
                    self.tool_executed.emit("📷 Webcam", "Captured.")

                else:
                    tool_result = execute_tool(action, args)
                    icon_map = {
                        "run_command":"⚡","read_file":"📄","write_file":"📝",
                        "list_files":"📋","open_app":"🚀","type_text":"⌨️",
                        "open_file":"📂","web_search":"🔍","remember_note":"🧠",
                        "recall_notes":"🔎","update_shared_session":"🔄",
                        "read_user_profile":"👤",
                    }
                    icon = icon_map.get(action, "⚙️")
                    summary = str(tool_result)[:120] + ("…" if len(str(tool_result)) > 120 else "")
                    self.tool_executed.emit(f"{icon} {action}", summary)

                # Truncate very long results before feeding back
                if len(str(tool_result)) > MAX_RESULT_LEN:
                    tool_result = str(tool_result)[:MAX_RESULT_LEN] + "\n… [truncated]"

                # Feed result back as next message
                current_message = (
                    f"Tool `{action}` returned:\n```\n{tool_result}\n```\n"
                    f"Continue with the task. If done, give the final response without a tool call."
                )
                log.debug(f"Feeding result of '{action}' back to LLM")

            else:
                # Hit step limit
                accumulated_response = (
                    "I've completed the maximum number of steps. Here's what I did:\n" +
                    accumulated_response
                )
                log.warning(f"Hit MAX_STEPS ({MAX_STEPS}) limit")

            # Save + emit final response
            self.memory.add_message("model", accumulated_response)
            self.response_ready.emit(accumulated_response)
            log.info(f"Done in {steps} step(s): \"{accumulated_response[:80]}\"")

        except Exception as e:
            log.error(f"Planner error: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
            self.response_ready.emit(f"Sorry, I ran into an error: {e}")
        finally:
            self.thinking.emit(False)
            self.step_update.emit("")

    # ── File analysis ──────────────────────────────────────────────────────────
    def process_file(self, file_path: str, user_prompt: str = ""):
        ftype = detect_file_type(file_path)
        prompt = user_prompt or "Please analyze this file and provide a summary."
        self.thinking.emit(True)
        try:
            if ftype == "image":
                img_bytes = get_image_bytes(file_path)
                mime      = get_image_mime(file_path)
                response, _ = self.llm.chat_with_image(prompt, img_bytes, mime) if img_bytes else ("Could not read image.", None)
            else:
                text_content, _ = extract_text(file_path)
                response = self.llm.analyze_file(prompt, text_content)

            self.memory.add_message("user", f"[File: {file_path}] {prompt}")
            self.memory.add_message("model", response)
            self.response_ready.emit(response)
        except Exception as e:
            self.error_occurred.emit(str(e))
            self.response_ready.emit(f"Error analyzing file: {e}")
        finally:
            self.thinking.emit(False)

    def stop(self):
        self._running = False
        self.wait(3000)
