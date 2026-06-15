"""
MARK-XX — Knowledge Base Integration (Nemesi)
Loads the user's knowledge graph from the note-taking app and provides
a condensed context summary for injection into the AI's system prompt.

This gives the AI "shared common knowledge" — awareness of all notes,
tags, hub topics, and recent activity without needing explicit tool calls.
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger("mark.knowledge")

# ── Paths ─────────────────────────────────────────────────────────────────────
NEMESI_DIR = Path(r"C:\Users\Putu Ari\note-taking-app\data\notes")
USER_PROFILE_PATH = NEMESI_DIR / "AI-Synthesized-User-Profile.md"

# ── API Config ────────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:3000/api"
CACHE_TTL = 300  # 5 minutes


class KnowledgeBase:
    """Loads and caches the user's knowledge base context from Nemesi."""

    def __init__(self):
        self._context_cache: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0
        self._profile_cache: Optional[str] = None
        self._profile_time: float = 0

    # ── API Helpers ────────────────────────────────────────────────────────────

    def _api_get(self, endpoint: str, timeout: int = 10) -> Optional[Dict]:
        """Make a GET request to the note-taking app API."""
        try:
            import requests
            resp = requests.get(f"{BASE_URL}{endpoint}", timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"API call failed ({endpoint}): {e}")
            return None

    def _api_post(self, endpoint: str, body: dict, timeout: int = 10) -> Optional[Dict]:
        """Make a POST request to the note-taking app API."""
        try:
            import requests
            resp = requests.post(f"{BASE_URL}{endpoint}", json=body, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"API POST failed ({endpoint}): {e}")
            return None

    # ── Context Loading ────────────────────────────────────────────────────────

    def _load_agent_context(self) -> Optional[Dict[str, Any]]:
        """Load the full agent context from /api/agent/context."""
        data = self._api_get("/agent/context")
        if data and data.get("success"):
            return data.get("context", {})
        return None

    def _load_context_filesystem(self) -> Dict[str, Any]:
        """Fallback: scan the notes directory directly when API is down."""
        context = {"notes": [], "tags": set(), "total": 0}
        if not NEMESI_DIR.exists():
            return context

        for f in sorted(NEMESI_DIR.glob("*.md")):
            if f.name.startswith("."):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                title = f.stem.replace("-", " ").replace("_", " ")

                # Extract tags from frontmatter
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        fm = content[3:end]
                        for line in fm.split("\n"):
                            if line.strip().startswith("tags:"):
                                tags_str = line.split(":", 1)[1].strip()
                                if tags_str.startswith("["):
                                    try:
                                        tags = json.loads(tags_str)
                                        context["tags"].update(tags)
                                    except json.JSONDecodeError:
                                        pass

                # First 200 chars as snippet
                snippet = content[:200].replace("\n", " ").strip()
                context["notes"].append({
                    "id": f.stem,
                    "title": title,
                    "snippet": snippet,
                })
            except Exception:
                continue

        # Also scan subdirectories (1 level deep)
        for d in sorted(NEMESI_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name != "gemini memory":
                for f in sorted(d.glob("*.md"))[:10]:
                    try:
                        title = f.stem.replace("-", " ").replace("_", " ")
                        context["notes"].append({
                            "id": f"{d.name}/{f.stem}",
                            "title": title,
                        })
                    except Exception:
                        continue

        context["total"] = len(context["notes"])
        context["tags"] = list(context["tags"])
        return context

    def get_context(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get the knowledge base context, using cache if available."""
        now = time.time()
        if not force_refresh and self._context_cache and (now - self._cache_time) < CACHE_TTL:
            return self._context_cache

        # Try API first
        ctx = self._load_agent_context()
        if ctx:
            self._context_cache = ctx
            self._cache_time = now
            logger.info(f"Knowledge base loaded from API ({len(str(ctx))} chars)")
            return ctx

        # Fallback to filesystem
        ctx = self._load_context_filesystem()
        self._context_cache = ctx
        self._cache_time = now
        logger.info(f"Knowledge base loaded from filesystem ({ctx.get('total', 0)} notes)")
        return ctx

    # ── User Profile ──────────────────────────────────────────────────────────

    def get_user_profile(self) -> str:
        """Load the AI-synthesized user profile."""
        now = time.time()
        if self._profile_cache and (now - self._profile_time) < CACHE_TTL:
            return self._profile_cache

        if USER_PROFILE_PATH.exists():
            try:
                profile = USER_PROFILE_PATH.read_text(encoding="utf-8", errors="replace")
                self._profile_cache = profile[:2000]
                self._profile_time = now
                return self._profile_cache
            except Exception:
                pass
        return ""

    # ── Context Summary for System Prompt ──────────────────────────────────────

    def get_context_summary(self) -> str:
        """Build a condensed knowledge base summary for injection into the system prompt.

        Returns a formatted string that gives the AI awareness of the user's
        entire knowledge base without consuming too much token budget.
        """
        ctx = self.get_context()
        if not ctx:
            return ""

        parts = []
        parts.append("## Your Knowledge Base (Nemesi)")
        parts.append("You have access to the user's personal knowledge graph — a second brain called \"Nemesi\".")

        # Stats
        notes = ctx.get("notes", [])
        if isinstance(notes, list):
            total = len(notes)
        else:
            total = ctx.get("total", ctx.get("noteCount", 0))
        if total:
            parts.append(f"It contains **{total} notes**.")

        # Tags / taxonomy
        tags = ctx.get("tags", ctx.get("taxonomy", ctx.get("topTags", [])))
        if isinstance(tags, list) and tags:
            # Take top 15 tags
            tag_names = []
            for t in tags[:15]:
                if isinstance(t, dict):
                    tag_names.append(t.get("tag", t.get("name", str(t))))
                else:
                    tag_names.append(str(t))
            if tag_names:
                parts.append(f"Top topics: {', '.join(tag_names)}")

        # Hub notes (most connected)
        hubs = ctx.get("hubs", ctx.get("hubNotes", []))
        if isinstance(hubs, list) and hubs:
            hub_names = []
            for h in hubs[:5]:
                if isinstance(h, dict):
                    hub_names.append(h.get("title", h.get("id", str(h))))
                else:
                    hub_names.append(str(h))
            if hub_names:
                parts.append(f"Hub notes (most connected): {', '.join(hub_names)}")

        # Recent notes
        recent = ctx.get("recentNotes", ctx.get("recent", []))
        if isinstance(recent, list) and recent:
            recent_names = []
            for r in recent[:5]:
                if isinstance(r, dict):
                    recent_names.append(r.get("title", r.get("id", str(r))))
                else:
                    recent_names.append(str(r))
            if recent_names:
                parts.append(f"Recently updated: {', '.join(recent_names)}")

        # Note index (condensed list of all notes for awareness)
        if isinstance(notes, list) and notes:
            note_index = []
            for n in notes[:40]:  # Cap at 40 to keep prompt reasonable
                if isinstance(n, dict):
                    nid = n.get("id", "?")
                    title = n.get("title", nid)
                    note_index.append(f"  - {title} ({nid})")
                else:
                    note_index.append(f"  - {n}")
            if note_index:
                parts.append("Note index:\n" + "\n".join(note_index))
                if total > 40:
                    parts.append(f"  ... and {total - 40} more notes")

        # Instructions for the AI
        parts.append("")
        parts.append("**IMPORTANT**: Use `note_search` or `note_get_context` to look up the user's existing knowledge before answering questions about their projects, business ideas, or personal context.")
        parts.append("Always check if relevant notes exist before creating new ones.")

        return "\n".join(parts)


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """Get the singleton KnowledgeBase instance."""
    global _instance
    if _instance is None:
        _instance = KnowledgeBase()
    return _instance
