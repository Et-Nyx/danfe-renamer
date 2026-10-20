"""The XML workflow: reading an NF-e/NFC-e, converting it, and naming the copy.

An XML is the document SEFAZ authorized, so it is read for its fields, rendered
into a DANFE/DANFCe PDF, named and copied - and the XML itself is never written
to. This is the application's main path, and every stage of it answers for
itself here: what it reads, what it refuses and why, and what it leaves behind
when it cannot finish (see ``_unrenamed``).

The fixtures build every XML and every PDF: real invoices are confidential.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.core.models import FailureCode, NameSource, SourceKind, Status
from app.core.pipeline import analyze_xml, run_batch
from app.xml.invoice import NFCE_MODEL, NFE_MODEL, inspect_xml
from app.xml.render import XmlRenderError, render_xml_to_pdf

from .fixtures.danfe_builder import (
    NFE_NAMESPACE,
    make_nfe_xml,
    write_danfe,
    write_nfe_xml,
    write_nfce_xml,
)

EXPECTED_NAME = "16.09.2026_NF 1234 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf"


def _write(path, text: str, encoding: str = "utf-8") -> Path:
    """Write XML text the way it arrived, declaration and encoding included."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


def _xml(**kwargs) -> str:
    """The XML text of a synthetic NF-e, for the cases a fixture cannot build."""
    return make_nfe_xml(**kwargs)[0]


# ------------------------------------------------------------- reading an XML
#
# inspect_xml is the only reader: it either returns an invoice with everything
# printed on it, or refuses the document and says which rule it broke.


def test_a_well_formed_nfe_reads_every_field(tmp_path):
    source = tmp_path / "nota.xml"
    key = write_nfe_xml(source, nf_number="1234")

    invoice = inspect_xml(source)

    assert invoice.model == NFE_MODEL
    assert invoice.access_key.digits == key
    assert invoice.nf_number == "1234"
    assert invoice.emission_date_text == "16.09.2026", "the format the file name uses"
    assert invoice.total_value == "1.234,56"
    assert invoice.issuer == "INDUSTRIA EXEMPLO LTDA"
    assert invoice.recipient == "COMERCIO EXEMPLO LTDA"
    assert invoice.authorized is True
    assert invoice.warnings == ()


def test_an_nfce_reads_as_an_nfce(tmp_path):
    source = tmp_path / "cupom.xml"
    write_nfce_xml(source, nf_number="4321")

    invoice = inspect_xml(source)

    assert invoice.model == NFCE_MODEL
    assert invoice.access_key.model == NFCE_MODEL
    assert invoice.nf_number == "4321"


@pytest.mark.parametrize(
    "root, expected",
    [
        ("resNFe", "summary"),
        ("evento", "event"),
        ("procEventoNFe", "event"),
        ("pedido", "NF-e/NFC-e XML"),
    ],
)
def test_an_xml_that_is_not_an_invoice_is_refused(tmp_path, root, expected):
    source = _write(
        tmp_path / "outro.xml",
        f'<?xml version="1.0" encoding="UTF-8"?>\n<{root} xmlns="{NFE_NAMESPACE}"></{root}>',
    )

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.XML_UNSUPPORTED
    assert expected in refused.value.detail.sentence(), refused.value.detail.sentence()


def test_an_xml_that_cannot_be_parsed_is_refused(tmp_path):
    source = _write(tmp_path / "quebrado.xml", "<nfeProc><NFe>")

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.XML_READ_ERROR


def test_an_xml_that_is_not_utf8_is_read_by_its_own_declaration(tmp_path):
    """A note saved by an older emitter still names the company it was issued to."""
    text = _xml(issuer="INDÚSTRIA EXEMPLO LTDA").replace(
        'encoding="UTF-8"', 'encoding="ISO-8859-1"'
    )
    source = _write(tmp_path / "latin1.xml", text, encoding="iso-8859-1")

    invoice = inspect_xml(source)

    assert invoice.issuer == "INDÚSTRIA EXEMPLO LTDA"


def test_an_xml_with_a_byte_order_mark_is_read(tmp_path):
    source = tmp_path / "com-bom.xml"
    source.write_bytes(b"\xef\xbb\xbf" + _xml().encode("utf-8"))

    assert inspect_xml(source).nf_number == "1234"


