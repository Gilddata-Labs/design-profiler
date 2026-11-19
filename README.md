# GildData Design Data Profiler

This repository is the tool a seller runs on a folder of design files (CAD, BIM, EDA) to produce one zip of numbers about them, without copying, uploading or sending any file anywhere. The seller sends GildData that zip. GildData turns the zips from many sellers into a design catalogue, quality flags and a score card per dataset.

You can run it straight from a clone or download of this repository. Nothing is installed, nothing phones home, and nothing needs administrator rights.

## What it does

For every project (each folder directly inside the one you point it at) it measures:

- **Files and size** per type: native CAD (SolidWorks, Inventor, Solid Edge, CATIA, Creo, NX, Fusion, FreeCAD), BIM (Revit, IFC), neutral formats (STEP, IGES, DXF, DWG, Parasolid, glTF), EDA (KiCad, Altium, Eagle, Gerber), drawings, PDF, simulation, and everything else.
- **Software and version** read from file headers only: which tool wrote each file, which release, 2D or 3D.
- **Assemblies**: which parts each assembly references, duplicates, shared parts, unresolved references, with a confidence number.
- **Drawings**: sheet counts in AutoCAD files (R2000 to R2018), with a confidence number. AutoCAD 2007 files are reported as unsupported rather than guessed.
- **Dates**: when files were made and last changed.
- **Compliance markings**: counts of ITAR, EAR, EXPORT, CONFIDENTIAL and PROPRIETARY words in formats whose text is readable. Only the count leaves the machine.
- **Readability**: folders that could not be read, cloud tiered files that were counted but not opened, damaged files.
- Optional and off by default: **fingerprints** (`--fingerprint`), a keyed code from each file's size and first and last 64 KB, so the same file offered by two sellers can be recognised. The code cannot be turned back into the file.

### What never leaves your machine

- No file content, no copies, no thumbnails. Files are opened read only and only their headers are read.
- **Names are coded by default.** Every project, folder and file name in the output is a code (extensions are kept). You keep `name_map_*.zip`, which turns the codes back into names, and send it only if you choose to. `--real-names` keeps the real names; the zip records which choice was made.
- There is no network code in the profiler. The only connection it can make is the optional Autodesk Fusion connector, which you sign into yourself.
- Every zip carries `manifest.json` with the tool version, detail level, name choice and a SHA256 of every member, so GildData can prove nothing changed after the run.
- `tests/test_no_leak.py` plants secret markers in file contents, file names and folder names and fails if any of them appears in the output.

## Run it (sellers)

**Requirements**: Windows 10 or 11, macOS or Linux, and Python 3.9 or newer (`python --version`). Python is on python.org; on Windows tick "Add python.exe to PATH" when installing. Nothing else is needed. The `openpyxl` package is only used by GildData's own commands.

**Get the code**, either way:

```bash
git clone https://github.com/Gilddata-Labs/design-profiler.git
cd design-profiler
```

or on the repository page use "Code", then "Download ZIP", and extract it.

**Three commands**, in this order. Replace the folder with the top folder that holds your projects.

| Step | Windows | macOS and Linux | What it does |
|---|---|---|---|
| Check | `python gilddesign.py check "D:\Projects"` | `python3 gilddesign.py check /data/projects` | Can it run here, can it read the folder, how big is the job. Opens no file. Seconds. |
| Step 1 | `python gilddesign.py quick "D:\Projects"` | `python3 gilddesign.py quick /data/projects` | Files per type and size per project. Opens no file. |
| Step 2 | `python gilddesign.py extract "D:\Projects"` | `python3 gilddesign.py extract /data/projects` | The full profile. |

Results go to the `output` folder next to `gilddesign.py` (or `--out FOLDER`).

**Send GildData** the `profile_<code>_<date>.zip` from Step 2 and the `quick_*.zip` from Step 1. `run_stats_*.zip` (timings and machine type, no names) helps us if something was slow. **Keep `name_map_*.zip`** unless you want us to see the real names.

Other ways to run the same steps:

- **The page in your browser**: `python gilddesign.py ui` (or double click `run-ui.bat` / `run-ui.command`). It opens `http://127.0.0.1:8765/` on this computer only. Pick the folder, click Step 1, then Step 2, then download the zip.
- **Launchers**: drag a folder onto `run.bat` (Windows) or run `./run.command /data/projects` (macOS, Linux) for Step 2.
- **Sealed in Docker**: `run-docker.bat` or `./run-docker.sh /data/projects`. The container sees the folder read only and has no network and no privileges.
- **Autodesk Fusion hubs**: `python gilddesign.py cloud fusion --help`, or the Fusion tab on the page. Metadata only, signed in by you.

Options for Step 2: `--level 0|1|2` (detail, default 2: everything), `--real-names`, `--fingerprint` (only if GildData asks), `--out FOLDER`, `--workers N`. A run that stops (laptop closed, network share dropped) continues where it was when started again with the same settings. Run `python gilddesign.py <command> --help` for every option.

### If something goes wrong

