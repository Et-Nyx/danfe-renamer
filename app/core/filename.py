"""Filename generation.

Template (confirmed with the user):

    DD.MM.YYYY_NF <number> - <Emitente> - <valor>.pdf

The document's data is preserved: only characters that Windows cannot store in
a filename are replaced.
"""

from __future__ import annotations

import re

from .models import ValidatedRecord
from .normalize import format_br_date

#: Characters Windows forbids in file names.
_UNSAFE_CHARS = '<>:"/\\|?*'
_UNSAFE_RE = re.compile(f"[{re.escape(_UNSAFE_CHARS)}]")
_WHITESPACE_RE = re.compile(r"\s+")

#: Keep the whole name comfortably inside the Windows path limit, leaving room
#: for the output directory and any batch sub-directory.
MAX_FILENAME_LENGTH = 150

#: Names Windows reserves; a name starting with ``DD.MM.YYYY_`` can never be
#: one of them, and tests assert that the template keeps that property.
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def sanitize_component(text: str) -> str:
    """Make ``text`` safe as part of a Windows file name.

    Only what Windows cannot store is changed: forbidden characters become
    ``-``, runs of forbidden characters collapse into one, runs of whitespace
    become a single space, and leading/trailing spaces, dots and dashes (which
    Windows strips or that would be read as separators) are removed. Letters,
    accents, punctuation and the spacing of the document are kept.
    """
    cleaned = _UNSAFE_RE.sub("-", text)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned.strip(" .-")


def build_filename(record: ValidatedRecord) -> str:
    """Build the target file name for a validated record.

    The name in the middle is the record's chosen one: the issuer, or the
    recipient when the document was processed with that preference.
    """
    date_part = format_br_date(record.emission_date)
    number_part = sanitize_component(record.nf_number)
    value_part = sanitize_component(record.total_value)
    name_part = _fit_name(record, date_part, number_part, value_part)
    return f"{date_part}_NF {number_part} - {name_part} - {value_part}.pdf"


def _fit_name(
    record: ValidatedRecord, date_part: str, number_part: str, value_part: str
) -> str:
    """Sanitize the name, shortening it only if the whole name gets too long."""
    name = sanitize_component(record.name)
    fixed_length = len(f"{date_part}_NF {number_part} -  - {value_part}.pdf")
    available = MAX_FILENAME_LENGTH - fixed_length
    if len(name) <= available:
        return name
    return name[:available].rstrip(" .-")
