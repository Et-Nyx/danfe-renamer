"""Validation rules (plan section 16): what may and may not become a filename."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.models import (
    ExtractedFields,
    ExtractionResult,
    FailureCode,
)
from app.core.validator import validate
from app.pdf.access_key import AccessKey

from .fixtures.danfe_builder import make_access_key

KEY = AccessKey("24260912345678000199550010000056781234567896")  # September 2026


def _result(**overrides) -> ExtractionResult:
    fields = {
        "access_key_digits": KEY.digits,
        "printed_nf_number": "5678",
        "emission_date": date(2026, 9, 8),
        "emission_date_text": "08/09/2026",
        "total_value": "9.876,54",
        "issuer": "DISTRIBUIDORA MODELO LTDA",
    }
    fields.update(overrides)
    return ExtractionResult(
        parser_id="danfe_standard", fields=ExtractedFields(**fields)
    )


def test_complete_document_passes_and_yields_a_record():
    outcome = validate(_result())
    assert outcome.passed
    assert outcome.status.value == "pass"
    assert outcome.record is not None
    assert outcome.record.nf_number == "5678"
    assert outcome.record.issuer == "DISTRIBUIDORA MODELO LTDA"


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"access_key_digits": None}, FailureCode.MISSING_ACCESS_KEY),
        ({"access_key_digits": "12345678901234567890123456789012345678901234"}, FailureCode.INVALID_ACCESS_KEY),
        ({"printed_nf_number": "999999"}, FailureCode.NF_NUMBER_CONFLICT),
        ({"emission_date": None, "emission_date_text": None}, FailureCode.EMISSION_DATE_NOT_FOUND),
        ({"emission_date": date(2026, 8, 8)}, FailureCode.EMISSION_DATE_CONFLICT),
        ({"total_value": None}, FailureCode.TOTAL_VALUE_NOT_FOUND),
        ({"issuer": None}, FailureCode.ISSUER_NOT_FOUND),
        ({"issuer": "   "}, FailureCode.ISSUER_NOT_FOUND),
    ],
)
def test_each_broken_field_stops_the_file(overrides, code):
    outcome = validate(_result(**overrides))
    assert not outcome.passed
    assert outcome.failure_code is code
    assert outcome.record is None
    assert outcome.reason, "a failure must explain itself"


def test_all_zero_number_is_not_a_usable_nf_number():
    zero_key = AccessKey(make_access_key("0"))
    outcome = validate(_result(access_key_digits=zero_key.digits))
    assert outcome.failure_code is FailureCode.NF_NUMBER_INVALID


def test_a_nfce_key_is_not_a_danfe():
    nfce = AccessKey(make_access_key("123", model="65"))
    outcome = validate(_result(access_key_digits=nfce.digits))
    assert outcome.failure_code is FailureCode.INVALID_ACCESS_KEY
    assert "model" in (outcome.reason or "")


def test_blocked_extraction_keeps_its_own_code():
    result = ExtractionResult(
        parser_id="danfe_standard",
        fields=ExtractedFields(),
        blocked_by=FailureCode.ACCESS_KEY_AMBIGUOUS,
        blocked_detail="multiple keys found",
    )
    outcome = validate(result)
    assert outcome.failure_code is FailureCode.ACCESS_KEY_AMBIGUOUS
    assert "multiple keys" in (outcome.reason or "")


def test_printed_number_absence_is_only_a_warning():
    outcome = validate(_result(printed_nf_number=None))
    assert outcome.passed
