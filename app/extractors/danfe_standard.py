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

#: Phrase that repeats the issuer name in the receipt area (DanfeSharp only).
_ISSUER_PHRASE_START = ("RECEBEMOS", "DE")
_ISSUER_PHRASE_END = ("OS", "PRODUTOS")

#: A printed NF number: ``000.011.563`` or ``011.563``.
_PRINTED_NF_RE = re.compile(r"^\d{3}(?:\.\d{3}){1,2}$")

#: Words that mark a printed NF number (``Nº.`` normalizes to ``N``).
_NF_MARKERS = frozenset({"N", "NO", "NF", "NRO", "NUMERO"})

#: How far below a label its value may sit.
#:
#: A DANFE prints a label and its value in the same cell, so the value sits right
#: under the label: measured gaps in production are 0.3pt (grid layouts) to
#: 7.4pt (the ERP variant), which is under one printed row. Staying inside the
#: cell is what keeps the parser from grabbing a number from the next block: an
#: empty cell must become a reported failure, never a guess.
MAX_VALUE_DISTANCE = 12.0

#: How far to the side of a label its value may start, because a value cell can
#: be a little wider than the label printed above it.
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
    issues: list[str] = field(default_factory=list)
    blocked: FailureCode | None = None
    blocked_detail: str | None = None

    def block(self, code: FailureCode, detail: str) -> None:
        if self.blocked is None:
            self.blocked = code
            self.blocked_detail = detail


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

        issues = [
            *key_read.issues,
            *printed_read.issues,
            *date_read.issues,
            *total_read.issues,
            *products_read.issues,
            *issuer_read.issues,
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
        read.block(FailureCode.MISSING_ACCESS_KEY, "no 44-digit key found")
        return read

    anchors = find_anchors(document, _KEY_LABELS)
    anchored = [
        occurrence for occurrence in occurrences if _is_anchored(occurrence, anchors)
    ]
    ranked = anchored or list(occurrences)
    distinct = list(dict.fromkeys(occurrence.digits for occurrence in ranked))

    if len(distinct) > 1:
        where = "next to the key label" if anchored else "anywhere in the document"
        read.block(
            FailureCode.ACCESS_KEY_AMBIGUOUS,
            f"multiple keys found {where}: " + ", ".join(distinct),
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
        read.issues.append("Referenced note keys present: " + ", ".join(extras))
    if not anchored:
        read.issues.append("Access key is not printed next to a CHAVE DE ACESSO label")
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
            "Printed NF number candidates found without a Nº label: "
            + ", ".join(word.text for word in candidates)
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
                f"impossible date {word.text.strip()!r}",
            )
            continue
        values.append(word.text.strip())

    if not values:
        return read
    distinct = list(dict.fromkeys(values))
    if len(distinct) > 1:
        read.block(
            FailureCode.EMISSION_DATE_CONFLICT,
            "emission date printed differently in the document: "
            + ", ".join(distinct),
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
            "VALOR TOTAL DA NOTA printed with different values: "
            + ", ".join(distinct),
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
        read.issues.append("Issuer read from the receipt phrase, not the emitente block")
        read.value = phrase_name
        return read

    read.value = block_name
    if phrase_name is not None and _letter_key(phrase_name) != _letter_key(block_name):
        read.issues.append(
            "Issuer differs between emitente block and receipt phrase: "
            f"{block_name!r} vs {phrase_name!r}"
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


def _find_run(tokens: tuple[str, ...], wanted: tuple[str, ...], start: int = 0):
    for position in range(start, len(tokens) - len(wanted) + 1):
        if tokens[position : position + len(wanted)] == wanted:
            return position
    return None


def _letter_key(name: str) -> str:
    return "".join(normalize_tokens(name))
