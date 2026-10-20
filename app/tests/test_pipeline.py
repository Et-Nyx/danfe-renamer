"""Pipeline and batch behaviour (plan sections 5, 12, 17 and 20)."""

from __future__ import annotations

import json

import pymupdf
import pytest

from app import __version__
from app.core.detector import detect
from app.core.models import FailureCode, InputKind, NameSource, Status
from app.core.pipeline import analyze_file, run_batch
from app.core.wording import message
from app.pdf.text import load_document

from .fixtures.danfe_builder import write_danfe, write_nfe_xml

EXPECTED_NAME = "16.09.2026_NF 1234 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf"


def _make_danfe(path, **kwargs):
    write_danfe(path, **kwargs)
    return path


def _make_xml(path, **kwargs):
    write_nfe_xml(path, **kwargs)
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


def _csv_rows(summary):
    """The CSV report as rows, keyed by column."""
    import csv

    from app.reporting.report import CSV_DELIMITER

    with summary.report_paths["csv"].open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=CSV_DELIMITER))


def _unreadable(path):
    """A file that goes through the batch and fails, so a report has a failure in it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a pdf at all")
    return path


def test_the_reports_are_written_in_the_language_they_are_asked_for(tmp_path):
    """The sentences follow the language; what a machine reads does not."""
    broken = _unreadable(tmp_path / "in" / "quebrado.pdf")

    portuguese = _csv_rows(run_batch([broken], tmp_path / "pt", language="pt"))[0]
    english = _csv_rows(run_batch([broken], tmp_path / "en", language="en"))[0]

    assert portuguese["failure_message"] == "Não foi possível ler o PDF"
    assert english["failure_message"] == "PDF could not be read"
    # The columns a machine keys on say the same thing either way; the words the
    # library produced travel inside the sentence instead of beside it.
    assert portuguese["failure_code"] == english["failure_code"] == "PDF_READ_ERROR"
    assert portuguese["status"] == english["status"] == Status.SKIPPED.value
    assert portuguese["detail_code"] == english["detail_code"] == "PDF_OPEN_FAILED"
    assert "Não foi possível abrir o PDF" in portuguese["reason"]
    assert "Could not open the PDF" in english["reason"]
    library_words = english["reason"].split(": ", 1)[1]
    assert library_words in portuguese["reason"], (
        "what the library said is kept, in whatever language it arrived"
    )


def test_an_english_report_is_still_the_default(tmp_path):
    """A caller that says nothing gets what it always got."""
    broken = _unreadable(tmp_path / "in" / "quebrado.pdf")
    row = _csv_rows(run_batch([broken], tmp_path / "out"))[0]
    assert row["failure_message"] == "PDF could not be read"


def test_the_html_report_is_in_the_language_too(tmp_path):
    broken = _unreadable(tmp_path / "in" / "quebrado.pdf")
    summary = run_batch([broken], tmp_path / "out", language="pt")

    document = summary.report_paths["html"].read_text(encoding="utf-8")
    assert '<html lang="pt">' in document
    assert "Motivos das falhas" in document
    assert "Arquivo original" in document
    assert "Não foi possível ler o PDF" in document
    assert "Source file" not in document, "no English heading left in it"


def test_the_json_report_says_which_language_it_is_in(tmp_path):
    broken = _unreadable(tmp_path / "in" / "quebrado.pdf")
    summary = run_batch([broken], tmp_path / "out", language="pt")

    payload = json.loads(summary.report_paths["json"].read_text(encoding="utf-8"))
    assert payload["language"] == "pt"
    assert list(payload["failures_by_code"]) == ["PDF_READ_ERROR"]
    assert list(payload["failures_by_message"]) == ["Não foi possível ler o PDF"]


def test_batch_report_lists_the_agreed_columns(tmp_path):
    source = _make_danfe(tmp_path / "in" / "nota.pdf")
    summary = run_batch([source], tmp_path / "out")
    csv_text = summary.report_paths["csv"].read_text(encoding="utf-8-sig")
    header = csv_text.splitlines()[0].split(";")
    assert header == [
        "source_filename",
        "status",
        "failure_code",
        "failure_message",
        "detail_code",
        "parser",
        "access_key",
        "nf_number",
        "emission_date",
        "valor_total_da_nota",
        "issuer",
        "recipient",
        "name_source",
        "target_filename",
        "output_file",
        "reason",
        "warnings",
        "source_type",
        "document_model",
        "generated",
    ]
    assert EXPECTED_NAME in csv_text

    payload = json.loads(summary.report_paths["json"].read_text(encoding="utf-8"))
    assert payload["application_version"] == __version__
    assert payload["totals"] == {
        "analyzed": 1,
        "renamed": 1,
        "converted_from_xml": 0,
        "skipped": 0,
        "errors": 0,
    }
    assert __version__ in summary.report_paths["html"].read_text(encoding="utf-8")


def test_dry_run_writes_nothing(tmp_path):
    source = _make_danfe(tmp_path / "nota.pdf")
    output_root = tmp_path / "out"

    summary = run_batch([source], output_root, copy_files=False)

    assert summary.succeeded == 1
    assert summary.output_directory is None
    assert not output_root.exists()
    assert list(tmp_path.rglob("*.pdf")) == [source]


def test_the_emission_date_reads_the_same_from_a_pdf_and_from_an_xml(tmp_path):
    """One note, one string: the column must not depend on which file it came from."""
    from_pdf = _make_danfe(tmp_path / "pdf" / "nota.pdf", emission_date="16/09/2026")
    from_xml = _make_xml(tmp_path / "xml" / "nota.xml", nf_number="1234")

    pdf_outcome = run_batch([from_pdf], tmp_path / "out-pdf").outcomes[0]
    xml_outcome = run_batch([from_xml], tmp_path / "out-xml").outcomes[0]

    assert pdf_outcome.emission_date == "16.09.2026"
    assert xml_outcome.emission_date == "16.09.2026"


def test_an_impossible_printed_date_is_named_in_the_detail(tmp_path):
    """With no date to report, the detail says which date the page printed."""
    source = _make_danfe(tmp_path / "nota.pdf", emission_date="31/02/2026")

    outcome = run_batch([source], tmp_path / "out").outcomes[0]

    assert outcome.failure_code is FailureCode.EMISSION_DATE_NOT_FOUND
    assert outcome.emission_date is None
    assert outcome.detail is not None
    assert "31/02/2026" in outcome.detail.sentence()


# --------------------------------------------- a file that fails keeps its PDF
#
# An XML has no PDF anywhere until a run makes one, so a file that could not be
# named used to leave nothing at all: the DANFE was rendered into a staging
# folder and deleted with it, or never rendered in the first place. Whoever has
# to finish that file by hand - rename it, print it, send it - needs the document
# itself, so it is kept in the batch's `_unrenamed` folder, under the name of the
# XML it came from.


def test_an_xml_that_cannot_be_named_keeps_its_pdf(tmp_path):
    source = _make_xml(tmp_path / "in" / "sem-destinatario.xml", recipient="")

    summary = run_batch([source], tmp_path / "out", name_source=NameSource.RECIPIENT)

    outcome = summary.outcomes[0]
    assert outcome.status is Status.SKIPPED
    assert outcome.failure_code is FailureCode.RECIPIENT_NOT_FOUND
    kept = summary.output_directory / "_unrenamed" / "sem-destinatario.pdf"
    assert outcome.destination_path == kept, "the row points at the PDF it kept"
    assert outcome.unnamed is True
    assert outcome.generated is True, "this run did make the PDF it is keeping"
    with pymupdf.open(kept) as document:
        assert document.page_count >= 1
        assert "INDUSTRIA EXEMPLO LTDA" in document[0].get_text(), (
            "the kept file is the document itself, not an empty stand-in"
        )


def test_the_kept_pdf_is_not_passed_off_as_a_renamed_copy(tmp_path):
    """The batch folder still holds only the files that were named."""
    source = _make_xml(tmp_path / "in" / "sem-destinatario.xml", recipient="")

    summary = run_batch([source], tmp_path / "out", name_source=NameSource.RECIPIENT)

    assert summary.succeeded == 0
    assert not list(summary.output_directory.glob("*.pdf")), (
        "a file nobody could name does not belong among the renamed ones"
    )


def test_a_copy_that_fails_keeps_the_pdf_it_was_going_to_write(tmp_path, monkeypatch):
    """The DANFE was made and verified; only putting it in place failed."""
    from app.core import pipeline
    from app.core.filesystem import OutputWriteError
    from app.core.wording import Detail, DetailCode

    real_copy = pipeline.copy_into_batch

    def refuse_the_named_copy(source, destination, **kwargs):
        if "_unrenamed" not in str(destination):
            raise OutputWriteError(
                Detail(
                    DetailCode.COPY_FAILED,
                    {
                        "destination": str(destination),
                        "error": "simulated: something is holding the fresh file",
                    },
                )
            )
        return real_copy(source, destination, **kwargs)

    monkeypatch.setattr(pipeline, "copy_into_batch", refuse_the_named_copy)
    source = _make_xml(tmp_path / "in" / "nota.xml")

    summary = run_batch([source], tmp_path / "out")

    outcome = summary.outcomes[0]
    assert outcome.status is Status.ERROR
    assert outcome.failure_code is FailureCode.OUTPUT_WRITE_ERROR
    kept = summary.output_directory / "_unrenamed" / "nota.pdf"
    assert outcome.destination_path == kept
    assert kept.exists(), "the generated PDF must not follow the staging folder out"
    assert outcome.generated is True


def test_what_went_wrong_is_still_what_the_row_says(tmp_path):
    """Keeping the PDF must not turn the row into a story about the rescue."""
    source = _make_xml(tmp_path / "in" / "sem-destinatario.xml", recipient="")

    summary = run_batch([source], tmp_path / "out", name_source=NameSource.RECIPIENT)

    outcome = summary.outcomes[0]
    assert outcome.failure_code is FailureCode.RECIPIENT_NOT_FOUND
    assert "recipient" in message(outcome.failure_code).lower()
    assert outcome.detail is None, "the rescue adds no story of its own"


def test_an_xml_that_cannot_be_read_keeps_nothing(tmp_path):
    source = tmp_path / "in" / "quebrado.xml"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"this is not XML at all")

    summary = run_batch([source], tmp_path / "out")

    outcome = summary.outcomes[0]
    assert outcome.failure_code is FailureCode.XML_READ_ERROR
    assert outcome.destination_path is None
    assert not (summary.output_directory / "_unrenamed").exists(), (
        "there was no DANFE to keep"
    )


def test_two_files_with_the_same_name_are_both_kept(tmp_path):
    """Neither may be lost to a name that nobody agreed on."""
    first = _make_xml(tmp_path / "2025" / "nota.xml", nf_number="1234", recipient="")
    second = _make_xml(tmp_path / "2026" / "nota.xml", nf_number="1235", recipient="")

    summary = run_batch(
        [first, second], tmp_path / "out", name_source=NameSource.RECIPIENT
    )

    folder = summary.output_directory / "_unrenamed"
    assert sorted(path.name for path in folder.iterdir()) == [
        "nota (2).pdf",
        "nota.pdf",
    ]
    assert [outcome.destination_path for outcome in summary.outcomes] == [
        folder / "nota.pdf",
        folder / "nota (2).pdf",
    ]


def test_a_note_already_in_the_batch_keeps_no_second_copy(tmp_path):
    """Its reason already says where it is; a duplicate is not a lost document."""
    first = _make_xml(tmp_path / "in" / "primeira.xml", nf_number="1234")
    second = _make_xml(tmp_path / "in" / "segunda.xml", nf_number="1234")

    summary = run_batch([first, second], tmp_path / "out")

    assert [o.failure_code for o in summary.outcomes] == [
        None,
        FailureCode.DUPLICATE_NOTE,
    ]
    assert summary.outcomes[1].destination_path is None
    assert not (summary.output_directory / "_unrenamed").exists()
    assert len(list(summary.output_directory.glob("*.pdf"))) == 1


def test_a_pdf_that_fails_keeps_nothing_because_the_reader_has_it(tmp_path):
    """A PDF input is the user's own file; the batch has nothing to hand over."""
    broken = _unreadable(tmp_path / "in" / "quebrado.pdf")

    summary = run_batch([broken], tmp_path / "out")

    assert summary.outcomes[0].destination_path is None
    assert not (summary.output_directory / "_unrenamed").exists()


