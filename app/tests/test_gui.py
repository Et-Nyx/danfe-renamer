"""GUI tests: strings, settings, summary text and the batch flow.

The window itself is only built when Tk can start on this machine; the tests
that need it are skipped otherwise, so the suite still runs on a bare server.
Windows are withdrawn and dialog boxes are replaced by recorders, because a test
run must never pop something up on whoever's desktop is running it.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.models import FailureCode, FileOutcome, InputKind, NameSource, Status
from app.core.wording import Detail, DetailCode
from app.gui import app_window, settings as settings_module
from app.gui.app_window import split_dropped_paths
from app.gui.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    STRINGS,
    Translator,
    summarise,
)

from .fixtures.danfe_builder import write_danfe, write_nfe_xml


def test_every_string_exists_in_every_language():
    english = set(STRINGS[DEFAULT_LANGUAGE])
    for code, table in STRINGS.items():
        assert set(table) == english, f"{code} is missing {english - set(table)}"
        for key, value in table.items():
            assert value.strip(), f"{code}.{key} is empty"


def test_placeholders_match_between_languages():
    import re

    pattern = re.compile(r"\{(\w+)")
    for key, english in STRINGS[DEFAULT_LANGUAGE].items():
        expected = set(pattern.findall(english))
        for code, table in STRINGS.items():
            assert set(pattern.findall(table[key])) == expected, f"{code}.{key}"


def test_translator_switches_and_notifies():
    translator = Translator("en")
    seen = []
    translator.subscribe(lambda: seen.append(translator.language))
    assert translator("process") == "Process Files"
    translator.set_language("pt")
    assert translator("process") == "Processar arquivos"
    assert seen == ["pt"]


def test_translator_rejects_an_unknown_language():
    with pytest.raises(KeyError):
        Translator("en").set_language("de")


def test_unknown_saved_language_falls_back_to_english(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    (tmp_path / "settings.json").write_text('{"language": "kl"}', encoding="utf-8")
    assert settings_module.load_language() == DEFAULT_LANGUAGE


def test_language_choice_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    settings_module.save_language("pt")
    assert settings_module.load_language() == "pt"
    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert stored["language"] == "pt"
    assert "notas" not in json.dumps(stored).lower(), "settings hold preferences only"


def test_settings_survive_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    (tmp_path / "settings.json").write_text("not json at all", encoding="utf-8")
    assert settings_module.load_language() == DEFAULT_LANGUAGE


def test_summary_text_is_in_the_selected_language():
    from app.core.models import BatchSummary, FileOutcome

    summary = BatchSummary(
        started_at=datetime(2026, 10, 20, 11, 0, 0),
        finished_at=datetime(2026, 10, 20, 11, 0, 12),
        outcomes=[
            FileOutcome(source_path=None, status=Status.SUCCESS),  # type: ignore[arg-type]
            FileOutcome(
                source_path=None,  # type: ignore[arg-type]
                status=Status.SKIPPED,
                failure_code=FailureCode.TOTAL_VALUE_NOT_FOUND,
            ),
        ],
    )
    english = summarise(summary, Translator("en"))
    portuguese = summarise(summary, Translator("pt"))
    assert english.analyzed == "2 files analyzed"
    assert english.converted == "0 converted from XML"
    assert english.skipped == "1 skipped"
    assert portuguese.analyzed == "2 arquivos analisados"
    assert portuguese.converted == "0 convertidos de XML"
    assert portuguese.failures[0][1] == 1
    assert "VALOR TOTAL DA NOTA" in portuguese.failures[0][0]


# ------------------------------------------------- what the summary is saying
#
# The window's own counts are how a person checks that nothing was lost. A batch
# of 33 files that renamed 32 and skipped 0 could not be accounted for, because
# the line saying one had failed was squeezed out of the window and the heading
# over the reasons talked about skips.


COUNT_KEYS = ("analyzed", "renamed", "converted", "skipped", "errors", "selected_files")


def summary_of(total: int, *, errors: int = 0, skipped: int = 0, seconds: float = 12.4):
    """A batch of ``total`` files, of which the named ones did not succeed."""
    from app.core.models import BatchSummary, FileOutcome

    good = total - errors - skipped
    outcomes = [
        FileOutcome(source_path=Path(f"n{i}.xml"), status=Status.SUCCESS, generated=True,
                    destination_path=Path(f"out{i}.pdf"))
        for i in range(good)
    ]
    outcomes += [
        FileOutcome(source_path=Path(f"e{i}.xml"), status=Status.ERROR,
                    failure_code=FailureCode.OUTPUT_WRITE_ERROR)
        for i in range(errors)
    ]
    outcomes += [
        FileOutcome(source_path=Path(f"s{i}.xml"), status=Status.SKIPPED,
                    failure_code=FailureCode.TOTAL_VALUE_NOT_FOUND)
        for i in range(skipped)
    ]
    return BatchSummary(
        started_at=datetime(2026, 10, 20, 11, 0, 0),
        finished_at=datetime(2026, 10, 20, 11, 0, 0) + timedelta(seconds=seconds),
        outcomes=outcomes,
    )


def test_every_count_says_one_in_every_language():
    """A key used with a count needs its singular, or "1 erros" reaches the user."""
    for code, table in STRINGS.items():
        for key in COUNT_KEYS:
            assert f"{key}_one" in table, f"{code}.{key} has no singular"


def test_one_of_anything_is_written_in_the_singular():
    assert Translator("pt")("errors", count=1) == "1 erro"
    assert Translator("pt")("errors", count=2) == "2 erros"
    assert Translator("pt")("analyzed", count=1) == "1 arquivo analisado"
    assert Translator("pt")("skipped", count=0) == "0 ignorados"
    assert Translator("en")("errors", count=1) == "1 error"
    assert Translator("en")("analyzed", count=1) == "1 file analyzed"
    assert Translator("en")("selected_files", count=1) == "1 file selected"


def test_the_three_things_the_window_counted_add_up():
    """Analyzed = renamed + skipped + errors, the way the lines read."""
    window = Translator("pt")
    summary = summary_of(33, errors=1)
    lines = summarise(summary, window)
    assert lines.analyzed == "33 arquivos analisados"
    assert lines.renamed == "32 renomeados com sucesso"
    assert lines.skipped == "0 ignorados"
    assert lines.errors == "1 erro", "the line that accounts for the missing file"


def test_an_error_is_never_headed_as_a_skip():
    """"0 ignorados" above "why files were skipped" is the contradiction."""
    for translate in (Translator("en"), Translator("pt")):
        headed = summarise(summary_of(33, errors=1), translate)
        assert "skipped" not in headed.failure_heading.lower()
        assert "ignorados" not in headed.failure_heading

        only_skips = summarise(summary_of(2, skipped=1), translate)
        assert "skipped" in only_skips.failure_heading.lower() or (
            "ignorados" in only_skips.failure_heading
        )


def test_the_heading_covers_both_kinds_when_both_happened():
    translate = Translator("pt")
    headed = summarise(summary_of(4, errors=1, skipped=1), translate)
    assert headed.failure_heading == translate("failures_mixed")
    assert "ignorados" in headed.failure_heading
    assert "erro" in headed.failure_heading


def test_the_summary_says_how_long_the_batch_took():
    """A run that finishes in seconds should read as fast, not as skipped work."""
    assert "12.4" in summarise(summary_of(4, seconds=12.4), Translator("pt")).duration
    assert "12.4" in summarise(summary_of(4, seconds=12.4), Translator("en")).duration


@pytest.fixture(scope="session")
def shared_root():
    """The one Tk root for the whole test session.

    Tcl does not survive having interpreters created and destroyed repeatedly, so
    every window in this file is built on this root instead of making its own.
    """
    tk = pytest.importorskip("tkinter")
    from app.gui.app_window import create_root

    try:
        root = create_root()
    except tk.TclError as exc:  # pragma: no cover - no display available
        pytest.skip(f"Tk cannot start here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def window(shared_root, monkeypatch, tmp_path):
    """A window on the shared root, in a temporary settings directory."""
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    from app.gui.app_window import RenamerWindow, require_tkdnd

    built = RenamerWindow(shared_root, dnd_available=require_tkdnd(shared_root))
    yield built
    built._close_details()


def test_the_environment_report_has_the_facts_a_support_request_needs():
    """No window is built here: one process, one Tk root.

    The window probe is exercised by the release check, which runs the packaged
    executable's --diagnostics in its own process.
    """
    from app.cli import collect_diagnostics

    found = collect_diagnostics(probe_window=False)

    assert found["application"].startswith("DANFE Renamer ")
    assert found["tkinter"].startswith("Tk"), found["tkinter"]
    assert found["pymupdf"] != "unknown"
    assert "window" not in found, "the probe is opt-in"
    if app_window.HAS_DND:  # pragma: no cover - depends on the machine
        assert "drag_and_drop" not in found or "not installed" not in found["drag_and_drop"]
    else:
        assert "not installed" in found["drag_and_drop"]


def test_diagnostics_are_written_to_a_file(tmp_path):
    from app.cli import report_diagnostics

    written = report_diagnostics(tmp_path, probe_window=False)

    assert written == tmp_path / "danfe_renamer_diagnostics.txt"
    text = written.read_text(encoding="utf-8")
    assert "application: DANFE Renamer" in text
    assert "tkinter: Tk" in text
    assert "drag_and_drop:" in text


def run_window_batch(window, timeout: float = 30) -> None:
    """Start a batch and pump the Tk loop until the window has its summary."""
    window.start_processing()
    deadline = time.time() + timeout
    while window.summary is None and time.time() < deadline:
        window._drain_events()
        window.root.update()
        time.sleep(0.02)
    assert window.summary is not None, "the batch never finished"


def test_window_starts_in_english_and_switches_language(window):
    from app import __version__

    assert window.root.title() == f"DANFE Renamer {__version__}"
    assert window.process_button.cget("text") == "Process Files"

    window.translate.set_language("pt")
    window.root.update()
    assert window.root.title() == f"Renomeador de DANFE {__version__}"
    assert window.process_button.cget("text") == "Processar arquivos"
    assert set(LANGUAGE_NAMES) == set(STRINGS)


def test_window_processes_a_batch_end_to_end(window, tmp_path):
    """The GUI path must produce renamed copies through the same pipeline."""
    source = tmp_path / "in" / "nota.pdf"
    write_danfe(source)
    window.input_kind_buttons[InputKind.PDF].invoke()
    window._add_sources([source])
    assert len(window.selected) == 1

    run_window_batch(window)

    assert window.summary.succeeded == 1
    assert window.summary.errors == 0
    expected = (
        window.summary.output_directory
        / "16.09.2026_NF 1234 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf"
    )
    assert expected.exists()
    assert source.exists(), "the original must still be there"

    window.show_details()
    window.root.update()
    assert window.details_window is not None
    window._close_details()


def test_window_converts_xmls_in_the_mode_it_opens_in(window, tmp_path):
    """XML is the main workflow: the window reads it without being switched to."""
    source = tmp_path / "in" / "nota.xml"
    write_nfe_xml(source, nf_number="1234")
    window._add_sources([source])
    assert len(window.selected) == 1, "no input-kind button was touched"

    run_window_batch(window)

    assert window.input_kind is InputKind.XML
    assert window.summary.succeeded == 1
    assert window.summary.converted == 1
    expected = (
        window.summary.output_directory
        / "16.09.2026_NF 1234 - INDUSTRIA EXEMPLO LTDA - 1.234,56.pdf"
    )
    assert expected.exists()
    assert source.exists(), "the original XML must still be there"


def test_the_window_hands_over_the_pdf_of_a_note_it_could_not_name(window, tmp_path):
    """The whole point of the filter: a failure with a document behind it."""
    from app.gui.app_window import DetailsFilter

    source = tmp_path / "in" / "sem-destinatario.xml"
    write_nfe_xml(source, nf_number="1234", recipient="")
    window.name_source_buttons[NameSource.RECIPIENT].invoke()
    window._add_sources([source])

    run_window_batch(window)

    outcome = window.summary.outcomes[0]
    kept = window.summary.output_directory / "_unrenamed" / "sem-destinatario.pdf"
    assert outcome.status is Status.SKIPPED
    assert outcome.destination_path == kept
    assert kept.exists()

    window.show_details()
    window.root.update()
    window.filter_buttons[DetailsFilter.FAILED].invoke()
    window.details_table.selection_set(window.details_table.get_children())
    window.root.update()

    assert window.filter_count_label.cget("text") == "1 of 1 files"
    assert window.open_copy_button.cget("text") == "Open PDF (not renamed)"
    assert "disabled" not in window.open_copy_button.state()
    window._close_details()


def test_a_folder_added_again_does_not_bring_the_copies_back(window, tmp_path):
    """The batch folder lives inside the input folder; it is not an input.

    Adding the same folder twice used to select the PDFs the previous run had
    just written, so a second batch copied the first one's output.
    """
    folder = tmp_path / "notas"
    source = folder / "nota.pdf"
    write_danfe(source)
    window.input_kind_buttons[InputKind.PDF].invoke()
    window._add_sources([folder])
    run_window_batch(window)
    copy = window.summary.outcomes[0].destination_path
    assert copy.exists()

    window.clear_list()
    window._add_sources([folder])

    assert window.selected == [source], "the run's own output is not an input"


def test_window_reports_why_a_file_was_skipped(window, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    window.input_kind_buttons[InputKind.PDF].invoke()
    window._add_sources([broken])
    run_window_batch(window)

    assert window.summary.skipped == 1
    assert window.failure_label.cget("text").strip()
    assert "PDF could not be read" in window.failure_label.cget("text")


def test_window_refuses_to_start_without_files(window, monkeypatch):
    """An empty selection must not start a batch; the user is told why."""
    shown = []
    monkeypatch.setattr(
        app_window.messagebox,
        "showinfo",
        lambda *args, **kwargs: shown.append(args),
    )
    assert window.selected == []
    window.start_processing()
    assert window.summary is None
    assert shown, "the user has to be told that nothing was selected"
    assert shown[0][1] == window.translate("no_files_alert")


# ---------------------------------------------------------------- name source


def test_the_window_starts_in_xml_mode(window):
    """XML is the main workflow; PDF remains a selectable option."""
    assert window.input_kind is InputKind.XML
    assert window.input_kind_var.get() == InputKind.XML.value
    assert window.input_kind_buttons[InputKind.XML].cget("text") == (
        "XML — convert and rename"
    )
    assert window.input_kind_buttons[InputKind.PDF].cget("text") == (
        "PDF — rename only"
    )


def test_the_input_kind_choice_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    assert settings_module.load_input_kind() is InputKind.XML
    settings_module.save_input_kind(InputKind.PDF)
    assert settings_module.load_input_kind() is InputKind.PDF
    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert stored["input_kind"] == "pdf"


def test_an_unknown_saved_input_kind_falls_back_to_xml(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(
        '{"input_kind": "docx"}', encoding="utf-8"
    )
    assert settings_module.load_input_kind() is InputKind.XML


def test_the_window_starts_naming_files_after_the_issuer(window):
    assert window.name_source is NameSource.EMITENTE
    assert window.name_source_var.get() == NameSource.EMITENTE.value
    assert window.name_source_buttons[NameSource.EMITENTE].cget("text").startswith("Issuer")
    assert window.name_source_buttons[NameSource.RECIPIENT].cget("text") == (
        "Recipient — Outgoing Note"
    )


def test_the_name_source_labels_follow_the_language(window):
    window.translate.set_language("pt")
    window.root.update()

    assert window.name_source_label.cget("text") == "Nome no arquivo"
    assert window.name_source_buttons[NameSource.EMITENTE].cget("text") == (
        "Emitente — Nota de Entrada"
    )
    assert window.name_source_buttons[NameSource.RECIPIENT].cget("text") == (
        "Destinatário — Nota de Saída"
    )


def test_the_name_source_choice_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)

    assert settings_module.load_name_source() is NameSource.EMITENTE
    settings_module.save_name_source(NameSource.RECIPIENT)

    assert settings_module.load_name_source() is NameSource.RECIPIENT
    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert stored["name_source"] == "destinatario"


def test_an_unknown_saved_name_source_falls_back_to_the_issuer(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    (tmp_path / "settings.json").write_text('{"name_source": "destinatario "}', encoding="utf-8")
    assert settings_module.load_name_source() is NameSource.EMITENTE


def test_the_two_preferences_do_not_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    settings_module.save_language("pt")
    settings_module.save_name_source(NameSource.RECIPIENT)
    assert settings_module.load_language() == "pt"
    assert settings_module.load_name_source() is NameSource.RECIPIENT


def test_a_radio_click_remembers_the_choice(window):
    assert settings_module.load_name_source() is NameSource.EMITENTE

    window.name_source_buttons[NameSource.RECIPIENT].invoke()

    assert window.name_source is NameSource.RECIPIENT
    assert settings_module.load_name_source() is NameSource.RECIPIENT


def test_a_batch_from_the_window_can_be_named_after_the_recipient(window, tmp_path):
    source = tmp_path / "in" / "nota.pdf"
    write_danfe(source, issuer="INDUSTRIA EXEMPLO LTDA", recipient="COMERCIO EXEMPLO LTDA")
    window.input_kind_buttons[InputKind.PDF].invoke()
    window.name_source_buttons[NameSource.RECIPIENT].invoke()
    window._add_sources([source])

    run_window_batch(window)

    assert window.summary.succeeded == 1
    expected = (
        window.summary.output_directory
        / "16.09.2026_NF 1234 - COMERCIO EXEMPLO LTDA - 1.234,56.pdf"
    )
    assert expected.exists()
    assert source.exists(), "the original must still be there"


def test_the_details_pane_shows_both_names_and_the_choice(window, tmp_path):
    source = tmp_path / "in" / "nota.pdf"
    write_danfe(source, issuer="INDUSTRIA EXEMPLO LTDA", recipient="COMERCIO EXEMPLO LTDA")
    window.input_kind_buttons[InputKind.PDF].invoke()
    window.name_source_buttons[NameSource.RECIPIENT].invoke()
    window._add_sources([source])
    run_window_batch(window)

    window.show_details()
    window.root.update()
    window.details_table.selection_set("0")
    window.root.update()
    text = window.detail_contents()

    assert "Recipient — Outgoing Note" in text, text
    assert "INDUSTRIA EXEMPLO LTDA" in text, "both names are shown"
    assert "COMERCIO EXEMPLO LTDA" in text


# --------------------------------------------------- acting on a failed file
#
# A file that failed has to be reachable from the window that names it: opened,
# found in its folder, its name copied into a message. Reading about it is not
# enough, and neither is a pane that cannot be selected or copied.


@pytest.fixture
def clipboard(window, monkeypatch):
    """Records what would be copied, so a test run never takes the real clipboard."""
    written: list[str] = []
    monkeypatch.setattr(window.root, "clipboard_clear", lambda: written.clear())
    monkeypatch.setattr(window.root, "clipboard_append", written.append)
    return written


def failing_batch(window, tmp_path, names):
    """Run the window over files that cannot be read, so every row fails."""
    window.input_kind_buttons[InputKind.PDF].invoke()
    sources = []
    for name in names:
        path = tmp_path / "in" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not a pdf")
        sources.append(path)
    window._add_sources(sources)
    run_window_batch(window)
    assert window.summary.errors + window.summary.skipped == len(names)
    return sources


def open_details(window, rows):
    """Open the details window and select the given rows."""
    window.show_details()
    window.root.update()
    window.details_table.selection_set(tuple(str(row) for row in rows))
    window.root.update()


def test_the_details_pane_names_the_file_and_what_went_wrong(window, tmp_path):
    """The pane a support request is pasted from leads with the file itself."""
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    shown = window.detail_contents()
    assert "broken.pdf" in shown, shown
    assert str(tmp_path / "in" / "broken.pdf") in shown, "the path comes with the name"
    assert "PDF could not be read" in shown, shown


def test_the_details_pane_is_read_only_text(window, tmp_path):
    """Read-only must not mean inert.

    Tk keeps the selection and the Ctrl+C handler on a disabled ``Text``, which
    is why the pane is one; the label it replaced answered to neither.
    """
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    assert window.detail_text.cget("state") == "disabled", "the user cannot type here"
    assert window.detail_contents().startswith("File: broken.pdf"), "and can read it"


def test_the_reason_is_not_below_the_run_of_empty_fields(window, tmp_path):
    """A file that failed early is mostly dashes; the reason is what is wanted."""
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    head = "\n".join(window.detail_contents().splitlines()[:4])

    assert "PDF could not be read" in head, head


def test_copying_the_details_puts_the_file_and_the_reason_on_the_clipboard(
    window, tmp_path, clipboard
):
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    window.copy_details()

    assert len(clipboard) == 1, "one paste, not one per line"
    assert "broken.pdf" in clipboard[0]
    assert "PDF could not be read" in clipboard[0]


def test_every_selected_failure_can_be_copied_at_once(window, tmp_path, clipboard):
    """Copying the names is how a batch of failures is handed to someone else."""
    failing_batch(window, tmp_path, ["first.pdf", "second.pdf"])
    open_details(window, [0, 1])

    window.copy_selected_names()
    assert clipboard[-1].splitlines() == ["first.pdf", "second.pdf"]

    window.copy_selected_paths()
    assert clipboard[-1].splitlines() == [
        str(tmp_path / "in" / "first.pdf"),
        str(tmp_path / "in" / "second.pdf"),
    ]


def test_the_pane_shows_every_selected_failure_together(window, tmp_path):
    failing_batch(window, tmp_path, ["first.pdf", "second.pdf"])
    open_details(window, [0, 1])

    shown = window.detail_contents()
    assert "first.pdf" in shown and "second.pdf" in shown, shown


def test_nothing_selected_means_nothing_to_act_on(window, tmp_path, clipboard):
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [])

    assert window.detail_contents() == ""
    assert window.detail_text.cget("state") == "disabled"
    for button in (
        window.open_file_button,
        window.open_copy_button,
        window.reveal_button,
        window.copy_name_button,
        window.copy_path_button,
        window.copy_details_button,
    ):
        assert "disabled" in button.state(), button.cget("text")
    window.copy_details()
    window.copy_selected_names()
    assert clipboard == [], "an empty copy is not put on the clipboard"


def test_the_details_pane_opens_the_file_that_failed(window, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(app_window, "open_path", opened.append)
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    window.open_selected_file()

    assert opened == [tmp_path / "in" / "broken.pdf"]


def test_the_details_pane_shows_the_file_where_it_lives(window, tmp_path, monkeypatch):
    revealed = []
    monkeypatch.setattr(app_window, "reveal_path", revealed.append)
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    window.reveal_selected_file()

    assert revealed == [tmp_path / "in" / "broken.pdf"]


def test_opening_acts_on_one_file_even_when_several_are_selected(
    window, tmp_path, monkeypatch
):
    """Copying takes the whole selection; opening must not open a dozen windows."""
    opened = []
    monkeypatch.setattr(app_window, "open_path", opened.append)
    failing_batch(window, tmp_path, ["first.pdf", "second.pdf"])
    open_details(window, [0, 1])

    window.details_table.focus("1")
    window.root.update()
    window.open_selected_file()

    assert opened == [tmp_path / "in" / "second.pdf"], opened


def test_a_file_that_left_is_reported_instead_of_opened(window, tmp_path, monkeypatch):
    """A batch can be looked at later, when the file has already moved."""
    opened = []
    warned = []
    monkeypatch.setattr(app_window, "open_path", opened.append)
    monkeypatch.setattr(
        app_window.messagebox, "showwarning", lambda *args, **kwargs: warned.append(args)
    )
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    (tmp_path / "in" / "broken.pdf").unlink()
    window.open_selected_file()

    assert opened == [], "there is nothing left to open"
    assert warned, "the user has to be told, not left with a button that does nothing"
    assert str(tmp_path / "in" / "broken.pdf") in warned[0][1]


def test_a_desktop_that_refuses_to_open_is_reported(window, tmp_path, monkeypatch):
    def refuse(_path):
        raise OSError("no handler for that kind")

    errors = []
    monkeypatch.setattr(app_window, "open_path", refuse)
    monkeypatch.setattr(
        app_window.messagebox, "showerror", lambda *args, **kwargs: errors.append(args)
    )
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    window.open_selected_file()

    assert errors, "a refused open must not look like nothing happened"
    assert "no handler for that kind" in errors[0][1]


def test_opening_the_copy_is_offered_only_when_the_run_wrote_one(
    window, tmp_path, monkeypatch
):
    """A failed row has no copy; a renamed row does, and it is the useful one."""
    opened = []
    monkeypatch.setattr(app_window, "open_path", opened.append)

    source = tmp_path / "in" / "nota.pdf"
    write_danfe(source)
    broken = tmp_path / "in" / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    window.input_kind_buttons[InputKind.PDF].invoke()
    window._add_sources([broken, source])
    run_window_batch(window)

    outcomes = window.summary.outcomes
    failed = next(i for i, o in enumerate(outcomes) if not o.succeeded)
    renamed = next(i for i, o in enumerate(outcomes) if o.succeeded)
    assert outcomes[renamed].destination_path is not None

    open_details(window, [failed])
    assert "disabled" in window.open_copy_button.state(), "there is no copy to open"

    open_details(window, [renamed])
    assert "disabled" not in window.open_copy_button.state()
    window.open_selected_copy()

    assert opened == [outcomes[renamed].destination_path]


def test_the_details_actions_speak_the_chosen_language(window, tmp_path):
    """Buttons and menu are rebuilt on a language change, like the rest."""
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    assert window.open_file_button.cget("text") == "Open original file"
    assert window.copy_name_button.cget("text") == "Copy name"
    assert window.close_button.cget("text") == "Close"

    window.translate.set_language("pt")
    window.root.update()

    assert window.open_file_button.cget("text") == "Abrir arquivo original"
    assert window.copy_name_button.cget("text") == "Copiar nome"
    assert window.close_button.cget("text") == "Fechar"


def test_the_copy_button_says_which_file_it_will_open(window, tmp_path):
    """A PDF that never got its name is not offered as a renamed copy.

    A file the batch could not name still has a PDF, and the button that opens
    it must not promise a name that is not on it.
    """
    from app.core.models import BatchSummary, FileOutcome

    renamed = FileOutcome(
        source_path=tmp_path / "nota.pdf",
        status=Status.SUCCESS,
        target_filename="16.09.2026_NF 1234 - X - 1.234,56.pdf",
        destination_path=tmp_path / "16.09.2026_NF 1234 - X - 1.234,56.pdf",
    )
    unnamed = FileOutcome(
        source_path=tmp_path / "sem-destinatario.xml",
        status=Status.SKIPPED,
        failure_code=FailureCode.RECIPIENT_NOT_FOUND,
        destination_path=tmp_path / "_unrenamed" / "sem-destinatario.pdf",
        unnamed=True,
    )
    for outcome in (renamed, unnamed):
        outcome.destination_path.parent.mkdir(parents=True, exist_ok=True)
        outcome.destination_path.write_bytes(b"%PDF-1.4")
    window.summary = BatchSummary(
        started_at=datetime(2026, 10, 20, 11, 0, 0),
        finished_at=datetime(2026, 10, 20, 11, 0, 1),
        outcomes=[renamed, unnamed],
    )

    open_details(window, ["0"])
    assert window.open_copy_button.cget("text") == "Open renamed copy"

    open_details(window, ["1"])
    assert window.open_copy_button.cget("text") == "Open PDF (not renamed)"
    assert "disabled" not in window.open_copy_button.state(), "the PDF is there"
    assert window.details_menu.entrycget(1, "label") == "Open PDF (not renamed)", (
        "the menu offers the same action, so it says the same thing"
    )

    open_details(window, ["0"])
    assert window.details_menu.entrycget(1, "label") == "Open renamed copy"


def test_the_context_menu_offers_what_the_buttons_do(window, tmp_path):
    """Right-clicking a row is the shortest way to the same actions."""
    failing_batch(window, tmp_path, ["broken.pdf"])
    open_details(window, [0])

    labels = [
        window.details_menu.entrycget(index, "label")
        for index in range(window.details_menu.index("end") + 1)
        if window.details_menu.type(index) == "command"
    ]

    assert labels == [
        "Open original file",
        "Open renamed copy",
        "Show in folder",
        "Copy name",
        "Copy full path",
        "Copy details",
    ]


def test_the_result_block_is_laid_out_before_the_file_list(window, tmp_path):
    """Tk squeezes whatever it packs last, and the error count is packed here.

    The window can be made shorter than its contents. The file list scrolls; the
    count of failures does not, so the list has to be the one that gives way. With
    the block packed last, "1 error" was the first line to leave the screen.
    """
    source = tmp_path / "in" / "nota.pdf"
    write_danfe(source)
    window.input_kind_buttons[InputKind.PDF].invoke()
    window._add_sources([source])
    run_window_batch(window)

    slaves = window.frame.pack_slaves()
    assert slaves[0] is window.result_frame, "the results are allocated first"
    assert window.result_frame.pack_info()["side"] == "bottom"
    assert "disabled" not in window.details_button.state()


def test_the_result_block_leaves_the_screen_again_for_the_next_batch(window, tmp_path):
    source = tmp_path / "in" / "nota.pdf"
    write_danfe(source)
    window.input_kind_buttons[InputKind.PDF].invoke()
    window._add_sources([source])
    run_window_batch(window)
    assert window.result_frame in window.frame.pack_slaves()

    window.reset_for_next_batch()
    window.root.update()

    assert window.result_frame not in window.frame.pack_slaves()


def test_the_pane_says_why_the_write_failed(window, tmp_path):
    """Every field read fine and the copy still failed: the cause is the answer.

    The recorded reason is the only place it appears - here a file another
    program was holding, which the catalogue sentence does not mention.
    """
    from app.core.models import BatchSummary, FileOutcome

    window.summary = BatchSummary(
        started_at=datetime(2026, 10, 20, 11, 0, 0),
        finished_at=datetime(2026, 10, 20, 11, 0, 1),
        outcomes=[
            FileOutcome(
                source_path=tmp_path / "12333.xml",
                status=Status.ERROR,
                failure_code=FailureCode.OUTPUT_WRITE_ERROR,
                parser_id="nfe_xml",
                source_type="xml",
                issuer="TEMP CLEAN NORDESTE PRODUTOS DE HIGIENE E SANITIZACAO LTDA",
                detail=Detail(
                    DetailCode.COPY_FAILED,
                    {
                        "destination": "C:/out/12333.pdf",
                        "error": "[WinError 32] The process cannot access the file "
                        "because it is being used by another process",
                    },
                ),
            )
        ],
    )
    open_details(window, [0])

    shown = window.detail_contents()
    assert "OUTPUT_WRITE_ERROR" in shown, shown
    assert "WinError 32" in shown, "the cause has to survive to the pane"
    assert "being used by another process" in shown


def test_the_cause_is_built_in_the_readers_language():
    """The layer records a fact; the pane and the reports make it words."""
    outcome = FileOutcome(
        source_path=Path("x.pdf"),
        status=Status.ERROR,
        failure_code=FailureCode.OUTPUT_WRITE_ERROR,
        detail=Detail(
            DetailCode.COPY_FAILED,
            {"destination": "C:/out/x.pdf", "error": "[WinError 32] held"},
        ),
    )

    assert app_window.outcome_cause(outcome, "en") == (
        "Could not copy to C:/out/x.pdf: [WinError 32] held"
    )
    assert app_window.outcome_cause(outcome, "pt") == (
        "Não foi possível copiar para C:/out/x.pdf: [WinError 32] held"
    )
    assert app_window.outcome_cause(outcome, "pt").endswith("[WinError 32] held"), (
        "what Windows said is not translated"
    )
    assert (
        app_window.outcome_cause(
            FileOutcome(source_path=Path("x.pdf"), status=Status.SKIPPED), "en"
        )
        == ""
    ), "a failure the code already explains has no cause of its own"


# --------------------------------------------------- narrowing the details list
#
# A batch is read for two reasons: to find the files that need attention and to
# confirm the ones that went through. One list serves both badly once a run is
# long, so it can be narrowed - and it says how much of the batch it is showing,
# because a list that is quietly shorter reads as files that went missing.


def mixed_batch(window, tmp_path):
    """A batch with one file that was renamed and one that was not."""
    good = tmp_path / "in" / "nota.pdf"
    write_danfe(good)
    broken = tmp_path / "in" / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    window.input_kind_buttons[InputKind.PDF].invoke()
    window._add_sources([broken, good])
    run_window_batch(window)
    assert window.summary.succeeded == 1
    assert window.summary.skipped + window.summary.errors == 1


def shown_rows(window) -> list[str]:
    """The file names the list is showing, in the order it shows them."""
    table = window.details_table
    return [table.item(row, "text") for row in table.get_children()]


def choose_filter(window, choice) -> None:
    """Click one of the filter's radio buttons, the way a person does."""
    window.filter_buttons[choice].invoke()
    window.root.update()


