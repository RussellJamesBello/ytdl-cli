import pytest


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch):
    # Rich wraps output at 80 columns when it can't detect a terminal; widen it so
    # assertions don't depend on where long lines happen to break.
    monkeypatch.setenv("COLUMNS", "300")
    monkeypatch.setenv("TERMINAL_WIDTH", "300")
