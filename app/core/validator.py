"""Validation layer: decide whether a filename can be trusted.

Every condition that could make the filename wrong is a FAIL (the file is
skipped and explained). Warnings are recorded when the document is still
unambiguous.
"""

from __future__ import annotations

from ..pdf.access_key import AccessKey, InvalidAccessKey
from .models import (
    CheckStatus,
    ExtractionResult,
    ExtractedFields,
    FailureCode,
    ValidatedRecord,
    ValidationOutcome,
    failure,
)


def validate(result: ExtractionResult) -> ValidationOutcome:
    """Apply the cross-field rules to an extraction result."""
    if result.blocked_by is not None:
        return failure(result.blocked_by, result.blocked_detail)

    fields = result.fields
    warnings = list(result.warnings)

    access_key, key_failure = _validated_key(fields)
    if key_failure is not None:
        return key_failure

    if not access_key.nf_number or not access_key.nf_number.isdigit():
        return failure(
            FailureCode.NF_NUMBER_INVALID,
            f"access key carries number {access_key.number!r}",
        )
    if fields.printed_nf_number and fields.printed_nf_number != access_key.nf_number:
        return failure(
            FailureCode.NF_NUMBER_CONFLICT,
            f"printed {fields.printed_nf_number}, access key {access_key.nf_number}",
        )

    emission_date = fields.emission_date
    if emission_date is None:
        detail = (
            f"printed as {fields.emission_date_text!r}"
            if fields.emission_date_text
            else None
        )
        return failure(FailureCode.EMISSION_DATE_NOT_FOUND, detail)
    if (emission_date.year, emission_date.month) != (
        access_key.year,
        access_key.month,
    ):
        return failure(
            FailureCode.EMISSION_DATE_CONFLICT,
            f"emission date {fields.emission_date_text} does not match access key "
            f"{access_key.year:04d}-{access_key.month:02d}",
        )

    if fields.total_value is None:
        return failure(FailureCode.TOTAL_VALUE_NOT_FOUND)

    if fields.issuer is None or not fields.issuer.strip():
        return failure(FailureCode.ISSUER_NOT_FOUND)

    return ValidationOutcome(
        status=CheckStatus.PASS,
        record=ValidatedRecord(
            access_key=access_key,
            nf_number=access_key.nf_number,
            emission_date=emission_date,
            total_value=fields.total_value,
            issuer=fields.issuer.strip(),
        ),
        warnings=tuple(warnings),
    )


def _validated_key(
    fields: ExtractedFields,
) -> tuple[AccessKey | None, ValidationOutcome | None]:
    """Return the trusted access key, or the failure that prevents trusting it."""
    if not fields.access_key_digits:
        return None, failure(FailureCode.MISSING_ACCESS_KEY)
    try:
        key = AccessKey(fields.access_key_digits)
    except InvalidAccessKey as exc:
        return None, failure(FailureCode.INVALID_ACCESS_KEY, str(exc))
    if not key.is_nfe:
        return None, failure(
            FailureCode.INVALID_ACCESS_KEY,
            f"document model {key.model} is not NF-e (55)",
        )
    return key, None
