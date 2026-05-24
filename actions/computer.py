"""
MARK-XX — Computer Control Actions
Open apps, run commands, manage files, type text, click.
"""

import os
import sys
import subprocess
import shutil
import platform
from pathlib import Path
from typing import Dict, Any, Optional


OS = platform.system()   # "Windows", "Darwin", "Linux"


def execute_action(action: str, args: Dict[str, Any]) -> str:
    """Route an action name to the correct handler. Returns a result string."""
    handlers = {
        "open_app":     action_open_app,
        "run_command":  action_run_command,
        "type_text":    action_type_text,
        "open_file":    action_open_file,
        "create_file":  action_create_file,
        "delete_file":  action_delete_file,
        "list_files":   action_list_files,
        "move_file":    action_move_file,
        "web_search":   action_web_search,
    }
    handler = handlers.get(action)
    if handler:
        try:
            return handler(**args)
        except TypeError as e:
            return f"Action '{action}' argument error: {e}"
        except Exception as e:
            return f"Action '{action}' failed: {e}"
    return f"Unknown action: {action}"


# ── App Launcher ───────────────────────────────────────────────────────────────
# Maps friendly names → Windows executable / protocol
APP_MAP_WINDOWS = {
    # Built-ins
    "notepad":          "notepad.exe",
    "calculator":       "calc.exe",
    "paint":            "mspaint.exe",
    "explorer":         "explorer.exe",
    "file explorer":    "explorer.exe",
    "task manager":     "taskmgr.exe",
    "cmd":              "cmd.exe",
    "command prompt":   "cmd.exe",
    "powershell":       "powershell.exe",
    "terminal":         "wt.exe",          # Windows Terminal
    "control panel":    "control.exe",
    "snipping tool":    "snippingtool.exe",
    "snip":             "snippingtool.exe",
    "wordpad":          "wordpad.exe",
    "settings":         "ms-settings:",
    # Browsers
    "chrome":           "chrome",
    "google chrome":    "chrome",
    "firefox":          "firefox",
    "edge":             "msedge",
    "microsoft edge":   "msedge",
    "brave":            "brave",
    # Microsoft Office
    "word":             "winword",
    "microsoft word":   "winword",
    "excel":            "excel",
    "microsoft excel":  "excel",
    "powerpoint":       "powerpnt",
    "outlook":          "outlook",
    "onenote":          "onenote",
    "access":           "msaccess",
    # Media / Apps
    "spotify":          "spotify",
    "discord":          "discord",
    "vlc":              "vlc",
    "steam":            "steam",
    "obs":              "obs64",
    "vscode":           "code",
    "visual studio code": "code",
    "vs code":          "code",
    "sublime":          "subl",
    "pycharm":          "pycharm",
    "zoom":             "zoom",
    "teams":            "teams",
    "microsoft teams":  "teams",
    "skype":            "skype",
    "telegram":         "telegram",
    "whatsapp":         "whatsapp",
    "slack":            "slack",
}


def action_open_app(app: str, **_) -> str:
    app_lower = app.lower().strip()

    if OS == "Windows":
        mapped = APP_MAP_WINDOWS.get(app_lower, app_lower)

        # ms-settings: and similar protocols
        if ":" in mapped and not mapped.endswith(".exe"):
            try:
                subprocess.Popen(["cmd", "/c", "start", "", mapped])
                return f"Opened {app}."
            except Exception as e:
                return f"Could not open '{app}': {e}"

        # Use 'start' command — this resolves Office, Chrome, etc. from registry
        try:
            subprocess.Popen(f'start "" "{mapped}"', shell=True)
            return f"Opened {app}."
        except Exception as e1:
            # Fallback 1: shutil.which
            exe = shutil.which(mapped) or shutil.which(mapped + ".exe")
            if exe:
                try:
                    subprocess.Popen([exe])
                    return f"Opened {app}."
                except Exception as e2:
                    return f"Could not open '{app}': {e2}"

            # Fallback 2: try the raw name via start
            try:
                subprocess.Popen(f'start "" "{app}"', shell=True)
                return f"Tried to open {app}."
            except Exception as e3:
                return f"Could not open '{app}': {e1}"

    elif OS == "Darwin":
        try:
            subprocess.Popen(["open", "-a", app])
            return f"Opened {app}."
        except Exception:
            try:
                subprocess.Popen(["open", app])
                return f"Opened {app}."
            except Exception as e:
                return f"Could not open '{app}': {e}"

    else:  # Linux
        mapped = APP_MAP_WINDOWS.get(app_lower, app_lower)
        for candidate in [mapped, app_lower, app]:
            exe = shutil.which(candidate)
            if exe:
                try:
                    subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return f"Opened {app}."
                except Exception as e:
                    return f"Could not open '{app}': {e}"
        # Last resort: xdg-open
        try:
            subprocess.Popen(["xdg-open", app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Tried to open {app}."
        except Exception as e:
            return f"Could not open '{app}': {e}"


# ── Terminal / Shell ────────────────────────────────────────────────────────────
def action_run_command(cmd: str, shell: bool = True, **_) -> str:
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip()
        if result.returncode != 0:
            return f"Command exited with code {result.returncode}:\n{output}"
        return output if output else "Command executed successfully."
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Command error: {e}"


# ── Keyboard Input ──────────────────────────────────────────────────────────────
def action_type_text(text: str, **_) -> str:
    try:
        import pyautogui
        pyautogui.write(text, interval=0.03)
        return f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}"
    except ImportError:
        return "pyautogui not available for typing."
    except Exception as e:
        return f"Type error: {e}"


# ── File Operations ─────────────────────────────────────────────────────────────
def action_open_file(path: str, **_) -> str:
    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"
    try:
        if OS == "Windows":
            os.startfile(str(p))
        elif OS == "Darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return f"Opened file: {p.name}"
    except Exception as e:
        return f"Could not open file: {e}"


def action_create_file(path: str, content: str = "", **_) -> str:
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Created file: {path}"
    except Exception as e:
        return f"Could not create file: {e}"


def action_delete_file(path: str, **_) -> str:
    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"
    try:
        if p.is_file():
            p.unlink()
        else:
            shutil.rmtree(p)
        return f"Deleted: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def action_list_files(path: str = ".", **_) -> str:
    p = Path(path)
    if not p.exists():
        return f"Directory not found: {path}"
    try:
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = []
        for e in entries[:50]:
            icon = "📁" if e.is_dir() else "📄"
            size = f" ({e.stat().st_size:,} bytes)" if e.is_file() else ""
            lines.append(f"{icon} {e.name}{size}")
        result = "\n".join(lines)
        if len(entries) > 50:
            result += f"\n... and {len(entries) - 50} more"
        return result or "Empty directory."
    except Exception as e:
        return f"Could not list directory: {e}"


def action_move_file(src: str, dst: str, **_) -> str:
    s, d = Path(src), Path(dst)
    if not s.exists():
        return f"Source not found: {src}"
    try:
        shutil.move(str(s), str(d))
        return f"Moved '{s.name}' → '{dst}'"
    except Exception as e:
        return f"Move failed: {e}"


# ── Web Search ──────────────────────────────────────────────────────────────────
def action_web_search(query: str, **_) -> str:
    import urllib.parse
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    try:
        if OS == "Windows":
            os.startfile(url)
        elif OS == "Darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        return f"Opened browser for: {query}"
    except Exception as e:
        return f"Could not open browser: {e}"