def test_a_dry_run_keeps_nothing(tmp_path):
    source = _make_xml(tmp_path / "in" / "sem-destinatario.xml", recipient="")
    output_root = tmp_path / "out"

    summary = run_batch(
        [source], output_root, copy_files=False, name_source=NameSource.RECIPIENT
    )

    assert summary.outcomes[0].destination_path is None
    assert not output_root.exists()


def test_the_report_names_the_file_it_kept(tmp_path):
    """One column locates every file the run produced, whether it has a name or not."""
    good = _make_xml(tmp_path / "in" / "nota.xml", nf_number="1235")
    refused = _make_xml(tmp_path / "in" / "sem-destinatario.xml", recipient="")

    summary = run_batch(
        [good, refused], tmp_path / "out", name_source=NameSource.RECIPIENT
    )

    rows = {row["source_filename"]: row for row in _csv_rows(summary)}
    kept = summary.output_directory / "_unrenamed" / "sem-destinatario.pdf"
    assert rows["sem-destinatario.xml"]["output_file"] == str(
        kept.relative_to(summary.output_directory)
    ), "the folder would otherwise hold a file no line explains"
    assert rows["nota.xml"]["output_file"] == rows["nota.xml"]["target_filename"]


def test_a_copying_run_needs_somewhere_to_copy_to(tmp_path, monkeypatch):
    """``None`` is not "the current directory": no caller means to write there."""
    source = _make_danfe(tmp_path / "nota.pdf")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError) as refused:
        run_batch([source], None)

    assert "output_root" in str(refused.value)
    assert not (tmp_path / "DANFE_Renamed").exists(), "nothing was written"


