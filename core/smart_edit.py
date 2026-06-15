"""
MARK — Smart Edit Engine (ported from gemini-cli's edit.ts)

4-strategy cascade for reliable file editing:
  1. Exact match     — direct string replacement
  2. Flexible match  — whitespace-stripped line-by-line comparison
  3. Regex match     — tokenized regex with flexible whitespace
  4. Fuzzy match     — Levenshtein distance ≤ 10% tolerance

Also includes:
  - Omission placeholder detection (catches "// ... rest of code")
  - Indentation preservation from the original source
"""

import re
import difflib
from typing import Optional, List, Tuple, NamedTuple

from core.logger import get_logger
log = get_logger("smart_edit")

# ── Configuration ──────────────────────────────────────────────────────────────
FUZZY_THRESHOLD = 0.10           # Allow up to 10% character difference
WHITESPACE_PENALTY = 0.1        # Whitespace diffs cost 10% of a char diff
OMISSION_PATTERNS = [
    r'^\s*//\s*\.{3}\s*',         # // ...
    r'^\s*#\s*\.{3}\s*',          # # ...
    r'^\s*//\s*rest\s+of',        # // rest of code
    r'^\s*#\s*rest\s+of',         # # rest of code
    r'^\s*//\s*\.\.\.\s*\w',      # // ... more code
    r'^\s*#\s*\.\.\.\s*\w',       # # ... more code
    r'^\s*//\s*existing\s+code',  # // existing code
    r'^\s*#\s*existing\s+code',   # # existing code
    r'^\s*//\s*unchanged',        # // unchanged
    r'^\s*#\s*unchanged',         # # unchanged
    r'^\s*\.\.\.',                # ... (standalone)
]
_OMISSION_RE = [re.compile(p, re.IGNORECASE) for p in OMISSION_PATTERNS]


class EditResult(NamedTuple):
    """Result of a smart edit operation."""
    new_content: str
    occurrences: int
    strategy: str              # exact | flexible | regex | fuzzy | failed
    final_old: str
    final_new: str


# ── Omission Detection ────────────────────────────────────────────────────────

def detect_omission_placeholders(text: str) -> List[str]:
    """Detect lines that look like LLM-generated omission placeholders."""
    hits = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        for pat in _OMISSION_RE:
            if pat.match(stripped):
                hits.append(line)
                break
    return hits


# ── Strategy 1: Exact Match ───────────────────────────────────────────────────

def _exact_replace(content: str, old: str, new: str, allow_multiple: bool = False) -> Optional[EditResult]:
    """Direct string replacement — most precise."""
    normalized_old = old.replace("\r\n", "\n")
    normalized_new = new.replace("\r\n", "\n")
    normalized_content = content.replace("\r\n", "\n")

    count = normalized_content.count(normalized_old)
    if count == 0:
        return None
    if not allow_multiple and count > 1:
        return EditResult(content, count, "exact", normalized_old, normalized_new)

    result = normalized_content.replace(normalized_old, normalized_new)
    return EditResult(result, count, "exact", normalized_old, normalized_new)


# ── Strategy 2: Flexible (whitespace-stripped) ────────────────────────────────

def _apply_indentation(lines: List[str], indent: str) -> List[str]:
    """Apply indentation from source to replacement lines."""
    result = []
    for i, line in enumerate(lines):
        if i == 0:
            result.append(indent + line.lstrip())
        elif line.strip():
            result.append(indent + line.lstrip())
        else:
            result.append("")
    return result


def _flexible_replace(content: str, old: str, new: str, allow_multiple: bool = False) -> Optional[EditResult]:
    """Whitespace-stripped line-by-line comparison — handles indentation differences."""
    normalized_content = content.replace("\r\n", "\n")
    normalized_old = old.replace("\r\n", "\n")
    normalized_new = new.replace("\r\n", "\n")

    source_lines = normalized_content.split("\n")
    search_lines_stripped = [line.strip() for line in normalized_old.split("\n")]
    replace_lines = normalized_new.split("\n")
    search_len = len(search_lines_stripped)

    # Remove empty trailing search line if present
    if search_lines_stripped and search_lines_stripped[-1] == "":
        search_lines_stripped = search_lines_stripped[:-1]
        search_len = len(search_lines_stripped)

    if search_len == 0:
        return None

    occurrences = 0
    i = 0
    while i <= len(source_lines) - search_len:
        window = source_lines[i:i + search_len]
        window_stripped = [line.strip() for line in window]

        if window_stripped == search_lines_stripped:
            occurrences += 1
            if not allow_multiple and occurrences > 1:
                return EditResult(content, occurrences, "flexible", normalized_old, normalized_new)

            # Preserve indentation from the first matched line
            indent_match = re.match(r'^([ \t]*)', window[0])
            indent = indent_match.group(1) if indent_match else ""
            new_block = _apply_indentation(replace_lines, indent)
            source_lines[i:i + search_len] = new_block
            i += len(new_block)
            continue
        i += 1

    if occurrences > 0:
        return EditResult("\n".join(source_lines), occurrences, "flexible", normalized_old, normalized_new)
    return None


# ── Strategy 3: Regex (tokenized flexible whitespace) ─────────────────────────

def _escape_regex(s: str) -> str:
    """Escape regex special chars."""
    return re.escape(s)


