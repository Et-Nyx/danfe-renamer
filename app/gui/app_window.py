"""The application window.

The interface is deliberately thin: it collects input paths, runs
:func:`app.core.pipeline.run_batch` on a worker thread, and shows the result.
No extraction or filesystem decision is made here - the safety rules live in the
pipeline, so the GUI cannot weaken them.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..cli import collect_sources, default_output_root
from .. import __version__
from ..core.models import BatchSummary, FileOutcome, Status
from ..core.pipeline import run_batch
from .i18n import LANGUAGE_NAMES, Translator, summarise, translate_failure
from .settings import load_language, save_language

POLL_INTERVAL_MS = 80

#: Optional drag-and-drop; the window works without it, so a missing package is
#: not an error.
try:  # pragma: no cover - depends on the machine
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except Exception:  # pragma: no cover
    DND_FILES = None
    TkinterDnD = None
    HAS_DND = False


def build_window() -> "RenamerWindow":
    """Create the main window, using drag-and-drop support when available."""
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    return RenamerWindow(root)


class RenamerWindow:
    """The one screen: choose files, process, read the result."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.translate = Translator(load_language())
        self.selected: list[Path] = []
        self.summary: BatchSummary | None = None
        self.details_window: tk.Toplevel | None = None
        self._events: queue.Queue = queue.Queue()
        self._running = False

        self._build_widgets()
        self.translate.subscribe(self._apply_language)
        self._apply_language()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(POLL_INTERVAL_MS, self._drain_events)

    # ---------------------------------------------------------------- layout

    def _build_widgets(self) -> None:
        self.root.minsize(720, 560)
        self.frame = ttk.Frame(self.root, padding=16)
        self.frame.pack(fill="both", expand=True)

        header = ttk.Frame(self.frame)
        header.pack(fill="x")
        self.title_label = ttk.Label(header, font=("Segoe UI", 16, "bold"))
        self.title_label.pack(side="left")
        self.language_label = ttk.Label(header)
        self.language_label.pack(side="right", padx=(8, 4))
        self.language_box = ttk.Combobox(
            header,
            state="readonly",
            width=12,
            values=[LANGUAGE_NAMES[code] for code in LANGUAGE_NAMES],
        )
        self.language_box.set(LANGUAGE_NAMES[self.translate.language])
        self.language_box.bind("<<ComboboxSelected>>", self._on_language_selected)
        self.language_box.pack(side="right")

        self.subtitle_label = ttk.Label(self.frame, wraplength=640, justify="left")
        self.subtitle_label.pack(fill="x", pady=(6, 10))

        self.drop_hint_label = ttk.Label(self.frame, anchor="center", foreground="#555555")
        self.drop_hint_label.pack(fill="x", pady=(0, 6))

        buttons = ttk.Frame(self.frame)
        buttons.pack(fill="x")
        self.choose_files_button = ttk.Button(buttons, command=self.choose_files)
        self.choose_files_button.pack(side="left")
        self.choose_folder_button = ttk.Button(buttons, command=self.choose_folder)
        self.choose_folder_button.pack(side="left", padx=6)
        self.remove_selected_button = ttk.Button(buttons, command=self.remove_selected)
        self.remove_selected_button.pack(side="left")
        self.clear_button = ttk.Button(buttons, command=self.clear_list)
        self.clear_button.pack(side="left", padx=6)

        list_frame = ttk.Frame(self.frame)
        list_frame.pack(fill="both", expand=True, pady=10)
        self.file_list = tk.Listbox(list_frame, selectmode="extended", activestyle="none")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=scrollbar.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._enable_drop_target()

        self.selection_label = ttk.Label(self.frame)
        self.selection_label.pack(fill="x")

        self.progress = ttk.Progressbar(self.frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(8, 4))
        self.progress_label = ttk.Label(self.frame)
        self.progress_label.pack(fill="x")

        actions = ttk.Frame(self.frame)
        actions.pack(fill="x", pady=(10, 0))
        self.process_button = ttk.Button(actions, command=self.start_processing)
        self.process_button.pack(side="left")
        self.open_output_button = ttk.Button(actions, command=self.open_output_folder)
        self.open_output_button.pack(side="left", padx=6)
        self.details_button = ttk.Button(actions, command=self.show_details)
        self.details_button.pack(side="left")
        self.another_button = ttk.Button(actions, command=self.reset_for_next_batch)
        self.another_button.pack(side="left", padx=6)

        self.result_frame = ttk.LabelFrame(self.frame, padding=10)
        self.result_labels: list[ttk.Label] = []
        for _ in range(4):
            label = ttk.Label(self.result_frame)
            label.pack(anchor="w")
            self.result_labels.append(label)
        self.failure_label = ttk.Label(self.result_frame)
        self.failure_label.pack(anchor="w", pady=(6, 0))
        self.output_label = ttk.Label(self.result_frame, foreground="#555555")
        self.output_label.pack(anchor="w", pady=(4, 0))

        self.safety_label = ttk.Label(self.frame, foreground="#1a7f37")
        self.safety_label.pack(fill="x", pady=(10, 0))

        self._refresh_selection()
        self._refresh_result_visibility()

    def _enable_drop_target(self) -> None:
        if not HAS_DND:  # pragma: no cover - exercised only without the package
            return
        try:
            self.file_list.drop_target_register(DND_FILES)
            self.file_list.dnd_bind("<<Drop>>", self._on_drop)
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:  # pragma: no cover - window without drop support
            pass

    # -------------------------------------------------------------- language

    def _apply_language(self) -> None:
        t = self.translate
        self.root.title(f"{t('window_title')} {__version__}")
        self.title_label.configure(text=t("headline"))
        self.subtitle_label.configure(text=t("subtitle"))
        self.language_label.configure(text=t("language_label"))
        self.drop_hint_label.configure(text=t("drop_hint"))
        self.choose_files_button.configure(text=t("choose_files"))
        self.choose_folder_button.configure(text=t("choose_folder"))
        self.remove_selected_button.configure(text=t("remove_selected"))
        self.clear_button.configure(text=t("clear_list"))
        self.process_button.configure(text=t("process"))
        self.open_output_button.configure(text=t("open_output"))
        self.details_button.configure(text=t("view_details"))
        self.another_button.configure(text=t("process_another"))
        self.failure_label.configure(text=t("failures_by_reason"))
        self.safety_label.configure(text=t("safety_note"))
        self.language_box.set(LANGUAGE_NAMES[self.translate.language])
        self._refresh_selection()
        self._refresh_result_visibility()
        if self.summary is not None:
            self._show_summary(self.summary)
        if self.details_window is not None and self.details_window.winfo_exists():
            self._close_details()
            self.show_details()

    def _on_language_selected(self, _event=None) -> None:
        chosen = self.language_box.get()
        for code, name in LANGUAGE_NAMES.items():
            if name == chosen:
                self.translate.set_language(code)
                save_language(code)
                return

    # ----------------------------------------------------------------- input

    def choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title=self.translate("choose_files"),
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")],
        )
        self._add_sources([Path(path) for path in paths])

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(title=self.translate("choose_folder"))
        if folder:
            self._add_sources([Path(folder)])

    def remove_selected(self) -> None:
        for index in sorted(self.file_list.curselection(), reverse=True):
            del self.selected[index]
        self._refresh_selection()

    def clear_list(self) -> None:
        self.selected.clear()
        self._refresh_selection()

    def _on_drop(self, event) -> None:  # pragma: no cover - needs a real drop
        raw = str(event.data)
        paths: list[Path] = []
        token = ""
        inside_braces = False
        for character in raw:
            if character == "{":
                inside_braces = True
            elif character == "}":
                inside_braces = False
                paths.append(Path(token))
                token = ""
            elif character == " " and not inside_braces:
                if token:
                    paths.append(Path(token))
                    token = ""
            else:
                token += character
        if token:
            paths.append(Path(token))
        self._add_sources(paths)

    def _add_sources(self, paths: list[Path]) -> None:
        excluded = []
        if self.summary is not None and self.summary.output_directory is not None:
            excluded.append(self.summary.output_directory)
        for found in collect_sources(paths, excluded):
            if found not in self.selected:
                self.selected.append(found)
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        self.file_list.delete(0, tk.END)
        for path in self.selected:
            self.file_list.insert(tk.END, str(path))
        if self.selected:
            self.selection_label.configure(
                text=self.translate("selected_files", count=len(self.selected))
            )
        else:
            self.selection_label.configure(text=self.translate("no_files"))

    # ------------------------------------------------------------ processing

    def start_processing(self) -> None:
        if self._running:
            return
        if not self.selected:
            messagebox.showinfo(
                self.translate("window_title"), self.translate("no_files_alert")
            )
            return

        self.summary = None
        self._running = True
        self.process_button.state(["disabled"])
        self.progress.configure(value=0)
        self._refresh_result_visibility()
        sources = list(self.selected)
        output_root = default_output_root(sources)
        thread = threading.Thread(
            target=self._run_batch, args=(sources, output_root), daemon=True
        )
        thread.start()

    def _run_batch(self, sources: list[Path], output_root: Path) -> None:
        """Worker thread: never touches Tk directly, only the queue."""
        try:
            summary = run_batch(sources, output_root, progress=self._report_progress)
        except Exception as exc:  # pragma: no cover - unexpected failure
            self._events.put(("error", f"{type(exc).__name__}: {exc}"))
            return
        self._events.put(("finished", summary))

    def _report_progress(self, index: int, total: int, source: Path) -> None:
        self._events.put(("progress", index, total, source))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.root.after(POLL_INTERVAL_MS, self._drain_events)

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "progress":
            _, index, total, source = event
            self.progress.configure(value=100.0 * index / max(total, 1))
            self.progress_label.configure(
                text=f"{self.translate('processing')} {index} {self.translate('of')} {total} — {Path(source).name}"
            )
        elif kind == "finished":
            self._running = False
            self.process_button.state(["!disabled"])
            self.summary = event[1]
            self.progress.configure(value=100)
            self.progress_label.configure(text="")
            self._show_summary(self.summary)
            self._refresh_result_visibility()
        elif kind == "error":  # pragma: no cover - unexpected failure
            self._running = False
            self.process_button.state(["!disabled"])
            messagebox.showerror(
                self.translate("error_title"), str(event[1])
            )

    def _refresh_result_visibility(self) -> None:
        if self.summary is None:
            self.result_frame.pack_forget()
            self.open_output_button.state(["disabled"])
            self.details_button.state(["disabled"])
            return
        self.result_frame.pack(fill="x", pady=(10, 0))
        self.open_output_button.state(
            ["!disabled"] if self.summary.output_directory else ["disabled"]
        )
        self.details_button.state(
            ["!disabled"] if self.summary.outcomes else ["disabled"]
        )

    def _show_summary(self, summary: BatchSummary) -> None:
        lines = summarise(summary, self.translate)
        for label, text in zip(
            self.result_labels,
            (lines.analyzed, lines.renamed, lines.skipped, lines.errors),
        ):
            label.configure(text=text)
        if lines.failures:
            self.failure_label.configure(
                text=self.translate("failures_by_reason")
                + ": "
                + "; ".join(f"{name} ({count})" for name, count in lines.failures)
            )
        else:
            self.failure_label.configure(text=self.translate("all_good"))
        if summary.output_directory is not None:
            self.output_label.configure(
                text=self.translate("output_directory", path=summary.output_directory)
            )
        else:
            self.output_label.configure(text="")

    def reset_for_next_batch(self) -> None:
        self.summary = None
        self.selected.clear()
        self.progress.configure(value=0)
        self.progress_label.configure(text="")
        self._refresh_selection()
        self._refresh_result_visibility()

    def open_output_folder(self) -> None:
        if self.summary is None or self.summary.output_directory is None:
            return
        directory = Path(self.summary.output_directory)
        try:
            if sys.platform.startswith("win"):
                import os

                os.startfile(directory)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(directory)])
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except OSError as exc:
            messagebox.showerror(
                self.translate("error_title"),
                self.translate("report_open_failed", error=exc),
            )

    # --------------------------------------------------------------- details

    def show_details(self) -> None:
        if self.summary is None:
            return
        if self.details_window is not None and self.details_window.winfo_exists():
            self.details_window.lift()
            return

        t = self.translate
        window = tk.Toplevel(self.root)
        self.details_window = window
        window.title(t("details_title"))
        window.geometry("900x520")
        window.transient(self.root)

        table = ttk.Treeview(
            window, columns=("status", "target", "reason"), show="headings"
        )
        table.heading("#0", text=t("column_source"))
        table.heading("status", text=t("column_status"))
        table.heading("target", text=t("column_target"))
        table.heading("reason", text=t("column_reason"))
        table.column("#0", width=280)
        table.column("status", width=90, anchor="center")
        table.column("target", width=300)
        table.column("reason", width=220)
        table.pack(fill="both", expand=True, side="top")

        status_names = {
            Status.SUCCESS: t("status_success"),
            Status.SKIPPED: t("status_skipped"),
            Status.ERROR: t("status_error"),
        }
        for index, outcome in enumerate(self.summary.outcomes):
            table.insert(
                "",
                "end",
                iid=str(index),
                text=outcome.source_path.name,
                values=(
                    status_names[outcome.status],
                    outcome.target_filename or "-",
                    outcome.reason or "",
                ),
            )

        detail_box = ttk.LabelFrame(window, padding=10)
        detail_box.pack(fill="both", expand=False, side="bottom")
        detail_label = ttk.Label(detail_box, justify="left", anchor="w")
        detail_label.pack(fill="both")
        detail_label.configure(text=t("select_row_hint"))

        def describe(outcome: FileOutcome) -> str:
            rows = [
                f"{t('field_parser')}: {outcome.parser_id or '-'}",
                f"{t('field_access_key')}: {outcome.access_key or '-'}",
                f"{t('field_nf_number')}: {outcome.nf_number or '-'}",
                f"{t('field_date')}: {outcome.emission_date or '-'}",
                f"{t('field_value')}: {outcome.total_value or '-'}",
                f"{t('field_issuer')}: {outcome.issuer or '-'}",
                f"{t('field_destination')}: {outcome.destination_path or '-'}",
                f"{t('field_duration')}: {t('seconds', value=outcome.duration_seconds)}",
            ]
            if outcome.warnings:
                rows.append(t("field_warnings") + ": " + "; ".join(outcome.warnings))
            if outcome.failure_code is not None:
                rows.append(
                    translate_failure(outcome.failure_code, t)
                    + (f" ({outcome.failure_code.value})" if outcome.reason else "")
                )
            return "\n".join(rows)

        def on_select(_event=None) -> None:
            selection = table.selection()
            if not selection:
                return
            outcome = self.summary.outcomes[int(selection[0])]
            detail_label.configure(text=describe(outcome))

        table.bind("<<TreeviewSelect>>", on_select)
        window.protocol("WM_DELETE_WINDOW", self._close_details)

    def _close_details(self) -> None:
        if self.details_window is not None and self.details_window.winfo_exists():
            self.details_window.destroy()
        self.details_window = None

    def _on_close(self) -> None:
        """Closing mid-run is allowed; a batch stops at the next file.

        The pipeline copies each file whole and never overwrites, so whatever was
        written before the window closed stays consistent, and the report only
        describes the files that were reached.
        """
        self._close_details()
        self.root.destroy()
