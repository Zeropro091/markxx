"""
MARK — Gemini Tool Declarations
Builds google.genai FunctionDeclaration objects for every tool in the registry.
"""


def build_tool_declarations_legacy():
    """Legacy SDK placeholder — returns None (not supported)."""
    return None


def build_tool_declarations():
    """Return a list containing a single genai_types.Tool with all FunctionDeclarations.

    Returns an empty list if google-genai is not installed.
    """
    try:
        from google.genai import types as genai_types
    except ImportError:
        return []

    try:
        S = "STRING"
        N = "NUMBER"
        B = "BOOLEAN"
        # A = "ARRAY"   # reserved for future use
        # O = "OBJECT"  # reserved for future use

        def _decl(name, desc, props, required=None):
            """Shorthand to build a FunctionDeclaration."""
            return genai_types.FunctionDeclaration(
                name=name,
                description=desc,
                parameters={
                    "type": "OBJECT",
                    "properties": props,
                    **({"required": required} if required else {}),
                },
            )

        declarations = []

        # ══════════════════════════════════════════════════════════════════════
        #  Shell / System
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "run_command",
            "Run a shell command (cmd/powershell) and return stdout+stderr. Timeout 30s.",
            {"command": {"type": S, "description": "The shell command to execute"}},
            ["command"],
        ))

        declarations.append(_decl(
            "open_app",
            "Open an application by name (e.g. 'notepad', 'chrome', 'code').",
            {"app": {"type": S, "description": "Application name or path to open"}},
            ["app"],
        ))

        declarations.append(_decl(
            "type_text",
            "Type text via keyboard input.",
            {"text": {"type": S, "description": "Text to type"}},
            ["text"],
        ))

        declarations.append(_decl(
            "open_file",
            "Open a file with its default system application.",
            {"path": {"type": S, "description": "Absolute path to the file"}},
            ["path"],
        ))

        declarations.append(_decl(
            "take_screenshot",
            "Capture a screenshot of the current screen.",
            {},
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  File Operations
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "read_file",
            "Read a file's contents (max ~500KB, returns first 8000 chars).",
            {"path": {"type": S, "description": "Absolute path to the file"}},
            ["path"],
        ))

        declarations.append(_decl(
            "write_file",
            "Create or overwrite a file with the given content.",
            {
                "path":    {"type": S, "description": "Absolute path to the file"},
                "content": {"type": S, "description": "Full text content to write"},
            },
            ["path", "content"],
        ))

        declarations.append(_decl(
            "edit_file",
            "Search-and-replace in a file. Finds 'old' text and replaces with 'new'. Shows unified diff.",
            {
                "path": {"type": S, "description": "Absolute path to the file"},
                "old":  {"type": S, "description": "Exact text to find in the file"},
                "new":  {"type": S, "description": "Replacement text"},
            },
            ["path", "old", "new"],
        ))

        declarations.append(_decl(
            "patch_file",
            "Apply multiple search-and-replace hunks to a file in one call. More surgical than edit_file.",
            {
                "path": {"type": S, "description": "Absolute path to the file"},
                "patches": {
                    "type": "ARRAY",
                    "description": "List of patch hunks, each with 'old' and 'new' keys",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "old": {"type": S, "description": "Exact text to find"},
                            "new": {"type": S, "description": "Replacement text"},
                        },
                        "required": ["old", "new"],
                    },
                },
            },
            ["path", "patches"],
        ))

        declarations.append(_decl(
            "delete_file",
            "Delete a file or directory (recursive for directories).",
            {"path": {"type": S, "description": "Absolute path to delete"}},
            ["path"],
        ))

        declarations.append(_decl(
            "move_file",
            "Move or rename a file or directory.",
            {
                "src": {"type": S, "description": "Source path"},
                "dst": {"type": S, "description": "Destination path"},
            },
            ["src", "dst"],
        ))

        declarations.append(_decl(
            "list_files",
            "List files and directories. Supports glob patterns and recursive listing.",
            {
                "path":      {"type": S, "description": "Directory path to list (default '.')"},
                "pattern":   {"type": S, "description": "Glob pattern filter (default '*')"},
                "recursive": {"type": B, "description": "If true, search recursively (default false)"},
            },
            ["path"],
        ))

        declarations.append(_decl(
            "search_files",
            "Grep-style regex search across files. Returns matching lines with line numbers.",
            {
                "path":         {"type": S, "description": "Root directory to search in"},
                "pattern":      {"type": S, "description": "Regex pattern to search for"},
                "file_pattern": {"type": S, "description": "Glob to filter filenames (default '*')"},
            },
            ["path", "pattern"],
        ))

        declarations.append(_decl(
            "glob_files",
            "Find files by name/glob pattern. Returns paths with sizes.",
            {
                "path":    {"type": S, "description": "Root directory"},
                "pattern": {"type": S, "description": "Glob pattern (e.g. '**/*.py')"},
            },
            ["path", "pattern"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Network / Web
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "fetch_url",
            "Fetch a URL and return text content. Handles HTML (strips tags), JSON, and plain text.",
            {"url": {"type": S, "description": "The URL to fetch"}},
            ["url"],
        ))

        declarations.append(_decl(
            "web_search",
            "Search the web using DuckDuckGo and return top result snippets.",
            {"query": {"type": S, "description": "Search query string"}},
            ["query"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Git
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "git_diff",
            "Check git repository state. Modes: status, diff, diff_staged, log.",
            {"mode": {"type": S, "description": "One of: status, diff, diff_staged, log"}},
            ["mode"],
        ))

        declarations.append(_decl(
            "git_commit",
            "Stage changes and commit. Optionally push to remote.",
            {
                "message": {"type": S, "description": "Commit message"},
                "push":    {"type": B, "description": "Push to remote after commit (default false)"},
                "add_all": {"type": B, "description": "Stage all changes with git add -A (default true)"},
            },
            ["message"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Browser Automation (Playwright)
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "browser_control",
            "Automate Chrome/Edge/Firefox via Playwright. Actions: go_to, search, click, type, scroll, screenshot, close.",
            {
                "action":   {"type": S, "description": "Action: go_to|search|click|type|scroll|screenshot|close"},
                "url":      {"type": S, "description": "URL to navigate to (for go_to)"},
                "query":    {"type": S, "description": "Search query (for search action)"},
                "selector": {"type": S, "description": "CSS/XPath selector (for click/type)"},
                "text":     {"type": S, "description": "Text to type (for type action)"},
            },
            ["action"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Computer Control (mouse, keyboard, screen)
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "computer_control",
            "Low-level computer control: mouse clicks, keyboard input, drag/drop, screenshots, AI screen-find. "
            "Actions: type, click, move, drag, hotkey, press, scroll, copy, paste, screenshot, focus_window, screen_find, screen_click.",
            {
                "action":       {"type": S, "description": "Action: type|click|move|drag|hotkey|press|scroll|copy|paste|screenshot|focus_window|screen_find|screen_click"},
                "text":         {"type": S, "description": "Text to type or window title (for focus_window)"},
                "x":            {"type": N, "description": "X coordinate for click/move/drag"},
                "y":            {"type": N, "description": "Y coordinate for click/move/drag"},
                "key":          {"type": S, "description": "Key name for press action (e.g. 'enter', 'tab')"},
                "keys":         {"type": S, "description": "Key combo for hotkey (e.g. 'ctrl+c')"},
                "dx":           {"type": N, "description": "Horizontal scroll delta"},
                "dy":           {"type": N, "description": "Vertical scroll delta"},
                "window_title": {"type": S, "description": "Window title for focus_window"},
                "target_text":  {"type": S, "description": "Text to find on screen (for screen_find/screen_click)"},
            },
            ["action"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Computer Settings
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "computer_settings",
            "Adjust system settings: volume, brightness, dark mode, wifi, window management, power. "
            "Actions: volume_up, volume_down, mute, volume_set, brightness_up, brightness_down, "
            "close_app, close_window, full_screen, minimize, maximize, snap_left, snap_right, "
            "switch_window, show_desktop, task_manager, dark_mode, toggle_wifi, restart, shutdown.",
            {
                "action": {"type": S, "description": "Settings action to perform"},
                "value":  {"type": S, "description": "Value for the action (e.g. volume level '50')"},
            },
            ["action"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Dev Agent
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "dev_agent",
            "Trigger a developer agent to plan, write, test, build, and debug software projects.",
            {
                "description":  {"type": S, "description": "What to build — full requirements description"},
                "language":     {"type": S, "description": "Programming language: python, js, ts, etc."},
                "project_name": {"type": S, "description": "Name for the project directory"},
            },
            ["description"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  File Processor
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "file_processor",
            "Process files: describe, OCR, resize, convert, compress, summarize, extract_text, "
            "to_word, stats, analyze, validate, format, run, transcribe, trim, list, extract. "
            "Supports images, PDFs, audio, video, JSON, CSV, DOCX, PPTX, ZIP, code files.",
            {
                "file_path": {"type": S, "description": "Absolute path to the file"},
                "action":    {"type": S, "description": "Processing action to perform"},
            },
            ["file_path", "action"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Memory / Notes / Session
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "remember_note",
            "Save a note to Nemesi (the user's second brain / memory system).",
            {
                "title":   {"type": S, "description": "Note title"},
                "content": {"type": S, "description": "Note content (markdown supported)"},
            },
            ["title", "content"],
        ))

        declarations.append(_decl(
            "recall_notes",
            "Search saved notes in Nemesi by keyword.",
            {"query": {"type": S, "description": "Keyword to search for"}},
            ["query"],
        ))

        declarations.append(_decl(
            "read_user_profile",
            "Read the AI-synthesized user profile from Nemesi.",
            {},
        ))

        declarations.append(_decl(
            "update_shared_session",
            "Update the shared session state (SHARED_SESSION.json) across AI instances.",
            {
                "key":   {"type": S, "description": "Session key to set"},
                "value": {"type": S, "description": "Value to store"},
            },
            ["key", "value"],
        ))

        declarations.append(_decl(
            "self_evolve",
            "Trigger self-evolution to improve or extend MARK's own codebase.",
            {"prompt": {"type": S, "description": "What to improve, add, or change"}},
            ["prompt"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Codebase Semantic Search
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "semantic_search",
            "Search the current codebase using semantic similarity (embedding-based). "
            "Finds code chunks by meaning, not just text matching. Auto-indexes on first use.",
            {
                "query":  {"type": S, "description": "Natural language search query (e.g. 'function that handles authentication')"},
                "top_k":  {"type": N, "description": "Number of results to return (default 5)"},
            },
            ["query"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Batch File Reading
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "read_many_files",
            "Read multiple files matching glob patterns in one call. Returns concatenated file contents with headers. "
            "Skips binary files, .git, node_modules, etc. Respects max_chars limit.",
            {
                "path":      {"type": S, "description": "Base directory to read from (default '.')"},
                "include":   {
                    "type": "ARRAY",
                    "description": "Glob patterns to include (default ['**/*'])",
                    "items": {"type": S},
                },
                "exclude":   {
                    "type": "ARRAY",
                    "description": "Glob patterns to exclude (default [])",
                    "items": {"type": S},
                },
                "max_chars": {"type": N, "description": "Maximum total characters to return (default 50000)"},
            },
            ["path"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Background Shell Processes
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "shell_background",
            "Start a shell command as a background process. Returns PID for later status checks or killing. "
            "Use for long-running commands like dev servers, builds, or watchers.",
            {"command": {"type": S, "description": "Shell command to run in the background"}},
            ["command"],
        ))

        declarations.append(_decl(
            "shell_status",
            "Check the status of a background process by PID. Returns running/exited state and captured stdout/stderr.",
            {"pid": {"type": N, "description": "Process ID returned by shell_background"}},
            ["pid"],
        ))

        declarations.append(_decl(
            "shell_kill",
            "Terminate a background process by PID. Attempts graceful termination, falls back to force kill.",
            {"pid": {"type": N, "description": "Process ID to kill"}},
            ["pid"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Optional: Note-Taking App Integration
        # ══════════════════════════════════════════════════════════════════════

        try:
            # Only declare if the notes module is importable
            from actions.notes import note_list as _  # noqa: F401

            declarations.append(_decl(
                "note_list",
                "List all notes in the knowledge base.",
                {},
            ))

            declarations.append(_decl(
                "note_read",
                "Read a specific note by ID. Returns content and metadata.",
                {"id": {"type": S, "description": "Note ID to read"}},
                ["id"],
            ))

            declarations.append(_decl(
                "note_search",
                "Full-text fuzzy search across all notes.",
                {"query": {"type": S, "description": "Search term"}},
                ["query"],
            ))

            declarations.append(_decl(
                "note_search_semantic",
                "AI-powered semantic (meaning-based) search across notes.",
                {"query": {"type": S, "description": "Semantic search query"}},
                ["query"],
            ))

            declarations.append(_decl(
                "note_create",
                "Create a new note in the knowledge base.",
                {
                    "path":    {"type": S, "description": "Note path (e.g. 'Projects/My-Idea')"},
                    "title":   {"type": S, "description": "Note title"},
                    "content": {"type": S, "description": "Note content (markdown)"},
                },
                ["path", "title", "content"],
            ))

            declarations.append(_decl(
                "note_update",
                "Update an existing note's content and/or tags.",
                {
                    "id":      {"type": S, "description": "Note ID to update"},
                    "content": {"type": S, "description": "New content (optional)"},
                    "tags":    {"type": S, "description": "Comma-separated tags (optional)"},
                },
                ["id"],
            ))

            declarations.append(_decl(
                "note_delete",
                "Delete a note from the knowledge base.",
                {"id": {"type": S, "description": "Note ID to delete"}},
                ["id"],
            ))

            declarations.append(_decl(
                "note_rename",
                "Rename or move a note to a new ID/path.",
                {
                    "id":     {"type": S, "description": "Current note ID"},
                    "new_id": {"type": S, "description": "New note ID/path"},
                },
                ["id", "new_id"],
            ))

            declarations.append(_decl(
                "note_graph",
                "Get the knowledge graph: nodes, edges, and communities.",
                {},
            ))

            declarations.append(_decl(
                "note_backlinks",
                "Get all backlinks (incoming references) pointing to a note.",
                {"id": {"type": S, "description": "Note ID to find backlinks for"}},
                ["id"],
            ))

            declarations.append(_decl(
                "note_get_context",
                "Get AI-optimized overview of the entire knowledge base. Recommended as a first call.",
                {},
            ))

            declarations.append(_decl(
                "note_get_projects",
                "Get the project cockpit: progress, tasks, and health for all projects.",
                {},
            ))

        except (ImportError, SyntaxError, Exception):
            pass  # Note tools not available — skip their declarations

        # ══════════════════════════════════════════════════════════════════════
        #  LSP (Language Server Protocol) tool
        # ══════════════════════════════════════════════════════════════════════

        declarations.append(_decl(
            "lsp",
            "Query Language Server for IDE-level code intelligence. Operations: "
            "goToDefinition (jump to definition), findReferences (find all usages), "
            "hover (get type info/docs), documentSymbol (list all symbols in file).",
            {
                "operation": {"type": S, "description": "LSP operation: goToDefinition | findReferences | hover | documentSymbol"},
                "file": {"type": S, "description": "Absolute path to the source file"},
                "line": {"type": N, "description": "Line number (1-based)"},
                "character": {"type": N, "description": "Character offset (1-based)"},
            },
            ["operation", "file"],
        ))

        # ══════════════════════════════════════════════════════════════════════
        #  Bundle into a single Tool object
        # ══════════════════════════════════════════════════════════════════════

        return [genai_types.Tool(function_declarations=declarations)]

    except Exception:
        return []
