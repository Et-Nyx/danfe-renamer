"""Pipeline and batch behaviour (plan sections 5, 12, 17 and 20)."""

from __future__ import annotations

import pymupdf
import pytest

from app.core.detector import detect
from app.core.models import FailureCode, Status
from app.core.pipeline import analyze_file, run_batch
from app.pdf.text import load_document

from .fixtures.danfe_builder import write_danfe

EXPECTED_NAME = "16.09.2026_NF 1234 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf"


def _make_danfe(path, **kwargs):
    write_danfe(path, **kwargs)
    return path


def test_batch_writes_renamed_copies_and_leaves_originals(tmp_path):
    source = _make_danfe(tmp_path / "in" / "nota.pdf")
    before = source.read_bytes()
    output_root = tmp_path / "out"

    summary = run_batch([source], output_root)

    assert summary.total == 1
    assert summary.succeeded == 1
    assert summary.output_directory is not None
    assert (summary.output_directory / EXPECTED_NAME).exists()
    assert source.read_bytes() == before
    assert not (source.parent / EXPECTED_NAME).exists()
    assert set(summary.report_paths) == {"csv", "json", "html"}
    for path in summary.report_paths.values():
        assert path.exists()


def test_batch_report_lists_the_agreed_columns(tmp_path):
    source = _make_danfe(tmp_path / "in" / "nota.pdf")
    summary = run_batch([source], tmp_path / "out")
    csv_text = summary.report_paths["csv"].read_text(encoding="utf-8-sig")
    header = csv_text.splitlines()[0].split(";")
    assert header == [
        "source_filename",
        "status",
        "parser",
        "access_key",
        "nf_number",
        "emission_date",
        "valor_total_da_nota",
        "issuer",
        "target_filename",
        "reason",
        "warnings",
    ]
    assert EXPECTED_NAME in csv_text


def test_dry_run_writes_nothing(tmp_path):
    source = _make_danfe(tmp_path / "nota.pdf")
    output_root = tmp_path / "out"

    summary = run_batch([source], output_root, copy_files=False)

    assert summary.succeeded == 1
    assert summary.output_directory is None
    assert not output_root.exists()
    assert list(tmp_path.rglob("*.pdf")) == [source]


def test_two_sources_with_the_same_name_collide_without_overwriting(tmp_path):
    first = _make_danfe(tmp_path / "a" / "nota.pdf")
    second = _make_danfe(tmp_path / "b" / "outra.pdf")

    summary = run_batch([first, second], tmp_path / "out")

    assert summary.total == 2
    assert summary.succeeded == 1
    assert summary.skipped == 1
    collisions = [
        item for item in summary.outcomes if item.failure_code is FailureCode.OUTPUT_COLLISION
    ]
    assert len(collisions) == 1
    assert collisions[0].status is Status.SKIPPED
    assert summary.output_directory is not None
    assert (summary.output_directory / EXPECTED_NAME).read_bytes() == first.read_bytes()


def test_mixed_batch_reports_every_file(tmp_path):
    good = _make_danfe(tmp_path / "good.pdf")
    unsupported = tmp_path / "other.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((40, 40), "not an invoice", fontsize=10)
    document.save(unsupported)
    document.close()
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a PDF at all")

    summary = run_batch([good, unsupported, broken], tmp_path / "out")

    assert summary.total == 3
    assert summary.succeeded == 1
    assert summary.skipped == 2
    assert summary.errors == 0
    codes = {item.failure_code for item in summary.outcomes if item.failure_code}
    assert codes == {FailureCode.UNSUPPORTED_FORMAT, FailureCode.PDF_READ_ERROR}
    assert all(item.reason for item in summary.outcomes if not item.succeeded)
    assert summary.failures_by_code()[FailureCode.UNSUPPORTED_FORMAT] == 1


def test_a_batch_where_everything_fails_still_writes_a_report(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")

    summary = run_batch([broken], tmp_path / "out")

    assert summary.succeeded == 0
    assert summary.skipped == 1
    assert summary.report_paths["json"].exists()


def test_repeated_input_paths_are_processed_once(tmp_path):
    source = _make_danfe(tmp_path / "nota.pdf")
    summary = run_batch([source, source, source], tmp_path / "out")
    assert summary.total == 1
    assert summary.succeeded == 1


def test_password_protected_pdf_is_reported(tmp_path):
    path = tmp_path / "locked.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((40, 40), "locked", fontsize=10)
    document.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    document.close()

    outcome = analyze_file(path).outcome
    assert outcome.failure_code is FailureCode.PDF_ENCRYPTED
    assert outcome.status is Status.SKIPPED


def test_nested_source_folders_are_found(tmp_path):
    from app.cli import collect_sources

    _make_danfe(tmp_path / "batch" / "sub" / "deeper" / "nota.pdf")
    (tmp_path / "batch" / "notes.txt").write_text("ignore me", encoding="utf-8")
    (tmp_path / "batch" / "out").mkdir()
    _make_danfe(tmp_path / "batch" / "out" / "already_renamed.pdf")

    found = collect_sources([tmp_path / "batch"], [tmp_path / "batch" / "out"])

    assert [path.name for path in found] == ["nota.pdf"]


def test_progress_callback_sees_every_file(tmp_path):
    paths = [_make_danfe(tmp_path / f"nota{index}.pdf", nf_number=str(1000 + index)) for index in range(3)]
    seen = []
    run_batch(paths, tmp_path / "out", progress=lambda index, total, path: seen.append((index, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_analysis_of_a_good_file_is_deterministic(tmp_path):
    """Same PDF, same result: the pipeline must not depend on run order."""
    source = _make_danfe(tmp_path / "nota.pdf")
    first = analyze_file(source).outcome
    second = analyze_file(source).outcome
    assert first.target_filename == second.target_filename
    assert first.access_key == second.access_key
    assert first.status is second.status


def test_landscape_and_portrait_pdfs_produce_the_same_fields(tmp_path):
    portrait = _make_danfe(tmp_path / "portrait.pdf")
    landscape = _make_danfe(tmp_path / "landscape.pdf", landscape=True)
    assert analyze_file(portrait).outcome.target_filename == analyze_file(
        landscape
    ).outcome.target_filename


def test_detector_reports_which_signature_is_missing(tmp_path):
    path = tmp_path / "partial.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 40), "DANFE Documento Auxiliar da Nota Fiscal Eletrônica", fontsize=8)
    document.save(path)
    document.close()

    with pytest.raises(Exception) as excinfo:
        detect(load_document(path))
    assert "CHAVE DE ACESSO" in str(excinfo.value)


def test_acroform_or_extra_content_does_not_break_extraction(tmp_path):
    """Extra content elsewhere on the page does not disturb the fields."""
    path = _make_danfe(tmp_path / "nota.pdf")
    document = pymupdf.open(path)
    page = document[0]
    page.insert_text((40, 780), "RESERVADO AO FISCO", fontsize=8)
    page.insert_text((40, 790), "Inf. Contribuinte: PEDIDO 2182743", fontsize=8)
    document.save(path.with_suffix(".extra.pdf"))
    document.close()

    record = analyze_file(path.with_suffix(".extra.pdf")).outcome
    assert record.status is Status.SUCCESS
    assert record.target_filename == EXPECTED_NAME
