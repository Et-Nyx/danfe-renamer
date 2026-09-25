"""Field-level parsing and normalization.

These helpers are pure: they turn printed text (``16/09/2026``, ``1.234,56``)
into values, and format those values the way the filename expects. They never
change how a value is *printed* unless the application needs it for comparison.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

#: ``16/09/2026`` (DANFE prints the emission date with slashes).
_BR_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")

#: ``1.234,56`` / ``4321,00`` / ``R$ 1.234,56`` - Brazilian currency as printed.
_BR_MONEY_RE = re.compile(
    r"^\s*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2}))?\s*$"
)

#: A DANFE prints the total with two decimals; anything larger is not a value
#: this application should trust.
MAX_PLAUSIBLE_VALUE = Decimal("10000000000")


def looks_like_br_date(text: str) -> bool:
    """Whether ``text`` is printed as a Brazilian calendar date."""
    return _BR_DATE_RE.match(text) is not None


def parse_br_date(text: str) -> date | None:
    """Parse ``16/09/2026`` into a date, or return ``None`` when impossible.

    Impossible calendar dates (``31/02/2026``) return ``None`` so callers can
    flag them instead of silently repairing them.
    """
    match = _BR_DATE_RE.match(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def format_br_date(value: date) -> str:
    """Format a date the way the filename template requires: ``16.09.2026``."""
    return f"{value.day:02d}.{value.month:02d}.{value.year:04d}"


def looks_like_br_money(text: str) -> bool:
    """Whether ``text`` is printed as a Brazilian currency amount."""
    return _BR_MONEY_RE.match(text) is not None


def normalize_money(text: str) -> str | None:
    """Return the amount as printed, without ``R$`` or surrounding spaces.

    ``R$ 1.234,56`` -> ``1.234,56``. The Brazilian decimal convention is kept so
    the filename matches the document instead of a rewritten number.
    """
    if not looks_like_br_money(text):
        return None
    return re.sub(r"^\s*(?:R\$\s*)?", "", text).strip()


def money_to_decimal(text: str) -> Decimal | None:
    """Convert a printed Brazilian amount into a number, for validation."""
    normalized = normalize_money(text)
    if normalized is None:
        return None
    integer_part, _, decimals = normalized.partition(",")
    try:
        return Decimal(f"{integer_part.replace('.', '')}.{decimals or '0'}")
    except InvalidOperation:  # pragma: no cover - guarded by the regex above
        return None


def is_plausible_money(text: str) -> bool:
    """Whether an amount could plausibly be a NF-e total."""
    value = money_to_decimal(text)
    return value is not None and Decimal(0) <= value <= MAX_PLAUSIBLE_VALUE
