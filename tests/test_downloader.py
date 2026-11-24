import io
from typing import Any, ClassVar

import pytest
from rich.console import Console
from yt_dlp.utils import DownloadError

from ytdl.downloader import (
    Cancelled,
    Downloader,
    Settings,
    Status,
    build_options,
    clean_error,
    normalize_name_template,
    resolution_note,
)


def settings(tmp_path, file_type="mp3", audio_quality=192, video_quality=720, **extra):
    return Settings(file_type, audio_quality, video_quality, tmp_path, **extra)


# --- yt-dlp options ---------------------------------------------------------


def test_mp3_options(tmp_path):
    options = build_options(settings(tmp_path, "mp3", audio_quality=320))

    assert options["format"] == "bestaudio/best"
    assert options["final_ext"] == "mp3"
    assert options["postprocessors"][0] == {
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "320",
    }
    assert options["outtmpl"]["default"] == str(tmp_path / "%(title)s.%(ext)s")
    assert options["noplaylist"] is True


@pytest.mark.parametrize(("file_type", "format_spec"), [("m4a", "[ext=m4a]"), ("opus", "[acodec=opus]")])
def test_m4a_and_opus_keep_original_audio(tmp_path, file_type, format_spec):
    options = build_options(settings(tmp_path, file_type, audio_quality=320))

    assert options["format"].startswith(f"bestaudio{format_spec}/")
    assert options["final_ext"] == file_type
    assert options["postprocessors"][0] == {
        "key": "FFmpegExtractAudio",
        "preferredcodec": file_type,
        "preferredquality": None,
    }


@pytest.mark.parametrize("file_type", ["mp3", "m4a", "opus"])
def test_audio_gets_tags_and_cover_art_after_conversion(tmp_path, file_type):
    options = build_options(settings(tmp_path, file_type))

    assert options["writethumbnail"] is True
    assert [pp["key"] for pp in options["postprocessors"]] == [
        "FFmpegExtractAudio",
        "FFmpegMetadata",
        "EmbedThumbnail",
    ]
    assert options["postprocessors"][1]["add_metadata"] is True


def test_mp4_options_prefer_h264_aac_up_to_requested_resolution(tmp_path):
    options = build_options(settings(tmp_path, "mp4", video_quality=1080))

    assert options["format_sort"] == ["vcodec:h264", "res:1080", "acodec:aac"]
    assert options["merge_output_format"] == "mp4"
    assert "postprocessors" not in options
    assert "writethumbnail" not in options


def test_name_template_sets_output_path(tmp_path):
    options = build_options(settings(tmp_path, name_template="%(uploader)s/%(title)s"))
    assert options["outtmpl"]["default"] == str(tmp_path / "%(uploader)s" / "%(title)s.%(ext)s")


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("%(title)s", "%(title)s"),
        ("  %(uploader)s - %(title)s  ", "%(uploader)s - %(title)s"),
        ("%(title)s.%(ext)s", "%(title)s"),
        ("%(uploader)s/%(title)s", "%(uploader)s/%(title)s"),
        ("%(upload_date>%Y)s %(title)s", "%(upload_date>%Y)s %(title)s"),
    ],
)
def test_valid_name_templates(template, expected):
    assert normalize_name_template(template) == expected


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("", "can't be empty"),
        (".%(ext)s", "can't be empty"),
        ("my song", "at least one field"),
        ("/music/%(title)s", "use --save-path"),
        ("~/music/%(title)s", "use --save-path"),
        ("../%(title)s", "outside the save folder"),
        ("%(title", "incomplete format key"),
        ("%(title)z", "unsupported format"),
    ],
)
def test_invalid_name_templates(template, message):
    with pytest.raises(ValueError, match=message):
        normalize_name_template(template)


def test_quiet_by_default(tmp_path):
    options = build_options(settings(tmp_path))
    assert options["quiet"] is True
    assert options["verbose"] is False


def test_verbose_options(tmp_path):
    options = build_options(settings(tmp_path, verbose=True))
    assert (options["quiet"], options["no_warnings"], options["noprogress"]) == (False, False, False)
    assert options["verbose"] is True


def test_node_is_enabled_alongside_deno(tmp_path):
    runtimes = build_options(settings(tmp_path))["js_runtimes"]
    assert {"deno", "node"} <= runtimes.keys()


