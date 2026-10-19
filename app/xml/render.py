"""Convert NF-e/NFC-e XML into a DANFE/DANFCe PDF.

This is the converter stage on its own: it knows nothing about file names,
batch folders or reports. The renamer calls it with a destination path in its
staging area, then copies the result into the batch under the final name.

The library is imported lazily so a source checkout that only renames PDFs can
still start without the rendering dependency installed.
"""

from __future__ import annotations

from pathlib import Path

from .invoice import NFCE_MODEL, NFE_MODEL


class XmlRenderError(Exception):
    """The XML could not be turned into a readable PDF."""


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
        raise XmlRenderError(f"{target} already exists")

    try:
        xml_content = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise XmlRenderError(f"could not read {source.name}: {exc}") from exc

    try:
        if model == NFCE_MODEL:
            from brazilfiscalreport.danfce import Danfce

            document = Danfce(xml=xml_content)
        elif model == NFE_MODEL:
            from brazilfiscalreport.danfe import Danfe

            document = Danfe(xml=xml_content)
        else:
            raise XmlRenderError(f"unsupported document model: {model!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        document.output(str(target))
    except XmlRenderError:
        raise
    except Exception as exc:
        _remove(target)
        raise XmlRenderError(f"{type(exc).__name__}: {exc}") from exc

    try:
        _verify_pdf(target)
    except XmlRenderError:
        _remove(target)
        raise
    return target


def _verify_pdf(path: Path) -> None:
    """A render that produced no readable page is not a successful render."""
    if not path.exists() or path.stat().st_size == 0:
        raise XmlRenderError("the converter did not produce a PDF")
    import pymupdf

    document = pymupdf.open(path)
    try:
        if document.page_count == 0:
            raise XmlRenderError("the generated PDF has no pages")
    except XmlRenderError:
        raise
    except Exception as exc:
        raise XmlRenderError(f"the generated PDF could not be read: {exc}") from exc
    finally:
        document.close()


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
