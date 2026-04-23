"""Tests for resolve_config_root() (issue #11)."""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path

from rlm_tools_bsl.extension_detector import (
    ConfigRole,
    resolve_config_root,
)


_CF_MAIN_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses">
        <Configuration uuid="00000000-0000-0000-0000-000000000001">
            <Properties>
                <Name>Main</Name>
                <NamePrefix/>
            </Properties>
        </Configuration>
    </MetaDataObject>
""")


def _cf_extension_xml(name: str = "Ext1", purpose: str = "Customization", prefix: str = "ext_") -> str:
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses">
            <Configuration uuid="00000000-0000-0000-0000-000000000099">
                <Properties>
                    <Name>{name}</Name>
                    <ConfigurationExtensionPurpose>{purpose}</ConfigurationExtensionPurpose>
                    <NamePrefix>{prefix}</NamePrefix>
                </Properties>
            </Configuration>
        </MetaDataObject>
    """)


_EDT_MAIN_MDO = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <mdclass:Configuration xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass"
                           uuid="00000000-0000-0000-0000-000000000003">
        <name>Main</name>
    </mdclass:Configuration>
""")


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_resolve_config_root_cf_direct():
    with tempfile.TemporaryDirectory() as d:
        _write(os.path.join(d, "Configuration.xml"), _CF_MAIN_XML)
        effective, candidates = resolve_config_root(d)
        assert effective == d
        assert candidates == []


def test_resolve_config_root_edt_direct():
    with tempfile.TemporaryDirectory() as d:
        _write(os.path.join(d, "Configuration", "Configuration.mdo"), _EDT_MAIN_MDO)
        effective, candidates = resolve_config_root(d)
        assert effective == d
        assert candidates == []


def test_resolve_config_root_src_parent_with_cf_cfe():
    with tempfile.TemporaryDirectory() as root:
        src = os.path.join(root, "src")
        _write(os.path.join(src, "cf", "Configuration.xml"), _CF_MAIN_XML)
        _write(os.path.join(src, "cfe", "MyExt", "Configuration.xml"), _cf_extension_xml("MyExt"))

        effective, candidates = resolve_config_root(src)
        assert Path(effective) == Path(src) / "cf"
        # Only the MAIN cf/ is a candidate; cfe/ is not MAIN, cfe/MyExt is nested
        assert len(candidates) == 1
        assert candidates[0].role == ConfigRole.MAIN
        assert Path(candidates[0].path).name == "cf"


def test_resolve_config_root_multiple_main_with_cf():
    with tempfile.TemporaryDirectory() as root:
        src = os.path.join(root, "src")
        _write(os.path.join(src, "cf", "Configuration.xml"), _CF_MAIN_XML)
        _write(os.path.join(src, "other", "Configuration.xml"), _CF_MAIN_XML)
        effective, candidates = resolve_config_root(src)
        assert Path(effective).name == "cf"
        assert len(candidates) == 2


def test_resolve_config_root_multiple_main_without_cf():
    with tempfile.TemporaryDirectory() as root:
        src = os.path.join(root, "src")
        _write(os.path.join(src, "main1", "Configuration.xml"), _CF_MAIN_XML)
        _write(os.path.join(src, "main2", "Configuration.xml"), _CF_MAIN_XML)

        effective, candidates = resolve_config_root(src)
        # ambiguous — return base_path unchanged, candidates populated
        assert Path(effective) == Path(src)
        assert len(candidates) == 2
        assert {Path(c.path).name for c in candidates} == {"main1", "main2"}


def test_resolve_config_root_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        effective, candidates = resolve_config_root(d)
        assert effective == d
        assert candidates == []


def test_resolve_config_root_case_insensitive_cf_name():
    with tempfile.TemporaryDirectory() as root:
        src = os.path.join(root, "src")
        _write(os.path.join(src, "CF", "Configuration.xml"), _CF_MAIN_XML)
        _write(os.path.join(src, "OtherMain", "Configuration.xml"), _CF_MAIN_XML)

        effective, candidates = resolve_config_root(src)
        assert Path(effective).name == "CF"
        assert len(candidates) == 2


def test_resolve_config_root_depth_limited():
    """Round-1 #4: no wrapper-dir recursion like _detect_single.

    wrapper/real_cf/Configuration.xml exists but wrapper/ is NOT a candidate.
    """
    with tempfile.TemporaryDirectory() as root:
        src = os.path.join(root, "src")
        _write(os.path.join(src, "wrapper", "real_cf", "Configuration.xml"), _CF_MAIN_XML)
        effective, candidates = resolve_config_root(src)
        # wrapper/ is not itself a config root and depth=1 stops there
        assert Path(effective) == Path(src)
        assert candidates == []


def test_resolve_config_root_arbitrary_container_name():
    """Round-2 #2: no hardcoded 'src'. Cyrillic container name works the same."""
    with tempfile.TemporaryDirectory() as root:
        container = os.path.join(root, "МоиБазы", "База_тест_ЕРП")
        _write(os.path.join(container, "cf", "Configuration.xml"), _CF_MAIN_XML)
        _write(os.path.join(container, "cfe", "Ext", "Configuration.xml"), _cf_extension_xml("Ext"))
        effective, candidates = resolve_config_root(container)
        assert Path(effective) == Path(container) / "cf"
        assert len(candidates) == 1


def test_is_path_registered_normalizes_both_sides(tmp_path):
    """Round-2 #1: registry entry and query are both cf-normalized."""
    from rlm_tools_bsl.projects import ProjectRegistry

    src = tmp_path / "proj" / "src"
    (src / "cf").mkdir(parents=True)
    (src / "cf" / "Configuration.xml").write_text(_CF_MAIN_XML, encoding="utf-8")

    reg_path = tmp_path / "registry.json"
    reg = ProjectRegistry(reg_path)
    reg.add("test", str(src / "cf"), password="pw")

    assert reg.is_path_registered(str(src)) is True
    assert reg.is_path_registered(str(src / "cf")) is True


def test_is_path_registered_canonicalization_preserved(tmp_path, monkeypatch):
    """Round-3 #2: canonical semantics preserved (relative/backslash/resolve)."""
    from rlm_tools_bsl.projects import ProjectRegistry

    src = tmp_path / "proj" / "src" / "cf"
    src.mkdir(parents=True)
    (src / "Configuration.xml").write_text(_CF_MAIN_XML, encoding="utf-8")

    reg_path = tmp_path / "registry.json"
    reg = ProjectRegistry(reg_path)
    reg.add("test", str(src), password="pw")

    # From the project root, the relative path "./src/cf" must resolve the same
    monkeypatch.chdir(tmp_path / "proj")
    assert reg.is_path_registered(os.path.join(".", "src", "cf")) is True
    assert reg.is_path_registered(os.path.join(".", "src")) is True
