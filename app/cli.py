"""Command-line entry point: the same pipeline the GUI uses, without the GUI.

Examples
--------
Batch from a folder, writing renamed copies next to it::

    python -m app.cli "C:/notas" --output "C:/notas/renomeadas"

Analysis only, no files written (used to measure a corpus)::

    python -m app.cli "C:/notas" --dry-run --report C:/tmp/reports --verbose

Environment report, for a support request (no document data in it)::

    python -m app.cli --diagnostics
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from . import __version__
from .core.models import BatchSummary, Status
from .core.pipeline import run_batch
from .reporting.report import write_reports

DEFAULT_OUTPUT_DIR_NAME = "DANFE_Renamed"
DIAGNOSTICS_FILE_NAME = "danfe_renamer_diagnostics.txt"


def collect_diagnostics(*, probe_window: bool = True) -> dict[str, str]:
    """Version and environment facts, deliberately free of document data.

    Read from a machine the application misbehaves on, this says which build ran
    and whether its optional pieces (Tk, drag-and-drop, the PDF library) were
    usable there. With ``probe_window`` the window is built for real, so a build
    whose window cannot open says so here instead of by the person using it; it
    appears briefly and is closed again. Tests skip that part: one process
    should hold one Tk root, and the test process already has one.
    """
    import pymupdf

    from .gui.app_window import HAS_DND

    found: dict[str, str] = {
        "application": f"DANFE Renamer {__version__}",
        "python": sys.version.split()[0],
        "operating_system": platform.platform(),
        "packaged_executable": str(bool(getattr(sys, "frozen", False))),
        "pymupdf": _pymupdf_version(pymupdf),
    }
    try:
        import tkinter

        found["tkinter"] = f"Tk {tkinter.TkVersion}"
    except Exception as exc:  # pragma: no cover - broken Tk installation
        found["tkinter"] = f"unavailable: {type(exc).__name__}: {exc}"

    if not HAS_DND:
        found["drag_and_drop"] = "not installed (the window falls back to buttons)"
    if not probe_window:
        if HAS_DND:
            found["drag_and_drop"] = "tkinterdnd2 is installed (the window reports it when built)"
        return found

    from .gui.app_window import build_window

    try:
        window = build_window()
        window.root.withdraw()
        window.root.update()
        found["window"] = "opens"
        if HAS_DND and window.dnd_available:
            version = window.root.tk.call("package", "require", "tkdnd")
            found["drag_and_drop"] = f"tkdnd {version}; the window accepts drops"
        elif HAS_DND:
            found["drag_and_drop"] = "tkdnd is installed but the drop target was refused"
        window.root.destroy()
    except Exception as exc:  # pragma: no cover - machine without a window
        found["window"] = f"unavailable: {type(exc).__name__}: {exc}"
    return found


def _pymupdf_version(pymupdf) -> str:
    """The library's own version string, whichever attribute carries it."""
    version = getattr(pymupdf, "__version__", None)
    if isinstance(version, str) and version:
        return version
    parts = [str(part) for part in getattr(pymupdf, "version", ()) if part]
    return ".".join(parts) or "unknown"


def report_diagnostics(
    directory: Path | None = None, *, probe_window: bool = True
) -> Path:
    """Print the diagnostics and write the same lines to a file."""
    found = collect_diagnostics(probe_window=probe_window)
    lines = [f"{name}: {value}" for name, value in found.items()]
    for line in lines:
        print(line)
    target = Path(directory or Path.cwd()) / DIAGNOSTICS_FILE_NAME
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWritten to: {target}")
    return target


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
    parser.add_argument(
        "sources",
        nargs="*",
        help="PDF files and/or folders (omit with --diagnostics)",
    )
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
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="report version and environment (Tk, drag-and-drop, PDF library), then exit",
    )
    parser.add_argument("--limit", type=int, help="process at most N files")
    parser.add_argument(
        "--verbose", action="store_true", help="print one line per file"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.diagnostics:
        report_diagnostics()
        return 0
    if not args.sources:
        print("Nothing to do: give one or more PDF files or folders.", file=sys.stderr)
        return 1
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
