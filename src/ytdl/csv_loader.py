"""Reading URL lists for --csv-list, and writing the list of failed downloads."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

FAILED_LIST_NAME = "ytdl-failed.csv"
# First line of every failed list, so ytdl only ever deletes lists it wrote itself.
_FAILED_LIST_MARKER = "# ytdl:"


class CsvError(Exception):
    """The CSV file couldn't be read or contained no URLs."""


def load_urls(path: Path) -> list[str]:
    """Return the URLs in the first column of a CSV file, in order.

    Blank rows, rows starting with ``#``, and a leading ``url`` header row are
    skipped. Any columns after the first are ignored.
    """
    try:
        # utf-8-sig drops the byte-order mark that Excel puts at the start of CSVs.
        with path.open(newline="", encoding="utf-8-sig") as file:
            rows = list(csv.reader(file))
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise CsvError(f"Couldn't read {path}: {error}") from error

    urls: list[str] = []
    for row in rows:
        cell = row[0].strip() if row else ""
        if not cell or cell.startswith("#"):
            continue
        if not urls and cell.lower() == "url":
            continue
        urls.append(cell)

    if not urls:
        raise CsvError(f"No URLs found in {path}.")
    return urls


def save_failed_list(path: Path, failures: Iterable[tuple[str, str]], retry_command: str) -> None:
    """Write failed URLs and their errors as a CSV that --csv-list can read back."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with path.open("w", newline="", encoding="utf-8") as file:
        file.write(f"{_FAILED_LIST_MARKER} these videos failed to download on {timestamp}.\n")
        file.write(f"# Retry them with: {retry_command}\n")
        writer = csv.writer(file)
        writer.writerow(["url", "error"])
        writer.writerows(failures)


def remove_failed_list(path: Path) -> bool:
    """Delete a failed list left by an earlier run. Returns whether one was removed."""
    try:
        with path.open(encoding="utf-8") as file:
            if not file.readline().startswith(_FAILED_LIST_MARKER):
                return False
        path.unlink()
    except (OSError, UnicodeDecodeError):
        return False
    return True