def test_the_details_list_starts_showing_every_file(window, tmp_path):
    mixed_batch(window, tmp_path)
    window.show_details()
    window.root.update()

    assert [button.cget("text") for button in window.filter_buttons.values()] == [
        "All files",
        "Only failures",
        "Only successes",
    ]
    assert window.details_filter is app_window.DetailsFilter.ALL
    assert shown_rows(window) == ["broken.pdf", "nota.pdf"]


def test_only_failures_shows_the_files_that_were_not_renamed(window, tmp_path):
    mixed_batch(window, tmp_path)
    open_details(window, [])

    choose_filter(window, app_window.DetailsFilter.FAILED)

    assert shown_rows(window) == ["broken.pdf"], "a skipped file is one to act on too"


def test_only_successes_shows_the_files_that_were_renamed(window, tmp_path):
    mixed_batch(window, tmp_path)
    open_details(window, [])

    choose_filter(window, app_window.DetailsFilter.SUCCESSFUL)

    assert shown_rows(window) == ["nota.pdf"]


def test_a_narrowed_row_still_points_at_its_own_file(window, tmp_path, monkeypatch):
    """The filter decides what is listed, not what a row stands for."""
    opened = []
    monkeypatch.setattr(app_window, "open_path", opened.append)
    mixed_batch(window, tmp_path)
    open_details(window, [])
    choose_filter(window, app_window.DetailsFilter.SUCCESSFUL)

    window.details_table.selection_set(window.details_table.get_children())
    window.root.update()
    window.open_selected_file()

    renamed = next(outcome for outcome in window.summary.outcomes if outcome.succeeded)
    assert opened == [renamed.source_path]


