"""The parser interface every DANFE layout must implement.

A layout is supported by adding an extractor module and registering it; the
pipeline, validation, filename and filesystem layers stay untouched.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.models import ExtractionResult
from ..pdf.text import Document

class DanfeExtractor(ABC):
    """Reads the four required fields from one DANFE layout."""

    #: Stable identifier reported in the batch report and used in tests.
    parser_id: str

    @abstractmethod
    def can_handle(self, document: Document) -> bool:
        """Whether this layout's signature is present in the document."""

    @abstractmethod
    def extract(self, document: Document) -> ExtractionResult:
        """Read the fields. Missing fields stay ``None`` for the validator."""

    def describe(self, document: Document) -> tuple[tuple[str, bool], ...]:
        """Report this layout's signatures and whether the document has them.

        The detector uses this to explain why a document was not recognised.
        """
        return ()
