"""Note-Taking App integration for MARK-XX.

Provides tools to interact with the Lensa Insignia knowledge graph note-taking app
running at http://localhost:3000.

Tools:
  note_list          — list all notes
  note_read          — read a note by ID
  note_search        — full-text fuzzy search (POST /api/notes/search)
  note_search_semantic — AI-powered semantic search
  note_create        — create a new note (requires path + title)
  note_update        — update note content/frontmatter
  note_delete        — delete a note
  note_rename        — rename/move a note
  note_graph         — knowledge graph summary
  note_backlinks     — find incoming references
  note_get_context   — full AI-optimized knowledge base overview
  note_get_projects  — project cockpit analytics
"""

import json
import logging
import os
import re
import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("mark.notes")

BASE_URL = "http://localhost:3000/api"
TIMEOUT = 10  # seconds

_CONNECTION_ERROR = "⚠️ Cannot connect to note-taking app. Is the dev server running? (npm run dev)"

# ── Filesystem Config & Helpers ───────────────────────────────────────────────
NEMESI_DIR = Path(r"C:\Users\Putu Ari\note-taking-app\data\notes")
LINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def _get_note_file(note_id: str) -> Path:
    """Ensure note_id is a safe relative path and return file path."""
    safe_id = note_id.lstrip("/\\").replace("\\", "/")
    return NEMESI_DIR / f"{safe_id}.md"


def _parse_note_file(file_path: Path) -> dict:
    """Read a markdown note from the filesystem, parsing title and tags."""
    content = ""
    title = file_path.stem.replace("-", " ").replace("_", " ")
    tags = []
    updated_at = ""

    try:
        if file_path.exists():
            stat = file_path.stat()
            updated_at = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
            raw_content = file_path.read_text(encoding="utf-8", errors="replace")
            # Parse frontmatter
            if raw_content.startswith("---"):
                end = raw_content.find("---", 3)
                if end != -1:
                    fm_text = raw_content[3:end]
                    content = raw_content[end+3:].strip()
                    for line in fm_text.split("\n"):
                        line = line.strip()
                        if line.startswith("title:"):
                            title = line.split(":", 1)[1].strip().strip("'\"")
                        elif line.startswith("tags:"):
                            tags_str = line.split(":", 1)[1].strip()
                            if tags_str.startswith("[") and tags_str.endswith("]"):
                                try:
                                    tags = [t.strip().strip("'\"") for t in tags_str[1:-1].split(",") if t.strip()]
                                except Exception:
                                    tags = []
                            else:
                                tags = [t.strip().strip("'\"") for t in tags_str.split(",") if t.strip()]
                else:
                    content = raw_content
            else:
                content = raw_content
    except Exception as e:
        content = f"Error reading note content: {e}"

    try:
        note_id = file_path.relative_to(NEMESI_DIR).with_suffix("").as_posix()
    except Exception:
        note_id = file_path.stem

    return {
        "id": note_id,
        "title": title,
        "tags": tags,
        "content": content,
        "updatedAt": updated_at
    }


