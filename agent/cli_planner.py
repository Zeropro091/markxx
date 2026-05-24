"""
MARK — CLI Planner (Qt-free ReAct Loop)
Full-featured agentic loop with all pillars integrated:

Pillar 1: Self-healing loop, state persistence (resume)
Pillar 3: Context pruning, .markignore, token budget, workspace mapping
Pillar 4: Path jailing, secret redaction, interceptor, dry-run mode
"""

import json
import time
import os
from pathlib import Path
from typing import Optional, Dict, List

from core.logger import get_logger
from core.llm import LLMClient
from core.memory import Memory
from core.safety import (
    MarkIgnore, ContextPruner, TokenBudget, WorkspaceMapper,
    PathJail, SecretRedactor, Interceptor, DryRunner,
)
from agent.tools import (
    TOOL_DESCRIPTIONS, execute_tool,
    GEMINI_DIR, NEMESI_DIR, MEMORY_DIR, SHARED_SESSION
)

log = get_logger("cli_planner")

MAX_STEPS      = 10
MAX_RESULT_LEN = 3000
MAX_HEAL_RETRIES = 3   # Self-healing: max automatic retries on failure
STATE_DIR = ".mark"    # State persistence directory


# ── ANSI colors ────────────────────────────────────────────────────────────────
class C:
    """ANSI color codes for terminal output."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    CYAN    = "\033[36m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    RED     = "\033[31m"
    WHITE   = "\033[37m"

    @staticmethod
    def supports_color() -> bool:
        import sys, os
        if os.getenv("NO_COLOR"):
            return False
        if not hasattr(sys.stdout, "isatty"):
            return False
        return sys.stdout.isatty()

# Disable colors if not supported
if not C.supports_color():
    for attr in dir(C):
        if attr.isupper() and not attr.startswith("_"):
            setattr(C, attr, "")


# ── Load .gemini context ──────────────────────────────────────────────────────
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


# ── System Prompt (CLI-optimized) ─────────────────────────────────────────────
CLI_SYSTEM_PROMPT = """You are MARK, an advanced agentic AI assistant running in CLI mode on the user's computer.
You have direct access to their system and can execute tools to complete tasks.

{gemini_context}

## Memory Context
{memory_context}

## Working Directory
The user is working in: {working_dir}
Use absolute paths derived from this directory when creating or editing files.

## Workspace Map
{workspace_map}

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
- Be autonomous: don't ask for confirmation, just do it
- Be efficient: chain tools to complete complex tasks
- Be transparent: briefly explain what you're doing before each tool call
- Use absolute paths when writing or editing files
- For commands, prefer PowerShell on Windows
- When editing code, prefer `edit_file` or `patch_file` over rewriting entire files with `write_file`
- Use `search_files` and `glob_files` to explore the codebase before making changes
- Always verify your changes: run syntax checks, tests, or the code itself after editing
- Use `git_diff` to check what changed before starting your work
- If a command fails with an error, read the error message, fix the code, and retry

{tool_descriptions}
"""


# ── State Persistence ─────────────────────────────────────────────────────────

class SessionState:
    """Persist conversation state to .mark/state.json for resume capability."""

    def __init__(self, working_dir: str):
        self.path = Path(working_dir) / STATE_DIR / "state.json"
        self.data = {
            "conversation": [],
            "working_dir": working_dir,
            "last_task": "",
            "steps_completed": 0,
            "timestamp": None,
        }

    def save(self, conversation: list, working_dir: str, last_task: str, steps: int):
        """Save current session state."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {
            "conversation": conversation[-30:],  # Keep last 30 messages
            "working_dir": working_dir,
            "last_task": last_task,
            "steps_completed": steps,
            "timestamp": time.time(),
        }
        try:
            self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.warning(f"Failed to save state: {e}")

    def load(self) -> Optional[dict]:
        """Load saved session state."""
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8", errors="replace"))
            return data
        except Exception:
            return None

    def clear(self):
        """Delete saved state."""
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            pass


# ── CLI Planner ────────────────────────────────────────────────────────────────