def test_a_report_does_not_repeat_the_reason_in_two_languages(tmp_path):
    """One sentence, chosen by the report's language, plus what the layer added."""
    source = _make_xml(tmp_path / "in" / "sem-destinatario.xml", recipient="")

    summary = run_batch(
        [source], tmp_path / "out", name_source=NameSource.RECIPIENT, language="pt"
    )

    html = summary.report_paths["html"].read_text(encoding="utf-8")
    assert "Não foi possível identificar o destinatário com segurança" in html
    assert "Recipient name could not be identified confidently" not in html, (
        "the catalogue sentence in the other language is not a reason"
    )
    assert _csv_rows(summary)[0]["reason"] == "", (
        "the failure code already says it all: no second sentence, in any language"
    )


def test_a_batch_can_name_the_copies_after_the_recipient(tmp_path):
    source = _make_danfe(
        tmp_path / "nota.pdf",
        issuer="INDUSTRIA EXEMPLO LTDA",
        recipient="COMERCIO EXEMPLO LTDA",
    )

    summary = run_batch(
        [source], tmp_path / "out", name_source=NameSource.RECIPIENT
    )

    expected = "16.09.2026_NF 1234 - COMERCIO EXEMPLO LTDA - 1.234,56.pdf"
    assert summary.succeeded == 1
    assert summary.output_directory is not None
    assert (summary.output_directory / expected).exists()
    assert not (summary.output_directory / EXPECTED_NAME).exists()
    outcome = summary.outcomes[0]
    assert outcome.name_source == NameSource.RECIPIENT.value
    assert outcome.issuer == "INDUSTRIA EXEMPLO LTDA", "both names are reported"
    assert outcome.recipient == "COMERCIO EXEMPLO LTDA"
    csv_text = summary.report_paths["csv"].read_text(encoding="utf-8-sig")
    assert "destinatario" in csv_text


