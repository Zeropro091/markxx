"""
MARK — CLI-specific Tools
Extended tool set for the CLI agent mode: editing, searching, file management,
git integration, URL fetching. These complement the base tools in agent/tools.py.
"""

import os
import re
import difflib
import shutil
import subprocess
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Optional

from core.logger import get_logger
log = get_logger("cli_tools")


def tool_edit_file(args: dict) -> str:
    """Search-and-replace editing. Finds `old` text in a file and replaces with `new`."""
    path = args.get("path", "")
    old  = args.get("old", "")
    new  = args.get("new", "")
    if not path:
        return "Error: no path provided"
    if not old:
        return "Error: no 'old' text to search for"

    try:
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"

        content = p.read_text(encoding="utf-8", errors="replace")
        count = content.count(old)
        if count == 0:
            # Show nearby lines to help the LLM adjust
            first_line = old.strip().split("\n")[0][:60]
            lines = content.split("\n")
            near = []
            for i, line in enumerate(lines):
                if first_line.lower() in line.lower():
                    start = max(0, i - 1)
                    end = min(len(lines), i + 2)
                    near.append(f"  Line {i+1}: {lines[i].rstrip()}")
            context = "\n".join(near[:5]) if near else "(no similar lines found)"
            return f"Error: 'old' text not found in {path}. Similar lines:\n{context}"

        new_content = content.replace(old, new)

        # Generate diff
        diff_lines = list(difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after)",
        ))
        diff_text = "".join(diff_lines)
        if len(diff_text) > 2000:
            diff_text = diff_text[:2000] + "\n... (diff truncated)"

        p.write_text(new_content, encoding="utf-8")
        log.info(f"Edited {path}: {count} replacement(s)")
        return f"Edited {path}: replaced {count} occurrence(s)\n{diff_text}"

    except Exception as e:
        return f"Error editing file: {e}"


def tool_delete_file(args: dict) -> str:
    """Delete a file or directory."""
    path = args.get("path", "")
    if not path:
        return "Error: no path provided"

    try:
        p = Path(path)
        if not p.exists():
            return f"Error: not found: {path}"
        if p.is_dir():
            shutil.rmtree(p)
            return f"Deleted directory: {path}"
        else:
            p.unlink()
            return f"Deleted file: {path}"
    except Exception as e:
        return f"Error deleting: {e}"


def tool_move_file(args: dict) -> str:
    """Move or rename a file/directory."""
    src = args.get("src", "")
    dst = args.get("dst", "")
    if not src or not dst:
        return "Error: need both 'src' and 'dst' paths"

    try:
        s = Path(src)
        d = Path(dst)
        if not s.exists():
            return f"Error: source not found: {src}"
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"Moved: {src} -> {dst}"
    except Exception as e:
        return f"Error moving: {e}"


def tool_search_files(args: dict) -> str:
    """Search for a pattern in files (like grep). Returns matching lines with line numbers."""
    path         = args.get("path", ".")
    pattern      = args.get("pattern", "")
    file_pattern = args.get("file_pattern", "*")
    case_insensitive = args.get("ignore_case", True)

    if not pattern:
        return "Error: no search pattern provided"

    try:
        root = Path(path)
        if not root.exists():
            return f"Error: path not found: {path}"

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: invalid regex pattern: {e}"

        results = []
        files_searched = 0
        for fp in root.rglob(file_pattern):
            if not fp.is_file():
                continue
            # Skip binary/common non-text dirs
            skip_parts = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist", "build"}
            if any(part in fp.parts for part in skip_parts):
                continue
            if fp.stat().st_size > 200_000:
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            files_searched += 1
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    results.append(f"{fp}:{i}: {line.strip()}")
                    if len(results) >= 50:
                        break
            if len(results) >= 50:
                break

        if not results:
            return f"No matches for '{pattern}' in {files_searched} file(s)"
        header = f"Found {len(results)} match(es) in {files_searched} file(s):\n"
        return header + "\n".join(results)

    except Exception as e:
        return f"Error searching: {e}"


def tool_glob_files(args: dict) -> str:
    """Find files by name/glob pattern."""
    path    = args.get("path", ".")
    pattern = args.get("pattern", "**/*")

    try:
        root = Path(path)
        if not root.exists():
            return f"Error: path not found: {path}"

        skip_parts = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist", "build"}
        files = []
        for fp in root.glob(pattern):
            if any(part in fp.parts for part in skip_parts):
                continue
            if fp.is_file():
                size = fp.stat().st_size
                files.append((fp, size))

        if not files:
            return f"No files matching '{pattern}' in {path}"

        files.sort(key=lambda x: x[1], reverse=True)
        lines = []
        for fp, size in files[:100]:
            size_str = f"{size:,}" if size < 1024 else f"{size/1024:.1f}KB"
            lines.append(f"  {size_str:>10}  {fp}")

        return f"{len(files)} file(s) matching '{pattern}':\n" + "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 2: FetchURL — curl documentation, API specs, or GitHub issues
# ══════════════════════════════════════════════════════════════════════════════

