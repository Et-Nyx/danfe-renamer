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

from .wording import Detail, DetailCode

#: Timestamp format of a batch directory, e.g. ``2026-09-25_13-51-02``.
BATCH_DIR_FORMAT = "%Y-%m-%d_%H-%M-%S"

#: Where a batch keeps the PDFs it could not give their agreed name to. It sorts
#: first and is not a copy anybody asked for by name, so it must not be mistaken
#: for one of the renamed files next to it.
UNRENAMED_DIRECTORY_NAME = "_unrenamed"

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

    def __init__(self, detail: Detail) -> None:
        super().__init__(str(detail))
        self.detail = detail


class OutputWriteError(Exception):
    """The copy could not be completed or did not verify.

    ``leftover`` is set when a partial copy could not be removed: the caller
    reports it as a warning, because a batch folder holding a file no line
    explains is the one thing it must not do.
    """

    def __init__(self, detail: Detail, leftover: Detail | None = None) -> None:
        super().__init__(str(detail))
        self.detail = detail
        self.leftover = leftover


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


def unused_path(directory: Path, filename: str) -> Path:
    """The first free name for ``filename`` inside ``directory``.

    Somewhere else this would be a refusal: a name was agreed, and a run that
    invented another one would be lying about what it produced. A copy that has
    no agreed name is the exception - it exists so that a document is not lost -
    and two inputs can carry the same file name, so the second one is numbered
    instead: ``nota.pdf``, ``nota (2).pdf``.
    """
    candidate = Path(directory) / filename
    stem, suffix = candidate.stem, candidate.suffix
    index = 2
    while candidate.exists():
        candidate = Path(directory) / f"{stem} ({index}){suffix}"
        index += 1
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
        raise OutputCollision(
            Detail(DetailCode.COLLISION_EXISTS, {"name": destination.name})
        )

    detail: Detail | None = None
    leftover: Detail | None = None
    for attempt in range(COPY_ATTEMPTS):
        if attempt:
            time.sleep(COPY_RETRY_PAUSE_SECONDS)
        try:
            _copy_verified(source, destination)
        except OutputWriteError as exc:
            # It already names the rule the copy broke; wrapping it in another
            # frame would make the sentence longer, not clearer.
            detail = exc.detail
        except OSError as exc:
            detail = Detail(
                DetailCode.COPY_FAILED,
                {"destination": str(destination), "error": str(exc)},
            )
        else:
            return destination
        # Only the attempt's own remains are ever removed: the destination was
        # proved absent a few lines up, so nothing of the user's is involved.
        leftover = discard_partial(destination)
    assert detail is not None  # the loop above always records one
    raise OutputWriteError(detail, leftover)


def _copy_verified(source: Path, destination: Path) -> None:
    """Copy, then check the size, so a truncated write is never accepted."""
    shutil.copy2(source, destination)
    written = destination.stat().st_size
    expected = source.stat().st_size
    if written != expected:
        raise OutputWriteError(
            Detail(
                DetailCode.COPY_INCOMPLETE,
                {"written": str(written), "expected": str(expected)},
            )
        )


def discard_partial(path: Path) -> Detail | None:
    """Remove an unfinished copy, returning the fact when it will not go.

    Returns ``None`` once the path is gone, or the fact that it is still there:
    whoever reads the batch has to know, because the point of this is that the
    folder holds only files the report accounts for.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        return Detail(DetailCode.LEFTOVER, {"path": str(path), "error": str(exc)})
    return None


def ensure_inside(path: Path, directory: Path) -> None:
    """Raise when ``path`` would escape ``directory``."""
    resolved_directory = os.path.abspath(directory)
    resolved_path = os.path.abspath(path)
    if os.path.commonpath([resolved_directory, resolved_path]) != resolved_directory:
        raise OutputWriteError(
            Detail(
                DetailCode.OUTSIDE_BATCH,
                {"path": str(path), "directory": str(directory)},
            )
        )


def path_key(path: Path) -> str:
    """Comparable identity of a path, for deduplicating input files."""
    return os.path.normcase(os.path.abspath(path))
