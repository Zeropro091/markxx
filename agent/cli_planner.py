"""
MARK — CLI Planner (Qt-free ReAct Loop)
Full-featured agentic loop with all pillars integrated:

Pillar 1: Self-healing loop, state persistence (resume)
Pillar 3: Context pruning, .markignore, token budget, workspace mapping
Pillar 4: Path jailing, secret redaction, interceptor, dry-run mode
"""

import json
import sys
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
from core.hooks import hooks
from agent.tools import (
    TOOL_DESCRIPTIONS, execute_tool,
    GEMINI_DIR, NEMESI_DIR, MEMORY_DIR, SHARED_SESSION
)

log = get_logger("cli_planner")

MAX_STEPS      = 20
MAX_RESULT_LEN = 3000
MAX_HEAL_RETRIES = 5   # Self-healing: max automatic retries on failure
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


# ── Knowledge Base ────────────────────────────────────────────────────────────
try:
    from core.knowledge import get_knowledge_base
    _kb = get_knowledge_base()
except Exception:
    _kb = None


# ── Load .gemini context ──────────────────────────────────────────────────────
def _load_gemini_context() -> str:
    """Load GEMINI.md persona, user profile, shared session, and knowledge base."""
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

    # Load knowledge base context
    if _kb:
        try:
            kb_summary = _kb.get_context_summary()
            if kb_summary:
                parts.append(kb_summary)
        except Exception:
            pass

    return "\n\n---\n\n".join(parts) if parts else ""


