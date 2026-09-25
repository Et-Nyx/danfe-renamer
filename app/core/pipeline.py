"""The processing pipeline: one file, and one batch.

Order of operations per file (never reordered):

detect layout -> extract fields -> validate -> build filename -> check
collision -> copy -> record outcome

The originals are opened read-only; the only write is the copy in the batch
directory.
"""

from __future__ import annotations

import gc
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from ..pdf.text import PdfReadError, load_document
from ..reporting.report import write_reports
from .detector import UnsupportedDocument, detect
from .filesystem import (
    OutputCollision,
    OutputWriteError,
    copy_into_batch,
    create_batch_directory,
    path_key,
)
from .filename import build_filename
from .models import (
    BatchSummary,
    FailureCode,
    FileOutcome,
    Status,
    ValidatedRecord,
)
from .validator import validate

#: Called as ``progress(index, total, source_path)`` while a batch runs.
ProgressCallback = Callable[[int, int, Path], None]


@dataclass(frozen=True)
class FileAnalysis:
    """Extraction and validation result for one file, before any writing."""

    outcome: FileOutcome
    target_filename: str | None = None
    record: ValidatedRecord | None = None


def analyze_file(source: Path) -> FileAnalysis:
    """Read and validate one PDF; never touches the filesystem beyond reading."""
    source = Path(source)
    started = time.perf_counter()
    outcome = FileOutcome(source_path=source, status=Status.SKIPPED)

    try:
        document = load_document(source)
    except PdfReadError as exc:
        return _failed(outcome, _code(exc.code), str(exc), started)

    try:
        detection = detect(document)
        result = detection.parser.extract(document)
    except UnsupportedDocument as exc:
        return _failed(outcome, exc.code, exc.reason, started)
    except Exception as exc:  # pragma: no cover - unexpected parser failure
        return _failed(
            outcome,
            FailureCode.UNEXPECTED_EXTRACTION_ERROR,
            f"{type(exc).__name__}: {exc}",
            started,
            status=Status.ERROR,
        )

    outcome.parser_id = detection.parser.parser_id
    outcome.access_key = _join_key(result.fields.access_key_digits)
    outcome.emission_date = result.fields.emission_date_text
    outcome.total_value = result.fields.total_value
    outcome.issuer = result.fields.issuer
    outcome.warnings = list(result.warnings)

    validation = validate(result)
    if not validation.passed:
        outcome.failure_code = validation.failure_code
        outcome.reason = validation.reason
        outcome.duration_seconds = time.perf_counter() - started
        return FileAnalysis(outcome=outcome)

    record = validation.record
    assert record is not None  # validation guarantees a record when it passes
    outcome.status = Status.SUCCESS
    outcome.nf_number = record.nf_number
    outcome.target_filename = build_filename(record)
    outcome.duration_seconds = time.perf_counter() - started
    return FileAnalysis(
        outcome=outcome, target_filename=outcome.target_filename, record=record
    )


def run_batch(
    sources: Iterable[Path],
    output_root: Path | None,
    *,
    copy_files: bool = True,
    progress: ProgressCallback | None = None,
    timestamp: datetime | None = None,
) -> BatchSummary:
    """Process a batch of PDFs and copy the successful ones with new names.

    With ``copy_files=False`` the run only analyses and reports: no directory is
    created and nothing is written.

    Cyclic garbage collection is paused for the duration of the batch; see
    :func:`_pause_garbage_collection` for why that matters when a window runs the
    batch on a worker thread.
    """
    with _pause_garbage_collection():
        return _run_batch(
            sources,
            output_root,
            copy_files=copy_files,
            progress=progress,
            timestamp=timestamp,
        )


class _pause_garbage_collection:
    """Stop the cyclic collector while a batch is being read.

    Reading a PDF happens in whatever thread called us - in the window that is a
    worker thread. The window's own thread keeps allocating (Tk), and either
    thread collecting while the other is inside MuPDF takes the process down: it
    is a hard crash, not an exception, because MuPDF is not thread-safe and the
    collector walks objects from both threads. With the collector paused for the
    length of the batch, neither thread collects; the library objects are closed
    where they were made, and the memory a paused collector leaves behind is
    bounded by one batch.
    """

    def __enter__(self) -> None:
        self._was_enabled = gc.isenabled()
        if self._was_enabled:
            gc.disable()

    def __exit__(self, *exc_info) -> None:
        if self._was_enabled:
            gc.enable()


