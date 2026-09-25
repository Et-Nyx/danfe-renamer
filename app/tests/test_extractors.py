"""Parser tests (plan section 20: layout variants, dates, values, issuer)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.detector import UnsupportedDocument, detect, detect_and_extract
from app.core.models import FailureCode
from app.core.validator import validate
from app.pdf.text import load_document

from .fixtures.danfe_builder import make_access_key, write_danfe


@pytest.fixture
def danfe(tmp_path):
    """A portrait DANFE with the fields the tests expect."""
    path = tmp_path / "nota.pdf"
    write_danfe(path)
    return path


def extract(path):
    return detect_and_extract(load_document(path))


def validated(path):
    """The values that passed validation, which is what a filename is built from."""
    outcome = validate(extract(path))
    assert outcome.passed, outcome.reason
    assert outcome.record is not None
    return outcome.record


def test_standard_layout_is_recognised(danfe):
    detection = detect(load_document(danfe))
    assert detection.parser.parser_id == "danfe_standard"


def test_fields_are_read_from_a_portrait_danfe(danfe):
    record = validated(danfe)
    assert record.nf_number == "1234"
    assert record.emission_date == date(2026, 9, 16)
    assert record.total_value == "1.234,56"
    assert record.issuer == "INDUSTRIA EXEMPLO LTDA"
    assert record.access_key.digits == make_access_key("1234")


def test_landscape_danfe_with_rotated_stub_is_read(tmp_path):
    path = tmp_path / "landscape.pdf"
    write_danfe(path, landscape=True, issuer="COMERCIO EXEMPLO LTDA")
    record = validated(path)
    assert record.nf_number == "1234"
    assert record.total_value == "1.234,56"
    assert record.issuer == "COMERCIO EXEMPLO LTDA"
    directions = {line.direction for line in load_document(path).lines}
    assert (0.0, -1.0) in directions, "the fixture must exercise a rotated stub"


def test_erp_labels_are_read(tmp_path):
    """``DATA DA EMISSÃO`` and ``V. TOTAL DA NOTA`` are the ERP variant."""
    path = tmp_path / "erp.pdf"
    write_danfe(path, date_label="DATA DA EMISSÃO", total_label="V. TOTAL DA NOTA")
    record = validated(path)
    assert record.emission_date == date(2026, 9, 16)
    assert record.total_value == "1.234,56"


def test_unknown_layout_is_not_guessed(tmp_path):
    import pymupdf

    path = tmp_path / "not-a-danfe.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 40), "Some other document", fontsize=10)
    document.save(path)
    document.close()

    with pytest.raises(UnsupportedDocument) as excinfo:
        detect(load_document(path))
    assert excinfo.value.code is FailureCode.UNSUPPORTED_FORMAT
    assert "CHAVE DE ACESSO" in excinfo.value.reason


def test_access_key_conflict_with_printed_number_fails(tmp_path):
    """The printed number is a cross-check, never silently overridden."""
    path = tmp_path / "conflict.pdf"
    write_danfe(path, nf_number="1234", printed_nf_number="9999999")
    outcome = validate(extract(path))
    assert not outcome.passed
    assert outcome.failure_code is FailureCode.NF_NUMBER_CONFLICT
    assert "9999999" in (outcome.reason or "")


def test_exit_date_is_never_used(tmp_path):
    path = tmp_path / "exit.pdf"
    write_danfe(path, emission_date="16/09/2026", exit_date="30/09/2026")
    assert validated(path).emission_date == date(2026, 9, 16)


def test_impossible_emission_date_is_reported(tmp_path):
    path = tmp_path / "impossible.pdf"
    write_danfe(path, emission_date="31/02/2026")
    result = extract(path)
    assert result.fields.emission_date is None
    assert result.blocked_by is FailureCode.EMISSION_DATE_NOT_FOUND
    outcome = validate(result)
    assert outcome.failure_code is FailureCode.EMISSION_DATE_NOT_FOUND
    assert "31/02/2026" in (outcome.reason or "")


def test_emission_date_disagreeing_with_key_month_fails(tmp_path):
    path = tmp_path / "month.pdf"
    # The key carries September, the printed date says August.
    write_danfe(path, emission_date="16/08/2026", emitted="16/08/2026")
    outcome = validate(extract(path))
    assert outcome.failure_code is FailureCode.EMISSION_DATE_CONFLICT


def test_products_total_is_not_used_as_the_note_total(tmp_path):
    path = tmp_path / "products.pdf"
    write_danfe(path, products_total="1.200,00", total="1.234,56")
    result = extract(path)
    assert result.fields.total_value == "1.234,56"
    assert result.fields.products_total == "1.200,00"


def test_missing_total_value_is_reported_not_guessed(tmp_path):
    """An empty cell must fail, even when other amounts sit further down."""
    path = tmp_path / "no-total.pdf"
    write_danfe(path, total="sem valor informado")
    result = extract(path)
    assert result.fields.total_value is None
    assert validate(result).failure_code is FailureCode.TOTAL_VALUE_NOT_FOUND


def test_unusual_but_valid_amount_is_preserved(tmp_path):
    path = tmp_path / "big.pdf"
    write_danfe(path, total="1.234.567,89")
    assert validated(path).total_value == "1.234.567,89"


def test_issuer_is_taken_from_the_emitente_block_not_the_recipient(tmp_path):
    path = tmp_path / "two-names.pdf"
    write_danfe(
        path,
        issuer="INDUSTRIA MODELO LTDA EPP",
        recipient="DISTRIBUIDORA MODELO LTDA",
    )
    assert validated(path).issuer == "INDUSTRIA MODELO LTDA EPP"


def test_accented_issuer_is_kept_as_printed(tmp_path):
    path = tmp_path / "accented.pdf"
    write_danfe(path, issuer="São João Comércio Ltda")
    assert validated(path).issuer == "São João Comércio Ltda"


def test_later_pages_do_not_override_the_first_page(tmp_path):
    """Money rows on page 2 must not beat the total printed on page 1."""
    path = tmp_path / "multi.pdf"
    write_danfe(path, total="29.870,44", extra_pages=2)
    assert validated(path).total_value == "29.870,44"


def test_key_of_a_referenced_note_does_not_win(tmp_path):
    """A devolução carries another note's key in its additional data."""
    import pymupdf

    path = tmp_path / "devolucao.pdf"
    own_key = write_danfe(path)
    referenced = make_access_key("605", year=2026, month=8)
    document = pymupdf.open(path)
    page = document[0]
    page.insert_text((40, 700), "DADOS ADICIONAIS", fontsize=8)
    page.insert_text((40, 710), f"DEV REFERENTE A NF 605 CHAVE {referenced}", fontsize=8)
    document.save(tmp_path / "devolucao-with-reference.pdf")
    document.close()

    result = extract(tmp_path / "devolucao-with-reference.pdf")
    assert result.fields.access_key_digits == own_key
    assert any("Referenced note keys present" in note for note in result.warnings)
