"""
MARK-XX — Language-aware File Chunker
Splits source files into semantically meaningful chunks for embedding.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

# Directories and files to skip during indexing
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    ".env", ".tox", ".mypy_cache", ".pytest_cache", "dist",
    "build", ".mark", ".eggs", "egg-info",
}

SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".bin",
    ".o", ".a", ".lib", ".obj", ".class", ".jar", ".war",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flac",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx",
    ".db", ".sqlite", ".sqlite3",
    ".lock", ".min.js", ".min.css",
}

MAX_FILE_SIZE = 100_000  # 100 KB


@dataclass
class Chunk:
    file: str
    start_line: int
    end_line: int
    content: str


def should_index(path: str) -> bool:
    """Return True if the file should be indexed."""
    p = Path(path)

    # Skip hidden files (starting with .)
    if p.name.startswith("."):
        return False

    # Skip files in excluded directories
    parts = p.parts
    for part in parts:
        if part.lower() in SKIP_DIRS:
            return False
        # Also catch .egg-info style dirs
        if part.endswith(".egg-info"):
            return False

    # Skip by extension
    suffix = p.suffix.lower()
    if suffix in SKIP_EXTENSIONS:
        return False

    # Skip files without extension that look binary (e.g. LICENSE is OK)
    if not p.is_file():
        return False

    # Skip large files
    try:
        if p.stat().st_size > MAX_FILE_SIZE:
            return False
        if p.stat().st_size == 0:
            return False
    except OSError:
        return False

    # Quick binary check: read first 8KB and look for null bytes
    try:
        with open(p, "rb") as f:
            head = f.read(8192)
            if b"\x00" in head:
                return False
    except OSError:
        return False

    return True


def _split_on_boundaries(lines: List[str], pattern: re.Pattern,
                         max_lines: int, overlap: int) -> List[tuple]:
    """Split lines at regex boundaries. Returns list of (start, end) 1-indexed."""
    boundaries = []
    for i, line in enumerate(lines):
        if pattern.match(line):
            boundaries.append(i)

    if not boundaries:
        # No boundaries found — fall back to line-count splitting
        return _split_by_lines(len(lines), max_lines, overlap)

    chunks = []
    for idx, start in enumerate(boundaries):
        if idx + 1 < len(boundaries):
            end = boundaries[idx + 1]
        else:
            end = len(lines)

        # If a single definition is too long, sub-split it
        if end - start > max_lines:
            sub = _split_by_lines(end - start, max_lines, overlap)
            for s, e in sub:
                chunks.append((start + s, start + e))
        else:
            chunks.append((start, end))

    # Include any preamble before the first boundary
    if boundaries[0] > 0:
        preamble_end = boundaries[0]
        if preamble_end > max_lines:
            sub = _split_by_lines(preamble_end, max_lines, overlap)
            for s, e in sub:
                chunks.append((s, e))
        else:
            chunks.append((0, preamble_end))

    # Sort by start position and convert to 1-indexed
    chunks.sort(key=lambda x: x[0])
    return [(s + 1, e) for s, e in chunks]


def _split_by_lines(total: int, max_lines: int, overlap: int) -> List[tuple]:
    """Split into fixed-size chunks with overlap. Returns 0-indexed (start, end)."""
    chunks = []
    start = 0
    while start < total:
        end = min(start + max_lines, total)
        chunks.append((start, end))
        if end >= total:
            break
        start = end - overlap
    return chunks


# Pre-compiled patterns for language-aware splitting
_PY_BOUNDARY = re.compile(r"^(def |class |async def )", re.MULTILINE)
_JS_BOUNDARY = re.compile(
    r"^(function |class |export |const \w+ = |let \w+ = |var \w+ = |async function )",
    re.MULTILINE,
)

_LANG_PATTERNS = {
    ".py": _PY_BOUNDARY,
    ".js": _JS_BOUNDARY,
    ".ts": _JS_BOUNDARY,
    ".tsx": _JS_BOUNDARY,
    ".jsx": _JS_BOUNDARY,
    ".mjs": _JS_BOUNDARY,
}


def chunk_file(path: str, max_lines: int = 80, overlap: int = 20) -> List[Chunk]:
    """Chunk a single file into semantically meaningful pieces.

    Args:
        path: Absolute or relative path to the file.
        max_lines: Maximum lines per chunk.
        overlap: Overlap lines between consecutive chunks (line-split mode).

    Returns:
        List of Chunk dataclass instances.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    suffix = p.suffix.lower()
    pattern = _LANG_PATTERNS.get(suffix)

    if pattern:
        ranges = _split_on_boundaries(lines, pattern, max_lines, overlap)
    else:
        raw = _split_by_lines(len(lines), max_lines, overlap)
        ranges = [(s + 1, e) for s, e in raw]

    chunks = []
    for start, end in ranges:
        content = "".join(lines[start - 1 : end])
        if content.strip():  # skip empty chunks
            chunks.append(Chunk(
                file=str(p),
                start_line=start,
                end_line=end,
                content=content,
            ))

    return chunks
