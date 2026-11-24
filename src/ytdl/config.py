"""Personal defaults from a TOML config file.

Precedence: a command-line flag wins, then the config file, then ytdl's built-in default.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ytdl.downloader import normalize_name_template

AUDIO_QUALITIES = (320, 256, 192, 128)
VIDEO_QUALITIES = (1080, 720, 360)
SETTINGS = ("audio_quality", "video_quality", "save_path", "name_template")


class ConfigError(Exception):
    """The config file exists but can't be used. The message names the file."""


@dataclass(frozen=True)
class Config:
    path: Path
    audio_quality: int | None = None
    video_quality: int | None = None
    save_path: Path | None = None
    name_template: str | None = None


def config_path() -> Path:
    """$YTDL_CONFIG if set, else $XDG_CONFIG_HOME/ytdl/config.toml (~/.config by default)."""
    if override := os.environ.get("YTDL_CONFIG"):
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "ytdl" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Read the config file. A missing file is fine and means no personal defaults."""
    path = path or config_path()
    if not path.is_file():
        return Config(path)

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"Couldn't read {path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} isn't valid TOML: {error}") from error

    if "type" in data:
        raise ConfigError(f"{path}: 'type' can't have a default. Pass --type each time instead.")
    if unknown := sorted(data.keys() - set(SETTINGS)):
        raise ConfigError(
            f"{path}: unknown setting{'s' if len(unknown) > 1 else ''} {', '.join(map(repr, unknown))}. "
            f"Valid settings are: {', '.join(SETTINGS)}."
        )

    return Config(
        path,
        audio_quality=_choice(path, data, "audio_quality", AUDIO_QUALITIES),
        video_quality=_choice(path, data, "video_quality", VIDEO_QUALITIES),
        save_path=_save_path(path, data),
        name_template=_name_template(path, data),
    )


def _choice(path: Path, data: dict[str, Any], key: str, allowed: tuple[int, ...]) -> int | None:
    if key not in data:
        return None
    value = data[key]
    # bool is a subclass of int in Python, so rule it out explicitly.
    if isinstance(value, bool) or value not in allowed:
        choices = ", ".join(map(str, allowed))
        raise ConfigError(f"{path}: {key} must be one of {choices} (a number, no quotes), not {value!r}.")
    return int(value)


def _save_path(path: Path, data: dict[str, Any]) -> Path | None:
    if "save_path" not in data:
        return None
    value = data["save_path"]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f'{path}: save_path must be a folder path in quotes, e.g. "~/Music".')
    return Path(value.strip()).expanduser()


def _name_template(path: Path, data: dict[str, Any]) -> str | None:
    if "name_template" not in data:
        return None
    value = data["name_template"]
    if not isinstance(value, str):
        raise ConfigError(f'{path}: name_template must be text in quotes, e.g. "%(uploader)s - %(title)s".')
    try:
        return normalize_name_template(value)
    except ValueError as error:
        raise ConfigError(f"{path}: name_template is invalid: {error}") from error
