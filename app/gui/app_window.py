"""The application window.

The interface is deliberately thin: it collects input paths, runs
:func:`app.core.pipeline.run_batch` on a worker thread, and shows the result.
No extraction or filesystem decision is made here - the safety rules live in the
pipeline, so the GUI cannot weaken them.

Dropping files on the window is optional: :func:`build_window` uses
``tkinterdnd2`` when the machine has it and falls back to plain Tkinter when it
does not, so the window always opens and the buttons always work.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__
from ..cli import collect_sources, default_output_root
from ..core.wording import message as failure_message
from ..core.models import (
    FAILURE_MESSAGES,
    BatchSummary,
    FileOutcome,
    InputKind,
    NameSource,
    Status,
)
from ..core.pipeline import run_batch
from .i18n import (
    INPUT_KIND_KEYS,
    LANGUAGE_NAMES,
    NAME_SOURCE_KEYS,
    Translator,
    describe_name_source,
    summarise,
    translate_failure,
)
from .settings import (
    load_input_kind,
    load_language,
    load_name_source,
    save_input_kind,
    save_language,
    save_name_source,
)

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


class _DropEvent:
    """Stand-in for a Tk drop event, used by tests."""

    def __init__(self, data: str) -> None:
        self.data = data


def split_dropped_paths(data: str, splitter) -> list[Path]:
    """Turn a drop's payload into paths.

    Tk sends a Tcl list, which quotes whatever contains spaces or braces, so the
    split is left to Tcl itself instead of being guessed at: this is where file
    names with spaces arrive, and where a Windows path's backslashes would be
    eaten by a hand-written parser. A payload that is not a well-formed Tcl list
    is split on line breaks instead, so an odd source still produces paths rather
    than an exception.

    ``splitter`` is the caller's interpreter - in the window always
    ``root.tk.splitlist``. It is passed in rather than made here because a process
    should hold one Tcl interpreter (see :func:`create_root`): a second one may not
    find Tcl's own library directory on a machine where the first one did.
    """
    if not data or not data.strip():
        return []
    try:
        items = splitter(data)
    except tk.TclError:
        items = data.replace("\r", "\n").split("\n")
    return [Path(item) for item in items if item.strip()]


def create_root() -> tk.Tk:
    """Open the application's one Tk root, with drag-and-drop when possible.

    A process should hold a single Tk root: Tcl does not take kindly to repeated
    interpreter creation and destruction, so the root is created here and reused.
    """
    if HAS_DND:
        try:
            return TkinterDnD.Tk()
        except tk.TclError:  # pragma: no cover - Tk present but tkdnd missing
            return tk.Tk()
    return tk.Tk()  # pragma: no cover - machine without tkinterdnd2


def require_tkdnd(root: tk.Tk) -> bool:
    """Whether a root can actually use tkdnd, asked of Tk itself."""
    if not HAS_DND:
        return False
    try:
        return bool(root.tk.call("package", "require", "tkdnd"))
    except tk.TclError:  # pragma: no cover - tkdnd files missing from the build
        return False


def open_path(path: Path) -> None:
    """Open a file or folder in whatever this desktop uses for that kind."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_path(path: Path) -> None:
    """Show a path in the desktop's file manager, with the file selected.

    A file that is gone still has a folder worth opening, so the folder is what
    gets shown then. Explorer takes the switch and the path as one argument:
    splitting them loses a path that contains spaces.
    """
    folder = path if path.is_dir() else path.parent
    if sys.platform.startswith("win"):
        target = f"/select,{path}" if path.exists() else str(folder)
        subprocess.Popen(["explorer", target])
    elif sys.platform == "darwin" and path.exists():
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def failure_sentence(outcome: FileOutcome, language: str) -> str:
    """What went wrong, short enough for a column and in the reader's language.

    The recorded ``reason`` is not what goes here. For XML, PDF and write
    failures it is the library's own words - a path and a Windows error code -
    which is the wrong language and far too long for a column; the detail pane
    is where that belongs. A failure without a code keeps its reason.
    """
    if outcome.failure_code is None:
        return (outcome.reason or "").strip()
    return failure_message(outcome.failure_code, language)