def test_the_list_says_how_much_of_the_batch_it_is_showing(window, tmp_path):
    mixed_batch(window, tmp_path)
    open_details(window, [])

    assert window.filter_count_label.cget("text") == "2 of 2 files"

    choose_filter(window, app_window.DetailsFilter.FAILED)

    assert window.filter_count_label.cget("text") == "1 of 2 files"


def test_the_filter_and_its_count_speak_the_chosen_language(window, tmp_path):
    mixed_batch(window, tmp_path)
    open_details(window, [])

    window.translate.set_language("pt")
    window.root.update()

    assert window.filter_label.cget("text") == "Mostrar"
    assert [button.cget("text") for button in window.filter_buttons.values()] == [
        "Todos os arquivos",
        "Somente falhas",
        "Somente sucessos",
    ]
    assert window.filter_count_label.cget("text") == "2 de 2 arquivos"


def test_the_chosen_filter_survives_a_language_change(window, tmp_path):
    """A language change rebuilds the window that shows the filter."""
    mixed_batch(window, tmp_path)
    open_details(window, [])
    choose_filter(window, app_window.DetailsFilter.FAILED)

    window.translate.set_language("pt")
    window.root.update()

    assert shown_rows(window) == ["broken.pdf"], "the same rows, in the other language"
    assert window.filter_count_label.cget("text") == "1 de 2 arquivos"


