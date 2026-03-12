"""Tests that the strategy text contains recipes, return formats, and code examples."""

from rlm_tools_bsl.bsl_knowledge import get_strategy


def _get_strategy_text():
    return get_strategy("medium", None)


def test_strategy_contains_recipes():
    s = _get_strategy_text()
    assert "RECIPES" in s


def test_strategy_contains_return_formats():
    s = _get_strategy_text()
    assert "RETURN FORMATS" in s


def test_strategy_contains_print_calls():
    s = _get_strategy_text()
    assert "print(" in s


def test_strategy_contains_find_module_example():
    s = _get_strategy_text()
    assert "find_module(" in s


def test_strategy_contains_find_exports_example():
    s = _get_strategy_text()
    assert "find_exports(" in s


def test_strategy_contains_find_callers_context_example():
    s = _get_strategy_text()
    assert "find_callers_context(" in s


def test_strategy_contains_help_mention():
    s = _get_strategy_text()
    assert "help(" in s


def test_strategy_mentions_python_sandbox():
    s = _get_strategy_text()
    assert "Python" in s


def test_strategy_all_effort_levels():
    """All effort levels should produce strategy with recipes."""
    for effort in ("low", "medium", "high", "max"):
        s = get_strategy(effort, None)
        assert "RECIPES" in s, f"Missing RECIPES for effort={effort}"
        assert "RETURN FORMATS" in s, f"Missing RETURN FORMATS for effort={effort}"
