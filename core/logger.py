"""
MARK-XX — Centralized Logging
Rotating file log + console. Import `get_logger` anywhere.
"""

import logging
import logging.handlers
import sys
import os
from pathlib import Path


# ── Paths ──────────────────────────────────────────────────────────────────────
LOG_DIR  = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "mark.log"
LOG_DIR.mkdir(exist_ok=True)

# ── Formats ───────────────────────────────────────────────────────────────────
FMT_FILE    = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
FMT_CONSOLE = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATEFMT     = "%Y-%m-%d %H:%M:%S"


def _setup_root_logger() -> logging.Logger:
    root = logging.getLogger("mark")
    if root.handlers:          # already configured (multi-import guard)
        return root

    root.setLevel(logging.DEBUG)

    # ── Rotating file (10 MB × 5 backups) ────────────────────────────────────
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5,
        encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FMT_FILE, datefmt=DATEFMT))
    root.addHandler(fh)

    # ── Console ───────────────────────────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    if os.getenv("MARK_CLI") == "1":
        ch.setLevel(logging.WARNING)
    else:
        ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(FMT_CONSOLE, datefmt=DATEFMT))
    # Fix Windows CP1252 console encoding for emoji/arrows in log messages
    if hasattr(ch.stream, 'reconfigure'):
        try: ch.stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception: pass
    root.addHandler(ch)

    root.info("=" * 70)
    root.info("MARK-XX  starting up")
    root.info("=" * 70)
    return root


_ROOT = _setup_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Return a child logger. Usage: log = get_logger(__name__)"""
    return _ROOT.getChild(name.replace(".", "_"))


def get_log_path() -> Path:
    return LOG_FILE