def test_the_filter_row_is_laid_out_before_the_list(window, tmp_path):
    """Tk squeezes whatever it packs last, and this row has no give in it."""
    mixed_batch(window, tmp_path)
    window.show_details()
    window.root.update()

    slaves = window.details_window.pack_slaves()
    assert slaves[0] is window.filter_label.master, "the filter is allocated first"
    assert window.details_table in slaves


def test_processing_another_batch_does_not_leave_the_old_list_open(window, tmp_path):
    """The list describes the batch that just went away, so it goes with it."""
    mixed_batch(window, tmp_path)
    window.show_details()
    window.root.update()

    window.reset_for_next_batch()
    window.root.update()

    assert window.details_table is None
    assert window.details_window is None
    assert window.details_filter is app_window.DetailsFilter.ALL, "a new batch opens whole"


def test_a_skipped_file_is_a_failure_of_the_batch():
    """Both filters are about the batch's two halves, not about three statuses."""
    skipped = FileOutcome(source_path=Path("b.pdf"), status=Status.SKIPPED)
    errored = FileOutcome(source_path=Path("c.pdf"), status=Status.ERROR)
    renamed = FileOutcome(source_path=Path("a.pdf"), status=Status.SUCCESS)
    keeps = app_window.keeps_row

    assert all(
        keeps(outcome, app_window.DetailsFilter.ALL)
        for outcome in (renamed, skipped, errored)
    )
    assert [
        keeps(outcome, app_window.DetailsFilter.FAILED)
        for outcome in (renamed, skipped, errored)
    ] == [False, True, True]
    assert [
        keeps(outcome, app_window.DetailsFilter.SUCCESSFUL)
        for outcome in (renamed, skipped, errored)
    ] == [True, False, False]


