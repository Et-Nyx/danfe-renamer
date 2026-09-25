"""Layout detection: decide which parser (if any) owns a document.

The detector never guesses. No match means unsupported; more than one match
means ambiguous; both are reported with the evidence that led there.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..extractors.base import DanfeExtractor
from ..extractors.registry import PARSERS
from ..pdf.text import Document
from .models import ExtractionResult, FailureCode


class UnsupportedDocument(Exception):
    """No known parser matched, or more than one did."""

    def __init__(self, code: FailureCode, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class Detection:
    """The parser chosen for a document, plus the evidence for the choice."""

    parser: DanfeExtractor
    matched_parser_ids: tuple[str, ...]
    signatures: tuple[tuple[str, bool], ...] = ()


#: Snapshot of the signatures of a layout, with the reason a document failed.
_UNMATCHED_REASON = "Could not identify a supported DANFE layout"


def detect(document: Document) -> Detection:
    """Return the single parser that recognises ``document``.

    Raises :class:`UnsupportedDocument` when none or several do.
    """
    matches = [parser for parser in PARSERS if parser.can_handle(document)]
    if len(matches) == 1:
        parser = matches[0]
        return Detection(parser=parser, matched_parser_ids=(parser.parser_id,))
    if not matches:
        missing = _missing_signature_summary(document)
        raise UnsupportedDocument(
            FailureCode.UNSUPPORTED_FORMAT,
            f"{_UNMATCHED_REASON}{missing}",
        )
    raise UnsupportedDocument(
        FailureCode.AMBIGUOUS_FORMAT,
        "More than one DANFE layout matched: "
        + ", ".join(parser.parser_id for parser in matches),
    )


def detect_and_extract(document: Document) -> ExtractionResult:
    """Detect the layout and read the fields in one step."""
    detection = detect(document)
    return detection.parser.extract(document)


def _missing_signature_summary(document: Document) -> str:
    """List which markers of each known layout the document is missing."""
    details: list[str] = []
    for parser in PARSERS:
        missing = [
            description
            for description, present in parser.describe(document)
            if not present
        ]
        if missing:
            details.append(f"{parser.parser_id}: missing " + ", ".join(missing))
    if not details:
        return ""
    return " (" + "; ".join(details) + ")"
