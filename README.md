# GildData Design Data Profiler

Measures a folder of design files (CAD, BIM, EDA) into one zip of numbers, without copying, opening for upload, or sending any file anywhere. A seller runs it on their own machine and sends GildData the zip; GildData turns the zips from many sellers into a design catalogue, quality flags and a score card per dataset.

Two editions come from this one repository:

| Edition | Who runs it | Commands | How it is built |
|---|---|---|---|
| Supplier | A seller, on the machine or file server that holds the files | `check`, `quick`, `extract`, `cloud`, `ui` | `gilddesign-<version>-supplier.zip`, and `-supplier-windows.zip` with Python included |
| Internal | GildData | the above plus `verify`, `compile`, `compare`, `catalogue` | `gilddesign-<version>-internal.zip`, or this repository checked out |

## What it measures

For every project (each folder directly inside the one you point it at):

- **Files and size** per type: native CAD (SolidWorks, Inventor, Solid Edge, CATIA, Creo, NX, Fusion, FreeCAD), BIM (Revit, IFC), neutral formats (STEP, IGES, DXF, DWG, Parasolid, glTF), EDA (KiCad, Altium, Eagle, Gerber), drawings, PDF, simulation, and everything else.
- **Software and version** read from file headers (never the content): which CAD tool wrote each file, which release, 2D or 3D.
- **Assemblies**: which parts each assembly references, duplicates, shared parts, unresolved references, with a confidence number.
- **Drawings**: sheet counts in AutoCAD files (R2000 to R2018), with a confidence number. AutoCAD 2007 files are reported as unsupported, not guessed.
- **Dates and vintage**: when files were made and last changed.
- **Compliance markings**: counts of ITAR, EAR, EXPORT, CONFIDENTIAL and PROPRIETARY words in formats whose text is readable (DXF, STEP, IFC, IGES, KiCad, Solid Edge, Inventor, Revit). Only the count leaves the machine, never the text.
- **Readability**: folders that could not be read, cloud tiered files that were counted but not opened, damaged files.
- Optional, off by default: **fingerprints** (`--fingerprint`), a keyed code from each file's size and first and last 64 KB, so the same file offered by two sellers can be recognised. The code cannot be turned back into the file.

GildData's side adds, per dataset: domain (mechanical, architecture, electronics), native richness, 14 quality flags, a merge with the seller's own answers (rights to sell, authorship, description), duplicate groups across sellers, and the GildDesign Score card.

## What never leaves the seller's machine

- No file content, no file copies, no thumbnails. Files are opened read only, and only their headers are read.
- **Names are coded by default**: every project, folder and file name in the output is a code (extensions are kept). The seller keeps `name_map_*.zip`, which turns codes back into names, and sends it only if they choose to. `--real-names` keeps the real names; the zip records which choice was made.
- No network code in the profiler. The only connection it can make is the optional Autodesk Fusion connector, which the seller signs into themselves.
- Every zip carries `manifest.json` with the tool version, edition, detail level, name choice and a SHA256 of every member, so GildData can prove nothing changed after the run.
- `tests/test_no_leak.py` plants secret markers in contents, names and folder names and fails if any appear in the output.

## For sellers: run it

Requirements: Windows 10 or 11, macOS, or Linux. Python 3.9 or newer, except with the Windows bundle, which includes Python. Nothing to install, no administrator rights.

1. Extract the zip you received. Check it: the SHA256 we sent you must match `certutil -hashfile <zip> SHA256` (Windows) or `shasum -a 256 <zip>` (macOS, Linux).
2. Open a terminal in the extracted folder, or double click the launchers.

| Step | Windows | macOS and Linux | What it does |
|---|---|---|---|
| Check | `python gilddesign.py check "D:\Projects"` | `python3 gilddesign.py check /data/projects` | Can it run, can it read the folder, how big is the job. Opens no file. Takes seconds. |
| Step 1 | `python gilddesign.py quick "D:\Projects"` | `python3 gilddesign.py quick /data/projects` | Files per type and size per project. Opens no file. |
| Step 2 | `python gilddesign.py extract "D:\Projects"` or drag the folder onto `run.bat` | `python3 gilddesign.py extract /data/projects` or `./run.command` | The full profile. |

Or use the page in your browser: `run-ui.bat` (Windows) or `run-ui.command` (macOS, Linux), which opens `http://127.0.0.1:8765/` on this computer only. Pick the folder, click Step 1, then Step 2, then download the zip.

Or run it sealed in Docker, where the container sees your folder read only, has no network and no privileges: `run-docker.bat` or `run-docker.sh <folder>`.

3. Send the `profile_<code>_<date>.zip` from the `output` folder, plus the `quick_*.zip` from Step 1. `run_stats_*.zip` (timings and machine type, no names) helps us if something was slow. **Keep `name_map_*.zip`** unless you want us to see the real names.

Options for Step 2: `--level 0|1|2` (detail, default 2: everything), `--real-names`, `--fingerprint` (only if GildData asks), `--out FOLDER`, `--workers N`. A stopped run resumes where it was when started again with the same settings.

Autodesk Fusion hubs: `python gilddesign.py cloud fusion --help`, or the Fusion tab on the page. Metadata only, signed in by you.

## For GildData: build the catalogue

```bash
pip install openpyxl                                   # only for the workbooks
python3 gilddesign.py verify received/                 # every zip: manifest present, nothing changed after the run
python3 gilddesign.py catalogue received/ --out catalogue/ \
    --sellers sellers.csv --supplier-answers answers.xlsx [--answers-map map.csv]
python3 gilddesign.py compare ours.zip upstream.zip     # counts per file type side by side
python3 gilddesign.py compile received/ -- --out compiled/   # the compiler alone, one or more zips
```