def test_an_xml_that_defines_entities_is_refused(tmp_path):
    """The reader must not go looking for a file or a URL the XML names."""
    source = _write(
        tmp_path / "entidades.xml",
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE nfeProc [<!ENTITY segredo SYSTEM "file:///c:/windows/win.ini">]>\n'
        f'<nfeProc xmlns="{NFE_NAMESPACE}"><NFe><infNFe Id="NFe&">'
        "&segredo;</infNFe></NFe></nfeProc>",
    )

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.XML_READ_ERROR


def test_an_xml_without_an_access_key_is_refused(tmp_path):
    text = _xml(include_protocol=False).replace('<infNFe Id="NFe', '<infNFe data-id="NFe')
    source = _write(tmp_path / "sem-chave.xml", text)

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.MISSING_ACCESS_KEY


def test_an_access_key_that_fails_its_check_digit_is_refused(tmp_path):
    key = make_nfe_xml(nf_number="1234")[1]
    wrong = key[:-1] + ("0" if key[-1] != "0" else "1")
    source = _write(tmp_path / "chave-errada.xml", _xml(nf_number="1234").replace(key, wrong))

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.INVALID_ACCESS_KEY


def test_a_document_model_that_is_neither_nfe_nor_nfce_is_refused(tmp_path):
    source = _write(
        tmp_path / "outro-modelo.xml",
        _xml().replace("<mod>55</mod>", "<mod>57</mod>"),
    )

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.XML_UNSUPPORTED
    assert "57" in refused.value.detail.sentence()


def test_a_model_that_disagrees_with_the_key_is_refused(tmp_path):
    source = _write(
        tmp_path / "modelo-trocado.xml",
        _xml().replace("<mod>55</mod>", "<mod>65</mod>"),
    )

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.INVALID_ACCESS_KEY


def test_the_nf_number_comes_from_the_key_when_the_invoice_omits_it(tmp_path):
    source = _write(
        tmp_path / "sem-numero.xml", _xml(nf_number="1234").replace("<nNF>1234</nNF>", "")
    )

    invoice = inspect_xml(source)

    assert invoice.nf_number == "1234", "the key carries the number"
    assert any("nNF" in warning.sentence() for warning in invoice.warnings), (
        invoice.warnings
    )


@pytest.mark.parametrize("status", ["101", "110", "301", "999"])
def test_a_note_the_sefaz_did_not_authorize_is_refused(tmp_path, status):
    source = tmp_path / "cancelada.xml"
    write_nfe_xml(source, nf_number="1234", status=status)

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.XML_NOT_AUTHORIZED


def test_a_protocol_key_that_disagrees_with_the_invoice_key_is_refused(tmp_path):
    other = make_nfe_xml(nf_number="9999")[1]
    key = make_nfe_xml(nf_number="1234")[1]
    source = _write(
        tmp_path / "protocolo-trocado.xml",
        _xml(nf_number="1234").replace(f"<chNFe>{key}</chNFe>", f"<chNFe>{other}</chNFe>"),
    )

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.INVALID_ACCESS_KEY


def test_an_issuer_that_disagrees_with_the_key_is_refused(tmp_path):
    source = _write(
        tmp_path / "cnpj-trocado.xml",
        _xml().replace("12.345.678/0001-99", "99.999.999/0001-99"),
    )

    with pytest.raises(Exception) as refused:
        inspect_xml(source)

    assert refused.value.code is FailureCode.INVALID_ACCESS_KEY
    assert "CNPJ" in refused.value.detail.sentence()


def test_a_note_without_a_protocol_is_read_but_flagged(tmp_path):
    source = tmp_path / "sem-protocolo.xml"
    write_nfe_xml(source, nf_number="1234", include_protocol=False)

    invoice = inspect_xml(source)

    assert invoice.authorized is False
    assert any("protocol" in warning.sentence() for warning in invoice.warnings), (
        invoice.warnings
    )


def test_a_protocol_without_a_status_is_read_but_flagged(tmp_path):
    source = _write(
        tmp_path / "sem-cstat.xml", _xml(status="100").replace("<cStat>100</cStat>", "")
    )

    invoice = inspect_xml(source)

    assert invoice.authorized is False
    assert any("cStat" in warning.sentence() for warning in invoice.warnings), (
        invoice.warnings
    )


