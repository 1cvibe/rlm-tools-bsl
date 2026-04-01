"""Presentation-layer formatting utilities (no domain dependencies)."""


def number_lines(text: str, start: int = 1) -> str:
    """Add absolute line numbers: '  42 | code'."""
    lines = text.splitlines()
    if not lines:
        return text
    width = len(str(start + len(lines) - 1))
    return "\n".join(f"{start + i:>{width}} | {ln}" for i, ln in enumerate(lines))
