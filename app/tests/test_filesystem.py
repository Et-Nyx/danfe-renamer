"""Filesystem safety (plan sections 2.2, 12, 13 and 20)."""

from __future__ import annotations

import shutil
from datetime import datetime

import pytest

from app.core import filesystem as app_filesystem
from app.core.filesystem import (
    OutputCollision,
    OutputWriteError,
    copy_into_batch,
    create_batch_directory,
    ensure_inside,
    path_key,
)


def test_batch_directory_is_fresh_for_every_run(tmp_path):
    stamp = datetime(2026, 9, 25, 13, 51, 2)
    first = create_batch_directory(tmp_path, stamp)
    second = create_batch_directory(tmp_path, stamp)
    assert first.name == "2026-09-25_13-51-02"
    assert second.name == "2026-09-25_13-51-02_2"
    assert first != second
    assert first.is_dir() and second.is_dir()


def test_originals_are_never_touched_and_copies_are_verified(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF-1.4 content")
    batch = create_batch_directory(tmp_path / "out", datetime(2026, 9, 25, 8, 0, 0))

    destination = copy_into_batch(
        source, batch / "renamed.pdf", batch_directory=batch
    )
    assert destination.read_bytes() == source.read_bytes()
    assert source.exists()
    assert source.read_bytes() == b"%PDF-1.4 content"


def test_existing_output_file_is_never_overwritten(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF-1.4 content")
    batch = create_batch_directory(tmp_path / "out", datetime(2026, 9, 25, 8, 0, 0))
    destination = batch / "renamed.pdf"
    destination.write_bytes(b"existing file that must survive")

    with pytest.raises(OutputCollision):
        copy_into_batch(source, destination, batch_directory=batch)
    assert destination.read_bytes() == b"existing file that must survive"


def test_copy_outside_the_batch_directory_is_refused(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF-1.4 content")
    batch = create_batch_directory(tmp_path / "out", datetime(2026, 9, 25, 8, 0, 0))

    with pytest.raises(OutputWriteError):
        copy_into_batch(
            source, tmp_path / "escaped.pdf", batch_directory=batch
        )
    assert not (tmp_path / "escaped.pdf").exists()


def test_ensure_inside_rejects_sibling_directories(tmp_path):
    batch = tmp_path / "batch"
    batch.mkdir()
    ensure_inside(batch / "ok.pdf", batch)
    with pytest.raises(OutputWriteError):
        ensure_inside(tmp_path / "other" / "no.pdf", batch)


def test_path_key_is_case_insensitive_for_deduplication(tmp_path):
    assert path_key(tmp_path / "A.pdf") == path_key(tmp_path / "a.pdf")


# ------------------------------------------------- when a copy does not finish
#
# Two things can go wrong after the bytes are on disk: something else holds the
# fresh file, or the write is short. Either way the folder must end up holding
# only files the report accounts for, because a finished-looking PDF with no line
# saying otherwise is exactly the quiet mistake this application exists to avoid.


def a_batch_with_one_file(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF-1.4 content" * 50)
    batch = create_batch_directory(tmp_path / "out", datetime(2026, 9, 25, 8, 0, 0))
    return source, batch, batch / "renamed.pdf"


def held_by_something_else(monkeypatch, times: int = 99):
    """Make the metadata step fail the way a scanner holding a fresh file does.

    ``shutil.copy2`` writes the bytes and copies the metadata after them, so a
    failure here is a file that is already on disk - the shape of this bug.
    """
    real = shutil.copystat
    calls = []

    def copystat(src, dst, **kwargs):
        calls.append(dst)
        if len(calls) <= times:
            raise OSError(
                32,
                "The process cannot access the file because it is being used "
                "by another process",
            )
        return real(src, dst, **kwargs)

    monkeypatch.setattr(app_filesystem.shutil, "copystat", copystat)
    monkeypatch.setattr(app_filesystem, "COPY_RETRY_PAUSE_SECONDS", 0)
    return calls


def test_a_failed_copy_leaves_nothing_behind(tmp_path, monkeypatch):
    """Reproduced before this: a 2400-byte PDF in a folder the report called clean."""
    source, batch, destination = a_batch_with_one_file(tmp_path)
    held_by_something_else(monkeypatch)

    with pytest.raises(OutputWriteError) as raised:
        copy_into_batch(source, destination, batch_directory=batch)

    assert "being used by another process" in str(raised.value)
    assert not destination.exists(), "the unfinished copy stayed in the folder"
    assert list(batch.iterdir()) == [], "the folder holds only reported files"
    assert source.exists(), "and the original is untouched"


def test_a_copy_something_is_holding_is_tried_again(tmp_path, monkeypatch):
    """A scanner lets go on its own, so the attempt is worth repeating."""
    source, batch, destination = a_batch_with_one_file(tmp_path)
    calls = held_by_something_else(monkeypatch, times=2)

    copied = copy_into_batch(source, destination, batch_directory=batch)

    assert len(calls) == 3, "it kept trying until the file was free"
    assert copied.read_bytes() == source.read_bytes()


def test_a_copy_that_never_works_is_reported_after_the_last_attempt(tmp_path, monkeypatch):
    """Never endlessly: the bound is the promise that a batch still finishes."""
    source, batch, destination = a_batch_with_one_file(tmp_path)
    calls = held_by_something_else(monkeypatch)

    with pytest.raises(OutputWriteError):
        copy_into_batch(source, destination, batch_directory=batch)

    assert len(calls) == app_filesystem.COPY_ATTEMPTS


def test_a_truncated_copy_is_refused_and_taken_away(tmp_path, monkeypatch):
    """A short file is worse than no file, and must not outlive the failure."""
    source, batch, destination = a_batch_with_one_file(tmp_path)

    def short(src, dst, **kwargs):
        dst = str(dst)
        with open(dst, "wb") as handle:
            handle.write(source.read_bytes()[:10])
        return dst

    monkeypatch.setattr(app_filesystem.shutil, "copy2", short)
    monkeypatch.setattr(app_filesystem, "COPY_RETRY_PAUSE_SECONDS", 0)

    with pytest.raises(OutputWriteError) as raised:
        copy_into_batch(source, destination, batch_directory=batch)

    assert "not the whole file" in str(raised.value)
    assert str(destination) in str(raised.value), "the failure names the file"
    assert list(batch.iterdir()) == []


def test_a_leftover_that_will_not_go_is_named_in_the_failure(tmp_path, monkeypatch):
    """If it cannot be removed, saying nothing would be the original bug again."""
    source, batch, destination = a_batch_with_one_file(tmp_path)
    held_by_something_else(monkeypatch)
    monkeypatch.setattr(
        app_filesystem,
        "discard_partial",
        lambda path: f"{path} is still there and could not be removed",
    )

    with pytest.raises(OutputWriteError) as raised:
        copy_into_batch(source, destination, batch_directory=batch)

    assert "still there and could not be removed" in str(raised.value)


def test_an_existing_output_is_still_never_overwritten(tmp_path):
    """The retry must not have loosened the one thing this module promises."""
    source, batch, destination = a_batch_with_one_file(tmp_path)
    destination.write_bytes(b"a document that was already there")

    with pytest.raises(OutputCollision):
        copy_into_batch(source, destination, batch_directory=batch)

    assert destination.read_bytes() == b"a document that was already there"
