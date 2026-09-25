"""Filesystem safety (plan sections 2.2, 12, 13 and 20)."""

from __future__ import annotations

from datetime import datetime

import pytest

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
