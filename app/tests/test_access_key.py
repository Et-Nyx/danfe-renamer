"""Access-key tests (plan section 20, "Access key")."""

from __future__ import annotations

import pytest

from app.pdf.access_key import (
    AccessKey,
    InvalidAccessKey,
    check_digit,
    digits_only,
    find_key_occurrences,
    is_valid_access_key,
)
from app.pdf.text import load_document

from .fixtures.danfe_builder import group_key, make_access_key, write_danfe

#: A real key from the corpus, with its check digit.
REAL_KEY = "24260912345678000199550010000056781234567896"


def test_real_key_decodes_to_expected_fields():
    key = AccessKey(REAL_KEY)
    assert key.nf_number == "5678"
    assert key.number == "000005678"
    assert (key.year, key.month) == (2026, 9)
    assert key.uf == "35"
    assert key.issuer_cnpj == "12345678000199"
    assert key.is_nfe


def test_check_digit_matches_printed_key():
    assert check_digit(REAL_KEY[:43]) == REAL_KEY[43]


def test_key_with_all_zero_number_is_flagged_by_nf_number():
    key = AccessKey(make_access_key("0"))
    assert key.number == "000000000"
    assert key.nf_number == ""


def test_malformed_key_is_rejected():
    with pytest.raises(InvalidAccessKey):
        AccessKey(REAL_KEY[:-1] + ("0" if REAL_KEY[-1] != "0" else "1"))
    with pytest.raises(InvalidAccessKey):
        AccessKey("1234")
    with pytest.raises(InvalidAccessKey):
        AccessKey("X" * 44)
    assert not is_valid_access_key(REAL_KEY + "9")


def test_digits_only_strips_the_printed_grouping():
    assert digits_only("2426 0912 3456-7800") == "2426091234567800"


def test_key_split_over_spaces_is_found(tmp_path):
    path = tmp_path / "spaced.pdf"
    write_danfe(path, key=REAL_KEY)
    document = load_document(path)
    occurrences = find_key_occurrences(document)
    assert [occurrence.digits for occurrence in occurrences] == [REAL_KEY]
    assert group_key(REAL_KEY).count(" ") == 10


def test_key_split_over_two_rows_is_found(tmp_path):
    """A key that wraps at the end of its box must still be read."""
    import pymupdf

    path = tmp_path / "wrapped.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 40), "CHAVE DE ACESSO", fontsize=8)
    page.insert_text((40, 50), group_key(REAL_KEY)[:24], fontsize=8)
    page.insert_text((40, 59), group_key(REAL_KEY)[25:], fontsize=8)
    document.save(path)
    document.close()

    loaded = load_document(path)
    assert [occ.digits for occ in find_key_occurrences(loaded)] == [REAL_KEY]


def test_unrelated_digits_never_form_a_key(tmp_path):
    """Digits from other cells must not concatenate into a key."""
    import pymupdf

    path = tmp_path / "cells.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 40), "CEP 16401-094", fontsize=8)
    page.insert_text((40, 50), group_key(REAL_KEY), fontsize=8)
    document.save(path)
    document.close()

    loaded = load_document(path)
    assert [occ.digits for occ in find_key_occurrences(loaded)] == [REAL_KEY]
