"""Tests for the help(task) sandbox helper."""

import tempfile

from test_bsl_helpers import _make_bsl_fixture


def _get_help(tmpdir=None):
    """Get the help function from a BSL fixture."""
    if tmpdir is None:
        with tempfile.TemporaryDirectory() as td:
            bsl, _ = _make_bsl_fixture(td)
            return bsl["help"]
    bsl, _ = _make_bsl_fixture(tmpdir)
    return bsl["help"]


def test_help_no_args_returns_all_recipes():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help()
        assert "Available recipes" in result
        assert "help('find_exports')" in result
        assert "help('find_callers_context')" in result
        assert "help('parse_object_xml')" in result
        assert "help('safe_grep')" in result
        assert "help('read_procedure')" in result


def test_help_exports():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help("exports")
        assert "find_exports" in result
        assert "print(" in result


def test_help_exports_russian():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help("экспорт")
        assert "find_exports" in result


def test_help_callers():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help("call graph")
        assert "find_callers_context" in result


def test_help_callers_russian():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help("граф вызовов")
        assert "find_callers_context" in result


def test_help_metadata():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help("метаданные")
        assert "parse_object_xml" in result


def test_help_search():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help("поиск")
        assert "safe_grep" in result


def test_help_read():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help("read")
        assert "read_procedure" in result


def test_help_unknown_falls_back_to_all():
    with tempfile.TemporaryDirectory() as td:
        bsl_help = _get_help(td)
        result = bsl_help("xyzzy_gibberish_12345")
        assert "Available recipes" in result
