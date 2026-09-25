"""GUI tests: strings, settings, summary text and the batch flow.

The window itself is only built when Tk can start on this machine; the tests
that need it are skipped otherwise, so the suite still runs on a bare server.
Windows are withdrawn and dialog boxes are replaced by recorders, because a test
run must never pop something up on whoever's desktop is running it.
"""

from __future__ import annotations

import json
import time

import pytest

from app.core.models import FailureCode, Status
from app.gui import app_window, settings as settings_module
from app.gui.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    STRINGS,
    Translator,
    summarise,
)

from .fixtures.danfe_builder import write_danfe


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
        started_at=None,  # type: ignore[arg-type]
        finished_at=None,  # type: ignore[arg-type]
        outcomes=[
            FileOutcome(source_path=None, status=Status.SUCCESS),  # type: ignore[arg-type]
            FileOutcome(
                source_path=None,  # type: ignore[arg-type]
                status=Status.SKIPPED,
                failure_code=FailureCode.TOTAL_VALUE_NOT_FOUND,
                reason="VALOR TOTAL DA NOTA not found",
            ),
        ],
    )
    english = summarise(summary, Translator("en"))
    portuguese = summarise(summary, Translator("pt"))
    assert english.analyzed == "2 files analyzed"
    assert english.skipped == "1 skipped"
    assert portuguese.analyzed == "2 arquivos analisados"
    assert portuguese.failures[0][1] == 1
    assert "VALOR TOTAL DA NOTA" in portuguese.failures[0][0]


@pytest.fixture
def window(monkeypatch, tmp_path):
    """A real window, in a temporary settings directory."""
    tk = pytest.importorskip("tkinter")
    monkeypatch.setattr(settings_module, "settings_directory", lambda: tmp_path)
    from app.gui.app_window import build_window

    try:
        built = build_window()
    except tk.TclError as exc:  # pragma: no cover - no display available
        pytest.skip(f"Tk cannot start here: {exc}")
    built.root.withdraw()
    yield built
    built._close_details()
    built.root.destroy()


def test_window_starts_in_english_and_switches_language(window):
    assert window.root.title() == "DANFE Renamer"
    assert window.process_button.cget("text") == "Process Files"

    window.translate.set_language("pt")
    window.root.update()
    assert window.root.title() == "Renomeador de DANFE"
    assert window.process_button.cget("text") == "Processar arquivos"
    assert set(LANGUAGE_NAMES) == set(STRINGS)


def test_window_processes_a_batch_end_to_end(window, tmp_path):
    """The GUI path must produce renamed copies through the same pipeline."""
    source = tmp_path / "in" / "nota.pdf"
    write_danfe(source)
    window._add_sources([source])
    assert len(window.selected) == 1

    window.start_processing()
    deadline = time.time() + 30
    while window.summary is None and time.time() < deadline:
        window._drain_events()
        window.root.update()
        time.sleep(0.02)

    assert window.summary is not None, "the batch never finished"
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


def test_window_reports_why_a_file_was_skipped(window, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    window._add_sources([broken])
    window.start_processing()

    deadline = time.time() + 30
    while window.summary is None and time.time() < deadline:
        window._drain_events()
        window.root.update()
        time.sleep(0.02)

    assert window.summary is not None
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