def _regex_replace(content: str, old: str, new: str, allow_multiple: bool = False) -> Optional[EditResult]:
    """Tokenized regex with flexible whitespace between tokens."""
    normalized_old = old.replace("\r\n", "\n")
    normalized_new = new.replace("\r\n", "\n")

    # Split on structural delimiters first
    delimiters = ['(', ')', ':', '[', ']', '{', '}', '>', '<', '=']
    processed = normalized_old
    for d in delimiters:
        processed = processed.replace(d, f" {d} ")

    # Tokenize by whitespace
    tokens = [t for t in processed.split() if t]
    if not tokens:
        return None

    escaped = [_escape_regex(t) for t in tokens]
    pattern = r'\s*'.join(escaped)
    final_pattern = r'^([ \t]*)' + pattern

    try:
        flags = re.MULTILINE
        matches = list(re.finditer(final_pattern, content, flags))
    except re.error:
        return None

    if not matches:
        return None

    count = len(matches)
    if not allow_multiple and count > 1:
        return EditResult(content, count, "regex", normalized_old, normalized_new)

    new_lines = normalized_new.split("\n")
    def replacer(m):
        indent = m.group(1) or ""
        return "\n".join(_apply_indentation(new_lines, indent))

    if allow_multiple:
        result = re.sub(final_pattern, replacer, content, flags=re.MULTILINE)
    else:
        result = re.sub(final_pattern, replacer, content, count=1, flags=re.MULTILINE)

    return EditResult(result, count, "regex", normalized_old, normalized_new)


# ── Strategy 4: Fuzzy (Levenshtein-based) ─────────────────────────────────────

def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Insertions, deletions, substitutions
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(
                curr_row[j] + 1,       # insert
                prev_row[j + 1] + 1,   # delete
                prev_row[j] + cost,    # substitute
            ))
        prev_row = curr_row
    return prev_row[-1]


def _weighted_distance(s1: str, s2: str) -> float:
    """Levenshtein distance with reduced penalty for whitespace-only diffs."""
    if s1 == s2:
        return 0.0

    # Check if they're the same when stripped
    s1_stripped = re.sub(r'\s+', ' ', s1).strip()
    s2_stripped = re.sub(r'\s+', ' ', s2).strip()

    if s1_stripped == s2_stripped:
        # Only whitespace differences — very low penalty
        raw = _levenshtein_distance(s1, s2)
        return raw * WHITESPACE_PENALTY

    return float(_levenshtein_distance(s1, s2))


def _fuzzy_replace(content: str, old: str, new: str, allow_multiple: bool = False) -> Optional[EditResult]:
    """Fuzzy matching using Levenshtein distance with threshold."""
    normalized_old = old.replace("\r\n", "\n")
    normalized_new = new.replace("\r\n", "\n")
    normalized_content = content.replace("\r\n", "\n")

    search_lines = normalized_old.split("\n")
    search_len = len(search_lines)
    source_lines = normalized_content.split("\n")

    if search_len == 0 or search_len > len(source_lines):
        return None

    best_score = float("inf")
    best_index = -1
    max_allowed = len(normalized_old) * FUZZY_THRESHOLD

    for i in range(len(source_lines) - search_len + 1):
        window = "\n".join(source_lines[i:i + search_len])
        dist = _weighted_distance(window, normalized_old)

        if dist < best_score and dist <= max_allowed:
            best_score = dist
            best_index = i

    if best_index < 0:
        return None

    # Preserve indentation from original
    indent_match = re.match(r'^([ \t]*)', source_lines[best_index])
    indent = indent_match.group(1) if indent_match else ""
    replace_lines = _apply_indentation(normalized_new.split("\n"), indent)
    source_lines[best_index:best_index + search_len] = replace_lines

    pct = (best_score / max(len(normalized_old), 1)) * 100
    log.info(f"Fuzzy match at line {best_index + 1} (distance: {best_score:.1f}, {pct:.1f}%)")
    return EditResult("\n".join(source_lines), 1, "fuzzy", normalized_old, normalized_new)


# ── Main Entry Point ──────────────────────────────────────────────────────────

def smart_edit(content: str, old: str, new: str, allow_multiple: bool = False) -> EditResult:
    """Apply a 4-strategy cascade to edit file content.

    Tries in order: exact → flexible → regex → fuzzy
    Returns EditResult with strategy used and occurrence count.
    """
    if not old:
        return EditResult(content, 0, "failed", old, new)

    # Check for omission placeholders in new content
    omissions = detect_omission_placeholders(new)
    if omissions:
        log.warning(f"Omission placeholder detected in new_string: {omissions[:3]}")
        # Still proceed but log warning — the LLM might have truncated the code

    # Strategy 1: Exact
    result = _exact_replace(content, old, new, allow_multiple)
    if result and result.occurrences > 0:
        if not allow_multiple and result.occurrences > 1:
            log.info(f"Exact: found {result.occurrences} occurrences (expected 1)")
        else:
            log.info(f"Exact match: {result.occurrences} replacement(s)")
        return result

    # Strategy 2: Flexible (whitespace-insensitive)
    result = _flexible_replace(content, old, new, allow_multiple)
    if result and result.occurrences > 0:
        log.info(f"Flexible match: {result.occurrences} replacement(s)")
        return result

    # Strategy 3: Regex (tokenized)
    result = _regex_replace(content, old, new, allow_multiple)
    if result and result.occurrences > 0:
        log.info(f"Regex match: {result.occurrences} replacement(s)")
        return result

    # Strategy 4: Fuzzy (Levenshtein)
    result = _fuzzy_replace(content, old, new, allow_multiple)
    if result:
        log.info(f"Fuzzy match: 1 replacement (Levenshtein)")
        return result

    # All strategies failed
    return EditResult(content, 0, "failed", old, new)
