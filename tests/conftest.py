import sys
from pathlib import Path

# Ensure tests/ is on sys.path so bare imports work on all platforms
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from types import SimpleNamespace

from test_bsl_helpers import _make_bsl_fixture


@pytest.fixture(autouse=True)
def _isolate_real_home(tmp_path_factory, monkeypatch):
    """Default-isolation: every test writes indexes AND file-cache to tmp dirs.

    Without this:
    - ``IndexBuilder.build()`` without a test-local ``RLM_INDEX_DIR`` patch
      writes a ~360 KiB ``bsl_index.db`` into the developer's real
      ``~/.cache/rlm-tools-bsl/<hash>/``.
    - ``rlm_start`` / cache helpers without a test-local ``RLM_CONFIG_FILE``
      patch resolve ``cache._cache_base()`` to ``Path.home()/.cache/...`` and
      drop ``file_index.json`` files there.

    Found in v1.9.2 smoke test: a single ``pytest -q`` run accumulated 19
    stale ``bsl_index.db`` and 87 stale ``file_index.json`` in real home.

    Two-layer isolation:
    1. Set ``RLM_INDEX_DIR`` → indexes go to a session-shared tmp dir.
    2. Patch ``pathlib.Path.home`` → any code that falls back to
       ``Path.home()/.cache/...`` (cache module, migration helper) sees a
       fake home instead of the developer's real one.

    Tests that explicitly verify fallback behavior (migration tests, cache
    tests) can still override either layer — monkeypatch applies later
    changes on top of this autouse setup.
    """
    import pathlib

    isolated_root = tmp_path_factory.mktemp("rlm_index_root")
    fake_home = tmp_path_factory.mktemp("rlm_fake_home")
    monkeypatch.setenv("RLM_INDEX_DIR", str(isolated_root))
    monkeypatch.setattr(pathlib.Path, "home", lambda: fake_home)


@pytest.fixture
def bsl_env(tmp_path):
    """Shared BSL test environment with default CF fixture.

    Returns SimpleNamespace with:
        path  – tmp_path (pathlib.Path) where the CF structure lives
        bsl   – dict of BSL helper functions
        helpers – dict of generic helper functions
    """
    tmpdir = str(tmp_path)
    bsl, helpers = _make_bsl_fixture(tmpdir)
    return SimpleNamespace(path=tmp_path, bsl=bsl, helpers=helpers)
