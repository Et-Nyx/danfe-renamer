"""Synthetic DANFE builders for tests.

Real invoices are confidential, so tests build their own PDFs. The builders
reproduce what the production generators actually do, which is what the parser
has to cope with:

* the label of a cell and the value under it are separate rows that touch;
* the access key is printed in groups of four, sometimes interleaved with the
  label of its box;
* a landscape DANFE keeps its receipt stub rotated a quarter turn on the same
  page as the body;
* the receipt stub repeats emission date and total under other wording.

Fixtures are written with PyMuPDF, the same library the application reads with.
"""

from __future__ import annotations

import pymupdf

PAGE = pymupdf.paper_rect("a4")
FONT_SIZE = 8.0
LINE = 9.0


def make_access_key(
    nf_number: str,
    *,
    year: int = 2026,
    month: int = 9,
    uf: str = "24",
    model: str = "55",
    series: str = "001",
    control: str = "123456789",
) -> str:
    """Build a valid 44-digit key whose NF number is ``nf_number``."""
    from app.pdf.access_key import check_digit

    issuer_cnpj = "12345678000199"
    body = (
        uf
        + f"{year % 100:02d}"
        + f"{month:02d}"
        + issuer_cnpj
        + model
        + series
        + f"{int(nf_number):09d}"
        + control
    )
    return body + check_digit(body)


def group_key(key: str) -> str:
    """Print a key the way a DANFE does: groups of four digits."""
    return " ".join(key[index : index + 4] for index in range(0, 44, 4))


def _printed_nf_number(number: str) -> str:
    """Print an NF number the way a DANFE does: nine digits, grouped by three."""
    digits = f"{int(number):09d}"
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:]}"


def write_danfe(
    path,
    *,
    issuer: str = "INDUSTRIA EXEMPLO LTDA",
    recipient: str | None = None,
    nf_number: str = "1234",
    emission_date: str = "16/09/2026",
    exit_date: str = "17/09/2026",
    products_total: str | None = "1.200,00",
    total: str = "1.234,56",
    emitted: str = "16/09/2026",
    key: str | None = None,
    date_label: str = "DATA DE EMISSÃO",
    total_label: str = "VALOR TOTAL DA NOTA",
    printed_nf_number: str | None = None,
    series: str = "001",
    control: str = "123456789",
    landscape: bool = False,
    extra_pages: int = 0,
):
    """Write a DANFE-like PDF and return its access key."""
    key = key or make_access_key(
        nf_number, year=2026, month=9, series=series, control=control
    )
    printed = printed_nf_number or nf_number
    path = _ensure_parent(path)
    document = pymupdf.open()
    page_width = PAGE.height if landscape else PAGE.width
    page_height = PAGE.width if landscape else PAGE.height
    page = document.new_page(width=page_width, height=page_height)
    rotation = 90 if landscape else 0
    _draw_receipt_stub(page, rotation, issuer, emitted, total)
    _draw_body(
        page,
        rotation,
        issuer,
        recipient,
        printed,
        date_label,
        emission_date,
        exit_date,
        total_label,
        products_total,
        total,
        key,
    )
    # PyMuPDF invalidates page handles when a page is added, so the extra pages
    # are drawn through fresh lookups and the size is kept as plain numbers.
    for index in range(extra_pages):
        document.new_page(width=page_width, height=page_height)
        _draw_product_rows(
            document[-1], count=30, offset=40.0, x=40.0, value_x=370.0, sequence=index
        )
    document.save(path)
    document.close()
    return key


def _ensure_parent(path) -> "pymupdf.Path | str":
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return path


def _draw_receipt_stub(page, rotation, issuer, emitted, total) -> None:
    """The receipt area, which repeats date and total under other wording."""
    if rotation == 90:
        # A landscape DANFE keeps the stub rotated, reading bottom to top.
        page.insert_text(
            (14, page.rect.height - 20),
            f"RECEBEMOS DE {issuer} OS PRODUTOS CONSTANTES DA NOTA FISCAL",
            fontsize=FONT_SIZE,
            rotate=90,
        )
        page.insert_text(
            (28, page.rect.height - 20),
            f"EMISSÃO: {emitted} VALOR TOTAL: R$ {total}",
            fontsize=FONT_SIZE,
            rotate=90,
        )
        return
    page.insert_text(
        (14, 20),
        f"RECEBEMOS DE {issuer} OS PRODUTOS CONSTANTES DA NOTA FISCAL ELETRÔNICA",
        fontsize=FONT_SIZE,
    )
    page.insert_text(
        (14, 30), f"EMISSÃO: {emitted} VALOR TOTAL: R$ {total}", fontsize=FONT_SIZE
    )


