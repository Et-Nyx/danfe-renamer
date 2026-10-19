"""Result models shared by extraction, validation, the pipeline and reporting.

The three layers of the application (extraction, validation, output) exchange
these records, so no layer has to know how another one is implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from ..pdf.access_key import AccessKey


class FailureCode(str, Enum):
    """Stable failure codes; the GUI shows the friendly message instead."""

    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    AMBIGUOUS_FORMAT = "AMBIGUOUS_FORMAT"
    MISSING_ACCESS_KEY = "MISSING_ACCESS_KEY"
    ACCESS_KEY_AMBIGUOUS = "ACCESS_KEY_AMBIGUOUS"
    INVALID_ACCESS_KEY = "INVALID_ACCESS_KEY"
    NF_NUMBER_INVALID = "NF_NUMBER_INVALID"
    NF_NUMBER_CONFLICT = "NF_NUMBER_CONFLICT"
    EMISSION_DATE_NOT_FOUND = "EMISSION_DATE_NOT_FOUND"
    EMISSION_DATE_CONFLICT = "EMISSION_DATE_CONFLICT"
    TOTAL_VALUE_NOT_FOUND = "TOTAL_VALUE_NOT_FOUND"
    TOTAL_VALUE_AMBIGUOUS = "TOTAL_VALUE_AMBIGUOUS"
    ISSUER_NOT_FOUND = "ISSUER_NOT_FOUND"
    RECIPIENT_NOT_FOUND = "RECIPIENT_NOT_FOUND"
    INVALID_FILENAME = "INVALID_FILENAME"
    DUPLICATE_NOTE = "DUPLICATE_NOTE"
    OUTPUT_COLLISION = "OUTPUT_COLLISION"
    OUTPUT_WRITE_ERROR = "OUTPUT_WRITE_ERROR"
    PDF_READ_ERROR = "PDF_READ_ERROR"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    PDF_GENERATION_ERROR = "PDF_GENERATION_ERROR"
    XML_READ_ERROR = "XML_READ_ERROR"
    XML_UNSUPPORTED = "XML_UNSUPPORTED"
    XML_NOT_AUTHORIZED = "XML_NOT_AUTHORIZED"
    UNEXPECTED_EXTRACTION_ERROR = "UNEXPECTED_EXTRACTION_ERROR"


#: Friendly, user-facing wording for each failure code.
FAILURE_MESSAGES: dict[FailureCode, str] = {
    FailureCode.UNSUPPORTED_FORMAT: "Could not identify a supported DANFE layout",
    FailureCode.AMBIGUOUS_FORMAT: "More than one DANFE layout matched this document",
    FailureCode.MISSING_ACCESS_KEY: "NF-e access key not found",
    FailureCode.ACCESS_KEY_AMBIGUOUS: "More than one access key found in the document",
    FailureCode.INVALID_ACCESS_KEY: "Access key is not valid",
    FailureCode.NF_NUMBER_INVALID: "NF number could not be derived from the access key",
    FailureCode.NF_NUMBER_CONFLICT: "Printed NF number disagrees with the access key",
    FailureCode.EMISSION_DATE_NOT_FOUND: "Emission date not found",
    FailureCode.EMISSION_DATE_CONFLICT: "Emission date disagrees with the access key",
    FailureCode.TOTAL_VALUE_NOT_FOUND: "VALOR TOTAL DA NOTA not found",
    FailureCode.TOTAL_VALUE_AMBIGUOUS: "Total value is ambiguous or implausible",
    FailureCode.ISSUER_NOT_FOUND: "Issuer name could not be identified confidently",
    FailureCode.RECIPIENT_NOT_FOUND: "Recipient name could not be identified confidently",
    FailureCode.INVALID_FILENAME: "Generated filename is not usable on Windows",
    FailureCode.DUPLICATE_NOTE: "This note is already in the batch under another name",
    FailureCode.OUTPUT_COLLISION: "Output filename already exists",
    FailureCode.OUTPUT_WRITE_ERROR: "Could not write the renamed copy",
    FailureCode.PDF_READ_ERROR: "PDF could not be read",
    FailureCode.PDF_ENCRYPTED: "PDF is password protected",
    FailureCode.PDF_GENERATION_ERROR: "PDF could not be generated from the XML",
    FailureCode.XML_READ_ERROR: "XML could not be read",
    FailureCode.XML_UNSUPPORTED: "XML is not an NF-e or NFC-e document",
    FailureCode.XML_NOT_AUTHORIZED: "XML does not carry an authorized NF-e/NFC-e",
    FailureCode.UNEXPECTED_EXTRACTION_ERROR: "Unexpected error while reading the document",
}


class Status(str, Enum):
    """Batch outcome for a single file."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    ERROR = "error"