# --- resolution notice ------------------------------------------------------


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        ({"format_note": "720p", "width": 1280, "height": 720}, "downloading 720p instead"),
        ({"format_note": "1080p60", "width": 1920, "height": 1080}, None),
        # Widescreen films are labelled 1080p even though they're only 804 pixels tall.
        ({"format_note": "1080p", "width": 1920, "height": 804}, None),
        # No label: use the short side, so a 720x1280 vertical video counts as 720p.
        ({"width": 720, "height": 1280}, "downloading 720p instead"),
        # Merged formats: the video stream comes first.
        ({"requested_formats": [{"format_note": "480p"}, {"format_note": "medium"}]}, "downloading 480p"),
        ({}, None),
    ],
)
def test_resolution_note(tmp_path, info, expected):
    note = resolution_note(info, settings(tmp_path, "mp4", video_quality=1080))
    if expected is None:
        assert note is None
    else:
        assert note is not None
        assert expected in note


@pytest.mark.parametrize("file_type", ["mp3", "m4a", "opus"])
def test_no_resolution_note_for_audio(tmp_path, file_type):
    assert resolution_note({"height": 144}, settings(tmp_path, file_type)) is None


# --- error messages ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ERROR: [youtube] dQw4w9-WgXc: Video unavailable", "Video unavailable"),
        ("\x1b[0;31mERROR:\x1b[0m [youtube] abc: Private video", "Private video"),
        (
            "ERROR: [youtube] abc: Sign in to confirm you're not a bot. "
            "Use --cookies-from-browser or --cookies",
            "Sign in to confirm you're not a bot.",
        ),
        (
            "ERROR: 'nope' is not a valid URL. Set --default-search \"ytsearch\" to search YouTube",
            "'nope' is not a valid URL.",
        ),
        ("ERROR: first line\nsecond line", "first line"),
        ("", "Unknown error"),
    ],
)
def test_clean_error(raw, expected):
    assert clean_error(raw) == expected


