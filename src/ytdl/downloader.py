"""Downloading videos with yt-dlp and reporting what happened."""

from __future__ import annotations

import contextlib
import io
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# YouTube needs a JavaScript runtime to solve its player challenges. yt-dlp only
# enables Deno by default; enabling the rest lets an existing Node, Bun or QuickJS
# install work too. yt-dlp sandboxes whichever it uses (Node runs with --permission).
JS_RUNTIMES: dict[str, dict[str, str]] = {"deno": {}, "node": {}, "bun": {}, "quickjs": {}}
JS_RUNTIME_EXECUTABLES = ("deno", "node", "bun", "qjs")

MAX_TITLE_LENGTH = 50

_POSTPROCESSOR_ACTIVITY = {
    "ExtractAudio": "converting to MP3",
    "Merger": "merging video and audio",
}


class Status(Enum):
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class Settings:
    file_type: str  # "mp3" or "mp4"
    audio_quality: int  # kbps, used for mp3
    video_quality: int  # maximum resolution, used for mp4
    save_path: Path
    verbose: bool = False  # show yt-dlp's own output instead of ytdl's progress bar


@dataclass(frozen=True)
class Result:
    url: str
    status: Status
    path: Path | None = None
    error: str | None = None


def missing_tools() -> list[str]:
    """Return the ffmpeg executables that aren't on PATH."""
    return [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]


def has_js_runtime() -> bool:
    return any(shutil.which(executable) for executable in JS_RUNTIME_EXECUTABLES)


def build_options(settings: Settings) -> dict[str, Any]:
    """Translate ytdl settings into yt-dlp options."""
    options: dict[str, Any] = {
        "outtmpl": {"default": str(settings.save_path / "%(title)s.%(ext)s")},
        # A watch URL with &list=... downloads just the video, not the playlist.
        "noplaylist": True,
        # Don't resolve every entry of a playlist/channel URL; we reject those anyway.
        "extract_flat": "in_playlist",
        "js_runtimes": JS_RUNTIMES,
        "quiet": not settings.verbose,
        "no_warnings": not settings.verbose,
        "noprogress": not settings.verbose,
        "verbose": settings.verbose,
    }
    if settings.file_type == "mp3":
        options |= {
            "format": "bestaudio/best",
            "final_ext": "mp3",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(settings.audio_quality),
                }
            ],
        }
    else:
        options |= {
            "format": "bv*+ba/b",
            # Prefer H.264 + AAC so the MP4 plays everywhere without re-encoding, then
            # the highest resolution at or below the one requested.
            "format_sort": ["vcodec:h264", f"res:{settings.video_quality}", "acodec:aac"],
            "merge_output_format": "mp4",
        }
    return options


def resolution_note(info: dict[str, Any], settings: Settings) -> str | None:
    """Explain when an MP4 will be lower quality than requested."""
    if settings.file_type != "mp4":
        return None
    quality = _quality_label(info)
    if quality is not None and quality < settings.video_quality:
        return f"{settings.video_quality}p isn't available; downloading {quality}p instead."
    return None


def _quality_label(info: dict[str, Any]) -> int | None:
    # YouTube labels quality by its own ladder ("1080p" for a 1920x804 widescreen
    # video), so trust the label when there is one, then fall back to the short side.
    video = (info.get("requested_formats") or [info])[0]
    if match := re.match(r"(\d+)p", video.get("format_note") or ""):
        return int(match.group(1))
    sides = [side for side in (video.get("width"), video.get("height")) if side]
    return min(sides) if sides else None


_ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")


def clean_error(message: str) -> str:
    """Turn a yt-dlp error into a short message that makes sense for ytdl."""
    lines = _ANSI_CODES.sub("", message).strip().splitlines()
    message = lines[0] if lines else ""
    message = re.sub(r"^ERROR:\s*", "", message)
    message = re.sub(r"^\[[^\]]+\]\s*(?:[\w-]+:\s*)?", "", message)
    # yt-dlp suggests its own command-line flags, which ytdl doesn't have.
    message = re.sub(r"\s*(?:Use --cookies|Set --default-search).*$", "", message)
    return message.strip() or "Unknown error"


