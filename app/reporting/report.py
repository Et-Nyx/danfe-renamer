"""Batch reports: CSV and JSON for machines, HTML for the person using it.

Every run writes a report, so a batch never has to be re-checked by hand.

Two of the columns keep a machine from ever having to read a sentence: ``status``
and ``failure_code`` are stable values that do not change with the language. The
sentences - ``failure_message``, and every heading in the HTML - are written in
the language the batch was run in.
"""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

from .. import __version__
from ..core.models import BatchSummary, FileOutcome
from ..core.wording import (
    DEFAULT_LANGUAGE,
    counted,
    message as failure_message,
    report as report_text,
    status_label,
)

#: Column order of the CSV/JSON report, matching the agreed field list.
REPORT_FIELDS = (
    "source_filename",
    "status",
    "failure_code",
    "failure_message",
    "parser",
    "access_key",
    "nf_number",
    "emission_date",
    "valor_total_da_nota",
    "issuer",
    "recipient",
    "name_source",
    "target_filename",
    "reason",
    "warnings",
    "source_type",
    "document_model",
    "generated",
)

CSV_DELIMITER = ";"  # Excel in pt-BR opens semicolon-separated files directly.


def write_reports(
    summary: BatchSummary,
    directory: Path | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> dict[str, Path]:
    """Write every report; ``directory`` defaults to the batch directory.

    ``language`` is the one the sentences in them are written in; the stable
    values (``status``, ``failure_code``) are the same in every language.

    Returns the paths written, keyed ``csv``, ``json`` and ``html``.
    """
    target = Path(directory) if directory is not None else summary.output_directory
    if target is None:
        return {}
    target.mkdir(parents=True, exist_ok=True)
    csv_path = target / "batch_report.csv"
    json_path = target / "batch_report.json"
    html_path = target / "batch_report.html"
    _write_csv(summary, csv_path, language)
    _write_json(summary, json_path, language)
    _write_html(summary, html_path, language)
    return {"csv": csv_path, "json": json_path, "html": html_path}


def report_rows(
    summary: BatchSummary, language: str = DEFAULT_LANGUAGE
) -> list[dict[str, str]]:
    """One dictionary per file, in :data:`REPORT_FIELDS` order."""
    return [_row(outcome, language) for outcome in summary.outcomes]


def _row(outcome: FileOutcome, language: str) -> dict[str, str]:
    code = outcome.failure_code
    return {
        "source_filename": outcome.source_path.name,
        "status": outcome.status.value,
        "failure_code": code.value if code is not None else "",
        "failure_message": failure_message(code, language) if code is not None else "",
        "parser": outcome.parser_id or "",
        "access_key": outcome.access_key or "",
        "nf_number": outcome.nf_number or "",
        "emission_date": outcome.emission_date or "",
        "valor_total_da_nota": outcome.total_value or "",
        "issuer": outcome.issuer or "",
        "recipient": outcome.recipient or "",
        "name_source": outcome.name_source or "",
        "target_filename": outcome.target_filename or "",
        # Kept verbatim: for XML, PDF and write failures this is the library's own
        # words, which no translation can improve and a support request needs.
        "reason": outcome.reason or "",
        "warnings": " | ".join(outcome.warnings),
        "source_type": outcome.source_type or "",
        "document_model": outcome.document_model or "",
        "generated": "true" if outcome.generated else "false",
    }


def _write_csv(summary: BatchSummary, path: Path, language: str) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(REPORT_FIELDS), delimiter=CSV_DELIMITER
        )
        writer.writeheader()
        writer.writerows(report_rows(summary, language))


def _write_json(summary: BatchSummary, path: Path, language: str) -> None:
    payload = {
        "application": "DANFE Renamer",
        "application_version": __version__,
        "language": language,
        "started_at": summary.started_at.isoformat(timespec="seconds"),
        "finished_at": summary.finished_at.isoformat(timespec="seconds"),
        "output_directory": str(summary.output_directory or ""),
        "totals": {
            "analyzed": summary.total,
            "renamed": summary.succeeded,
            "converted_from_xml": summary.converted,
            "skipped": summary.skipped,
            "errors": summary.errors,
        },
        "failures_by_code": {
            code.value: count for code, count in summary.failures_by_code().items()
        },
        "failures_by_message": {
            failure_message(code, language): count
            for code, count in summary.failures_by_code().items()
        },
        "files": report_rows(summary, language),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_html(summary: BatchSummary, path: Path, language: str) -> None:
    rows = []
    for outcome in summary.outcomes:
        rows.append(
            "<tr class=\"{style}\">"
            "<td>{source}</td><td>{status}</td>"
            "<td>{target}</td><td>{reason}</td></tr>".format(
                style=outcome.status.value,
                source=escape(outcome.source_path.name),
                status=escape(
                    status_label(
                        outcome.status, language, generated=outcome.generated
                    )
                ),
                target=escape(outcome.target_filename or "-"),
                reason=escape(_html_reason(outcome, language)),
            )
        )

    failures = summary.failures_by_code()
    failure_rows = "".join(
        f"<li><strong>{count}</strong> "
        f"{escape(failure_message(code, language))}</li>"
        for code, count in failures.items()
    )
    document = _HTML_TEMPLATE.format(
        language=escape(language),
        title=escape(report_text("title", language)),
        heading=escape(report_text("heading", language)),
        application=escape(report_text("application", language, version=__version__)),
        started=escape(report_text("started", language, when=summary.started_at.strftime("%d/%m/%Y %H:%M:%S"))),
        finished=escape(report_text("finished", language, when=summary.finished_at.strftime("%d/%m/%Y %H:%M:%S"))),
        total=escape(counted("analyzed", summary.total, language)),
        renamed=escape(counted("renamed", summary.succeeded, language)),
        converted=escape(counted("converted", summary.converted, language)),
        skipped=escape(counted("skipped", summary.skipped, language)),
        errors=escape(counted("errors", summary.errors, language)),
        failures_heading=escape(report_text("failures_heading", language)),
        failure_rows=failure_rows or escape(report_text("no_failures", language)),
        column_source=escape(report_text("column_source", language)),
        column_status=escape(report_text("column_status", language)),
        column_target=escape(report_text("column_target", language)),
        column_reason=escape(report_text("column_reason", language)),
        rows="\n".join(rows),
    )
    path.write_text(document, encoding="utf-8")


def _html_reason(outcome: FileOutcome, language: str) -> str:
    """What the report's reason column says for one file.

    The sentence a person reads first; the layer's own recorded detail follows it
    when there is one and it adds something, because that is what a support
    request asks for.
    """
    if outcome.failure_code is None:
        return outcome.reason or ""
    sentence = failure_message(outcome.failure_code, language)
    recorded = (outcome.reason or "").strip()
    if recorded and recorded not in sentence:
        return f"{sentence} - {recorded}"
    return sentence


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{language}">
<head>
<meta charset="utf-8">
<title>{title}</title>
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
<h1>{heading}</h1>
<ul class="summary">
 <li>{application}</li>
 <li>{started}</li>
 <li>{finished}</li>
 <li>{total}</li>
 <li>{renamed}</li>
 <li>{converted}</li>
 <li>{skipped}</li>
 <li>{errors}</li>
</ul>
<h2>{failures_heading}</h2>
<ul>{failure_rows}</ul>
<table>
 <thead><tr><th>{column_source}</th><th>{column_status}</th><th>{column_target}</th><th>{column_reason}</th></tr></thead>
 <tbody>
{rows}
 </tbody>
</table>
</body>
</html>
"""

__all__ = ["REPORT_FIELDS", "report_rows", "write_reports"]
