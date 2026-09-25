"""Measure the extraction against independent oracles, per the plan's phase 3.

The production input is the PDF, so nothing here is part of the application. It
exists to answer one question with evidence: *are the extracted values right?*

Two oracles are used, and neither is the parser's own output:

1. the NF-e XML files that sit next to the PDFs, named by access key, which
   carry the authoritative NF number, emission date, total value and issuer;
2. the file names a person already produced by hand, parsed back into
   date / NF number / value.

Usage::

    PYTHONPATH= .venv/Scripts/python.exe -m tools.evaluate_corpus \\
        --data-root "C:/path/to/Notas_fiscais" --report-dir local_output/eval
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.cli import collect_sources
from app.core.models import Status
from app.core.normalize import money_to_decimal
from app.core.pipeline import analyze_file
from app.pdf.text import load_document, normalize_text

NFE_NAMESPACE = "{http://www.portalfiscal.inf.br/nfe}"

_FILENAME_PREFIX_RE = re.compile(
    r"^\s*(\d{2})\.(\d{2})\.(\d{4})\s*_?\s*NF\s*(\d[\.\d]*)", re.IGNORECASE
)
_MONEY_IN_NAME_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")

#: The receipt stub repeats the emission date and the total under different
#: wording (``Emissão: 10/09/2026``, ``Valor Total: R$ 549,52``), which makes it
#: a second source inside the same document.
_STUB_DATE_RE = re.compile(r"EMISSAO:?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_STUB_VALUE_RE = re.compile(
    r"VALOR\s+TOTAL:?\s*R?\s?\$?\s*(\d{1,3}(?:\.\d{3})*,\d{2})", re.IGNORECASE
)


@dataclass(frozen=True)
class XmlFacts:
    """Authoritative facts from one NF-e XML."""

    key: str
    nf_number: str
    emission_date: date | None
    total_value: Decimal | None
    issuer: str | None
    issuer_cnpj: str | None


@dataclass(frozen=True)
class FilenameFacts:
    """Facts read back from a file name a person produced."""

    emission_date: date | None
    nf_number: str | None
    total_value: Decimal | None
    issuer_hint: str | None


@dataclass
class Comparison:
    """Field-by-field comparison of one PDF against its oracles."""

    source: str
    access_key: str | None = None
    parser_id: str | None = None
    status: str = ""
    reason: str | None = None
    xml_key: str | None = None
    checks: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def mismatches(self) -> list[str]:
        return [name for name, verdict in self.checks.items() if verdict == "MISMATCH"]


ORACLE_AGREEMENT = "agrees"
ORACLE_MISMATCH = "MISMATCH"
ORACLE_MISSING = "no oracle"


def load_xml_facts(root: Path) -> dict[str, XmlFacts]:
    """Index every XML in the corpus by its 44-digit access key."""
    facts: dict[str, XmlFacts] = {}
    for path in sorted(root.rglob("*.xml")):
        parsed = _parse_xml(path)
        if parsed is not None:
            facts[parsed.key] = parsed
    return facts


def _parse_xml(path: Path) -> XmlFacts | None:
    try:
        tree = ElementTree.parse(path)
    except ElementTree.ParseError:
        return None
    inf_nfe = tree.find(f".//{NFE_NAMESPACE}infNFe")
    if inf_nfe is None:
        return None
    key = (inf_nfe.get("Id") or "").replace("NFe", "")
    if len(key) != 44:
        return None

    number = _text(inf_nfe, "ide/nNF") or ""
    emitted = _text(inf_nfe, "ide/dhEmi") or _text(inf_nfe, "ide/dEmi")
    total = _text(inf_nfe, "total/ICMSTot/vNF")
    issuer = _text(inf_nfe, "emit/xNome")
    cnpj = _text(inf_nfe, "emit/CNPJ")
    return XmlFacts(
        key=key,
        nf_number=number.lstrip("0") or "0",
        emission_date=_parse_xml_date(emitted),
        total_value=_decimal_or_none(total),
        issuer=issuer,
        issuer_cnpj=cnpj,
    )


def _text(element: ElementTree.Element, path: str) -> str | None:
    """Read a namespaced child element's text (NF-e XML uses one namespace)."""
    namespaced = "/".join(f"{NFE_NAMESPACE}{part}" for part in path.split("/"))
    found = element.find(namespaced)
    if found is None:
        found = element.find(path)
    return None if found is None or found.text is None else found.text.strip()