class Downloader:
    def __init__(self, settings: Settings, console: Console, ydl_class: type = YoutubeDL) -> None:
        self.settings = settings
        self.console = console
        self._ydl_class = ydl_class

    def download(self, url: str, label: str = "") -> Result:
        """Download one URL. Never raises for download problems; see Result."""
        progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=True,
            # No bar when output is piped or redirected, or when yt-dlp prints its own.
            disable=self.settings.verbose or not self.console.is_terminal,
        )
        task = progress.add_task(escape(f"{label}Fetching video info…"), total=None)
        hooks = _ProgressHooks(progress, task, label)
        options = build_options(self.settings) | {
            "progress_hooks": [hooks.on_download],
            "postprocessor_hooks": [hooks.on_postprocess],
        }
        if self.settings.verbose:
            quiet_stderr: contextlib.AbstractContextManager[object] = contextlib.nullcontext()
        else:
            options["logger"] = _SilentLogger()
            # Some yt-dlp helpers print warnings straight to stderr, bypassing the logger.
            quiet_stderr = contextlib.redirect_stderr(io.StringIO())

        try:
            with progress, quiet_stderr, self._ydl_class(options) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get("_type") == "playlist" or "entries" in info:
                    return Result(
                        url,
                        Status.FAILED,
                        error=("This is a playlist or channel link; ytdl only downloads single videos."),
                    )
                if info.get("is_live"):
                    return Result(url, Status.FAILED, error="Live streams can't be downloaded.")

                path = Path(ydl.prepare_filename(info)).with_suffix(f".{self.settings.file_type}")
                if path.exists():
                    return Result(url, Status.SKIPPED, path)

                if note := resolution_note(info, self.settings):
                    progress.console.print(f"{escape(label)}[yellow]![/yellow] {escape(note)}")
                hooks.title = info.get("title") or url
                # Reuse the info we already fetched rather than asking YouTube again.
                ydl.process_ie_result(ydl.sanitize_info(info, remove_private_keys=True), download=True)
        except DownloadError as error:
            return Result(url, Status.FAILED, error=clean_error(str(error)))
        except Exception as error:  # One bad video shouldn't stop a whole batch.
            return Result(url, Status.FAILED, error=str(error) or type(error).__name__)

        return Result(url, Status.DOWNLOADED, path)


class _ProgressHooks:
    """Feeds yt-dlp's progress callbacks into a Rich progress bar."""

    def __init__(self, progress: Progress, task: TaskID, label: str) -> None:
        self.progress = progress
        self.task = task
        self.label = label
        self.title = ""
        self._current_file: str | None = None
        self._total: float | None = None

    def _describe(self, activity: str) -> str:
        title = self.title
        if len(title) > MAX_TITLE_LENGTH:
            title = title[: MAX_TITLE_LENGTH - 1] + "…"
        return escape(f"{self.label}{title} · {activity}")

    def on_download(self, status: dict[str, Any]) -> None:
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        if status["status"] == "downloading":
            # MP4s arrive as two files (video, then audio); restart the bar for each.
            if status.get("filename") != self._current_file:
                self._current_file = status.get("filename")
                is_audio = (status.get("info_dict") or {}).get("vcodec") == "none"
                self.progress.reset(
                    self.task,
                    total=total,
                    description=self._describe("downloading audio" if is_audio else "downloading video"),
                )
            self._total = total or self._total
            self.progress.update(self.task, completed=status.get("downloaded_bytes") or 0, total=total)
        elif status["status"] == "finished" and self._total:
            self.progress.update(self.task, completed=self._total)

    def on_postprocess(self, status: dict[str, Any]) -> None:
        activity = _POSTPROCESSOR_ACTIVITY.get(status.get("postprocessor", ""))
        if status["status"] == "started" and activity:
            self.progress.update(self.task, description=self._describe(activity))


class _SilentLogger:
    """Hides yt-dlp's own output. Failures still surface as DownloadError."""

    def debug(self, message: str) -> None:
        pass

    info = warning = error = debug
