"""Regression tests: rlm_index uses the same effective path as rlm_start (issue #11).

Critical Codex finding (Round-1 #1): a container-style path (``src/``) must map to
the same index hash directory when touched by ``rlm_index(build/info/drop)`` and
``rlm_start``. Without shared cf-normalization, these tools look at different
directories and the index appears "missing" after a fresh build.
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
import time
from pathlib import Path
from unittest.mock import patch


_CF_MAIN_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses">
        <Configuration uuid="00000000-0000-0000-0000-000000000001">
            <Properties>
                <Name>MainCfg</Name>
                <NamePrefix/>
            </Properties>
        </Configuration>
    </MetaDataObject>
""")


def _make_src_proj(root: str) -> str:
    src = os.path.join(root, "src")
    cf = os.path.join(src, "cf")
    os.makedirs(cf)
    with open(os.path.join(cf, "Configuration.xml"), "w", encoding="utf-8") as f:
        f.write(_CF_MAIN_XML)
    with open(os.path.join(cf, "Module.bsl"), "w", encoding="utf-8") as f:
        f.write("Процедура Тест()\nКонецПроцедуры\n")
    return src


def test_rlm_index_build_and_info_same_hash_for_src_path():
    from rlm_tools_bsl.server import _rlm_index

    with tempfile.TemporaryDirectory() as tmpdir:
        src = _make_src_proj(tmpdir)
        idx_dir = os.path.join(tmpdir, "indexes")

        with patch.dict(os.environ, {"RLM_INDEX_DIR": idx_dir}):
            r = json.loads(_rlm_index(action="build", path=src))
            assert r["action"] == "build"
            assert Path(r["path"]) == (Path(src) / "cf").resolve()

            r = json.loads(_rlm_index(action="info", path=src))
            assert r.get("action") == "info", f"expected info, got {r}"
            assert "methods" in r


def test_rlm_start_and_rlm_index_use_same_index_dir():
    from rlm_tools_bsl.server import _rlm_start, _rlm_index, _rlm_end

    with tempfile.TemporaryDirectory() as tmpdir:
        src = _make_src_proj(tmpdir)
        idx_dir = os.path.join(tmpdir, "indexes")

        with patch.dict(os.environ, {"RLM_INDEX_DIR": idx_dir}):
            _rlm_index(action="build", path=src)

            start_result = json.loads(_rlm_start(path=src, query="test"))
            assert "session_id" in start_result
            assert start_result["index"]["loaded"] is True
            _rlm_end(start_result["session_id"])


def test_rlm_index_drop_removes_correct_dir():
    from rlm_tools_bsl.server import _rlm_index
    from rlm_tools_bsl.bsl_index import get_index_db_path

    with tempfile.TemporaryDirectory() as tmpdir:
        src = _make_src_proj(tmpdir)
        idx_dir = os.path.join(tmpdir, "indexes")

        with patch.dict(os.environ, {"RLM_INDEX_DIR": idx_dir}):
            _rlm_index(action="build", path=src)

            cf_resolved = str((Path(src) / "cf").resolve())
            db_path = get_index_db_path(cf_resolved)
            assert db_path.exists()

            r = json.loads(_rlm_index(action="drop", path=src))
            assert r["action"] == "drop"
            assert not db_path.exists()


def test_rlm_index_build_jobs_key_matches_info_lookup(tmp_path, monkeypatch):
    """Round-3 #1: outer wrapper and _rlm_index must use the same key for _build_jobs."""
    from rlm_tools_bsl import projects as projects_mod
    from rlm_tools_bsl.projects import ProjectRegistry
    from rlm_tools_bsl.server import _build_jobs, _build_jobs_lock, _normalize_and_validate_path

    src_root = _make_src_proj(str(tmp_path))
    idx_dir = tmp_path / "indexes"

    # Isolated registry
    reg_path = tmp_path / "projects.json"
    reg = ProjectRegistry(reg_path)
    reg.add("test-src", src_root, password="pw")
    monkeypatch.setattr(projects_mod, "_registry", reg)

    try:
        monkeypatch.setenv("RLM_INDEX_DIR", str(idx_dir))

        # Pre-populate a fake in-progress job under the normalized key
        resolved, _err = _normalize_and_validate_path(src_root)
        with _build_jobs_lock:
            _build_jobs[resolved] = {
                "status": "building",
                "action": "build",
                "project": "test-src",
                "started_at": time.time(),
                "finished_at": None,
                "result": None,
                "error": None,
            }

        # info via project name — outer wrapper would canonicalize and look up job
        from rlm_tools_bsl.server import _rlm_index

        r = json.loads(_rlm_index(action="info", project="test-src"))
        assert r.get("build_status") == "building", f"expected building status, got {r}"

        # cleanup
        with _build_jobs_lock:
            _build_jobs.pop(resolved, None)
    finally:
        monkeypatch.setattr(projects_mod, "_registry", None)
