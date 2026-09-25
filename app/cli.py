"""Command-line entry point: the same pipeline the GUI uses, without the GUI.

Examples
--------
Batch from a folder, writing renamed copies next to it::

    python -m app.cli "C:/notas" --output "C:/notas/renomeadas"

Analysis only, no files written (used to measure a corpus)::

    python -m app.cli "C:/notas" --dry-run --report C:/tmp/reports --verbose
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core.models import BatchSummary, Status
from .core.pipeline import run_batch
from .reporting.report import write_reports

DEFAULT_OUTPUT_DIR_NAME = "DANFE_Renamed"


def collect_sources(paths: list[Path], excluded_dirs: list[Path]) -> list[Path]:
    """Expand files and folders into a sorted list of PDFs.

    Folders are searched recursively; anything inside an excluded directory (a
    previous batch output, for example) is left out.
    """
    excluded = [path.resolve() for path in excluded_dirs]
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(
                candidate
                for candidate in sorted(path.rglob("*.pdf"))
                if not _is_excluded(candidate, excluded)
            )
        elif path.suffix.lower() == ".pdf":
            found.append(path)
    unique: dict[str, Path] = {}
    for candidate in found:
        unique.setdefault(str(candidate.resolve()).lower(), candidate)
    return list(unique.values())


def _is_excluded(candidate: Path, excluded: list[Path]) -> bool:
    resolved = candidate.resolve()
    return any(parent in resolved.parents for parent in excluded)


def default_output_root(sources: list[Path]) -> Path:
    """Put the batch directory next to the input when there is a single folder."""
    parents = {source.parent for source in sources}
    if len(parents) == 1:
        return parents.pop() / DEFAULT_OUTPUT_DIR_NAME
    return Path.home() / "Documents" / DEFAULT_OUTPUT_DIR_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="danfe-renamer",
        description="Rename DANFE/NF-e PDFs into copies with the agreed name pattern.",
    )
    parser.add_argument("sources", nargs="+", help="PDF files and/or folders")
    parser.add_argument(
        "--output",
        help=f"root folder for the batch directory (default: <input>/{DEFAULT_OUTPUT_DIR_NAME})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="analyse and report only; do not create or copy any file",
    )
    parser.add_argument(
        "--report",
        help="folder to also write the report into (the batch folder gets one too)",
    )
    parser.add_argument("--limit", type=int, help="process at most N files")
    parser.add_argument(
        "--verbose", action="store_true", help="print one line per file"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    excluded = [Path(args.output)] if args.output else []
    sources = collect_sources([Path(item) for item in args.sources], excluded)
    if args.limit:
        sources = sources[: args.limit]
    if not sources:
        print("No PDF files found.", file=sys.stderr)
        return 1

    output_root = None if args.dry_run else Path(
        args.output or default_output_root(sources)
    )
    summary = run_batch(
        sources,
        output_root,
        copy_files=not args.dry_run,
        progress=_progress_printer() if not args.verbose else None,
    )
    extra_report_directory: Path | None = None
    if args.report:
        extra_report_directory = Path(args.report)
        write_reports(summary, directory=extra_report_directory)

    print_summary(summary, verbose=args.verbose)
    if extra_report_directory is not None:
        print(f"Reports also written to: {extra_report_directory}")
    return 0 if summary.skipped == 0 and summary.errors == 0 else 1


def _progress_printer():
    def progress(index: int, total: int, source: Path) -> None:
        print(f"\rProcessing {index} of {total}...", end="", file=sys.stderr)
        if index == total:
            print(file=sys.stderr)

    return progress


def print_summary(summary: BatchSummary, *, verbose: bool = False) -> None:
    """Print the batch summary, and optionally one line per file."""
    if verbose:
        for outcome in summary.outcomes:
            marker = {
                Status.SUCCESS: "OK  ",
                Status.SKIPPED: "SKIP",
                Status.ERROR: "ERR ",
            }[outcome.status]
            detail = outcome.target_filename or outcome.reason or ""
            print(f"{marker} {outcome.source_path.name}\n     -> {detail}")
            for warning in outcome.warnings:
                print(f"     ! {warning}")

    print(f"{summary.total} files analyzed")
    print(f"{summary.succeeded} renamed successfully")
    print(f"{summary.skipped} skipped")
    print(f"{summary.errors} errors")
    for code, count in summary.failures_by_code().items():
        print(f"  {count} x {code.value}")
    if summary.output_directory is not None:
        print(f"Output: {summary.output_directory}")
    for kind, path in summary.report_paths.items():
        print(f"Report ({kind}): {path}")


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