def test_a_homologation_note_is_read_and_flagged(tmp_path):
    source = tmp_path / "homologacao.xml"
    write_nfe_xml(source, nf_number="1234", homologation=True)

    invoice = inspect_xml(source)

    assert invoice.authorized is True
    assert any("omologa" in warning.sentence() for warning in invoice.warnings), (
        invoice.warnings
    )


# -------------------------------------------------------------- making the PDF
#
# The converter is the stage the whole XML workflow depends on: it either leaves
# a PDF a person can open, or it refuses and leaves nothing at all.


def test_an_nfe_renders_a_danfe(tmp_path):
    source = tmp_path / "nota.xml"
    write_nfe_xml(source)

    rendered = render_xml_to_pdf(source, tmp_path / "danfe.pdf", model=NFE_MODEL)

    with pymupdf.open(rendered) as document:
        assert document.page_count == 1
        assert "INDUSTRIA EXEMPLO LTDA" in document[0].get_text()


def test_an_nfce_renders_its_own_document(tmp_path):
    source = tmp_path / "cupom.xml"
    write_nfce_xml(source)

    rendered = render_xml_to_pdf(source, tmp_path / "danfce.pdf", model=NFCE_MODEL)

    with pymupdf.open(rendered) as document:
        assert document.page_count == 1
        assert document[0].get_text().strip(), "a page with nothing on it is not a DANFCe"


def test_a_render_never_overwrites_what_is_already_there(tmp_path):
    source = tmp_path / "nota.xml"
    write_nfe_xml(source)
    existing = tmp_path / "danfe.pdf"
    existing.write_bytes(b"something of the user's")

    with pytest.raises(XmlRenderError):
        render_xml_to_pdf(source, existing, model=NFE_MODEL)

    assert existing.read_bytes() == b"something of the user's"


def test_a_render_that_fails_leaves_no_file_behind(tmp_path):
    source = _write(tmp_path / "nao-e-nfe.xml", "<nfeProc><NFe/></nfeProc>")
    target = tmp_path / "danfe.pdf"

    with pytest.raises(XmlRenderError):
        render_xml_to_pdf(source, target, model=NFE_MODEL)

    assert not target.exists()


def test_a_document_model_that_has_no_renderer_is_refused(tmp_path):
    source = tmp_path / "nota.xml"
    write_nfe_xml(source)

    with pytest.raises(XmlRenderError) as refused:
        render_xml_to_pdf(source, tmp_path / "out.pdf", model="57")

    assert "57" in str(refused.value)


def test_an_xml_saved_in_another_encoding_can_still_be_rendered(tmp_path):
    """The reader takes the XML's own declaration; so must the converter.

    An older emitter can write the file in Latin-1, and the company name then
    carries bytes that are not UTF-8. Reading the file as UTF-8 refuses a
    document the application had already read and accepted.
    """
    text = _xml(issuer="INDÚSTRIA EXEMPLO LTDA").replace(
        'encoding="UTF-8"', 'encoding="ISO-8859-1"'
    )
    source = _write(tmp_path / "latin1.xml", text, encoding="iso-8859-1")

    rendered = render_xml_to_pdf(source, tmp_path / "danfe.pdf", model=NFE_MODEL)

    with pymupdf.open(rendered) as document:
        assert document.page_count == 1
        assert "INDÚSTRIA EXEMPLO LTDA" in document[0].get_text(), (
            "the name is printed as the file declared it, not as mojibake"
        )


# ------------------------------------------------------ the batch, end to end
#
# The XML is the document SEFAZ authorized, so the XML is what the name is built
# from and the PDF this run makes is the copy. When both files of a note are in
# one batch the printed PDF is the copy and the XML is only read for its fields.


def test_an_xml_becomes_a_named_danfe_in_a_new_batch(tmp_path):
    source = tmp_path / "in" / "nota.xml"
    key = write_nfe_xml(source, nf_number="1234")
    before = source.read_bytes()
    output_root = tmp_path / "out"

    summary = run_batch([source], output_root)

    batch = summary.output_directory
    assert summary.total == 1
    assert summary.succeeded == 1
    assert summary.converted == 1
    assert (batch / EXPECTED_NAME).exists(), sorted(path.name for path in batch.iterdir())
    assert source.read_bytes() == before, "the XML is only ever read"
    assert not list(batch.glob("*.xml")), "the XML is not copied into the batch"
    outcome = summary.outcomes[0]
    assert outcome.status is Status.SUCCESS
    assert outcome.generated is True
    assert outcome.unnamed is False
    assert outcome.source_type == "xml"
    assert outcome.document_model == "55"
    assert outcome.access_key == " ".join(
        key[index : index + 4] for index in range(0, 44, 4)
    )
    assert outcome.destination_path == batch / EXPECTED_NAME