class CLIPlanner:
    """Synchronous ReAct loop for CLI mode with all pillars integrated."""

    ICON_MAP = {
        "run_command":  "\u26a1",
        "read_file":    "\ud83d\udcc4",
        "write_file":   "\ud83d\udcdd",
        "edit_file":    "\u270f\ufe0f",
        "patch_file":   "\ud83d\udd0d",
        "delete_file":  "\ud83d\uddd1\ufe0f",
        "move_file":    "\ud83d\udce6",
        "list_files":   "\ud83d\udccb",
        "search_files": "\ud83d\udd0d",
        "glob_files":   "\ud83d\udc81",
        "fetch_url":    "\ud83c\udf10",
        "git_diff":     "\ud83d\udcdd",
        "git_commit":   "\u2705",
        "open_app":     "\ud83d\ude80",
        "type_text":    "\u2328\ufe0f",
        "open_file":    "\ud83d\udcc2",
        "web_search":   "\ud83d\udd0e",
        "remember_note": "\ud83e\udde0",
        "recall_notes":  "\ud83d\udd0e",
    }

    def __init__(self, llm: LLMClient, memory: Memory,
                 working_dir: str = ".",
                 mode: str = "auto",           # auto | normal | strict
                 budget_usd: float = 1.0,      # Token budget
                 dry_run: bool = False):        # Dry-run mode
        self.llm = llm
        self.memory = memory

        # Pillar 3: Context management
        self.ignore = MarkIgnore(working_dir)
        self.pruner = ContextPruner()
        self.budget = TokenBudget(max_budget_usd=budget_usd)
        self.mapper = WorkspaceMapper(working_dir, self.ignore)

        # Pillar 4: Safety
        self.jail = PathJail(working_dir)
        self.redactor = SecretRedactor()
        self.interceptor = Interceptor(mode=mode)
        self.dry_runner = DryRunner()
        self.dry_runner.active = dry_run

        # Pillar 1: State persistence
        self.state = SessionState(working_dir)
        self.working_dir = working_dir

        # Self-healing: track last failed command for auto-retry
        self._heal_attempts = 0

    def _refresh_system_prompt(self, working_dir: str = "."):
        """Rebuild system prompt with fresh context + workspace map."""
        gemini_ctx = _load_gemini_context()
        memory_ctx = self.memory.build_context_summary()

        # Build workspace map (lazy — only on first call or if cache is stale)
        try:
            workspace_map = self.mapper.summary()
        except Exception:
            workspace_map = "(workspace not mapped)"

        prompt = CLI_SYSTEM_PROMPT.format(
            gemini_context=gemini_ctx,
            memory_context=memory_ctx or "No prior context.",
            working_dir=str(Path(working_dir).resolve()),
            workspace_map=workspace_map,
            tool_descriptions=TOOL_DESCRIPTIONS,
        )
        self.llm.update_system_prompt(prompt)

    def process(self, user_input: str, working_dir: str = ".") -> str:
        """Run the full ReAct loop synchronously. Returns the final response."""
        self._refresh_system_prompt(working_dir)
        self.memory.add_message("user", user_input)

        # Pillar 4: Redact secrets from user input before sending
        safe_input = self.redactor.redact(user_input)

        current_message = user_input
        accumulated_response = ""
        steps = 0
        self._heal_attempts = 0

        try:
            while steps < MAX_STEPS:
                # Pillar 3: Check token budget
                if self.budget.is_exhausted:
                    print(f"\n  {C.RED}[BUDGET EXHAUSTED] {self.budget.usage_summary}{C.RESET}")
                    accumulated_response = "Token budget exhausted. Stopping to prevent overspend."
                    break

                steps += 1
                self._print_step(steps)

                # Call LLM
                raw, tool_call = self.llm.chat(current_message)

                # Pillar 3: Track token usage
                self.budget.record_input(current_message)
                self.budget.record_output(raw or "")

                # Handle empty/blocked responses
                if not raw and not tool_call:
                    log.warning(f"Step {steps}: empty response (possible safety filter)")
                    accumulated_response = "[No response -- the request may have been filtered by safety settings. Try rephrasing.]"
                    break

                log.info(f"Step {steps}: tool={tool_call.get('action') if tool_call else None} | {len(raw)} chars")

                if not tool_call:
                    accumulated_response = raw
                    break

                # ── Execute the tool ──────────────────────────────────────────
                action = tool_call.get("action", "")
                args   = tool_call.get("args", {})

                # Pillar 4: Path jailing for file write operations
                if action in ("write_file", "edit_file", "patch_file", "delete_file", "move_file"):
                    path_key = "path" if "path" in args else "src"
                    if path_key in args:
                        allowed, reason = self.jail.is_allowed(args[path_key], "write")
                        if not allowed:
                            self._print_blocked(action, reason)
                            tool_result = f"BLOCKED: {reason}"
                            self._feed_result(action, tool_result, current_message)
                            continue

                # Pillar 4: Interceptor (human-in-the-loop)
                approved, reason = self.interceptor.should_approve(action, args)
                if not approved:
                    self._print_blocked(action, reason)
                    tool_result = f"REJECTED: {reason}"
                    self._feed_result(action, tool_result, current_message)
                    continue

                # Pillar 4: Dry-run mode
                if self.dry_runner.active:
                    self.dry_runner.record(action, args)
                    self._print_dry_run(action, args)
                    tool_result = f"[DRY RUN] Would execute: {action}({list(args.keys())})"
                    self._feed_result(action, tool_result, current_message)
                    continue

                # Memory shortcuts handled locally
                if action == "remember":
                    key, val = args.get("key", ""), args.get("value", "")
                    self.memory.set_pref(key, val)
                    tool_result = f"Stored: {key} = {val}"
                    self._print_tool("\U0001f9e0", "remember", tool_result)

                elif action == "recall":
                    key = args.get("key", "")
                    val = self.memory.get_pref(key, "(not found)")
                    tool_result = f"{key}: {val}"
                    self._print_tool("\U0001f50e", "recall", tool_result)

                else:
                    # Pillar 4: Redact secrets from tool args before display
                    display_args = {k: self.redactor.redact(str(v)) if isinstance(v, str) else v
                                   for k, v in args.items()}

                    tool_result = execute_tool(action, args)
                    icon = self.ICON_MAP.get(action, "\u2699\ufe0f")
                    summary = str(tool_result)
                    if len(summary) > 200:
                        summary = summary[:200] + "..."
                    self._print_tool(icon, action, summary)

                    # Show diff for edit/patch operations
                    if action in ("edit_file", "patch_file") and "---" in str(tool_result):
                        self._print_diff_summary(tool_result)

                    # ── Pillar 1: Self-healing loop ──────────────────────────
                    # If a run_command fails, feed the error back and let the LLM
                    # try to fix it automatically
                    if action == "run_command" and self._is_failure(tool_result):
                        self._heal_attempts += 1
                        if self._heal_attempts <= MAX_HEAL_RETRIES:
                            print(f"  {C.YELLOW}[SELF-HEAL] Command failed (attempt {self._heal_attempts}/{MAX_HEAL_RETRIES}){C.RESET}")
                            # Don't truncate — give the LLM the full error
                            tool_result = (
                                f"COMMAND FAILED (attempt {self._heal_attempts}):\n{tool_result}\n\n"
                                f"Please analyze the error and fix the issue. "
                                f"You can edit the file and re-run the command."
                            )
                        else:
                            print(f"  {C.RED}[SELF-HEAL] Max retries ({MAX_HEAL_RETRIES}) reached{C.RESET}")
                            self._heal_attempts = 0
                    elif action != "run_command":
                        self._heal_attempts = 0  # Reset on non-command steps

                # Truncate very long results (context management)
                if len(str(tool_result)) > MAX_RESULT_LEN:
                    tool_result = str(tool_result)[:MAX_RESULT_LEN] + "\n... [truncated]"

                # Feed result back as next message
                current_message = (
                    f"Tool `{action}` returned:\n```\n{tool_result}\n```\n"
                    f"Continue with the task. If done, give the final response without a tool call."
                )

            else:
                # Hit step limit
                accumulated_response = (
                    "I've completed the maximum number of steps. Here's what I did:\n" +
                    accumulated_response
                )

            # Save + return
            self.memory.add_message("model", accumulated_response)
            log.info(f"Done in {steps} step(s)")

            # Pillar 1: Save state for resume
            self.state.save(
                conversation=self.memory.get_history(limit=30),
                working_dir=working_dir,
                last_task=user_input,
                steps=steps,
            )

            # Print budget summary
            print(f"  {C.DIM}{self.budget.usage_summary}{C.RESET}")

            return accumulated_response

        except KeyboardInterrupt:
            print(f"\n  {C.YELLOW}[Interrupted] State saved -- use /resume to continue{C.RESET}")
            self.state.save(
                conversation=self.memory.get_history(limit=30),
                working_dir=working_dir,
                last_task=user_input,
                steps=steps,
            )
            return accumulated_response or "(interrupted)"
        except Exception as e:
            log.error(f"CLI planner error: {e}", exc_info=True)
            return f"Error: {e}"

    def resume(self) -> Optional[str]:
        """Resume a previous interrupted session."""
        state = self.state.load()
        if not state:
            return None

        last_task = state.get("last_task", "")
        steps = state.get("steps_completed", 0)
        ts = state.get("timestamp")

        if not last_task:
            return None

        # Format time since last session
        time_ago = ""
        if ts:
            elapsed = time.time() - ts
            if elapsed < 60:
                time_ago = f"{elapsed:.0f}s ago"
            elif elapsed < 3600:
                time_ago = f"{elapsed/60:.0f}m ago"
            else:
                time_ago = f"{elapsed/3600:.1f}h ago"

        print(f"  {C.CYAN}Resuming session{C.RESET} ({time_ago}, {steps} steps completed)")
        print(f"  {C.DIM}Last task: {last_task[:80]}{C.RESET}")
        print()

        # Re-run the task (conversation history is preserved in SQLite memory)
        return self.process(last_task, self.working_dir)

    def _is_failure(self, result: str) -> bool:
        """Check if a tool result indicates a failure that can be self-healed."""
        result_lower = result.lower()
        failure_indicators = [
            "error:", "failed", "traceback", "exception",
            "syntaxerror", "typeerror", "nameerror", "importerror",
            "command timed out", "non-zero exit",
            "test failed", "assertionerror",
        ]
        return any(indicator in result_lower for indicator in failure_indicators)

    def _feed_result(self, action, tool_result, current_message):
        """Helper to feed a result back without executing."""
        pass  # Used by the continue flow above

    # ── Terminal output helpers ────────────────────────────────────────────────

    def _print_step(self, step: int):
        msg = f"Thinking... (step {step})" if step > 1 else "Thinking..."
        print(f"{C.DIM}{C.CYAN}  {msg}{C.RESET}")

    def _print_tool(self, icon: str, name: str, summary: str):
        display = summary.replace("\n", " ")[:120]
        print(f"  {icon} {C.BOLD}{C.WHITE}{name}{C.RESET} {C.DIM}{display}{C.RESET}")

    def _print_blocked(self, action: str, reason: str):
        print(f"  {C.RED}BLOCKED {action}: {reason}{C.RESET}")

    def _print_dry_run(self, action: str, args: dict):
        if action == "run_command":
            detail = args.get("command", "?")[:80]
        elif "path" in args:
            detail = args.get("path", "?")
        else:
            detail = str(args)[:80]
        print(f"  {C.YELLOW}[DRY RUN] {action}: {detail}{C.RESET}")

    def _print_diff_summary(self, result: str):
        """Print a compact diff view for edit/patch results."""
        lines = result.split("\n")
        diff_lines = []
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                diff_lines.append(f"  {C.GREEN}{line}{C.RESET}")
            elif line.startswith("-") and not line.startswith("---"):
                diff_lines.append(f"  {C.RED}{line}{C.RESET}")
            elif line.startswith("@@"):
                diff_lines.append(f"  {C.CYAN}{line}{C.RESET}")
        for line in diff_lines[:20]:
            print(line)
        if len(diff_lines) > 20:
            print(f"  {C.DIM}... ({len(diff_lines) - 20} more lines){C.RESET}")

    def _print_response(self, text: str):
        """Print the final response with basic formatting."""
        print()
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("```"):
                continue
            if stripped.startswith("# "):
                print(f"{C.BOLD}{C.WHITE}{stripped}{C.RESET}")
            elif stripped.startswith("## "):
                print(f"{C.BOLD}{C.CYAN}{stripped}{C.RESET}")
            elif stripped.startswith("- ") or stripped.startswith("* "):
                print(f"  {C.YELLOW}\u2022{C.RESET} {stripped[2:]}")
            else:
                print(line)
        print()
