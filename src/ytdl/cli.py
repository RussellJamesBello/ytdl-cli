"""Command-line interface: argument parsing, validation and output."""

from __future__ import annotations

import shlex
from enum import StrEnum
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from rich.console import Console
from rich.markup import escape
from yt_dlp.version import __version__ as yt_dlp_version

from ytdl.config import ConfigError, load_config
from ytdl.csv_loader import FAILED_LIST_NAME, CsvError, load_urls, remove_failed_list, save_failed_list
from ytdl.downloader import (
    DEFAULT_NAME_TEMPLATE,
    Cancelled,
    Downloader,
    Result,
    Settings,
    Status,
    has_js_runtime,
    missing_tools,
    normalize_name_template,
)

DEFAULT_AUDIO_QUALITY = 192
DEFAULT_VIDEO_QUALITY = 720
DEFAULT_SAVE_PATH = Path("ytdl-downloads")


class FileType(StrEnum):
    MP3 = "mp3"
    M4A = "m4a"
    OPUS = "opus"
    MP4 = "mp4"


class AudioQuality(StrEnum):
    KBPS_320 = "320"
    KBPS_256 = "256"
    KBPS_192 = "192"
    KBPS_128 = "128"


class VideoQuality(StrEnum):
    P1080 = "1080"
    P720 = "720"
    P360 = "360"


app = typer.Typer(add_completion=False)

CONFIG_HELP = (
    "Defaults for --audio-quality, --video-quality, --save-path and --name-template can be set in "
    "~/.config/ytdl/config.toml (or the file $YTDL_CONFIG points to). Flags you pass override them."
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"ytdl {package_version('ytdl-cli')} (yt-dlp {yt_dlp_version})")
        raise typer.Exit()


