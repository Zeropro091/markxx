"""
MARK-XX — Hierarchical MARK.md Context Loader
Inspired by gemini-cli's GEMINI.md system.

Searches 4 tiers (highest priority first):
1. {working_dir}/MARK.md — project-level instructions
2. {working_dir}/.mark/MEMORY.md — private project memory
3. Subdirectory MARK.md files (common code dirs)
4. ~/.mark/MARK.md — global user preferences
"""

import os
from pathlib import Path
from typing import Optional


def load_mark_context(working_dir: str) -> str:
    """Load hierarchical MARK.md context.

    Searches 4 tiers (highest priority first):
    1. {working_dir}/MARK.md — project-level instructions
    2. {working_dir}/.mark/MEMORY.md — private project memory
    3. Subdirectory MARK.md files (walk up from cwd to git root)
    4. ~/.mark/MARK.md — global user preferences
    """
    sections = []

    # Tier 4: Global (~/.mark/MARK.md)
    global_md = Path.home() / ".mark" / "MARK.md"
    if global_md.exists():
        sections.append(("Global Preferences", global_md.read_text(encoding='utf-8', errors='replace')))

    # Tier 1: Project-level (working_dir/MARK.md)
    project_md = Path(working_dir) / "MARK.md"
    if project_md.exists():
        sections.append(("Project Instructions", project_md.read_text(encoding='utf-8', errors='replace')))

    # Tier 2: Private memory (.mark/MEMORY.md)
    memory_md = Path(working_dir) / ".mark" / "MEMORY.md"
    if memory_md.exists():
        sections.append(("Project Memory", memory_md.read_text(encoding='utf-8', errors='replace')))

    # Tier 3: Subdirectory MARK.md files (scan common dirs)
    for subdir in ['src', 'lib', 'app', 'core', 'agent', 'actions']:
        sub_md = Path(working_dir) / subdir / "MARK.md"
        if sub_md.exists():
            sections.append((f"{subdir}/ Instructions", sub_md.read_text(encoding='utf-8', errors='replace')))

    if not sections:
        return ""

    parts = []
    for title, content in sections:
        content = content.strip()
        if content:
            parts.append(f"### {title}\n{content}")

    return "\n\n".join(parts)


def save_memory(working_dir: str, content: str):
    """Save to .mark/MEMORY.md"""
    mem_path = Path(working_dir) / ".mark" / "MEMORY.md"
    mem_path.parent.mkdir(parents=True, exist_ok=True)
    mem_path.write_text(content, encoding='utf-8')
