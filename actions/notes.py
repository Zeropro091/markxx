"""Note-Taking App integration for MARK-XX.

Provides tools to interact with the Lensa Insignia knowledge graph note-taking app
running at http://localhost:3000.
"""

import json
import logging
from typing import Any

import requests

logger = logging.getLogger("mark.notes")

BASE_URL = "http://localhost:3000/api"
TIMEOUT = 10  # seconds


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


def note_list(args: dict) -> str:
    """List all notes with IDs and tags."""
    try:
        data = _get("/notes")
        notes = data if isinstance(data, list) else data.get("notes", [])
        if not notes:
            return "No notes found."
        lines = [f"📝 {n.get('id','?')}  [{', '.join(n.get('tags',[]) or [])}]" for n in notes]
        return f"{len(notes)} notes:\n" + "\n".join(lines)
    except requests.ConnectionError:
        return "⚠️ Cannot connect to note-taking app. Is the dev server running? (pnpm dev)"
    except Exception as e:
        return f"Error listing notes: {e}"


def note_read(args: dict) -> str:
    """Read a note by ID. Returns title, tags, and full content."""
    note_id = args.get("id", "")
    if not note_id:
        return "Error: 'id' argument is required."
    try:
        data = _get(f"/notes/{note_id}")
        note = data.get("note", data)
        title = note.get("title", note_id)
        tags = note.get("tags", [])
        content = note.get("content", "")
        lines = [
            f"# {title}",
            f"**Tags:** {', '.join(tags) if tags else '(none)'}",
            f"**ID:** {note_id}",
            "",
            content,
        ]
        return "\n".join(lines).strip()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return f"Note not found: {note_id}"
        return f"Error reading note: {e}"
    except requests.ConnectionError:
        return "⚠️ Cannot connect to note-taking app. Is the dev server running? (pnpm dev)"
    except Exception as e:
        return f"Error reading note: {e}"


def note_search(args: dict) -> str:
    """Search notes by keyword. Searches both titles and content."""
    query = args.get("q", "") or args.get("query", "")
    if not query:
        return "Error: 'q' (query) argument is required."
    try:
        data = _get(f"/notes?search={query}")
        notes = data if isinstance(data, list) else data.get("results", data.get("notes", []))
        if not notes:
            return f"No results for: {query}"
        lines = [f"Results for '{query}':", ""]
        for n in notes:
            title = n.get("title", n.get("id", "?"))
            snippet = (n.get("content", "") or "")[:200].replace("\n", " ")
            lines.append(f"📄 {n.get('id','?')} — {title}")
            if snippet:
                lines.append(f"   {snippet}...")
            lines.append("")
        return "\n".join(lines).strip()
    except requests.ConnectionError:
        return "⚠️ Cannot connect to note-taking app. Is the dev server running? (pnpm dev)"
    except Exception as e:
        return f"Error searching notes: {e}"


def note_create(args: dict) -> str:
    """Create a new note."""
    title = args.get("title", "Untitled")
    content = args.get("content", "")
    tags = args.get("tags", "")
    path = args.get("path", "")

    body = {"title": title}
    if content:
        body["content"] = content
    if tags:
        body["tags"] = tags if isinstance(tags, list) else [t.strip() for t in tags.split(",")]
    if path:
        body["path"] = path

    try:
        data = _post("/notes", body)
        note = data.get("note", data)
        note_id = note.get("id", "?")
        return f"✅ Created note: {note_id} — {title}"
    except requests.ConnectionError:
        return "⚠️ Cannot connect to note-taking app. Is the dev server running? (pnpm dev)"
    except Exception as e:
        return f"Error creating note: {e}"


def note_update(args: dict) -> str:
    """Update a note's content and/or tags."""
    note_id = args.get("id", "")
    if not note_id:
        return "Error: 'id' argument is required."
    try:
        # Read current note to preserve frontmatter
        current = _get(f"/notes/{note_id}")
        note = current.get("note", current)

        body = {}
        if "content" in args:
            body["content"] = args["content"]
        if "tags" in args:
            body["tags"] = args["tags"] if isinstance(args["tags"], list) else [t.strip() for t in args["tags"].split(",")]

        data = _put(f"/notes/{note_id}", body)
        return f"✅ Updated note: {note_id}"
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return f"Note not found: {note_id}"
        return f"Error updating note: {e}"
    except requests.ConnectionError:
        return "⚠️ Cannot connect to note-taking app. Is the dev server running? (pnpm dev)"
    except Exception as e:
        return f"Error updating note: {e}"


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
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return f"Note not found: {note_id}"
        return f"Error deleting note: {e}"
    except requests.ConnectionError:
        return "⚠️ Cannot connect to note-taking app. Is the dev server running? (pnpm dev)"
    except Exception as e:
        return f"Error deleting note: {e}"


def note_graph(args: dict) -> str:
    """Get knowledge graph summary — total notes and connections."""
    try:
        data = _get("/graph")
        nodes = data.get("nodes", 0) or len(data.get("notes", []))
        edges = data.get("edges", 0) or len(data.get("links", []))
        return f"📊 Knowledge Graph: {nodes} notes, {edges} connections"
    except requests.ConnectionError:
        return "⚠️ Cannot connect to note-taking app. Is the dev server running? (pnpm dev)"
    except Exception as e:
        return f"Error fetching graph: {e}"


def note_backlinks(args: dict) -> str:
    """Find notes that link to a specific note."""
    note_id = args.get("id", "")
    if not note_id:
        return "Error: 'id' argument is required."
    try:
        data = _get(f"/backlinks/{note_id}")
        backlinks = data.get("backlinks", [])
        if not backlinks:
            return f"No notes link to: {note_id}"
        lines = [f"🔗 {len(backlinks)} note(s) link to {note_id}:", ""]
        for bl in backlinks:
            bl_id = bl.get("id", bl.get("source", "?"))
            bl_title = bl.get("title", bl_id)
            lines.append(f"  📄 {bl_id} — {bl_title}")
        return "\n".join(lines)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return f"Note '{note_id}' not found."
        return f"Error fetching backlinks: {e}"
    except Exception as e:
        return f"Error: {e}"



