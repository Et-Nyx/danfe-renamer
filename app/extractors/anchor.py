"""Label anchoring over a document's text geometry.

Every DANFE layout prints the same fields under slightly different labels and in
a different text order, so parsers locate a *label* and then look for its value
by position: after the label on the same row, or on a following row inside the
label's column.

Positions are compared inside one *frame* - the direction the anchor's own row
reads (``(1, 0)`` for ordinary text, ``(0, -1)`` for a receipt stub printed
bottom to top) - so a rotated stub never competes with the document body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from ..pdf.text import Document, Frame, Line, Word, frame_of, normalize_tokens

#: A label variant is a sequence of normalized words, e.g.
#: ``("VALOR", "TOTAL", "DA", "NOTA")``.
LabelVariants = Sequence[Sequence[str]]
TokenPredicate = Callable[[str], bool]


@dataclass(frozen=True)
class Anchor:
    """One printed occurrence of a label."""

    line_index: int
    words: tuple[Word, ...]
    label: tuple[str, ...]
    direction: tuple[float, float]

    @property
    def frame(self) -> Frame:
        return frame_of(self.words, self.direction)


def find_anchors(document: Document, variants: LabelVariants) -> tuple[Anchor, ...]:
    """Return every occurrence of any label variant, in reading order."""
    wanted = tuple(tuple(variant) for variant in variants)
    anchors: list[Anchor] = []
    for line in document.lines:
        tokens = normalize_tokens(line.text)
        if not tokens:
            continue
        for variant in wanted:
            start = _find_subsequence(tokens, variant)
            if start is None:
                continue
            matched = _words_for_tokens(line.words, start, len(variant))
            if matched:
                anchors.append(
                    Anchor(
                        line_index=line.index,
                        words=matched,
                        label=variant,
                        direction=line.direction,
                    )
                )
    return tuple(anchors)


def find_value_near(
    document: Document,
    anchor: Anchor,
    predicate: TokenPredicate,
    *,
    max_distance: float = 90.0,
    max_horizontal_offset: float = 25.0,
) -> Word | None:
    """Return the closest value-shaped word that belongs to ``anchor``.

    Candidates must be printed in the anchor's own frame: on the same line after
    the label, or on a following line inside the label's column.
    """
    anchor_frame = anchor.frame
    best: tuple[float, Word] | None = None
    for word in document.words:
        if word.direction != anchor.direction or not predicate(word.text):
            continue
        word_frame = word.frame(anchor.direction)
        if word.line_index == anchor.line_index:
            if word_frame.advance[0] < anchor_frame.advance[1] - 1.0:
                continue
            stack_gap, advance_gap = 0.0, 0.0
        elif word_frame.stack[0] >= anchor_frame.stack[1] - 2.0:
            stack_gap = word_frame.stack[0] - anchor_frame.stack[1]
            advance_gap = word_frame.advance_gap(anchor_frame)
            if advance_gap > max_horizontal_offset:
                continue
        else:
            continue
        if stack_gap > max_distance:
            continue
        cost = stack_gap + 3.0 * advance_gap
        if best is None or cost < best[0]:
            best = (cost, word)
    return None if best is None else best[1]


def find_line_below(
    document: Document, anchor: Anchor, *, max_distance: float = 30.0
) -> Line | None:
    """Return the first text line inside the label's cell, below the label."""
    anchor_frame = anchor.frame
    for line in document.lines:
        if line.index <= anchor.line_index or line.direction != anchor.direction:
            continue
        line_frame = frame_of(line.words, anchor.direction)
        stack_gap = line_frame.stack[0] - anchor_frame.stack[1]
        if stack_gap > max_distance:
            continue
        if stack_gap < -2.0:
            continue
        if line_frame.advance_gap(anchor_frame) > 0.0:
            continue
        return line
    return None

def _find_subsequence(tokens: Sequence[str], wanted: Sequence[str]) -> int | None:
    if not wanted or len(wanted) > len(tokens):
        return None
    for start in range(len(tokens) - len(wanted) + 1):
        if tuple(tokens[start : start + len(wanted)]) == tuple(wanted):
            return start
    return None


def _words_for_tokens(
    words: Sequence[Word], start: int, length: int
) -> tuple[Word, ...]:
    """Map a token range back to the words that produced those tokens."""
    first_token = start
    last_token = start + length - 1
    selected: list[Word] = []
    position = 0
    for word in words:
        count = len(normalize_tokens(word.text))
        if not count:
            continue
        if position <= last_token and position + count - 1 >= first_token:
            selected.append(word)
        position += count
    return tuple(selected)
