"""Tests for activity marker + auto-cleanup of stale project caches.

Key invariants (v1.9.1):

- ``_cache_base()`` respects ``RLM_CONFIG_FILE`` (service install with --env
  places cache alongside logs/config in the user's home).
- ``cleanup_stale_cache`` scans **cache root only**. BSL index directories
  (``RLM_INDEX_DIR``) are never touched.
- ``last_used.txt`` markers are written in the **cache root only**, never in
  index directories.
"""

from __future__ import annotations

import os
import textwrap
import time
from unittest import mock

import pytest

from rlm_tools_bsl import cache as cache_mod
from rlm_tools_bsl.cache import (
    LAST_USED_MARKER,
    _cache_base,
    _cache_dir,
    _project_hash,
    cleanup_stale_cache,
    touch_project_cache,
)


_CF_MAIN_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses">
        <Configuration>
            <Properties>
                <Name>TestConfig</Name>
            </Properties>
        </Configuration>
    </MetaDataObject>
""")


@pytest.fixture
def _isolated_caches(tmp_path, monkeypatch):
    """Redirect cache root via RLM_CONFIG_FILE and isolate RLM_INDEX_DIR.

    Returns (cache_base, idx_root). The cache root comes from a synthetic
    RLM_CONFIG_FILE so `_cache_base()` returns the test-owned path.
    """
    user_home = tmp_path / "fake_home"
    user_home.mkdir()
    config_dir = user_home / ".config" / "rlm-tools-bsl"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "service.json"
    config_file.write_text("{}", encoding="utf-8")
    cache_base = config_dir / "cache"
    cache_base.mkdir()

    idx_root = tmp_path / "idx"
    idx_root.mkdir()

    monkeypatch.setenv("RLM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("RLM_INDEX_DIR", str(idx_root))
    monkeypatch.delenv("RLM_CACHE_MAX_AGE_DAYS", raising=False)
    return cache_base, idx_root


def _set_age_days(path, days: float) -> None:
    ts = time.time() - (days * 86400)
    os.utime(path, (ts, ts))


# ---------------------------------------------------------------------------
# _cache_base() — RLM_CONFIG_FILE override
# ---------------------------------------------------------------------------


def test_cache_base_respects_rlm_config_file(tmp_path, monkeypatch):
    """_cache_base() must follow RLM_CONFIG_FILE override (same rule as logs).

    This is the v1.9.1 fix: previously _CACHE_BASE was a module-level constant
    computed via Path.home(), which under LocalSystem resolves to systemprofile.
    """
    config_dir = tmp_path / "user-config" / "rlm-tools-bsl"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "service.json"
    config_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("RLM_CONFIG_FILE", str(config_file))
    assert _cache_base() == config_dir / "cache"


def test_cache_base_fallback_when_no_rlm_config_file(tmp_path, monkeypatch):
    """Without RLM_CONFIG_FILE, _cache_base() falls back to ~/.cache/rlm-tools-bsl."""
    import pathlib

    monkeypatch.delenv("RLM_CONFIG_FILE", raising=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    # Override the autouse Path.home patch from conftest.py with this test's
    # own fake_home (setenv USERPROFILE/HOME does not override setattr).
    monkeypatch.setattr(pathlib.Path, "home", lambda: fake_home)

    assert _cache_base() == fake_home / ".cache" / "rlm-tools-bsl"


def test_cache_dir_uses_cache_base(_isolated_caches):
    """_cache_dir(base_path) must be computed from _cache_base() + hash."""
    cache_base, _ = _isolated_caches
    base_path = "/some/proj"
    assert _cache_dir(base_path) == cache_base / _project_hash(base_path)


# ---------------------------------------------------------------------------
# touch_project_cache — cache-only, never writes to index root
# ---------------------------------------------------------------------------


def test_touch_creates_marker(_isolated_caches):
    cache_base, _ = _isolated_caches
    base_path = "/some/proj"
    h = _project_hash(base_path)
    (cache_base / h).mkdir()

    touch_project_cache(base_path)

    marker = cache_base / h / LAST_USED_MARKER
    assert marker.is_file()
    content = marker.read_text(encoding="utf-8")
    assert base_path in content


def test_touch_updates_marker(_isolated_caches):
    cache_base, _ = _isolated_caches
    base_path = "/some/proj"
    h = _project_hash(base_path)
    (cache_base / h).mkdir()
    touch_project_cache(base_path)
    marker = cache_base / h / LAST_USED_MARKER
    _set_age_days(marker, 30)
    old_mtime = marker.stat().st_mtime

    touch_project_cache(base_path)
    new_mtime = marker.stat().st_mtime
    assert new_mtime > old_mtime


def test_touch_never_writes_to_index_dir(_isolated_caches):
    """Critical invariant: activity markers belong ONLY in cache root.

    Even when RLM_INDEX_DIR is configured and its per-project subdir exists,
    touch_project_cache must NOT create a marker there.
    """
    cache_base, idx_root = _isolated_caches
    base_path = "/some/proj"
    h = _project_hash(base_path)
    (cache_base / h).mkdir()
    (idx_root / h).mkdir()

    touch_project_cache(base_path)

    assert (cache_base / h / LAST_USED_MARKER).is_file()
    assert not (idx_root / h / LAST_USED_MARKER).exists(), "marker must NOT be written to RLM_INDEX_DIR"


def test_save_index_stamps_marker(_isolated_caches):
    """save_index() must write last_used.txt alongside file_index.json.

    This covers the first-ever rlm_start on a project without an index:
    touch_project_cache() runs before save_index() creates the cache dir,
    so it silently skips. save_index is the place where the dir first
    appears — the marker must be stamped here to avoid a missing-marker
    window until the next rlm_start.
    """
    from rlm_tools_bsl.cache import save_index
    from rlm_tools_bsl.format_detector import BslFileInfo

    cache_base, _ = _isolated_caches
    base_path = "/some/new/proj"
    h = _project_hash(base_path)

    # Before save_index: no dir yet
    assert not (cache_base / h).exists()

    entries: list[tuple[str, BslFileInfo]] = [
        (
            "CommonModules/X/Ext/Module.bsl",
            BslFileInfo(
                relative_path="CommonModules/X/Ext/Module.bsl",
                category="CommonModules",
                object_name="X",
                module_type="Module",
                form_name=None,
                command_name=None,
                is_form_module=False,
            ),
        ),
    ]
    save_index(base_path, bsl_count=1, entries=entries)

    # After save_index: both file_index.json AND last_used.txt exist
    assert (cache_base / h / "file_index.json").is_file()
    assert (cache_base / h / LAST_USED_MARKER).is_file()
    marker_content = (cache_base / h / LAST_USED_MARKER).read_text(encoding="utf-8")
    assert base_path in marker_content


def test_touch_skips_nonexistent_dirs(_isolated_caches):
    """touch_project_cache must not create empty cache dirs."""
    cache_base, idx_root = _isolated_caches
    base_path = "/some/proj"
    h = _project_hash(base_path)

    touch_project_cache(base_path)

    assert not (cache_base / h).exists()
    assert not (idx_root / h).exists()


# ---------------------------------------------------------------------------
# cleanup_stale_cache — cache-only, indexes never touched
# ---------------------------------------------------------------------------


def test_cleanup_removes_stale_projects(_isolated_caches):
    cache_base, _ = _isolated_caches

    fresh = cache_base / ("a" * 12)
    old_10d = cache_base / ("b" * 12)
    very_old = cache_base / ("c" * 12)
    for d in (fresh, old_10d, very_old):
        d.mkdir()
        (d / "stuff").write_text("data")

    _set_age_days(fresh, 1)
    _set_age_days(old_10d, 10)
    _set_age_days(very_old, 30)

    stats = cleanup_stale_cache(max_age_days=14)
    assert stats["removed"] == 1
    assert fresh.exists()
    assert old_10d.exists()
    assert not very_old.exists()


def test_cleanup_preserves_touched_project(_isolated_caches):
    cache_base, _ = _isolated_caches
    proj = cache_base / ("d" * 12)
    proj.mkdir()
    (proj / "stuff").write_text("data")
    _set_age_days(proj, 30)

    (proj / LAST_USED_MARKER).write_text(f"{time.time():.3f}\n", encoding="utf-8")

    stats = cleanup_stale_cache(max_age_days=14)
    assert stats["removed"] == 0
    assert proj.exists()


def test_cleanup_never_scans_index_dir(_isolated_caches):
    """Cleanup must never touch RLM_INDEX_DIR — indexes are expensive to
    rebuild and are managed manually via rlm_index(action='drop')."""
    cache_base, idx_root = _isolated_caches

    # Stale project in cache → WILL be removed
    stale_cache_proj = cache_base / ("1" * 12)
    stale_cache_proj.mkdir()
    _set_age_days(stale_cache_proj, 30)

    # Stale project in INDEX dir (with both old marker AND old mtime) → MUST survive
    stale_idx_proj = idx_root / ("2" * 12)
    stale_idx_proj.mkdir()
    fake_db = stale_idx_proj / "bsl_index.db"
    fake_db.write_text("stub")
    _set_age_days(fake_db, 60)
    _set_age_days(stale_idx_proj, 60)
    # Even a stale marker in index dir (legacy leftover) must not trigger removal
    legacy_marker = stale_idx_proj / LAST_USED_MARKER
    legacy_marker.write_text("stale\n", encoding="utf-8")
    _set_age_days(legacy_marker, 60)

    stats = cleanup_stale_cache(max_age_days=14)

    assert not stale_cache_proj.exists(), "stale project in cache must be removed"
    assert stale_idx_proj.exists(), "index directory must never be removed by cleanup"
    assert fake_db.exists(), "index DB must never be removed by cleanup"
    # Sanity: the index root should not even appear as a scanned root
    assert stats["cache_root"] == str(cache_base)
    assert stats["removed"] == 1


def test_cleanup_zero_disables(_isolated_caches):
    cache_base, _ = _isolated_caches
    proj = cache_base / ("f" * 12)
    proj.mkdir()
    _set_age_days(proj, 100)
    stats = cleanup_stale_cache(max_age_days=0)
    assert stats["disabled"] is True
    assert stats["removed"] == 0
    assert proj.exists()


def test_cleanup_handles_missing_base_dir(tmp_path, monkeypatch):
    """If cache root doesn't exist yet, cleanup is a no-op."""
    config_dir = tmp_path / "empty-config" / "rlm-tools-bsl"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "service.json"
    config_file.write_text("{}", encoding="utf-8")
    # cache_base derived from this config_file doesn't exist yet
    monkeypatch.setenv("RLM_CONFIG_FILE", str(config_file))
    monkeypatch.delenv("RLM_CACHE_MAX_AGE_DAYS", raising=False)

    stats = cleanup_stale_cache(max_age_days=14)
    assert stats["removed"] == 0
    assert stats["scanned"] == 0


