#!/usr/bin/env python3
# Copyright (c) 2026 Arthur Arsyonov — looi.ru
# Licensed under MIT
"""Smoke tests for search_history_fast as a script.

These verify the module imports cleanly, the script path is
executable, and the cache feature flag is honoured. They do not
require a real vector index — when ``chat_vectors.db`` is missing the
script must degrade gracefully, not raise on import.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "search_history_fast.py"
MODULE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(MODULE_DIR))


def test_module_imports_cleanly(monkeypatch, tmp_path):
    """Importing the module must never crash, even without a real DB."""
    monkeypatch.setenv("EMBED_CACHE_ENABLED", "0")
    import search_history_fast as shf

    importlib.reload(shf)
    assert hasattr(shf, "embed_query")
    assert hasattr(shf, "_embed_query_uncached")


def test_feature_flag_disables_cache_globally(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBED_CACHE_ENABLED", "0")
    import search_history_fast as shf

    importlib.reload(shf)
    assert shf._EMBED_CACHE is None


def test_script_exists_and_executable():
    assert SCRIPT.is_file()
    # Must have either shebang or be runnable via python3
    first_line = SCRIPT.read_text().split("\n", 1)[0]
    assert first_line.startswith("#!")


def test_script_runs_with_empty_query_gracefully():
    """Running the script with no args should exit cleanly (non-zero OK).

    The point is that it must not crash with an unhandled exception or
    import error. Any clean exit code (0, 1, 2) is acceptable.
    """
    env = {
        **os.environ,
        "EMBED_CACHE_ENABLED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    # Acceptable: any exit code, as long as no Python traceback in stderr
    assert "Traceback" not in result.stderr, (
        f"Script crashed with traceback:\n{result.stderr}"
    )
