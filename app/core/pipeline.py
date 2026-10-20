"""The processing pipeline: one file, and one batch.

Order of operations per file (never reordered):

detect layout -> extract fields -> validate -> build filename -> check
collision -> copy -> record outcome

For an XML source the converter runs first (XML -> PDF in a staging folder),
but validation, naming, collision checks and the copy itself stay in this
module: the converter only produces the PDF that the renamer then names.

The originals are opened read-only; the only writes are the copies (or the
generated PDFs) in the batch directory.
"""

from __future__ import annotations

import gc
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from ..pdf.text import PdfReadError, load_document, normalize_text
from ..reporting.report import write_reports
from ..xml.invoice import XmlInvoiceError, inspect_xml
from ..xml.render import XmlRenderError, render_xml_to_pdf
from .detector import UnsupportedDocument, detect
from .wording import DEFAULT_LANGUAGE
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
    NameSource,
    SourceKind,
    Status,
    ValidatedRecord,
)
from .normalize import format_br_date, money_to_decimal
from .validator import validate

#: Called as ``progress(index, total, source_path)`` while a batch runs.
ProgressCallback = Callable[[int, int, Path], None]


@dataclass(frozen=True)
class FileAnalysis:
    """Extraction and validation result for one file, before any writing."""

    outcome: FileOutcome
    target_filename: str | None = None
    record: ValidatedRecord | None = None
    source_kind: SourceKind = SourceKind.PDF
    #: PDF to copy into the batch (the original PDF or a rendered one).
    output_source: Path | None = None
    #: XML to render, when this analysis came from an XML source.
    render_xml: Path | None = None
    model: str | None = None


def analyze_file(
    source: Path, *, name_source: NameSource = NameSource.EMITENTE
) -> FileAnalysis:
    """Read and validate one PDF; never touches the filesystem beyond reading."""
    source = Path(source)
    started = time.perf_counter()
    outcome = FileOutcome(
        source_path=source,
        status=Status.SKIPPED,
        source_type=SourceKind.PDF.value,
    )

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
    outcome.recipient = result.fields.recipient
    outcome.name_source = name_source.value
    outcome.warnings = list(result.warnings)

    validation = validate(result, name_source=name_source)
    if not validation.passed:
        outcome.failure_code = validation.failure_code
        outcome.reason = validation.reason
        outcome.duration_seconds = time.perf_counter() - started
        return FileAnalysis(outcome=outcome, output_source=source)

    record = validation.record
    assert record is not None  # validation guarantees a record when it passes
    outcome.status = Status.SUCCESS
    outcome.document_model = record.access_key.model
    outcome.nf_number = record.nf_number
    outcome.target_filename = build_filename(record)
    outcome.duration_seconds = time.perf_counter() - started
    return FileAnalysis(
        outcome=outcome,
        target_filename=outcome.target_filename,
        record=record,
        output_source=source,
        model=record.access_key.model,
    )


def analyze_xml(
    source: Path, *, name_source: NameSource = NameSource.EMITENTE
) -> FileAnalysis:
    """Read and validate one NF-e/NFC-e XML; no PDF is written here."""
    source = Path(source)
    started = time.perf_counter()
    outcome = FileOutcome(
        source_path=source,
        status=Status.SKIPPED,
        source_type=SourceKind.XML.value,
    )
    model: str | None = None

    try:
        invoice = inspect_xml(source)
    except XmlInvoiceError as exc:
        return _failed(
            outcome,
            exc.code,
            exc.reason,
            started,
            source_kind=SourceKind.XML,
            render_xml=source,
            model=model,
        )

    model = invoice.model
    outcome.parser_id = invoice.parser_id
    outcome.document_model = invoice.model
    outcome.access_key = _join_key(invoice.access_key.digits)
    outcome.emission_date = invoice.emission_date_text
    outcome.total_value = invoice.total_value
    outcome.issuer = invoice.issuer
    outcome.recipient = invoice.recipient
    outcome.name_source = name_source.value
    outcome.warnings = list(invoice.warnings)

    validation = validate(invoice.to_result(), name_source=name_source)
    if not validation.passed:
        outcome.failure_code = validation.failure_code
        outcome.reason = validation.reason
        outcome.duration_seconds = time.perf_counter() - started
        return FileAnalysis(
            outcome=outcome,
            source_kind=SourceKind.XML,
            render_xml=source,
            model=model,
        )

    record = validation.record
    assert record is not None
    outcome.status = Status.SUCCESS
    outcome.generated = True
    outcome.nf_number = record.nf_number
    outcome.target_filename = build_filename(record)
    outcome.duration_seconds = time.perf_counter() - started
    return FileAnalysis(
        outcome=outcome,
        target_filename=outcome.target_filename,
        record=record,
        source_kind=SourceKind.XML,
        render_xml=source,
        model=model,
    )


