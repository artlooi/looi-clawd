# Changelog

All notable changes to `clawd` are documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Embedding cache** for `scripts/memory/search_history_fast.py`.
  Local SQLite cache for query embedding vectors, keyed on
  `sha256(model + dims + query)` with a configurable TTL (default
  7 days, env `EMBED_CACHE_TTL_DAYS`). Repeated queries skip the
  provider network call entirely and serve the normalized vector
  from disk.
  - **Speed:** warm-query latency drops from roughly 800 ms to
    ~150 ms on a typical chat-history index (5–7× faster). Cold
    queries are unchanged because the provider call still happens
    on the first touch.
  - **Isolation:** the cache lives in a separate SQLite file at
    `~/.openclaw/memory/embed_cache.db` and never touches the hot
    vector index (`chat_vectors.db`).
  - **Safety:** every cache-path exception is swallowed and falls
    through to the direct provider call. A broken cache can never
    break search. The original `embed_query` is preserved as
    `_embed_query_uncached` for the fallback branch, tests, and
    direct callers.
  - **Opt-out:** set `EMBED_CACHE_ENABLED=0` to disable at runtime
    with zero code changes and zero behaviour change from earlier
    versions.
  - **Implementation:** new module `scripts/memory/embed_cache.py`
    (`EmbedCache` class with `get`, `put`, `vacuum_expired`). WAL
    journal mode, float32 bit-exact round-trip, index on
    `created_at`.
- **Test suite** for `scripts/memory/` under
  `scripts/memory/tests/`. Three layers:
  - `test_embed_cache.py` — 14 unit tests covering the `EmbedCache`
    API in isolation.
  - `test_embed_query_wrapper.py` — 10 integration tests for the
    cached `embed_query` wrapper, with provider calls
    monkey-patched to avoid network.
  - `test_cli_smoke.py` — 4 smoke tests verifying the module
    imports cleanly, the script is executable, and the feature
    flag disables the cache globally.

### Changed

- `scripts/memory/search_history_fast.py` now routes query
  embeddings through `embed_cache.EmbedCache` when enabled.
  Public CLI and function signatures are unchanged. Original
  provider-resolution logic is preserved verbatim as
  `_embed_query_uncached`.

### Fixed

- `scripts/memory/search_history_fast.py`: renamed the local
  variable `l` (ambiguous per PEP 8 / ruff E741) to `lex` in the
  hybrid score merge. Pure rename, no behaviour change.
