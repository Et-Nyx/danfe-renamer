"""Filesystem safety layer: batch directory and copy operations.

The core invariant of the application lives here: originals are only ever read,
and an existing output file is never overwritten.
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path

#: Timestamp format of a batch directory, e.g. ``2026-09-25_13-51-02``.
BATCH_DIR_FORMAT = "%Y-%m-%d_%H-%M-%S"

#: How many times one copy is attempted before the file is reported as failed.
#:
#: A file that was just written can be held by something else for a moment - a
#: virus scanner reading it, a sync client picking it up - and Windows answers
#: that with ``[WinError 32] The process cannot access the file because it is
#: being used by another process``. It clears on its own, so the copy is tried
#: again; never endlessly, and never quietly, because the attempt decides the
#: outcome and the outcome is what gets reported.
COPY_ATTEMPTS = 3
COPY_RETRY_PAUSE_SECONDS = 0.25


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
    truncated write is reported instead of producing a damaged document, and a
    write something else is holding is tried again - see :data:`COPY_ATTEMPTS`.

    A copy that fails leaves nothing behind. A finished-looking file the report
    never mentions is worse than the failure itself: the folder would then hold a
    document that was never produced correctly, and no line saying so.
    """
    source = Path(source)
    destination = Path(destination)
    if batch_directory is not None:
        ensure_inside(destination, batch_directory)
    if destination.exists():
        raise OutputCollision(f"{destination.name} already exists")

    failure: Exception | None = None
    orphaned = ""
    for attempt in range(COPY_ATTEMPTS):
        if attempt:
            time.sleep(COPY_RETRY_PAUSE_SECONDS)
        try:
            _copy_verified(source, destination)
        except (OSError, OutputWriteError) as exc:
            failure = exc
        else:
            return destination
        # Only the attempt's own remains are ever removed: the destination was
        # proved absent a few lines up, so nothing of the user's is involved.
        orphaned = discard_partial(destination)
    message = f"could not copy to {destination}: {failure}"
    raise OutputWriteError(f"{message}; {orphaned}" if orphaned else message) from failure


def _copy_verified(source: Path, destination: Path) -> None:
    """Copy, then check the size, so a truncated write is never accepted."""
    shutil.copy2(source, destination)
    written = destination.stat().st_size
    expected = source.stat().st_size
    if written != expected:
        raise OutputWriteError(
            f"the copy is not the whole file: {written} bytes of {expected}"
        )


def discard_partial(path: Path) -> str:
    """Remove an unfinished copy, saying so when it will not go.

    Returns an empty string once the path is gone, or a sentence naming what is
    still there: whoever reads the batch has to know, because the point of this
    is that the folder holds only files the report accounts for.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        return f"{path} is still there and could not be removed: {exc}"
    return ""


def ensure_inside(path: Path, directory: Path) -> None:
    """Raise when ``path`` would escape ``directory``."""
    resolved_directory = os.path.abspath(directory)
    resolved_path = os.path.abspath(path)
    if os.path.commonpath([resolved_directory, resolved_path]) != resolved_directory:
        raise OutputWriteError(f"{path} is outside the batch directory {directory}")


def path_key(path: Path) -> str:
    """Comparable identity of a path, for deduplicating input files."""
    return os.path.normcase(os.path.abspath(path))