def analyze_source(
    source: Path, *, name_source: NameSource = NameSource.EMITENTE
) -> FileAnalysis:
    """Analyse a PDF or an XML by its suffix."""
    path = Path(source)
    if path.suffix.lower() == ".xml":
        return analyze_xml(path, name_source=name_source)
    return analyze_file(path, name_source=name_source)


def run_batch(
    sources: Iterable[Path],
    output_root: Path | None,
    *,
    copy_files: bool = True,
    progress: ProgressCallback | None = None,
    timestamp: datetime | None = None,
    name_source: NameSource = NameSource.EMITENTE,
    language: str = DEFAULT_LANGUAGE,
) -> BatchSummary:
    """Process a batch of PDFs and XMLs and write the successful outputs.

    With ``copy_files=False`` the run only analyses and reports: no directory is
    created and nothing is written. ``name_source`` decides which printed name
    the file names carry, and ``language`` is the one the reports are written in;
    the stable values in them are the same in every language.

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
            name_source=name_source,
            language=language,
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
    name_source: NameSource = NameSource.EMITENTE,
    language: str = DEFAULT_LANGUAGE,
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

    pdf_sources = [source for source in unique_sources if source.suffix.lower() == ".pdf"]
    xml_sources = [source for source in unique_sources if source.suffix.lower() == ".xml"]
    other_sources = [
        source
        for source in unique_sources
        if source.suffix.lower() not in {".pdf", ".xml"}
    ]

    if copy_files:
        batch_directory = create_batch_directory(
            Path(output_root) if output_root else Path.cwd(), started_at
        )
        summary.output_directory = batch_directory

    # XML fields are needed before the PDFs run so a successful PDF can use the
    # more reliable XML values for its name, and so a PDF that fails leaves its
    # XML available as the fallback.
    xml_analyses: dict[Path, FileAnalysis] = {}
    xml_by_key: dict[str, list[FileAnalysis]] = {}
    for source in xml_sources:
        analysis = analyze_xml(source, name_source=name_source)
        xml_analyses[source] = analysis
        if analysis.outcome.succeeded and analysis.record is not None:
            key = analysis.record.access_key.digits
            xml_by_key.setdefault(key, []).append(analysis)

    staging = (
        tempfile.TemporaryDirectory(prefix="danfe-renamer-")
        if copy_files and xml_sources
        else None
    )
    processed = 0

    def report(source: Path) -> None:
        nonlocal processed
        processed += 1
        if progress is not None:
            progress(processed, total, source)

    try:
        for source in pdf_sources:
            report(source)
            analysis = analyze_file(source, name_source=name_source)
            outcome = _skip_duplicate_note(analysis.outcome, notes)
            if outcome.succeeded:
                xml_analysis = _matching_xml(analysis, xml_by_key)
                if xml_analysis is not None:
                    analysis = _with_xml_data(analysis, xml_analysis)
                    outcome = analysis.outcome
                if copy_files and batch_directory is not None and analysis.target_filename:
                    outcome = _write_copy(
                        outcome,
                        analysis.target_filename,
                        batch_directory,
                        written,
                        copy_source=analysis.output_source or source,
                    )
                if outcome.succeeded:
                    _remember_note(outcome, notes)
            summary.outcomes.append(outcome)

        for source in xml_sources:
            report(source)
            analysis = xml_analyses[source]
            outcome = analysis.outcome
            if not outcome.succeeded:
                summary.outcomes.append(outcome)
                continue
            outcome = _skip_duplicate_note(outcome, notes)
            if not outcome.succeeded:
                summary.outcomes.append(outcome)
                continue
            if not copy_files:
                outcome.generated = False
                summary.outcomes.append(outcome)
                _remember_note(outcome, notes)
                continue
            if batch_directory is None or staging is None or analysis.target_filename is None:
                outcome.status = Status.ERROR
                outcome.failure_code = FailureCode.OUTPUT_WRITE_ERROR
                outcome.reason = "no batch directory available for the generated PDF"
                summary.outcomes.append(outcome)
                continue

            staged_pdf = Path(staging.name) / f"{len(summary.outcomes):05d}.pdf"
            try:
                render_xml_to_pdf(
                    source, staged_pdf, model=analysis.model or "55"
                )
            except XmlRenderError as exc:
                outcome.status = Status.ERROR
                outcome.failure_code = FailureCode.PDF_GENERATION_ERROR
                outcome.generated = False
                outcome.reason = str(exc)
                summary.outcomes.append(outcome)
                continue

            outcome = _write_copy(
                outcome,
                analysis.target_filename,
                batch_directory,
                written,
                copy_source=staged_pdf,
                written_source=source,
            )
            if not outcome.succeeded:
                outcome.generated = False
            summary.outcomes.append(outcome)
            if outcome.succeeded:
                _remember_note(outcome, notes)

        for source in other_sources:
            report(source)
            outcome = FileOutcome(
                source_path=source,
                status=Status.SKIPPED,
                failure_code=FailureCode.UNSUPPORTED_FORMAT,
                reason="Only PDF and XML files are supported",
            )
            summary.outcomes.append(outcome)
    finally:
        if staging is not None:
            staging.cleanup()

    summary.finished_at = datetime.now()
    if batch_directory is not None:
        summary.report_paths = write_reports(summary, language=language)
    return summary


def _matching_xml(
    analysis: FileAnalysis, xml_by_key: dict[str, list[FileAnalysis]]
) -> FileAnalysis | None:
    """The first valid XML for the PDF's note, if the batch carries one."""
    if analysis.record is None:
        return None
    candidates = xml_by_key.get(analysis.record.access_key.digits)
    return candidates[0] if candidates else None