def _run_batch(
    sources: Iterable[Path],
    output_root: Path | None,
    *,
    copy_files: bool = True,
    progress: ProgressCallback | None = None,
    timestamp: datetime | None = None,
) -> BatchSummary:
    started_at = timestamp or datetime.now()
    unique_sources = _deduplicate(sources)
    summary = BatchSummary(
        started_at=started_at,
        finished_at=started_at,
        outcomes=[],
    )

    batch_directory: Path | None = None
    written: dict[str, Path] = {}
    #: Access key -> the file that first carried that note in this batch.
    notes: dict[str, FileOutcome] = {}
    total = len(unique_sources)

    if copy_files:
        batch_directory = create_batch_directory(
            Path(output_root) if output_root else Path.cwd(), started_at
        )
        summary.output_directory = batch_directory

    for index, source in enumerate(unique_sources, start=1):
        if progress is not None:
            progress(index, total, source)
        analysis = analyze_file(source)
        outcome = analysis.outcome

        outcome = _skip_duplicate_note(outcome, notes)
        if (
            copy_files
            and outcome.succeeded
            and batch_directory is not None
            and analysis.target_filename
        ):
            outcome = _write_copy(
                outcome, analysis.target_filename, batch_directory, written
            )
        summary.outcomes.append(outcome)

    summary.finished_at = datetime.now()
    if batch_directory is not None:
        summary.report_paths = write_reports(summary)
    return summary


def _skip_duplicate_note(
    outcome: FileOutcome, notes: dict[str, FileOutcome]
) -> FileOutcome:
    """Recognise a note that is already in this batch, whatever its file is called.

    The same note is often present twice: the copy somebody already renamed and
    the raw download. Both would produce the same file name, and reporting that
    as a collision would suggest a data problem where there is none. The access
    key tells the two apart from two genuinely different notes.
    """
    if not outcome.succeeded or not outcome.access_key:
        return outcome
    key = outcome.access_key.replace(" ", "")
    first = notes.get(key)
    if first is None:
        notes[key] = outcome
        return outcome
    outcome.status = Status.SKIPPED
    outcome.failure_code = FailureCode.DUPLICATE_NOTE
    outcome.reason = (
        "Same note as "
        f"{first.source_path.name} (already renamed in this batch)"
    )
    outcome.destination_path = None
    return outcome


def _write_copy(
    outcome: FileOutcome,
    target_filename: str,
    batch_directory: Path,
    written: dict[str, Path],
) -> FileOutcome:
    """Copy one analysed file into the batch directory, or explain why not."""
    destination = batch_directory / target_filename
    key = path_key(destination)
    if key in written:
        outcome.status = Status.SKIPPED
        outcome.failure_code = FailureCode.OUTPUT_COLLISION
        outcome.reason = (
            "Output filename already exists (same name produced by "
            f"{written[key].name})"
        )
        outcome.destination_path = None
        return outcome
    try:
        copy_into_batch(
            outcome.source_path, destination, batch_directory=batch_directory
        )
    except OutputCollision as exc:
        outcome.status = Status.SKIPPED
        outcome.failure_code = FailureCode.OUTPUT_COLLISION
        outcome.reason = str(exc)
        return outcome
    except OutputWriteError as exc:
        outcome.status = Status.ERROR
        outcome.failure_code = FailureCode.OUTPUT_WRITE_ERROR
        outcome.reason = str(exc)
        return outcome

    written[key] = outcome.source_path
    outcome.destination_path = destination
    return outcome


def _deduplicate(sources: Iterable[Path]) -> list[Path]:
    """Drop repeated input paths, keeping the first occurrence order."""
    seen: set[str] = set()
    unique: list[Path] = []
    for source in sources:
        key = path_key(source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(Path(source))
    return unique


def _failed(
    outcome: FileOutcome,
    code: FailureCode,
    reason: str | None,
    started: float,
    *,
    status: Status = Status.SKIPPED,
) -> FileAnalysis:
    outcome.status = status
    outcome.failure_code = code
    outcome.reason = reason
    outcome.duration_seconds = time.perf_counter() - started
    return FileAnalysis(outcome=outcome)


def _code(raw: str) -> FailureCode:
    try:
        return FailureCode(raw)
    except ValueError:  # pragma: no cover - defensive
        return FailureCode.PDF_READ_ERROR


def _join_key(digits: str | None) -> str | None:
    """Access keys are reported in the same groups of four as printed."""
    if not digits:
        return None
    return " ".join(digits[index : index + 4] for index in range(0, len(digits), 4))
