"""NF-e/NFC-e XML input: read the fields, then render a PDF.

The XML is the authoritative source of the file-name fields. Rendering is kept
in :mod:`app.xml.render`, so the parser can be tested without the PDF library
and the converter can be used on its own.
"""

from .invoice import (
    NFCE_MODEL,
    NFE_MODEL,
    XmlInvoice,
    XmlInvoiceError,
    inspect_xml,
)
from .render import XmlRenderError, render_xml_to_pdf

__all__ = [
    "NFCE_MODEL",
    "NFE_MODEL",
    "XmlInvoice",
    "XmlInvoiceError",
    "XmlRenderError",
    "inspect_xml",
    "render_xml_to_pdf",
]
