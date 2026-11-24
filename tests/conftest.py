import pytest


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch):
    # Rich wraps output at 80 columns when it can't detect a terminal; widen it so
    # assertions don't depend on where long lines happen to break.
    monkeypatch.setenv("COLUMNS", "300")
    monkeypatch.setenv("TERMINAL_WIDTH", "300")


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    # Never read the real ~/.config/ytdl/config.toml. Tests that need a config write
    # to this path, which starts out missing.
    path = tmp_path / "ytdl-config.toml"
    monkeypatch.setenv("YTDL_CONFIG", str(path))
    return path
