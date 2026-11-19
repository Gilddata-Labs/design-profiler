"""GildData Design Data Profiler: one command for every step.

Seller (supplier edition and internal):
    gilddesign check   FOLDER            will it run here, how big is the job (opens no file, counts only)
    gilddesign quick   FOLDER            Step 1: files per type and size per project (opens no file)
    gilddesign extract FOLDER            Step 2: the full profile (detail level 2 by default)
    gilddesign cloud fusion [...]        the same zip from an Autodesk Fusion hub (metadata only)
    gilddesign ui                        the same steps in a page in your browser (this computer only)
GildData (internal edition only):
    gilddesign compile ZIP|FOLDER ...    zips -> workbook (Project Compiled, breakdowns, domain tabs, Review)
    gilddesign compare A.zip B.zip       counts per file type side by side (ours vs upstream, Step 1 vs Step 2, two runs)
    gilddesign verify  ZIP ...           manifest present and no member changed after the run
    gilddesign catalogue ZIP|FOLDER ...  many sellers -> design catalogue, QC flags, seller answers merge, GildDesign Score cards

Names are CODED by default (project, folder and file names become codes; extensions kept; the seller keeps the name map). Real names
only with --real-names, which is the seller's explicit choice and is written into manifest.json.
Nothing is ever sent anywhere: there is no network code except the optional Fusion connector.
"""
import argparse
import glob
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gd_version  # noqa: E402

COMPILER = os.path.join(HERE, "profile-compile", "scripts", "compile_profiles.py")
INTERNAL_ONLY = ("compile", "compare", "verify", "catalogue")


def _default_out():
    return os.path.join(HERE, "output")


def _ask_folder():
    import file_profiler as fp
    return fp.ask_folder()


def _names(a):
    if a.real_names:
        print("Real file and folder names will be written into the result (you chose --real-names).")
        print("Share the zip only if your organisation agrees to that.\n")
        return False
    return True


def cmd_check(a):
    import gd_check
    folder = (a.folder or _ask_folder() or "").strip().strip('"')
    rep, _path = gd_check.run(folder, _writable_out(a.out or _default_out()), budget_s=a.seconds, project_depth=a.project_depth or 1)
    return 1 if rep["verdict"] == "FAIL" else 0


def _label(a, coded):
    """--name, else in coded mode the folder's own code (P-xxxx-hhhhhh, the same code its name map uses), so the zip's FILE NAME does
    not carry the real folder name either; real names mode keeps the folder name, as upstream does."""
    if a.name or not coded:
        return a.name
    try:
        import name_anon
        key, where = name_anon.load_key(a.out or _default_out())
        return name_anon.NameMap(key=key, key_path=where).project(os.path.basename(os.path.abspath(a.folder)))
    except Exception:  # noqa: BLE001
        return "dataset"


def _writable_out(path):
    """Create the output folder and prove it can be written, with a plain message instead of a traceback when it cannot."""
    try:
        if os.path.isfile(path):
            raise OSError(f"{path} is a file, not a folder")
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        print(f"Cannot write to the output folder {path}: {e}\nChoose another folder with --out.", file=sys.stderr)
        raise SystemExit(1)
    return path


def _folder(a):
    a.folder = (a.folder or _ask_folder() or "").strip().strip('"')
    return a.folder


def cmd_quick(a):
    import file_profiler as fp
    if not _folder(a):
        return 1
    coded = _names(a)
    a.name = _label(a, coded)
    argv = [a.folder] if a.folder else []
    argv += ["--quick", "--out", _writable_out(a.out or _default_out())]
    argv += [] if not a.name else ["--name", a.name]
    argv += [] if not a.project_depth else ["--project-depth", str(a.project_depth)]
    argv += ["--anonymize-names"] if coded else []
    argv += ["--no-paths"] if a.no_paths else []
    argv += [] if not a.workers else ["--workers", str(a.workers)]
    return fp.main(argv)


def cmd_extract(a):
    import file_profiler as fp
    if not _folder(a):
        return 1
    coded = _names(a)
    a.name = _label(a, coded)
    argv = [a.folder] if a.folder else []
    argv += ["--out", _writable_out(a.out or _default_out()), "--level", str(a.level)]
    argv += [] if not a.name else ["--name", a.name]
    argv += [] if not a.project_depth else ["--project-depth", str(a.project_depth)]
    argv += ["--anonymize-names"] if coded else []
    argv += ["--fresh"] if a.fresh else []
    if a.fingerprint:
        os.environ["PROFILER_DESIGN_FP"] = "1"
    argv += [] if not a.workers else ["--workers", str(a.workers)]
    return fp.main(argv)


def cmd_cloud(a):
    if a.service != "fusion":
        print("Only 'fusion' is supported.")
        return 1
    sys.argv = [os.path.join(HERE, "fusion_cloud_profiler.py")] + a.rest
    runpy.run_path(sys.argv[0], run_name="__main__")
    return 0


def cmd_ui(a):
    import ui
    return ui.main(a.rest) or 0


