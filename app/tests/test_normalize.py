"""Printing-level parsing tests (dates and Brazilian currency)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.normalize import (
    format_br_date,
    is_plausible_money,
    looks_like_br_date,
    looks_like_br_money,
    money_to_decimal,
    normalize_money,
    parse_br_date,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("16/09/2026", date(2026, 9, 16)),
        (" 1/9/2026 ", date(2026, 9, 1)),
        ("31/02/2026", None),
        ("00/09/2026", None),
        ("2026-09-16", None),
        ("16/09/26", None),
    ],
)
def test_parse_br_date(text, expected):
    assert parse_br_date(text) == expected


def test_only_a_full_printed_date_looks_like_a_date():
    assert looks_like_br_date("16/09/2026")
    assert not looks_like_br_date("16/09/26")
    assert not looks_like_br_date("59082-080")
    assert not looks_like_br_date("08.09.2026")


def test_format_br_date_is_the_filename_form():
    assert format_br_date(date(2026, 9, 6)) == "06.09.2026"


@pytest.mark.parametrize(
    "text, printed, number",
    [
        ("1.234,56", "1.234,56", Decimal("1234.56")),
        ("R$ 1.234,56", "1.234,56", Decimal("1234.56")),
        ("4321,00", "4321,00", Decimal("4321.00")),
        ("1.234.567,89", "1.234.567,89", Decimal("1234567.89")),
        ("0,00", "0,00", Decimal("0.00")),
        ("20,00", "20,00", Decimal("20.00")),
    ],
)
def test_brazilian_amounts_keep_their_printed_form(text, printed, number):
    assert normalize_money(text) == printed
    assert money_to_decimal(text) == number
    assert is_plausible_money(text)


@pytest.mark.parametrize(
    "text",
    [
        "4321.00",  # the US convention must not be read as a Brazilian amount
        "2,999.51",
        "16/09/2026",
        "1.0450,00",  # a human typo found in the corpus
        "R$",
        "",
    ],
)
def test_non_brazilian_amounts_are_not_accepted(text):
    assert not looks_like_br_money(text)
    assert money_to_decimal(text) is None


def test_absurdly_large_amount_is_not_plausible():
    assert not is_plausible_money("99.999.999.999,99")
