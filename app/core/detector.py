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
from .wording import Detail, DetailCode


class UnsupportedDocument(Exception):
    """No known parser matched, or more than one did.

    ``detail`` carries the evidence: which markers were missing, or which
    layouts matched. The sentence around it belongs to whoever shows it.
    """

    def __init__(self, code: FailureCode, detail: Detail) -> None:
        super().__init__(str(detail))
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Detection:
    """The parser chosen for a document, plus the evidence for the choice."""

    parser: DanfeExtractor
    matched_parser_ids: tuple[str, ...]
    signatures: tuple[tuple[str, bool], ...] = ()


def detect(document: Document) -> Detection:
    """Return the single parser that recognises ``document``.

    Raises :class:`UnsupportedDocument` when none or several do.
    """
    matches = [parser for parser in PARSERS if parser.can_handle(document)]
    if len(matches) == 1:
        parser = matches[0]
        return Detection(parser=parser, matched_parser_ids=(parser.parser_id,))
    if not matches:
        raise UnsupportedDocument(
            FailureCode.UNSUPPORTED_FORMAT,
            Detail(
                DetailCode.LAYOUT_MISSING,
                {"signatures": _missing_signature_summary(document)},
            ),
        )
    raise UnsupportedDocument(
        FailureCode.AMBIGUOUS_FORMAT,
        Detail(
            DetailCode.LAYOUT_AMBIGUOUS,
            {"parsers": ", ".join(parser.parser_id for parser in matches)},
        ),
    )


def detect_and_extract(document: Document) -> ExtractionResult:
    """Detect the layout and read the fields in one step."""
    detection = detect(document)
    return detection.parser.extract(document)


def _missing_signature_summary(document: Document) -> str:
    """List which markers of each known layout the document is missing.

    The markers are a value, not a sentence: the frame that shows them says what
    they mean (see :data:`app.core.wording.DETAILS`).
    """
    details: list[str] = []
    for parser in PARSERS:
        missing = [
            description
            for description, present in parser.describe(document)
            if not present
        ]
        if missing:
            details.append(f"{parser.parser_id}: " + ", ".join(missing))
    return "; ".join(details)
