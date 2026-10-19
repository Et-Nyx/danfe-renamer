"""Validation rules (plan section 16): what may and may not become a filename."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.models import (
    ExtractedFields,
    ExtractionResult,
    FailureCode,
    NameSource,
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
        "recipient": "COMERCIO EXEMPLO LTDA",
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


def test_an_nfce_key_is_accepted():
    nfce = AccessKey(make_access_key("5678", model="65"))
    outcome = validate(_result(access_key_digits=nfce.digits))
    assert outcome.passed
    assert outcome.record is not None
    assert outcome.record.access_key.is_nfce


def test_another_document_model_is_not_a_danfe():
    cte = AccessKey(make_access_key("5678", model="57"))
    outcome = validate(_result(access_key_digits=cte.digits))
    assert outcome.failure_code is FailureCode.INVALID_ACCESS_KEY
    assert "55" in (outcome.reason or "")
    assert "65" in (outcome.reason or "")


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


# --------------------------------------------------------------- name source


def test_the_file_name_takes_the_issuer_by_default():
    record = validate(_result()).record
    assert record is not None
    assert record.name == "DISTRIBUIDORA MODELO LTDA"
    assert record.name_source is NameSource.EMITENTE
    assert record.recipient == "COMERCIO EXEMPLO LTDA", "both names are kept"


def test_the_recipient_can_name_the_file_instead():
    record = validate(_result(), name_source=NameSource.RECIPIENT).record
    assert record is not None
    assert record.name == "COMERCIO EXEMPLO LTDA"
    assert record.name_source is NameSource.RECIPIENT
    assert record.issuer == "DISTRIBUIDORA MODELO LTDA", "both names are kept"


@pytest.mark.parametrize("blank", [None, "   "])
def test_the_chosen_name_has_to_be_present(blank):
    """A missing name fails the file; the other name is never used instead."""
    assert validate(_result(recipient=blank)).passed, "the issuer was chosen"
    outcome = validate(_result(recipient=blank), name_source=NameSource.RECIPIENT)
    assert outcome.failure_code is FailureCode.RECIPIENT_NOT_FOUND
    assert outcome.record is None

    other = validate(_result(issuer=blank), name_source=NameSource.EMITENTE)
    assert other.failure_code is FailureCode.ISSUER_NOT_FOUND
