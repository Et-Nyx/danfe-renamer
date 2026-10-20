"""Every sentence the application says about a batch, in every language.

A failure is recorded as a stable :class:`~app.core.models.FailureCode`, never as
prose. This is the only place that turns a code into a sentence, so the window,
the CSV, the JSON and the HTML report all say the same thing in the language they
were asked for.

It holds more than failures because more than one surface prints the same lines:
the window's counts and the report's summary are one sentence each, and two copies
of a translation drift apart. Window-only text (buttons, labels, the drop hint)
stays in :mod:`app.gui.i18n`, which merges :data:`SUMMARY` in.

The tables are keyed by the codes' string values rather than by the enum, so this
module imports nothing from :mod:`~app.core.models` and that module can use it.
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "en"

#: One sentence per failure code, describing what could not be done.
MESSAGES: dict[str, dict[str, str]] = {
    "UNSUPPORTED_FORMAT": {
        "en": "Could not identify a supported DANFE layout",
        "pt": "Não foi possível identificar um leiaute de DANFE",
    },
    "AMBIGUOUS_FORMAT": {
        "en": "More than one DANFE layout matched this document",
        "pt": "Mais de um leiaute de DANFE corresponde a este documento",
    },
    "MISSING_ACCESS_KEY": {
        "en": "NF-e access key not found",
        "pt": "Chave de acesso da NF-e não encontrada",
    },
    "ACCESS_KEY_AMBIGUOUS": {
        "en": "More than one access key found in the document",
        "pt": "Mais de uma chave de acesso no documento",
    },
    "INVALID_ACCESS_KEY": {
        "en": "Access key is not valid",
        "pt": "Chave de acesso inválida",
    },
    "NF_NUMBER_INVALID": {
        "en": "NF number could not be derived from the access key",
        "pt": "Não foi possível obter o número da NF pela chave de acesso",
    },
    "NF_NUMBER_CONFLICT": {
        "en": "Printed NF number disagrees with the access key",
        "pt": "O número da NF impresso não confere com a chave de acesso",
    },
    "EMISSION_DATE_NOT_FOUND": {
        "en": "Emission date not found",
        "pt": "Data de emissão não encontrada",
    },
    "EMISSION_DATE_CONFLICT": {
        "en": "Emission date disagrees with the access key",
        "pt": "A data de emissão não confere com a chave de acesso",
    },
    "TOTAL_VALUE_NOT_FOUND": {
        "en": "VALOR TOTAL DA NOTA not found",
        "pt": "VALOR TOTAL DA NOTA não encontrado",
    },
    "TOTAL_VALUE_AMBIGUOUS": {
        "en": "Total value is ambiguous or implausible",
        "pt": "Valor total ambíguo ou implausível",
    },
    "ISSUER_NOT_FOUND": {
        "en": "Issuer name could not be identified confidently",
        "pt": "Não foi possível identificar o emitente com segurança",
    },
    "RECIPIENT_NOT_FOUND": {
        "en": "Recipient name could not be identified confidently",
        "pt": "Não foi possível identificar o destinatário com segurança",
    },
    "INVALID_FILENAME": {
        "en": "Generated filename is not usable on Windows",
        "pt": "O nome de arquivo gerado não é válido no Windows",
    },
    "DUPLICATE_NOTE": {
        "en": "This note is already in the batch under another name",
        "pt": "Esta nota já está no lote com outro nome",
    },
    "OUTPUT_COLLISION": {
        "en": "Output filename already exists",
        "pt": "Já existe um arquivo com o nome de saída",
    },
    "OUTPUT_WRITE_ERROR": {
        "en": "Could not write the renamed copy",
        "pt": "Não foi possível escrever a cópia renomeada",
    },
    "PDF_READ_ERROR": {
        "en": "PDF could not be read",
        "pt": "Não foi possível ler o PDF",
    },
    "PDF_ENCRYPTED": {
        "en": "PDF is password protected",
        "pt": "O PDF tem senha de proteção",
    },
    "PDF_GENERATION_ERROR": {
        "en": "PDF could not be generated from the XML",
        "pt": "Não foi possível gerar o PDF a partir do XML",
    },
    "XML_READ_ERROR": {
        "en": "XML could not be read",
        "pt": "Não foi possível ler o XML",
    },
    "XML_UNSUPPORTED": {
        "en": "XML is not an NF-e or NFC-e document",
        "pt": "O XML não é um documento NF-e ou NFC-e",
    },
    "XML_NOT_AUTHORIZED": {
        "en": "XML does not carry an authorized NF-e/NFC-e",
        "pt": "O XML não contém uma NF-e/NFC-e autorizada",
    },
    "UNEXPECTED_EXTRACTION_ERROR": {
        "en": "Unexpected error while reading the document",
        "pt": "Erro inesperado ao ler o documento",
    },
}

#: Notes a document carries without failing: still the reader's language.
NOTES: dict[str, dict[str, str]] = {
    "homologation": {
        "en": "Homologation XML (tpAmb=2); it has no fiscal value",
        "pt": "XML de homologação (tpAmb=2); não tem valor fiscal",
    },
    "nf_number_from_key": {
        "en": "NF number read from the access key; ide/nNF is missing",
        "pt": "Número da NF lido da chave de acesso; ide/nNF ausente",
    },
    "no_protocol": {
        "en": "XML has no authorization protocol; the data was read from the NFe",
        "pt": "O XML não tem protocolo de autorização; os dados foram lidos da NFe",
    },
    "protocol_without_cstat": {
        "en": "XML protocol has no cStat; authorization is unconfirmed",
        "pt": "O protocolo do XML não tem cStat; a autorização não foi confirmada",
    },
}

#: How many files a batch got through. The window and the report both print these.
#: ``_one`` is the singular; a language that does not inflect leaves it out and the
#: plural wording is used for every count.
SUMMARY: dict[str, dict[str, str]] = {
    "en": {
        "analyzed": "{count} files analyzed",
        "analyzed_one": "{count} file analyzed",
        "renamed": "{count} renamed successfully",
        "renamed_one": "{count} renamed successfully",
        "converted": "{count} converted from XML",
        "converted_one": "{count} converted from XML",
        "skipped": "{count} skipped",
        "skipped_one": "{count} skipped",
        "errors": "{count} errors",
        "errors_one": "{count} error",
    },
    "pt": {
        "analyzed": "{count} arquivos analisados",
        "analyzed_one": "{count} arquivo analisado",
        "renamed": "{count} renomeados com sucesso",
        "renamed_one": "{count} renomeado com sucesso",
        "converted": "{count} convertidos de XML",
        "converted_one": "{count} convertido de XML",
        "skipped": "{count} ignorados",
        "skipped_one": "{count} ignorado",
        "errors": "{count} erros",
        "errors_one": "{count} erro",
    },
}

#: What one file's outcome is called on a report line.
STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "success": "renamed",
        "generated": "converted",
        "skipped": "skipped",
        "error": "error",
    },
    "pt": {
        "success": "renomeado",
        "generated": "convertido",
        "skipped": "ignorado",
        "error": "erro",
    },
}

#: The report's own headings, which the window never shows.
REPORT: dict[str, dict[str, str]] = {
    "en": {
        "title": "DANFE renamer - batch report",
        "heading": "DANFE renamer - batch report",
        "application": "DANFE Renamer {version}",
        "started": "Started: {when}",
        "finished": "Finished: {when}",
        "failures_heading": "Failures by reason",
        "no_failures": "No failures.",
        "column_source": "Source file",
        "column_status": "Status",
        "column_target": "New name",
        "column_reason": "Reason",
    },
    "pt": {
        "title": "Relatório do lote - Renomeador de DANFE",
        "heading": "Relatório do lote - Renomeador de DANFE",
        "application": "Renomeador de DANFE {version}",
        "started": "Início: {when}",
        "finished": "Término: {when}",
        "failures_heading": "Motivos das falhas",
        "no_failures": "Nenhuma falha.",
        "column_source": "Arquivo original",
        "column_status": "Situação",
        "column_target": "Novo nome",
        "column_reason": "Motivo",
    },
}

#: Every language a caller may ask for.
LANGUAGES = tuple(REPORT)


def _code_name(code: object) -> str:
    """A :class:`FailureCode` or its plain string, as the string the tables use."""
    return str(getattr(code, "value", code))


def _pick(table: dict[str, str], language: str) -> str:
    return table.get(language) or table[DEFAULT_LANGUAGE]


def message(code: object, language: str = DEFAULT_LANGUAGE) -> str:
    """What went wrong, as a sentence in ``language``.

    An unknown code comes back as the code itself: a failure never reaches the
    user as a sentence about nothing.
    """
    name = _code_name(code)
    table = MESSAGES.get(name)
    return name if table is None else _pick(table, language)


def note(key: str, language: str = DEFAULT_LANGUAGE) -> str:
    """A recorded note, as a sentence in ``language``."""
    table = NOTES.get(key)
    return key if table is None else _pick(table, language)


def counted(key: str, count: int, language: str = DEFAULT_LANGUAGE) -> str:
    """A count line, singular when the language has a singular for it."""
    table = SUMMARY.get(language) or SUMMARY[DEFAULT_LANGUAGE]
    if count == 1 and f"{key}_one" in table:
        return table[f"{key}_one"].format(count=count)
    if key not in table:
        return f"{count} {key}"
    return table[key].format(count=count)


def status_label(
    status: object, language: str = DEFAULT_LANGUAGE, *, generated: bool = False
) -> str:
    """What one file's outcome is called on a report line."""
    name = _code_name(status)
    if generated and name == "success":
        name = "generated"
    table = STATUS_LABELS.get(language) or STATUS_LABELS[DEFAULT_LANGUAGE]
    return table.get(name) or name


def report(key: str, language: str = DEFAULT_LANGUAGE, **values) -> str:
    """One of the report's own headings, filled in."""
    table = REPORT.get(language) or REPORT[DEFAULT_LANGUAGE]
    template = table.get(key) or REPORT[DEFAULT_LANGUAGE][key]
    return template.format(**values) if values else template
