# DANFE/NF-e local renamer

A fully offline Windows application for NF-e/NFC-e files. It reads the **XML**,
generates the **DANFE/DANFCe PDF** and writes the renamed copy into a fresh folder
for the batch. Existing PDFs can also be renamed on their own, and when a PDF and
its XML are in the same batch the PDF is the copy that is kept. The originals are
never modified, moved, renamed or deleted.

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

The XML carries the fields the issuer's system wrote, so it is the authoritative
source of the fields whenever the batch has one. A PDF (existing or generated) is
only read when there is no XML for that note.

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

What the authorization protocol says is recorded, never used to refuse the file.
A note SEFAZ has not authorized - cancelled, denied, or with no protocol at all -
is read and named like any other, because the fields are on the XML whatever the
status is and an XML has no PDF anywhere until the run makes one. The status
travels as a note on the row - the window's details list, the reports and
`--verbose` all say it - with the protocol's own words kept inside as evidence
(`Situação da autorização 101: Cancelamento de NF-e homologado`). What still
fails is what makes the *name* wrong: an unreadable XML, a document that is not
an NF-e/NFC-e, a key that disagrees with the data. Nothing is guessed.

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
the default input; `--input pdf` keeps the previous PDF-only behaviour, and
`--language en|pt` picks the language of the reports **and of the lines the run
prints** - by default the one chosen in the window, so a scheduled run reports in
the language its reader reads.

The window has an English/Portuguese switch (top right), the **Input files**
choice (XML, PDF or both) and the **Name in the file name** choice (issuer or
recipient); all are stored in `%APPDATA%\DANFE_Renamer\settings.json`.

After a batch, **View details** lists every file it read: the name it was given,
or the reason it was not. The list can be narrowed to **All files**, **Only
failures** or **Only successes** - a failure being any file that was not renamed,
whether it was skipped or errored - and the count beside it says how much of the
batch is showing. From there a file can be opened, copied, or found in its
folder: **Show in folder** opens the folder the file is read from, with the file
selected.

## What every batch produces

```text
<output>/2026-09-25_13-51-02/
├── 16.09.2026_NF 1234 - Industria Exemplo Ltda - 1.234,56.pdf
├── _unrenamed/         (only when a DANFE could not be named; see below)
├── batch_report.csv    (opens in Excel; one row per input file)
├── batch_report.json   (same rows, for machines)
└── batch_report.html   (open in a browser to read by eye)
```

An XML input becomes a DANFE (NF-e) or DANFCe (NFC-e) PDF under its final name;
the XML itself is not copied into the batch folder. The batch folder is new on
every run; an existing file is never overwritten, and a name produced twice in
one run is reported as a collision instead. The folder a batch is written into is
never read back as input, so running the same folder a second time does not
process the copies the first run made.

A file that cannot be named does not lose its document. The DANFE of an XML that
failed - over its fields or over the copy - is generated anyway and kept in
`_unrenamed/`, under the name of the XML it came from, and the row that reports
the failure points at it, so the file can be read and renamed by hand. No PDF is
kept where there is none to keep: an XML that could not be read, or that is not
an NF-e/NFC-e, has no DANFE in it, and a PDF input is the reader's own file,
which the batch never moved.

The three reports are written in the language chosen in the window. The values a
script keys on never change with it - `status`, `failure_code` and
`detail_code` - while `failure_message` and `reason` are what a person reads:
what kind of failure it was, and the one fact behind it, in that language.
`reason` keeps the names, paths and error text the library or Windows produced
exactly as they arrived, because that part is evidence. `output_file` is where
the run put each file's output, inside the batch folder: the agreed name for a
file it could name, and the `_unrenamed` copy for one it could not. A copy that
fails leaves nothing behind: a write something else is holding is retried before
giving up, and a failed attempt is removed, so the folder holds only files the
report accounts for.

## Development

```bash
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest      # 297 tests, no confidential data needed
```

If every Python command on the machine dies with an import error from an old
`python-future` tree (`This package should not be accessible on Python 3`), a
stray `PYTHONPATH` is pointing at it: run the commands above with `PYTHONPATH=`
cleared, and build the environment with whatever interpreter the machine already
has - `PYTHONPATH=/path/to/python.exe -m venv .venv` works the same.

Tests build their own DANFE-like PDFs with PyMuPDF and their own NF-e/NFC-e XMLs
with the standard library (`app/tests/fixtures/danfe_builder.py`): real invoices
are confidential and are never copied into the repository or into test output.
Every company name, CNPJ, access key and amount in the tests and in the examples
above is invented. The XML workflow is covered as a workflow of its own
(`app/tests/test_xml_workflow.py`): what each document is read as, what the
converter refuses, and which file a failed note leaves behind.

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
  never overwrite, stay inside the batch folder, retry a write something else is
  holding for a moment, and leave nothing behind when a copy fails - a folder must
  hold only files a report accounts for.
- No layer writes a sentence a person reads. A layer records a stable code and the
  values a sentence needs (`app/core/wording.py`), and the window, the reports and
  the console build that sentence in the language of whoever is reading. What a
  library or Windows said travels inside it unchanged: evidence is not translated.
- A note is never dropped over what SEFAZ answered about it. The authorization
  status is recorded on the row (`NOT_AUTHORIZED`, `NO_PROTOCOL`), so a cancelled
  note is named like any other and still says it is cancelled. Only what would
  make the file *name* wrong refuses the file.
- Adding a layout means adding a parser in `app/extractors/` and listing it in
  `registry.py`; nothing else changes.

## License

GPL-3.0-or-later: see [LICENSE](LICENSE). Copyright (C) 2026 Et-Nyx.

You may use, study, share and modify this program, commercial use included, as
long as derivative work is distributed under the same license with its source
available. The packaged `DANFE_Renamer.exe` is distributed under the same terms,
and the source it was built from is this repository. Runtime dependencies and
their licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
