"""Command-line interface: argument parsing, validation and output."""

from __future__ import annotations

from enum import StrEnum
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from yt_dlp.version import __version__ as yt_dlp_version

from ytdl.csv_loader import CsvError, load_urls
from ytdl.downloader import Downloader, Result, Settings, Status, has_js_runtime, missing_tools

DEFAULT_AUDIO_QUALITY = 192
DEFAULT_VIDEO_QUALITY = 720
DEFAULT_SAVE_PATH = Path("ytdl-downloads")


class FileType(StrEnum):
    MP3 = "mp3"
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


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"ytdl {package_version('ytdl-cli')} (yt-dlp {yt_dlp_version})")
        raise typer.Exit()


@app.command(help="Download YouTube videos as MP3 or MP4.")
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
        typer.Option("--type", case_sensitive=False, help="Output file type."),
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
        Path,
        typer.Option("--save-path", metavar="DIR", file_okay=False, help="Folder to save downloads in."),
    ] = DEFAULT_SAVE_PATH,
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

    if (url is None) == (csv_list is None):
        raise typer.BadParameter("pass exactly one of them.", param_hint="'--url' / '--csv-list'")
    if url is not None and not url.strip():
        raise typer.BadParameter("URL can't be empty.", param_hint="'--url'")

    if file_type is FileType.MP4 and audio_quality is not None:
        _warn(err_console, "--audio-quality only applies to --type=mp3, so it's being ignored.")
    if file_type is FileType.MP3 and video_quality is not None:
        _warn(err_console, "--video-quality only applies to --type=mp4, so it's being ignored.")

    if csv_list is not None:
        try:
            urls = load_urls(csv_list)
        except CsvError as error:
            raise typer.BadParameter(str(error), param_hint="'--csv-list'") from error
    else:
        assert url is not None  # guaranteed by the exactly-one check above
        urls = [url.strip()]

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

    save_path = save_path.expanduser()
    try:
        save_path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise typer.BadParameter(
            f"Couldn't create {save_path}: {error.strerror}", param_hint="'--save-path'"
        ) from error

    settings = Settings(
        file_type=file_type.value,
        audio_quality=int(audio_quality.value) if audio_quality else DEFAULT_AUDIO_QUALITY,
        video_quality=int(video_quality.value) if video_quality else DEFAULT_VIDEO_QUALITY,
        save_path=save_path,
        verbose=verbose,
    )
    downloader = Downloader(settings, console)
    bulk = csv_list is not None

    results: list[Result] = []
    try:
        for number, video_url in enumerate(urls, start=1):
            label = f"[{number}/{len(urls)}] " if bulk else ""
            result = downloader.download(video_url, label)
            _print_result(console, result, label)
            results.append(result)
    except KeyboardInterrupt:
        err_console.print("\nCancelled.")
        raise typer.Exit(130) from None

    if bulk:
        _print_summary(console, results)
    raise typer.Exit(1 if any(r.status is Status.FAILED for r in results) else 0)


def _warn(console: Console, message: str) -> None:
    console.print(f"[yellow]Warning:[/yellow] {escape(message)}")


def _print_result(console: Console, result: Result, label: str) -> None:
    label = escape(label)
    name = escape(result.path.name if result.path else result.url)
    if result.status is Status.DOWNLOADED:
        console.print(f"{label}[green]✓[/green] {name}")
    elif result.status is Status.SKIPPED:
        console.print(f"{label}[dim]•[/dim] {name} [dim]already exists, skipped[/dim]")
    else:
        console.print(f"{label}[red]✗[/red] {escape(result.url)} [red]— {escape(result.error or '')}[/red]")


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


def main() -> None:
    app()
