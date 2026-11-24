# ytdl

[![CI](https://github.com/RussellJamesBello/ytdl-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/RussellJamesBello/ytdl-cli/actions/workflows/ci.yml)

A small command-line tool for downloading YouTube videos as audio (**MP3**, **M4A** or **Opus**) or **MP4** video, one at a time or in bulk from a CSV file.

It's a thin, opinionated wrapper around [yt-dlp](https://github.com/yt-dlp/yt-dlp), which handles talking to YouTube, and [ffmpeg](https://ffmpeg.org/), which handles merging and conversion.

```bash
ytdl --url="https://www.youtube.com/watch?v=VIDEO_ID" --type=mp3
```

---

## Features

- Download a single video, or a whole list of URLs from a CSV file
- MP3 output at 128, 192, 256 or 320 kbps
- M4A or Opus output with YouTube's original audio copied as is: smaller files, no quality loss
- Audio files come tagged with title, artist, date and cover art, so music apps display them properly
- MP4 output at 360p, 720p or 1080p, using H.264 + AAC so it plays on any device
- Falls back to the best available resolution if the one you asked for doesn't exist
- Skips files you've already downloaded, so re-running a batch only fetches what's missing
- Bulk mode keeps going when one video fails and prints a summary at the end

---

## Requirements

| Dependency | Version | Why |
|---|---|---|
| Python | 3.11+ | Runtime |
| [ffmpeg](https://ffmpeg.org/) | any recent | Converts and repackages audio, and merges the video and audio streams for MP4 |
| [uv](https://docs.astral.sh/uv/) | any recent | Installs and runs the project |
| A JavaScript runtime: [Deno](https://deno.com/), Node 22+, Bun or QuickJS | see left | YouTube makes clients run JavaScript before it hands over the video. yt-dlp runs it sandboxed. |

On macOS:

```bash
brew install ffmpeg

# uv: if you manage tools with mise, this repo pins it in mise.toml
mise install
# ...or without mise
brew install uv

# JavaScript runtime: skip this if you already have Node 22+ on your PATH
brew install deno
```

---

## Installation

```bash
git clone <repo-url> ytdl-cli
cd ytdl-cli
uv tool install .
```

This puts the `ytdl` command on your `PATH`. Check it worked:

```bash
ytdl --help
```

To uninstall:

```bash
uv tool uninstall ytdl-cli
```

---

## Usage

```bash
ytdl (--url=<URL> | --csv-list=<FILE>) --type=<mp3|m4a|opus|mp4> [options]
```

### Options

| Option | Values | Default | Description |
|---|---|---|---|
| `--url` | YouTube video URL | — | A single video to download. Use either this or `--csv-list`. |
| `--csv-list` | Path to a `.csv` file | — | A file of URLs to download in bulk. Use either this or `--url`. |
| `--type` | `mp3`, `m4a`, `opus`, `mp4` | **required** | Output file type. `m4a` and `opus` are audio-only, like `mp3`. |
| `--audio-quality` | `320`, `256`, `192`, `128` | `192` | MP3 bitrate in kbps. Only applies to `--type=mp3`. |
| `--video-quality` | `1080`, `720`, `360` | `720` | Maximum video height in pixels. Only applies to `--type=mp4`. |
| `--save-path` | Directory path | `./ytdl-downloads` | Where files are saved. Created if it doesn't exist. |
| `--name-template` | yt-dlp template | `%(title)s` | How files are named. The extension is added for you. See [File names](#behaviour-details). |
| `--verbose` | — | off | Show yt-dlp's full output in place of the progress bar. Use it when a download fails and the reason isn't clear. |
| `--version` | — | — | Print the ytdl and yt-dlp versions, then exit. |

You must pass **exactly one** of `--url` or `--csv-list`. Both `--flag=value` and `--flag value` work.

### Examples

Download a song as MP3 at the default 192 kbps:

```bash
ytdl --url="https://www.youtube.com/watch?v=VIDEO_ID" --type=mp3
```

Download an MP3 at 320 kbps into your Music folder:

```bash
ytdl --url="https://youtu.be/VIDEO_ID" --type=mp3 --audio-quality=320 --save-path=~/Music
```

Keep YouTube's original audio with no re-encoding (M4A suits Apple devices best; Opus gives the smallest files):

```bash
ytdl --url="https://youtu.be/VIDEO_ID" --type=m4a
```

Download a video in 1080p:

```bash
ytdl --url="https://www.youtube.com/watch?v=VIDEO_ID" --type=mp4 --video-quality=1080
```

Name files "Artist - Title" and sort them into a folder per channel:

```bash
ytdl --url="https://youtu.be/VIDEO_ID" --type=mp3 --name-template="%(uploader)s/%(uploader)s - %(title)s"
```

Download everything in a CSV as 720p MP4s:

```bash
ytdl --csv-list=./playlist.csv --type=mp4
```

> **Tip:** Always put URLs in quotes. They often contain `&`, which your shell would otherwise treat as a command separator.

---

## CSV format

Put one URL per row, in the first column. The tool:

- skips a header row if the first cell is `url` (any capitalisation)
- skips blank lines
- skips lines starting with `#`, so you can leave comments
- ignores any other columns

Every row is downloaded with the same `--type` and quality options from the command line.

```csv
url
https://www.youtube.com/watch?v=VIDEO_ID_1
https://youtu.be/VIDEO_ID_2

# Saving this one for later
# https://www.youtube.com/watch?v=VIDEO_ID_3
https://www.youtube.com/watch?v=VIDEO_ID_4
```

---

## Behaviour details

**File names.** By default, files are named after the video title, e.g. `My Favourite Song.mp3`. Characters that aren't allowed in file names are cleaned up.

Change this with `--name-template`, using [yt-dlp's output template fields](https://github.com/yt-dlp/yt-dlp#output-template). Useful ones:

| Field | Example |
|---|---|
| `%(title)s` | `Me at the zoo` |
| `%(uploader)s` | `jawed` (the channel name) |
| `%(upload_date>%Y)s` | `2005` (any [strftime](https://strftime.org/) format works after `>`) |
| `%(id)s` | `jNQXAC9IVRw` (the video ID, which is always unique) |

Use `/` to sort files into subfolders of the save folder, e.g. `%(uploader)s/%(title)s`. The template must include at least one field; otherwise every video would get the same name, and every download after the first would be skipped as already existing. Templates are checked before anything downloads.

**Tags and cover art.** Audio files (MP3, M4A, Opus) are tagged with the video title, the artist (the channel name when YouTube doesn't list one), the upload date and the video's URL. The video thumbnail is embedded as cover art.

**Existing files.** If a file with the same name already exists in the save folder, that video is skipped and reported as already downloaded. Nothing is ever overwritten.

**Resolution fallback.** `--video-quality` is a maximum. If you ask for `1080` and the video only goes up to `720`, you get the 720p version and a notice saying so.

**Playlists.** If a URL points to a video inside a playlist (`watch?v=...&list=...`), only that video is downloaded, not the whole playlist. Links to a playlist or channel page itself are rejected. For bulk downloads, list the video URLs in a CSV.

**Live streams.** Streams that are currently live are rejected, since they have no end. Once a stream has finished and YouTube has processed it, it downloads like any other video.

**Options that don't apply.** Passing `--audio-quality` with anything other than `--type=mp3`, or `--video-quality` with anything other than `--type=mp4`, prints a warning and has no effect. The download still runs.

**Cancelling.** Press Ctrl+C at any time. The half-finished files for the video in progress (`.part` files, separate video/audio streams, the thumbnail) are deleted, so a rerun starts clean. Finished downloads, and any files that were already there, are left alone.

**Bulk downloads.** Videos are downloaded one at a time, in the order they appear in the file. If one fails (private, removed, network error), the error is logged and the tool moves on to the next. A summary is printed at the end:

```
Done: 8 downloaded, 1 skipped (already exists), 2 failed
  ✗ https://www.youtube.com/watch?v=VIDEO_ID_5 — Video unavailable
  ✗ https://youtu.be/VIDEO_ID_9 — Private video
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Every video was downloaded or already existed |
| `1` | At least one video failed to download, or ffmpeg isn't installed |
| `2` | Invalid usage, e.g. missing `--type`, both `--url` and `--csv-list`, or an unreadable CSV |
| `130` | Cancelled with Ctrl+C |

---

## A note on audio quality

YouTube's own audio streams are about 128–160 kbps. Converting to a higher MP3 bitrate doesn't recover detail that isn't in the source; it only makes the file bigger. That's why the default is **192 kbps**, which sounds the same as 320 in practice at about 60% of the size. `320` is still available if you want it.

If you don't specifically need MP3, use `--type=m4a` or `--type=opus`. They copy YouTube's audio stream into the file without re-encoding it, so you get exactly what YouTube serves, in a smaller file, with no generation loss. Both play in modern players and browsers. M4A is the safer choice for Apple devices and car stereos.

---

## Troubleshooting

**`ffmpeg not found`**: Install ffmpeg (`brew install ffmpeg` on macOS) and make sure it's on your `PATH`.

**`No JavaScript runtime found`**: Without one, YouTube only offers some formats, so downloads may fail or come out at lower quality. Install Deno (`brew install deno`), or make sure Node 22 or newer is on your `PATH`.

**A download fails and the message doesn't explain why**: Run the same command again with `--verbose` to see everything yt-dlp is doing. Include that output if you report a problem.

**Downloads suddenly start failing for every video**: YouTube changes things regularly, and an outdated yt-dlp is the most common cause. Upgrade it:

```bash
uv tool upgrade ytdl-cli
```

**`Sign in to confirm you're not a bot`**: YouTube is rate-limiting your IP. Wait a while before trying again, especially after large batches.

---

## Development

```bash
mise install           # optional: installs the uv version pinned in mise.toml
uv sync                # create the virtualenv and install dependencies
uv run ytdl --help     # run the CLI from source
uv run pytest          # run the tests (these don't hit the network)
uv run ruff check      # lint
uv run ruff format     # auto-format
uv run mypy            # type-check
```

Project layout:

```
ytdl-cli/
├── .github/workflows/  # CI: lint, type-check and tests on every push
├── mise.toml           # pins uv for mise users
├── pyproject.toml
├── uv.lock
├── README.md
├── src/ytdl/
│   ├── __init__.py
│   ├── __main__.py     # lets you run `python -m ytdl`
│   ├── cli.py          # argument parsing, validation and output (Typer)
│   ├── csv_loader.py   # reading and filtering the CSV list
│   └── downloader.py   # yt-dlp options, downloading, progress, results
└── tests/
    ├── test_cli.py
    ├── test_csv_loader.py
    └── test_downloader.py
```

### Built with

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for extracting and downloading from YouTube
- [Typer](https://typer.tiangolo.com/) for the CLI
- [Rich](https://github.com/Textualize/rich) for progress bars and terminal output

---

## Disclaimer

This tool is for personal use. Downloading content from YouTube may violate [YouTube's Terms of Service](https://www.youtube.com/t/terms) and copyright law depending on the content and what you do with it. Only download videos you own, have permission to download, or that are licensed for reuse (e.g. Creative Commons). You are responsible for how you use it.