class NameSource(str, Enum):
    """Which name from the document goes into the file name.

    ``EMITENTE`` is the company that issued the note (``IDENTIFICAÇÃO DO
    EMITENTE``); ``RECIPIENT`` is the one it was issued to, printed under
    ``RAZÃO SOCIAL`` in the ``DESTINATÁRIO / REMETENTE`` block. Both are read for
    every document; this setting only decides which one is used.
    """

    EMITENTE = "emitente"
    RECIPIENT = "destinatario"


class InputKind(str, Enum):
    """Which input files a batch looks for.

    ``XML`` is the main workflow: the XML is converted to a PDF and then named.
    ``PDF`` keeps the original behaviour for a folder of PDFs that were already
    generated elsewhere. ``BOTH`` reads both kinds; a PDF for the same note is
    preferred over generating one from its XML.
    """

    XML = "xml"
    PDF = "pdf"
    BOTH = "both"


class SourceKind(str, Enum):
    """The kind of file a file outcome was produced from."""

    PDF = "pdf"
    XML = "xml"


class CheckStatus(str, Enum):
    """Outcome of the validation layer."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class ExtractedFields:
    """Raw fields read from a document, before validation.

    Everything is kept as *printed*: ``access_key_digits`` is the 44-digit
    string, ``emission_date_text`` is ``16/09/2026``, ``total_value`` is
    ``2.999,51``. The validator turns these into trusted values.
    """

    access_key_digits: str | None = None
    printed_nf_number: str | None = None
    emission_date: date | None = None
    emission_date_text: str | None = None
    total_value: str | None = None
    products_total: str | None = None
    issuer: str | None = None
    recipient: str | None = None


@dataclass(frozen=True)
class ValidatedRecord:
    """Values that passed every check, ready to build a filename from."""

    access_key: AccessKey
    nf_number: str
    emission_date: date
    total_value: str
    #: The name the file name will show, and where it came from.
    name: str
    name_source: NameSource
    #: Both names as printed, so a report can show what the choice was made from.
    issuer: str | None
    recipient: str | None



@dataclass(frozen=True)
class ExtractionResult:
    """What a parser produced for one document.

    ``blocked_by`` is set when the document itself cannot be trusted (an
    ambiguous access key, for example); field-level rules belong to the
    validator instead.
    """

    parser_id: str
    fields: ExtractedFields
    blocked_by: FailureCode | None = None
    blocked_detail: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationOutcome:
    """Whether the extracted fields may be turned into a filename.

    ``record`` is always set when the outcome passed, so the filename layer
    never has to re-check for missing data.
    """

    status: CheckStatus
    record: ValidatedRecord | None = None
    failure_code: FailureCode | None = None
    reason: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status is not CheckStatus.FAIL


def failure(code: FailureCode, detail: str | None = None) -> ValidationOutcome:
    """Build a FAIL outcome, optionally with a specific human explanation."""
    reason = FAILURE_MESSAGES[code]
    if detail:
        reason = f"{reason} ({detail})"
    return ValidationOutcome(status=CheckStatus.FAIL, failure_code=code, reason=reason)


@dataclass
class FileOutcome:
    """Everything the report and the GUI need to know about one file."""

    source_path: Path
    status: Status
    failure_code: FailureCode | None = None
    reason: str | None = None
    parser_id: str | None = None
    access_key: str | None = None
    nf_number: str | None = None
    emission_date: str | None = None
    total_value: str | None = None
    issuer: str | None = None
    target_filename: str | None = None
    destination_path: Path | None = None
    recipient: str | None = None
    name_source: str | None = None
    #: ``pdf`` or ``xml``: the file that was read.
    source_type: str | None = None
    #: ``55`` (NF-e) or ``65`` (NFC-e), when known.
    document_model: str | None = None
    #: True when the output PDF was generated from an XML by this run.
    generated: bool = False
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.status is Status.SUCCESS


@dataclass
class BatchSummary:
    """Aggregated result of one processing run."""

    started_at: datetime
    finished_at: datetime
    outcomes: list[FileOutcome]
    output_directory: Path | None = None
    report_paths: dict[str, Path] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    def count(self, status: Status) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is status)

    @property
    def succeeded(self) -> int:
        return self.count(Status.SUCCESS)

    @property
    def skipped(self) -> int:
        return self.count(Status.SKIPPED)

    @property
    def errors(self) -> int:
        return self.count(Status.ERROR)

    @property
    def converted(self) -> int:
        """Successful outputs whose PDF was generated from an XML."""
        return sum(
            1
            for outcome in self.outcomes
            if outcome.status is Status.SUCCESS
            and outcome.generated
            and outcome.destination_path is not None
        )

    def failures_by_code(self) -> dict[FailureCode, int]:
        """Group unsuccessful files by failure code, worst first."""
        counts: dict[FailureCode, int] = {}
        for outcome in self.outcomes:
            if outcome.failure_code is None:
                continue
            counts[outcome.failure_code] = counts.get(outcome.failure_code, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0].value)))