def _parse_xml_date(value: str | None) -> date | None:
    if not value or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _decimal_or_none(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def parse_filename_facts(name: str) -> FilenameFacts | None:
    """Read date, NF number and value back from a hand-made file name."""
    match = _FILENAME_PREFIX_RE.match(name)
    if not match:
        return None
    day, month, year, number = match.groups()
    try:
        emitted = date(int(year), int(month), int(day))
    except ValueError:
        emitted = None
    amounts = _MONEY_IN_NAME_RE.findall(name[match.end() :])
    issuer_hint = name[match.end() :]
    if amounts:
        issuer_hint = issuer_hint[: issuer_hint.rfind(amounts[-1])]
    issuer_hint = issuer_hint.removesuffix(".pdf").strip(" -_[]")
    return FilenameFacts(
        emission_date=emitted,
        nf_number=number.replace(".", "").lstrip("0") or "0",
        total_value=_decimal_or_none(amounts[-1].replace(".", "").replace(",", "."))
        if amounts
        else None,
        issuer_hint=issuer_hint or None,
    )


def _deaccent(text: str) -> str:
    """Remove accents but keep punctuation, so printed dates stay parseable."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def receipt_claims(pdf: Path) -> tuple[str | None, str | None]:
    """Read the emission date and total the receipt stub prints, if it has them.

    Used only for verification: it is deliberately a different label, in a
    different part of the page, from the cells the parser reads. The stub wraps
    over a few printed rows, so those rows are joined before matching.
    """
    try:
        document = load_document(pdf)
    except Exception:
        return None, None
    if not document.pages:
        return None, None
    first_page = document.pages[0]
    stub_text = " ".join(_deaccent(line.text) for line in first_page.lines[:8])
    date_match = _STUB_DATE_RE.search(stub_text)
    value_match = _STUB_VALUE_RE.search(stub_text)
    return (
        date_match.group(1) if date_match else None,
        value_match.group(1) if value_match else None,
    )


def compare(pdf: Path, xml_facts: dict[str, XmlFacts]) -> Comparison:
    """Analyse one PDF and compare the result with both oracles."""
    analysis = analyze_file(pdf)
    outcome = analysis.outcome
    comparison = Comparison(source=str(pdf), status=outcome.status.value)
    comparison.parser_id = outcome.parser_id
    comparison.reason = outcome.reason
    comparison.access_key = (outcome.access_key or "").replace(" ", "") or None
    if outcome.warnings:
        comparison.notes.extend(outcome.warnings)

    name_facts = parse_filename_facts(pdf.name)
    xml = xml_facts.get(comparison.access_key or "")
    comparison.xml_key = xml.key if xml else None
    if xml is None and comparison.access_key and name_facts is None:
        comparison.notes.append("no XML and no readable file name")

    if outcome.status is not Status.SUCCESS:
        return comparison

    if xml is not None:
        comparison.checks["nf_number"] = _verdict(
            outcome.nf_number, xml.nf_number
        )
        comparison.checks["emission_date"] = _verdict(
            outcome.emission_date, _format_date(xml.emission_date)
        )
        comparison.checks["total_value"] = _verdict(
            _decimal_of(outcome.total_value), xml.total_value
        )
        comparison.checks["issuer"] = _issuer_verdict(outcome.issuer, xml.issuer)
        comparison.checks["access_key_matches_xml"] = "agrees"

    if name_facts is not None:
        prefix = "name: "
        comparison.checks[prefix + "emission_date"] = _verdict(
            outcome.emission_date, _format_date(name_facts.emission_date)
        )
        comparison.checks[prefix + "nf_number"] = _verdict(
            outcome.nf_number, name_facts.nf_number
        )
        comparison.checks[prefix + "total_value"] = _verdict(
            _decimal_of(outcome.total_value), name_facts.total_value
        )
        if name_facts.issuer_hint and xml is None:
            comparison.checks[prefix + "issuer"] = _issuer_verdict(
                outcome.issuer, name_facts.issuer_hint
            )

    stub_date, stub_value = receipt_claims(pdf)
    if stub_date is not None or stub_value is not None:
        comparison.checks["stub: emission_date"] = _verdict(
            outcome.emission_date, stub_date
        )
        comparison.checks["stub: total_value"] = _verdict(
            _decimal_of(outcome.total_value),
            money_to_decimal(stub_value) if stub_value else None,
        )
    return comparison


def _format_date(value: date | None) -> str | None:
    return None if value is None else f"{value.day:02d}/{value.month:02d}/{value.year:04d}"


def _decimal_of(printed: str | None) -> Decimal | None:
    return money_to_decimal(printed) if printed else None


def _verdict(extracted, expected) -> str:
    if expected is None:
        return ORACLE_MISSING
    if extracted is None:
        return ORACLE_MISMATCH
    return ORACLE_AGREEMENT if extracted == expected else ORACLE_MISMATCH


def _issuer_verdict(extracted: str | None, expected: str | None) -> str:
    if not expected:
        return ORACLE_MISSING
    if not extracted:
        return ORACLE_MISMATCH
    ratio = difflib.SequenceMatcher(
        None, _issuer_key(extracted), _issuer_key(expected)
    ).ratio()
    if ratio == 1.0:
        return ORACLE_AGREEMENT
    if ratio >= 0.75:
        return f"differs a little ({ratio:.2f})"
    return ORACLE_MISMATCH


def _issuer_key(name: str) -> str:
    return normalize_text(name).replace(" ", "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="folder with the PDFs and XMLs")
    parser.add_argument("--report-dir", default="local_output/eval")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--list", type=int, default=40, help="how many mismatches to print")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    xml_facts = load_xml_facts(data_root)
    pdfs = collect_sources([data_root], [])
    if args.limit:
        pdfs = pdfs[: args.limit]

    comparisons: list[Comparison] = []
    for index, pdf in enumerate(pdfs, start=1):
        print(f"\rAnalysing {index} of {len(pdfs)}...", end="", flush=True)
        comparisons.append(compare(pdf, xml_facts))
    print()

    summary = _summarise(comparisons, xml_facts)
    _write_reports(report_dir, comparisons, summary)
    print(_render_summary(summary, comparisons, args.list))
    print(f"\nReports: {report_dir.resolve()}")
    return 0


def _summarise(comparisons: list[Comparison], xml_facts: dict[str, XmlFacts]) -> dict:
    processed = [item for item in comparisons if item.status == Status.SUCCESS.value]
    with_xml = [item for item in processed if item.xml_key]
    without_xml = [item for item in processed if not item.xml_key]
    mismatched = [item for item in processed if item.mismatches]
    return {
        "pdfs": len(comparisons),
        "processed": len(processed),
        "failed": len(comparisons) - len(processed),
        "compared_with_xml": len(with_xml),
        "without_xml": len(without_xml),
        "with_any_mismatch": len(mismatched),
        "xml_files": len(xml_facts),
        "checks": _count_checks(processed),
        "failures_by_code": _count_failures(comparisons),
    }


def _count_checks(processed: list[Comparison]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for item in processed:
        for name, verdict in item.checks.items():
            bucket = counts.setdefault(name, {})
            bucket[verdict] = bucket.get(verdict, 0) + 1
    return counts


def _count_failures(comparisons: list[Comparison]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in comparisons:
        if item.status == Status.SUCCESS.value:
            continue
        key = item.reason or item.status
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: -pair[1]))


def _write_reports(
    report_dir: Path, comparisons: list[Comparison], summary: dict
) -> None:
    (report_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    check_names = sorted({name for item in comparisons for name in item.checks})
    with (report_dir / "comparisons.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["source", "status", "parser", "access_key", "xml_key"] + check_names + ["notes"])
        for item in comparisons:
            writer.writerow(
                [
                    Path(item.source).name,
                    item.status,
                    item.parser_id or "",
                    item.access_key or "",
                    item.xml_key or "",
                ]
                + [item.checks.get(name, "") for name in check_names]
                + [" | ".join(item.notes)]
            )


def _render_summary(summary: dict, comparisons: list[Comparison], limit: int) -> str:
    lines = [
        f"PDFs analysed          : {summary['pdfs']}",
        f"processed successfully : {summary['processed']}",
        f"failed                 : {summary['failed']}",
        f"XML files indexed      : {summary['xml_files']}",
        f"compared with an XML   : {summary['compared_with_xml']}",
        f"PDFs without any XML   : {summary['without_xml']}",
        f"files with a mismatch  : {summary['with_any_mismatch']}",
        "",
        "checks:",
    ]
    for name, counts in summary["checks"].items():
        extra = {
            key: value
            for key, value in counts.items()
            if key not in (ORACLE_AGREEMENT, ORACLE_MISMATCH, ORACLE_MISSING)
        }
        lines.append(
            f"  {name:<28} agrees={counts.get(ORACLE_AGREEMENT, 0):<5}"
            f" mismatch={counts.get(ORACLE_MISMATCH, 0):<5}"
            f" no-oracle={counts.get(ORACLE_MISSING, 0):<5}"
            + (f" {extra}" if extra else "")
        )
    if summary["failures_by_code"]:
        lines.append("")
        lines.append("failures:")
        for reason, count in summary["failures_by_code"].items():
            lines.append(f"  {count:>4} x {reason}")

    interesting = [
        item for item in comparisons if item.mismatches or item.notes or item.status != Status.SUCCESS.value
    ]
    if interesting:
        lines.append("")
        lines.append(f"first {min(limit, len(interesting))} files needing a look:")
        for item in interesting[:limit]:
            lines.append(f"  {Path(item.source).name}")
            lines.append(f"     status={item.status} parser={item.parser_id}")
            if item.reason:
                lines.append(f"     reason={item.reason}")
            for name, verdict in item.checks.items():
                if verdict != ORACLE_AGREEMENT:
                    lines.append(f"     {name}: {verdict}")
            for note in item.notes:
                lines.append(f"     note: {note}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
