from pathlib import Path
import threading

import pytest

import main


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00.00"),
        (0.005, "00:00.01"),
        (59.999, "01:00.00"),
        (3600, "60:00.00"),
    ],
)
def test_format_lrc_time(seconds, expected):
    assert main.format_lrc_time(seconds) == expected


def test_format_lrc_time_rejects_negative_values():
    with pytest.raises(ValueError):
        main.format_lrc_time(-0.01)


def test_format_subtitle_time_rejects_tiny_negative_values():
    with pytest.raises(ValueError):
        main.format_subtitle_time(-0.0004)


def test_generate_lrc_normalizes_whitespace_and_skips_empty_segments():
    result = {
        "segments": [
            {"start": 1.234, "text": "  hello\n  world\t "},
            {"start": 2, "text": " \n\t "},
            {"start": 3, "text": None},
        ]
    }
    assert main.generate_lrc_content(result) == "[00:01.23]hello world\n"
    assert main.generate_lrc_content({"segments": []}) == ""


def test_generate_srt_vtt_txt_tsv_and_json_content():
    result = {
        "text": " hello world",
        "language": "en",
        "segments": [{"start": 1.2345, "end": 2.5, "text": " hello --> world "}],
    }

    assert main.generate_output_content("srt", result) == (
        "1\n00:00:01,235 --> 00:00:02,500\nhello -> world\n"
    )
    assert main.generate_output_content("vtt", result) == (
        "WEBVTT\n\n00:00:01.235 --> 00:00:02.500\nhello -> world\n"
    )
    assert main.generate_output_content("txt", result) == "hello --> world\n"
    assert main.generate_output_content("tsv", result) == (
        "start\tend\ttext\n1235\t2500\thello --> world\n"
    )
    assert '"language": "en"' in main.generate_output_content("json", result)


def test_generate_output_content_rejects_unknown_format():
    with pytest.raises(ValueError, match="unsupported output format"):
        main.generate_output_content("docx", {"segments": []})


def test_atomic_write_replaces_target(tmp_path):
    target = tmp_path / "song.lrc"
    target.write_text("old", encoding="utf-8")
    main.write_text_atomically(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert list(tmp_path.glob(".song.lrc.*.tmp")) == []


def test_atomic_write_failure_preserves_target_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "song.lrc"
    target.write_text("old", encoding="utf-8")

    def fail_replace(source: Path, destination: Path):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(main.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        main.write_text_atomically(target, "new\n")

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".song.lrc.*.tmp")) == []


def test_exclusive_atomic_write_has_one_winner_between_concurrent_writers(tmp_path):
    target = tmp_path / "song.lrc"
    barrier = threading.Barrier(3)
    results = []

    def writer(content):
        barrier.wait()
        results.append((content, main.write_text_exclusively(target, content)))

    threads = [
        threading.Thread(target=writer, args=("first\n",)),
        threading.Thread(target=writer, args=("second\n",)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    winners = [content for content, created in results if created]
    assert len(winners) == 1
    assert target.read_text(encoding="utf-8") == winners[0]
    assert list(tmp_path.glob(".song.lrc.*.tmp")) == []


def test_concurrent_writers_never_replace_an_existing_target(tmp_path):
    target = tmp_path / "song.lrc"
    target.write_text("keep\n", encoding="utf-8")
    results = []

    threads = [
        threading.Thread(
            target=lambda content=content: results.append(
                main.write_text_exclusively(target, content)
            )
        )
        for content in ("first\n", "second\n")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert results == [False, False]
    assert target.read_text(encoding="utf-8") == "keep\n"
    assert list(tmp_path.glob(".song.lrc.*.tmp")) == []
