"""Reading the list of URLs given to --csv-list."""

from __future__ import annotations

import csv
from pathlib import Path


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