def test_cleanup_skips_locked_files_gracefully(_isolated_caches):
    cache_base, _ = _isolated_caches
    proj = cache_base / ("9" * 12)
    proj.mkdir()
    _set_age_days(proj, 30)

    with mock.patch.object(cache_mod.shutil, "rmtree", side_effect=PermissionError("locked")):
        stats = cleanup_stale_cache(max_age_days=14)

    assert stats["removed"] == 0
    assert stats["errors"]
    assert proj.exists()


def test_env_var_override(_isolated_caches, monkeypatch):
    cache_base, _ = _isolated_caches
    proj = cache_base / ("7" * 12)
    proj.mkdir()
    _set_age_days(proj, 10)

    monkeypatch.setenv("RLM_CACHE_MAX_AGE_DAYS", "7")
    stats = cleanup_stale_cache()
    assert stats["removed"] == 1


# ---------------------------------------------------------------------------
# One-shot legacy migration via _touch_registered_projects()
# ---------------------------------------------------------------------------


def _make_registry_project(tmp_path, monkeypatch, project_name="legacy-proj"):
    """Create a minimal CF project on disk + register it."""
    from rlm_tools_bsl import projects as projects_mod
    from rlm_tools_bsl.projects import ProjectRegistry

    proj_root = tmp_path / "proj"
    cf = proj_root / "src" / "cf"
    cf.mkdir(parents=True)
    (cf / "Configuration.xml").write_text(_CF_MAIN_XML, encoding="utf-8")

    reg_path = tmp_path / "projects.json"
    reg = ProjectRegistry(reg_path)
    reg.add(project_name, str(cf), password="pw")
    monkeypatch.setattr(projects_mod, "_registry", reg)
    return cf


