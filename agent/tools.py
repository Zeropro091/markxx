"""
MARK — Tool Registry
All tools MARK can call in its agentic loop.
Each tool is a function: (args: dict) -> str result
"""

from core.tool_registry import ToolRegistry

import os
import subprocess
import json
import datetime
from pathlib import Path
from typing import Dict, Callable, Any

from core.logger import get_logger
log = get_logger("tools")

# ── Paths ─────────────────────────────────────────────────────────────────────
GEMINI_DIR    = Path(r"C:\Users\Putu Ari\.gemini")
NEMESI_DIR    = Path(r"C:\Users\Putu Ari\note-taking-app\data\notes")
MEMORY_DIR    = NEMESI_DIR / "gemini memory"
SHARED_SESSION = GEMINI_DIR / "SHARED_SESSION.json"


# ══════════════════════════════════════════════════════════════════════════════
# Tool implementations
# ══════════════════════════════════════════════════════════════════════════════

def tool_run_command(args: dict) -> str:
    cmd = args.get("command", "")
    if not cmd:
        return "Error: no command provided"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace"
        )
        out = (result.stdout + result.stderr).strip()
        return out[:3000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (30s)"
    except Exception as e:
        return f"Error: {e}"


def tool_read_file(args: dict) -> str:
    path = args.get("path", "")
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"
        if p.stat().st_size > 500_000:
            return f"Error: file too large ({p.stat().st_size} bytes). Read a smaller file."
        return p.read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception as e:
        return f"Error reading file: {e}"


def tool_write_file(args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def tool_list_files(args: dict) -> str:
    path = args.get("path", ".")
    pattern = args.get("pattern", "*")
    recursive = args.get("recursive", False)
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: path not found: {path}"
        fn = p.rglob if recursive else p.glob
        files = list(fn(pattern))[:100]
        lines = []
        for f in sorted(files):
            stat = f.stat()
            size = f"{stat.st_size:,}" if f.is_file() else "DIR"
            lines.append(f"{size:>10}  {f}")
        return "\n".join(lines) if lines else "(empty)"
    except Exception as e:
        return f"Error: {e}"


def tool_open_app(args: dict) -> str:
    from actions.computer import action_open_app
    return action_open_app(args)


def tool_type_text(args: dict) -> str:
    from actions.computer import action_type_text
    return action_type_text(args)


def tool_open_file(args: dict) -> str:
    path = args.get("path", "")
    try:
        os.startfile(path)
        return f"Opened: {path}"
    except Exception as e:
        return f"Error opening file: {e}"


def tool_take_screenshot(args: dict) -> str:
    from actions.screen import get_screen_thumbnail
    img = get_screen_thumbnail()
    return "screenshot_captured" if img else "Error: could not capture screenshot"


def tool_web_search(args: dict) -> str:
    query = args.get("query", "")
    try:
        import urllib.parse, urllib.request
        encoded = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="replace")
        # Extract plain text snippets
        import re
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        titles   = re.findall(r'class="result__title[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)
        def clean(s): return re.sub(r'<[^>]+>', '', s).strip()
        results = []
        for t, s in zip(titles[:5], snippets[:5]):
            results.append(f"• {clean(t)}: {clean(s)}")
        return "\n".join(results) if results else f"No results for: {query}"
    except Exception as e:
        # Fallback: open browser
        import webbrowser
        webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        return f"Opened browser search for: {query}"


def tool_remember_note(args: dict) -> str:
    """Save a note to Nemesi (the user's second brain)."""
    title   = args.get("title", f"MARK Note {datetime.date.today()}")
    content = args.get("content", "")
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
        path = MEMORY_DIR / f"{safe_title}.md"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        full = f"# {title}\n_Saved by MARK at {timestamp}_\n\n{content}\n"
        path.write_text(full, encoding="utf-8")
        log.info(f"Note saved: {path}")
        return f"Note saved: {path.name}"
    except Exception as e:
        return f"Error saving note: {e}"


def tool_recall_notes(args: dict) -> str:
    """Search Nemesi notes for a keyword."""
    query = args.get("query", "").lower()
    try:
        if not MEMORY_DIR.exists():
            return "No notes found."
        matches = []
        for f in sorted(MEMORY_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
            content = f.read_text(encoding="utf-8", errors="replace")
            if query in content.lower() or query in f.name.lower():
                snippet = content[:300].replace("\n", " ")
                matches.append(f"📄 {f.name}: {snippet}")
        return "\n\n".join(matches[:5]) if matches else f"No notes matching: {query}"
    except Exception as e:
        return f"Error searching notes: {e}"


def tool_read_user_profile(args: dict) -> str:
    """Read the user's AI-synthesized profile from Nemesi."""
    profile_path = NEMESI_DIR / "AI-Synthesized-User-Profile.md"
    if profile_path.exists():
        return profile_path.read_text(encoding="utf-8", errors="replace")[:4000]
    return "User profile not found."


def tool_update_shared_session(args: dict) -> str:
    """Update the shared session state across AI instances."""
    key   = args.get("key", "")
    value = args.get("value", "")
    try:
        data = {}
        if SHARED_SESSION.exists():
            data = json.loads(SHARED_SESSION.read_text())
        data[key] = value
        data["_last_updated"] = datetime.datetime.now().isoformat()
        data["_updated_by"] = "MARK"
        SHARED_SESSION.write_text(json.dumps(data, indent=2))
        return f"Shared session updated: {key}"
    except Exception as e:
        return f"Error updating shared session: {e}"


def tool_remember(args: dict) -> str:
    return f"remembered:{args.get('key','')}={args.get('value','')}"  # handled by planner


def tool_recall(args: dict) -> str:
    return f"recall:{args.get('key','')}"  # handled by planner


def tool_browser_control(args: dict) -> str:
    """Controls any web browser using Playwright automation."""
    from actions.browser_control import browser_control
    return browser_control(parameters=args)


def tool_computer_control(args: dict) -> str:
    """Perform a computer control action like typing, clicking, drag/drop, keyboard/mouse actions, screenshot, etc."""
    from actions.computer_control import computer_control
    return computer_control(parameters=args)


def tool_computer_settings(args: dict) -> str:
    """Modify computer settings like volume, brightness, dark mode, wifi, window positioning, or screen locks."""
    from actions.computer_settings import computer_settings
    return computer_settings(parameters=args)


def tool_dev_agent(args: dict) -> str:
    """Trigger a developer agent to plan, write, test, build, and debug software projects in a desktop sandbox."""
    from actions.dev_agent import dev_agent
    return dev_agent(parameters=args)


def tool_file_processor(args: dict) -> str:
    """Analyze, process, trim, transcribe, convert, compress, extract, or summarize files of various types (images, pdfs, audio, video, json, csv, docx, pptx, zip, code, etc.)."""
    from actions.file_processor import file_processor
    return file_processor(parameters=args)


# ── Semantic Search (codebase indexing) ────────────────────────────────────────
_indexer_instance = None

def _get_indexer():
    """Lazy-init the CodebaseIndexer using the current API key."""
    global _indexer_instance
    if _indexer_instance is None:
        try:
            from config.settings import load_settings
            from core.indexer import CodebaseIndexer
            settings = load_settings()
            api_key = settings.gemini_api_key
            if not api_key:
                return None
            _indexer_instance = CodebaseIndexer(
                api_key=api_key,
                db_path=os.path.join(os.getcwd(), ".mark", "index.db"),
            )
        except Exception as e:
            log.error(f"Failed to init CodebaseIndexer: {e}")
            return None
    return _indexer_instance


def tool_semantic_search(args: dict) -> str:
    """Search the codebase using semantic similarity (embedding-based)."""
    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    if not query:
        return "Error: no query provided"

    indexer = _get_indexer()
    if indexer is None:
        return "Error: could not initialize indexer (no API key?)"

    # Auto-index if stale or empty
    cwd = os.getcwd()
    try:
        if indexer.is_stale(cwd):
            log.info("Index stale — re-indexing codebase...")
            stats = indexer.index(cwd)
            log.info(f"Indexed: {stats}")
    except Exception as e:
        log.warning(f"Auto-index failed: {e}")

    try:
        results = indexer.search(query, top_k=top_k)
        if not results:
            return f"No results found for: {query}"
        lines = []
        for r in results:
            lines.append(f"── {r.file}:{r.start_line}-{r.end_line} (score: {r.score}) ──")
            lines.append(r.snippet)
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Error during search: {e}"


# ── CLI-extended tools ────────────────────────────────────────────────────────
from agent.cli_tools import (
    tool_edit_file,
    tool_delete_file,
    tool_move_file,
    tool_search_files,
    tool_glob_files,
    tool_fetch_url,
    tool_git_diff,
    tool_git_commit,
    tool_patch_file,
    tool_read_many_files,
    tool_shell_background,
    tool_shell_status,
    tool_shell_kill,
)


# ══════════════════════════════════════════════════════════════════════════════
# Registry
# ══════════════════════════════════════════════════════════════════════════════

registry = ToolRegistry()

# ── Shell / System (read-write) ───────────────────────────────────────────────
registry.register("run_command",       tool_run_command,       category="system")
registry.register("open_app",          tool_open_app,          category="system")
registry.register("type_text",         tool_type_text,         category="system")
registry.register("open_file",         tool_open_file,         category="system")
registry.register("take_screenshot",   tool_take_screenshot,   category="system")

# ── File Operations ───────────────────────────────────────────────────────────
registry.register("read_file",         tool_read_file,         category="file", read_only=True)
registry.register("write_file",        tool_write_file,        category="file")
registry.register("edit_file",         tool_edit_file,         category="file")
registry.register("patch_file",        tool_patch_file,        category="file")
registry.register("delete_file",       tool_delete_file,       category="file")
registry.register("move_file",         tool_move_file,         category="file")
registry.register("list_files",        tool_list_files,        category="file", read_only=True)
registry.register("search_files",      tool_search_files,      category="file", read_only=True)
registry.register("glob_files",        tool_glob_files,        category="file", read_only=True)
registry.register("read_many_files",   tool_read_many_files,   category="file", read_only=True)

# ── Network / Web ─────────────────────────────────────────────────────────────
registry.register("fetch_url",         tool_fetch_url,         category="web",  read_only=True)
registry.register("web_search",        tool_web_search,        category="web",  read_only=True)

# ── Git ───────────────────────────────────────────────────────────────────────
registry.register("git_diff",          tool_git_diff,          category="git",  read_only=True)
registry.register("git_commit",        tool_git_commit,        category="git")

# ── Browser / Computer / Settings ─────────────────────────────────────────────
registry.register("browser_control",   tool_browser_control,   category="automation")
registry.register("computer_control",  tool_computer_control,  category="automation")
registry.register("computer_settings", tool_computer_settings, category="automation")

# ── Agent ─────────────────────────────────────────────────────────────────────
registry.register("dev_agent",         tool_dev_agent,         category="agent")
registry.register("file_processor",    tool_file_processor,    category="agent")

# ── Semantic Search ───────────────────────────────────────────────────────────
registry.register("semantic_search",   tool_semantic_search,   category="search", read_only=True)

# ── Background Shell ──────────────────────────────────────────────────────────
registry.register("shell_background",  tool_shell_background,  category="system")
registry.register("shell_status",      tool_shell_status,      category="system", read_only=True)
registry.register("shell_kill",        tool_shell_kill,        category="system")

# ── Memory / Notes / Session ──────────────────────────────────────────────────
registry.register("remember_note",         tool_remember_note,         category="memory")
registry.register("recall_notes",          tool_recall_notes,          category="memory", read_only=True)
registry.register("read_user_profile",     tool_read_user_profile,     category="memory", read_only=True)
registry.register("update_shared_session", tool_update_shared_session, category="memory")
registry.register("self_evolve",           lambda args: "self_evolve_handled_by_planner", category="meta")


# ── Optional note-taking tools ────────────────────────────────────────────────
try:
    from actions.notes import (
        note_list, note_read, note_search, note_search_semantic,
        note_create, note_update, note_delete, note_rename,
        note_graph, note_backlinks, note_get_context, note_get_projects,
    )
    # Read-only note tools
    registry.register("note_list",            note_list,            category="notes", read_only=True)
    registry.register("note_read",            note_read,            category="notes", read_only=True)
    registry.register("note_search",          note_search,          category="notes", read_only=True)
    registry.register("note_search_semantic", note_search_semantic, category="notes", read_only=True)
    registry.register("note_graph",           note_graph,           category="notes", read_only=True)
    registry.register("note_backlinks",       note_backlinks,       category="notes", read_only=True)
    registry.register("note_get_context",     note_get_context,     category="notes", read_only=True)
    registry.register("note_get_projects",    note_get_projects,    category="notes", read_only=True)
    # Read-write note tools
    registry.register("note_create",          note_create,          category="notes")
    registry.register("note_update",          note_update,          category="notes")
    registry.register("note_delete",          note_delete,          category="notes")
    registry.register("note_rename",          note_rename,          category="notes")
    _NOTES_AVAILABLE = True
except (ImportError, SyntaxError, Exception):
    _NOTES_AVAILABLE = False


# ── LSP (Language Server Protocol) ────────────────────────────────────────────
try:
    from core.lsp import tool_lsp
    registry.register("lsp", tool_lsp, category="search", read_only=True)
except (ImportError, Exception):
    pass


# ── Backward-compatible TOOLS dict ────────────────────────────────────────────
TOOLS: Dict[str, Callable] = registry.tools


_NOTES_DESCRIPTION = """
note_list             {}                                                   -- list all notes in the knowledge base
note_read             {"id":"<note_id>"}                                   -- read a note (returns content + metadata)
note_search           {"query":"<search term>"}                            -- full-text fuzzy search across all notes
note_search_semantic  {"query":"<search term>"}                            -- AI-powered semantic search (meaning-based)
note_create           {"path":"<path>","title":"<Title>","content":"..."}  -- create a new note (path like 'Projects/My-Idea')
note_update           {"id":"<note_id>","content":"<text>","tags":"a,b"}   -- update note content, tags, or title
note_delete           {"id":"<note_id>"}                                   -- delete a note
note_rename           {"id":"<note_id>","new_id":"<new_path>"}             -- rename or move a note
note_graph            {}                                                   -- get the knowledge graph (nodes + edges + communities)
note_backlinks        {"id":"<note_id>"}                                   -- get backlinks pointing to a note
note_get_context      {}                                                   -- get AI-optimized overview of entire knowledge base (RECOMMENDED: use first!)
note_get_projects     {}                                                   -- get project cockpit (progress, tasks, health)
""" if _NOTES_AVAILABLE else ""

TOOL_DESCRIPTIONS = """
Available tools (emit JSON: {"action":"<name>","args":{...}}):

run_command      {"command":"<shell command>"}                        -- run any cmd/powershell command
read_file        {"path":"<abs path>"}                                -- read file contents
write_file       {"path":"<abs path>","content":"<text>"}             -- create/overwrite a file
edit_file        {"path":"<abs path>","old":"<text>","new":"<text>"}  -- search-and-replace in a file (shows diff)
patch_file       {"path":"<abs path>","patches":[{"old":"","new":""}]}-- multi-hunk diff editing (surgical edits)
delete_file      {"path":"<abs path>"}                                -- delete a file or directory
move_file        {"src":"<path>","dst":"<path>"}                      -- move/rename a file
list_files       {"path":"<dir>","pattern":"*.py","recursive":false}  -- list files in directory
search_files     {"path":"<dir>","pattern":"<regex>","file_pattern":"*.py"} -- grep-style search across files
glob_files       {"path":"<dir>","pattern":"**/*.py"}                 -- find files by name/glob pattern
fetch_url        {"url":"<url>"}                                      -- fetch a URL (docs, API specs, GitHub issues)
git_diff         {"mode":"status|diff|log"}                           -- check git status/diff/log
git_commit       {"message":"<msg>","push":false,"add_all":true}      -- stage and commit changes
open_app         {"app":"<name>"}                                     -- open an application
type_text        {"text":"<text>"}                                    -- type text via keyboard
open_file        {"path":"<abs path>"}                                -- open file with default app
take_screenshot  {}                                                   -- capture screen
web_search       {"query":"<search terms>"}                           -- search the web
browser_control  {"action":"go_to|search|click|type|scroll|screenshot|close","url":"...","query":"..."} -- automate Chrome/Edge/Firefox via Playwright
computer_control {"action":"type|click|move|drag|hotkey|press|scroll|copy|paste|screenshot|focus_window|screen_find|screen_click"} -- mouse, keyboard, screenshot, or AI screen finder
computer_settings {"action":"volume_up|volume_down|mute|volume_set|brightness_up|brightness_down|close_app|close_window|full_screen|minimize|maximize|snap_left|snap_right|switch_window|show_desktop|task_manager|dark_mode|toggle_wifi|restart|shutdown","value":"..."} -- adjust settings, display/window options, Wifi, power commands
dev_agent        {"description":"<build requirements>","language":"python|js|ts","project_name":"..."} -- multi-file workspace developer agent to plan, write, run, fix, and verify projects
file_processor   {"file_path":"<abs path>","action":"describe|ocr|resize|convert|compress|summarize|extract_text|to_word|stats|analyze|validate|format|run|transcribe|trim|list|extract"} -- process images, pdfs, text, data, code, audio, video, zip archives
remember_note    {"title":"<title>","content":"<text>"}               -- save note to memory
recall_notes     {"query":"<keyword>"}                                -- search saved notes
remember         {"key":"<k>","value":"<v>"}                          -- store a preference
recall           {"key":"<k>"}                                        -- retrieve a preference
update_shared_session {"key":"<k>","value":"<v>"}                     -- sync state across AI instances
self_evolve      {"prompt":"<what to improve/add>"}                   -- trigger self-evolution to improve/rewrite my own codebase
semantic_search  {"query":"<search query>","top_k":5}                 -- search codebase by semantic meaning (embedding-based, auto-indexes)
read_many_files  {"path":"<dir>","include":["**/*.py"],"exclude":["test_*"],"max_chars":50000} -- batch read files matching glob patterns
shell_background {"command":"<long running command>"}                  -- start a background process (returns PID)
shell_status     {"pid":<pid>}                                        -- check background process status and output
shell_kill       {"pid":<pid>}                                        -- kill a background process
""" + _NOTES_DESCRIPTION


def execute_tool(action: str, args: dict) -> str:
    fn = TOOLS.get(action)
    if fn is None:
        # Try legacy computer executor as fallback
        try:
            from actions.computer import execute_action
            result = execute_action(action, args)
            if result and "unknown" not in str(result).lower():
                return result
        except Exception:
            pass
        available = registry.get_all_names()
        return (
            f"Error: Unknown tool '{action}'. "
            f"Available tools: {', '.join(available)}"
        )

    # Git checkpoint before destructive file operations
    if action in ("write_file", "edit_file", "patch_file", "delete_file", "move_file"):
        try:
            from core.git_checkpoint import checkpoint_before_edit
            import os
            path = args.get("path", args.get("src", ""))
            cwd = os.getcwd()
            if checkpoint_before_edit(cwd, action, path):
                log.info(f"📌 Git checkpoint before {action}")
        except Exception as e:
            log.debug(f"Git checkpoint skipped: {e}")

    log.info(f"Executing tool: {action}({list(args.keys())})")
    try:
        result = fn(args)
    except Exception as e:
        log.error(f"Tool '{action}' raised exception: {e}", exc_info=True)
        result = f"Error executing {action}: {e}"
    log.info(f"Tool result ({action}): {str(result)[:120]}")
    return result


