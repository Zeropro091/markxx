"""
MARK-XX — Persistent Memory (SQLite)
Stores conversation history, user preferences, and project notes.
"""

import sqlite3
import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Any


class Memory:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    role    TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts      REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    description TEXT,
                    notes       TEXT,
                    files       TEXT DEFAULT '[]',
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS uploaded_files (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename    TEXT NOT NULL,
                    path        TEXT NOT NULL,
                    file_type   TEXT,
                    summary     TEXT,
                    added_at    REAL NOT NULL
                );
            """)

    # ── Conversations ──────────────────────────────────────────────────────────
    def add_message(self, role: str, content: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (role, content, ts) VALUES (?, ?, ?)",
                (role, content, time.time())
            )

    def get_history(self, limit: int = 20) -> List[Dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM conversations ORDER BY ts DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"role": r["role"], "parts": [r["content"]]} for r in reversed(rows)]

    def clear_history(self):
        with self._connect() as conn:
            conn.execute("DELETE FROM conversations")

    # ── Preferences ────────────────────────────────────────────────────────────
    def set_pref(self, key: str, value: Any):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
                (key, json.dumps(value))
            )

    def get_pref(self, key: str, default=None) -> Any:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            ).fetchone()
        if row:
            return json.loads(row["value"])
        return default

    def get_all_prefs(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM preferences").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    # ── Projects ───────────────────────────────────────────────────────────────
    def add_project(self, name: str, description: str = "", notes: str = "") -> int:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO projects (name, description, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, description, notes, now, now)
            )
            return cur.lastrowid

    def update_project(self, project_id: int, **kwargs):
        fields = {k: v for k, v in kwargs.items() if k in ("name", "description", "notes", "files")}
        if not fields:
            return
        fields["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [project_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)

    def get_projects(self) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    # ── Uploaded Files ─────────────────────────────────────────────────────────
    def add_file(self, filename: str, path: str, file_type: str, summary: str = ""):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO uploaded_files (filename, path, file_type, summary, added_at) VALUES (?, ?, ?, ?, ?)",
                (filename, path, file_type, summary, time.time())
            )

    def get_files(self) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM uploaded_files ORDER BY added_at DESC LIMIT 20"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Context Builder ────────────────────────────────────────────────────────
    def build_context_summary(self) -> str:
        """Returns a short context string to inject into the system prompt."""
        prefs = self.get_all_prefs()
        projects = self.get_projects()
        files = self.get_files()

        lines = []
        if prefs:
            lines.append("User preferences: " + ", ".join(f"{k}={v}" for k, v in prefs.items()))
        if projects:
            names = [p["name"] for p in projects[:3]]
            lines.append(f"Active projects: {', '.join(names)}")
        if files:
            fnames = [f["filename"] for f in files[:5]]
            lines.append(f"Recently uploaded files: {', '.join(fnames)}")
        return "\n".join(lines) if lines else ""
