from pathlib import Path

import pytest

from ytdl.config import Config, ConfigError, config_path, load_config


def write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_file_means_no_defaults(tmp_path):
    assert load_config(tmp_path / "nope.toml") == Config(tmp_path / "nope.toml")


def test_all_settings(tmp_path):
    path = write(
        tmp_path / "config.toml",
        'audio_quality = 320\nvideo_quality = 1080\nsave_path = "~/Music"\n'
        'name_template = "%(uploader)s - %(title)s.%(ext)s"\n',
    )

    config = load_config(path)

    assert config.audio_quality == 320
    assert config.video_quality == 1080
    assert config.save_path == Path("~/Music").expanduser()
    assert config.name_template == "%(uploader)s - %(title)s"


def test_empty_file(tmp_path):
    path = write(tmp_path / "config.toml", "# nothing set yet\n")
    assert load_config(path) == Config(path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('type = "mp3"', "'type' can't have a default"),
        ("audio_qualty = 320", "unknown setting 'audio_qualty'. Valid settings are: audio_quality"),
        ("a = 1\nb = 2", "unknown settings 'a', 'b'"),
        ("audio_quality = 999", "audio_quality must be one of 320, 256, 192, 128"),
        ('audio_quality = "320"', "audio_quality must be one of .* not '320'"),
        ("video_quality = true", "video_quality must be one of 1080, 720, 360 .* not True"),
        ("save_path = 5", "save_path must be a folder path"),
        ('save_path = "  "', "save_path must be a folder path"),
        ("name_template = 5", "name_template must be text"),
        ('name_template = "no fields"', "name_template is invalid: the template needs at least one field"),
        ("audio_quality = ", "isn't valid TOML"),
    ],
)
def test_invalid_config(tmp_path, content, message):
    path = write(tmp_path / "config.toml", content)
    with pytest.raises(ConfigError, match=message) as error:
        load_config(path)
    assert str(path) in str(error.value)


def test_config_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("YTDL_CONFIG")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_path() == tmp_path / ".config" / "ytdl" / "config.toml"


def test_config_path_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("YTDL_CONFIG")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config_path() == tmp_path / "xdg" / "ytdl" / "config.toml"


def test_config_path_override(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDL_CONFIG", str(tmp_path / "custom.toml"))
    assert config_path() == tmp_path / "custom.toml"