def test_an_nfce_becomes_a_danfce_in_the_batch(tmp_path):
    source = tmp_path / "in" / "cupom.xml"
    write_nfce_xml(source, nf_number="4321")

    summary = run_batch([source], tmp_path / "out")

    outcome = summary.outcomes[0]
    assert outcome.document_model == "65"
    assert outcome.target_filename == (
        "16.09.2026_NF 4321 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf"
    )
    with pymupdf.open(outcome.destination_path) as document:
        page = document[0]
        assert page.rect.width < 300, "a DANFCe is the coupon, not an A4 page"
        assert "CONSUMIDOR" in page.get_text()


def test_an_xml_can_be_named_after_its_recipient(tmp_path):
    source = tmp_path / "in" / "nota.xml"
    write_nfe_xml(source, nf_number="1234", recipient="COMERCIO EXEMPLO LTDA")

    summary = run_batch([source], tmp_path / "out", name_source=NameSource.RECIPIENT)

    assert summary.outcomes[0].target_filename == (
        "16.09.2026_NF 1234 - COMERCIO EXEMPLO LTDA - 1.234,56.pdf"
    )


def test_a_note_with_both_files_in_the_batch_is_copied_once(tmp_path):
    """The printed PDF is the copy; the XML only supplies the name."""
    xml = tmp_path / "in" / "nota.xml"
    write_nfe_xml(xml, nf_number="1234")
    pdf = tmp_path / "in" / "nota.pdf"
    write_danfe(pdf, issuer="INDUSTRIA EXEMPLO LTDA", recipient="COMERCIO EXEMPLO LTDA")

    summary = run_batch([pdf, xml], tmp_path / "out")

    assert summary.total == 2
    assert summary.succeeded == 1
    assert summary.skipped == 1
    assert summary.converted == 0, "the copy kept is the PDF that was already there"
    copy = summary.output_directory / EXPECTED_NAME
    assert copy.read_bytes() == pdf.read_bytes()
    assert summary.outcomes[0].source_type == "pdf"
    assert summary.outcomes[1].failure_code is FailureCode.DUPLICATE_NOTE


def test_the_xml_names_the_copy_when_the_two_disagree(tmp_path):
    """The XML is structured; the page is what somebody printed. They can differ."""
    xml = tmp_path / "in" / "nota.xml"
    write_nfe_xml(xml, nf_number="1234", issuer="INDUSTRIA DO XML LTDA")
    pdf = tmp_path / "in" / "nota.pdf"
    write_danfe(pdf, issuer="INDUSTRIA DO PDF LTDA")

    summary = run_batch([pdf, xml], tmp_path / "out")

    outcome = summary.outcomes[0]
    assert outcome.target_filename == (
        "16.09.2026_NF 1234 - INDUSTRIA DO XML LTDA - 1.234,56.pdf"
    )
    sentences = [warning.sentence() for warning in outcome.warnings]
    assert any("Issuer differs" in sentence for sentence in sentences), sentences
    assert any("The value from the XML" in sentence for sentence in sentences), sentences


def test_a_pdf_that_cannot_be_read_leaves_its_xml_to_make_the_copy(tmp_path):
    xml = tmp_path / "in" / "nota.xml"
    write_nfe_xml(xml, nf_number="1234")
    broken = tmp_path / "in" / "nota.pdf"
    broken.write_bytes(b"not a pdf at all")

    summary = run_batch([broken, xml], tmp_path / "out")

    assert [outcome.failure_code for outcome in summary.outcomes] == [
        FailureCode.PDF_READ_ERROR,
        None,
    ]
    assert summary.succeeded == 1
    assert summary.converted == 1, "the XML made the copy the PDF could not"
    assert (summary.output_directory / EXPECTED_NAME).exists()


