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

from dataclasses import dataclass, field
from enum import Enum

DEFAULT_LANGUAGE = "en"


class DetailCode(str, Enum):
    """The one fact a layer recorded, beyond the failure's own sentence.

    No layer writes a sentence a person reads: it records one of these and the
    values the frame needs, and whichever surface shows it builds the sentence in
    the language of that reader. Values that came from a library or from Windows
    are evidence - they travel exactly as they arrived and are quoted inside the
    frame, because a ``[WinError 32]`` cannot be translated.

    The frames live in :data:`DETAILS` further down this module.
    """

    # Reading a PDF.
    PDF_OPEN_FAILED = "PDF_OPEN_FAILED"
    PDF_NO_PAGES = "PDF_NO_PAGES"
    PDF_READ_FAILED = "PDF_READ_FAILED"
    # The access key, on a PDF or in an XML.
    KEY_LENGTH = "KEY_LENGTH"
    KEY_CHECK_DIGIT = "KEY_CHECK_DIGIT"
    KEY_NOT_FOUND = "KEY_NOT_FOUND"
    KEY_AMBIGUOUS_ANCHORED = "KEY_AMBIGUOUS_ANCHORED"
    KEY_AMBIGUOUS_ANYWHERE = "KEY_AMBIGUOUS_ANYWHERE"
    KEY_WITHOUT_LABEL = "KEY_WITHOUT_LABEL"
    KEY_NUMBER_UNUSABLE = "KEY_NUMBER_UNUSABLE"
    KEY_NUMBER_CONFLICT = "KEY_NUMBER_CONFLICT"
    REFERENCED_KEYS = "REFERENCED_KEYS"
    # The layout of a printed DANFE.
    LAYOUT_MISSING = "LAYOUT_MISSING"
    LAYOUT_AMBIGUOUS = "LAYOUT_AMBIGUOUS"
    DATE_IMPOSSIBLE = "DATE_IMPOSSIBLE"
    DATE_PRINTED_AS = "DATE_PRINTED_AS"
    DATE_CONFLICT = "DATE_CONFLICT"
    DATE_DISAGREES_WITH_KEY = "DATE_DISAGREES_WITH_KEY"
    TOTAL_CONFLICT = "TOTAL_CONFLICT"
    NUMBER_WITHOUT_LABEL = "NUMBER_WITHOUT_LABEL"
    ISSUER_FROM_RECEIPT = "ISSUER_FROM_RECEIPT"
    ISSUER_DIFFERS = "ISSUER_DIFFERS"
    # Reading an XML.
    XML_READ_FAILED = "XML_READ_FAILED"
    XML_PARSE_FAILED = "XML_PARSE_FAILED"
    XML_SUMMARY = "XML_SUMMARY"
    XML_EVENT = "XML_EVENT"
    XML_NOT_INVOICE = "XML_NOT_INVOICE"
    XML_NO_KEY = "XML_NO_KEY"
    MODEL_UNSUPPORTED = "MODEL_UNSUPPORTED"
    MODEL_DISAGREES = "MODEL_DISAGREES"
    CNPJ_DISAGREES = "CNPJ_DISAGREES"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    NOT_AUTHORIZED_SILENT = "NOT_AUTHORIZED_SILENT"
    PROTOCOL_KEY_DISAGREES = "PROTOCOL_KEY_DISAGREES"
    NO_PROTOCOL = "NO_PROTOCOL"
    PROTOCOL_WITHOUT_CSTAT = "PROTOCOL_WITHOUT_CSTAT"
    HOMOLOGATION = "HOMOLOGATION"
    NUMBER_FROM_KEY = "NUMBER_FROM_KEY"
    # Turning an XML into a PDF.
    RENDER_TARGET_EXISTS = "RENDER_TARGET_EXISTS"
    RENDER_READ_FAILED = "RENDER_READ_FAILED"
    RENDER_MODEL_UNSUPPORTED = "RENDER_MODEL_UNSUPPORTED"
    RENDER_NO_PDF = "RENDER_NO_PDF"
    RENDER_NO_PAGES = "RENDER_NO_PAGES"
    RENDER_UNREADABLE = "RENDER_UNREADABLE"
    # Writing into the batch folder.
    COLLISION_EXISTS = "COLLISION_EXISTS"
    COPY_FAILED = "COPY_FAILED"
    COPY_INCOMPLETE = "COPY_INCOMPLETE"
    LEFTOVER = "LEFTOVER"
    OUTSIDE_BATCH = "OUTSIDE_BATCH"
    NO_BATCH_DIRECTORY = "NO_BATCH_DIRECTORY"
    NAME_ALREADY_PRODUCED = "NAME_ALREADY_PRODUCED"
    # The batch as a whole.
    DUPLICATE_OF = "DUPLICATE_OF"
    ONLY_PDF_AND_XML = "ONLY_PDF_AND_XML"
    PDF_XML_NUMBER_DIFFERS = "PDF_XML_NUMBER_DIFFERS"
    PDF_XML_DATE_DIFFERS = "PDF_XML_DATE_DIFFERS"
    PDF_XML_TOTAL_DIFFERS = "PDF_XML_TOTAL_DIFFERS"
    PDF_XML_ISSUER_DIFFERS = "PDF_XML_ISSUER_DIFFERS"
    PDF_XML_RECIPIENT_DIFFERS = "PDF_XML_RECIPIENT_DIFFERS"
    XML_VALUE_USED = "XML_VALUE_USED"
    # Evidence with no frame of its own.
    EVIDENCE = "EVIDENCE"


