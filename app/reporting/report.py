"""Batch reports: CSV and JSON for machines, HTML for the person using it.

Every run writes a report, so a batch never has to be re-checked by hand.
"""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

from ..core.models import BatchSummary, FileOutcome, Status

#: Column order of the CSV/JSON report, matching the agreed field list.
REPORT_FIELDS = (
    "source_filename",
    "status",
    "parser",
    "access_key",
    "nf_number",
    "emission_date",
    "valor_total_da_nota",
    "issuer",
    "target_filename",
    "reason",
    "warnings",
)

CSV_DELIMITER = ";"  # Excel in pt-BR opens semicolon-separated files directly.


def write_reports(summary: BatchSummary, directory: Path | None = None) -> dict[str, Path]:
    """Write every report; ``directory`` defaults to the batch directory.

    Returns the paths written, keyed ``csv``, ``json`` and ``html``.
    """
    target = Path(directory) if directory is not None else summary.output_directory
    if target is None:
        return {}
    target.mkdir(parents=True, exist_ok=True)
    csv_path = target / "batch_report.csv"
    json_path = target / "batch_report.json"
    html_path = target / "batch_report.html"
    _write_csv(summary, csv_path)
    _write_json(summary, json_path)
    _write_html(summary, html_path)
    return {"csv": csv_path, "json": json_path, "html": html_path}


def report_rows(summary: BatchSummary) -> list[dict[str, str]]:
    """One dictionary per file, in :data:`REPORT_FIELDS` order."""
    return [_row(outcome) for outcome in summary.outcomes]


def _row(outcome: FileOutcome) -> dict[str, str]:
    return {
        "source_filename": outcome.source_path.name,
        "status": outcome.status.value,
        "parser": outcome.parser_id or "",
        "access_key": outcome.access_key or "",
        "nf_number": outcome.nf_number or "",
        "emission_date": outcome.emission_date or "",
        "valor_total_da_nota": outcome.total_value or "",
        "issuer": outcome.issuer or "",
        "target_filename": outcome.target_filename or "",
        "reason": outcome.reason or "",
        "warnings": " | ".join(outcome.warnings),
    }


def _write_csv(summary: BatchSummary, path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(REPORT_FIELDS), delimiter=CSV_DELIMITER
        )
        writer.writeheader()
        writer.writerows(report_rows(summary))


def _write_json(summary: BatchSummary, path: Path) -> None:
    payload = {
        "started_at": summary.started_at.isoformat(timespec="seconds"),
        "finished_at": summary.finished_at.isoformat(timespec="seconds"),
        "output_directory": str(summary.output_directory or ""),
        "totals": {
            "analyzed": summary.total,
            "renamed": summary.succeeded,
            "skipped": summary.skipped,
            "errors": summary.errors,
        },
        "failures_by_code": {
            code.value: count for code, count in summary.failures_by_code().items()
        },
        "files": report_rows(summary),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_html(summary: BatchSummary, path: Path) -> None:
    rows = []
    for outcome in summary.outcomes:
        rows.append(
            "<tr class=\"{style}\">"
            "<td>{source}</td><td>{status}</td>"
            "<td>{target}</td><td>{reason}</td></tr>".format(
                style=outcome.status.value,
                source=escape(outcome.source_path.name),
                status=escape(_status_label(outcome.status)),
                target=escape(outcome.target_filename or "-"),
                reason=escape(outcome.reason or ""),
            )
        )

    failures = summary.failures_by_code()
    failure_rows = "".join(
        f"<li><strong>{count}</strong> {escape(code.value)}</li>"
        for code, count in failures.items()
    )
    document = _HTML_TEMPLATE.format(
        started=escape(summary.started_at.strftime("%d/%m/%Y %H:%M:%S")),
        finished=escape(summary.finished_at.strftime("%d/%m/%Y %H:%M:%S")),
        total=summary.total,
        renamed=summary.succeeded,
        skipped=summary.skipped,
        errors=summary.errors,
        failure_rows=failure_rows or "<li>No failures.</li>",
        rows="\n".join(rows),
    )
    path.write_text(document, encoding="utf-8")


def _status_label(status: Status) -> str:
    return {
        Status.SUCCESS: "renamed",
        Status.SKIPPED: "skipped",
        Status.ERROR: "error",
    }[status]


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DANFE renamer batch report</title>
<style>
 body {{ font-family: Segoe UI, Arial, sans-serif; margin: 2rem; color: #1d1d1f; }}
 h1 {{ font-size: 1.4rem; }}
 .summary li {{ margin: .2rem 0; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 1.5rem; font-size: .9rem; }}
 th, td {{ border-bottom: 1px solid #d8d8de; padding: .4rem .5rem; text-align: left; vertical-align: top; }}
 tr.success td:nth-child(2) {{ color: #1a7f37; }}
 tr.skipped td:nth-child(2) {{ color: #9a6700; }}
 tr.error td:nth-child(2) {{ color: #b42318; }}
</style>
</head>
<body>
<h1>DANFE renamer — batch report</h1>
<ul class="summary">
 <li>Started: {started}</li>
 <li>Finished: {finished}</li>
 <li>{total} files analyzed</li>
 <li>{renamed} renamed successfully</li>
 <li>{skipped} skipped</li>
 <li>{errors} errors</li>
</ul>
<h2>Failures by reason</h2>
<ul>{failure_rows}</ul>
<table>
 <thead><tr><th>Source file</th><th>Status</th><th>New name</th><th>Reason</th></tr></thead>
 <tbody>
{rows}
 </tbody>
</table>
</body>
</html>
"""
