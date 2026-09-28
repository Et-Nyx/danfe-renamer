"""Validation layer: decide whether a filename can be trusted.

Every condition that could make the filename wrong is a FAIL (the file is
skipped and explained). Warnings are recorded when the document is still
unambiguous.

``name_source`` says which of the two printed names the file name should carry;
the validator fails the file when that particular name is missing, rather than
falling back to the other one - a file named after the wrong company is exactly
the kind of quiet mistake the plan forbids.
"""

from __future__ import annotations

from ..pdf.access_key import AccessKey, InvalidAccessKey
from .models import (
    CheckStatus,
    ExtractionResult,
    ExtractedFields,
    FailureCode,
    NameSource,
    ValidatedRecord,
    ValidationOutcome,
    failure,
)


def validate(
    result: ExtractionResult,
    *,
    name_source: NameSource = NameSource.EMITENTE,
) -> ValidationOutcome:
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

    name, name_failure = _chosen_name(fields, name_source)
    if name_failure is not None:
        return name_failure

    return ValidationOutcome(
        status=CheckStatus.PASS,
        record=ValidatedRecord(
            access_key=access_key,
            nf_number=access_key.nf_number,
            emission_date=emission_date,
            total_value=fields.total_value,
            name=name,
            name_source=name_source,
            issuer=fields.issuer,
            recipient=fields.recipient,
        ),
        warnings=tuple(warnings),
    )


def _chosen_name(
    fields: ExtractedFields, name_source: NameSource
) -> tuple[str | None, ValidationOutcome | None]:
    """The name the file should carry, or the failure that prevents naming it."""
    if name_source is NameSource.RECIPIENT:
        if fields.recipient is None or not fields.recipient.strip():
            return None, failure(FailureCode.RECIPIENT_NOT_FOUND)
        return fields.recipient.strip(), None
    if fields.issuer is None or not fields.issuer.strip():
        return None, failure(FailureCode.ISSUER_NOT_FOUND)
    return fields.issuer.strip(), None


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
