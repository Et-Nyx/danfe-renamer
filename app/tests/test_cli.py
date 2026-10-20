"""Command-line entry point: the same batch, driven from a shell."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import build_parser, collect_sources, main
from app.core.models import InputKind, NameSource
from app.gui import settings as settings_module

from .fixtures.danfe_builder import write_danfe, write_nfe_xml

ISSUER_NAME = "16.09.2026_NF 1234 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf"
RECIPIENT_NAME = "16.09.2026_NF 1234 - COMERCIO EXEMPLO LTDA - 1.234,56.pdf"


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """The command line reads the language saved in the window.

    A test must not depend on - or write to - the machine it runs on, so the
    settings directory is a temporary one, which says English until it is told
    otherwise.
    """
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "in" / "nota.pdf"
    write_danfe(
        path, issuer="INDUSTRIA EXEMPLO LTDA", recipient="COMERCIO EXEMPLO LTDA"
    )
    return path


def _batch_directory(output_root: Path) -> Path:
    """The one timestamped directory a run creates under the output root."""
    batches = [path for path in output_root.iterdir() if path.is_dir()]
    assert len(batches) == 1, batches
    return batches[0]


def test_the_choice_defaults_to_the_issuer():
    assert build_parser().parse_args([]).name_source == NameSource.EMITENTE.value


def test_the_input_defaults_to_xml():
    assert build_parser().parse_args([]).input == InputKind.XML.value


def test_an_unknown_choice_is_refused():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--name-source", "cliente"])


def test_the_cli_converts_xmls_by_default(tmp_path):
    """The command line reads XMLs without being told to; that is its default."""
    source = tmp_path / "in" / "nota.xml"
    write_nfe_xml(source, nf_number="1234")
    output = tmp_path / "out"

    assert main([str(source), "--output", str(output)]) == 0

    batch = _batch_directory(output)
    assert (batch / ISSUER_NAME).exists()
    assert not list(batch.glob("*.xml")), "the XML is read, never copied"
    assert source.exists()


def test_the_cli_exits_one_when_a_note_cannot_be_named(tmp_path):
    """A scheduled task has to tell a clean run from one with a file left over."""
    good = tmp_path / "in" / "nota.xml"
    write_nfe_xml(good, nf_number="1234")
    refused = tmp_path / "in" / "sem-destinatario.xml"
    write_nfe_xml(refused, nf_number="1235", recipient="")
    output = tmp_path / "out"

    code = main(
        [
            str(tmp_path / "in"),
            "--output",
            str(output),
            "--name-source",
            "destinatario",
        ]
    )

    assert code == 1
    batch = _batch_directory(output)
    assert (batch / RECIPIENT_NAME).exists()
    assert (batch / "_unrenamed" / "sem-destinatario.pdf").exists(), (
        "the file that could not be named keeps its PDF"
    )


def test_the_cli_says_what_it_looked_for_when_it_finds_nothing(tmp_path, capsys):
    empty = tmp_path / "vazia"
    empty.mkdir()

    for kind, expected in (
        ("xml", "No XML files found."),
        ("pdf", "No PDF files found."),
        ("both", "No XML or PDF files found."),
    ):
        assert main([str(empty), "--input", kind]) == 1
        message = capsys.readouterr().err.strip()
        assert message == expected, message


def test_the_cli_says_it_in_the_chosen_language(tmp_path, capsys):
    """The console lines are read by whoever reads the reports."""
    empty = tmp_path / "vazia"
    empty.mkdir()

    assert main([str(empty), "--input", "both", "--language", "pt"]) == 1

    assert capsys.readouterr().err.strip() == "Nenhum arquivo XML ou PDF encontrado."


def test_the_cli_prints_the_counts_the_reports_print(tmp_path, capsys):
    """One table of counts, so the console cannot say something else."""
    source = tmp_path / "in" / "nota.xml"
    write_nfe_xml(source, nf_number="1234")

    code = main(
        [str(source), "--output", str(tmp_path / "out"), "--language", "pt"]
    )

    assert code == 0
    printed = capsys.readouterr().out
    assert "1 arquivo analisado" in printed
    assert "1 renomeado com sucesso" in printed
    assert "1 convertido de XML" in printed
    assert "1 erro" not in printed, """no sentence about failures that did not happen"""
    assert "Saída: " in printed
    assert "Relatório (csv): " in printed


def test_the_cli_says_a_dry_run_wrote_nothing(tmp_path, capsys):
    """The counts say what the run found; only this line says it wrote nothing."""
    source = tmp_path / "in" / "nota.xml"
    write_nfe_xml(source, nf_number="1234")
    output = tmp_path / "out"

    assert main([str(source), "--dry-run", "--output", str(output)]) == 0

    printed = capsys.readouterr().out
    assert printed.splitlines()[0] == (
        "Dry run: the counts below say what would be written; nothing was."
    )
    assert not output.exists()


def test_the_folder_a_batch_is_written_into_is_not_an_input(tmp_path):
    """A run must not read the copies it made last time back in."""
    folder = tmp_path / "notas"
    write_nfe_xml(folder / "nota.xml", nf_number="1234")
    old_batch = folder / "DANFE_Renamed" / "2026-09-25_13-51-02"
    old_batch.mkdir(parents=True)
    (old_batch / ISSUER_NAME).write_bytes(b"%PDF-1.4 a copy from a previous run")

    found = collect_sources([folder], [], input_kind=InputKind.BOTH)

    assert [path.name for path in found] == ["nota.xml"]


def test_pointing_at_the_output_folder_itself_still_reads_it(tmp_path):
    """It is only left out while scanning a folder that contains it."""
    output = tmp_path / "DANFE_Renamed"
    batch = output / "2026-09-25_13-51-02"
    batch.mkdir(parents=True)
    copy = batch / ISSUER_NAME
    copy.write_bytes(b"%PDF-1.4 a copy from a previous run")

    found = collect_sources([output], [], input_kind=InputKind.PDF)

    assert found == [copy], "an added folder is always read"


def test_the_cli_names_the_copies_after_the_issuer(tmp_path):
    source = _source(tmp_path)
    output = tmp_path / "out"

    assert main([str(source), "--output", str(output), "--input", "pdf"]) == 0

    batch = _batch_directory(output)
    assert (batch / ISSUER_NAME).exists()
    assert not (batch / RECIPIENT_NAME).exists()


def test_the_cli_can_name_the_copies_after_the_recipient(tmp_path):
    source = _source(tmp_path)
    output = tmp_path / "out"

    code = main(
        [
            str(source),
            "--output",
            str(output),
            "--name-source",
            "destinatario",
            "--input",
            "pdf",
        ]
    )

    assert code == 0
    batch = _batch_directory(output)
    assert (batch / RECIPIENT_NAME).exists()
    assert not (batch / ISSUER_NAME).exists()
    # The report says what the names were built from, and keeps both names.
    csv_text = (batch / "batch_report.csv").read_text(encoding="utf-8-sig")
    assert "destinatario" in csv_text
    assert "COMERCIO EXEMPLO LTDA" in csv_text
    assert "INDUSTRIA EXEMPLO LTDA" in csv_text