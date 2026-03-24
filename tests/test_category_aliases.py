"""Tests for find_by_type category normalization (singular, Russian aliases)."""

import tempfile

from test_bsl_helpers import _make_bsl_fixture
from rlm_tools_bsl.bsl_helpers import _normalize_category
from rlm_tools_bsl.format_detector import METADATA_CATEGORIES


# --- _normalize_category unit tests ---


def test_normalize_singular_to_plural():
    assert _normalize_category("InformationRegister") == "informationregisters"
    assert _normalize_category("Document") == "documents"
    assert _normalize_category("Catalog") == "catalogs"
    assert _normalize_category("CommonModule") == "commonmodules"
    assert _normalize_category("Report") == "reports"
    assert _normalize_category("DataProcessor") == "dataprocessors"
    assert _normalize_category("AccumulationRegister") == "accumulationregisters"
    assert _normalize_category("Constant") == "constants"


def test_normalize_plural_passthrough():
    assert _normalize_category("InformationRegisters") == "informationregisters"
    assert _normalize_category("Documents") == "documents"
    assert _normalize_category("Catalogs") == "catalogs"
    assert _normalize_category("CommonModules") == "commonmodules"


def test_normalize_russian_aliases():
    assert _normalize_category("РегистрСведений") == "informationregisters"
    assert _normalize_category("Документ") == "documents"
    assert _normalize_category("Справочник") == "catalogs"
    assert _normalize_category("Отчет") == "reports"
    assert _normalize_category("Обработка") == "dataprocessors"
    assert _normalize_category("ОбщийМодуль") == "commonmodules"
    assert _normalize_category("РегистрНакопления") == "accumulationregisters"
    assert _normalize_category("Константа") == "constants"


def test_normalize_case_insensitive():
    assert _normalize_category("informationregister") == "informationregisters"
    assert _normalize_category("INFORMATIONREGISTERS") == "informationregisters"
    assert _normalize_category("документ") == "documents"


def test_normalize_with_spaces_underscores():
    assert _normalize_category("Information Register") == "informationregisters"
    assert _normalize_category("Information_Register") == "informationregisters"


# --- find_by_type integration tests ---


def test_find_by_type_singular_document():
    with tempfile.TemporaryDirectory() as tmpdir:
        bsl, _ = _make_bsl_fixture(tmpdir)
        plural = bsl["find_by_type"]("Documents")
        singular = bsl["find_by_type"]("Document")
        assert len(plural) >= 1
        assert plural == singular


def test_find_by_type_singular_commonmodule():
    with tempfile.TemporaryDirectory() as tmpdir:
        bsl, _ = _make_bsl_fixture(tmpdir)
        plural = bsl["find_by_type"]("CommonModules", "МойМодуль")
        singular = bsl["find_by_type"]("CommonModule", "МойМодуль")
        assert len(plural) >= 1
        assert plural == singular


def test_find_by_type_russian_alias():
    with tempfile.TemporaryDirectory() as tmpdir:
        bsl, _ = _make_bsl_fixture(tmpdir)
        english = bsl["find_by_type"]("Documents")
        russian = bsl["find_by_type"]("Документ")
        assert len(english) >= 1
        assert english == russian


def test_xdto_packages_in_categories():
    assert "XDTOPackages" in METADATA_CATEGORIES


def test_external_data_sources_in_categories():
    assert "ExternalDataSources" in METADATA_CATEGORIES


def test_normalize_xdto_aliases():
    assert _normalize_category("XDTOPackage") == "xdtopackages"
    assert _normalize_category("ПакетXDTO") == "xdtopackages"
    assert _normalize_category("xdtopackages") == "xdtopackages"


def test_normalize_external_data_source_aliases():
    assert _normalize_category("ExternalDataSource") == "externaldatasources"
    assert _normalize_category("ВнешнийИсточникДанных") == "externaldatasources"
    assert _normalize_category("externaldatasources") == "externaldatasources"


def test_find_by_type_plural_still_works():
    """Regression: original plural names must still work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bsl, _ = _make_bsl_fixture(tmpdir)
        results = bsl["find_by_type"]("Documents")
        assert len(results) >= 1
        assert all(r["category"] == "Documents" for r in results)