def _expand(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(glob.glob(os.path.join(p, "*.zip")))
        else:
            out.append(p)
    return out


def cmd_verify(a):
    import gd_manifest
    bad = 0
    for z in _expand(a.zips):
        base = os.path.basename(z)
        if base.startswith(("run_stats_", "name_map_")):
            continue
        try:
            ok, problems = gd_manifest.verify(z)
            m = gd_manifest.read(z)
        except Exception as e:  # noqa: BLE001
            ok, problems, m = False, [f"cannot read: {type(e).__name__}: {e}"], None
        what = f"{m['kind']}, level {m['detail_level']}, names {m['names']}, {m['tool']} {m['tool_version']}" if m else ""
        print(f"{'OK  ' if ok else 'FLAG'} {base}" + (f"  ({what})" if what else ""))
        for p in problems:
            print(f"       {p}")
        bad += not ok
    return 1 if bad else 0


def cmd_compile(a):
    print("Manifest check:")
    cmd_verify(argparse.Namespace(zips=a.inputs))
    print()
    sys.argv = [COMPILER] + a.inputs + a.rest
    try:
        runpy.run_path(COMPILER, run_name="__main__")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return 0


def cmd_catalogue(a):
    import gd_catalogue
    zips = [z for z in _expand(a.inputs) if os.path.basename(z).startswith("profile_")]
    print("Manifest check:")
    cmd_verify(argparse.Namespace(zips=zips))
    print()
    gd_catalogue.build(zips, _writable_out(a.out or os.path.join(_default_out(), "catalogue")), sellers_csv=a.sellers,
                       answers_path=a.supplier_answers, answers_map=a.answers_map, cards=not a.no_cards)
    return 0


def cmd_compare(a):
    import gd_compare
    identical, _rows, _notes = gd_compare.compare(a.a, a.b, out_dir=a.out or _default_out())
    return 0 if identical else 2


def build_parser():
    ed = gd_version.edition()
    ap = argparse.ArgumentParser(prog="gilddesign", description=f"{gd_version.TOOL_NAME} {gd_version.TOOL_VERSION} ({ed} edition)")
    ap.add_argument("--version", action="version", version=f"{gd_version.TOOL_NAME} {gd_version.TOOL_VERSION} ({ed})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, names=True):
        p.add_argument("folder", nargs="?", help="folder to measure (asked for if omitted)")
        p.add_argument("--out", help="where to write results (default: ./output next to this program)")
        p.add_argument("--project-depth", type=int, help="projects are the folders this many levels down (default 1)")
        if names:
            p.add_argument("--name", help="label for the report (default: the folder's own name)")
            p.add_argument("--real-names", action="store_true", help="write REAL file and folder names (default: coded)")
            p.add_argument("--workers", type=int, help="parallel reader threads (default: automatic)")

    p = sub.add_parser("check", help="will it run here and how big is the job (opens no file)")
    common(p, names=False)
    p.add_argument("--seconds", type=float, default=20.0, help="time budget for listing the folder (default 20)")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("quick", help="Step 1: files per type and size (opens no file)")
    common(p)
    p.add_argument("--no-paths", action="store_true", help="do not list each file's path, size and date")
    p.set_defaults(fn=cmd_quick)

    p = sub.add_parser("extract", help="Step 2: the full profile")
    common(p)
    p.add_argument("--level", type=int, choices=[0, 1, 2], default=2, help="0 metrics only, 1 + names and paths, 2 (default) + references and sheets")
    p.add_argument("--fresh", action="store_true", help="ignore saved progress and start again")
    p.add_argument("--fingerprint", action="store_true",
                   help="also write a keyed partial fingerprint of each design file (size + first and last 64 KB), so GildData can find copies sold twice")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("cloud", help="profile an Autodesk Fusion hub (metadata only)")
    p.add_argument("service", choices=["fusion"])
    p.add_argument("rest", nargs=argparse.REMAINDER, help="options for the Fusion profiler (--client-id, --hub ...)")
    p.set_defaults(fn=cmd_cloud)

    p = sub.add_parser("ui", help="open the page in your browser (this computer only)")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_ui)

    if ed == "internal":
        p = sub.add_parser("compile", help="GildData: zips -> workbook")
        p.add_argument("inputs", nargs="+", help="zips or folders of zips; compiler options go after --  (e.g. -- --out DIR --unique)")
        p.set_defaults(fn=cmd_compile, rest=[])

        p = sub.add_parser("catalogue", help="GildData: zips of many sellers -> design catalogue, QC flags, GildDesign Score cards")
        p.add_argument("inputs", nargs="+", help="profile zips or folders of them")
        p.add_argument("--out", help="output folder (default ./output/catalogue)")
        p.add_argument("--sellers", help="CSV with columns zip,seller (default: the label in each zip's file name)")
        p.add_argument("--supplier-answers", help="seller answers, CSV or XLSX: Project Name (+ Seller) and one column per field")
        p.add_argument("--answers-map", help="CSV (form_column,field) or JSON that renames the intake form's headings to our field names")
        p.add_argument("--no-cards", action="store_true", help="do not write the HTML score cards")
        p.set_defaults(fn=cmd_catalogue)

        p = sub.add_parser("compare", help="GildData: two zips side by side")
        p.add_argument("a")
        p.add_argument("b")
        p.add_argument("--out")
        p.set_defaults(fn=cmd_compare)

        p = sub.add_parser("verify", help="GildData: manifest present and unchanged")
        p.add_argument("zips", nargs="+")
        p.set_defaults(fn=cmd_verify)
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in INTERNAL_ONLY and gd_version.edition() != "internal":
        print(f"'{argv[0]}' is part of GildData's internal edition, not this one.")
        return 2
    rest = []
    if argv and argv[0] == "compile" and "--" in argv:   # everything after -- goes to the compiler unchanged
        i = argv.index("--")
        argv, rest = argv[:i], argv[i + 1:]
    if argv and argv[0] == "ui":
        # Everything after the command belongs to the page (its own --port, --out, --workers). argparse's REMAINDER
        # does not accept options that come first, so they are handed over directly.
        a = build_parser().parse_args(["ui"]); a.rest = argv[1:]
        return a.fn(a)
    if argv and argv[0] == "cloud" and len(argv) > 1 and argv[1] == "fusion":
        a = build_parser().parse_args(["cloud", "fusion"]); a.rest = argv[2:]   # same for the Fusion connector's options
        return a.fn(a)
    a = build_parser().parse_args(argv)
    if a.cmd == "compile":
        a.rest = rest
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