def test_revealing_names_the_file_for_the_file_manager(monkeypatch, tmp_path):
    """Explorer parses its own command line, and wants the quotes around the path.

    Handed a list, ``subprocess`` quotes the switch and the path together -
    ``"/select,C:\\a b\\c.pdf"`` - and Explorer answers that by opening its
    default folder instead. Only a path containing a space shows it, which is
    why a batch read from a folder like ``Notas fiscais`` opened Documentos.
    """
    launched = []
    monkeypatch.setattr(app_window.subprocess, "Popen", launched.append)
    monkeypatch.setattr(app_window.sys, "platform", "win32")
    target = tmp_path / "a note with spaces.pdf"
    target.write_bytes(b"%PDF")

    app_window.reveal_path(target)

    assert launched == [f'explorer /select,"{target}"']


def test_revealing_a_file_that_left_opens_its_folder(monkeypatch, tmp_path):
    """The file is gone; the folder it was read from is still worth showing."""
    launched = []
    monkeypatch.setattr(app_window.subprocess, "Popen", launched.append)
    monkeypatch.setattr(app_window.sys, "platform", "win32")
    folder = tmp_path / "Notas fiscais"

    app_window.reveal_path(folder / "gone.pdf")

    assert launched == [f'explorer "{folder}"']


def test_a_relative_path_is_made_the_file_it_means(monkeypatch, tmp_path):
    """Explorer is given an absolute path; a relative one names its own folder."""
    launched = []
    monkeypatch.setattr(app_window.subprocess, "Popen", launched.append)
    monkeypatch.setattr(app_window.sys, "platform", "win32")
    folder = tmp_path / "Notas fiscais"
    folder.mkdir()
    (folder / "nota.xml").write_bytes(b"<x/>")
    monkeypatch.chdir(folder)

    app_window.reveal_path(Path("nota.xml"))

    assert launched == [f'explorer /select,"{folder / "nota.xml"}"']


