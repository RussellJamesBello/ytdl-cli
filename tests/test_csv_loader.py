import pytest

from ytdl.csv_loader import CsvError, load_urls


def write(tmp_path, content, encoding="utf-8"):
    path = tmp_path / "list.csv"
    path.write_text(content, encoding=encoding)
    return path


def test_reads_first_column_skipping_header_blanks_and_comments(tmp_path):
    path = write(
        tmp_path,
        "URL,notes\n"
        "# a comment\n"
        "https://youtu.be/one,first\n"
        "\n"
        "   \n"
        "  https://youtu.be/two  \n"
        "# https://youtu.be/commented-out\n",
    )
    assert load_urls(path) == ["https://youtu.be/one", "https://youtu.be/two"]


def test_only_a_leading_url_row_is_treated_as_a_header(tmp_path):
    path = write(tmp_path, "https://youtu.be/one\nurl\n")
    assert load_urls(path) == ["https://youtu.be/one", "url"]


def test_file_without_header(tmp_path):
    path = write(tmp_path, "https://youtu.be/one\nhttps://youtu.be/two\n")
    assert load_urls(path) == ["https://youtu.be/one", "https://youtu.be/two"]


def test_excel_byte_order_mark_is_ignored(tmp_path):
    path = write(tmp_path, "url\nhttps://youtu.be/one\n", encoding="utf-8-sig")
    assert load_urls(path) == ["https://youtu.be/one"]


def test_quoted_cells(tmp_path):
    path = write(tmp_path, '"https://www.youtube.com/watch?v=one&t=5","has, a comma"\n')
    assert load_urls(path) == ["https://www.youtube.com/watch?v=one&t=5"]


def test_no_urls_is_an_error(tmp_path):
    path = write(tmp_path, "url\n# nothing here\n\n")
    with pytest.raises(CsvError, match="No URLs found"):
        load_urls(path)


def test_unreadable_file_is_an_error(tmp_path):
    path = tmp_path / "list.csv"
    path.write_bytes(b"\xff\xfe\x00not utf-8")
    with pytest.raises(CsvError, match="Couldn't read"):
        load_urls(path)
