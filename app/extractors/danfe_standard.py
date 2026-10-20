"""The standard DANFE layout, as printed by the generators seen in production.

One parser covers the layouts found so far, because they are the same DANFE
document with different label spellings and orientations:

* ``DanfeSharp`` output, portrait and landscape (``DATA DE EMISSÃO``);
* the ERP variant (``DATA DA EMISSÃO``, labels and values in separate blocks).

Both are read with the same anchor vocabulary, so the differences are declared
as label variants instead of duplicated parser code. A layout that is
*structurally* different (a different data model, not a different spelling) gets
its own module in this package.

Extraction keeps the *printed* text of each field; turning that text into typed
values happens once, at the end of :meth:`DanfeStandardExtractor.extract`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.models import ExtractionResult, ExtractedFields, FailureCode
from ..core.normalize import (
    is_plausible_money,
    looks_like_br_date,
    normalize_money,
    parse_br_date,
)
from ..core.wording import Detail, DetailCode
from ..pdf.access_key import find_key_occurrences
from ..pdf.text import Document, Word, normalize_tokens
from .anchor import find_anchors, find_line_below, find_value_near, frame_of
from .base import DanfeExtractor

PARSER_ID = "danfe_standard"

#: Labels of the access-key box. The long ERP variant
#: (``CHAVE DE ACESSO DA NF-e P/ CONSULTA ...``) contains this sequence.
_KEY_LABELS = (("CHAVE", "DE", "ACESSO"),)

#: ``DATA DE EMISSÃO`` (DanfeSharp) and ``DATA DA EMISSÃO`` (ERP variant).
_DATE_LABELS = (("DATA", "DE", "EMISSAO"), ("DATA", "DA", "EMISSAO"))

#: The confirmed financial field. Never ``VALOR TOTAL DOS PRODUTOS``.
#: ``V. TOTAL DA NOTA`` is the abbreviation used by some ERP generators.
_TOTAL_LABELS = (("VALOR", "TOTAL", "DA", "NOTA"), ("V", "TOTAL", "DA", "NOTA"))
_PRODUCTS_TOTAL_LABELS = (
    ("VALOR", "TOTAL", "DOS", "PRODUTOS"),
    ("V", "TOTAL", "PRODUTOS"),
)

#: Issuer block, printed in upper or mixed case depending on the generator.
_ISSUER_LABELS = (("IDENTIFICACAO", "DO", "EMITENTE"),)

#: Recipient block. ``RAZÃO SOCIAL`` also labels the carrier's name further down
#: the page, and the receipt stub quotes it in a placeholder, so the recipient is
#: taken from the one printed right under this block title.
_RECIPIENT_BLOCK_LABELS = (("DESTINATARIO", "REMETENTE"),)
_RECIPIENT_NAME_LABELS = (("RAZAO", "SOCIAL"),)

#: Digits this long are never part of a company name (four-digit years are).
_NAME_BREAK_DIGITS = 5

#: Phrase that repeats the issuer name in the receipt area (DanfeSharp only).
_ISSUER_PHRASE_START = ("RECEBEMOS", "DE")
_ISSUER_PHRASE_END = ("OS", "PRODUTOS")

#: A printed NF number: ``000.011.563`` or ``011.563``.
_PRINTED_NF_RE = re.compile(r"^\d{3}(?:\.\d{3}){1,2}$")

#: Words that mark a printed NF number (``Nº.`` normalizes to ``N``).
_NF_MARKERS = frozenset({"N", "NO", "NF", "NRO", "NUMERO"})

#: How far below a label its value may sit.
#:
#: A DANFE prints a label and its value in the same cell, so the value is right
#: under the label (measured gaps in production are under 8pt). Staying tight is
#: what keeps the parser from grabbing a number from a neighbouring or later
#: row: an empty cell must become a reported failure, never a guess.
MAX_VALUE_DISTANCE = 20.0

#: How far to the side of the label a value may start (value cells can be wider
#: than the label that sits above them).
MAX_VALUE_SIDE_OFFSET = 25.0


def _contains(tokens: tuple[str, ...], wanted: tuple[str, ...]) -> bool:
    """Whether ``wanted`` appears as a run of tokens anywhere in ``tokens``."""
    if not wanted or len(wanted) > len(tokens):
        return False
    return any(
        tokens[start : start + len(wanted)] == wanted
        for start in range(len(tokens) - len(wanted) + 1)
    )


@dataclass(frozen=True)
class _Signature:
    """A required marker of the layout, with a readable name for diagnostics."""

    description: str
    variants: tuple[tuple[str, ...], ...]

    def present(self, tokens: tuple[str, ...]) -> bool:
        return any(_contains(tokens, variant) for variant in self.variants)


_SIGNATURES = (
    _Signature("DANFE", (("DANFE",),)),
    _Signature("CHAVE DE ACESSO", _KEY_LABELS),
    _Signature("DATA DE EMISSÃO", _DATE_LABELS),
    _Signature("VALOR TOTAL DA NOTA", _TOTAL_LABELS),
)


@dataclass
class _Read:
    """Outcome of reading one field: the printed text, notes and any blocker."""

    value: str | None = None
    issues: list[Detail] = field(default_factory=list)
    blocked: FailureCode | None = None
    blocked_detail: Detail | None = None

    def block(self, code: FailureCode, detail: Detail) -> None:
        if self.blocked is None:
            self.blocked = code
            self.blocked_detail = detail


class DanfeStandardExtractor(DanfeExtractor):
    """Reads NF number, emission date, total value and issuer from a DANFE."""

    parser_id = PARSER_ID

    def can_handle(self, document: Document) -> bool:
        """Require the full signature set, so unrelated PDFs are not guessed at."""
        tokens = _document_tokens(document)
        return all(signature.present(tokens) for signature in _SIGNATURES)

    def describe(self, document: Document) -> tuple[tuple[str, bool], ...]:
        tokens = _document_tokens(document)
        return tuple(
            (signature.description, signature.present(tokens))
            for signature in _SIGNATURES
        )

    def extract(self, document: Document) -> ExtractionResult:
        key_read = _read_access_key(document)
        printed_read = _read_printed_nf_number(document)
        date_read = _read_emission_date(document)
        total_read = _read_total_value(document)
        products_read = _read_products_total(document)
        issuer_read = _read_issuer(document)
        recipient_read = _read_recipient(document)

        issues = [
            *key_read.issues,
            *printed_read.issues,
            *date_read.issues,
            *total_read.issues,
            *products_read.issues,
            *issuer_read.issues,
            *recipient_read.issues,
        ]
        blocked = key_read.blocked or date_read.blocked or total_read.blocked
        blocked_detail = (
            key_read.blocked_detail
            if key_read.blocked
            else date_read.blocked_detail
            if date_read.blocked
            else total_read.blocked_detail
        )

        access_key_digits = key_read.value
        fields = ExtractedFields(
            access_key_digits=access_key_digits,
            printed_nf_number=printed_read.value,
            emission_date=parse_br_date(date_read.value) if date_read.value else None,
            emission_date_text=date_read.value,
            total_value=total_read.value,
            products_total=products_read.value,
            issuer=issuer_read.value,
            recipient=recipient_read.value,
        )

        return ExtractionResult(
            parser_id=self.parser_id,
            fields=fields,
            blocked_by=blocked,
            blocked_detail=blocked_detail,
            warnings=tuple(issues),
        )


def _document_tokens(document: Document) -> tuple[str, ...]:
    return tuple(
        token for line in document.lines for token in normalize_tokens(line.text)
    )


def _read_access_key(document: Document) -> _Read:
    """Read the key from the key box, ignoring referenced notes' keys.

    A devolução carries the original note's key in its additional data, so
    occurrences are ranked by how close they sit to ``CHAVE DE ACESSO`` and only
    the best-ranked one is used; leftover keys are reported as warnings.
    """
    read = _Read()
    occurrences = find_key_occurrences(document)
    if not occurrences:
        read.block(FailureCode.MISSING_ACCESS_KEY, Detail(DetailCode.KEY_NOT_FOUND))
        return read

    anchors = find_anchors(document, _KEY_LABELS)
    anchored = [
        occurrence for occurrence in occurrences if _is_anchored(occurrence, anchors)
    ]
    ranked = anchored or list(occurrences)
    distinct = list(dict.fromkeys(occurrence.digits for occurrence in ranked))

    if len(distinct) > 1:
        code = (
            DetailCode.KEY_AMBIGUOUS_ANCHORED
            if anchored
            else DetailCode.KEY_AMBIGUOUS_ANYWHERE
        )
        read.block(
            FailureCode.ACCESS_KEY_AMBIGUOUS,
            Detail(code, {"keys": ", ".join(distinct)}),
        )
        return read

    read.value = distinct[0]
    extras = list(
        dict.fromkeys(
            occurrence.digits
            for occurrence in occurrences
            if occurrence.digits != read.value
        )
    )
    if extras:
        read.issues.append(Detail(DetailCode.REFERENCED_KEYS, {"keys": ", ".join(extras)}))
    if not anchored:
        read.issues.append(Detail(DetailCode.KEY_WITHOUT_LABEL))
    return read


def _is_anchored(occurrence, anchors) -> bool:
    """Whether the key is printed in the key box, at or below a key label.

    A key printed elsewhere (``NF-e Ref.:`` in the additional data of a
    devolução) is not anchored and never becomes the document's own key.
    """
    for anchor in anchors:
        if occurrence.words[0].page_number != anchor.page_number:
            continue
        if occurrence.words[0].direction != anchor.direction:
            continue
        if not 0 <= occurrence.first_line - anchor.line_index <= 6:
            continue
        anchor_frame = anchor.frame
        key_frame = frame_of(occurrence.words, anchor.direction)
        if key_frame.advance[1] >= anchor_frame.advance[0] - 60.0:
            return True
    return False



def _read_printed_nf_number(document: Document) -> _Read:
    """Read the NF number as printed (``Nº.: 000.011.563``), minus zeroes."""
    read = _Read()
    candidates = [
        word for word in document.words if _PRINTED_NF_RE.match(word.text.strip())
    ]
    marked = [word for word in candidates if _preceded_by_nf_marker(document, word)]
    if marked:
        candidates = marked
    elif candidates:
        read.issues.append(
            Detail(
                DetailCode.NUMBER_WITHOUT_LABEL,
                {"numbers": ", ".join(word.text for word in candidates)},
            )
        )

    numbers = {
        re.sub(r"\D", "", word.text).lstrip("0") for word in candidates
    }
    numbers.discard("")
    if len(numbers) == 1:
        read.value = numbers.pop()
    elif len(numbers) > 1:
        read.issues.append(
            "Conflicting printed NF numbers: " + ", ".join(sorted(numbers))
        )
    return read


def _preceded_by_nf_marker(document: Document, word: Word) -> bool:
    """Whether the word is preceded by ``Nº`` on the same line."""
    for line in document.lines:
        if line.index != word.line_index:
            continue
        for index, candidate in enumerate(line.words):
            if candidate is not word:
                continue
            if index == 0:
                return False
            previous = normalize_tokens(line.words[index - 1].text)
            return bool(previous) and previous[-1] in _NF_MARKERS
    return False


def _read_emission_date(document: Document) -> _Read:
    """Read the emission date; never the exit date and never a repaired date."""
    read = _Read()
    values: list[str] = []
    for anchor in find_anchors(document, _DATE_LABELS):
        word = find_value_near(
            document,
            anchor,
            looks_like_br_date,
            max_distance=MAX_VALUE_DISTANCE,
            max_horizontal_offset=MAX_VALUE_SIDE_OFFSET,
        )
        if word is None:
            continue
        if parse_br_date(word.text) is None:
            read.block(
                FailureCode.EMISSION_DATE_NOT_FOUND,
                Detail(DetailCode.DATE_IMPOSSIBLE, {"printed": word.text.strip()}),
            )
            continue
        values.append(word.text.strip())

    if not values:
        return read
    distinct = list(dict.fromkeys(values))
    if len(distinct) > 1:
        read.block(
            FailureCode.EMISSION_DATE_CONFLICT,
            Detail(DetailCode.DATE_CONFLICT, {"values": ", ".join(distinct)}),
        )
        return read
    read.value = distinct[0]
    return read


def _read_total_value(document: Document) -> _Read:
    """Read ``VALOR TOTAL DA NOTA`` and reject a mismatched cells."""
    read = _Read()
    values = _resolved_values(document, _TOTAL_LABELS)
    if not values:
        return read
    distinct = list(dict.fromkeys(values))
    if len(distinct) > 1:
        read.block(
            FailureCode.TOTAL_VALUE_AMBIGUOUS,
            Detail(DetailCode.TOTAL_CONFLICT, {"values": ", ".join(distinct)}),
        )
        return read
    read.value = distinct[0]
    return read


def _read_products_total(document: Document) -> _Read:
    """Read ``VALOR TOTAL DOS PRODUTOS``, used only as a cross-check."""
    read = _Read()
    values = _resolved_values(document, _PRODUCTS_TOTAL_LABELS)
    if len(values) == 1:
        read.value = values[0]
    return read


def _resolved_values(document: Document, labels) -> list[str]:
    """Return the normalized amounts resolved for every label occurrence."""
    values: list[str] = []
    for anchor in find_anchors(document, labels):
        word = find_value_near(
            document,
            anchor,
            is_plausible_money,
            max_distance=MAX_VALUE_DISTANCE,
            max_horizontal_offset=MAX_VALUE_SIDE_OFFSET,
        )
        if word is None:
            continue
        amount = normalize_money(word.text)
        if amount is not None:
            values.append(amount)
    return values


def _read_issuer(document: Document) -> _Read:
    """Read the issuer from the emitente block, cross-checked with the receipt."""
    read = _Read()
    block_name: str | None = None
    for anchor in find_anchors(document, _ISSUER_LABELS):
        line = find_line_below(document, anchor)
        if line is not None and line.text.strip():
            block_name = line.text.strip()
            break

    phrase_name = _read_receipt_issuer(document)
    if block_name is None:
        if phrase_name is None:
            return read
        read.issues.append(Detail(DetailCode.ISSUER_FROM_RECEIPT))
        read.value = phrase_name
        return read

    read.value = block_name
    if phrase_name is not None and _letter_key(phrase_name) != _letter_key(block_name):
        read.issues.append(
            Detail(
                DetailCode.ISSUER_DIFFERS,
                {"block": block_name, "phrase": phrase_name},
            )
        )
    return read


def _read_receipt_issuer(document: Document) -> str | None:
    """Read ``RECEBEMOS DE <issuer> OS PRODUTOS ...``, when it carries a name."""
    for line in document.lines:
        tokens = normalize_tokens(line.text)
        start = _find_run(tokens, _ISSUER_PHRASE_START)
        if start is None:
            continue
        end = _find_run(tokens, _ISSUER_PHRASE_END, start=start)
        if end is None:
            continue
        name = " ".join(tokens[start + len(_ISSUER_PHRASE_START) : end])
        if name and "RAZAO SOCIAL" not in name:
            return name
    return None


def _read_recipient(document: Document) -> _Read:
    """Read the recipient's name: the ``RAZÃO SOCIAL`` under the destinatário block.

    In the DanfeSharp layout the name shares its row with the CNPJ and the
    emission date, so the value is cut where the numbers begin; in the ERP
    variant the values have rows of their own.
    """
    read = _Read()
    anchor = _recipient_name_anchor(document)
    if anchor is None:
        return read

    line = find_line_below(document, anchor, max_distance=20.0)
    if line is None:
        return read
    name = _name_before_numbers(line.text)
    if not name:
        return read
    read.value = name
    return read


def _recipient_name_anchor(document: Document):
    """The ``RAZÃO SOCIAL`` label that belongs to the destinatário block.

    Picks the first one below the block title: the carrier's own ``RAZÃO SOCIAL``
    sits much further down, and the placeholder in the receipt stub sits above.
    """
    blocks = find_anchors(document, _RECIPIENT_BLOCK_LABELS)
    if not blocks:
        return None
    block = blocks[0]
    best = None
    for candidate in find_anchors(document, _RECIPIENT_NAME_LABELS):
        if candidate.page_number != block.page_number:
            continue
        if candidate.direction != block.direction:
            continue
        gap = candidate.frame.stack[0] - block.frame.stack[1]
        if gap < -2.0:
            continue
        if best is None or gap < best[0]:
            best = (gap, candidate)
    return best[1] if best else None


def _name_before_numbers(text: str) -> str:
    """Cut a printed row at the first token that is a number, not a name.

    A company can be called ``MERCADO 2000`` or ``PIER 43``, so a short number on
    its own stays. What stops the name is a printed document number: dots,
    slashes or dashes holding digits (``10.898.825/0001-29``, ``08/09/2026``), or
    a run of five digits and up - the codes the DanfeSharp layout prints in the
    same cell, right after the name.
    """
    kept: list[str] = []
    for token in text.split():
        if _looks_like_document_number(token.strip(":")):
            break
        kept.append(token)
    return " ".join(kept).strip(" -")


def _looks_like_document_number(token: str) -> bool:
    """Whether a printed token is a document number rather than part of a name."""
    if not any(character.isdigit() for character in token):
        return False
    if any(separator in token for separator in "./-"):
        return True
    return token.isdigit() and len(token) >= _NAME_BREAK_DIGITS


def _find_run(tokens: tuple[str, ...], wanted: tuple[str, ...], start: int = 0):
    for position in range(start, len(tokens) - len(wanted) + 1):
        if tokens[position : position + len(wanted)] == wanted:
            return position
    return None


def _letter_key(name: str) -> str:
    return "".join(normalize_tokens(name))