def test_a_path_needs_quotes_only_when_it_contains_a_space():
    """The quotes go around the path, and a path Explorer reads as one word has none.

    A drive root is the one path ``abspath`` leaves a trailing separator on, and
    a backslash before the closing quote would escape it - so it is never
    quoted. The paths here are absolute and made up, so the rule is the only
    thing the answer depends on.
    """
    command = app_window.explorer_command

    assert command(Path("C:/notas/nota.xml"), select=True) == (
        "explorer /select,C:\\notas\\nota.xml"
    )
    assert command(Path("C:/notas/nota.xml"), select=False) == (
        "explorer C:\\notas\\nota.xml"
    )
    assert command(Path("C:/notas fiscais/nota.xml"), select=True) == (
        'explorer /select,"C:\\notas fiscais\\nota.xml"'
    )
    assert command(Path("C:/"), select=False) == "explorer C:\\"
    assert command(Path("C:/"), select=True) == "explorer /select,C:\\"


def test_opening_hands_the_file_to_the_desktop(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(app_window.os, "startfile", started.append, raising=False)
    monkeypatch.setattr(app_window.sys, "platform", "win32")
    target = tmp_path / "broken.pdf"

    app_window.open_path(target)

    assert started == [target]


# --------------------------------------------------------------- drag and drop


def tcl_list(paths, tcl) -> str:
    """Build a drop payload the way Tk builds one.

    The items go through Tcl's own list builder - the live window's interpreter,
    the one the application itself uses, not a second one it would have to share
    the process with - so the quoting is exactly what a real drop carries rather
    than what a test guesses.
    """
    tcl.eval("set dropped [list]")
    for path in paths:
        tcl.call("lappend", "dropped", str(path))
    return tcl.eval("set dropped")


def test_dropped_paths_survive_a_real_payload(shared_root, tmp_path):
    """Paths with spaces have to survive the round trip."""
    names = ["a.pdf", "nota fiscal 09.09.2026.pdf", "nota de 1,50.pdf"]
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"%PDF-1.4")
        paths.append(path)

    payload = tcl_list(paths, shared_root.tk)

    assert "{" in payload, "Tk quotes an element with spaces"
    assert split_dropped_paths(payload, shared_root.tk.splitlist) == paths


