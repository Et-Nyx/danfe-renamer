"""Interface strings, in English (default) and Portuguese.

Every piece of text the window shows comes from here, so adding a language is
adding a dictionary. Keys are shared across both dictionaries; a test asserts
that, so a missing translation cannot reach the user as a raw key.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.models import InputKind, NameSource

DEFAULT_LANGUAGE = "en"

#: Language code -> the name shown in the selector, written in that language.
LANGUAGE_NAMES = {
    "en": "English",
    "pt": "Português",
}

#: Each name source and the string that labels it, so the selector, the details
#: pane and the reports all speak about the choice the same way.
NAME_SOURCE_KEYS = {
    NameSource.EMITENTE: "name_source_emitente",
    NameSource.RECIPIENT: "name_source_recipient",
}

#: Each input kind and the string that labels it in the window.
INPUT_KIND_KEYS = {
    InputKind.XML: "input_xml",
    InputKind.PDF: "input_pdf",
    InputKind.BOTH: "input_both",
}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "window_title": "DANFE Renamer",
        "headline": "DANFE Renamer",
        "subtitle": "Rename DANFE/NF-e PDFs into copies with the agreed name pattern.",
        "language_label": "Language",
        "input_label": "Input files",
        "input_xml": "XML — convert and rename",
        "input_pdf": "PDF — rename only",
        "input_both": "XML + PDF",
        "name_source_label": "Name in the file name",
        "name_source_emitente": "Issuer — Incoming Note",
        "name_source_recipient": "Recipient — Outgoing Note",
        "drop_hint": "Drop your XML/PDF files here, or choose files or a folder.",
        "drop_hint_buttons": "Choose the XML/PDF files or the folder to process.",
        "choose_files": "Choose PDFs",
        "choose_folder": "Choose Folder",
        "remove_selected": "Remove selected",
        "clear_list": "Clear list",
        "process": "Process Files",
        "processing": "Processing",
        "of": "of",
        "safety_note": "Originals are never modified.",
        "selected_files": "{count} file(s) selected",
        "no_files": "No files selected yet.",
        "no_files_alert": "Choose the PDF files or the folder you want to process first.",
        "report_title": "Batch finished",
        "analyzed": "{count} files analyzed",
        "renamed": "{count} renamed successfully",
        "converted": "{count} converted from XML",
        "skipped": "{count} skipped",
        "errors": "{count} errors",
        "failures_by_reason": "Why files were skipped",
        "open_output": "Open output folder",
        "view_details": "View details",
        "process_another": "Process another batch",
        "details_title": "Details",
        "column_source": "Original file",
        "column_status": "Status",
        "column_target": "New name",
        "column_reason": "Reason",
        "status_success": "renamed",
        "status_generated": "converted",
        "status_skipped": "skipped",
        "status_error": "error",
        "technical_details": "Technical details",
        "field_parser": "Layout read by",
        "field_source_type": "Source type",
        "field_model": "Document model",
        "field_generated": "PDF generated",
        "yes": "yes",
        "no": "no",
        "field_access_key": "Access key",
        "field_nf_number": "NF number",
        "field_date": "Emission date",
        "field_value": "VALOR TOTAL DA NOTA",
        "field_issuer": "Issuer",
        "field_recipient": "Recipient",
        "field_destination": "Copied to",
        "field_warnings": "Notes",
        "field_duration": "Took",
        "select_row_hint": "Select a file to see its details.",
        "seconds": "{value:.2f} s",
        "close": "Close",
        "error_title": "Something went wrong",
        "report_open_failed": "The output folder could not be opened: {error}",
        "all_good": "Every file was renamed.",
        "output_directory": "Output: {path}",
        "unknown_language": "Language {code!r} is not available.",
    },
    "pt": {
        "window_title": "Renomeador de DANFE",
        "headline": "Renomeador de DANFE",
        "subtitle": "Renomeia PDFs de DANFE/NF-e em cópias com o padrão de nome combinado.",
        "language_label": "Idioma",
        "input_label": "Arquivos de entrada",
        "input_xml": "XML — converter e renomear",
        "input_pdf": "PDF — apenas renomear",
        "input_both": "XML + PDF",
        "name_source_label": "Nome no arquivo",
        "name_source_emitente": "Emitente — Nota de Entrada",
        "name_source_recipient": "Destinatário — Nota de Saída",
        "drop_hint": "Arraste os XMLs/PDFs para cá, ou escolha arquivos ou uma pasta.",
        "drop_hint_buttons": "Escolha os XMLs/PDFs ou a pasta que deseja processar.",
        "choose_files": "Escolher PDFs",
        "choose_folder": "Escolher pasta",
        "remove_selected": "Remover selecionados",
        "clear_list": "Limpar lista",
        "process": "Processar arquivos",
        "processing": "Processando",
        "of": "de",
        "safety_note": "Os arquivos originais nunca são modificados.",
        "selected_files": "{count} arquivo(s) selecionado(s)",
        "no_files": "Nenhum arquivo selecionado ainda.",
        "no_files_alert": "Escolha primeiro os PDFs ou a pasta que deseja processar.",
        "report_title": "Lote concluído",
        "analyzed": "{count} arquivos analisados",
        "renamed": "{count} renomeados com sucesso",
        "converted": "{count} convertidos de XML",
        "skipped": "{count} ignorados",
        "errors": "{count} erros",
        "failures_by_reason": "Motivos dos arquivos ignorados",
        "open_output": "Abrir pasta de saída",
        "view_details": "Ver detalhes",
        "process_another": "Processar outro lote",
        "details_title": "Detalhes",
        "column_source": "Arquivo original",
        "column_status": "Situação",
        "column_target": "Novo nome",
        "column_reason": "Motivo",
        "status_success": "renomeado",
        "status_generated": "convertido",
        "status_skipped": "ignorado",
        "status_error": "erro",
        "technical_details": "Detalhes técnicos",
        "field_parser": "Leiaute lido",
        "field_source_type": "Tipo de origem",
        "field_model": "Modelo do documento",
        "field_generated": "PDF gerado",
        "yes": "sim",
        "no": "não",
        "field_access_key": "Chave de acesso",
        "field_nf_number": "Número da NF",
        "field_date": "Data de emissão",
        "field_value": "VALOR TOTAL DA NOTA",
        "field_issuer": "Emitente",
        "field_recipient": "Destinatário",
        "field_destination": "Copiado para",
        "field_warnings": "Observações",
        "field_duration": "Levou",
        "select_row_hint": "Selecione um arquivo para ver os detalhes.",
        "seconds": "{value:.2f} s",
        "close": "Fechar",
        "error_title": "Algo deu errado",
        "report_open_failed": "Não foi possível abrir a pasta de saída: {error}",
        "all_good": "Todos os arquivos foram renomeados.",
        "output_directory": "Saída: {path}",
        "unknown_language": "O idioma {code!r} não está disponível.",
    },
}


class Translator:
    """Holds the current language and looks strings up in it."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self.language = language if language in STRINGS else DEFAULT_LANGUAGE
        self._listeners: list = []

    def set_language(self, language: str) -> None:
        """Switch language and notify everything that has to redraw."""
        if language not in STRINGS:
            raise KeyError(STRINGS[DEFAULT_LANGUAGE]["unknown_language"].format(code=language))
        if language == self.language:
            return
        self.language = language
        for listener in list(self._listeners):
            listener()

    def subscribe(self, listener) -> None:
        """Register a callback to run after every language change."""
        self._listeners.append(listener)

    def __call__(self, key: str, **values) -> str:
        """Look up ``key`` in the current language, filling in any placeholders."""
        template = STRINGS[self.language].get(key) or STRINGS[DEFAULT_LANGUAGE][key]
        return template.format(**values) if values else template


