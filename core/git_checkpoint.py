"""
Git checkpoint — auto-save before destructive file operations.

Creates a lightweight git commit before write_file, edit_file, patch_file,
delete_file, or move_file so the user can always `git revert HEAD` to undo.
"""

import subprocess
import logging
from pathlib import Path

log = logging.getLogger("mark.git_checkpoint")

# Track the last checkpoint to avoid spamming commits on rapid edits
_last_checkpoint_hash: str = ""


def _run_git(cmd: list, cwd: str, timeout: int = 10) -> tuple:
    """Run a git command, return (success, stdout)."""
    try:
        result = subprocess.run(
            ["git"] + cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        log.debug(f"git {' '.join(cmd)} failed: {e}")
        return False, ""


def _is_git_repo(working_dir: str) -> bool:
    """Check if the directory is inside a git repository."""
    ok, _ = _run_git(["rev-parse", "--is-inside-work-tree"], working_dir)
    return ok


def _init_repo(working_dir: str) -> bool:
    """Initialize a new git repo with an initial commit."""
    ok, _ = _run_git(["init"], working_dir)
    if not ok:
        return False
    # Create .gitignore for common excludes
    gitignore = Path(working_dir) / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "__pycache__/\n*.pyc\n.env\nnode_modules/\nvenv/\n"
            ".mark/\nlogs/\nmemory/\n*.db\n",
            encoding="utf-8",
        )
    _run_git(["add", "-A"], working_dir)
    _run_git(["commit", "-m", "Initial commit (MARK auto-init)", "--no-verify"], working_dir)
    log.info(f"Initialized git repo in {working_dir}")
    return True


def _has_changes(working_dir: str) -> bool:
    """Check if there are any uncommitted changes."""
    ok, output = _run_git(["status", "--porcelain"], working_dir)
    return ok and bool(output.strip())


def checkpoint_before_edit(working_dir: str, action: str, path: str) -> bool:
    """Create a git checkpoint before a destructive file operation.

    Args:
        working_dir: The project root directory
        action: The tool action name (write_file, edit_file, etc.)
        path: The file being modified

    Returns:
        True if a checkpoint was created, False otherwise
    """
    global _last_checkpoint_hash

    if not working_dir:
        return False

    # Ensure we're in a git repo
    if not _is_git_repo(working_dir):
        if not _init_repo(working_dir):
            log.warning("Could not initialize git repo for checkpointing")
            return False

    # Only checkpoint if there are actual changes
    if not _has_changes(working_dir):
        return False

    # Stage everything and commit
    _run_git(["add", "-A"], working_dir)

    basename = Path(path).name if path else "unknown"
    msg = f"📌 MARK checkpoint before {action} on {basename}"

    ok, _ = _run_git(
        ["commit", "-m", msg, "--no-verify", "--quiet"],
        working_dir,
    )

    if ok:
        # Store hash so we can detect duplicate checkpoints
        _, new_hash = _run_git(["rev-parse", "HEAD"], working_dir)
        if new_hash != _last_checkpoint_hash:
            _last_checkpoint_hash = new_hash
            log.info(f"Git checkpoint: {msg}")
            return True

    return False


def undo_last_edit(working_dir: str) -> str:
    """Revert the last MARK checkpoint commit.

    Returns a status message.
    """
    if not _is_git_repo(working_dir):
        return "Not a git repository."

    # Check if the last commit is a MARK checkpoint
    ok, msg = _run_git(["log", "-1", "--format=%s"], working_dir)
    if not ok:
        return "Could not read git log."

    if "MARK checkpoint" not in msg:
        return f"Last commit is not a MARK checkpoint: '{msg}'. Use `git revert` manually."

    # Show what would be reverted
    _, diff = _run_git(["diff", "HEAD~1", "--stat"], working_dir)

    # Revert
    ok, output = _run_git(["revert", "HEAD", "--no-edit"], working_dir)
    if ok:
        return f"✅ Reverted last checkpoint.\nFiles changed:\n{diff}"
    else:
        return f"❌ Revert failed: {output}"
