# DANFE/NF-e local renamer

A fully offline Windows application for NF-e/NFC-e files. It reads the
authorized **XML**, generates the **DANFE/DANFCe PDF** and writes the renamed
copy into a fresh folder for the batch. Existing PDFs can also be renamed on
their own, and when a PDF and its XML are in the same batch the PDF is the copy
that is kept. The originals are never modified, moved, renamed or deleted.

Target file name:

```text
DD.MM.YYYY_NF <number> - <name> - <valor>.pdf
```

`<name>` is the company the file is named after: the **emitente** by default, or
the **destinatário** if the batch was run with that choice. Example:

```text
16.09.2026_NF 1234 - Industria Exemplo Ltda - 1.234,56.pdf
```

Ready to run, for Windows 10/11 (64-bit, no Python needed):
[releases page](https://github.com/Et-Nyx/danfe-renamer/releases/latest).
The rest of this file is how to build, run and check it from source.

The implementation plan is kept with the documents on the machine that holds
them.

## Fields and where they come from

The XML is the document SEFAZ authorized, so it is the authoritative source of
the fields whenever the batch has one. A PDF (existing or generated) is only
read when there is no XML for that note.

| Field | XML source | PDF source |
|---|---|---|
| NF number | `ide/nNF`, cross-checked with the 44-digit access key | the 44-digit access key; the printed `Nº.:` is a cross-check |
| Emission date | `ide/dhEmi` (`ide/dEmi` in older layouts) | `DATA DE EMISSÃO` (also `DATA DA EMISSÃO`), never `DATA DE SAÍDA` |
| Total value | `total/ICMSTot/vNF` | `VALOR TOTAL DA NOTA` (also `V. TOTAL DA NOTA`), never `VALOR TOTAL DOS PRODUTOS` |
| Emitente | `emit/xNome` | `IDENTIFICAÇÃO DO EMITENTE` block, cross-checked with the receipt phrase |
| Destinatário | `dest/xNome` (may be absent in an NFC-e) | `RAZÃO SOCIAL` under the `DESTINATÁRIO / REMETENTE` title |

Both names are always read; only the chosen one goes into the file name. The
access key, the document model (NF-e 55 or NFC-e 65) and the emission year and
month must agree everywhere they are printed.

When a PDF and its XML are in the same batch, the PDF is the copy that is kept
and the XML provides the name fields; if the PDF cannot be read, the XML
generates the copy instead. Anything that could make the file name wrong is a
failure, reported with a reason, and the file is skipped. Nothing is guessed.

## Running it

Windows, from a source checkout:

```bash
# the window (this is what a packaged .exe does by default)
.venv/Scripts/python.exe run_danfe_renamer.py

# a batch from XMLs, no window: the generated PDFs go to
# <input>/DANFE_Renamed/<timestamp>/
.venv/Scripts/python.exe -m app.cli "C:/notas"

# only rename PDFs that already exist (the earlier behaviour)
.venv/Scripts/python.exe -m app.cli "C:/notas" --input pdf

# read XMLs and existing PDFs together
.venv/Scripts/python.exe -m app.cli "C:/notas" --input both

# name the copies after the recipient (RAZÃO SOCIAL) instead of the issuer
.venv/Scripts/python.exe -m app.cli "C:/notas" --name-source destinatario

# analyse without writing anything, and keep a report
.venv/Scripts/python.exe -m app.cli "C:/notas" --dry-run --report C:/tmp/report --verbose
```

The command line exits `0` when every file was renamed or generated and `1` when
anything was skipped or failed, so it can be used from a scheduled task. XML is
the default input; `--input pdf` keeps the previous PDF-only behaviour.

The window has an English/Portuguese switch (top right), the **Input files**
choice (XML, PDF or both) and the **Name in the file name** choice (issuer or
recipient); all are stored in `%APPDATA%\DANFE_Renamer\settings.json`.

## What every batch produces

```text
<output>/2026-09-25_13-51-02/
├── 16.09.2026_NF 1234 - Industria Exemplo Ltda - 1.234,56.pdf
├── batch_report.csv    (opens in Excel; one row per input file)
├── batch_report.json   (same rows, for machines)
└── batch_report.html   (open in a browser to read by eye)
```

An XML input becomes a DANFE (NF-e) or DANFCe (NFC-e) PDF under its final name;
the XML itself is not copied into the batch folder. The batch folder is new on
every run; an existing file is never overwritten, and a name produced twice in
one run is reported as a collision instead.

## Development

```bash
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest      # 148 tests, no confidential data needed
```

Tests build their own DANFE-like PDFs with PyMuPDF and their own NF-e/NFC-e XMLs
with the standard library (`app/tests/fixtures/danfe_builder.py`): real invoices
are confidential and are never copied into the repository or into test output.
Every company name, CNPJ, access key and amount in the tests and in the examples
above is invented.

### Measuring against real documents

Development tools live in `tools/` and are not part of the application:

```bash
# phase 1: what is in this folder at all?
.venv/Scripts/python.exe -m tools.inventory --data-root "C:/notas"

# phases 2-3: are the extracted values right? Compares them with the NF-e XMLs
# next to the PDFs, with the receipt stub, and with file names made by hand.
.venv/Scripts/python.exe -m tools.evaluate_corpus --data-root "C:/notas"
```

These tools measure the PDF path. The XML path is exercised by the application
itself and by the packaged executable check in the release workflow.

Last measured on the real corpus (459 PDFs, 362 of them with a matching XML):

- 459/459 processed, 0 failures, ~20 s;
- 362/362 agreement with the XMLs on NF number, emission date, total value and
  issuer, and 362/362 on the recipient (in 2 of them the DANFE cuts the printed
  name; the application reads what is printed);
- 456/456 agreement with the receipt stub on the date, 457/457 on the value;
- the two files that disagree with their hand-made names are human errors: a typed
  `1.0450,00` and a date that matches neither the PDF nor the stub.

## Building the .exe

```bash
.venv/Scripts/pyinstaller.exe --noconfirm --clean packaging/danfe_renamer.spec
```

This produces `dist/DANFE_Renamer.exe`: windowed, no Python needed on the target
machine, and no network access at runtime. The release workflow also converts a
synthetic XML with the packaged executable, so missing hidden imports fail the
release instead of the person using the program. Run it from a folder outside
the source tree to check the bundle is complete:

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

## License

GPL-3.0-or-later: see [LICENSE](LICENSE). Copyright (C) 2026 Et-Nyx.

You may use, study, share and modify this program, commercial use included, as
long as derivative work is distributed under the same license with its source
available. The packaged `DANFE_Renamer.exe` is distributed under the same terms,
and the source it was built from is this repository. Runtime dependencies and
their licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