def test_cleanup_preserves_registered_legacy_cache(_isolated_caches, tmp_path, monkeypatch):
    """Legacy cache without last_used.txt for a registered project must NOT
    be deleted on first v1.9.1 startup (one-shot migration)."""
    cache_base, _ = _isolated_caches
    cf = _make_registry_project(tmp_path, monkeypatch, "legacy-proj")

    try:
        h = _project_hash(str(cf))
        legacy = cache_base / h
        legacy.mkdir()
        (legacy / "file_index.json").write_text("{}")
        _set_age_days(legacy, 40)

        unregistered = cache_base / ("f" * 12)
        unregistered.mkdir()
        _set_age_days(unregistered, 40)

        stats = cleanup_stale_cache(max_age_days=14)

        assert legacy.exists(), "registered legacy cache must be preserved"
        assert not unregistered.exists(), "unregistered stale cache must be removed"
        assert stats["legacy_markers_written"] >= 1
    finally:
        from rlm_tools_bsl import projects as projects_mod

        monkeypatch.setattr(projects_mod, "_registry", None)


def test_cleanup_removes_registered_but_forgotten_project(_isolated_caches, tmp_path, monkeypatch):
    """Registered project whose marker has aged out beyond the threshold
    must still be cleaned up. Pre-touch is a one-shot migration, not a
    permanent whitelist."""
    cache_base, _ = _isolated_caches
    cf = _make_registry_project(tmp_path, monkeypatch, "forgotten")

    try:
        h = _project_hash(str(cf))
        proj_dir = cache_base / h
        proj_dir.mkdir()
        (proj_dir / "file_index.json").write_text("{}")
        marker = proj_dir / LAST_USED_MARKER
        marker.write_text("stale\n", encoding="utf-8")
        _set_age_days(marker, 40)
        _set_age_days(proj_dir, 40)

        stats = cleanup_stale_cache(max_age_days=14)

        assert not proj_dir.exists(), "registered-but-forgotten project must be removed"
        assert stats["legacy_markers_written"] == 0  # marker exists → not overridden
    finally:
        from rlm_tools_bsl import projects as projects_mod

        monkeypatch.setattr(projects_mod, "_registry", None)


def test_cleanup_pretouch_handles_missing_cache_dir(_isolated_caches, tmp_path, monkeypatch):
    """Pre-touch must not create empty dirs for projects with no cache yet."""
    cache_base, _ = _isolated_caches
    cf = _make_registry_project(tmp_path, monkeypatch, "no-cache-yet")

    try:
        cleanup_stale_cache(max_age_days=14)
        h = _project_hash(str(cf))
        assert not (cache_base / h).exists(), "pre-touch must not create empty dirs"
    finally:
        from rlm_tools_bsl import projects as projects_mod

        monkeypatch.setattr(projects_mod, "_registry", None)
