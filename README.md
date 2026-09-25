# DANFE/NF-e local renamer

A fully offline Windows application that reads NF-e/DANFE PDFs, extracts four
fields and writes **renamed copies** into a fresh folder for the batch. The
originals are never modified, moved, renamed or deleted.

Target file name:

```text
DD.MM.YYYY_NF <number> - <Emitente> - <valor>.pdf
```

Example:

```text
16.09.2026_NF 1234 - Industria Exemplo Ltda - 1.234,56.pdf
```

The implementation plan is kept with the documents on the machine that holds
them; this file is how to build, run and check the result.

## Fields and where they come from

| Field | Source | Rule |
|---|---|---|
| NF number | 44-digit access key | Unsigned NF number is derived from the key, never from proximity to a label; the printed `Nº.:` is used as a cross-check. |
| Emission date | `DATA DE EMISSÃO` (also `DATA DA EMISSÃO`) | Never `DATA DE SAÍDA`; year and month must agree with the key. |
| Total value | `VALOR TOTAL DA NOTA` (also `V. TOTAL DA NOTA`) | Never `VALOR TOTAL DOS PRODUTOS` / `V. TOTAL PRODUTOS`; printed with the Brazilian decimal comma. |
| Emitente | `IDENTIFICAÇÃO DO EMITENTE` block | Cross-checked against the receipt phrase when the document prints one. |

Anything that could make the file name wrong is a failure, reported with a
reason, and the file is skipped. Nothing is guessed.

## Running it

Windows, from a source checkout:

```bash
# the window (this is what a packaged .exe does by default)
PYTHONPATH= .venv/Scripts/python.exe run_danfe_renamer.py

# a batch, no window: renamed copies go to <input>/DANFE_Renamed/<timestamp>/
PYTHONPATH= .venv/Scripts/python.exe -m app.cli "C:/notas"

# analyse without writing anything, and keep a report
PYTHONPATH= .venv/Scripts/python.exe -m app.cli "C:/notas" --dry-run --report C:/tmp/report --verbose
```

The command line exits `0` when every file was renamed and `1` when anything was
skipped or failed, so it can be used from a scheduled task.

The window has an English/Portuguese switch (top right); the choice is stored in
`%APPDATA%\DANFE_Renamer\settings.json`.

## What every batch produces

```text
<output>/2026-09-25_13-51-02/
├── 16.09.2026_NF 1234 - Industria Exemplo Ltda - 1.234,56.pdf
├── batch_report.csv    (opens in Excel; one row per input file)
├── batch_report.json   (same rows, for machines)
└── batch_report.html   (open in a browser to read by eye)
```

The batch folder is new on every run; an existing file is never overwritten, and
a name produced twice in one run is reported as a collision instead.

## Development

```bash
export PYTHONPATH=                      # see the note below, it matters
/c/ProgramData/anaconda3/python.exe -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest      # 102 tests, no confidential data needed
```

> **Note (this machine):** a user-level `PYTHONPATH` points at an old ClickOnce
> Python and breaks Anaconda's interpreter, so every command needs `PYTHONPATH=`
> cleared. A packaged `.exe` is not affected.

Tests build their own DANFE-like PDFs with PyMuPDF
(`app/tests/fixtures/danfe_builder.py`): real invoices are confidential and are
never copied into the repository or into test output.

### Measuring against real documents

Development tools live in `tools/` and are not part of the application:

```bash
# phase 1: what is in this folder at all?
PYTHONPATH= .venv/Scripts/python.exe -m tools.inventory --data-root "C:/notas"

# phases 2-3: are the extracted values right? Compares them with the NF-e XMLs
# next to the PDFs, with the receipt stub, and with file names made by hand.
PYTHONPATH= .venv/Scripts/python.exe -m tools.evaluate_corpus --data-root "C:/notas"
```

Last measured on the real corpus (457 PDFs, 360 of them with a matching XML):

- 457/457 processed, 0 failures, ~15 s;
- 360/360 agreement with the XMLs on NF number, emission date, total value and issuer;
- 456/456 agreement with the receipt stub on the date, 455/455 on the value;
- the two files that disagree with their hand-made names are human errors: a typed
  `1.0450,00` and a date that matches neither the PDF nor the stub.

## Building the .exe

```bash
PYTHONPATH= .venv/Scripts/pyinstaller.exe --noconfirm --clean packaging/danfe_renamer.spec
```

This produces `dist/DANFE_Renamer.exe`: windowed, no Python needed on the target
machine, and no network access at runtime. Run it from a folder outside the
source tree to check the bundle is complete:

```bash
DANFE_Renamer.exe "C:/notas" --output "C:/notas/saida" --report "C:/tmp/report"
```

## How the code is organised

The three layers of the plan's mental model, plus the interface on top:

```text
app/pdf/          reading PDFs: page text, row geometry, access keys
app/extractors/   one parser per DANFE layout, plus anchor/value geometry
app/core/         models, detector, validator, filename, filesystem, pipeline
app/reporting/    CSV, JSON and HTML reports
app/gui/          the Tkinter window and its strings
app/cli.py        the same pipeline without a window
```

Rules that keep it trustworthy:

- `app/pdf/text.py` maps every variant - portrait, landscape, a receipt stub
  rotated inside the page - onto one representation: printed rows with a reading
  direction and coordinates. Parsers never see PDF library details.
- A parser reads *printed* text and reports what it found, including "two
  candidate access keys" or "the date is impossible".
- `app/core/validator.py` decides PASS/WARN/FAIL and produces the only record a
  file name may be built from.
- `app/core/filesystem.py` owns the safety invariant: copy only, verify the copy,
  never overwrite, stay inside the batch folder.
- Adding a layout means adding a parser in `app/extractors/` and listing it in
  `registry.py`; nothing else changes.
