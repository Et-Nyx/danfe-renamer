"""NF-e access key: detection, validation and field decoding.

The 44-digit key is the authoritative source for the NF number, because it
occupies a fixed position instead of depending on how the DANFE was printed.

Layout (44 digits):

====== ===== ==============================================
Pos.   Len   Meaning
====== ===== ==============================================
0      2     UF (IBGE code)
2      4     AAMM (year, month)
6      14    Issuer CNPJ
20     2     Document model (55 = NF-e, 65 = NFC-e)
22     3     Series
25     9     NF number
34     9     Random / control number
43     1     Check digit (mod 11)
====== ===== ==============================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import Document, Line, Word

NFE_MODEL = "55"
KEY_LENGTH = 44

#: How many lines a printed key may span (the key is often split over lines).
_MAX_KEY_LINES = 3

#: A printed group of key digits, e.g. ``2426`` or ``0908.``
_KEY_GROUP_RE = re.compile(r"^[0-9][0-9.\-\u00a0]*$")


def check_digit(first_43_digits: str) -> str:
    """Return the mod-11 check digit of the first 43 key digits."""
    total = 0
    weight = 2
    for char in reversed(first_43_digits):
        total += int(char) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return "0" if remainder in (0, 1) else str(11 - remainder)


def is_valid_access_key(digits: str) -> bool:
    """Whether ``digits`` is a 44-digit string with a matching check digit."""
    if len(digits) != KEY_LENGTH or not digits.isdigit():
        return False
    return check_digit(digits[:43]) == digits[43]


def digits_only(text: str) -> str:
    """Strip spaces, dots and dashes used to group the key as printed."""
    return re.sub(r"[^0-9]", "", text)


class InvalidAccessKey(ValueError):
    """The digit string is not a well-formed NF-e access key."""


@dataclass(frozen=True)
class AccessKey:
    """A validated 44-digit NF-e access key."""

    digits: str

    def __post_init__(self) -> None:
        if len(self.digits) != KEY_LENGTH or not self.digits.isdigit():
            raise InvalidAccessKey(f"access key must be {KEY_LENGTH} digits")
        if self.check_digit != check_digit(self.digits[:43]):
            raise InvalidAccessKey("access key check digit does not match")

    @property
    def uf(self) -> str:
        return self.digits[0:2]

    @property
    def year(self) -> int:
        """Four-digit emission year."""
        return 2000 + int(self.digits[2:4])

    @property
    def month(self) -> int:
        return int(self.digits[4:6])

    @property
    def issuer_cnpj(self) -> str:
        return self.digits[6:20]

    @property
    def model(self) -> str:
        return self.digits[20:22]

    @property
    def series(self) -> str:
        return self.digits[22:25].lstrip("0") or "0"

    @property
    def number(self) -> str:
        """NF number as carried by the key (9 digits, leading zeroes kept)."""
        return self.digits[25:34]

    @property
    def nf_number(self) -> str:
        """NF number with leading zeroes removed, for the filename.

        Returns an empty string when the key carries an all-zero number, so the
        validator can flag it instead of building an empty filename part.
        """
        return self.number.lstrip("0")

    @property
    def check_digit(self) -> str:
        return self.digits[43]

    @property
    def is_nfe(self) -> bool:
        return self.model == NFE_MODEL


@dataclass(frozen=True)
class KeyOccurrence:
    """A 44-digit key as printed somewhere in a document."""

    digits: str
    first_line: int
    last_line: int
    words: tuple[Word, ...]

    @property
    def x0(self) -> float:
        return min(word.x0 for word in self.words)

    @property
    def x1(self) -> float:
        return max(word.x1 for word in self.words)


def find_key_occurrences(document: Document) -> tuple[KeyOccurrence, ...]:
    """Find every printed 44-digit key in ``document``, in reading order.

    The key is printed as groups of four digits. Groups are accumulated from
    consecutive words of one row, and a key may continue on the next row when it
    wraps at the end of its box. Anything else (a postal code followed by a key,
    digits from two different columns) never accumulates into a key.
    """
    occurrences: list[KeyOccurrence] = []
    lines = document.lines
    for position, line in enumerate(lines):
        for start in range(len(line.words)):
            occurrence = _accumulate_key(lines, position, start)
            if occurrence is not None:
                occurrences.append(occurrence)
    return tuple(occurrences)


#: Largest horizontal gap between two groups of the same key.
_MAX_GROUP_GAP = 30.0

#: How far a wrapped key may restart from where it started on the row above.
_MAX_WRAP_INDENT = 12.0

#: How many rows a wrapped key may span.
_MAX_KEY_ROWS = 3


def _accumulate_key(
    lines: tuple["Line", ...], line_position: int, word_position: int
) -> KeyOccurrence | None:
    """Try to read a 44-digit key starting at one printed word."""
    direction = lines[line_position].direction
    digits = ""
    collected: list[Word] = []
    rows_used = 1
    first_x0: float | None = None
    previous_x1: float | None = None

    while True:
        line = lines[line_position]
        if line.direction != direction:
            return None
        for word in line.words[word_position:]:
            if not _KEY_GROUP_RE.match(word.text):
                return None
            if first_x0 is None:
                first_x0 = word.x0
            elif previous_x1 is not None and word.x0 - previous_x1 > _MAX_GROUP_GAP:
                return None
            digits += digits_only(word.text)
            collected.append(word)
            previous_x1 = word.x1
            if len(digits) >= KEY_LENGTH:
                if len(digits) > KEY_LENGTH:
                    return None
                return KeyOccurrence(
                    digits=digits,
                    first_line=collected[0].line_index,
                    last_line=collected[-1].line_index,
                    words=tuple(collected),
                )

        line_position += 1
        rows_used += 1
        if rows_used > _MAX_KEY_ROWS or line_position >= len(lines):
            return None
        continuation_line = lines[line_position]
        if not continuation_line.words or continuation_line.direction != direction:
            return None
        first_word = continuation_line.words[0]
        if not _KEY_GROUP_RE.match(first_word.text):
            return None
        if abs(first_word.x0 - (first_x0 or 0.0)) > _MAX_WRAP_INDENT:
            return None
        word_position = 0
        previous_x1 = None