def outcome_cause(outcome: FileOutcome) -> str:
    """What the layer recorded beyond the catalogue sentence for this code.

    ``reason`` is the domain layer's own words, and it is one of three things:
    the catalogue sentence, that sentence followed by the specific detail, or -
    from the filesystem and XML layers - the detail alone. Whatever the
    catalogue already says is dropped, because the rest is the whole point: a
    locked file, a value that disagrees with the access key.
    """
    recorded = (outcome.reason or "").strip()
    if not recorded:
        return ""
    catalogue = FAILURE_MESSAGES.get(outcome.failure_code, "") if outcome.failure_code else ""
    if catalogue and recorded.startswith(catalogue):
        recorded = recorded[len(catalogue) :].strip()
    return recorded


def build_window() -> "RenamerWindow":
    """Create the main window, with drag-and-drop when this machine supports it."""
    root = create_root()
    return RenamerWindow(root, dnd_available=require_tkdnd(root))


class RenamerWindow:
    """The one screen: choose files, process, read the result."""

    def __init__(self, root: tk.Tk, *, dnd_available: bool = False) -> None:
        self.root = root
        self.dnd_available = dnd_available
        self.translate = Translator(load_language())
        self.input_kind_var = tk.StringVar(value=load_input_kind().value)
        self.selected: list[Path] = []
        self.summary: BatchSummary | None = None
        # The details widgets below are built by show_details and cleared by
        # _close_details: whenever details_table is set, they are all set.
        self.details_window: tk.Toplevel | None = None
        self.details_table: ttk.Treeview | None = None
        self.detail_text: tk.Text | None = None
        self.details_menu: tk.Menu | None = None
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

        # The result block is created first and, when a batch finishes, packed
        # first as well - from the bottom. Tk hands out space in packing order
        # and squeezes whatever comes last, and this frame is where the error
        # count lives: the one line that says a file was lost. Everything under
        # it here is scrollable or a note, so it can yield; the count cannot.
        self.result_frame = ttk.LabelFrame(self.frame, padding=10)
        self.result_labels: list[ttk.Label] = []
        for _ in range(6):
            label = ttk.Label(self.result_frame)
            label.pack(anchor="w")
            self.result_labels.append(label)
        self.failure_label = ttk.Label(self.result_frame)
        self.failure_label.pack(anchor="w", pady=(6, 0))
        self.duration_label = ttk.Label(self.result_frame, foreground="#555555")
        self.duration_label.pack(anchor="w", pady=(4, 0))
        self.output_label = ttk.Label(self.result_frame, foreground="#555555")
        self.output_label.pack(anchor="w", pady=(4, 0))

        self.header = ttk.Frame(self.frame)
        header = self.header
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

        self._build_input_selector()
        self._build_name_source_selector()

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
        self.file_list = tk.Listbox(
            list_frame, selectmode="extended", activestyle="none", height=6
        )
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

        self.safety_label = ttk.Label(self.frame, foreground="#1a7f37")
        self.safety_label.pack(fill="x", pady=(10, 0))

        self._refresh_selection()
        self._refresh_result_visibility()

    def _build_input_selector(self) -> None:
        """Choose which files a batch reads: XML, PDF, or both.

        XML is the main workflow: it is converted and then named. PDF keeps the
        original behaviour for files that were generated elsewhere.
        """
        options = ttk.Frame(self.frame)
        options.pack(fill="x", pady=(0, 4))
        self.input_kind_label = ttk.Label(options)
        self.input_kind_label.pack(side="left", padx=(0, 10))
        self.input_kind_buttons: dict[InputKind, ttk.Radiobutton] = {}
        for kind in (InputKind.XML, InputKind.PDF, InputKind.BOTH):
            button = ttk.Radiobutton(
                options,
                variable=self.input_kind_var,
                value=kind.value,
                command=self._on_input_kind_selected,
            )
            button.pack(side="left", padx=(0, 12))
            self.input_kind_buttons[kind] = button

    def _build_name_source_selector(self) -> None:
        """The one processing choice: which printed company names the files.

        Both names are read from every document; this decides which of the two
        the file name carries, and it is remembered for the next start.
        """
        options = ttk.Frame(self.frame)
        options.pack(fill="x", pady=(0, 8))
        self.name_source_label = ttk.Label(options)
        self.name_source_label.pack(side="left", padx=(0, 10))
        self.name_source_var = tk.StringVar(value=load_name_source().value)
        self.name_source_buttons: dict[NameSource, ttk.Radiobutton] = {}
        for source in (NameSource.EMITENTE, NameSource.RECIPIENT):
            button = ttk.Radiobutton(
                options,
                variable=self.name_source_var,
                value=source.value,
                command=self._on_name_source_selected,
            )
            button.pack(side="left", padx=(0, 12))
            self.name_source_buttons[source] = button

    def _enable_drop_target(self) -> None:
        """Accept dropped files when the machine supports it; otherwise do nothing."""
        if not self.dnd_available:  # pragma: no cover - needs a machine without tkdnd
            return
        try:
            self.file_list.drop_target_register(DND_FILES)
            self.file_list.dnd_bind("<<Drop>>", self._on_drop)
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:  # pragma: no cover - window without drop support
            self.dnd_available = False

    def _drop_paths(self, data: str) -> list[Path]:
        """Parse a drop payload and repair Tcl's brace escaping if it bit us.

        Tcl keeps ``\\{`` inside a quoted element, so a path that really contains
        braces arrives escaped. If the literal path does not exist and the
        unescaped one does, the second is the file the person dropped.
        """
        paths = split_dropped_paths(data, self.root.tk.splitlist)
        repaired: list[Path] = []
        for path in paths:
            text = str(path)
            if not path.exists() and ("\\{" in text or "\\}" in text):
                candidate = Path(text.replace("\\{", "{").replace("\\}", "}"))
                if candidate.exists():
                    path = candidate
            repaired.append(path)
        return repaired

    # -------------------------------------------------------------- language

    def _apply_language(self) -> None:
        t = self.translate
        self.root.title(f"{t('window_title')} {__version__}")
        self.title_label.configure(text=t("headline"))
        self.subtitle_label.configure(text=t("subtitle"))
        self.language_label.configure(text=t("language_label"))
        self.input_kind_label.configure(text=t("input_label"))
        for kind, button in self.input_kind_buttons.items():
            button.configure(text=t(INPUT_KIND_KEYS[kind]))
        self.name_source_label.configure(text=t("name_source_label"))
        for source, button in self.name_source_buttons.items():
            button.configure(text=t(NAME_SOURCE_KEYS[source]))
        self.drop_hint_label.configure(
            text=t("drop_hint" if self.dnd_available else "drop_hint_buttons")
        )
        self.choose_files_button.configure(text=t("choose_files"))
        self.choose_folder_button.configure(text=t("choose_folder"))
        self.remove_selected_button.configure(text=t("remove_selected"))
        self.clear_button.configure(text=t("clear_list"))
        self.process_button.configure(text=t("process"))
        self.open_output_button.configure(text=t("open_output"))
        self.details_button.configure(text=t("view_details"))
        self.another_button.configure(text=t("process_another"))
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

    def _on_input_kind_selected(self) -> None:
        """Remember the input kind and drop files of the previous kind."""
        save_input_kind(self.input_kind)
        self.selected.clear()
        self._refresh_selection()

    def _on_name_source_selected(self) -> None:
        """Remember the choice straight away, so the next start keeps it."""
        save_name_source(self.name_source)

    @property
    def input_kind(self) -> InputKind:
        """Which files the next selection and batch read."""
        return InputKind(self.input_kind_var.get())

    @property
    def name_source(self) -> NameSource:
        """Which printed name the next batch puts into the file names."""
        return NameSource(self.name_source_var.get())

    # ----------------------------------------------------------------- input

    def choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title=self.translate("choose_files"),
            filetypes=[
                ("XML and PDF", "*.xml *.pdf"),
                ("XML", "*.xml"),
                ("PDF", "*.pdf"),
                ("All files", "*.*"),
            ],
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

    def _on_drop(self, event) -> None:
        """Handle a drop: the payload is a Tcl list of paths."""
        self._add_sources(self._drop_paths(str(event.data)))

    def _add_sources(self, paths: list[Path]) -> None:
        excluded = []
        if self.summary is not None and self.summary.output_directory is not None:
            excluded.append(self.summary.output_directory)
        for found in collect_sources(
            paths, excluded, input_kind=self.input_kind
        ):
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
        # Read the choices here, on the Tk thread; the worker only gets values.
        name_source = self.name_source
        language = self.translate.language
        thread = threading.Thread(
            target=self._run_batch,
            args=(sources, output_root, name_source, language),
            daemon=True,
        )
        thread.start()

    def _run_batch(
        self,
        sources: list[Path],
        output_root: Path,
        name_source: NameSource,
        language: str,
    ) -> None:
        """Worker thread: never touches Tk directly, only the queue."""
        try:
            summary = run_batch(
                sources,
                output_root,
                progress=self._report_progress,
                name_source=name_source,
                language=language,
            )
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
        """Show the result block only when there is one, and never below the fold.

        Packing it again puts it back at the front of the order, so the room it
        needs comes off the scrollable file list rather than the other way round.
        """
        if self.summary is None:
            self.result_frame.pack_forget()
            self.open_output_button.state(["disabled"])
            self.details_button.state(["disabled"])
            return
        self.result_frame.pack(
            fill="x", pady=(10, 0), side="bottom", before=self.header
        )
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
            (
                lines.analyzed,
                lines.renamed,
                lines.converted,
                lines.skipped,
                lines.errors,
                lines.duration,
            ),
        ):
            label.configure(text=text)
        if lines.failures:
            self.failure_label.configure(
                text=lines.failure_heading
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
        self._hand_to_desktop(Path(self.summary.output_directory), reveal=False)

    # --------------------------------------------------------------- details

    def show_details(self) -> None:
        """Open the per-file list, where a failure can be acted on.

        This is not a report to read: a file that failed has to be reachable -
        opened, found in its folder, its name copied into a message.
        """
        if self.summary is None:
            return
        if self.details_window is not None and self.details_window.winfo_exists():
            self.details_window.lift()
            return

        t = self.translate
        window = tk.Toplevel(self.root)
        self.details_window = window
        window.title(t("details_title"))
        window.geometry("900x600")
        window.minsize(720, 460)
        window.transient(self.root)

        table = ttk.Treeview(
            window,
            columns=("status", "target", "reason"),
            show="headings",
            selectmode="extended",
            height=8,
        )
        self.details_table = table
        table.heading("#0", text=t("column_source"))
        table.heading("status", text=t("column_status"))
        table.heading("target", text=t("column_target"))
        table.heading("reason", text=t("column_reason"))
        table.column("#0", width=260)
        table.column("status", width=90, anchor="center")
        table.column("target", width=250)
        table.column("reason", width=280)
        table.pack(fill="both", expand=True, side="top")

        status_names = {
            Status.SUCCESS: t("status_success"),
            Status.SKIPPED: t("status_skipped"),
            Status.ERROR: t("status_error"),
        }
        for index, outcome in enumerate(self.summary.outcomes):
            status = status_names[outcome.status]
            if outcome.status is Status.SUCCESS and outcome.generated:
                status = t("status_generated")
            table.insert(
                "",
                "end",
                iid=str(index),
                text=outcome.source_path.name,
                values=(
                    status,
                    outcome.target_filename or "-",
                    failure_sentence(outcome, self.translate.language),
                ),
            )

        self._build_details_actions(window)

        table.bind("<<TreeviewSelect>>", self._refresh_details_actions)
        table.bind("<Double-1>", self._on_details_double_click)
        table.bind("<Button-3>", self._on_details_right_click)
        table.bind("<Control-c>", self._on_details_copy_names)
        window.protocol("WM_DELETE_WINDOW", self._close_details)
        self._refresh_details_actions()

    def _build_details_actions(self, window: tk.Toplevel) -> None:
        """The pane under the list: one file's details, and what can be done.

        The details are a disabled ``Text`` rather than a label. A label cannot
        be selected, so the name and the reason of a file that failed could be
        read but never copied out of the window; a disabled ``Text`` still
        answers to the mouse and to Ctrl+C. The buttons repeat the menu for the
        actions nobody thinks to right-click for.
        """
        t = self.translate
        # The frame grows with the window as well as the list above it, so a
        # description that runs past the pane is a scroll away, not a hidden one.
        box = ttk.LabelFrame(window, padding=10)
        box.pack(fill="both", expand=True, side="bottom")

        hint = ttk.Label(box, wraplength=820, justify="left", foreground="#555555")
        hint.configure(text=t("select_row_hint"))
        hint.pack(fill="x")

        text = tk.Text(box, height=7, wrap="word", relief="solid", borderwidth=1)
        text.pack(fill="both", expand=True, pady=(6, 8))
        self.detail_text = text

        opening = ttk.Frame(box)
        opening.pack(fill="x")
        self.open_file_button = ttk.Button(opening, command=self.open_selected_file)
        self.open_file_button.configure(text=t("open_original"))
        self.open_file_button.pack(side="left")
        self.open_copy_button = ttk.Button(opening, command=self.open_selected_copy)
        self.open_copy_button.configure(text=t("open_copy"))
        self.open_copy_button.pack(side="left", padx=6)
        self.reveal_button = ttk.Button(opening, command=self.reveal_selected_file)
        self.reveal_button.configure(text=t("show_in_folder"))
        self.reveal_button.pack(side="left")

        copying = ttk.Frame(box)
        copying.pack(fill="x", pady=(6, 0))
        self.copy_name_button = ttk.Button(copying, command=self.copy_selected_names)
        self.copy_name_button.configure(text=t("copy_name"))
        self.copy_name_button.pack(side="left")
        self.copy_path_button = ttk.Button(copying, command=self.copy_selected_paths)
        self.copy_path_button.configure(text=t("copy_path"))
        self.copy_path_button.pack(side="left", padx=6)
        self.copy_details_button = ttk.Button(copying, command=self.copy_details)
        self.copy_details_button.configure(text=t("copy_details"))
        self.copy_details_button.pack(side="left")
        self.close_button = ttk.Button(copying, command=self._close_details)
        self.close_button.configure(text=t("close"))
        self.close_button.pack(side="right")

        menu = tk.Menu(window, tearoff=False)
        self.details_menu = menu
        menu.add_command(label=t("open_original"), command=self.open_selected_file)
        menu.add_command(label=t("open_copy"), command=self.open_selected_copy)
        menu.add_command(label=t("show_in_folder"), command=self.reveal_selected_file)
        menu.add_separator()
        menu.add_command(label=t("copy_name"), command=self.copy_selected_names)
        menu.add_command(label=t("copy_path"), command=self.copy_selected_paths)
        menu.add_command(label=t("copy_details"), command=self.copy_details)

    # -- what the pane is looking at

    def _outcome_for(self, iid: str) -> FileOutcome | None:
        if self.summary is None:
            return None
        try:
            return self.summary.outcomes[int(iid)]
        except (ValueError, IndexError):
            return None

    def _selected_outcomes(self) -> list[FileOutcome]:
        table = self.details_table
        if table is None or not table.winfo_exists():
            return []
        found = []
        for iid in table.selection():
            outcome = self._outcome_for(iid)
            if outcome is not None:
                found.append(outcome)
        return found

    def _focused_outcome(self) -> FileOutcome | None:
        """The row an opening acts on: the focused one, else the first selected.

        Opening is an act on one file - a dozen selected rows must not open a
        dozen windows. Copying is the one that takes the whole selection.
        """
        table = self.details_table
        if table is None or not table.winfo_exists():
            return None
        iid = table.focus() or next(iter(table.selection()), "")
        return self._outcome_for(iid) if iid else None

    def detail_contents(self) -> str:
        """What the pane shows, without the newline Tk keeps at the end."""
        box = self.detail_text
        if box is None or not box.winfo_exists():
            return ""
        return box.get("1.0", "end-1c")

    def _set_detail_text(self, text: str) -> None:
        box = self.detail_text
        if box is None or not box.winfo_exists():
            return
        box.configure(state="normal")
        box.delete("1.0", tk.END)
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _describe_outcome(self, outcome: FileOutcome) -> str:
        """Everything known about one file, as text that can be copied out.

        The file leads and the reason follows it, because this is what a support
        request pastes first and what a person reads first - the run of fields
        under them is mostly dashes when a file failed early.
        """
        t = self.translate
        rows = [
            f"{t('field_file')}: {outcome.source_path.name}",
            f"{t('field_path')}: {outcome.source_path}",
        ]
        if outcome.failure_code is not None:
            rows.append(
                f"{t('column_reason')}: "
                + translate_failure(outcome.failure_code, t)
                + f" ({outcome.failure_code.value})"
            )
            cause = outcome_cause(outcome)
            if cause:
                rows.append(f"{t('field_detail')}: {cause}")
        rows += [
            f"{t('field_parser')}: {outcome.parser_id or '-'}",
            f"{t('field_source_type')}: {outcome.source_type or '-'}",
            f"{t('field_model')}: {outcome.document_model or '-'}",
            f"{t('field_generated')}: "
            f"{t('yes') if outcome.generated else t('no')}",
            f"{t('field_access_key')}: {outcome.access_key or '-'}",
            f"{t('field_nf_number')}: {outcome.nf_number or '-'}",
            f"{t('field_date')}: {outcome.emission_date or '-'}",
            f"{t('field_value')}: {outcome.total_value or '-'}",
            f"{t('name_source_label')}: {describe_name_source(outcome.name_source, t)}",
            f"{t('field_issuer')}: {outcome.issuer or '-'}",
            f"{t('field_recipient')}: {outcome.recipient or '-'}",
            f"{t('field_destination')}: {outcome.destination_path or '-'}",
            f"{t('field_duration')}: {t('seconds', value=outcome.duration_seconds)}",
        ]
        if outcome.warnings:
            rows.append(t("field_warnings") + ": " + "; ".join(outcome.warnings))
        return "\n".join(rows)

    def _refresh_details_actions(self, _event=None) -> None:
        """Show the selection's details and fit the buttons to it."""
        table = self.details_table
        if table is None or not table.winfo_exists():
            return
        outcomes = self._selected_outcomes()
        focused = self._focused_outcome()
        self._set_detail_text("\n\n".join(self._describe_outcome(o) for o in outcomes))
        for button in (
            self.open_file_button,
            self.reveal_button,
            self.copy_name_button,
            self.copy_path_button,
            self.copy_details_button,
        ):
            button.state(["!disabled"] if outcomes else ["disabled"])
        written = focused.destination_path if focused is not None else None
        has_copy = written is not None and written.exists()
        self.open_copy_button.state(["!disabled"] if has_copy else ["disabled"])

    # -- the actions

    def open_selected_file(self) -> None:
        """Open the original of the selected row: the file that failed."""
        outcome = self._focused_outcome()
        if outcome is not None:
            self._hand_to_desktop(outcome.source_path, reveal=False)

    def open_selected_copy(self) -> None:
        """Open the copy this run wrote, when the row has one."""
        outcome = self._focused_outcome()
        if outcome is not None and outcome.destination_path is not None:
            self._hand_to_desktop(outcome.destination_path, reveal=False)

    def reveal_selected_file(self) -> None:
        """Show the selected row's file in its folder."""
        outcome = self._focused_outcome()
        if outcome is not None:
            self._hand_to_desktop(outcome.source_path, reveal=True)

    def copy_selected_names(self) -> None:
        """Put the selected files' names on the clipboard, one per line."""
        self._copy_text("\n".join(o.source_path.name for o in self._selected_outcomes()))

    def copy_selected_paths(self) -> None:
        self._copy_text("\n".join(str(o.source_path) for o in self._selected_outcomes()))

    def copy_details(self) -> None:
        self._copy_text(self.detail_contents())

    def _copy_text(self, text: str) -> None:
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _hand_to_desktop(self, path: Path, *, reveal: bool) -> None:
        """Let the desktop open a path, saying so when it cannot.

        A file the batch read may be gone by the time it is clicked, while a
        folder that is merely shown is still worth showing then.
        """
        if not reveal and not path.exists():
            messagebox.showwarning(
                self.translate("error_title"),
                self.translate("file_missing", path=path),
            )
            return
        try:
            if reveal:
                reveal_path(path)
            else:
                open_path(path)
        except OSError as exc:
            messagebox.showerror(
                self.translate("error_title"),
                self.translate("file_open_failed", path=path, error=exc),
            )

    # -- the mouse

    def _select_under_pointer(self, event) -> bool:
        """Make the row under the pointer the one the actions act on."""
        table = self.details_table
        if table is None:
            return False
        row = table.identify_row(event.y)
        if not row:
            return False
        if row not in table.selection():
            table.selection_set(row)
        table.focus(row)
        self._refresh_details_actions()
        return True

    def _on_details_right_click(self, event) -> None:
        """Right-click: pick the row under the pointer, then offer the menu."""
        table = self.details_table
        if table is None:
            return
        self._select_under_pointer(event)
        if not table.selection() or self.details_menu is None:
            return
        try:
            self.details_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.details_menu.grab_release()

    def _on_details_double_click(self, event) -> None:
        """Double-clicking a row opens the file it names."""
        if self._select_under_pointer(event):
            self.open_selected_file()

    def _on_details_copy_names(self, _event=None) -> str:
        """Ctrl+C on the list copies the names; a table cannot do it itself."""
        self.copy_selected_names()
        return "break"

    def _close_details(self) -> None:
        if self.details_window is not None and self.details_window.winfo_exists():
            self.details_window.destroy()
        self.details_window = None
        self.details_table = None
        self.detail_text = None
        self.details_menu = None

    def _on_close(self) -> None:
        """Closing mid-run is allowed; a batch stops at the next file.

        The pipeline copies each file whole and never overwrites, so whatever was
        written before the window closed stays consistent, and the report only
        describes the files that were reached.
        """
        self._close_details()
        self.root.destroy()