def _write_note_file(note_id: str, title: str, tags: list, content: str) -> None:
    """Write markdown file to the filesystem, retaining existing frontmatter keys."""
    file_path = _get_note_file(note_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    other_fm = {}
    if file_path.exists():
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
            if raw.startswith("---"):
                end = raw.find("---", 3)
                if end != -1:
                    fm_text = raw[3:end]
                    for line in fm_text.split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k = k.strip()
                            if k not in ("title", "tags"):
                                other_fm[k] = v.strip()
        except Exception:
            pass

    fm_lines = ["---"]
    fm_lines.append(f"title: {title}")
    tags_str = ", ".join(f'"{t}"' for t in tags)
    fm_lines.append(f"tags: [{tags_str}]")
    for k, v in other_fm.items():
        fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")

    full_content = "\n".join(fm_lines) + "\n\n" + content.strip()
    file_path.write_text(full_content, encoding="utf-8")


# ── HTTP Helpers ──────────────────────────────────────────────────────────────

def _get(endpoint: str) -> Any:
    """Make a GET request to the note-taking app API."""
    resp = requests.get(f"{BASE_URL}{endpoint}", timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(endpoint: str, body: dict) -> Any:
    """Make a POST request to the note-taking app API."""
    resp = requests.post(f"{BASE_URL}{endpoint}", json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _put(endpoint: str, body: dict) -> Any:
    """Make a PUT request to the note-taking app API."""
    resp = requests.put(f"{BASE_URL}{endpoint}", json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _delete(endpoint: str) -> bool:
    """Make a DELETE request to the note-taking app API."""
    resp = requests.delete(f"{BASE_URL}{endpoint}", timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("success", False)


def _patch(endpoint: str, body: dict) -> Any:
    """Make a PATCH request to the note-taking app API."""
    resp = requests.patch(f"{BASE_URL}{endpoint}", json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ══════════════════════════════════════════════════════════════════════════════
# Core CRUD Tools
# ══════════════════════════════════════════════════════════════════════════════

def note_list(args: dict) -> str:
    """List all notes with IDs and tags."""
    try:
        data = _get("/notes")
        notes = data.get("notes", []) if isinstance(data, dict) else data
    except Exception:
        # Fallback to filesystem
        if not NEMESI_DIR.exists():
            return "No notes found (filesystem empty)."
        notes = []
        for f in NEMESI_DIR.rglob("*.md"):
            if f.name.startswith(".") or "gemini memory" in f.parts:
                continue
            try:
                parsed = _parse_note_file(f)
                notes.append(parsed)
            except Exception:
                continue
        notes.sort(key=lambda x: x["id"])

    if not notes:
        return "No notes found."
    lines = []
    for n in notes:
        nid = n.get("id", "?")
        title = n.get("title", nid)
        tags = n.get("tags", []) or []
        tag_str = f"  [{', '.join(tags)}]" if tags else ""
        lines.append(f"📝 {nid} — {title}{tag_str}")
    return f"{len(notes)} notes:\n" + "\n".join(lines)


def note_read(args: dict) -> str:
    """Read a note by ID. Returns title, tags, and full content."""
    note_id = args.get("id", "")
    if not note_id:
        return "Error: 'id' argument is required."
    try:
        data = _get(f"/notes/{note_id}")
        note = data.get("note", data) if isinstance(data, dict) else data
    except Exception:
        # Fallback to filesystem
        file_path = _get_note_file(note_id)
        if not file_path.exists():
            return f"Note not found: {note_id}"
        try:
            note = _parse_note_file(file_path)
        except Exception as e:
            return f"Error reading note from filesystem: {e}"

    title = note.get("title", note_id)
    tags = note.get("tags", [])
    content = note.get("content", "")
    updated = note.get("updatedAt", "")
    lines = [
        f"# {title}",
        f"**Tags:** {', '.join(tags) if tags else '(none)'}",
        f"**ID:** {note_id}",
    ]
    if updated:
        lines.append(f"**Updated:** {updated}")
    lines.append("")
    lines.append(content)
    return "\n".join(lines).strip()


def note_search(args: dict) -> str:
    """Search notes by keyword. Uses POST /api/notes/search for full-text fuzzy search."""
    query = args.get("q", "") or args.get("query", "")
    if not query:
        return "Error: 'query' argument is required."
    limit = args.get("limit", 10)
    try:
        data = _post("/notes/search", {
            "query": query,
            "limit": limit,
            "mode": "full",
        })
        results = data.get("results", []) if isinstance(data, dict) else data
    except Exception:
        # Fallback to filesystem
        if not NEMESI_DIR.exists():
            return f"No results for: {query}"
        results = []
        query_lower = query.lower()
        for f in NEMESI_DIR.rglob("*.md"):
            if f.name.startswith(".") or "gemini memory" in f.parts:
                continue
            try:
                parsed = _parse_note_file(f)
                score = 0
                if query_lower in parsed["title"].lower():
                    score += 10
                for tag in parsed["tags"]:
                    if query_lower in tag.lower():
                        score += 5
                if query_lower in parsed["content"].lower():
                    score += 1
                if score > 0:
                    results.append({
                        "note": parsed,
                        "score": score
                    })
            except Exception:
                continue
        results.sort(key=lambda x: x["score"], reverse=True)
        results = results[:limit]

    if not results:
        return f"No results for: {query}"
    lines = [f"Results for '{query}':", ""]
    for r in results:
        note = r.get("note", r) if isinstance(r, dict) else r
        nid = note.get("id", "?")
        title = note.get("title", nid)
        snippet = (note.get("content", "") or "")[:200].replace("\n", " ")
        score = r.get("score", "") if isinstance(r, dict) else ""
        score_str = f" (score: {score:.2f})" if isinstance(score, (int, float)) else f" (score: {score})" if score else ""
        lines.append(f"📄 {nid} — {title}{score_str}")
        if snippet:
            lines.append(f"   {snippet}...")
        lines.append("")
    return "\n".join(lines).strip()


def note_search_semantic(args: dict) -> str:
    """Semantic search — AI-powered search across notes using embeddings."""
    query = args.get("q", "") or args.get("query", "")
    if not query:
        return "Error: 'query' argument is required."
    limit = args.get("limit", 10)
    try:
        data = _post("/notes/search", {
            "query": query,
            "limit": limit,
            "mode": "semantic",
        })
        results = data.get("results", []) if isinstance(data, dict) else data
        if not results:
            return f"No semantic results for: {query}"
        lines = [f"Semantic results for '{query}':", ""]
        for r in results:
            note = r.get("note", r) if isinstance(r, dict) else r
            nid = note.get("id", "?")
            title = note.get("title", nid)
            score = r.get("score", r.get("similarity", ""))
            score_str = f" (similarity: {score:.2f})" if isinstance(score, (int, float)) else ""
            lines.append(f"🔮 {nid} — {title}{score_str}")
        return "\n".join(lines).strip()
    except Exception:
        # Fallback to keyword search
        return f"(⚠️ Semantic search API unavailable. Falling back to keyword search)\n\n" + note_search(args)


def note_create(args: dict) -> str:
    """Create a new note. Requires 'path' (e.g. 'Projects/My-Idea') and 'title'."""
    title = args.get("title", "Untitled")
    path = args.get("path", "") or args.get("id", "")
    content = args.get("content", "")

    if not path:
        # Auto-generate path from title
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
        path = safe_title.replace(" ", "-")

    body = {
        "path": path,
        "title": title,
    }

    try:
        data = _post("/notes", body)
        note = data.get("note", data) if isinstance(data, dict) else data
        note_id = note.get("id", path)

        # If content was provided, update the note with that content
        if content:
            try:
                _put(f"/notes/{note_id}", {"content": content})
            except Exception as e:
                logger.warning(f"Note created but content update failed: {e}")
                return f"✅ Created note: {note_id} — {title} (⚠️ content update failed: {e})"

        return f"✅ Created note: {note_id} — {title}"
    except Exception:
        # Fallback to filesystem
        note_id = path
        try:
            _write_note_file(note_id, title, [], content)
            return f"✅ Created note (filesystem): {note_id} — {title}"
        except Exception as fs_err:
            return f"Error creating note on filesystem: {fs_err}"


def note_update(args: dict) -> str:
    """Update a note's content and/or frontmatter."""
    note_id = args.get("id", "")
    if not note_id:
        return "Error: 'id' argument is required."
    try:
        body = {}
        if "content" in args:
            body["content"] = args["content"]
        if "tags" in args:
            tags = args["tags"]
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            body["frontmatter"] = {"tags": tags}
        if "frontmatter" in args:
            body["frontmatter"] = args["frontmatter"]
        if "title" in args:
            fm = body.get("frontmatter", {})
            fm["title"] = args["title"]
            body["frontmatter"] = fm

        if not body:
            return "Error: provide 'content', 'tags', 'title', or 'frontmatter' to update."

        data = _put(f"/notes/{note_id}", body)
        return f"✅ Updated note: {note_id}"
    except Exception:
        # Fallback to filesystem
        file_path = _get_note_file(note_id)
        if not file_path.exists():
            return f"Note not found: {note_id}"
        try:
            note = _parse_note_file(file_path)

            title = args.get("title", note.get("title", ""))

            # Extract tags update
            tags = note.get("tags", [])
            if "tags" in args:
                new_tags = args["tags"]
                if isinstance(new_tags, str):
                    tags = [t.strip() for t in new_tags.split(",") if t.strip()]
                elif isinstance(new_tags, list):
                    tags = new_tags
            elif "frontmatter" in args and isinstance(args["frontmatter"], dict) and "tags" in args["frontmatter"]:
                tags = args["frontmatter"]["tags"]

            content = args.get("content", note.get("content", ""))

            _write_note_file(note_id, title, tags, content)
            return f"✅ Updated note (filesystem): {note_id}"
        except Exception as fs_err:
            return f"Error updating note on filesystem: {fs_err}"


def note_delete(args: dict) -> str:
    """Delete a note by ID."""
    note_id = args.get("id", "")
    if not note_id:
        return "Error: 'id' argument is required."
    try:
        success = _delete(f"/notes/{note_id}")
        if success:
            return f"🗑️ Deleted note: {note_id}"
        return f"Failed to delete note: {note_id}"
    except Exception:
        # Fallback to filesystem
        file_path = _get_note_file(note_id)
        if not file_path.exists():
            return f"Note not found: {note_id}"
        try:
            file_path.unlink()
            # Clean up empty parent directories up to NEMESI_DIR
            parent = file_path.parent
            while parent != NEMESI_DIR and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            return f"🗑️ Deleted note (filesystem): {note_id}"
        except Exception as fs_err:
            return f"Error deleting note on filesystem: {fs_err}"


def note_rename(args: dict) -> str:
    """Rename or move a note. Requires 'id' (current) and 'new_id' (target)."""
    note_id = args.get("id", "")
    new_id = args.get("new_id", "") or args.get("newId", "")
    if not note_id:
        return "Error: 'id' argument is required."
    if not new_id:
        return "Error: 'new_id' argument is required."
    try:
        data = _patch(f"/notes/{note_id}", {"newId": new_id})
        return f"✅ Renamed note: {note_id} → {new_id}"
    except Exception:
        # Fallback to filesystem
        old_path = _get_note_file(note_id)
        new_path = _get_note_file(new_id)
        if not old_path.exists():
            return f"Note not found: {note_id}"
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            # Clean up empty old parents
            parent = old_path.parent
            while parent != NEMESI_DIR and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            return f"✅ Renamed note (filesystem): {note_id} → {new_id}"
        except Exception as fs_err:
            return f"Error renaming note on filesystem: {fs_err}"


# ══════════════════════════════════════════════════════════════════════════════
# Graph & Context Tools
# ══════════════════════════════════════════════════════════════════════════════

def note_graph(args: dict) -> str:
    """Get knowledge graph summary — nodes, edges, and communities."""
    try:
        data = _get("/graph")
        if isinstance(data, dict) and data.get("success") is not None:
            graph = data
        else:
            graph = data

        nodes = graph.get("nodes", [])
        edges = graph.get("edges", graph.get("links", []))

        node_count = len(nodes) if isinstance(nodes, list) else nodes
        edge_count = len(edges) if isinstance(edges, list) else edges
        communities = graph.get("communities", [])
    except Exception:
        # Fallback to filesystem
        if not NEMESI_DIR.exists():
            return "📊 Knowledge Graph (filesystem): empty"

        nodes = []
        edges = []
        for f in NEMESI_DIR.rglob("*.md"):
            if f.name.startswith(".") or "gemini memory" in f.parts:
                continue
            try:
                parsed = _parse_note_file(f)
                nodes.append(parsed["id"])

                # Search for links in content
                links = LINK_PATTERN.findall(parsed["content"])
                for link in links:
                    edges.append((parsed["id"], link.strip()))
            except Exception:
                continue

        node_count = len(nodes)
        edge_count = len(edges)

        # Group by tag as simple communities
        tag_groups = {}
        for f in NEMESI_DIR.rglob("*.md"):
            if f.name.startswith(".") or "gemini memory" in f.parts:
                continue
            try:
                parsed = _parse_note_file(f)
                for tag in parsed["tags"]:
                    tag_groups[tag] = tag_groups.get(tag, 0) + 1
            except Exception:
                continue
        communities = sorted([{"name": k, "size": v} for k, v in tag_groups.items()], key=lambda x: x["size"], reverse=True)

    lines = [f"📊 Knowledge Graph: {node_count} notes, {edge_count} connections"]

    if communities:
        lines.append(f"   Communities: {len(communities)}")
        for c in communities[:5]:
            name = c.get("name", c.get("label", "?"))
            size = c.get("size", c.get("count", "?"))
            lines.append(f"   • {name} ({size} notes)")

    return "\n".join(lines)


def note_backlinks(args: dict) -> str:
    """Find notes that link to a specific note."""
    note_id = args.get("id", "")
    if not note_id:
        return "Error: 'id' argument is required."
    try:
        data = _get(f"/backlinks/{note_id}")
        backlinks = data.get("backlinks", []) if isinstance(data, dict) else data
    except Exception:
        # Fallback to filesystem
        if not NEMESI_DIR.exists():
            return f"No notes link to: {note_id}"

        backlinks = []
        target_id_lower = note_id.lower()
        for f in NEMESI_DIR.rglob("*.md"):
            if f.name.startswith(".") or "gemini memory" in f.parts:
                continue
            try:
                parsed = _parse_note_file(f)
                if parsed["id"].lower() == target_id_lower:
                    continue
                links = LINK_PATTERN.findall(parsed["content"])
                for link in links:
                    if link.strip().lower() == target_id_lower:
                        backlinks.append({
                            "id": parsed["id"],
                            "title": parsed["title"]
                        })
                        break
            except Exception:
                continue

    if not backlinks:
        return f"No notes link to: {note_id}"
    lines = [f"🔗 {len(backlinks)} note(s) link to {note_id}:", ""]
    for bl in backlinks:
        bl_id = bl.get("id", bl.get("source", "?"))
        bl_title = bl.get("title", bl_id)
        lines.append(f"  📄 {bl_id} — {bl_title}")
    return "\n".join(lines)


def note_get_context(args: dict) -> str:
    """Get AI-optimized overview of the entire knowledge base.
    Returns a condensed map of all notes, tags, hubs, and graph stats.
    This is the best way for the AI to orient itself in the user's knowledge.
    """
    try:
        data = _get("/agent/context")
        if not data or not data.get("success"):
            return "Error: could not load agent context"
        ctx = data.get("context", {})
    except Exception:
        # Fallback to filesystem
        if not NEMESI_DIR.exists():
            return "Error: could not load context (filesystem empty or path does not exist)"

        notes = []
        tag_counts = {}
        links_count = 0
        hubs_map = {}

        for f in NEMESI_DIR.rglob("*.md"):
            if f.name.startswith(".") or "gemini memory" in f.parts:
                continue
            try:
                parsed = _parse_note_file(f)
                notes.append({
                    "id": parsed["id"],
                    "title": parsed["title"],
                    "tags": parsed["tags"],
                    "summary": parsed["content"][:100].replace("\n", " ").strip()
                })
                for tag in parsed["tags"]:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

                links = LINK_PATTERN.findall(parsed["content"])
                links_count += len(links)
                hubs_map[parsed["id"]] = hubs_map.get(parsed["id"], 0) + len(links)
                for l in links:
                    lid = l.strip()
                    hubs_map[lid] = hubs_map.get(lid, 0) + 1
            except Exception:
                continue

        hubs = sorted([{"title": k, "connections": v} for k, v in hubs_map.items()], key=lambda x: x["connections"], reverse=True)
        tags = sorted([{"tag": k, "count": v} for k, v in tag_counts.items()], key=lambda x: x["count"], reverse=True)

        ctx = {
            "stats": {
                "totalNotes": len(notes),
                "totalTags": len(tags),
                "totalEdges": links_count
            },
            "notes": notes,
            "hubs": hubs,
            "tags": tags
        }

    lines = ["📚 Knowledge Base Overview:", ""]

    # Stats
    stats = ctx.get("stats", {})
    if stats:
        lines.append(f"Total notes: {stats.get('totalNotes', '?')}")
        lines.append(f"Total tags: {stats.get('totalTags', '?')}")
        lines.append(f"Graph edges: {stats.get('totalEdges', '?')}")

    # Notes listing
    notes = ctx.get("notes", [])
    if notes:
        lines.append(f"\n--- Notes ({len(notes)}) ---")
        for n in notes[:50]:
            nid = n.get("id", "?")
            title = n.get("title", nid)
            tags = n.get("tags", [])
            summary = n.get("summary", "")[:100]
            tag_str = f"  [{', '.join(tags)}]" if tags else ""
            lines.append(f"  {nid} — {title}{tag_str}")
            if summary:
                lines.append(f"    {summary}")

    # Hub notes
    hubs = ctx.get("hubs", ctx.get("hubNotes", []))
    if hubs:
        lines.append(f"\n--- Hub Notes (most connected) ---")
        for h in hubs[:5]:
            if isinstance(h, dict):
                lines.append(f"  🔗 {h.get('title', h.get('id', '?'))} ({h.get('connections', '?')} links)")

    # Tags
    tags = ctx.get("tags", ctx.get("topTags", []))
    if tags:
        lines.append(f"\n--- Tags ---")
        for t in tags[:20]:
            if isinstance(t, dict):
                lines.append(f"  #{t.get('tag', t.get('name', '?'))} ({t.get('count', '?')})")
            else:
                lines.append(f"  #{t}")

    return "\n".join(lines)


def note_get_projects(args: dict) -> str:
    """Get project cockpit — all projects with progress, status, and pending tasks."""
    try:
        data = _get("/cockpit")
        projects = data.get("projects", []) if isinstance(data, dict) else data
    except Exception:
        # Fallback to filesystem
        if not NEMESI_DIR.exists():
            return "No projects found (filesystem empty)."

        projects = []
        for f in NEMESI_DIR.rglob("*.md"):
            if f.name.startswith(".") or "gemini memory" in f.parts:
                continue
            try:
                parsed = _parse_note_file(f)

                is_project = False
                for tag in parsed["tags"]:
                    if tag.lower() == "project":
                        is_project = True
                        break

                status = "active"
                health = "healthy"

                # Check if file has custom project metadata in frontmatter
                raw = f.read_text(encoding="utf-8", errors="replace")
                if raw.startswith("---"):
                    end = raw.find("---", 3)
                    if end != -1:
                        fm_text = raw[3:end]
                        for line in fm_text.split("\n"):
                            if ":" in line:
                                k, v = line.split(":", 1)
                                k = k.strip().lower()
                                v = v.strip().lower().strip("'\"")
                                if k == "status":
                                    status = v
                                elif k == "health":
                                    health = v
                                elif k == "project" and v in ("true", "yes"):
                                    is_project = True

                if not is_project:
                    continue

                content = parsed["content"]
                pending_tasks = []
                completed_count = 0

                for line in content.split("\n"):
                    line_strip = line.strip()
                    if "- [ ]" in line_strip or "* [ ]" in line_strip:
                        task_desc = line_strip.split("[ ]", 1)[1].strip()
                        if task_desc:
                            pending_tasks.append(task_desc)
                    elif any(pat in line_strip for pat in ["- [x]", "- [X]", "* [x]", "* [X]"]):
                        completed_count += 1

                total_tasks = len(pending_tasks) + completed_count
                progress = int(completed_count / total_tasks * 100) if total_tasks > 0 else 0

                projects.append({
                    "title": parsed["title"],
                    "progress": progress,
                    "status": status,
                    "health": health,
                    "taskCount": total_tasks,
                    "completedCount": completed_count,
                    "pendingTasks": pending_tasks
                })
            except Exception:
                continue

    if not projects:
        return "No projects found. (Tag notes with 'project' to track them here)"
    lines = [f"🚀 {len(projects)} project(s):", ""]
    for p in projects:
        title = p.get("title", "?")
        progress = p.get("progress", 0)
        status = p.get("status", "?")
        health = p.get("health", "?")
        tasks = p.get("taskCount", 0)
        completed = p.get("completedCount", 0)
        bar = "█" * (progress // 10) + "░" * (10 - progress // 10)
        health_icon = "🟢" if health == "healthy" else "🔴"

        lines.append(f"{health_icon} {title}")
        lines.append(f"   [{bar}] {progress}% ({completed}/{tasks} tasks) — {status}")

        pending = p.get("pendingTasks", [])
        if pending:
            for t in pending[:3]:
                lines.append(f"   ☐ {t}")
        lines.append("")
    return "\n".join(lines).strip()