@dataclass(frozen=True)
class SummaryText:
    """The outcome lines shown after a batch, already translated."""

    analyzed: str
    renamed: str
    converted: str
    skipped: str
    errors: str
    failures: tuple[tuple[str, int], ...]


def summarise(summary, translate: Translator) -> SummaryText:
    """Turn a :class:`~app.core.models.BatchSummary` into displayable lines."""
    failures = ()
    if summary.skipped or summary.errors:
        failures = tuple(
            (translate_failure(code, translate), count)
            for code, count in summary.failures_by_code().items()
        )
    return SummaryText(
        analyzed=translate("analyzed", count=summary.total),
        renamed=translate("renamed", count=summary.succeeded),
        converted=translate("converted", count=summary.converted),
        skipped=translate("skipped", count=summary.skipped),
        errors=translate("errors", count=summary.errors),
        failures=failures,
    )


def translate_failure(code, translate: Translator) -> str:
    """A failure code as a sentence the user can act on.

    The codes are stable and identical in every language; the message the parser
    recorded is what gets shown, so a failure never appears as a bare code.
    """
    from ..core.models import FAILURE_MESSAGES

    return FAILURE_MESSAGES.get(code, translate("errors", count=1))


def describe_name_source(value, translate: Translator) -> str:
    """A record's stored ``name_source`` value as the label the selector shows."""
    try:
        source = NameSource(value)
    except ValueError:
        return str(value) if value else "-"
    return translate(NAME_SOURCE_KEYS[source])
