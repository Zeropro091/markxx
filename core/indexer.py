"""
MARK-XX — Codebase Indexer with Semantic Search
Embeds code chunks via google.genai text-embedding-004, stores in SQLite,
and does cosine-similarity search at query time.
"""

import math
import os
import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from core.chunker import Chunk, chunk_file, should_index
from core.logger import get_logger

log = get_logger("indexer")

EMBED_MODEL = "text-embedding-004"
EMBED_BATCH_SIZE = 100  # max texts per API call


@dataclass
class SearchResult:
    file: str
    start_line: int
    end_line: int
    snippet: str
    score: float


def _pack_embedding(values: List[float]) -> bytes:
    """Pack a list of floats into a compact binary blob (float32)."""
    return struct.pack(f"{len(values)}f", *values)


def _unpack_embedding(blob: bytes) -> List[float]:
    """Unpack a binary blob back into a list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors using math stdlib."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class CodebaseIndexer:
    """Indexes a codebase directory for semantic search.

    Uses google.genai for embeddings and SQLite for persistent storage.
    """

    def __init__(self, api_key: str, db_path: str = ".mark/index.db"):
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db()

    def _ensure_db(self):
        """Create the SQLite database and tables if they don't exist."""
        db = Path(self._db_path)
        db.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                file TEXT,
                start_line INTEGER,
                end_line INTEGER,
                content TEXT,
                embedding BLOB,
                mtime REAL,
                indexed_at REAL
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file);
        """)
        self._conn.commit()

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts (up to EMBED_BATCH_SIZE)."""
        result = self._client.models.embed_content(
            model=EMBED_MODEL,
            contents=texts,
        )
        return [e.values for e in result.embeddings]

    def _embed_all(self, texts: List[str]) -> List[List[float]]:
        """Embed an arbitrary number of texts, batching as needed."""
        all_embeddings = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            embeddings = self._embed_batch(batch)
            all_embeddings.extend(embeddings)
            if i + EMBED_BATCH_SIZE < len(texts):
                time.sleep(0.1)  # small delay between batches
        return all_embeddings

    def index(self, directory: str, force: bool = False) -> dict:
        """Walk directory, chunk files, embed chunks, store in SQLite.

        Args:
            directory: Root directory to index.
            force: If True, re-index all files regardless of mtime.

        Returns:
            {"indexed": N, "skipped": N, "time": "X.Xs"}
        """
        t0 = time.time()
        root = Path(directory).resolve()
        indexed = 0
        skipped = 0

        # Gather files to process
        files_to_index: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skip dirs in-place
            dirnames[:] = [
                d for d in dirnames
                if d.lower() not in {
                    "node_modules", ".git", "__pycache__", "venv", ".venv",
                    ".env", ".tox", ".mypy_cache", ".pytest_cache", "dist",
                    "build", ".mark", ".eggs",
                }
                and not d.endswith(".egg-info")
            ]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if should_index(str(fpath)):
                    files_to_index.append(fpath)

        # Check mtime for each file, collect chunks to embed
        pending_chunks: List[Chunk] = []
        pending_mtimes: List[float] = []

        for fpath in files_to_index:
            try:
                mtime = fpath.stat().st_mtime
            except OSError:
                skipped += 1
                continue

            if not force:
                row = self._conn.execute(
                    "SELECT MAX(mtime) FROM chunks WHERE file = ?",
                    (str(fpath),),
                ).fetchone()
                if row[0] is not None and row[0] >= mtime:
                    skipped += 1
                    continue

            # File is new or changed — delete old chunks and re-chunk
            self._conn.execute("DELETE FROM chunks WHERE file = ?", (str(fpath),))
            chunks = chunk_file(str(fpath))
            for c in chunks:
                pending_chunks.append(c)
                pending_mtimes.append(mtime)

        # Embed all pending chunks
        if pending_chunks:
            texts = [c.content for c in pending_chunks]
            log.info(f"Embedding {len(texts)} chunks from {len(files_to_index) - skipped} files...")
            embeddings = self._embed_all(texts)

            now = time.time()
            rows = []
            for chunk, mtime, emb in zip(pending_chunks, pending_mtimes, embeddings):
                rows.append((
                    chunk.file,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.content,
                    _pack_embedding(emb),
                    mtime,
                    now,
                ))

            self._conn.executemany(
                "INSERT INTO chunks (file, start_line, end_line, content, embedding, mtime, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            indexed = len(rows)

        # Update meta
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("last_indexed", str(time.time())),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("directory", str(root)),
        )
        self._conn.commit()

        elapsed = time.time() - t0
        log.info(f"Index complete: {indexed} indexed, {skipped} skipped, {elapsed:.1f}s")
        return {"indexed": indexed, "skipped": skipped, "time": f"{elapsed:.1f}s"}

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """Embed query and find top_k most similar chunks.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.

        Returns:
            List of SearchResult sorted by descending similarity score.
        """
        # Embed the query
        result = self._client.models.embed_content(
            model=EMBED_MODEL,
            contents=[query],
        )
        query_vec = result.embeddings[0].values

        # Load all chunk embeddings and compute similarity
        rows = self._conn.execute(
            "SELECT id, file, start_line, end_line, content, embedding FROM chunks"
        ).fetchall()

        if not rows:
            return []

        scored = []
        for row_id, file, start_line, end_line, content, emb_blob in rows:
            chunk_vec = _unpack_embedding(emb_blob)
            score = _cosine_similarity(query_vec, chunk_vec)
            scored.append((score, file, start_line, end_line, content))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, file, start_line, end_line, content in scored[:top_k]:
            # Truncate snippet for display
            snippet = content[:500].rstrip()
            if len(content) > 500:
                snippet += "\n..."
            results.append(SearchResult(
                file=file,
                start_line=start_line,
                end_line=end_line,
                snippet=snippet,
                score=round(score, 4),
            ))
        return results

    def is_stale(self, directory: str) -> bool:
        """Check if any files changed since last index.

        Returns True if the index is empty or any file has a newer mtime.
        """
        root = Path(directory).resolve()

        # Check if we have any chunks at all
        count = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if count == 0:
            return True

        # Check last indexed time
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'last_indexed'"
        ).fetchone()
        if not row:
            return True

        last_indexed = float(row[0])

        # Scan directory for any file newer than last index
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d.lower() not in {
                    "node_modules", ".git", "__pycache__", "venv", ".venv",
                    ".env", ".tox", ".mypy_cache", ".pytest_cache", "dist",
                    "build", ".mark", ".eggs",
                }
                and not d.endswith(".egg-info")
            ]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if should_index(str(fpath)):
                    try:
                        if fpath.stat().st_mtime > last_indexed:
                            return True
                    except OSError:
                        continue

        return False

    def close(self):
        """Close the SQLite connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
