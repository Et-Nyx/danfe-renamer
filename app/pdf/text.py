"""PDF text access layer.

PyMuPDF is used only here. Callers receive :class:`Document` objects made of
``Page``, ``Line`` and ``Word`` records plus the normalized text helpers used
for label matching.

Three things make this layer worth its own module:

* a DANFE may store its layout in different ways - portrait, landscape, and a
  receipt stub rotated a quarter turn on the same page - so every line carries
  its writing direction and callers compare geometry inside one frame;
* PyMuPDF's line grouping follows the text direction, which is what makes the
  rotated stub readable, but it also merges rows that merely touch (a label and
  the value printed just under it), so each line is split into stack-consistent
  segments - the rows a person sees;
* the library's own objects never leave this module and are closed in the thread
  that created them (``app/core/pipeline.py`` explains why collections have to
  stay out of that window).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pymupdf

#: Characters kept by :func:`normalize_text`. Everything else becomes a space.
_KEEP_RE = re.compile(r"[^A-Za-z0-9]+")

#: Minimum stacking overlap for two words of one PyMuPDF line to count as the
#: same printed row, as a fraction of the shorter word.
_ROW_OVERLAP_RATIO = 0.5

#: Reading direction of a line, e.g. ``(1.0, 0.0)`` for ordinary text.
Direction = tuple[float, float]

#: A box as ``(stack0, stack1)``, or an interval in general.
Interval = tuple[float, float]


def normalize_text(text: str) -> str:
    """Return the uppercase ASCII form used to match labels and values.

    Accents are removed rather than transliterated (``EMISSÃO`` -> ``EMISSAO``),
    so equivalent spellings coming from different generators, or from PDFs whose
    fonts lose accented glyphs, compare equal.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_only = without_marks.encode("ASCII", "ignore").decode("ASCII")
    return _KEEP_RE.sub(" ", ascii_only).strip().upper()


def normalize_tokens(text: str) -> tuple[str, ...]:
    """Return the normalized words of ``text`` (see :func:`normalize_text`)."""
    return tuple(normalize_text(text).split())


