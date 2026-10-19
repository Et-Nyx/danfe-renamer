"""Read the fields of an NF-e or NFC-e from its authorized XML.

Only the fields the file name needs are read here. The XML is the authoritative
source (it is what SEFAZ authorized), so the parser is deliberately strict about
the access key, the document model and the authorization protocol.

Supported roots are ``nfeProc`` (an authorized NF-e/NFC-e with its protocol) and
plain ``NFe``. A plain ``NFe`` is accepted with a warning: the data is valid,
but there is no protocol proving that SEFAZ authorized it. A ``resNFe`` summary,
an event XML, a CT-e or any other document is rejected instead of guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from defusedxml import ElementTree as SafeElementTree

from ..core.models import ExtractedFields, ExtractionResult, FailureCode
from ..core.normalize import format_br_date, format_br_money, parse_iso_date
from ..pdf.access_key import AccessKey, InvalidAccessKey

NFE_MODEL = "55"
NFCE_MODEL = "65"
SUPPORTED_MODELS = (NFE_MODEL, NFCE_MODEL)

#: Status code SEFAZ uses for an authorized document.
AUTHORIZED_STATUS = "100"


class XmlInvoiceError(Exception):
    """The XML cannot be used, with a stable failure code and a reason."""

    def __init__(self, code: FailureCode, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class XmlInvoice:
    """The fields of one NF-e/NFC-e XML, ready for the validator."""

    path: Path
    model: str
    access_key: AccessKey
    nf_number: str | None
    emission_date: date | None
    emission_date_text: str | None
    total_value: str | None
    issuer: str | None
    recipient: str | None
    authorized: bool
    warnings: tuple[str, ...] = ()

    @property
    def parser_id(self) -> str:
        return "nfe_xml" if self.model == NFE_MODEL else "nfce_xml"

    def to_result(self) -> ExtractionResult:
        """The record the validator consumes, with the XML as its source."""
        return ExtractionResult(
            parser_id=self.parser_id,
            fields=ExtractedFields(
                access_key_digits=self.access_key.digits,
                printed_nf_number=self.nf_number,
                emission_date=self.emission_date,
                emission_date_text=self.emission_date_text,
                total_value=self.total_value,
                issuer=self.issuer,
                recipient=self.recipient,
            ),
            warnings=self.warnings,
        )


def inspect_xml(path: str | Path) -> XmlInvoice:
    """Read one XML, or raise :class:`XmlInvoiceError` with the reason."""
    xml_path = Path(path)
    try:
        raw = xml_path.read_bytes()
    except OSError as exc:
        raise XmlInvoiceError(
            FailureCode.XML_READ_ERROR, f"Could not read XML: {exc}"
        ) from exc

    try:
        root = SafeElementTree.fromstring(raw)
    except Exception as exc:  # defusedxml raises several exception types
        raise XmlInvoiceError(
            FailureCode.XML_READ_ERROR, f"Could not parse XML: {exc}"
        ) from exc

    inf_nfe = _find_first(root, "infNFe")
    if inf_nfe is None:
        raise _unsupported_root(root)

    access_key = _read_access_key(root, inf_nfe)
    model, model_warnings = _read_model(inf_nfe, access_key)
    warnings = list(model_warnings)

    nf_number = _read_nf_number(inf_nfe, access_key, warnings)
    emission_date, emission_date_text = _read_emission_date(inf_nfe)
    total_value = _read_total_value(inf_nfe)
    issuer = _path_text(inf_nfe, "emit", "xNome")
    recipient = _path_text(inf_nfe, "dest", "xNome")

    _check_issuer_cnpj(inf_nfe, access_key)
    authorized = _read_authorization(root, access_key, warnings)
    if _path_text(inf_nfe, "ide", "tpAmb") == "2":
        warnings.append("Homologation XML (tpAmb=2); it has no fiscal value")

    return XmlInvoice(
        path=xml_path,
        model=model,
        access_key=access_key,
        nf_number=nf_number,
        emission_date=emission_date,
        emission_date_text=emission_date_text,
        total_value=total_value,
        issuer=issuer,
        recipient=recipient,
        authorized=authorized,
        warnings=tuple(warnings),
    )


def _read_access_key(root, inf_nfe) -> AccessKey:
    raw_id = (inf_nfe.get("Id") or "").strip()
    digits = raw_id[3:] if raw_id.startswith("NFe") else raw_id
    if not digits:
        protocol_key = _find_first(root, "infProt")
        ch_nfe = _path_text(protocol_key, "chNFe") if protocol_key is not None else None
        digits = ch_nfe or ""
    if not digits:
        raise XmlInvoiceError(
            FailureCode.MISSING_ACCESS_KEY, "infNFe has no Id and no chNFe"
        )
    try:
        return AccessKey(digits)
    except InvalidAccessKey as exc:
        raise XmlInvoiceError(FailureCode.INVALID_ACCESS_KEY, str(exc)) from exc


def _read_model(inf_nfe, access_key: AccessKey) -> tuple[str, list[str]]:
    model = _path_text(inf_nfe, "ide", "mod") or access_key.model
    if model not in SUPPORTED_MODELS:
        raise XmlInvoiceError(
            FailureCode.XML_UNSUPPORTED,
            f"document model {model!r} is not NF-e (55) or NFC-e (65)",
        )
    if model != access_key.model:
        raise XmlInvoiceError(
            FailureCode.INVALID_ACCESS_KEY,
            f"model {model!r} disagrees with the access key model "
            f"{access_key.model!r}",
        )
    return model, []


def _read_nf_number(
    inf_nfe, access_key: AccessKey, warnings: list[str]
) -> str | None:
    printed = _path_text(inf_nfe, "ide", "nNF")
    if printed is None:
        warnings.append("NF number read from the access key; ide/nNF is missing")
        return access_key.nf_number or None
    return printed.lstrip("0") or "0"


def _read_emission_date(inf_nfe) -> tuple[date | None, str | None]:
    raw = _path_text(inf_nfe, "ide", "dhEmi") or _path_text(inf_nfe, "ide", "dEmi")
    parsed = parse_iso_date(raw)
    if parsed is None:
        return None, raw
    return parsed, format_br_date(parsed)


def _read_total_value(inf_nfe) -> str | None:
    raw = _path_text(inf_nfe, "total", "ICMSTot", "vNF")
    if raw is None:
        return None
    try:
        return format_br_money(Decimal(raw))
    except (InvalidOperation, ValueError):
        return None


def _check_issuer_cnpj(inf_nfe, access_key: AccessKey) -> None:
    cnpj = _path_text(inf_nfe, "emit", "CNPJ")
    if cnpj is None:
        return
    digits = "".join(character for character in cnpj if character.isdigit())
    if digits and digits != access_key.issuer_cnpj:
        raise XmlInvoiceError(
            FailureCode.INVALID_ACCESS_KEY,
            f"issuer CNPJ {digits} disagrees with the access key "
            f"{access_key.issuer_cnpj}",
        )


def _read_authorization(root, access_key: AccessKey, warnings: list[str]) -> bool:
    protocol = _find_first(root, "infProt")
    if protocol is None:
        warnings.append(
            "XML has no authorization protocol; the data was read from the NFe"
        )
        return False

    status = _path_text(protocol, "cStat")
    if status is None:
        warnings.append("XML protocol has no cStat; authorization is unconfirmed")
        return False
    if status != AUTHORIZED_STATUS:
        reason = _path_text(protocol, "xMotivo") or "no reason given"
        raise XmlInvoiceError(
            FailureCode.XML_NOT_AUTHORIZED,
            f"authorization status {status}: {reason}",
        )

    protocol_key = _path_text(protocol, "chNFe")
    if protocol_key and protocol_key != access_key.digits:
        raise XmlInvoiceError(
            FailureCode.INVALID_ACCESS_KEY,
            "the protocol key disagrees with the infNFe key",
        )
    return True


def _unsupported_root(root) -> XmlInvoiceError:
    root_name = _local_name(root.tag)
    if root_name == "resNFe":
        return XmlInvoiceError(
            FailureCode.XML_UNSUPPORTED,
            "this is an NF-e summary (resNFe), not an authorized invoice",
        )
    if root_name in {"evento", "procEventoNFe"}:
        return XmlInvoiceError(
            FailureCode.XML_UNSUPPORTED,
            "this is an NF-e event, not an invoice",
        )
    return XmlInvoiceError(
        FailureCode.XML_UNSUPPORTED,
        f"not an NF-e/NFC-e XML (root element: {root_name})",
    )


def _find_first(element, name: str):
    for candidate in element.iter():
        if _local_name(candidate.tag) == name:
            return candidate
    return None


def _path_text(element, *names: str) -> str | None:
    current = element
    for name in names:
        current = _child(current, name)
        if current is None:
            return None
    if current.text is None:
        return None
    text = current.text.strip()
    return text or None


def _child(element, name: str):
    for candidate in element:
        if _local_name(candidate.tag) == name:
            return candidate
    return None


def _local_name(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]