@app.command(help="Download YouTube videos as audio (MP3, M4A, Opus) or MP4 video.", epilog=CONFIG_HELP)
def ytdl(
    *,
    url: Annotated[
        str | None,
        typer.Option("--url", metavar="URL", help="YouTube video to download. Use this or --csv-list."),
    ] = None,
    csv_list: Annotated[
        Path | None,
        typer.Option(
            "--csv-list",
            metavar="FILE",
            exists=True,
            dir_okay=False,
            readable=True,
            help="CSV file with one YouTube URL per row. Use this or --url.",
        ),
    ] = None,
    file_type: Annotated[
        FileType,
        typer.Option(
            "--type",
            case_sensitive=False,
            help="Output file type: mp3, m4a or opus for audio, mp4 for video.",
        ),
    ],
    audio_quality: Annotated[
        AudioQuality | None,
        typer.Option(
            "--audio-quality",
            show_default=False,
            help=f"MP3 bitrate in kbps. Only applies to --type=mp3. Default: {DEFAULT_AUDIO_QUALITY}.",
        ),
    ] = None,
    video_quality: Annotated[
        VideoQuality | None,
        typer.Option(
            "--video-quality",
            show_default=False,
            help=f"Maximum video resolution. Only applies to --type=mp4. Default: {DEFAULT_VIDEO_QUALITY}.",
        ),
    ] = None,
    save_path: Annotated[
        Path | None,
        typer.Option(
            "--save-path",
            metavar="DIR",
            file_okay=False,
            show_default=False,
            help=f"Folder to save downloads in. Default: ./{DEFAULT_SAVE_PATH}.",
        ),
    ] = None,
    name_template: Annotated[
        str | None,
        typer.Option(
            "--name-template",
            metavar="TEMPLATE",
            show_default=False,
            help=(
                'File name pattern using yt-dlp fields, e.g. "%(uploader)s - %(title)s". '
                "The extension is added for you. Use / for subfolders. "
                f'Default: "{DEFAULT_NAME_TEMPLATE}".'
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Show yt-dlp's full output, for diagnosing failed downloads."),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the ytdl and yt-dlp versions and exit.",
        ),
    ] = False,
) -> None:
    console = Console(highlight=False)
    err_console = Console(stderr=True, highlight=False)

    try:
        config = load_config()
    except ConfigError as error:
        raise typer.BadParameter(str(error), param_hint="config file") from error

    if (url is None) == (csv_list is None):
        raise typer.BadParameter("pass exactly one of them.", param_hint="'--url' / '--csv-list'")
    if url is not None and not url.strip():
        raise typer.BadParameter("URL can't be empty.", param_hint="'--url'")

    if file_type is not FileType.MP3 and audio_quality is not None:
        reason = "" if file_type is FileType.MP4 else f" ({file_type} keeps YouTube's original audio)"
        _warn(err_console, f"--audio-quality only applies to --type=mp3{reason}, so it's being ignored.")
    if file_type is not FileType.MP4 and video_quality is not None:
        _warn(err_console, "--video-quality only applies to --type=mp4, so it's being ignored.")

    if csv_list is not None:
        try:
            urls = load_urls(csv_list)
        except CsvError as error:
            raise typer.BadParameter(str(error), param_hint="'--csv-list'") from error
    else:
        assert url is not None  # guaranteed by the exactly-one check above
        urls = [url.strip()]

    if name_template is not None:
        try:
            name_template = normalize_name_template(name_template)
        except ValueError as error:
            raise typer.BadParameter(str(error), param_hint="'--name-template'") from error

    if missing := missing_tools():
        err_console.print(
            f"[red]Error:[/red] {' and '.join(missing)} not found. ytdl needs ffmpeg to convert "
            "and merge downloads. Install it with: brew install ffmpeg"
        )
        raise typer.Exit(1)
    if not has_js_runtime():
        _warn(
            err_console,
            "No JavaScript runtime found (Deno, Node, Bun or QuickJS). YouTube downloads may fail "
            "or be limited to lower quality. Install one with: brew install deno",
        )

    # A flag wins, then the config file, then the built-in default.
    settings = Settings(
        file_type=file_type.value,
        audio_quality=_first(
            int(audio_quality) if audio_quality else None, config.audio_quality, DEFAULT_AUDIO_QUALITY
        ),
        video_quality=_first(
            int(video_quality) if video_quality else None, config.video_quality, DEFAULT_VIDEO_QUALITY
        ),
        save_path=_first(save_path.expanduser() if save_path else None, config.save_path, DEFAULT_SAVE_PATH),
        name_template=_first(name_template, config.name_template, DEFAULT_NAME_TEMPLATE),
        verbose=verbose,
    )
    save_path = settings.save_path
    try:
        save_path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        source = "'--save-path'" if settings.save_path != config.save_path else f"save_path in {config.path}"
        raise typer.BadParameter(
            f"Couldn't create {save_path}: {error.strerror}", param_hint=source
        ) from error

    downloader = Downloader(settings, console)
    bulk = csv_list is not None

    results: list[Result] = []
    try:
        for number, video_url in enumerate(urls, start=1):
            label = f"[{number}/{len(urls)}] " if bulk else ""
            result = downloader.download(video_url, label)
            _print_result(console, result, label, save_path)
            results.append(result)
    except KeyboardInterrupt as interrupt:
        removed = interrupt.removed if isinstance(interrupt, Cancelled) else []
        cleanup = (
            f" Removed {len(removed)} partial file{'s' if len(removed) != 1 else ''}." if removed else ""
        )
        err_console.print(f"\nCancelled.{cleanup}")
        raise typer.Exit(130) from None

    if bulk:
        _print_summary(console, results)
        _update_failed_list(console, err_console, results, settings)
    raise typer.Exit(1 if any(r.status is Status.FAILED for r in results) else 0)


_T = TypeVar("_T")


def _first(*values: _T | None) -> _T:
    """The first value that was actually given."""
    for value in values:
        if value is not None:
            return value
    raise ValueError("no value given")


def _warn(console: Console, message: str) -> None:
    console.print(f"[yellow]Warning:[/yellow] {escape(message)}")


def _print_result(console: Console, result: Result, label: str, save_path: Path) -> None:
    label = escape(label)
    name = escape(_display_path(result.path, save_path) if result.path else result.url)
    if result.status is Status.DOWNLOADED:
        console.print(f"{label}[green]✓[/green] {name}")
    elif result.status is Status.SKIPPED:
        console.print(f"{label}[dim]•[/dim] {name} [dim]already exists, skipped[/dim]")
    else:
        console.print(f"{label}[red]✗[/red] {escape(result.url)} [red]— {escape(result.error or '')}[/red]")


def _display_path(path: Path, save_path: Path) -> str:
    # Relative to the save folder, so subfolders from --name-template are visible.
    try:
        return str(path.relative_to(save_path))
    except ValueError:
        return path.name


def _print_summary(console: Console, results: list[Result]) -> None:
    downloaded = sum(r.status is Status.DOWNLOADED for r in results)
    skipped = sum(r.status is Status.SKIPPED for r in results)
    failed = [r for r in results if r.status is Status.FAILED]

    console.print()
    console.print(
        f"[bold]Done:[/bold] {downloaded} downloaded, {skipped} skipped (already exists), "
        f"{len(failed)} failed"
    )
    for result in failed:
        console.print(f"  [red]✗[/red] {escape(result.url)} — {escape(result.error or '')}")


def _update_failed_list(
    console: Console, err_console: Console, results: list[Result], settings: Settings
) -> None:
    path = settings.save_path / FAILED_LIST_NAME
    failures = [(r.url, r.error or "") for r in results if r.status is Status.FAILED]
    if not failures:
        remove_failed_list(path)
        return

    command = _retry_command(settings, path)
    try:
        save_failed_list(path, failures, command)
    except OSError as error:
        _warn(err_console, f"Couldn't save the failed URLs to {path}: {error.strerror}")
        return
    console.print(f"\nFailed URLs saved to {escape(str(path))}. Retry them with:")
    console.print(f"  {escape(command)}", soft_wrap=True)


def _retry_command(settings: Settings, csv_path: Path) -> str:
    """The ytdl command that repeats this run's settings for the failed list."""
    parts = ["ytdl", f"--csv-list={csv_path}", f"--type={settings.file_type}"]
    if settings.file_type == FileType.MP3:
        parts.append(f"--audio-quality={settings.audio_quality}")
    if settings.file_type == FileType.MP4:
        parts.append(f"--video-quality={settings.video_quality}")
    if settings.save_path != DEFAULT_SAVE_PATH:
        parts.append(f"--save-path={settings.save_path}")
    if settings.name_template != DEFAULT_NAME_TEMPLATE:
        parts.append(f"--name-template={settings.name_template}")
    return shlex.join(parts)


def main() -> None:
    app()
