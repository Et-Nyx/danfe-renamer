"""Filesystem safety layer: batch directory and copy operations.

The core invariant of the application lives here: originals are only ever read,
and an existing output file is never overwritten.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

#: Timestamp format of a batch directory, e.g. ``2026-09-25_13-51-02``.
BATCH_DIR_FORMAT = "%Y-%m-%d_%H-%M-%S"


class OutputCollision(Exception):
    """The destination file already exists; nothing was written."""


class OutputWriteError(Exception):
    """The copy could not be completed or did not verify."""


def create_batch_directory(output_root: Path, timestamp: datetime) -> Path:
    """Create a fresh directory for one run, never reusing an existing one."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    base_name = timestamp.strftime(BATCH_DIR_FORMAT)
    candidate = root / base_name
    suffix = 2
    while candidate.exists():
        candidate = root / f"{base_name}_{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def copy_into_batch(
    source: Path, destination: Path, *, batch_directory: Path | None = None
) -> Path:
    """Copy ``source`` to ``destination`` without ever overwriting anything.

    The copy is verified against the source size before it is accepted, so a
    truncated write is reported instead of producing a damaged document.
    """
    source = Path(source)
    destination = Path(destination)
    if batch_directory is not None:
        ensure_inside(destination, batch_directory)
    if destination.exists():
        raise OutputCollision(f"{destination.name} already exists")
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        raise OutputWriteError(f"could not copy to {destination}: {exc}") from exc

    try:
        if destination.stat().st_size != source.stat().st_size:
            raise OutputWriteError("copied file size differs from the source")
    except OSError as exc:
        raise OutputWriteError(f"could not verify the copy: {exc}") from exc
    return destination


def ensure_inside(path: Path, directory: Path) -> None:
    """Raise when ``path`` would escape ``directory``."""
    resolved_directory = os.path.abspath(directory)
    resolved_path = os.path.abspath(path)
    if os.path.commonpath([resolved_directory, resolved_path]) != resolved_directory:
        raise OutputWriteError(f"{path} is outside the batch directory {directory}")


def path_key(path: Path) -> str:
    """Comparable identity of a path, for deduplicating input files."""
    return os.path.normcase(os.path.abspath(path))
