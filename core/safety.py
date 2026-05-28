"""
MARK — Safety & Context Engine
Pillar 3: Memory & Context Management
Pillar 4: Safety & Security Guardrails

Provides:
  - .markignore protocol (per-project ignore rules)
  - Context pruner (sliding window to prevent context bloat)
  - Token budget enforcer (circuit breaker on cost)
  - Semantic workspace mapping (import graph)
  - Path jailing (restrict writes to project root)
  - Secret redaction (scrub API keys before sending to LLM)
  - Human-in-the-loop interceptor (approve dangerous actions)
  - Dry-run mode (preview without execution)
"""

import os
import re
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 3: .markignore Protocol
# ══════════════════════════════════════════════════════════════════════════════

# Default patterns to always ignore (can be overridden in .markignore)
DEFAULT_IGNORE_PATTERNS = [
    ".git", ".svn", ".hg",
    "node_modules", "vendor", "__pycache__",
    ".venv", "venv", "env", ".env",
    ".next", ".nuxt", "dist", "build", "out", "target",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "*.pyc", "*.pyo", "*.so", "*.dll", "*.exe", "*.bin",
    "*.min.js", "*.min.css", "*.map",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Gemfile.lock", "cargo.lock",
    ".DS_Store", "Thumbs.db",
    "*.log", "*.tmp",
]


class MarkIgnore:
    """Parse and evaluate .markignore rules for the current project."""

    def __init__(self, project_root: str):
        self.root = Path(project_root).resolve()
        self.patterns: List[str] = list(DEFAULT_IGNORE_PATTERNS)
        self._negations: List[str] = []
        self._load()

    def _load(self):
        """Load .markignore from project root if it exists."""
        ignore_file = self.root / ".markignore"
        if ignore_file.exists():
            try:
                for line in ignore_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("!"):
                        self._negations.append(line[1:])
                    else:
                        self.patterns.append(line)
            except Exception:
                pass

    def is_ignored(self, path: str) -> bool:
        """Check if a file path should be ignored."""
        p = Path(path)

        # Try relative path from root first
        try:
            rel = p.relative_to(self.root)
            check_path = str(rel).replace("\\", "/")
        except ValueError:
            check_path = str(p).replace("\\", "/")

        # Check negations first (un-ignore rules)
        for neg in self._negations:
            if self._match_pattern(check_path, neg):
                return False

        # Check ignore patterns
        for pattern in self.patterns:
            if self._match_pattern(check_path, pattern):
                return True

        return False

    def _match_pattern(self, path: str, pattern: str) -> bool:
        """Simple glob-style matching."""
        # Direct name match (e.g., "node_modules")
        if pattern in path.split("/"):
            return True
        # Suffix match (e.g., "*.pyc")
        if pattern.startswith("*."):
            ext = pattern[1:]  # ".pyc"
            if path.endswith(ext):
                return True
        # Prefix match
        if pattern.endswith("/"):
            prefix = pattern[:-1]
            if any(part == prefix for part in path.split("/")):
                return True
        # Exact match
        if path == pattern or path.endswith("/" + pattern):
            return True
        return False

    def filter_paths(self, paths: List[str]) -> List[str]:
        """Filter a list of paths, removing ignored ones."""
        return [p for p in paths if not self.is_ignored(p)]


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 3: Context Pruner (Sliding Window)
# ══════════════════════════════════════════════════════════════════════════════