# ── System Prompt (CLI-optimized) ─────────────────────────────────────────────
CLI_SYSTEM_PROMPT = """You are MARK, an advanced agentic AI assistant running in CLI mode on the user's computer.
You have direct access to their system and can execute tools to complete tasks autonomously.

{gemini_context}

## Memory Context
{memory_context}

## Working Directory
The user is working in: {working_dir}
Use absolute paths derived from this directory when creating or editing files.

## Workspace Map
{workspace_map}

## How You Work (The Agentic Loop)
You operate in a continuous ReAct loop:
1. **PLAN**: For complex tasks, first write out a brief plan of steps you intend to take.
2. **THINK**: Reason about the immediate next step based on the user task and previous tool results.
3. **ACT**: Call EXACTLY one tool at a time to move the task forward.
4. **OBSERVE**: Analyze the result of the tool call.
5. **ITERATE**: Repeat the loop until the goal is fully achieved.
6. **FINISH**: Provide a final response summarizing what you've done.

## Tool Calling
You have access to tools via function calling. Call tools directly when you need to perform an action.
Only call ONE tool per response. After seeing the result, decide the next step.
When done, respond naturally without calling a tool.

## Core Rules for Autonomy
- **Think Continuous**: Do not stop until the task is DONE. If you need 10 steps, take 10 steps.
- **Self-Healing**: If a tool fails or a command returns an error, analyze the output, fix your approach, and retry.
- **Proactive Exploration**: Use `search_files` and `glob_files` to understand the codebase before editing.
- **Verification**: Always verify your changes (run tests, check syntax, or use `ls`) before claiming success.
- **Absolute Paths**: Always use absolute paths for file operations.
- **Chain Actions**: If a task has multiple sub-tasks, do them sequentially in the same loop.
- **Act Immediately**: NEVER say "I will..." or "I am going to..." — call the tool right away.
- **No Narration**: If you need data, call the tool IMMEDIATELY without describing your plan first.
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
        "self_evolve":   "🧬",
    }

    def __init__(self, llm: LLMClient, memory: Memory,
                 working_dir: str = ".",
                 mode: str = "auto",           # auto | normal | strict
                 budget_usd: float = 1.0,      # Token budget
                 dry_run: bool = False,        # Dry-run mode
                 settings = None):             # Tunable settings object
        self.llm = llm
        self.memory = memory

        if settings is None:
            from config.settings import load_settings
            self.settings = load_settings()
        else:
            self.settings = settings

        # Load customizable parameters
        self.max_steps = self.settings.cli_max_steps
        self.max_result_len = self.settings.cli_max_result_len
        self.max_heal_retries = self.settings.cli_max_heal_retries

        # Pillar 3: Context management
        self.ignore = MarkIgnore(working_dir)
        self.pruner = ContextPruner()
        self.budget = TokenBudget(max_budget_usd=budget_usd)
        self.mapper = WorkspaceMapper(working_dir, self.ignore)

        # Pillar 4: Safety
        self.jail = PathJail(working_dir, forbidden_patterns=self.settings.cli_forbidden_patterns)
        self.redactor = SecretRedactor()
        self.interceptor = Interceptor(mode=mode, dangerous_tools=self.settings.cli_dangerous_tools)
        self.dry_runner = DryRunner()
        self.dry_runner.active = dry_run

        # Pillar 1: State persistence
        self.state = SessionState(working_dir)

        # Lifecycle hooks: load from .mark/hooks/
        hooks.load_from_config(working_dir)
        self.working_dir = working_dir

        # Self-healing: track last failed command for auto-retry
        self._heal_attempts = 0

        # Streaming: track whether we're mid-stream (for newline management)
        self._streaming_active = False

        # Plan mode: read-only exploration
        self.plan_mode = False
        self._plan_mode_tools = {
            "read_file", "list_files", "search_files", "glob_files",
            "web_search", "fetch_url", "semantic_search", "recall_notes",
            "read_user_profile", "git_diff", "read_many_files",
            "note_list", "note_read", "note_search", "note_search_semantic",
            "note_graph", "note_backlinks", "note_get_context", "note_get_projects",
        }

        # Context compaction
        from core.context import ContextCompactor
        self.context = ContextCompactor(
            max_tokens=self.settings.llm_max_tokens * 4 if hasattr(self.settings, 'llm_max_tokens') else 100_000,
            window_size=20,
        )

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
        )

        # MARK.md hierarchical context
        from core.markmd import load_mark_context
        mark_ctx = load_mark_context(working_dir)
        if mark_ctx:
            prompt += f"\n\n## Developer Instructions (MARK.md)\n{mark_ctx}"

        if self.settings.cli_system_prompt:
            prompt += f"\n\n## Custom Developer Rules\n{self.settings.cli_system_prompt}"

        # Only update (and reset chat) if the prompt actually changed
        if prompt != self.llm.system_prompt:
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
            while steps < self.max_steps:
                # Pillar 3: Check token budget
                if self.budget.is_exhausted:
                    print(f"\n  {C.RED}[BUDGET EXHAUSTED] {self.budget.usage_summary}{C.RESET}")
                    accumulated_response += "\n[Token budget exhausted. Stopping to prevent overspend.]"
                    break

                steps += 1
                self._print_step(steps)

                # Call LLM (streaming — tokens print live)
                sys.stdout.write(f"  {C.DIM}")
                sys.stdout.flush()
                self._streaming_active = True
                raw, tool_call = self.llm.chat_stream(
                    current_message, on_chunk=self._on_stream_chunk)
                self._finish_stream()

                # Pillar 3: Track token usage
                self.budget.record_input(current_message)
                self.budget.record_output(raw or "")

                # Handle empty/blocked responses
                if not raw and not tool_call:
                    log.warning(f"Step {steps}: empty response (possible safety filter)")
                    accumulated_response += "\n[No response -- the request may have been filtered by safety settings.]"
                    break

                log.info(f"Step {steps}: tool={tool_call.get('action') if tool_call else None} | {len(raw)} chars")

                # Collect current response as the running "best answer"
                if raw:
                    accumulated_response = raw

                if not tool_call:
                    # Final answer received
                    break

                # ── Tool execution + chaining loop ──────────────────────────
                while tool_call and steps < self.max_steps:
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
                                # For safety rejections, use text fallback
                                current_message = self._feed_result(action, tool_result, current_message)
                                break  # Break inner loop, outer loop will chat() again

                    # Plan mode: block non-read-only tools
                    if self.plan_mode and action not in self._plan_mode_tools:
                        self._print_blocked(action, "Plan mode active (read-only). Use /build to exit plan mode.")
                        tool_result = f"BLOCKED: Plan mode is active. Only read-only tools are allowed. Available: {', '.join(sorted(self._plan_mode_tools))}."
                        current_message = self._feed_result(action, tool_result, current_message)
                        break

                    # Pillar 4: Interceptor (human-in-the-loop)
                    approved, reason = self.interceptor.should_approve(action, args)
                    if not approved:
                        self._print_blocked(action, reason)
                        tool_result = f"REJECTED: {reason}"
                        current_message = self._feed_result(action, tool_result, current_message)
                        break

                    # Pillar 4: Dry-run mode
                    if self.dry_runner.active:
                        self.dry_runner.record(action, args)
                        self._print_dry_run(action, args)
                        tool_result = f"[DRY RUN] Would execute: {action}({list(args.keys())})"
                        current_message = self._feed_result(action, tool_result, current_message)
                        break

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

                    elif action == "self_evolve":
                        if not self.settings.cli_enable_self_evolution:
                            tool_result = "Error: Self-evolution is disabled in settings. Warn the user or ask them to enable it under Settings (Ctrl+S)."
                            self._print_blocked("self_evolve", "Disabled in settings")
                        else:
                            prompt = args.get("prompt", "")
                            if not prompt:
                                tool_result = "Error: Please provide a 'prompt' argument for self-evolution."
                            else:
                                print(f"\n  🧬 [SELF-EVOLUTION] Agent triggered self-evolution: {prompt}")
                                from agent.evolution import SelfEvolver
                                evolver = SelfEvolver(self, self.working_dir)
                                tool_result = evolver.run_evolution(prompt)
                                self._print_tool("🧬", "self_evolve", "Evolution attempt finished.")

                    else:
                        # Lifecycle hooks: before_tool
                        hook_result = hooks.fire('before_tool', {'action': action, 'args': args})
                        if not hook_result.allowed:
                            self._print_blocked(action, f'Hook blocked: {hook_result.reason}')
                            tool_result = f'BLOCKED by hook: {hook_result.reason}'
                            current_message = self._feed_result(action, tool_result, current_message)
                            break
                        if hook_result.modified_args:
                            args = hook_result.modified_args

                        # Pillar 4: Redact secrets from tool args before display
                        display_args = {k: self.redactor.redact(str(v)) if isinstance(v, str) else v
                                       for k, v in args.items()}

                        # Diff preview for file-editing operations
                        if action in ("edit_file", "patch_file") and self.interceptor.mode != "auto":
                            self._show_edit_preview(action, args)

                        tool_result = execute_tool(action, args)
                        icon = self.ICON_MAP.get(action, "\u2699\ufe0f")
                        summary = str(tool_result)
                        if len(summary) > 200:
                            summary = summary[:200] + "..."
                        self._print_tool(icon, action, summary)

                        # Lifecycle hooks: after_tool
                        hooks.fire('after_tool', {'action': action, 'args': args, 'result': str(tool_result)[:500]})

                        # Show diff for edit/patch operations
                        if action in ("edit_file", "patch_file") and "---" in str(tool_result):
                            self._print_diff_summary(tool_result)

                        # ── Pillar 1: Self-healing loop ──────────────────────
                        if action == "run_command" and self._is_failure(tool_result):
                            self._heal_attempts += 1
                            if self._heal_attempts <= self.max_heal_retries:
                                print(f"  {C.YELLOW}[SELF-HEAL] Command failed (attempt {self._heal_attempts}/{self.max_heal_retries}){C.RESET}")
                                tool_result = (
                                    f"COMMAND FAILED (attempt {self._heal_attempts}):\n{tool_result}\n\n"
                                    f"Please analyze the error and fix the issue. "
                                    f"You can edit the file and re-run the command."
                                )
                            else:
                                print(f"  {C.RED}[SELF-HEAL] Max retries ({self.max_heal_retries}) reached{C.RESET}")
                                self._heal_attempts = 0
                        elif action != "run_command":
                            self._heal_attempts = 0

                    # Truncate very long results
                    if len(str(tool_result)) > self.max_result_len:
                        tool_result = str(tool_result)[:self.max_result_len] + "\n... [truncated]"

                    # Feed result back via proper FunctionResponse (streaming)
                    sys.stdout.write(f"  {C.DIM}")
                    sys.stdout.flush()
                    self._streaming_active = True
                    raw, tool_call = self.llm.chat_tool_result_stream(
                        action, str(tool_result),
                        on_chunk=self._on_stream_chunk)
                    self._finish_stream()

                    # Track tokens
                    self.budget.record_input(str(tool_result))
                    self.budget.record_output(raw or "")

                    if not raw and not tool_call:
                        log.warning(f"Step {steps}: empty response after tool result")
                        accumulated_response += "\n[No response -- the request may have been filtered.]"
                        break

                    log.info(f"Step {steps}: tool={tool_call.get('action') if tool_call else None} | {len(raw)} chars")

                    if raw:
                        accumulated_response = raw

                    if not tool_call:
                        # Final answer from LLM — break inner loop
                        break

                    # Another tool_call — inner loop continues
                    steps += 1
                    self._print_step(steps)
                    log.debug(f"Chaining tool call: {tool_call.get('action')}")

                # If we got a final answer from the inner loop, break outer too
                if accumulated_response or (not tool_call and not raw):
                    break

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
        return (
            f"Tool `{action}` returned:\n```\n{tool_result}\n```\n"
            f"Continue with the task. If done, give the final response without a tool call."
        )

    # ── Streaming helpers ──────────────────────────────────────────────────────

    def _on_stream_chunk(self, text: str):
        """Callback for streaming: write each text delta to stdout immediately."""
        sys.stdout.write(text)
        sys.stdout.flush()

    def _finish_stream(self):
        """End a streaming output block: reset color and add newline."""
        if self._streaming_active:
            sys.stdout.write(f"{C.RESET}\n")
            sys.stdout.flush()
            self._streaming_active = False

    # ── Terminal output helpers ────────────────────────────────────────────────

    def _print_step(self, step: int):
        msg = f"Thinking... (step {step})" if step > 1 else "Thinking..."
        print(f"{C.DIM}{C.CYAN}  {msg}{C.RESET}")

    def _show_edit_preview(self, action: str, args: dict):
        """Show a colored diff preview before applying file edits."""
        try:
            path = args.get("path", "")
            if not path or not Path(path).exists():
                return

            content = Path(path).read_text(encoding="utf-8", errors="replace")
            old = args.get("old", "")
            new = args.get("new", "")
            if not old:
                return

            # Generate preview diff
            from core.smart_edit import smart_edit
            result = smart_edit(content, old, new)
            if result.occurrences == 0:
                return

            import difflib
            diff_lines = list(difflib.unified_diff(
                content.splitlines(keepends=True)[:50],
                result.new_content.splitlines(keepends=True)[:50],
                fromfile=Path(path).name,
                tofile=f"{Path(path).name} (modified)",
                lineterm="",
            ))

            if diff_lines:
                strategy = f" [{result.strategy}]" if result.strategy != "exact" else ""
                print(f"\n  {C.BOLD}📋 Edit Preview{strategy}:{C.RESET}")
                for line in diff_lines[:20]:
                    if line.startswith("+") and not line.startswith("+++"):
                        print(f"    {C.GREEN}{line}{C.RESET}")
                    elif line.startswith("-") and not line.startswith("---"):
                        print(f"    {C.RED}{line}{C.RESET}")
                    elif line.startswith("@@"):
                        print(f"    {C.CYAN}{line}{C.RESET}")
                    else:
                        print(f"    {C.DIM}{line}{C.RESET}")
                if len(diff_lines) > 20:
                    print(f"    {C.DIM}... ({len(diff_lines) - 20} more lines){C.RESET}")
                print()
        except Exception:
            pass  # Preview is best-effort, never block the edit

    def _print_tool(self, icon: str, name: str, summary: str):
        if "\n" in summary:
            lines = summary.split("\n")
            limit = 10
            truncated = len(lines) > limit
            display_lines = lines[:limit]
            indented = "\n".join(f"    {C.DIM}{line}{C.RESET}" for line in display_lines)
            if truncated:
                indented += f"\n    {C.DIM}... ({len(lines) - limit} more lines){C.RESET}"
            print(f"  {icon} {C.BOLD}{C.WHITE}{name}{C.RESET} {C.DIM}returned:{C.RESET}\n{indented}")
        else:
            display = summary[:120]
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