def test_the_chosen_name_missing_skips_the_file_with_its_own_code(tmp_path):
    """No recipient in the document, recipient chosen: nothing is written."""
    source = _make_danfe(tmp_path / "nota.pdf")
    output_root = tmp_path / "out"

    summary = run_batch(
        [source], output_root, name_source=NameSource.RECIPIENT
    )

    assert summary.skipped == 1
    assert summary.outcomes[0].failure_code is FailureCode.RECIPIENT_NOT_FOUND
    assert list(tmp_path.rglob("*.pdf")) == [source]


def test_two_different_notes_with_the_same_name_are_reported_as_a_collision(tmp_path):
    """Same number, issuer, date and value in two series: both want one name."""
    first = _make_danfe(tmp_path / "a" / "nota.pdf", series="001")
    second = _make_danfe(tmp_path / "b" / "outra.pdf", series="002", control="987654321")

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


def test_the_same_note_twice_is_reported_as_duplicate_work(tmp_path):
    """The same note often sits in a folder twice: renamed, and as downloaded.

    That is not a collision between two notes; the access key says so, and the
    report should say so too.
    """
    already_renamed = _make_danfe(tmp_path / "a" / "nota.pdf")
    raw_download = _make_danfe(
        tmp_path / "b" / "24260912345678000199550010000012341234567891.pdf"
    )

    summary = run_batch([already_renamed, raw_download], tmp_path / "out")

    assert summary.succeeded == 1
    assert summary.skipped == 1
    duplicate = [
        item for item in summary.outcomes if item.failure_code is FailureCode.DUPLICATE_NOTE
    ]
    assert len(duplicate) == 1
    assert duplicate[0].source_path == raw_download
    assert duplicate[0].detail is not None
    assert "nota.pdf" in duplicate[0].detail.sentence()
    assert not [
        item for item in summary.outcomes if item.failure_code is FailureCode.OUTPUT_COLLISION
    ]
    assert summary.failures_by_code()[FailureCode.DUPLICATE_NOTE] == 1


def test_duplicate_work_is_recognised_without_copying_too(tmp_path):
    """A dry run reports the duplicate as well, because nothing is written."""
    first = _make_danfe(tmp_path / "a" / "nota.pdf")
    second = _make_danfe(tmp_path / "b" / "outra.pdf")
    summary = run_batch([first, second], None, copy_files=False)
    assert summary.succeeded == 1
    assert summary.skipped == 1
    assert summary.failures_by_code()[FailureCode.DUPLICATE_NOTE] == 1


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
    assert all(
        message(item.failure_code) for item in summary.outcomes if not item.succeeded
    ), "every failure is explained"
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

    found = collect_sources(
        [tmp_path / "batch"],
        [tmp_path / "batch" / "out"],
        input_kind=InputKind.PDF,
    )

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