def tool_fetch_url(args: dict) -> str:
    """Fetch a URL and return the text content. Useful for reading docs, API specs, etc."""
    url = args.get("url", "")
    if not url:
        return "Error: no URL provided"

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "MARK-XX/1.0 (AI Agent)",
            "Accept": "text/html,text/plain,application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()

            # Handle JSON
            if "json" in content_type or url.endswith(".json"):
                data = json.loads(raw.decode("utf-8", errors="replace"))
                text = json.dumps(data, indent=2, ensure_ascii=False)
                return text[:6000]

            # Handle HTML — strip tags
            text = raw.decode("utf-8", errors="replace")
            if "html" in content_type.lower():
                # Remove script/style blocks
                text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', text, flags=re.I)
                text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=re.I)
                # Remove HTML tags
                text = re.sub(r'<[^>]+>', ' ', text)
                # Collapse whitespace
                text = re.sub(r'\s+', ' ', text).strip()

            return text[:6000] if text else "(empty response)"

    except urllib.error.HTTPError as e:
        return f"HTTP Error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"URL Error: {e.reason}"
    except Exception as e:
        return f"Error fetching URL: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 2: ReadGitDiff — check what changed before starting work
# ══════════════════════════════════════════════════════════════════════════════

def tool_git_diff(args: dict) -> str:
    """Check git status, diff, or log. Understands what changed in the repo."""
    mode = args.get("mode", "status")  # status, diff, log, diff_staged

    try:
        if mode == "status":
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            )
            out = result.stdout.strip()
            if not out:
                return "Git: working tree clean (no changes)"
            return f"Git status:\n{out}"

        elif mode == "diff":
            result = subprocess.run(
                ["git", "diff"],
                capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
            )
            out = result.stdout.strip()
            if not out:
                return "No unstaged changes"
            return out[:4000]

        elif mode == "diff_staged":
            result = subprocess.run(
                ["git", "diff", "--cached"],
                capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
            )
            out = result.stdout.strip()
            if not out:
                return "No staged changes"
            return out[:4000]

        elif mode == "log":
            n = args.get("count", 10)
            result = subprocess.run(
                ["git", "log", f"-{n}", "--oneline", "--decorate"],
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            )
            return result.stdout.strip() or "(no commits)"

        else:
            return f"Error: unknown mode '{mode}'. Use: status, diff, diff_staged, log"

    except FileNotFoundError:
        return "Error: git is not installed"
    except subprocess.TimeoutExpired:
        return "Error: git command timed out"
    except Exception as e:
        return f"Error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 2: GitAutoCommit — auto-commit with semantic message
# ══════════════════════════════════════════════════════════════════════════════

def tool_git_commit(args: dict) -> str:
    """Stage all changes and commit with a message. Optionally push."""
    message = args.get("message", "")
    push = args.get("push", False)
    add_all = args.get("add_all", True)

    if not message:
        return "Error: commit message is required"

    try:
        # Stage files
        if add_all:
            subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            )
        else:
            files = args.get("files", [])
            if not files:
                return "Error: no files specified and add_all is false"
            for f in files:
                subprocess.run(
                    ["git", "add", f],
                    capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
                )

        # Check if there's anything to commit
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
        )
        if not status.stdout.strip():
            return "Nothing to commit (working tree clean)"

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            return f"Commit failed: {result.stderr.strip()}"

        output = f"Committed: {message}"

        # Optionally push
        if push:
            push_result = subprocess.run(
                ["git", "push"],
                capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
            )
            if push_result.returncode == 0:
                output += "\nPushed to remote"
            else:
                output += f"\nPush failed: {push_result.stderr.strip()}"

        return output

    except FileNotFoundError:
        return "Error: git is not installed"
    except Exception as e:
        return f"Error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# Pillar 2: PatchFile — Multi-hunk diff editing (surgical edits)
# ══════════════════════════════════════════════════════════════════════════════

def tool_patch_file(args: dict) -> str:
    """Apply a multi-hunk diff patch to a file. More surgical than edit_file.

    Accepts a list of patches, each with 'old' and 'new' text.
    This allows making multiple targeted changes in one tool call
    without rewriting the entire file.
    """
    path = args.get("path", "")
    patches = args.get("patches", [])

    if not path:
        return "Error: no path provided"
    if not patches:
        # Fall back to single edit mode
        return tool_edit_file(args)

    try:
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"

        content = p.read_text(encoding="utf-8", errors="replace")
        original = content
        results = []
        failures = []

        for i, patch in enumerate(patches):
            old = patch.get("old", "")
            new = patch.get("new", "")
            if not old:
                failures.append(f"Patch {i+1}: no 'old' text")
                continue

            if old not in content:
                failures.append(f"Patch {i+1}: 'old' text not found")
                continue

            count = content.count(old)
            if count > 1:
                failures.append(f"Patch {i+1}: 'old' text found {count} times (ambiguous, add more context)")
                continue

            content = content.replace(old, new, 1)
            results.append(f"Patch {i+1}: applied")

        if not results:
            return f"No patches applied.\n" + "\n".join(failures)

        # Generate unified diff
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after)",
        ))
        diff_text = "".join(diff_lines)
        if len(diff_text) > 2000:
            diff_text = diff_text[:2000] + "\n... (diff truncated)"

        # Write the patched file
        p.write_text(content, encoding="utf-8")

        summary = f"Patched {path}: {len(results)}/{len(patches)} hunk(s) applied"
        if failures:
            summary += f"\nFailures:\n" + "\n".join(f"  {f}" for f in failures)
        summary += f"\n{diff_text}"

        log.info(f"Patched {path}: {len(results)}/{len(patches)} hunks")
        return summary

    except Exception as e:
        return f"Error patching file: {e}"