def _with_xml_data(
    pdf_analysis: FileAnalysis, xml_analysis: FileAnalysis
) -> FileAnalysis:
    """Keep the PDF file, but take the name fields from the XML.

    The XML is structured and therefore less likely to be misread than a printed
    PDF. The PDF remains the output; the XML is only the data source. Any
    disagreement is recorded as a warning instead of being silently hidden.
    """
    xml_record = xml_analysis.record
    assert xml_record is not None
    outcome = pdf_analysis.outcome
    differences = _record_differences(pdf_analysis.record, xml_record)

    outcome.parser_id = xml_analysis.outcome.parser_id
    outcome.document_model = xml_analysis.outcome.document_model
    outcome.access_key = xml_analysis.outcome.access_key
    outcome.nf_number = xml_record.nf_number
    outcome.emission_date = xml_analysis.outcome.emission_date
    outcome.total_value = xml_analysis.outcome.total_value
    outcome.issuer = xml_analysis.outcome.issuer
    outcome.recipient = xml_analysis.outcome.recipient
    outcome.name_source = xml_record.name_source.value
    outcome.target_filename = build_filename(xml_record)
    outcome.warnings = list(
        dict.fromkeys(
            [
                *outcome.warnings,
                *xml_analysis.outcome.warnings,
                *differences,
            ]
        )
    )
    return replace(
        pdf_analysis,
        outcome=outcome,
        target_filename=outcome.target_filename,
        record=xml_record,
    )


