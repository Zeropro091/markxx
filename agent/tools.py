"""
MARK — Tool Registry
All tools MARK can call in its agentic loop.
Each tool is a function: (args: dict) -> str result
"""

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
)


# ══════════════════════════════════════════════════════════════════════════════
# Registry
# ══════════════════════════════════════════════════════════════════════════════

TOOLS: Dict[str, Callable] = {
    "run_command":           tool_run_command,
    "read_file":             tool_read_file,
    "write_file":            tool_write_file,
    "edit_file":             tool_edit_file,
    "patch_file":            tool_patch_file,
    "delete_file":           tool_delete_file,
    "move_file":             tool_move_file,
    "list_files":            tool_list_files,
    "search_files":          tool_search_files,
    "glob_files":            tool_glob_files,
    "fetch_url":             tool_fetch_url,
    "git_diff":              tool_git_diff,
    "git_commit":            tool_git_commit,
    "open_app":              tool_open_app,
    "type_text":             tool_type_text,
    "open_file":             tool_open_file,
    "take_screenshot":       tool_take_screenshot,
    "web_search":            tool_web_search,
    "remember_note":         tool_remember_note,
    "recall_notes":          tool_recall_notes,
    "read_user_profile":     tool_read_user_profile,
    "update_shared_session": tool_update_shared_session,
    "remember":              tool_remember,
    "recall":                tool_recall,
}

# ── Optional note-taking tools ────────────────────────────────────────────────
try:
    from actions.notes import (
        note_list, note_read, note_search, note_create,
        note_update, note_delete, note_graph, note_backlinks,
    )
    TOOLS.update({
        "note_list":      note_list,
        "note_read":      note_read,
        "note_search":    note_search,
        "note_create":    note_create,
        "note_update":    note_update,
        "note_delete":    note_delete,
        "note_graph":     note_graph,
        "note_backlinks": note_backlinks,
    })
    _NOTES_AVAILABLE = True
except (ImportError, SyntaxError, Exception):
    _NOTES_AVAILABLE = False

_NOTES_DESCRIPTION = """
note_list        {}                                                   -- list all notes
note_read        {"id":"<note_id>"}                                   -- read a note (returns content + metadata)
note_search      {"query":"<search term>"}                            -- search notes by content
note_create      {"id":"<path>","title":"<Title>"}                   -- create a new note
note_update      {"id":"<note_id>","content":"<text>"}               -- update note content
note_delete      {"id":"<note_id>"}                                   -- delete a note
note_graph       {}                                                   -- get the knowledge graph (nodes + edges)
note_backlinks   {"id":"<note_id>"}                                   -- get backlinks pointing to a note
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
remember_note    {"title":"<title>","content":"<text>"}               -- save note to memory
recall_notes     {"query":"<keyword>"}                                -- search saved notes
remember         {"key":"<k>","value":"<v>"}                          -- store a preference
recall           {"key":"<k>"}                                        -- retrieve a preference
update_shared_session {"key":"<k>","value":"<v>"}                     -- sync state across AI instances
""" + _NOTES_DESCRIPTION


def execute_tool(action: str, args: dict) -> str:
    fn = TOOLS.get(action)
    if fn is None:
        # Fallback to old computer executor
        from actions.computer import execute_action
        return execute_action(action, args)
    log.info(f"Executing tool: {action}({list(args.keys())})")
    result = fn(args)
    log.info(f"Tool result ({action}): {str(result)[:120]}")
    return result
