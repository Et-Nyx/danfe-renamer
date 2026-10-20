"""Convert NF-e/NFC-e XML into a DANFE/DANFCe PDF.

This is the converter stage on its own: it knows nothing about file names,
batch folders or reports. The renamer calls it with a destination path in its
staging area, then copies the result into the batch under the final name.

The library is imported lazily so a source checkout that only renames PDFs can
still start without the rendering dependency installed.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.wording import Detail, DetailCode
from .invoice import NFCE_MODEL, NFE_MODEL

#: The encoding an XML declares in its first line, e.g. ``ISO-8859-1``. The
#: declaration itself is ASCII by definition, so the head of the file can be read
#: before the rest of it is decoded with what the file declares.
_DECLARED_ENCODING = re.compile(rb"<\?xml[^>]*encoding=[\"']([A-Za-z0-9._-]+)[\"']")

#: A byte order mark is not part of the document, whatever the declaration says.
_BYTE_ORDER_MARK = b"\xef\xbb\xbf"


def _read_text(path: Path) -> str:
    """The XML as text, in the encoding the file itself declares.

    Not every emitter writes UTF-8, and an XML says which encoding it used. Read
    as UTF-8 regardless, a Latin-1 file the application had already read and
    understood fails here with "could not read": the reader takes the
    declaration, so the converter has to as well.
    """
    raw = path.read_bytes()
    if raw.startswith(_BYTE_ORDER_MARK):
        raw = raw[len(_BYTE_ORDER_MARK) :]
    declared = _DECLARED_ENCODING.search(raw[:200])
    return raw.decode(declared.group(1).decode("ascii") if declared else "utf-8")


class XmlRenderError(Exception):
    """The XML could not be turned into a readable PDF, with the fact behind it."""

    def __init__(self, detail: Detail) -> None:
        super().__init__(str(detail))
        self.detail = detail


def render_xml_to_pdf(
    xml_path: str | Path,
    pdf_path: str | Path,
    *,
    model: str,
) -> Path:
    """Render ``xml_path`` into ``pdf_path`` and verify the result.

    The destination must not exist. A failed render never leaves the partial
    file behind, so the caller can treat the path as either absent or a valid
    PDF.
    """
    source = Path(xml_path)
    target = Path(pdf_path)
    if target.exists():
        raise XmlRenderError(
            Detail(DetailCode.RENDER_TARGET_EXISTS, {"target": str(target)})
        )

    try:
        xml_content = _read_text(source)
    except (OSError, UnicodeDecodeError, LookupError) as exc:
        raise XmlRenderError(
            Detail(
                DetailCode.RENDER_READ_FAILED,
                {"name": source.name, "error": str(exc)},
            )
        ) from exc

    try:
        if model == NFCE_MODEL:
            from brazilfiscalreport.danfce import Danfce

            document = Danfce(xml=xml_content)
        elif model == NFE_MODEL:
            from brazilfiscalreport.danfe import Danfe

            document = Danfe(xml=xml_content)
        else:
            raise XmlRenderError(
                Detail(DetailCode.RENDER_MODEL_UNSUPPORTED, {"model": str(model)})
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        document.output(str(target))
    except XmlRenderError:
        raise
    except Exception as exc:
        _remove(target)
        raise XmlRenderError(
            Detail(
                DetailCode.EVIDENCE,
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        ) from exc

    try:
        _verify_pdf(target)
    except XmlRenderError:
        _remove(target)
        raise
    return target


def _verify_pdf(path: Path) -> None:
    """A render that produced no readable page is not a successful render."""
    if not path.exists() or path.stat().st_size == 0:
        raise XmlRenderError(Detail(DetailCode.RENDER_NO_PDF))
    import pymupdf

    document = pymupdf.open(path)
    try:
        if document.page_count == 0:
            raise XmlRenderError(Detail(DetailCode.RENDER_NO_PAGES))
    except XmlRenderError:
        raise
    except Exception as exc:
        raise XmlRenderError(
            Detail(DetailCode.RENDER_UNREADABLE, {"error": str(exc)})
        ) from exc
    finally:
        document.close()


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