def _record_differences(
    pdf_record: ValidatedRecord | None, xml_record: ValidatedRecord
) -> list[str]:
    """Explain where the PDF and its XML disagree; the XML value is used."""
    if pdf_record is None:
        return []
    differences: list[str] = []
    if pdf_record.nf_number != xml_record.nf_number:
        differences.append(
            f"NF number (PDF {pdf_record.nf_number}, XML {xml_record.nf_number})"
        )
    if pdf_record.emission_date != xml_record.emission_date:
        differences.append(
            "emission date "
            f"(PDF {format_br_date(pdf_record.emission_date)}, "
            f"XML {format_br_date(xml_record.emission_date)})"
        )
    pdf_total = (
        money_to_decimal(pdf_record.total_value)
        if pdf_record.total_value
        else None
    )
    xml_total = (
        money_to_decimal(xml_record.total_value)
        if xml_record.total_value
        else None
    )
    if pdf_total != xml_total:
        differences.append(
            f"total value (PDF {pdf_record.total_value or '-'}, "
            f"XML {xml_record.total_value or '-'})"
        )
    if xml_record.name_source is NameSource.RECIPIENT:
        pdf_name, xml_name, label = (
            pdf_record.recipient,
            xml_record.recipient,
            "recipient",
        )
    else:
        pdf_name, xml_name, label = (
            pdf_record.issuer,
            xml_record.issuer,
            "issuer",
        )
    if normalize_text(pdf_name or "") != normalize_text(xml_name or ""):
        differences.append(
            f"{label} (PDF {pdf_name or '-'}, XML {xml_name or '-'})"
        )
    if not differences:
        return []
    return [
        "XML and PDF disagree on "
        + "; ".join(differences)
        + "; the XML value is used for the file name"
    ]


def _skip_duplicate_note(
    outcome: FileOutcome, notes: dict[str, FileOutcome]
) -> FileOutcome:
    """Recognise a note that is already in this batch, whatever its file is called.

    The same note is often present twice: the copy somebody already renamed and
    the raw download, or a PDF and its XML. Both would produce the same file
    name, and reporting that as a collision would suggest a data problem where
    there is none. The access key tells the two apart from two genuinely
    different notes.
    """
    if not outcome.succeeded or not outcome.access_key:
        return outcome
    key = outcome.access_key.replace(" ", "")
    first = notes.get(key)
    if first is None:
        return outcome
    outcome.status = Status.SKIPPED
    outcome.failure_code = FailureCode.DUPLICATE_NOTE
    outcome.generated = False
    outcome.reason = (
        "Same note as "
        f"{first.source_path.name} (already used in this batch)"
    )
    outcome.destination_path = None
    return outcome


def _remember_note(outcome: FileOutcome, notes: dict[str, FileOutcome]) -> None:
    """Remember a note only after its output was accepted."""
    if outcome.succeeded and outcome.access_key:
        notes.setdefault(outcome.access_key.replace(" ", ""), outcome)


def _write_copy(
    outcome: FileOutcome,
    target_filename: str,
    batch_directory: Path,
    written: dict[str, Path],
    *,
    copy_source: Path | None = None,
    written_source: Path | None = None,
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
    source = Path(copy_source or outcome.source_path)
    try:
        copy_into_batch(source, destination, batch_directory=batch_directory)
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

    written[key] = Path(written_source or source)
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
    source_kind: SourceKind = SourceKind.PDF,
    render_xml: Path | None = None,
    model: str | None = None,
) -> FileAnalysis:
    outcome.status = status
    outcome.failure_code = code
    outcome.reason = reason
    outcome.duration_seconds = time.perf_counter() - started
    return FileAnalysis(
        outcome=outcome,
        source_kind=source_kind,
        output_source=outcome.source_path if source_kind is SourceKind.PDF else None,
        render_xml=render_xml,
        model=model,
    )


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
