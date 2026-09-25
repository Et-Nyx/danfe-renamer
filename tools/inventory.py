"""Dataset inspection (plan phase 1): what is actually inside a folder of PDFs?

Answers, before any extraction is trusted:

* how many files, how big, how many pages;
* whether text is extractable at all (an image-only scan would need OCR);
* how many files carry an access key, and whether its check digit is valid;
* which expected labels each file prints, which is how a new layout shows up;
* which generator produced the file.

Usage::

    PYTHONPATH= .venv/Scripts/python.exe -m tools.inventory \\
        --data-root "C:/path/to/Notas_fiscais" --report-dir local_output/inventory
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.cli import collect_sources
from app.pdf.access_key import find_key_occurrences, is_valid_access_key
from app.pdf.text import PdfReadError, load_document, normalize_text
from app.extractors.danfe_standard import _DATE_LABELS, _KEY_LABELS, _TOTAL_LABELS

IGNORED_METADATA_KEYS = {"title", "format", "creationDate", "modDate", "subject"}

#: Labels the inventory looks for, so a new layout shows up as a gap.
WATCHED_LABELS = {
    "key_box": _KEY_LABELS,
    "emission_date": _DATE_LABELS,
    "note_total": _TOTAL_LABELS,
}


@dataclass
class FileInventory:
    source: str
    size_bytes: int
    pages: int
    text_characters: int
    has_text: bool
    generator: str
    access_keys: int
    access_key_valid: bool
    printed_nf_number: bool
    labels: dict[str, bool]
    error: str = ""


def inspect(pdf: Path) -> FileInventory:
    """Read one PDF far enough to describe it."""
    size = pdf.stat().st_size
    try:
        document = load_document(pdf)
    except PdfReadError as exc:
        return FileInventory(
            source=str(pdf),
            size_bytes=size,
            pages=0,
            text_characters=0,
            has_text=False,
            generator="",
            access_keys=0,
            access_key_valid=False,
            printed_nf_number=False,
            labels={name: False for name in WATCHED_LABELS},
            error=f"{exc.code}: {exc}",
        )

    text = document.text
    normalized = normalize_text(text)
    keys = find_key_occurrences(document)
    labels = {
        name: any(
            " ".join(variant) in normalized for variant in variants
        )
        for name, variants in WATCHED_LABELS.items()
    }
    return FileInventory(
        source=str(pdf),
        size_bytes=size,
        pages=document.page_count,
        text_characters=len(text),
        has_text=len(text.strip()) > 50,
        generator=_generator(document.metadata),
        access_keys=len(keys),
        access_key_valid=any(is_valid_access_key(occ.digits) for occ in keys),
        printed_nf_number="N " in normalized or "NF" in normalized,
        labels=labels,
    )


def _generator(metadata: dict[str, str]) -> str:
    for key in ("creator", "producer"):
        value = metadata.get(key)
        if value:
            return value.strip()
    return "unknown"


def summarise(rows: list[FileInventory]) -> dict:
    """The counts that tell you whether the dataset is what you assumed."""
    return {
        "files": len(rows),
        "unreadable": sum(1 for row in rows if row.error),
        "without_text": sum(1 for row in rows if not row.has_text and not row.error),
        "with_access_key": sum(1 for row in rows if row.access_keys),
        "with_valid_access_key": sum(1 for row in rows if row.access_key_valid),
        "multiple_access_keys": sum(1 for row in rows if row.access_keys > 1),
        "generators": dict(Counter(row.generator or "unknown" for row in rows).most_common()),
        "pages": dict(Counter(row.pages for row in rows).most_common()),
        "missing_labels": {
            name: sum(1 for row in rows if not row.labels.get(name))
            for name in WATCHED_LABELS
        },
    }


def write_reports(report_dir: Path, rows: list[FileInventory], summary: dict) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "inventory.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (report_dir / "inventory.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            [
                "source",
                "size_bytes",
                "pages",
                "text_characters",
                "generator",
                "access_keys",
                "access_key_valid",
                "error",
            ]
            + [f"label_{name}" for name in WATCHED_LABELS]
        )
        for row in rows:
            writer.writerow(
                [
                    Path(row.source).name,
                    row.size_bytes,
                    row.pages,
                    row.text_characters,
                    row.generator,
                    row.access_keys,
                    row.access_key_valid,
                    row.error,
                ]
                + [row.labels.get(name, False) for name in WATCHED_LABELS]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--report-dir", default="local_output/inventory")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    pdfs = collect_sources([Path(args.data_root)], [])
    if args.limit:
        pdfs = pdfs[: args.limit]

    rows: list[FileInventory] = []
    for index, pdf in enumerate(pdfs, start=1):
        print(f"\rReading {index} of {len(pdfs)}...", end="", flush=True)
        rows.append(inspect(pdf))
    print()

    summary = summarise(rows)
    report_dir = Path(args.report_dir)
    write_reports(report_dir, rows, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nReports: {report_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