def test_two_notes_of_different_kinds_are_both_copied(tmp_path):
    """What the 'both' input mode is for: one folder, PDFs and XMLs together."""
    pdf = tmp_path / "in" / "ja-impressa.pdf"
    write_danfe(pdf, nf_number="9999", issuer="INDUSTRIA EXEMPLO LTDA")
    xml = tmp_path / "in" / "recebida.xml"
    write_nfe_xml(xml, nf_number="1234")

    summary = run_batch([pdf, xml], tmp_path / "out")

    assert summary.succeeded == 2
    assert summary.converted == 1, "only the one made from an XML"
    assert (summary.output_directory / EXPECTED_NAME).exists()
    assert (summary.output_directory / "16.09.2026_NF 9999 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf").exists()


def test_a_dry_run_names_what_it_would_have_written(tmp_path):
    source = tmp_path / "in" / "nota.xml"
    write_nfe_xml(source, nf_number="1234")
    output_root = tmp_path / "out"

    summary = run_batch([source], output_root, copy_files=False)

    outcome = summary.outcomes[0]
    assert summary.succeeded == 1
    assert outcome.target_filename == EXPECTED_NAME
    assert outcome.generated is False, "nothing was rendered"
    assert outcome.destination_path is None
    assert not output_root.exists()


def test_an_analysis_carries_what_the_next_stage_needs(tmp_path):
    """The rescue renders from the analysis, so the analysis has to carry it."""
    source = tmp_path / "in" / "nota.xml"
    write_nfe_xml(source, nf_number="1234")

    analysis = analyze_xml(source)

    assert analysis.source_kind is SourceKind.XML
    assert analysis.render_xml == source
    assert analysis.model == NFE_MODEL
    assert analysis.record is not None
    assert analysis.output_source is None, "an XML has no PDF to copy until it is rendered"


def test_a_failed_analysis_still_carries_the_model_and_the_xml(tmp_path):
    """Which is what lets a file that cannot be named keep its PDF."""
    source = tmp_path / "in" / "sem-destinatario.xml"
    write_nfe_xml(source, nf_number="1234", recipient="")

    analysis = analyze_xml(source, name_source=NameSource.RECIPIENT)

    assert analysis.outcome.failure_code is FailureCode.RECIPIENT_NOT_FOUND
    assert analysis.model == NFE_MODEL
    assert analysis.render_xml == source
    assert analysis.record is None


def test_two_notes_that_would_get_the_same_name_keep_both_documents(tmp_path):
    """A collision used to lose the second document; the name cannot be given,
    the PDF still can."""
    first = tmp_path / "in" / "primeira.xml"
    write_nfe_xml(first, nf_number="1234", control="123456789")
    second = tmp_path / "in" / "segunda.xml"
    write_nfe_xml(second, nf_number="1234", control="987654321")

    summary = run_batch([first, second], tmp_path / "out")

    assert summary.succeeded == 1
    assert summary.outcomes[1].failure_code is FailureCode.OUTPUT_COLLISION
    batch = summary.output_directory
    assert (batch / EXPECTED_NAME).exists()
    assert (batch / "_unrenamed" / "segunda.pdf").exists(), (
        "two different notes must not become one document"
    )


def test_a_copy_that_leaves_a_file_behind_says_so_in_the_warnings(
    tmp_path, monkeypatch
):
    """A folder holding a partial copy is the one thing it must not do silently."""
    from app.core import pipeline
    from app.core.filesystem import OutputWriteError
    from app.core.wording import Detail, DetailCode

    def fail_and_leave_a_file(source, destination, **kwargs):
        raise OutputWriteError(
            Detail(
                DetailCode.COPY_FAILED,
                {"destination": str(destination), "error": "held by a scanner"},
            ),
            Detail(
                DetailCode.LEFTOVER,
                {"path": str(destination), "error": "still held by a scanner"},
            ),
        )

    monkeypatch.setattr(pipeline, "copy_into_batch", fail_and_leave_a_file)
    source = tmp_path / "in" / "nota.pdf"
    write_danfe(source)

    summary = run_batch([source], tmp_path / "out")

    outcome = summary.outcomes[0]
    assert outcome.failure_code is FailureCode.OUTPUT_WRITE_ERROR
    assert [warning.code for warning in outcome.warnings] == [DetailCode.LEFTOVER]
    assert str(tmp_path / "out") in outcome.warnings[0].sentence()