- `check` says what is wrong in plain words (no Python, folder not readable, not enough disk) and writes a report of counts only. Send us that report.
- A failed run writes `fail_log_<date>.zip` to the output folder: the log and the settings, no names, no content. Send us that file.
- The folder is a network share or cloud tiered: see `docs/ENGINE.md`, section "Windows file servers and network shares".
- Something else: open an issue on this repository or write to your GildData contact with the output of `check` and, if there is one, the fail log. We fix problems as they come up and you update with `git pull` (or download the zip again).

## For GildData: build the catalogue

A checkout is the seller edition. GildData staff switch on the internal commands with an environment variable, or by creating a file named `EDITION` containing `internal` next to `gilddesign.py` (git ignores it):

```bash
export GILDDESIGN_EDITION=internal          # Windows: set GILDDESIGN_EDITION=internal
pip install openpyxl                        # only for the workbooks
python3 gilddesign.py verify received/      # every zip: manifest present, nothing changed after the run
python3 gilddesign.py catalogue received/ --out catalogue/ \
    --sellers sellers.csv --supplier-answers answers.xlsx [--answers-map map.csv]
python3 gilddesign.py compare ours.zip upstream.zip     # counts per file type side by side
python3 gilddesign.py compile received/ -- --out compiled/   # the compiler alone
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

### Packaged copies

Sellers normally run from this repository. For a seller who cannot use git or has no Python, `python3 tools/build_release.py --windows` builds `dist/gilddesign-<version>-supplier.zip` and `-supplier-windows.zip` (with the official embeddable Python included) plus `SHA256SUMS.txt`; the `-internal.zip` is for GildData. A tag `vX.Y.Z` (matching `TOOL_VERSION` in `gd_version.py`) builds the same, signs them with Sigstore and publishes a GitHub release. Builds are reproducible: the same commit gives the same checksums.

## Changing the code

There is no CI on GitHub for this repository (it stays on the free tier). Every change is tested locally before it is pushed:

1. Once per clone, switch on the pre-push hook and install the one test dependency:

   ```bash
   git config core.hooksPath .githooks
   python3 -m venv .venv && .venv/bin/python -m pip install openpyxl     # Windows: .venv\Scripts\python -m pip install openpyxl
   ```

   The hook uses `.venv` when it exists (or `$PYTHON` if set), so the system Python stays untouched.

2. Make the change, then run the suite yourself (a few minutes; `python3 tools/run_tests.py quick` runs only the files whose name matches):

   ```bash
   .venv/bin/python tools/run_tests.py
   ```

3. `git push`. The hook runs the same suite again and stops the push if any test fails. `--no-verify` skips it; use that only for a change that cannot affect the code, such as a README typo.

The suite has 53 test files: synthetic trees with known counts, damaged files, planted markers that must not leak, resume after a crash, Windows network share behaviour, memory limits, the browser page, the Fusion connector against a local fake, the catalogue end to end, and the hardening checks. Tests that only apply to one operating system skip themselves elsewhere, so a change that touches Windows behaviour (paths, file locking, launchers) should also be run on a Windows machine before pushing.

`.github/workflows/` still holds the CI and release workflows from 0.4.0 (tests on Windows, macOS and Linux, the Docker image, the Windows bundle, signed releases). They need paid Actions minutes for a private repository and are not part of the process; keep them disabled in the repository's Actions settings.

## Repository layout

| Path | What |
|---|---|
| `gilddesign.py` | The command line: `check`, `quick`, `extract`, `cloud`, `ui`; and for GildData `verify`, `compile`, `compare`, `catalogue` |
| `file_profiler.py`, `cad_links.py`, `dwg_sheets.py`, `name_anon.py`, `sysmetrics.py` | The profiling engine (built on data847/folder-profiler, upstream commit in `UPSTREAM_COMMIT`) |
| `gd_check.py`, `gd_signals.py`, `gd_manifest.py`, `gd_version.py` | Preflight, compliance and fingerprint readers, manifest, version and edition |
| `gd_catalogue.py`, `gd_compare.py` | GildData's side: catalogue, QC flags, score cards, comparison |
| `profile-compile/` | The compiler (zips to the compiled workbook) and its mapping tables |
| `ui.py`, `fusion_cloud_profiler.py` | The local browser page and the Autodesk Fusion connector |
| `run*.bat`, `run*.command`, `run-docker.*`, `Dockerfile`, `docker-compose.yml` | Launchers |
| `tools/build_release.py` | Packaged copies |
| `tools/run_tests.py`, `.githooks/pre-push` | The local test run, and the hook that runs it before every push |
| `docs/ENGINE.md` | The engine's own documentation: detail levels, network shares, resume, sheet counting, what was verified on real files |
| `README_FIRST.txt` | The one page guide inside a packaged copy |
| `CHANGELOG.md` | What changed in each version |

## Known limits

- AutoCAD 2007 (R2007) drawings use a layout the sheet counter does not decode; they are reported as unsupported. DWG external reference names are compressed inside the file and are not read; DXF ones are.
- Revit, CATIA, Creo and NX readers follow the published format descriptions and were checked on public samples; counts from real seller files are reviewed on the first pilot.
- Score weights and thresholds are starting values until tuned on real datasets; the Method Notes tab prints the values used.