@dataclass(frozen=True)
class Detail:
    """What a layer recorded: which fact, and the values its sentence needs."""

    code: DetailCode
    values: dict[str, str] = field(default_factory=dict)

    def sentence(self, language: str = DEFAULT_LANGUAGE) -> str:
        """This detail as a sentence a person reads, in ``language``."""
        return detail(self.code, language, **self.values)

    def __hash__(self) -> int:
        """Two details are the same thing when they say the same thing.

        The batch de-duplicates recorded details, and a ``dict`` of values is not
        hashable on its own.
        """
        return hash((self.code, tuple(sorted(self.values.items()))))

    def __str__(self) -> str:
        """The English sentence, for logs and for test failures."""
        return self.sentence()

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
        "en": "Company name has no characters that can go in a file name",
        "pt": "O nome da empresa não tem caracteres que possam ir no nome do arquivo",
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

#: One frame per :class:`~app.core.models.DetailCode`: what a layer recorded,
#: as a sentence with the values filled in. The frames are what makes a detail
#: readable in the reader's language, and the values that came from a library or
#: from Windows (a pymupdf message, a ``[WinError 32]``) are evidence: they are
#: quoted inside the frame exactly as they arrived.
#:
#: A frame with no sentence of its own is ``{error}`` - the whole detail is the
#: evidence, and translating it would mean inventing words for it.
DETAILS: dict[str, dict[str, str]] = {
    # --- reading a PDF
    "PDF_OPEN_FAILED": {
        "en": "Could not open the PDF: {error}",
        "pt": "Não foi possível abrir o PDF: {error}",
    },
    "PDF_NO_PAGES": {
        "en": "The PDF has no pages",
        "pt": "O PDF não tem páginas",
    },
    "PDF_READ_FAILED": {
        "en": "Could not read the text of the PDF: {error}",
        "pt": "Não foi possível ler o texto do PDF: {error}",
    },
    # --- the access key
    "KEY_LENGTH": {
        "en": "An access key has {expected} digits",
        "pt": "Uma chave de acesso tem {expected} dígitos",
    },
    "KEY_CHECK_DIGIT": {
        "en": "The check digit of the access key does not match",
        "pt": "O dígito verificador da chave de acesso não confere",
    },
    "KEY_NOT_FOUND": {
        "en": "No 44-digit access key found",
        "pt": "Nenhuma chave de acesso de 44 dígitos encontrada",
    },
    "KEY_AMBIGUOUS_ANCHORED": {
        "en": "More than one key next to the key label: {keys}",
        "pt": "Mais de uma chave ao lado do rótulo da chave: {keys}",
    },
    "KEY_AMBIGUOUS_ANYWHERE": {
        "en": "More than one key in the document: {keys}",
        "pt": "Mais de uma chave no documento: {keys}",
    },
    "KEY_WITHOUT_LABEL": {
        "en": "The access key is not next to a CHAVE DE ACESSO label",
        "pt": "A chave de acesso não está ao lado de um rótulo CHAVE DE ACESSO",
    },
    "KEY_NUMBER_UNUSABLE": {
        "en": "The access key carries number {number}",
        "pt": "A chave de acesso traz o número {number}",
    },
    "KEY_NUMBER_CONFLICT": {
        "en": "Printed {printed}, access key {key}",
        "pt": "Impresso {printed}, chave de acesso {key}",
    },
    "REFERENCED_KEYS": {
        "en": "Keys of other notes are present: {keys}",
        "pt": "Chaves de outras notas presentes: {keys}",
    },
    # --- the layout of a printed DANFE
    "LAYOUT_MISSING": {
        "en": "Missing: {signatures}",
        "pt": "Faltando: {signatures}",
    },
    "LAYOUT_AMBIGUOUS": {
        "en": "The layouts that matched: {parsers}",
        "pt": "Os leiautes que corresponderam: {parsers}",
    },
    "DATE_IMPOSSIBLE": {
        "en": "Impossible date '{printed}'",
        "pt": "Data impossível '{printed}'",
    },
    "DATE_PRINTED_AS": {
        "en": "Printed as '{printed}'",
        "pt": "Impresso como '{printed}'",
    },
    "DATE_CONFLICT": {
        "en": "The emission date is printed in more than one way: {values}",
        "pt": "A data de emissão aparece de mais de uma forma: {values}",
    },
    "DATE_DISAGREES_WITH_KEY": {
        "en": "The emission date {printed} does not match the access key {key_period}",
        "pt": "A data de emissão {printed} não confere com a chave de acesso {key_period}",
    },
    "TOTAL_CONFLICT": {
        "en": "VALOR TOTAL DA NOTA is printed with different values: {values}",
        "pt": "VALOR TOTAL DA NOTA aparece com valores diferentes: {values}",
    },
    "NUMBER_WITHOUT_LABEL": {
        "en": "Printed NF number found without a Nº label: {numbers}",
        "pt": "Número da NF impresso sem o rótulo Nº: {numbers}",
    },
    "ISSUER_FROM_RECEIPT": {
        "en": "Issuer read from the receipt phrase, not from the emitente block",
        "pt": "Emitente lido da frase do recibo, não do bloco do emitente",
    },
    "ISSUER_DIFFERS": {
        "en": "The issuer differs between the emitente block and the receipt phrase: '{block}' vs '{phrase}'",
        "pt": "O emitente difere entre o bloco do emitente e a frase do recibo: '{block}' vs '{phrase}'",
    },
    # --- reading an XML
    "XML_READ_FAILED": {
        "en": "Could not read the XML: {error}",
        "pt": "Não foi possível ler o XML: {error}",
    },
    "XML_PARSE_FAILED": {
        "en": "Could not parse the XML: {error}",
        "pt": "Não foi possível interpretar o XML: {error}",
    },
    "XML_SUMMARY": {
        "en": "This is an NF-e summary (resNFe), not an authorized invoice",
        "pt": "Este é um resumo de NF-e (resNFe), não uma nota autorizada",
    },
    "XML_EVENT": {
        "en": "This is an NF-e event, not an invoice",
        "pt": "Este é um evento de NF-e, não uma nota",
    },
    "XML_NOT_INVOICE": {
        "en": "Not an NF-e/NFC-e XML (root element: {root})",
        "pt": "Não é um XML de NF-e/NFC-e (elemento raiz: {root})",
    },
    "XML_NO_KEY": {
        "en": "infNFe has no Id and the protocol has no chNFe",
        "pt": "O infNFe não tem Id e o protocolo não tem chNFe",
    },
    "MODEL_UNSUPPORTED": {
        "en": "Document model {model} is not NF-e (55) or NFC-e (65)",
        "pt": "O modelo do documento {model} não é NF-e (55) nem NFC-e (65)",
    },
    "MODEL_DISAGREES": {
        "en": "Document model {model} disagrees with the access key model {key_model}",
        "pt": "O modelo do documento {model} não confere com o da chave de acesso {key_model}",
    },
    "CNPJ_DISAGREES": {
        "en": "Issuer CNPJ {cnpj} disagrees with the access key {key_cnpj}",
        "pt": "O CNPJ do emitente {cnpj} não confere com o da chave de acesso {key_cnpj}",
    },
    "NOT_AUTHORIZED": {
        "en": "Authorization status {status}: {reason}",
        "pt": "Situação da autorização {status}: {reason}",
    },
    "NOT_AUTHORIZED_SILENT": {
        "en": "Authorization status {status}; the protocol gives no reason",
        "pt": "Situação da autorização {status}; o protocolo não informa o motivo",
    },
    "PROTOCOL_KEY_DISAGREES": {
        "en": "The protocol key disagrees with the infNFe key",
        "pt": "A chave do protocolo não confere com a do infNFe",
    },
    "NO_PROTOCOL": {
        "en": "XML has no authorization protocol; the data was read from the NFe",
        "pt": "O XML não tem protocolo de autorização; os dados foram lidos da NFe",
    },
    "PROTOCOL_WITHOUT_CSTAT": {
        "en": "The protocol has no cStat; authorization is unconfirmed",
        "pt": "O protocolo não tem cStat; a autorização não foi confirmada",
    },
    "HOMOLOGATION": {
        "en": "Homologation XML (tpAmb=2); it has no fiscal value",
        "pt": "XML de homologação (tpAmb=2); não tem valor fiscal",
    },
    "NUMBER_FROM_KEY": {
        "en": "NF number read from the access key; ide/nNF is missing",
        "pt": "Número da NF lido da chave de acesso; ide/nNF ausente",
    },
    # --- turning an XML into a PDF
    "RENDER_TARGET_EXISTS": {
        "en": "{target} already exists",
        "pt": "{target} já existe",
    },
    "RENDER_READ_FAILED": {
        "en": "Could not read {name}: {error}",
        "pt": "Não foi possível ler {name}: {error}",
    },
    "RENDER_MODEL_UNSUPPORTED": {
        "en": "There is no renderer for document model {model}",
        "pt": "Não há gerador para o modelo de documento {model}",
    },
    "RENDER_NO_PDF": {
        "en": "The converter did not produce a PDF",
        "pt": "O conversor não gerou um PDF",
    },
    "RENDER_NO_PAGES": {
        "en": "The generated PDF has no pages",
        "pt": "O PDF gerado não tem páginas",
    },
    "RENDER_UNREADABLE": {
        "en": "The generated PDF could not be read: {error}",
        "pt": "Não foi possível ler o PDF gerado: {error}",
    },
    # --- writing into the batch folder
    "COLLISION_EXISTS": {
        "en": "{name} already exists",
        "pt": "{name} já existe",
    },
    "COPY_FAILED": {
        "en": "Could not copy to {destination}: {error}",
        "pt": "Não foi possível copiar para {destination}: {error}",
    },
    "COPY_INCOMPLETE": {
        "en": "The copy is not the whole file: {written} bytes of {expected}",
        "pt": "A cópia não é o arquivo inteiro: {written} bytes de {expected}",
    },
    "LEFTOVER": {
        "en": "{path} is still there and could not be removed: {error}",
        "pt": "{path} continua lá e não pôde ser removido: {error}",
    },
    "OUTSIDE_BATCH": {
        "en": "{path} is outside the batch folder {directory}",
        "pt": "{path} está fora da pasta do lote {directory}",
    },
    "NO_BATCH_DIRECTORY": {
        "en": "There is no batch folder to write the generated PDF into",
        "pt": "Não há pasta de lote para gravar o PDF gerado",
    },
    "NAME_ALREADY_PRODUCED": {
        "en": "The name was already produced by {name} in this run",
        "pt": "O nome já foi gerado por {name} nesta execução",
    },
    # --- the batch as a whole
    "DUPLICATE_OF": {
        "en": "The same note as {name}, already in this batch",
        "pt": "A mesma nota que {name}, já neste lote",
    },
    "ONLY_PDF_AND_XML": {
        "en": "Only PDF and XML files are read",
        "pt": "Só arquivos PDF e XML são lidos",
    },
    "PDF_XML_NUMBER_DIFFERS": {
        "en": "NF number differs (PDF {pdf}, XML {xml})",
        "pt": "O número da NF difere (PDF {pdf}, XML {xml})",
    },
    "PDF_XML_DATE_DIFFERS": {
        "en": "Emission date differs (PDF {pdf}, XML {xml})",
        "pt": "A data de emissão difere (PDF {pdf}, XML {xml})",
    },
    "PDF_XML_TOTAL_DIFFERS": {
        "en": "Total value differs (PDF {pdf}, XML {xml})",
        "pt": "O valor total difere (PDF {pdf}, XML {xml})",
    },
    "PDF_XML_ISSUER_DIFFERS": {
        "en": "Issuer differs (PDF {pdf}, XML {xml})",
        "pt": "O emitente difere (PDF {pdf}, XML {xml})",
    },
    "PDF_XML_RECIPIENT_DIFFERS": {
        "en": "Recipient differs (PDF {pdf}, XML {xml})",
        "pt": "O destinatário difere (PDF {pdf}, XML {xml})",
    },
    "XML_VALUE_USED": {
        "en": "The value from the XML is used in the file name",
        "pt": "O valor do XML é usado no nome do arquivo",
    },
    # --- evidence, with no frame of its own
    "EVIDENCE": {
        "en": "{error}",
        "pt": "{error}",
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
        "column_output": "Output file",
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
        "column_output": "Arquivo de saída",
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


#: What the command line prints. Its counts and failure sentences are the shared
#: ones, so only the lines with no window equivalent live here.
CONSOLE: dict[str, dict[str, str]] = {
    "en": {
        "nothing_to_do": "Nothing to do: give one or more XML/PDF files or folders.",
        "dry_run": "Dry run: the counts below say what would be written; nothing was.",
        "no_files_xml": "No XML files found.",
        "no_files_pdf": "No PDF files found.",
        "no_files_both": "No XML or PDF files found.",
        "processing": "Processing {index} of {total}...",
        "output": "Output: {path}",
        "report": "Report ({kind}): {path}",
        "also_written": "Reports also written to: {path}",
    },
    "pt": {
        "nothing_to_do": "Nada a fazer: informe um ou mais arquivos XML/PDF ou pastas.",
        "dry_run": "Simulação: as contagens abaixo dizem o que seria gravado; nada foi.",
        "no_files_xml": "Nenhum arquivo XML encontrado.",
        "no_files_pdf": "Nenhum arquivo PDF encontrado.",
        "no_files_both": "Nenhum arquivo XML ou PDF encontrado.",
        "processing": "Processando {index} de {total}...",
        "output": "Saída: {path}",
        "report": "Relatório ({kind}): {path}",
        "also_written": "Relatórios também gravados em: {path}",
    },
}


def console(key: str, language: str = DEFAULT_LANGUAGE, **values) -> str:
    """One of the command line's own lines, in ``language`` and filled in."""
    table = CONSOLE.get(language) or CONSOLE[DEFAULT_LANGUAGE]
    template = table.get(key) or CONSOLE[DEFAULT_LANGUAGE][key]
    return template.format(**values) if values else template


def detail(code: object, language: str = DEFAULT_LANGUAGE, **values) -> str:
    """One recorded detail as a sentence, in ``language``, values filled in.

    An unknown code comes back as the code with its values: a detail never
    reaches the user as a sentence that says nothing about the file.
    """
    name = _code_name(code)
    table = DETAILS.get(name)
    if table is None:
        rendered = ", ".join(f"{key}={value}" for key, value in values.items())
        return f"{name} ({rendered})" if rendered else name
    template = _pick(table, language)
    return template.format(**values) if values else template