def test_a_path_with_braces_is_repaired_after_the_drop(window, tmp_path):
    """Tcl leaves its brace escaping in the name; the dropped file wins."""
    tricky = tmp_path / "nota {copia} 2.pdf"
    write_danfe(tricky)

    window.input_kind_buttons[InputKind.PDF].invoke()
    window._on_drop(app_window._DropEvent(tcl_list([tricky], window.root.tk)))

    assert [path.name for path in window.selected] == [tricky.name]


def test_a_folder_in_the_payload_is_kept(shared_root, tmp_path):
    folder = tmp_path / "notas fiscais"
    folder.mkdir()
    assert split_dropped_paths(
        tcl_list([folder], shared_root.tk), shared_root.tk.splitlist
    ) == [folder]
    assert split_dropped_paths("", shared_root.tk.splitlist) == []
    assert split_dropped_paths("   ", shared_root.tk.splitlist) == []


def test_a_malformed_payload_still_yields_paths(shared_root):
    """An unbalanced brace must not raise: the whole line is taken at face value.

    A payload that is a valid Tcl list is always taken at Tcl's word: an unquoted
    space really does separate two paths there, so only a payload Tcl rejects is
    read as a raw line.
    """
    single = "C:/notas/uma nota.pdf {C:/notas/aberto.pdf"
    found = split_dropped_paths(single, shared_root.tk.splitlist)
    assert [str(path) for path in found] == [str(Path(single))]