def _draw_body(
    page,
    rotation,
    issuer,
    recipient,
    printed_nf_number,
    date_label,
    emission_date,
    exit_date,
    total_label,
    products_total,
    total,
    key,
) -> None:
    """The DANFE body: issuer block, key box, dates and the tax grid."""
    x = 200 if rotation == 90 else 40
    y = 60
    page.insert_text((x, y), "IDENTIFICAÇÃO DO EMITENTE", fontsize=FONT_SIZE)
    page.insert_text((x, y + LINE), issuer, fontsize=FONT_SIZE)
    page.insert_text((x, y + 2 * LINE), "AV DAS INDUSTRIAS, 1000", fontsize=FONT_SIZE)

    page.insert_text((x + 260, y), "DANFE", fontsize=FONT_SIZE)
    page.insert_text(
        (x + 260, y + LINE),
        "Documento Auxiliar da Nota Fiscal Eletrônica",
        fontsize=FONT_SIZE,
    )
    page.insert_text(
        (x + 260, y + 2 * LINE),
        f"Nº.: {_printed_nf_number(printed_nf_number)}",
        fontsize=FONT_SIZE,
    )
    page.insert_text((x + 260, y + 3 * LINE), "CHAVE DE ACESSO", fontsize=FONT_SIZE)
    page.insert_text((x + 260, y + 4 * LINE), group_key(key), fontsize=FONT_SIZE)

    if recipient is not None:
        page.insert_text((x, y + 5 * LINE), "DESTINATÁRIO / REMETENTE", fontsize=FONT_SIZE)
        page.insert_text((x, y + 6 * LINE), "RAZÃO SOCIAL", fontsize=FONT_SIZE)
        page.insert_text((x, y + 7 * LINE), recipient, fontsize=FONT_SIZE)

    # The value row sits right below its label row, the way real layouts print
    # it, and both are inside the same column.
    page.insert_text((x + 330, y + 9 * LINE), date_label, fontsize=FONT_SIZE)
    page.insert_text((x + 330, y + 10 * LINE), emission_date, fontsize=FONT_SIZE)
    page.insert_text((x + 330, y + 11 * LINE), "DATA DE SAÍDA", fontsize=FONT_SIZE)
    page.insert_text((x + 330, y + 12 * LINE), exit_date, fontsize=FONT_SIZE)

    if products_total is not None:
        page.insert_text(
            (x + 330, y + 14 * LINE), "VALOR TOTAL DOS PRODUTOS", fontsize=FONT_SIZE
        )
        page.insert_text((x + 330, y + 15 * LINE), products_total, fontsize=FONT_SIZE)
    page.insert_text((x + 330, y + 17 * LINE), total_label, fontsize=FONT_SIZE)
    page.insert_text((x + 330, y + 18 * LINE), total, fontsize=FONT_SIZE)

    _draw_product_rows(
        page,
        count=10,
        offset=y + 22 * LINE,
        x=x,
        value_x=x + 330,
        header=True,
    )


def _draw_product_rows(
    page,
    *,
    count: int,
    offset: float,
    x: float = 40,
    value_x: float | None = None,
    sequence: int = 0,
    header: bool = False,
) -> None:
    """Rows of numbers, to make sure they are never mistaken for fields.

    ``value_x`` places a money column under the same column as the document's
    own values, which is what a later page of a long invoice looks like.
    """
    if header:
        page.insert_text((x, offset), "DADOS DOS PRODUTOS / SERVIÇOS", fontsize=FONT_SIZE)
        page.insert_text((x, offset + LINE), "CÓDIGO PRODUTO  NCM/SH  CFOP  UN  QUANTI.", fontsize=FONT_SIZE)
        offset += 3 * LINE
    for index in range(count):
        y = offset + index * LINE
        if y > page.rect.height - 20:
            break
        page.insert_text(
            (x, y),
            f"000{sequence}{index:03d} 87089490 000 5.102 1,00 58,55 58,55",
            fontsize=FONT_SIZE,
        )
        if value_x is not None:
            page.insert_text((value_x, y), f"{index + 1},15", fontsize=FONT_SIZE)
            page.insert_text((value_x + 45, y), "20,00", fontsize=FONT_SIZE)
