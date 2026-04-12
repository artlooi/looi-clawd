#!/usr/bin/env python3
# Copyright (c) 2026 Arthur Arsyonov — looi.ru
# Licensed under MIT
"""Integration tests for the cached embed_query wrapper.

These tests reload ``search_history_fast`` to reset module-level state.
``monkeypatch`` on module attributes MUST happen **after** the reload —
the reload re-executes the module body and resets any earlier patches.
"""

import importlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _setup(monkeypatch, tmp_path, cache_enabled):
    """Env + reload + isolate cache to ``tmp_path``.

    Reload alone is insufficient: ``EmbedCache.__init__`` evaluates its
    ``db_path`` default at class definition time, so a bare reload
    would point at the user's real cache file. We explicitly replace
    ``_EMBED_CACHE`` with a fresh instance bound to ``tmp_path``.
    """
    monkeypatch.setenv("EMBED_CACHE_ENABLED", "1" if cache_enabled else "0")
    import search_history_fast as shf

    importlib.reload(shf)
    if cache_enabled:
        from embed_cache import EmbedCache

        shf._EMBED_CACHE = EmbedCache(tmp_path / "embed_cache.db")
    else:
        shf._EMBED_CACHE = None
    return shf


def _patch_provider(monkeypatch, shf, counter):
    def fake_google(text, key):
        counter["n"] += 1
        return [float(i) for i in range(3072)]

    monkeypatch.setattr(shf, "embed_google", fake_google)
    monkeypatch.setattr(shf, "get_key", lambda: "fake-key")


def test_cache_enabled_initializes_cache(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, True)
    assert shf._EMBED_CACHE is not None


def test_cache_disabled_sets_none(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, False)
    assert shf._EMBED_CACHE is None


def test_cache_hit_skips_provider_call(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, True)
    calls = {"n": 0}
    _patch_provider(monkeypatch, shf, calls)

    v1 = shf.embed_query("query one")
    assert v1 is not None
    assert calls["n"] == 1

    v2 = shf.embed_query("query one")
    assert calls["n"] == 1  # served from cache
    np.testing.assert_array_equal(v1, v2)


def test_cache_disabled_always_calls_provider(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, False)
    calls = {"n": 0}
    _patch_provider(monkeypatch, shf, calls)

    shf.embed_query("query one")
    shf.embed_query("query one")
    shf.embed_query("query one")
    assert calls["n"] == 3


def test_uncached_function_preserved(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, True)
    assert hasattr(shf, "_embed_query_uncached")
    calls = {"n": 0}
    _patch_provider(monkeypatch, shf, calls)
    vec = shf._embed_query_uncached("direct")
    assert vec is not None
    assert calls["n"] == 1


def test_distinct_queries_each_miss_once(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, True)
    calls = {"n": 0}
    _patch_provider(monkeypatch, shf, calls)

    v1 = shf.embed_query("query one")
    v2 = shf.embed_query("query two")
    assert v1 is not None
    assert v2 is not None
    assert calls["n"] == 2


def test_returned_vector_is_normalized(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, True)
    calls = {"n": 0}
    _patch_provider(monkeypatch, shf, calls)
    vec = shf.embed_query("BMW")
    assert vec is not None
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5


def test_google_failure_falls_back_to_ollama(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, True)

    def broken_google(text, key):
        raise RuntimeError("provider-a down")

    def fake_ollama(text):
        return [float(i) for i in range(768)]

    monkeypatch.setattr(shf, "embed_google", broken_google)
    monkeypatch.setattr(shf, "embed_ollama", fake_ollama)
    monkeypatch.setattr(shf, "get_key", lambda: "fake-key")

    vec = shf.embed_query("fallback test")
    assert vec is not None
    assert vec.shape == (768,)


def test_cache_put_failure_does_not_break_search(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, True)
    calls = {"n": 0}
    _patch_provider(monkeypatch, shf, calls)

    class BrokenPutCache:
        def get(self, *a, **kw):
            return None

        def put(self, *a, **kw):
            raise RuntimeError("disk full")

    monkeypatch.setattr(shf, "_EMBED_CACHE", BrokenPutCache())
    vec = shf.embed_query("resilience test")
    assert vec is not None
    assert calls["n"] == 1


def test_cache_get_failure_does_not_break_search(tmp_path, monkeypatch):
    shf = _setup(monkeypatch, tmp_path, True)
    calls = {"n": 0}
    _patch_provider(monkeypatch, shf, calls)

    class BrokenGetCache:
        def get(self, *a, **kw):
            raise RuntimeError("db corrupt")

        def put(self, *a, **kw):
            pass

    monkeypatch.setattr(shf, "_EMBED_CACHE", BrokenGetCache())
    vec = shf.embed_query("get resilience")
    assert vec is not None
    assert calls["n"] == 1