class PdfReadError(Exception):
    """The document could not be opened or its text could not be read.

    ``code`` is the stable failure code reported for the file
    (``PDF_READ_ERROR`` or ``PDF_ENCRYPTED``).
    """

    def __init__(self, message: str, code: str = "PDF_READ_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Word:
    """A single positioned word, in its own page's coordinates."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    #: Global index of the row this word belongs to.
    line_index: int
    #: Page this word is printed on; coordinates are only comparable inside it.
    page_number: int
    #: Unit vector of the line's reading direction, e.g. ``(1.0, 0.0)``.
    direction: Direction

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0

    def frame(self, direction: Direction | None = None) -> "Frame":
        """This word's box in the axes of ``direction``."""
        return frame_of((self,), direction or self.direction)


@dataclass(frozen=True)
class Frame:
    """A box expressed in the axes of one reading direction.

    ``advance`` runs along the text direction (left to right for ordinary
    text); ``stack`` runs from one printed line to the next (top to bottom).
    """

    advance: Interval
    stack: Interval

    def advance_gap(self, other: "Frame") -> float:
        """Empty space between the two boxes along the reading direction."""
        return _gap(self.advance, other.advance)

    def stack_gap(self, other: "Frame") -> float:
        """Empty space between the two boxes across the printed lines."""
        return _gap(self.stack, other.stack)


def _gap(first: Interval, second: Interval) -> float:
    return max(0.0, first[0] - second[1], second[0] - first[1])


def frame_of(words: Sequence[Word], direction: Direction) -> Frame:
    """Express the box around ``words`` in the axes of ``direction``.

    The stack axis is the text direction turned a quarter turn clockwise, so
    the mapping is a plain rotation: it keeps the frame right-handed and
    therefore never mirrors the document.
    """
    dx, dy = direction
    if dx > 0:
        advance = (min(w.x0 for w in words), max(w.x1 for w in words))
        stack = (min(w.y0 for w in words), max(w.y1 for w in words))
    elif dx < 0:
        advance = (-max(w.x1 for w in words), -min(w.x0 for w in words))
        stack = (min(w.y0 for w in words), max(w.y1 for w in words))
    elif dy > 0:
        advance = (min(w.y0 for w in words), max(w.y1 for w in words))
        stack = (-max(w.x1 for w in words), -min(w.x0 for w in words))
    else:
        advance = (-max(w.y1 for w in words), -min(w.y0 for w in words))
        stack = (min(w.x0 for w in words), max(w.x1 for w in words))
    return Frame(advance=advance, stack=stack)


@dataclass(frozen=True)
class Line:
    """One printed row of text, in the page's coordinates."""

    page_number: int
    index: int
    words: tuple[Word, ...]
    #: Unit vector of the reading direction, e.g. ``(1.0, 0.0)`` for normal text
    #: and ``(0.0, -1.0)`` for a stub printed bottom to top.
    direction: Direction

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def x0(self) -> float:
        return min(word.x0 for word in self.words)

    @property
    def y0(self) -> float:
        return min(word.y0 for word in self.words)

    @property
    def x1(self) -> float:
        return max(word.x1 for word in self.words)

    @property
    def y1(self) -> float:
        return max(word.y1 for word in self.words)

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class Page:
    """One page of a document."""

    number: int
    width: float
    height: float
    rotation: int
    lines: tuple[Line, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def words(self) -> tuple[Word, ...]:
        return tuple(word for line in self.lines for word in line.words)


@dataclass(frozen=True)
class Document:
    """A parsed PDF: pages, document metadata and the original path."""

    path: Path
    pages: tuple[Page, ...]
    metadata: dict[str, str]

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)

    @property
    def lines(self) -> tuple[Line, ...]:
        return tuple(line for page in self.pages for line in page.lines)

    @property
    def words(self) -> tuple[Word, ...]:
        return tuple(word for page in self.pages for word in page.words)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def load_document(path: str | Path) -> Document:
    """Open ``path`` and build the positioned-text representation.

    Raises :class:`PdfReadError` when the file cannot be read, is not a PDF, is
    password protected or yields no pages.
    """
    pdf_path = Path(path)
    try:
        raw = pymupdf.open(pdf_path)
    except Exception as exc:  # pragma: no cover - library specific messages
        raise PdfReadError(f"Could not open PDF: {exc}") from exc

    try:
        if raw.needs_pass:
            raise PdfReadError("PDF is password protected", code="PDF_ENCRYPTED")
        if raw.page_count == 0:
            raise PdfReadError("PDF has no pages")

        metadata = {key: value for key, value in (raw.metadata or {}).items() if value}
        pages: list[Page] = []
        line_offset = 0
        for number, page in enumerate(raw, start=1):
            built = _build_page(number, page, line_offset)
            pages.append(built)
            line_offset += len(built.lines)
    except PdfReadError:
        raise
    except Exception as exc:  # pragma: no cover - library specific messages
        raise PdfReadError(f"Could not read PDF text: {exc}") from exc
    finally:
        # Close and drop the library's objects here, in the thread that made
        # them; MuPDF is not thread-safe.
        raw.close()
        del raw

    return Document(path=pdf_path, pages=tuple(pages), metadata=metadata)


def _build_page(number: int, page: "pymupdf.Page", line_offset: int) -> Page:
    box = page.rect
    directions = _line_directions(page)

    grouped: dict[tuple[int, int], list[tuple[float, float, float, float, str]]] = {}
    for x0, y0, x1, y1, text, block, line, *_ in page.get_text("words"):
        if not text.strip():
            continue
        grouped.setdefault((block, line), []).append((x0, y0, x1, y1, text))

    rows: list[tuple[Direction, list[tuple[float, float, float, float, str]]]] = []
    for key, words in grouped.items():
        direction = directions.get(key, (1.0, 0.0))
        rows.extend((direction, row) for row in _split_into_rows(words, direction))
    rows.sort(
        key=lambda item: _reading_position(item[1], item[0])
    )

    lines: list[Line] = []
    for position, (direction, words) in enumerate(rows):
        index = line_offset + position
        line_words = tuple(
            Word(
                text=text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                line_index=index,
                page_number=number,
                direction=direction,
            )
            for x0, y0, x1, y1, text in sorted(
                words, key=lambda word: _advance_key(word, direction)
            )
        )
        lines.append(
            Line(
                page_number=number,
                index=index,
                words=line_words,
                direction=direction,
            )
        )

    return Page(
        number=number,
        width=box.width,
        height=box.height,
        rotation=page.rotation,
        lines=tuple(lines),
    )


def _split_into_rows(
    words: Sequence[tuple[float, float, float, float, str]], direction: Direction
) -> list[list[tuple[float, float, float, float, str]]]:
    """Split one PyMuPDF line into the printed rows it visually contains.

    PyMuPDF treats a label and the value printed a hair below it as one line,
    which would interleave their words. Words are grouped again by stacking
    overlap so each row keeps its own words.
    """
    rows: list[list[tuple[float, float, float, float, str]]] = []
    for word in sorted(words, key=lambda item: _stack_extent(item, direction)):
        extent = _stack_extent(word, direction)
        for row in rows:
            row_extent = _stack_extent(_row_box(row, direction), direction)
            overlap = min(row_extent[1], extent[1]) - max(row_extent[0], extent[0])
            if overlap <= 0:
                continue
            shorter = min(
                row_extent[1] - row_extent[0], extent[1] - extent[0]
            )
            if shorter > 0 and overlap >= _ROW_OVERLAP_RATIO * shorter:
                row.append(word)
                break
        else:
            rows.append([word])
    return rows


def _row_box(
    row: Iterable[tuple[float, float, float, float, str]], direction: Direction
) -> tuple[float, float, float, float]:
    boxes = list(row)
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _stack_extent(
    box: tuple[float, float, float, float, str], direction: Direction
) -> Interval:
    """Extent of a word across printed lines, in the direction's frame."""
    dx, dy = direction
    if dx != 0:
        return (box[1], box[3])
    return (box[0], box[2])


def _advance_key(
    box: tuple[float, float, float, float, str], direction: Direction
) -> float:
    """Sort key that puts words of a row in the order they are read."""
    dx, dy = direction
    if dx > 0:
        return box[0]
    if dx < 0:
        return -box[2]
    if dy > 0:
        return box[1]
    return -box[3]


def _reading_position(
    words: Sequence[tuple[float, float, float, float, str]], direction: Direction
) -> tuple[float, float]:
    """Where a row sits in reading order: first down the page, then across."""
    dx, dy = direction
    if dx != 0:
        return (min(word[1] for word in words), min(word[0] for word in words))
    return (min(word[0] for word in words), -max(word[1] for word in words))


def _line_directions(page: "pymupdf.Page") -> dict[tuple[int, int], tuple[float, float]]:
    """Map ``(block, line)`` to the writing direction PyMuPDF reported."""
    directions: dict[tuple[int, int], tuple[float, float]] = {}
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for position, line in enumerate(block.get("lines", [])):
            dx, dy = line.get("dir", (1.0, 0.0))
            directions[(block["number"], position)] = (float(round(dx)), float(round(dy)))
    return directions
