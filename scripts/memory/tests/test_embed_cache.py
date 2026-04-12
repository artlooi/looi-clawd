#!/usr/bin/env python3
# Copyright (c) 2026 Arthur Arsyonov — looi.ru
# Licensed under MIT
"""Unit tests for the EmbedCache class.

No network, no real filesystem beyond pytest's ``tmp_path``. Tests the
public API contract: miss, hit, key isolation, TTL semantics, vacuum,
schema invariants, and bit-exact roundtrip.
"""

import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from embed_cache import EmbedCache  # noqa: E402


def test_miss_returns_none(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    assert cache.get("hello", "provider-a", 768) is None


def test_hit_roundtrip(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    cache.put("hello", "provider-a", 3, vec)
    got = cache.get("hello", "provider-a", 3)
    assert got is not None
    np.testing.assert_array_equal(got, vec)


def test_different_model_different_key(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    cache.put("hello", "provider-a", 3, vec)
    assert cache.get("hello", "provider-b", 3) is None


def test_different_dims_different_key(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    vec = np.array([0.1], dtype=np.float32)
    cache.put("hello", "provider-a", 1, vec)
    assert cache.get("hello", "provider-a", 3) is None


def test_ttl_zero_expires_immediately(tmp_path):
    cache = EmbedCache(tmp_path / "c.db", ttl_days=0)
    vec = np.array([0.1], dtype=np.float32)
    cache.put("hello", "provider-a", 1, vec)
    time.sleep(0.01)
    assert cache.get("hello", "provider-a", 1) is None


def test_ttl_non_zero_respects_expiry(tmp_path):
    cache = EmbedCache(tmp_path / "c.db", ttl_days=7)
    vec = np.array([0.1], dtype=np.float32)
    cache.put("hello", "provider-a", 1, vec)
    with sqlite3.connect(cache.db_path) as conn:
        stale_ts = int(time.time()) - (8 * 86400)
        conn.execute("UPDATE embed_cache SET created_at=?", (stale_ts,))
    assert cache.get("hello", "provider-a", 1) is None


def test_vacuum_expired_removes_rows(tmp_path):
    cache = EmbedCache(tmp_path / "c.db", ttl_days=7)
    vec = np.array([0.1], dtype=np.float32)
    cache.put("one", "provider-a", 1, vec)
    cache.put("two", "provider-a", 1, vec)
    with sqlite3.connect(cache.db_path) as conn:
        stale_ts = int(time.time()) - (30 * 86400)
        conn.execute("UPDATE embed_cache SET created_at=?", (stale_ts,))
    assert cache.vacuum_expired() == 2
    assert cache.get("one", "provider-a", 1) is None
    assert cache.get("two", "provider-a", 1) is None


def test_vacuum_zero_ttl_is_noop(tmp_path):
    cache = EmbedCache(tmp_path / "c.db", ttl_days=0)
    assert cache.vacuum_expired() == 0


def test_overwrite_existing_key(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    v1 = np.array([1.0, 2.0], dtype=np.float32)
    v2 = np.array([3.0, 4.0], dtype=np.float32)
    cache.put("hello", "provider-a", 2, v1)
    cache.put("hello", "provider-a", 2, v2)
    got = cache.get("hello", "provider-a", 2)
    np.testing.assert_array_equal(got, v2)


def test_put_none_is_noop(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    cache.put("hello", "provider-a", 3, None)
    assert cache.get("hello", "provider-a", 3) is None


def test_unicode_query_supported(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    vec = np.array([0.5, 0.5], dtype=np.float32)
    query = "multi-language unicode query with mixed scripts"
    cache.put(query, "provider-a", 2, vec)
    got = cache.get(query, "provider-a", 2)
    np.testing.assert_array_equal(got, vec)


def test_wal_journal_mode(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    with sqlite3.connect(cache.db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_schema_has_created_at_index(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    with sqlite3.connect(cache.db_path) as conn:
        indexes = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        ]
    assert "idx_created_at" in indexes


def test_bit_exact_float32_roundtrip(tmp_path):
    cache = EmbedCache(tmp_path / "c.db")
    vec = np.random.RandomState(42).rand(768).astype(np.float32)
    cache.put("roundtrip", "provider-a", 768, vec)
    got = cache.get("roundtrip", "provider-a", 768)
    assert got.dtype == np.float32
    assert got.shape == (768,)
    assert np.array_equal(got, vec)