# --- downloading ------------------------------------------------------------


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL. Configure the class attributes per test."""

    info: ClassVar[dict[str, Any]] = {}
    error: ClassVar[Exception | None] = None
    downloads: ClassVar[list[dict[str, Any]]] = []
    last_options: ClassVar[dict[str, Any]] = {}

    def __init__(self, options):
        self.options = options
        FakeYoutubeDL.last_options = options

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download):
        assert download is False
        if self.error:
            raise self.error
        return self.info

    def prepare_filename(self, info):
        return self.options["outtmpl"]["default"] % info

    @staticmethod
    def sanitize_info(info, remove_private_keys=False):
        return info

    def process_ie_result(self, info, download):
        assert download is True
        self.downloads.append(info)


@pytest.fixture
def fake_ydl():
    FakeYoutubeDL.info = {"title": "Some Song", "ext": "webm"}
    FakeYoutubeDL.error = None
    FakeYoutubeDL.downloads = []
    return FakeYoutubeDL


def run(tmp_path, fake_ydl, **kwargs):
    output = io.StringIO()
    downloader = Downloader(settings(tmp_path, **kwargs), Console(file=output, width=300), ydl_class=fake_ydl)
    return downloader.download("https://youtu.be/x", label="[1/2] "), output.getvalue()


def test_downloads_and_reports_final_mp3_path(tmp_path, fake_ydl):
    result, _ = run(tmp_path, fake_ydl)

    assert result.status is Status.DOWNLOADED
    assert result.path == tmp_path / "Some Song.mp3"
    assert len(fake_ydl.downloads) == 1


def test_yt_dlp_output_is_silenced_unless_verbose(tmp_path, fake_ydl):
    run(tmp_path, fake_ydl)
    assert "logger" in fake_ydl.last_options

    run(tmp_path, fake_ydl, verbose=True)
    assert "logger" not in fake_ydl.last_options


def test_skip_check_uses_name_template(tmp_path, fake_ydl):
    fake_ydl.info = {"title": "Song", "uploader": "Band", "ext": "webm"}
    (tmp_path / "Band - Song.mp3").touch()

    result, _ = run(tmp_path, fake_ydl, name_template="%(uploader)s - %(title)s")

    assert result.status is Status.SKIPPED
    assert result.path == tmp_path / "Band - Song.mp3"


def test_titles_with_dots_keep_their_full_name(tmp_path, fake_ydl):
    fake_ydl.info = {"title": "Mr. Brightside v2.0", "ext": "m4a"}
    result, _ = run(tmp_path, fake_ydl)
    assert result.path.name == "Mr. Brightside v2.0.mp3"


def test_skips_when_file_already_exists(tmp_path, fake_ydl):
    (tmp_path / "Some Song.mp3").touch()

    result, _ = run(tmp_path, fake_ydl)

    assert result.status is Status.SKIPPED
    assert result.path == tmp_path / "Some Song.mp3"
    assert fake_ydl.downloads == []


def test_opus_download_gets_opus_extension(tmp_path, fake_ydl):
    result, _ = run(tmp_path, fake_ydl, file_type="opus")
    assert result.path == tmp_path / "Some Song.opus"


def test_existing_file_of_other_type_does_not_cause_skip(tmp_path, fake_ydl):
    (tmp_path / "Some Song.mp3").touch()
    fake_ydl.info = {"title": "Some Song", "ext": "mp4", "format_note": "720p"}

    result, _ = run(tmp_path, fake_ydl, file_type="mp4")

    assert result.status is Status.DOWNLOADED
    assert result.path == tmp_path / "Some Song.mp4"


def test_prints_resolution_notice_with_label(tmp_path, fake_ydl):
    fake_ydl.info = {"title": "Old Clip", "ext": "mp4", "format_note": "240p"}

    result, output = run(tmp_path, fake_ydl, file_type="mp4", video_quality=1080)

    assert result.status is Status.DOWNLOADED
    assert "[1/2] ! 1080p isn't available; downloading 240p instead." in output


def test_ctrl_c_removes_only_this_downloads_partial_files(tmp_path, fake_ydl, monkeypatch):
    keep = [tmp_path / "Some Song.mp4", tmp_path / "Some Songs.mp3", tmp_path / "Other.webm.part"]
    for file in keep:
        file.touch()

    def interrupted_download(self, info, download):
        (tmp_path / "Some Song.webm.part").write_bytes(b"partial")
        (tmp_path / "Some Song.webp").write_bytes(b"thumbnail")
        raise KeyboardInterrupt

    monkeypatch.setattr(fake_ydl, "process_ie_result", interrupted_download)

    with pytest.raises(Cancelled) as cancelled:
        run(tmp_path, fake_ydl)

    assert [file.name for file in cancelled.value.removed] == ["Some Song.webm.part", "Some Song.webp"]
    assert sorted(tmp_path.iterdir()) == sorted(keep)


def test_ctrl_c_removes_subfolder_it_created(tmp_path, fake_ydl, monkeypatch):
    fake_ydl.info = {"title": "Song", "uploader": "Band", "ext": "webm"}

    def interrupted_download(self, info, download):
        (tmp_path / "Band").mkdir()
        (tmp_path / "Band" / "Song.webm.part").touch()
        raise KeyboardInterrupt

    monkeypatch.setattr(fake_ydl, "process_ie_result", interrupted_download)

    with pytest.raises(Cancelled):
        run(tmp_path, fake_ydl, name_template="%(uploader)s/%(title)s")

    assert list(tmp_path.iterdir()) == []


def test_download_error_becomes_failed_result(tmp_path, fake_ydl):
    fake_ydl.error = DownloadError("ERROR: [youtube] x: Video unavailable")

    result, _ = run(tmp_path, fake_ydl)

    assert result.status is Status.FAILED
    assert result.error == "Video unavailable"


def test_unexpected_error_becomes_failed_result(tmp_path, fake_ydl):
    fake_ydl.error = RuntimeError("boom")
    result, _ = run(tmp_path, fake_ydl)
    assert (result.status, result.error) == (Status.FAILED, "boom")


def test_rejects_playlists(tmp_path, fake_ydl):
    fake_ydl.info = {"_type": "playlist", "title": "Mix", "entries": []}

    result, _ = run(tmp_path, fake_ydl)

    assert result.status is Status.FAILED
    assert "playlist" in result.error
    assert fake_ydl.downloads == []


def test_rejects_live_streams(tmp_path, fake_ydl):
    fake_ydl.info = {"title": "Live now", "ext": "mp4", "is_live": True}
    result, _ = run(tmp_path, fake_ydl)
    assert result.status is Status.FAILED
    assert "Live" in result.error
