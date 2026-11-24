from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from ytdl import cli
from ytdl.downloader import Result, Status

runner = CliRunner()


class FakeDownloader:
    """Records what the CLI asked for. URLs containing 'bad' fail."""

    instances: ClassVar[list["FakeDownloader"]] = []

    def __init__(self, settings, console):
        self.settings = settings
        self.calls: list[tuple[str, str]] = []
        FakeDownloader.instances.append(self)

    def download(self, url, label=""):
        self.calls.append((url, label))
        if "bad" in url:
            return Result(url, Status.FAILED, error="Video unavailable")
        path = self.settings.save_path / f"{url[-3:]}.{self.settings.file_type}"
        return Result(url, Status.DOWNLOADED, path)


@pytest.fixture(autouse=True)
def fakes(monkeypatch, tmp_path):
    FakeDownloader.instances = []
    monkeypatch.setattr(cli, "Downloader", FakeDownloader)
    monkeypatch.setattr(cli, "missing_tools", lambda: [])
    monkeypatch.setattr(cli, "has_js_runtime", lambda: True)
    monkeypatch.chdir(tmp_path)


def invoke(*args):
    return runner.invoke(cli.app, list(args))


def downloader():
    assert len(FakeDownloader.instances) == 1
    return FakeDownloader.instances[0]


def write_csv(tmp_path, content):
    path = tmp_path / "list.csv"
    path.write_text(content)
    return str(path)


# --- argument validation ----------------------------------------------------


def test_requires_url_or_csv():
    result = invoke("--type=mp3")
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_rejects_both_url_and_csv(tmp_path):
    result = invoke("--url=https://youtu.be/abc", f"--csv-list={write_csv(tmp_path, 'x')}", "--type=mp3")
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_requires_type():
    result = invoke("--url=https://youtu.be/abc")
    assert result.exit_code == 2
    assert "Missing option '--type'" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["--type=wav"],
        ["--type=mp3", "--audio-quality=999"],
        ["--type=mp4", "--video-quality=480"],
    ],
)
def test_rejects_invalid_choices(args):
    result = invoke("--url=https://youtu.be/abc", *args)
    assert result.exit_code == 2
    assert FakeDownloader.instances == []


def test_rejects_empty_url():
    result = invoke("--url=", "--type=mp3")
    assert result.exit_code == 2


def test_missing_csv_file():
    result = invoke("--csv-list=nope.csv", "--type=mp3")
    assert result.exit_code == 2


def test_csv_without_urls(tmp_path):
    csv_path = write_csv(tmp_path, "url\n# nothing\n")
    result = invoke(f"--csv-list={csv_path}", "--type=mp3")
    assert result.exit_code == 2
    assert "No URLs found" in result.output


def test_missing_ffmpeg(monkeypatch):
    monkeypatch.setattr(cli, "missing_tools", lambda: ["ffmpeg", "ffprobe"])
    result = invoke("--url=https://youtu.be/abc", "--type=mp3")
    assert result.exit_code == 1
    assert "ffmpeg and ffprobe not found" in result.output
    assert FakeDownloader.instances == []


def test_warns_without_js_runtime(monkeypatch):
    monkeypatch.setattr(cli, "has_js_runtime", lambda: False)
    result = invoke("--url=https://youtu.be/abc", "--type=mp3")
    assert result.exit_code == 0
    assert "No JavaScript runtime found" in result.output


# --- defaults and settings --------------------------------------------------


def test_defaults(tmp_path):
    result = invoke("--url=https://youtu.be/abc", "--type=mp3")

    assert result.exit_code == 0, result.output
    settings = downloader().settings
    assert settings.file_type == "mp3"
    assert settings.audio_quality == 192
    assert settings.video_quality == 720
    assert settings.save_path == Path("ytdl-downloads")
    assert (tmp_path / "ytdl-downloads").is_dir()


def test_explicit_settings(tmp_path):
    result = invoke(
        "--url",
        "https://youtu.be/abc",
        "--type",
        "MP4",
        "--video-quality",
        "1080",
        "--save-path",
        str(tmp_path / "out" / "nested"),
    )

    assert result.exit_code == 0, result.output
    settings = downloader().settings
    assert (settings.file_type, settings.video_quality) == ("mp4", 1080)
    assert (tmp_path / "out" / "nested").is_dir()


def test_save_path_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = invoke("--url=https://youtu.be/abc", "--type=mp3", "--save-path=~/Music")
    assert result.exit_code == 0, result.output
    assert downloader().settings.save_path == tmp_path / "Music"


def test_save_path_that_is_a_file(tmp_path):
    (tmp_path / "file.txt").touch()
    result = invoke("--url=https://youtu.be/abc", "--type=mp3", "--save-path=file.txt")
    assert result.exit_code == 2


@pytest.mark.parametrize(
    ("args", "warning"),
    [
        (["--type=mp4", "--audio-quality=320"], "--audio-quality only applies to --type=mp3"),
        (["--type=mp3", "--video-quality=1080"], "--video-quality only applies to --type=mp4"),
    ],
)
def test_warns_about_options_that_dont_apply(args, warning):
    result = invoke("--url=https://youtu.be/abc", *args)
    assert result.exit_code == 0
    assert warning in result.output


def test_no_warning_when_options_match_type():
    result = invoke("--url=https://youtu.be/abc", "--type=mp3", "--audio-quality=320")
    assert "Warning" not in result.output
    assert downloader().settings.audio_quality == 320


# --- running downloads ------------------------------------------------------


def test_single_url_success():
    result = invoke("--url=https://youtu.be/abc", "--type=mp3")

    assert result.exit_code == 0
    assert "✓ abc.mp3" in result.output
    assert "Done:" not in result.output
    assert downloader().calls == [("https://youtu.be/abc", "")]


def test_single_url_failure():
    result = invoke("--url=https://youtu.be/bad", "--type=mp3")
    assert result.exit_code == 1
    assert "✗ https://youtu.be/bad — Video unavailable" in result.output


def test_bulk_keeps_going_and_summarises(tmp_path):
    csv_path = write_csv(tmp_path, "url\nhttps://youtu.be/one\nhttps://youtu.be/bad\nhttps://youtu.be/two\n")

    result = invoke(f"--csv-list={csv_path}", "--type=mp4")

    assert result.exit_code == 1
    assert [label for _, label in downloader().calls] == ["[1/3] ", "[2/3] ", "[3/3] "]
    assert "[1/3] ✓ one.mp4" in result.output
    assert "[3/3] ✓ two.mp4" in result.output
    assert "Done: 2 downloaded, 0 skipped (already exists), 1 failed" in result.output


def test_bulk_all_succeed(tmp_path):
    csv_path = write_csv(tmp_path, "https://youtu.be/one\nhttps://youtu.be/two\n")
    result = invoke(f"--csv-list={csv_path}", "--type=mp3")
    assert result.exit_code == 0
    assert "Done: 2 downloaded, 0 skipped (already exists), 0 failed" in result.output