class ContextPruner:
    """Manage conversation context to prevent token bloat.

    Keeps recent messages in full, truncates old tool results,
    and drops the oldest messages when the window is full.
    """

    def __init__(self, max_messages: int = 40, max_tool_result_chars: int = 1500):
        self.max_messages = max_messages
        self.max_tool_result_chars = max_tool_result_chars

    def prune(self, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Prune conversation history to fit within limits.

        Strategy:
        1. Always keep the first user message (original task)
        2. Truncate old tool results
        3. Drop oldest messages (except the first)
        4. Always keep the last N messages in full
        """
        if len(history) <= self.max_messages:
            return [self._truncate_tool_results(m) for m in history]

        pruned = []
        # Keep first message (original task)
        if history:
            pruned.append(history[0])

        # Keep the last (max_messages - 1) messages
        tail = history[-(self.max_messages - 1):]
        for msg in tail:
            pruned.append(self._truncate_tool_results(msg))

        return pruned

    def _truncate_tool_results(self, msg: Dict[str, str]) -> Dict[str, str]:
        """Truncate long tool results in message content."""
        content = msg.get("content", msg.get("parts", [""]))[0] if isinstance(msg.get("content", msg.get("parts", [""])), list) else msg.get("content", "")
        if len(content) > self.max_tool_result_chars and "Tool `" in content:
            truncated = content[:self.max_tool_result_chars] + "\n... [context pruned]"
            return {**msg, "content": truncated}
        return msg


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 3: Token Budget Enforcer
# ══════════════════════════════════════════════════════════════════════════════

class TokenBudget:
    """Hard circuit breaker on token usage / estimated cost.

    Estimates tokens as ~4 chars per token for English text.
    Tracks cumulative usage across the session.
    """

    CHARS_PER_TOKEN = 4
    # Gemini 2.5 Flash pricing (approximate, per million tokens)
    # Input: $0.15/M, Output: $0.60/M
    INPUT_COST_PER_M = 0.15
    OUTPUT_COST_PER_M = 0.60

    def __init__(self, max_budget_usd: float = 1.0):
        self.max_budget_usd = max_budget_usd
        self.total_input_chars = 0
        self.total_output_chars = 0
        self._cut_off = False

    def record_input(self, text: str):
        """Record input text sent to the LLM."""
        self.total_input_chars += len(text)
        self._check_budget()

    def record_output(self, text: str):
        """Record output text received from the LLM."""
        self.total_output_chars += len(text)
        self._check_budget()

    def _check_budget(self):
        """Kill the loop if budget exceeded."""
        if self.estimated_cost_usd > self.max_budget_usd:
            self._cut_off = True

    @property
    def is_exhausted(self) -> bool:
        return self._cut_off

    @property
    def estimated_cost_usd(self) -> float:
        input_tokens = self.total_input_chars / self.CHARS_PER_TOKEN
        output_tokens = self.total_output_chars / self.CHARS_PER_TOKEN
        cost = (input_tokens / 1_000_000 * self.INPUT_COST_PER_M +
                output_tokens / 1_000_000 * self.OUTPUT_COST_PER_M)
        return cost

    @property
    def usage_summary(self) -> str:
        in_tok = self.total_input_chars / self.CHARS_PER_TOKEN
        out_tok = self.total_output_chars / self.CHARS_PER_TOKEN
        budget_str = "Unlimited" if self.max_budget_usd == float('inf') or self.max_budget_usd > 1000000 else f"${self.max_budget_usd:.2f}"
        return (f"Input: ~{in_tok:,.0f} tokens | "
                f"Output: ~{out_tok:,.0f} tokens | "
                f"Est. cost: ${self.estimated_cost_usd:.4f} / {budget_str}")


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 3: Semantic Workspace Mapping
# ══════════════════════════════════════════════════════════════════════════════

class WorkspaceMapper:
    """Build a lightweight import graph of the project.

    Parses Python, JS/TS imports to map which files depend on which.
    Helps the AI know exactly which file to read next without guessing.
    """

    # Regex patterns for imports
    PY_IMPORT = re.compile(r'^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)', re.MULTILINE)
    JS_IMPORT = re.compile(r'(?:import|require)\s*\(?[\'"]([^\'"]+)[\'"]', re.MULTILINE)

    def __init__(self, project_root: str, ignore: MarkIgnore = None):
        self.root = Path(project_root).resolve()
        self.ignore = ignore or MarkIgnore(project_root)
        self._graph: Optional[Dict[str, Set[str]]] = None

    def build(self) -> Dict[str, Set[str]]:
        """Scan the project and build the import graph."""
        graph = {}

        for ext, parser in [(".py", self._parse_py), (".js", self._parse_js), (".ts", self._parse_js)]:
            for fp in self.root.rglob(f"*{ext}"):
                if self.ignore.is_ignored(str(fp)):
                    continue
                try:
                    rel = str(fp.relative_to(self.root)).replace("\\", "/")
                    imports = parser(fp)
                    graph[rel] = imports
                except Exception:
                    continue

        self._graph = graph
        return graph

    def get_graph(self) -> Dict[str, Set[str]]:
        """Get cached graph or build it."""
        if self._graph is None:
            return self.build()
        return self._graph

    def summary(self) -> str:
        """Return a human-readable summary of the workspace structure."""
        graph = self.get_graph()
        if not graph:
            return "(empty workspace)"

        lines = [f"Workspace: {len(graph)} source files\n"]

        # Group by directory
        dirs: Dict[str, List[str]] = {}
        for file_path, imports in sorted(graph.items()):
            parts = file_path.rsplit("/", 1)
            directory = parts[0] if len(parts) > 1 else "."
            dirs.setdefault(directory, []).append(file_path)

        for directory, files in sorted(dirs.items()):
            lines.append(f"  {directory}/ ({len(files)} files)")
            for f in files[:10]:
                num_deps = len(graph.get(f, set()))
                if num_deps > 0:
                    lines.append(f"    {Path(f).name} -> {num_deps} import(s)")
                else:
                    lines.append(f"    {Path(f).name}")
            if len(files) > 10:
                lines.append(f"    ... and {len(files) - 10} more")

        return "\n".join(lines)

    def _parse_py(self, fp: Path) -> Set[str]:
        """Extract Python imports from a file."""
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return set()
        imports = set()
        for match in self.PY_IMPORT.findall(text):
            # Convert "foo.bar.baz" to "foo/bar.py" or "foo/__init__.py"
            parts = match.split(".")
            local_path = str(Path(*parts))
            # Check if it's a local import (file exists in project)
            for candidate in [local_path + ".py", local_path + "/__init__.py"]:
                if (self.root / candidate).exists():
                    imports.add(candidate.replace("\\", "/"))
                    break
        return imports

    def _parse_js(self, fp: Path) -> Set[str]:
        """Extract JS/TS imports from a file."""
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return set()
        imports = set()
        for match in self.JS_IMPORT.findall(text):
            if match.startswith("."):
                # Relative import
                rel = str((fp.parent / match).relative_to(self.root)).replace("\\", "/")
                imports.add(rel)
        return imports


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 4: Path Jailing
# ══════════════════════════════════════════════════════════════════════════════

class PathJail:
    """Restrict file writes to within the project root directory."""

    # Paths that are NEVER allowed to be written to, even inside the project
    FORBIDDEN_PATTERNS = [
        ".env", ".env.local", ".env.production",
        "credentials", "secrets", "id_rsa", "id_ed25519",
        ".ssh", ".gnupg",
    ]

    def __init__(self, project_root: str, forbidden_patterns: List[str] = None):
        self.root = Path(project_root).resolve()
        self.forbidden_patterns = forbidden_patterns if forbidden_patterns is not None else self.FORBIDDEN_PATTERNS

    def is_allowed(self, path: str, mode: str = "write") -> Tuple[bool, str]:
        """Check if a path operation is allowed.

        Args:
            path: The target file path
            mode: "read", "write", or "delete"

        Returns:
            (allowed, reason) tuple
        """
        target = Path(path).resolve()

        # Read operations are always allowed
        if mode == "read":
            return True, ""

        # Write/delete operations must be within the project root
        try:
            target.relative_to(self.root)
        except ValueError:
            return False, f"Path outside project jail: {path} (project root: {self.root})"

        # Check forbidden patterns
        for pattern in self.forbidden_patterns:
            if pattern in str(target).replace("\\", "/").lower():
                return False, f"Refusing to {mode} sensitive file: {path} (matches '{pattern}')"

        return True, ""

    def jail_path(self, path: str) -> str:
        """Resolve a relative path against the project root."""
        p = Path(path)
        if p.is_absolute():
            return str(p)
        return str((self.root / p).resolve())


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 4: Secret Redaction
# ══════════════════════════════════════════════════════════════════════════════

class SecretRedactor:
    """Scrub API keys and passwords from text before sending to the LLM."""

    # Patterns that look like secrets
    PATTERNS = [
        # API keys (common formats)
        (re.compile(r'(api[_-]?key\s*[:=]\s*["\']?)\S+(["\']?)', re.I), r'\1[REDACTED]\2'),
        (re.compile(r'(secret\s*[:=]\s*["\']?)\S+(["\']?)', re.I), r'\1[REDACTED]\2'),
        (re.compile(r'(password\s*[:=]\s*["\']?)\S+(["\']?)', re.I), r'\1[REDACTED]\2'),
        (re.compile(r'(token\s*[:=]\s*["\']?)\S+(["\']?)', re.I), r'\1[REDACTED]\2'),
        (re.compile(r'(auth(?:orization)?\s*[:=]\s*["\']?(?:Bearer\s+)?)\S+(["\']?)', re.I), r'\1[REDACTED]\2'),
        # Long hex/base64 strings that look like keys (32+ chars)
        (re.compile(r'["\']([A-Za-z0-9+/=_-]{32,})["\']'), '"[REDACTED_KEY]"'),
        # .env variable assignments
        (re.compile(r'((?:API_KEY|SECRET|PASSWORD|TOKEN|PRIVATE_KEY|DATABASE_URL)\s*=\s*)\S+'), r'\1[REDACTED]'),
        # AWS keys
        (re.compile(r'AKIA[0-9A-Z]{16}'), 'AKIA[REDACTED]'),
        # Google API keys (AIza...)
        (re.compile(r'AIza[0-9A-Za-z_-]{35}'), 'AIza[REDACTED]'),
        # Private key blocks
        (re.compile(r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----'),
         '-----BEGIN PRIVATE KEY----- [REDACTED] -----END PRIVATE KEY-----'),
    ]

    def redact(self, text: str) -> str:
        """Remove secrets from text before sending to the LLM."""
        for pattern, replacement in self.PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def has_secrets(self, text: str) -> bool:
        """Check if text likely contains secrets."""
        redacted = self.redact(text)
        return redacted != text


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 4: Human-in-the-Loop Interceptor
# ══════════════════════════════════════════════════════════════════════════════

# Tools that require human approval
DANGEROUS_TOOLS = {
    "run_command",   # Can execute arbitrary commands
    "write_file",    # Overwrites files
    "edit_file",     # Modifies files
    "delete_file",   # Deletes files
    "move_file",     # Can break imports
}


class Interceptor:
    """Human-in-the-loop approval for dangerous actions.

    Modes:
    - "auto": Approve everything (yolo mode)
    - "normal": Ask for dangerous tools only
    - "strict": Ask for every tool call
    """

    def __init__(self, mode: str = "normal", dangerous_tools: List[str] = None):
        self.mode = mode
        self.dangerous_tools = set(dangerous_tools) if dangerous_tools is not None else DANGEROUS_TOOLS
        self._auto_approved: Set[str] = set()  # Tools auto-approved for this session

    def should_approve(self, action: str, args: dict) -> Tuple[bool, str]:
        """Check if a tool call should be approved.

        Returns:
            (approved, reason)
        """
        if self.mode == "auto":
            return True, ""

        if self.mode == "strict":
            return self._ask_user(action, args)

        # Normal mode: ask only for dangerous tools
        if action in self.dangerous_tools and action not in self._auto_approved:
            return self._ask_user(action, args)

        return True, ""

    def _ask_user(self, action: str, args: dict) -> Tuple[bool, str]:
        """Prompt user for approval via terminal input."""
        # Build a readable summary of the action
        if action == "run_command":
            detail = args.get("command", "?")
            if len(detail) > 80:
                detail = detail[:80] + "..."
        elif action in ("write_file", "edit_file", "delete_file"):
            detail = args.get("path", "?")
        elif action == "move_file":
            detail = f"{args.get('src', '?')} -> {args.get('dst', '?')}"
        else:
            detail = str(args)[:80]

        print(f"\n  \033[33mINTERCEPTOR\033[0m  {action}: {detail}")
        print(f"  [y] Yes  [n] No  [a] Always approve '{action}'  [e] Edit args")

        try:
            choice = input("  Choose: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False, "Rejected by user"

        if choice in ("y", "yes"):
            return True, ""
        elif choice in ("a", "always"):
            self._auto_approved.add(action)
            return True, ""
        elif choice in ("e", "edit"):
            # Allow user to modify args (simplified — just the command for now)
            if action == "run_command":
                new_cmd = input(f"  New command: ").strip()
                if new_cmd:
                    args["command"] = new_cmd
            return True, ""
        else:
            return False, "Rejected by user"


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 4: Dry-Run Mode
# ══════════════════════════════════════════════════════════════════════════════

class DryRunner:
    """Preview what the agent would do without actually executing."""

    def __init__(self):
        self.planned_actions: List[Dict] = []
        self.active = False

    def record(self, action: str, args: dict, predicted_result: str = ""):
        """Record a planned action without executing it."""
        self.planned_actions.append({
            "action": action,
            "args": args,
            "predicted_result": predicted_result,
            "timestamp": time.time(),
        })

    def summary(self) -> str:
        """Generate a markdown plan of what would have been done."""
        if not self.planned_actions:
            return "(no actions planned)"

        lines = ["# Dry-Run Plan\n"]
        for i, plan in enumerate(self.planned_actions, 1):
            action = plan["action"]
            args = plan["args"]
            lines.append(f"## Step {i}: `{action}`")
            if action == "run_command":
                lines.append(f"  Command: `{args.get('command', '')}`")
            elif action in ("write_file", "edit_file"):
                lines.append(f"  File: `{args.get('path', '')}`")
                if action == "edit_file":
                    lines.append(f"  Find: `{args.get('old', '')[:60]}...`")
                    lines.append(f"  Replace with: `{args.get('new', '')[:60]}...`")
                elif action == "write_file":
                    content = args.get("content", "")
                    lines.append(f"  Content: {len(content)} chars")
            elif action == "delete_file":
                lines.append(f"  Path: `{args.get('path', '')}`")
            elif action == "move_file":
                lines.append(f"  `{args.get('src', '')}` -> `{args.get('dst', '')}`")
            else:
                lines.append(f"  Args: `{args}`")
            lines.append("")

        return "\n".join(lines)