def test_a_note_the_sefaz_did_not_authorize_is_left_without_a_pdf(tmp_path):
    """There is no DANFE to keep for a note that was never authorized.

    The reminder of the boundary: an XML this application cannot vouch for does
    not get a document made from it, however readable the XML is.
    """
    source = tmp_path / "in" / "cancelada.xml"
    write_nfe_xml(source, nf_number="1234", status="101")

    summary = run_batch([source], tmp_path / "out")

    outcome = summary.outcomes[0]
    assert outcome.failure_code is FailureCode.XML_NOT_AUTHORIZED
    assert outcome.destination_path is None
    assert not (summary.output_directory / "_unrenamed").exists()


@pytest.mark.parametrize("name", ["nota.XML", "NOTA.XML"])
def test_the_suffix_is_read_whatever_its_case(tmp_path, name):
    source = tmp_path / "in" / name
    write_nfe_xml(source, nf_number="1234")

    summary = run_batch([source], tmp_path / "out")

    assert summary.succeeded == 1
    assert (summary.output_directory / EXPECTED_NAME).exists()


def test_an_empty_xml_file_is_refused(tmp_path):
    source = tmp_path / "in" / "vazio.xml"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"")

    summary = run_batch([source], tmp_path / "out")

    assert summary.outcomes[0].failure_code is FailureCode.XML_READ_ERROR


def test_an_nfce_without_a_recipient_is_named_after_its_issuer(tmp_path):
    """A coupon issued to nobody in particular is the ordinary NFC-e."""
    import re

    text = make_nfe_xml(nf_number="4321", model=NFCE_MODEL)[0]
    source = _write(tmp_path / "cupom.xml", re.sub(r"<dest>.*?</dest>", "", text, flags=re.S))

    issuer_run = analyze_xml(source)
    recipient_run = analyze_xml(source, name_source=NameSource.RECIPIENT)

    assert issuer_run.outcome.succeeded
    assert issuer_run.outcome.recipient is None
    assert recipient_run.outcome.failure_code is FailureCode.RECIPIENT_NOT_FOUND


def test_a_note_whose_company_name_cannot_be_used_keeps_its_pdf(tmp_path):
    """A name slot that would come out empty is a failure, and the DANFE stays."""
    source = _write(tmp_path / "in" / "sem-nome.xml", _xml(issuer="///"))

    summary = run_batch([source], tmp_path / "out")

    assert summary.outcomes[0].failure_code is FailureCode.INVALID_FILENAME
    assert not list(summary.output_directory.glob("*.pdf")), "nothing was named"
    assert (summary.output_directory / "_unrenamed" / "sem-nome.pdf").exists()


def test_a_recorded_warning_is_a_code_the_table_can_say(tmp_path):
    """A note is recorded as a code, so its sentence has one home in every language."""
    from app.core.wording import Detail, DetailCode, detail

    source = tmp_path / "in" / "homologacao.xml"
    write_nfe_xml(source, nf_number="1234", homologation=True)

    summary = run_batch([source], tmp_path / "out")

    assert summary.outcomes[0].warnings == [Detail(DetailCode.HOMOLOGATION)]
    assert summary.outcomes[0].warnings[0].sentence("pt") == detail(
        DetailCode.HOMOLOGATION, "pt"
    )


def test_the_report_describes_an_xml_row(tmp_path):
    """What a machine reads back about a note that came from an XML."""
    import csv

    from app.reporting.report import CSV_DELIMITER

    source = tmp_path / "in" / "nota.xml"
    key = write_nfe_xml(source, nf_number="1234")

    summary = run_batch([source], tmp_path / "out")

    with summary.report_paths["csv"].open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle, delimiter=CSV_DELIMITER))
    assert row["source_filename"] == "nota.xml"
    assert row["status"] == "success"
    assert row["source_type"] == "xml"
    assert row["document_model"] == "55"
    assert row["parser"] == "nfe_xml"
    assert row["generated"] == "true"
    assert row["failure_code"] == ""
    assert row["emission_date"] == "16.09.2026"
    assert row["access_key"] == " ".join(
        key[index : index + 4] for index in range(0, 44, 4)
    )
    assert row["output_file"] == row["target_filename"] == EXPECTED_NAME