- `sellers.csv` has columns `zip,seller` and names the seller behind each zip. Without it the label in the zip's file name is used (a code when names were coded).
- `answers.xlsx` or `.csv` has one row per project: `Project Name`, optionally `Seller`, then `Project Description`, `Rights to sell (Y/N)`, `Original author (in house / client / third party)`, and any measured value the seller claims (`Domain`, `Native CAD Software`, `Part Files`, `Assembly Files`, `Native 2D Drawings`, `Total Files`). Claims that disagree with the measurement land in `qc/conflicts.csv`; the measurement wins.
- `map.csv` (columns `form_column,field`) renames the headings of the real intake form to the field names above, so the form can change without touching code.

Output of `catalogue`:

| Path | Contents |
|---|---|
| `design_catalogue.xlsx` | Tabs Catalogue, Sellers, Scores, QC Flags, Conflicts, Missing Fields, Duplicate Groups, Format Status, Method Notes |
| `catalogue.csv`, `scores.csv` | The same, flat |
| `qc/qc_report.csv`, `qc/conflicts.csv`, `qc/missing_fields.csv`, `qc/duplicate_groups.csv` | One line per flag, conflict, missing answer, duplicate group |
| `cards/<seller>_<project>.html`, `cards/index.html` | GildDesign Score cards |
| `compiled/<seller>/` | The compiler's workbook and CSVs per seller |

Everything that is a judgement is a setting or a table, not code: score weights and thresholds in `gd_catalogue.SETTINGS`, software counted as in demand in `IN_DEMAND`, required seller fields in `REQUIRED_SELLER_FIELDS`, file types and classes in `profile-compile/scripts/mapping/*.csv` (mirrored in `ext_classes.csv`, a test checks they match), format status shown to buyers in `mapping/format_status.csv`, compliance words in `gd_signals.MARKINGS`, the fingerprint key in `gd_version.FINGERPRINT_KEY` (changing it makes old and new fingerprints incomparable).

## Release

```bash
python3 tools/build_release.py             # dist/: supplier zip, internal zip, SHA256SUMS.txt
python3 tools/build_release.py --windows   # plus the supplier bundle with the embeddable Python
```

Builds are reproducible: the same commit gives the same checksums. To publish: bump `TOOL_VERSION` in `gd_version.py`, tag `vX.Y.Z` and push the tag. The release workflow builds all three zips, signs them with Sigstore and attaches them with the checksums to a GitHub release. Anyone can verify a download with `pip install sigstore` and `sigstore verify github --cert-identity-regexp 'https://github.com/Gilddata-Labs/design-profiler/' <file>`.

Send sellers only the supplier zip, or the Windows bundle for sellers without Python, with the checksum in a separate message. The internal zip and this repository stay at GildData. The tool never updates itself; a new version is a new zip.

## Tests and CI

```bash
pip install openpyxl
for t in tests/test_*.py; do python3 "$t" || echo "FAILED $t"; done
```

53 test files: synthetic trees with known counts, damaged files, planted markers that must not leak, resume after a crash, Windows network share behaviour, memory limits, the browser page, the Fusion connector against a local fake, and the catalogue end to end. CI (`.github/workflows/ci.yml`) runs them on Windows, macOS and Linux with Python 3.9 and 3.12, builds and runs the Docker image sealed, builds and runs the Windows bundle, and builds the release zips.

## Repository layout

| Path | What |
|---|---|
| `gilddesign.py` | The command line: `check`, `quick`, `extract`, `cloud`, `ui`, `verify`, `compile`, `compare`, `catalogue` |
| `file_profiler.py`, `cad_links.py`, `dwg_sheets.py`, `name_anon.py`, `sysmetrics.py` | The profiling engine (built on data847/folder-profiler, upstream commit in `UPSTREAM_COMMIT`) |
| `gd_check.py`, `gd_signals.py`, `gd_manifest.py`, `gd_version.py` | GildData's seller side layer: preflight, compliance and fingerprint readers, manifest, version and edition |
| `gd_catalogue.py`, `gd_compare.py` | GildData's internal side: catalogue, QC flags, score cards, comparison |
| `profile-compile/` | The compiler (zips to the compiled workbook) and its mapping tables |
| `ui.py`, `fusion_cloud_profiler.py` | The local browser page and the Autodesk Fusion connector |
| `run*.bat`, `run*.command`, `run-docker.*`, `Dockerfile`, `docker-compose.yml` | Launchers |
| `tools/build_release.py` | Release zips |
| `docs/ENGINE.md` | The engine's own documentation: detail levels, network shares, resume, sheet counting, what was verified on real files |
| `README_FIRST.txt` | The one page guide inside the seller zip |

## Known limits and open items

- AutoCAD 2007 (R2007) drawings use a layout the sheet counter does not decode; they are reported as unsupported. DWG external reference names are compressed inside the file and are not read; DXF ones are.
- Revit, CATIA, Creo and NX readers were written from the published format descriptions and checked on public samples only; counts from real seller files should be reviewed on the first pilot.
- Score weights and thresholds are starting values until tuned on real datasets; the Method Notes tab prints the values used.
- The profiler has run on Windows in CI and on synthetic trees of 300,000 files; a run against a real Windows file server is still to be done on the first pilot.