def test_dropping_a_folder_adds_its_pdfs(window, tmp_path):
    """The drop handler adds what the payload names, and skips everything else."""
    folder = tmp_path / "drop"
    folder.mkdir()
    write_danfe(folder / "nota 1.pdf")
    write_danfe(folder / "nota 2.pdf")
    (folder / "leiame.txt").write_text("not a pdf", encoding="utf-8")

    window.input_kind_buttons[InputKind.PDF].invoke()
    window._on_drop(app_window._DropEvent(tcl_list([folder], window.root.tk)))

    assert sorted(path.name for path in window.selected) == ["nota 1.pdf", "nota 2.pdf"]
    assert window.selection_label.cget("text") == "2 files selected"


def test_window_says_when_dropping_is_not_available(shared_root, tmp_path, monkeypatch):
    """Without tkinterdnd2 the buttons still work and the hint tells the truth."""
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    window = app_window.RenamerWindow(shared_root, dnd_available=False)
    try:
        shared_root.update()
        assert window.dnd_available is False
        assert window.drop_hint_label.cget("text") == window.translate("drop_hint_buttons")
        window.translate.set_language("pt")
        shared_root.update()
        assert (
            window.drop_hint_label.cget("text")
            == "Escolha os XMLs/PDFs ou a pasta que deseja processar."
        )
    finally:
        window._close_details()


def test_the_window_offers_dropping_when_the_machine_supports_it(window):
    """On a machine with tkdnd the hint invites a drop and it is registered."""
    if not app_window.HAS_DND:  # pragma: no cover - machine without tkinterdnd2
        pytest.skip("tkinterdnd2 is not installed here")
    assert window.dnd_available is True
    assert window.drop_hint_label.cget("text") == window.translate("drop_hint")


def test_a_root_reports_whether_it_can_use_tkdnd(shared_root):
    """The decision the window makes comes from Tk, not from a guess."""
    available = app_window.require_tkdnd(shared_root)
    assert available is app_window.HAS_DND or available is False
    if app_window.HAS_DND:
        assert available is True
