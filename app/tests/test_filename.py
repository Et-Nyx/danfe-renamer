"""Filename rules (plan sections 10, 11 and 20)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.filename import (
    MAX_FILENAME_LENGTH,
    RESERVED_NAMES,
    build_filename,
    sanitize_component,
)
from app.core.models import ValidatedRecord
from app.pdf.access_key import AccessKey

KEY = AccessKey("24260912345678000199550010000012341234567891")


def record(**overrides) -> ValidatedRecord:
    values = {
        "access_key": KEY,
        "nf_number": "1234",
        "emission_date": date(2026, 9, 16),
        "total_value": "1.234,56",
        "issuer": "Industria Exemplo Ltda",
    }
    values.update(overrides)
    return ValidatedRecord(**values)


def test_filename_follows_the_agreed_pattern():
    assert build_filename(record()) == "16.09.2026_NF 1234 - Industria Exemplo Ltda - 1.234,56.pdf"


def test_printed_amount_is_reproduced_not_converted():
    assert build_filename(record(total_value="1.234,56")).endswith(" - 1.234,56.pdf")
    assert "," in build_filename(record(total_value="9.876,54"))


@pytest.mark.parametrize(
    "unsafe, expected",
    [
        ('CIA "ALFA" LTDA', "CIA -ALFA- LTDA"),
        ("A/B: C\\D", "A-B- C-D"),
        ("EMPRESA?*LTDA", "EMPRESA-LTDA"),
        ("TRAILING SPACES   ", "TRAILING SPACES"),
        ("DOTS...", "DOTS"),
        ("-LEADING DASH", "LEADING DASH"),
    ],
)
def test_invalid_characters_are_replaced_not_dropped(unsafe, expected):
    cleaned = sanitize_component(unsafe)
    assert cleaned == expected
    assert not set(cleaned) & set('<>:"/\\|?*')
    assert cleaned == cleaned.rstrip(" .-")


def test_spacing_of_valid_data_is_not_rewritten():
    """A single dash surrounded by spaces keeps its spaces."""
    assert sanitize_component("L S COMERCIO - ME") == "L S COMERCIO - ME"


def test_meaning_of_valid_data_is_kept():
    name = build_filename(record(issuer="EMPRESA EXEMPLO LTDA [DEVOLUÇÃO]"))
    assert "EMPRESA EXEMPLO LTDA [DEVOLUÇÃO]" in name


def test_very_long_issuer_is_shortened_to_a_usable_length():
    long_issuer = "EMPRESA MUITO LONGA " * 12
    name = build_filename(record(issuer=long_issuer))
    assert len(name) <= MAX_FILENAME_LENGTH + len(".pdf")
    assert name.endswith(" - 1.234,56.pdf")
    assert name.startswith("16.09.2026_NF 1234 - ")


def test_generated_names_can_never_be_reserved_windows_names():
    """The template starts with the date, so a reserved name is impossible."""
    extremes = [
        record(nf_number="1", issuer="CON", total_value="0,00"),
        record(nf_number="1", issuer="NUL", total_value="0,00"),
    ]
    for item in extremes:
        name = build_filename(item)
        assert name.split(".pdf")[0].upper() not in RESERVED_NAMES
        assert name[:2].isdigit()
