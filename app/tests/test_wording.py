"""The sentences about a batch, and the promise that they exist in every language.

A failure is recorded as a code and a detail code, never as prose, so these
tables are the only place a sentence reaches the user from. A code without a
sentence in some language would reach them as a bare code, which is what the
window and the reports must never show.
"""

from __future__ import annotations

import re

import pytest

from app.core.models import FailureCode
from app.core.wording import (
    CONSOLE,
    DEFAULT_LANGUAGE,
    DETAILS,
    LANGUAGES,
    MESSAGES,
    REPORT,
    STATUS_LABELS,
    SUMMARY,
    DetailCode,
    counted,
    detail,
    message,
    report,
    status_label,
)
from app.gui.i18n import STRINGS, Translator


def test_every_language_says_every_failure_code():
    for code in FailureCode:
        table = MESSAGES.get(code.value)
        assert table, f"{code.value} has no sentence at all"
        for language in LANGUAGES:
            assert table.get(language, "").strip(), f"{language} is missing {code.value}"


def test_every_table_holds_the_same_keys_in_every_language():
    """A language added to one table has to be added to all of them."""
    # Keyed by language first: every language needs every key.
    for name, table in (
        ("SUMMARY", SUMMARY),
        ("STATUS_LABELS", STATUS_LABELS),
        ("REPORT", REPORT),
        ("CONSOLE", CONSOLE),
    ):
        for language, entries in table.items():
            assert set(entries) == set(table[DEFAULT_LANGUAGE]), f"{name}.{language}"
    # Keyed by code first: every entry needs every language.
    for name, table in (
        ("MESSAGES", MESSAGES),
        ("DETAILS", DETAILS),
    ):
        for key, entries in table.items():
            assert set(entries) == set(LANGUAGES), f"{name}.{key}"


def test_a_failure_code_says_what_went_wrong_in_the_readers_language():
    assert message(FailureCode.TOTAL_VALUE_NOT_FOUND, "en") == (
        "VALOR TOTAL DA NOTA not found"
    )
    assert message(FailureCode.TOTAL_VALUE_NOT_FOUND, "pt") == (
        "VALOR TOTAL DA NOTA não encontrado"
    )
    assert message(FailureCode.OUTPUT_WRITE_ERROR, "pt") == (
        "Não foi possível escrever a cópia renomeada"
    )


def test_an_unknown_code_comes_back_as_the_code_not_as_a_sentence():
    """Half a sentence is worse than a code: a code at least identifies itself."""
    assert message("SOMETHING_NEW", "pt") == "SOMETHING_NEW"
    assert detail("SOMETHING_NEW", "pt") == "SOMETHING_NEW"
    assert detail("SOMETHING_NEW", "pt", path="x") == "SOMETHING_NEW (path=x)"
    assert status_label("something_new", "pt") == "something_new"


def test_every_detail_code_has_a_frame_in_every_language():
    """A layer records the code; this table has to be able to say it."""
    for code in DetailCode:
        table = DETAILS.get(code.value)
        assert table, f"{code.value} has no frame at all"
        for language in LANGUAGES:
            assert table.get(language, "").strip(), f"{language} is missing {code.value}"


def test_a_detail_is_a_sentence_with_its_values_filled_in():
    assert detail(DetailCode.PDF_OPEN_FAILED, "en", error="cannot open it") == (
        "Could not open the PDF: cannot open it"
    )
    assert detail(DetailCode.PDF_OPEN_FAILED, "pt", error="cannot open it") == (
        "Não foi possível abrir o PDF: cannot open it"
    )
    assert detail(DetailCode.PDF_NO_PAGES, "pt") == "O PDF não tem páginas"


def test_a_details_placeholders_match_between_languages():
    """A frame that forgot {error} would render a sentence about nothing."""
    pattern = re.compile(r"\{(\w+)")
    for code, entries in DETAILS.items():
        english = set(pattern.findall(entries[DEFAULT_LANGUAGE]))
        for language in LANGUAGES:
            assert set(pattern.findall(entries[language])) == english, (
                f"{code}.{language}"
            )


def test_the_console_placeholders_match_between_languages():
    pattern = re.compile(r"\{(\w+)")
    for language, entries in CONSOLE.items():
        for key, frame in entries.items():
            assert set(pattern.findall(frame)) == set(
                pattern.findall(CONSOLE[DEFAULT_LANGUAGE][key])
            ), f"{language}.{key}"


def test_a_count_uses_the_singular_when_there_is_one():
    assert counted("errors", 1, "pt") == "1 erro"
    assert counted("errors", 2, "pt") == "2 erros"
    assert counted("analyzed", 1, "en") == "1 file analyzed"
    assert status_label("success", "pt") == "renomeado"
    assert status_label("success", "en", generated=True) == "converted"


def test_the_console_says_what_the_window_says():
    """One table of counts: the console cannot drift from the reports."""
    for language in LANGUAGES:
        translate = Translator(language)
        for key in ("analyzed", "renamed", "converted", "skipped", "errors"):
            for count in (0, 1, 2, 33):
                assert translate(key, count=count) == counted(key, count, language), (
                    f"{language}.{key} at {count}"
                )


def test_the_window_table_carries_the_shared_counts():
    for language, table in STRINGS.items():
        for key in SUMMARY[language]:
            assert key in table, f"{language}.{key} was not merged in"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_report_heading_is_filled_in(language):
    written = report("application", language, version="1.3.1")
    assert "1.3.1" in written
    assert "{version}" not in written
    assert "DANFE" in written
