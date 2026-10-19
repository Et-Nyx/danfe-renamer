"""Command-line entry point: the same batch, driven from a shell."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import build_parser, main
from app.core.models import InputKind, NameSource

from .fixtures.danfe_builder import write_danfe

ISSUER_NAME = "16.09.2026_NF 1234 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf"
RECIPIENT_NAME = "16.09.2026_NF 1234 - COMERCIO EXEMPLO LTDA - 1.234,56.pdf"


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