#!/usr/bin/env python3
# Copyright (c) 2026 Arthur Arsyonov — looi.ru
# Licensed under MIT
"""
Local SQLite cache for query embedding vectors.

Query embeddings are expensive: the provider network call dominates
cold-query latency for a typical chat-history search. Most real-world
query streams contain repeats (same phrase, minor rephrasings, routine
checks from agents), so caching the normalized float32 vector on disk
turns repeat queries into a millisecond-scale SQLite lookup.

Design:

- Separate SQLite file. Does not touch the hot vector index.
- Key: sha256(model_name + dims + query). Model or dims change
  invalidates the key automatically.
- Values are stored as float32 BLOBs — bit-identical round-trip.
- Configurable TTL (default 7 days). ``ttl_days=0`` means every
  read is immediately stale.
- WAL journal mode so readers and an occasional writer do not block.
- All cache-path exceptions are the caller's responsibility to
  swallow. The cache itself never silently drops data.

CLI usage is not provided — this is a library module.
"""

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import numpy as np

DEFAULT_DB = Path.home() / ".openclaw/memory/embed_cache.db"
DEFAULT_TTL_DAYS = int(os.getenv("EMBED_CACHE_TTL_DAYS", "7"))


class EmbedCache:
    """SQLite-backed cache for normalized embedding vectors."""

    def __init__(
        self,
        db_path: os.PathLike[str] | str = DEFAULT_DB,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = int(ttl_days) * 86400
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embed_cache (
                    cache_key  TEXT PRIMARY KEY,
                    model      TEXT NOT NULL,
                    dims       INTEGER NOT NULL,
                    vector     BLOB NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_created_at ON embed_cache(created_at)"
            )

    @staticmethod
    def _key(query: str, model: str, dims: int) -> str:
        src = f"{model}|{dims}|{query}".encode("utf-8")
        return hashlib.sha256(src).hexdigest()

    def get(self, query: str, model: str, dims: int) -> Optional[np.ndarray]:
        """Return cached vector or None on miss / expiry."""
        key = self._key(query, model, dims)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT vector, created_at FROM embed_cache WHERE cache_key=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        vec_blob, created_at = row
        if self.ttl_seconds == 0 or time.time() - created_at > self.ttl_seconds:
            return None
        return np.frombuffer(vec_blob, dtype=np.float32).copy()

    def put(
        self, query: str, model: str, dims: int, vector: Optional[np.ndarray]
    ) -> None:
        """Store vector. Silent no-op if vector is None."""
        if vector is None:
            return
        vec_f32 = np.asarray(vector, dtype=np.float32)
        key = self._key(query, model, dims)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO embed_cache VALUES (?,?,?,?,?)",
                (key, model, int(dims), vec_f32.tobytes(), int(time.time())),
            )

    def vacuum_expired(self) -> int:
        """Delete rows older than TTL. Returns the number of rows removed."""
        if self.ttl_seconds <= 0:
            return 0
        cutoff = int(time.time()) - self.ttl_seconds
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM embed_cache WHERE created_at < ?", (cutoff,)
            )
            return cur.rowcount
