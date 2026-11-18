"""GildData Milestone 3 (internal edition): design catalogue, QC flags, seller answers merge and the GildDesign Score.

    python3 gilddesign.py catalogue ZIP|FOLDER ... --out DIR [--sellers sellers.csv] [--supplier-answers answers.xlsx|csv] [--no-cards]

For every step 2 profile zip (one zip = one seller run): the profile-compile compiler is run on it alone (so per seller figures such as
"share of vendor files" stay per seller), then its outputs and the zip's own Files.csv / Links.csv / Unreadable.csv / manifest.json are
combined, across ALL sellers, into:

    design_catalogue.xlsx   Catalogue, Sellers, Scores, QC Flags, Conflicts, Missing Fields, Duplicate Groups, Format Status, Method Notes
    catalogue.csv  scores.csv  qc/qc_report.csv  qc/conflicts.csv  qc/missing_fields.csv  qc/duplicate_groups.csv
    cards/index.html + cards/<dataset>.html   one GildDesign Score card per dataset (plain English)
    compiled/<seller>/      the compiler's own workbook and CSVs per seller (the buyer templates: Project Compiled, domain tabs ...)

A dataset is one compiled project of one seller; its Dataset ID is "<seller>:<project>". Every threshold and weight below is a STARTING
value (PRD section 6), to be tuned on 5 to 10 real datasets; all of them are in SETTINGS and repeated in the Method Notes tab.
Standard library, plus openpyxl for the .xlsx (without it the CSVs and cards are still written).
"""
import collections
import csv
import glob
import html
import io
import json
import math
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.join(HERE, "claude-skill", "profile-compile", "scripts", "compile_profiles.py")
MAPPING = os.path.join(HERE, "claude-skill", "profile-compile", "scripts", "mapping")
sys.path.insert(0, HERE)
import gd_manifest  # noqa: E402
import gd_signals  # noqa: E402

SETTINGS = {
    "weights": {"Scale": 15, "Structure and completeness": 25, "Native richness": 20, "Hygiene": 15, "Originality": 25},
    "grades": [(85, "A"), (70, "B"), (55, "C"), (40, "D")],
    "scale_full_native_3d": 5000, "scale_full_assemblies": 500, "scale_full_drawings": 5000,
    "resolved_full_pct": 90, "drawings_linked_full_pct": 70,
    "native_share_full_pct": 80, "paired_full_pct": 50,
    "hygiene_ok_pct": 5, "hygiene_zero_pct": 25,
    "library_ok_pct": 20, "library_zero_pct": 70,
    "cap_cross_seller_pct": 50, "cap_library_pct": 50, "cap_unreadable_pct": 10,
    "flag_low_resolution_pct": 50, "flag_stub_pct": 30, "flag_unmapped_pct": 5, "vintage_year": 2024,
}
IN_DEMAND = {"SolidWorks", "Solid Edge", "SolidEdge", "Inventor", "Creo", "CATIA", "NX", "Revit", "ArchiCAD", "Altium", "KiCad", "Fusion360", "Fusion 360"}
LIBRARY_RX = re.compile(r"toolbox|mcmaster|misumi|\bdin[ _-]?\d{2,}|\biso[ _-]?\d{3,}|\bansi\b|\bhex[ _-]?(nut|bolt|screw)|\bwasher\b|"
                        r"\bscrew\b|\bbolt\b|\bbearing\b|\bnut\b|\brivet\b|\bspring[ _-]?pin\b|\bdowel\b|\bo[ _-]?ring\b", re.I)
DRAWING_EXTS = {"slddrw", "dft", "idw", "dwg", "dxf", "catdrawing", "drw", "pdf"}
REQUIRED_SELLER_FIELDS = ["Project Description", "Rights to sell (Y/N)", "Original author (in house / client / third party)"]
COMPARABLE = {"Domain": "text", "Native CAD Software": "contains", "Part Files": "int", "Assembly Files": "int",
              "Native 2D Drawings": "int", "Total Files": "int"}
QC_FLAGS = [
    ("UNREADABLE", "some folders or files could not be read; counts are below the truth"),
    ("TIERED_NOT_READ", "cloud tiered files were counted but not opened"),
    ("NO_NATIVE", "neutral, PDF or other files only: no native CAD or EDA file"),
    ("SCAN_ONLY_REFS", "references come only from text search (CATIA, Creo, NX): weaker evidence"),
    ("LOW_LINK_RESOLUTION", "under 50% of references resolve to a file in the dataset"),
    ("WHOLE_PROJECT_COPY", "80% or more of the files match a bigger project of the same seller"),
    ("CROSS_SELLER_DUPLICATE", "fingerprints match files of another seller"),
    ("LIBRARY_HEAVY", "over 50% of parts are standard library parts (by name)"),
    ("STUB_HEAVY", "over 30% of mechanical parts are under 10 KB"),
    ("EXPORT_MARKING", "ITAR, EAR or export control markings were counted: compliance hold"),
    ("UNCLASSIFIED_DOMAIN", "no tool, header or name evidence for a domain"),
    ("UNMAPPED_EXTENSIONS", "over 5% of files have a type the mapping tables do not know"),
    ("CONFLICT", "a seller answer differs from the measured value; the measured value is kept"),
    ("MISSING_FIELD", "a required seller answer is blank"),
]


# ---------------------------------------------------------------------------------------------------------------- helpers
def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _zrows(z, name):
    if name not in z.namelist():
        return []
    return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))))


def _num(v, default=None):
    try:
        s = str(v).replace(",", "").replace("%", "").strip()
        return float(s) if s not in ("", "None") else default
    except (TypeError, ValueError):
        return default


def _yn(v):
    v = str(v or "").strip().upper()
    return 1.0 if v == "Y" else 0.0 if v == "N" else None


def _ramp_up(x, full):
    return None if x is None else max(0.0, min(1.0, x / full))


def _ramp_down(x, ok, zero):
    if x is None:
        return None
    return 1.0 if x <= ok else 0.0 if x >= zero else 1.0 - (x - ok) / (zero - ok)


def _pct(a, b):
    return None if not b else round(100.0 * a / b, 1)


def _folder(project):
    return project.split(" / ")[0]


def _stem(name):
    base = re.split(r"[\\/]", name or "")[-1].lower()
    return base.rsplit(".", 1)[0] if "." in base else base


def _ext_classes():
    out = {}
    for r in _rows(os.path.join(MAPPING, "extensions.csv")):
        out[(r.get("ext") or "").lower()] = r.get("class") or ""
    return out


def _seller_of(zip_path, sellers):
    base = os.path.basename(zip_path)
    if base in sellers:
        return sellers[base]
    m = re.match(r"profile_(.+)_\d{8}-\d{6}\.zip$", base)
    return m.group(1) if m else base.rsplit(".", 1)[0]


def _read_answers(path):
    """Seller answers, wide format: one row per project, a 'Project Name' column, one column per field. CSV or XLSX (first sheet)."""
    if not path:
        return None
    if path.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:   # a read_only workbook keeps the file open until closed; Windows cannot delete it meanwhile
            it = wb.worksheets[0].iter_rows(values_only=True)
            head = [str(h or "").strip() for h in next(it)]
            rows = [dict(zip(head, ["" if v is None else str(v) for v in r])) for r in it]
        finally:
            wb.close()
    else:
        rows = _rows(path)
    out = {}
    for r in rows:
        key = (r.get("Seller") or "").strip(), (r.get("Project Name") or r.get("project") or "").strip()
        if key[1]:
            out[key] = r
    return out


# ---------------------------------------------------------------------------------------------------------------- per seller
def compile_one(zip_path, out_dir, log=print):
    os.makedirs(out_dir, exist_ok=True)
    r = subprocess.run([sys.executable, COMPILER, zip_path, "--out", out_dir], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(os.path.join(out_dir, "Project_Compiled.csv")):
        raise SystemExit(f"compile failed for {os.path.basename(zip_path)}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return out_dir


def seller_facts(zip_path, classes):
    """Per FOLDER project facts the compiler does not give: signals, fingerprints, vintage, unreadable / tiered, link kinds, pairs, library."""
    with zipfile.ZipFile(zip_path) as z:
        files = _zrows(z, "Files.csv")
        links = _zrows(z, "Links.csv")
        unread = _zrows(z, "Unreadable.csv")
    man = gd_manifest.read(zip_path) or {}
    by = collections.defaultdict(lambda: {"files": 0, "signals": collections.Counter(), "marked_files": collections.Counter(),
                                          "fps": [], "years": collections.Counter(), "unreadable": 0, "tiered": 0,
                                          "link_kinds": collections.Counter(), "parts": 0, "library_parts": 0, "named": False,
                                          "models": 0, "paired": 0})
    stems_by_proj = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in files:
        p = by[r["project"]]
        p["files"] += 1
        sig = gd_signals.parse(r.get("signals", ""))
        for k, v in sig.items():
            if k in ("ITAR", "EAR", "EXPORT", "CONFIDENTIAL", "PROPRIETARY"):
                p["signals"][k] += v
                p["marked_files"][k] += 1
        if r.get("fp"):
            p["fps"].append((r["fp"], r["ext"], r.get("size_bytes", "")))
        y = (r.get("modified_utc") or "")[:4]
        if y.isdigit():
            p["years"][int(y)] += 1
        if r.get("header_signature") == "TIERED":
            p["tiered"] += 1
        cls = classes.get((r.get("ext") or "").lower(), "")
        name = r.get("rel_path") or r.get("asm_name") or ""
        if name:
            p["named"] = True
            stems_by_proj[r["project"]][_stem(name)].add((cls, (r.get("ext") or "").lower()))
        if cls == "PART":
            p["parts"] += 1
            if name and LIBRARY_RX.search(re.split(r"[\\/]", name)[-1]):
                p["library_parts"] += 1
    for proj, stems in stems_by_proj.items():
        p = by[proj]
        for _s, kinds in stems.items():
            model = any(c in ("PART", "ASSEMBLY") for c, _e in kinds)
            if model:
                p["models"] += 1
                if any(e in DRAWING_EXTS or c in ("DRAWING", "NEUTRAL3D") for c, e in kinds):
                    p["paired"] += 1
    for r in unread:
        by[r["project"]]["unreadable"] += 1
    for r in links:
        by[r["project"]]["link_kinds"][r["kind"]] += 1
    coded = (man.get("names") or "").startswith("coded")
    for p in by.values():
        p["library_known"] = p["named"] and not coded
    return by, man


# ---------------------------------------------------------------------------------------------------------------- scoring
def score_dataset(m):
    """m: the dataset's measured values (see build()). -> (score 0-100, grade, pillars {name: (score 0-1 or None, [notes])}, caps [text])."""
    S, pillars = SETTINGS, {}
    dom = m["Domain"]
    n3d = m["native_3d"]
    asm = m["Assembly Files"] or 0
    nd = m["Native 2D Drawings"] or 0
    sc = [x for x in (_ramp_up(math.log10(n3d + 1), math.log10(S["scale_full_native_3d"] + 1)) if n3d is not None else None,
                      _ramp_up(math.log10(asm + 1), math.log10(S["scale_full_assemblies"] + 1)) if asm else None,
                      _ramp_up(math.log10(nd + 1), math.log10(S["scale_full_drawings"] + 1)) if nd else None) if x is not None]
    pillars["Scale"] = (max(sc) if sc else None, [f"{n3d or 0:,} native 3D or EDA files, {asm:,} assemblies, {nd:,} native drawings"])

    def pct(v):
        return "unknown" if v is None else f"{v:g}%"

    def pillar(parts, empty):
        got = [(v, txt) for v, txt in parts if v is not None]
        return (sum(v for v, _ in got) / len(got) if got else None, [t for _v, t in got] or [empty])

    if dom == "Electronics":
        parts = [(_yn(m.get(k)), f"{k.replace(' (Y/N)', '').lower()}: {m.get(k) or 'unknown'}")
                 for k in ("Has Schematic and Layout (Y/N)", "Has Gerber and Drill (Y/N)", "Has Netlist or Simulation (Y/N)")]
    elif dom == "Architecture":
        sh = _num(m.get("Drawing Sheets"))
        parts = [(_yn(m.get("Full-Set Project (Y/N)")), f"full set project: {m.get('Full-Set Project (Y/N)') or 'unknown'}"),
                 (None if sh is None else (1.0 if sh > 0 else 0.0), f"drawing sheets: {'unknown' if sh is None else int(sh)}")]
    else:
        parts = [(_ramp_up(m["References Resolved %"], S["resolved_full_pct"]), f"references resolved {pct(m['References Resolved %'])} (full marks at {S['resolved_full_pct']}%)"),
                 (_ramp_up(_num(m.get("Drawings Linked to Assembly %")), S["drawings_linked_full_pct"]),
                  f"drawings linked to an assembly {pct(_num(m.get('Drawings Linked to Assembly %')))} (full marks at {S['drawings_linked_full_pct']}%)"),
                 (_yn(m.get("Complete Project (Y/N)")), f"complete project: {m.get('Complete Project (Y/N)') or 'unknown'}"),
                 (_yn(m.get("BOM Present (Y/N)")), f"BOM present: {m.get('BOM Present (Y/N)') or 'unknown'}")]
    pillars["Structure and completeness"] = pillar(parts, "no structure evidence")

    sw = str(m["Native CAD Software"])
    parts = [(_ramp_up(m["Native Share of 3D %"], S["native_share_full_pct"]), f"native share of 3D files {pct(m['Native Share of 3D %'])} (full marks at {S['native_share_full_pct']}%)"),
             (_ramp_up(m["Paired Sets %"], S["paired_full_pct"]), f"models with their own drawing or export {pct(m['Paired Sets %'])} (full marks at {S['paired_full_pct']}%)"),
             ((1.0 if any(x.strip() in IN_DEMAND for x in sw.split(",")) else 0.5 if sw not in ("", "Unknown") else 0.0),
              f"software: {sw or 'unknown'}")]
    pillars["Native richness"] = pillar(parts, "no evidence")

    labels = {"Duplicate %": "duplicates", "Stub Parts %": "stub parts under 10 KB", "Backup Files %": "backup and old revision files", "Unreadable %": "unreadable or tiered files"}
    parts = [(_ramp_down(m[k], S["hygiene_ok_pct"], S["hygiene_zero_pct"]), f"{labels[k]} {pct(m[k])}") for k in labels]
    pillars["Hygiene"] = pillar(parts, "no evidence")
    pillars["Hygiene"] = (pillars["Hygiene"][0], pillars["Hygiene"][1] + [f"full marks up to {S['hygiene_ok_pct']}% each, zero at {S['hygiene_zero_pct']}%"])

    parts = [(_ramp_down(m["Library Part Share %"], S["library_ok_pct"], S["library_zero_pct"]),
              f"standard library parts {pct(m['Library Part Share %'])} (full marks up to {S['library_ok_pct']}%)"),
             (0.0 if m["Possible Copy Of"] else 1.0, f"copy of another project: {'yes, of ' + m['Possible Copy Of'] if m['Possible Copy Of'] else 'no'}"),
             (None if m["Cross Seller Duplicate %"] is None else max(0.0, 1.0 - m["Cross Seller Duplicate %"] / 50.0),
              f"files also sold by another seller {pct(m['Cross Seller Duplicate %'])}")]
    pillars["Originality"] = pillar(parts, "no evidence")
    if m["Library Part Share %"] is None:
        pillars["Originality"][1].append("library share unknown (coded names)")
    if m["Cross Seller Duplicate %"] is None:
        pillars["Originality"][1].append("no fingerprints: cross seller copies not checked")

    weights = dict(SETTINGS["weights"])
    if m["Scan Only References"]:
        weights["Structure and completeness"] /= 2
    used = {k: w for k, w in weights.items() if pillars[k][0] is not None}
    raw = 100.0 * sum(pillars[k][0] * w for k, w in used.items()) / sum(used.values()) if used else 0.0

    caps = []
    cap = 100.0
    if m["Cross Seller Duplicate %"] is not None and m["Cross Seller Duplicate %"] > S["cap_cross_seller_pct"]:
        cap = min(cap, 40); caps.append(f"over {S['cap_cross_seller_pct']}% of files also sold by another seller: capped at 40")
    if m["Possible Copy Of"]:
        cap = min(cap, 40); caps.append(f"copy of project {m['Possible Copy Of']}: capped at 40")
    if m["Library Part Share %"] is not None and m["Library Part Share %"] > S["cap_library_pct"]:
        cap = min(cap, 55); caps.append(f"library parts over {S['cap_library_pct']}%: capped at 55")
    if m["no_native"]:
        cap = min(cap, 70); caps.append("no native files (neutral and PDF only): capped at 70")
    if (m["Unreadable %"] or 0) > S["cap_unreadable_pct"]:
        cap = min(cap, 70); caps.append(f"unreadable or tiered files over {S['cap_unreadable_pct']}%: capped at 70, incomplete evidence")
    if m["Scan Only References"]:
        caps.append("references from text search only: structure counted at half weight")
    score = round(min(raw, cap), 1)
    grade = next((g for t, g in SETTINGS["grades"] if score >= t), "F")
    if m["Export Marked Files"]:
        grade = "HOLD"
        caps.append("ITAR, EAR or export control markings: compliance hold, no grade until the seller clears it in writing")
    unscored = [k for k in weights if k not in used]
    if unscored:
        caps.append("not scored (no evidence): " + ", ".join(unscored) + "; the other pillars carry its weight")
    return score, grade, pillars, caps


# ---------------------------------------------------------------------------------------------------------------- build
def build(zips, out, sellers_csv=None, answers_path=None, cards=True, log=print):
    zips = [z for z in zips if os.path.basename(z).startswith("profile_")]
    if not zips:
        raise SystemExit("no step 2 profile zips (profile_*.zip) given")
    os.makedirs(out, exist_ok=True)
    sellers = {r["zip"]: r["seller"] for r in _rows(sellers_csv)} if sellers_csv else {}
    answers = _read_answers(answers_path)
    classes = _ext_classes()
    datasets, seller_rows, fp_index = [], [], collections.defaultdict(list)
    used_names = collections.Counter()

    for zp in sorted(zips):
        seller = _seller_of(zp, sellers)
        used_names[seller] += 1
        if used_names[seller] > 1:
            seller = f"{seller} ({used_names[seller]})"
        log(f"compiling {os.path.basename(zp)} as seller '{seller}'")
        cdir = compile_one(zp, os.path.join(out, "compiled", re.sub(r"[^A-Za-z0-9_.-]", "_", seller)))
        pc = _rows(os.path.join(cdir, "Project_Compiled.csv"))
        stats = {r["project"]: r for r in _rows(os.path.join(cdir, "Project_Stats.csv"))}
        conf = {r["project"]: r for r in _rows(os.path.join(cdir, "Assembly_Confidence.csv"))}
        dom_rows = {}
        for d in ("Mechanical", "Architecture", "Electronics"):
            for r in _rows(os.path.join(cdir, f"Domain_{d}.csv")):
                dom_rows[r["Project Name"]] = r
        facts, man = seller_facts(zp, classes)
        for fol, f in facts.items():
            for fpv, ext, size in f["fps"]:
                fp_index[fpv].append((seller, fol, ext, size))
        for r in pc:
            proj = r["Project Name"]
            st, ac, dr = stats.get(proj, {}), conf.get(proj, {}), dom_rows.get(proj, {})
            f = facts.get(_folder(proj)) or facts.get(proj) or {}
            total = int(_num(st.get("files_total"), 0))
            parts, asms = int(_num(r["Part Files"], 0)), int(_num(r["Assembly Files"], 0))
            neutral, eda = int(_num(r["Neutral 3D Files"], 0)), int(_num(st.get("eda_files"), 0))
            ndraw = int(_num(r["Native 2D Drawings"], 0))
            refs_t, refs_r = _num(ac.get("refs_total"), 0), _num(ac.get("refs_resolved"), 0)
            yrs = f.get("years", collections.Counter()) if f else collections.Counter()
            nyr = sum(yrs.values())
            unread_n = (f.get("unreadable", 0) + f.get("tiered", 0)) if f else 0
            lk = f.get("link_kinds", collections.Counter()) if f else collections.Counter()
            native3d = parts + asms
            if r["Domain"] == "Electronics":
                native3d = eda
            elif r["Domain"] == "Architecture":
                native3d = int(_num(dr.get("3D File"), native3d) or native3d)
            m = {
                "Dataset ID": f"{seller}:{proj}", "Seller": seller, "Project": proj, "Domain": r["Domain"],
                "Domain Basis": st.get("domain_basis", ""), "Domain Confidence": st.get("domain_confidence", ""),
                "Native CAD Software": r["Native CAD Software"], "Detail Level": man.get("detail_level", ""),
                "Names": man.get("names", "no manifest (older zip)"), "Tool Version": man.get("tool_version", ""),
                "Total Files": total, "Total GB": round(_num(st.get("total_bytes"), 0) / 1e9, 3),
                "Part Files": parts, "Assembly Files": asms, "Native 2D Drawings": ndraw,
                "Drawing Sheets": st.get("drawing_sheets", ""), "PDF Drawings": int(_num(r["PDF Drawings"], 0)),
                "Neutral 3D Files": neutral, "EDA Files": eda,
                "Parts per Assembly": round(parts / asms, 1) if asms else "",
                "References Found": int(refs_t), "References Resolved %": _pct(refs_r, refs_t),
                "Drawings Linked to Assembly %": dr.get("Drawings Linked to Assembly %", ""),
                "Native Share of 3D %": _pct(parts + asms, parts + asms + neutral) if r["Domain"] != "Electronics" else _pct(eda, eda + neutral),
                "Paired Sets %": _pct(f.get("paired", 0), f.get("models", 0)) if f and f.get("models") else None,
                "Complete Project (Y/N)": dr.get("Complete Project (Y/N)", ""), "BOM Present (Y/N)": dr.get("BOM Present (Y/N)", ""),
                "Full-Set Project (Y/N)": dr.get("Full-Set Project (Y/N)", ""),
                "Has Schematic and Layout (Y/N)": dr.get("Has Schematic and Layout (Y/N)", ""),
                "Has Gerber and Drill (Y/N)": dr.get("Has Gerber and Drill (Y/N)", ""),
                "Has Netlist or Simulation (Y/N)": dr.get("Has Netlist or Simulation (Y/N)", ""),
                "Duplicate %": _pct(_num(st.get("duplicate_files"), 0), total),
                "Stub Parts %": _num(dr.get("Stub Parts <10 KB %")),
                "Backup Files %": _pct(_num(dr.get("Backup / Old-Revision Files"), 0), total) if dr.get("Backup / Old-Revision Files", "") != "" else None,
                "Unreadable %": _pct(unread_n, total) if total else None,
                "Unmapped %": _pct(_num(st.get("unmapped"), 0), total),
                "Library Part Share %": (_pct(f["library_parts"], f["parts"]) if f and f.get("library_known") and f.get("parts") else None),
                "Possible Copy Of": st.get("possible_copy_of", ""),
                "Cross Seller Duplicate %": None,
                "Export Marked Files": sum((f.get("marked_files") or collections.Counter())[k] for k in gd_signals.COMPLIANCE_CODES) if f else 0,
                "Confidential Marked Files": sum((f.get("marked_files") or collections.Counter())[k] for k in ("CONFIDENTIAL", "PROPRIETARY")) if f else 0,
                "Files Before " + str(SETTINGS["vintage_year"]) + " %": _pct(sum(v for y, v in yrs.items() if y < SETTINGS["vintage_year"]), nyr),
                "Newest Year": max(yrs) if yrs else "", "Oldest Year": min(yrs) if yrs else "",
                "Scan Only References": bool(lk.get("scan")) and not (lk.get("native") or lk.get("step")),
                "native_3d": native3d, "no_native": (parts + asms + ndraw + eda) == 0 and total > 0,
                "_fps": f.get("fps", []) if f else [], "_folder": _folder(proj), "_years": dict(yrs),
                "_split": proj != _folder(proj), "_unread": f.get("unreadable", 0) if f else 0, "_tiered": f.get("tiered", 0) if f else 0,
            }
            datasets.append(m)
        seller_rows.append({"Seller": seller, "Zip": os.path.basename(zp), "Tool Version": man.get("tool_version", ""),
                            "Names": man.get("names", ""), "Fingerprints": "yes" if any(f["fps"] for f in facts.values()) else "no",
                            "Projects": len(pc)})

    # cross seller duplicates (fingerprints)
    for m in datasets:
        fps = m["_fps"]
        if not fps:
            continue
        other = sum(1 for fpv, _e, _s in fps if any(s != m["Seller"] for s, *_ in fp_index[fpv]))
        m["Cross Seller Duplicate %"] = _pct(other, len(fps))
    dup_rows = []
    for fpv, hits in fp_index.items():
        if len(hits) > 1 and len({(s, p) for s, p, *_ in hits}) > 1:
            dup_rows.append({"fingerprint": fpv, "copies": len(hits), "sellers": len({s for s, *_ in hits}),
                             "where": "; ".join(sorted({f"{s}:{p}" for s, p, *_ in hits})), "ext": hits[0][2], "size_bytes": hits[0][3]})
    dup_rows.sort(key=lambda r: (-r["sellers"], -r["copies"]))

    # seller answers merge
    conflicts, missing = [], []
    if answers is not None:
        for m in datasets:
            a = answers.get((m["Seller"], m["Project"])) or answers.get(("", m["Project"]))
            for fld in REQUIRED_SELLER_FIELDS:
                if not a or not str(a.get(fld, "")).strip():
                    missing.append({"Dataset ID": m["Dataset ID"], "field": fld})
            if not a:
                continue
            for fld, how in COMPARABLE.items():
                given = str(a.get(fld, "")).strip()
                if not given:
                    continue
                meas = m.get(fld)
                if how == "int":
                    bad = _num(given) is None or int(_num(given)) != int(meas or 0)
                elif how == "contains":
                    bad = given.lower() not in str(meas).lower()
                else:
                    bad = given.lower() != str(meas).lower()
                if bad:
                    conflicts.append({"Dataset ID": m["Dataset ID"], "field": fld, "seller answer": given, "measured (kept)": meas})
            m["Seller Description"] = a.get("Project Description", "")

    # QC flags and scores
    qc_rows, score_rows = [], []
    for m in datasets:
        flags = []
        if m["_unread"]:
            flags.append("UNREADABLE")
        if m["_tiered"]:
            flags.append("TIERED_NOT_READ")
        if m["no_native"]:
            flags.append("NO_NATIVE")
        if m["Scan Only References"]:
            flags.append("SCAN_ONLY_REFS")
        if m["References Found"] and (m["References Resolved %"] or 0) < SETTINGS["flag_low_resolution_pct"]:
            flags.append("LOW_LINK_RESOLUTION")
        if m["Possible Copy Of"]:
            flags.append("WHOLE_PROJECT_COPY")
        if m["Cross Seller Duplicate %"]:
            flags.append("CROSS_SELLER_DUPLICATE")
        if (m["Library Part Share %"] or 0) > SETTINGS["cap_library_pct"]:
            flags.append("LIBRARY_HEAVY")
        if (m["Stub Parts %"] or 0) > SETTINGS["flag_stub_pct"]:
            flags.append("STUB_HEAVY")
        if m["Export Marked Files"]:
            flags.append("EXPORT_MARKING")
        if m["Domain"] == "Unclassified":
            flags.append("UNCLASSIFIED_DOMAIN")
        if (m["Unmapped %"] or 0) > SETTINGS["flag_unmapped_pct"]:
            flags.append("UNMAPPED_EXTENSIONS")
        if any(c["Dataset ID"] == m["Dataset ID"] for c in conflicts):
            flags.append("CONFLICT")
        if any(c["Dataset ID"] == m["Dataset ID"] for c in missing):
            flags.append("MISSING_FIELD")
        m["QC Flags"] = ", ".join(flags)
        desc = dict(QC_FLAGS)
        for fl in flags:
            qc_rows.append({"Dataset ID": m["Dataset ID"], "flag": fl, "meaning": desc[fl]})
        score, grade, pillars, caps = score_dataset(m)
        m["GildDesign Score"], m["Grade"], m["_pillars"], m["Caps and Notes"] = score, grade, pillars, "; ".join(caps)
        row = {"Dataset ID": m["Dataset ID"], "GildDesign Score": score, "Grade": grade}
        for k in SETTINGS["weights"]:
            v = pillars[k][0]
            row[k] = "" if v is None else round(100 * v)
        row["Caps and Notes"] = m["Caps and Notes"]
        score_rows.append(row)
    for s in seller_rows:
        mine = [m for m in datasets if m["Seller"] == s["Seller"]]
        s["Files"] = sum(m["Total Files"] for m in mine)
        s["Average Score"] = round(sum(m["GildDesign Score"] for m in mine) / len(mine), 1) if mine else ""
        s["Datasets on Hold"] = sum(1 for m in mine if m["Grade"] == "HOLD")
        s["QC Flags"] = sum(1 for q in qc_rows if q["Dataset ID"].startswith(s["Seller"] + ":"))

    cat_cols = [k for k in datasets[0] if not k.startswith("_") and k not in ("native_3d", "no_native")] if datasets else []
    for extra in ("Seller Description", "QC Flags", "GildDesign Score", "Grade", "Caps and Notes"):
        if extra in cat_cols:
            cat_cols.remove(extra)
        cat_cols.append(extra)
    for m in datasets:
        m.setdefault("Seller Description", "")
    _write_outputs(out, datasets, cat_cols, seller_rows, score_rows, qc_rows, conflicts, missing, dup_rows, answers is not None)
    if cards:
        _write_cards(out, datasets)
    log(f"catalogue: {len(datasets)} dataset(s) from {len(seller_rows)} seller zip(s); {len(qc_rows)} QC flag(s), "
        f"{len(conflicts)} conflict(s), {len(dup_rows)} duplicate group(s) -> {out}")
    return datasets


# ---------------------------------------------------------------------------------------------------------------- output
NOTES = [
    ("Dataset", "One compiled project of one seller; Dataset ID = seller:project. A project the compiler split by root assembly ('Folder / Root') "
                "takes the folder's signals, fingerprints, vintage and unreadable counts."),
    ("Seller", "The name given in --sellers (zip,seller), else the label in the zip's file name (a code when names were coded)."),
    ("References Resolved %", "Assembly_Confidence: references resolved to a file in the dataset / references found. SolidWorks virtual parts "
                              "(names with ^) never exist as files and lower this figure."),
    ("Paired Sets %", "Parts and assemblies whose name stem also has a drawing (native, DWG/DXF or PDF) or a neutral export; works with coded names "
                      "because a name always gets the same code."),
    ("Library Part Share %", "Parts whose file name matches standard part words (Toolbox, McMaster, Misumi, DIN, ISO, ANSI, screw, bolt, nut, washer, "
                             "bearing ...). Needs real names: blank (not scored) for coded profiles."),
    ("Cross Seller Duplicate %", "Fingerprinted files of this dataset whose fingerprint also occurs at another seller. Blank when the seller ran without "
                                 "--fingerprint."),
    ("Export Marked Files", "Files with ITAR, EAR (EAR99 / ECCN) or export control wording in the text the profiler can read (not DWG, not SolidWorks)."),
    ("Score", "Weighted mean of the pillars with evidence (weights " + ", ".join(f"{k} {w}" for k, w in SETTINGS["weights"].items()) +
              "); a pillar without evidence passes its weight to the others. Grades A 85+, B 70+, C 55+, D 40+, else F; HOLD = export marking."),
    ("Caps", "Copy of another project or over 50% of files also at another seller: 40. Library parts over 50%: 55. No native files: 70. "
             "Unreadable or tiered over 10%: 70. Text search references only: structure pillar at half weight."),
    ("Thresholds", json.dumps(SETTINGS)),
    ("Seller answers", "Wide CSV or XLSX: Project Name (and optionally Seller) plus fields. Compared: " + ", ".join(COMPARABLE) +
                       ". Required: " + "; ".join(REQUIRED_SELLER_FIELDS) + ". Without an answers file MISSING_FIELD is not checked."),
]


def _csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})


def _write_outputs(out, datasets, cat_cols, seller_rows, score_rows, qc_rows, conflicts, missing, dup_rows, have_answers):
    fs = _rows(os.path.join(MAPPING, "format_status.csv"))
    tabs = [
        ("Catalogue", cat_cols, datasets),
        ("Sellers", ["Seller", "Zip", "Tool Version", "Names", "Fingerprints", "Projects", "Files", "Average Score", "Datasets on Hold", "QC Flags"], seller_rows),
        ("Scores", ["Dataset ID", "GildDesign Score", "Grade"] + list(SETTINGS["weights"]) + ["Caps and Notes"], score_rows),
        ("QC Flags", ["Dataset ID", "flag", "meaning"], qc_rows),
        ("Conflicts", ["Dataset ID", "field", "seller answer", "measured (kept)"], conflicts),
        ("Missing Fields", ["Dataset ID", "field"], missing),
        ("Duplicate Groups", ["fingerprint", "copies", "sellers", "where", "ext", "size_bytes"], dup_rows),
        ("Format Status", list(fs[0].keys()) if fs else ["format"], fs),
        ("Method Notes", ["topic", "rule"], [{"topic": t, "rule": r} for t, r in NOTES]
         + [{"topic": "QC " + c, "rule": d} for c, d in QC_FLAGS]
         + ([] if have_answers else [{"topic": "Seller answers", "rule": "none given in this run"}])),
    ]
    _csv(os.path.join(out, "catalogue.csv"), cat_cols, datasets)
    _csv(os.path.join(out, "scores.csv"), tabs[2][1], score_rows)
    _csv(os.path.join(out, "qc", "qc_report.csv"), tabs[3][1], qc_rows)
    _csv(os.path.join(out, "qc", "conflicts.csv"), tabs[4][1], conflicts)
    _csv(os.path.join(out, "qc", "missing_fields.csv"), tabs[5][1], missing)
    _csv(os.path.join(out, "qc", "duplicate_groups.csv"), tabs[6][1], dup_rows)
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl not installed: CSVs written, design_catalogue.xlsx skipped")
        return
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="1F3A5F")
    for name, cols, rows in tabs:
        ws = wb.create_sheet(name)
        ws.append(cols)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), head_fill
        for r in rows:
            ws.append([("" if r.get(k) is None else (r.get(k) if not isinstance(r.get(k), (list, dict, set)) else str(r.get(k)))) for k in cols])
        ws.freeze_panes = "B2" if name == "Catalogue" else "A2"
        for i, col in enumerate(cols, 1):
            longest = max([len(str(col))] + [len(str(r.get(col, "") or "")) for r in rows[:200]])
            ws.column_dimensions[get_column_letter(i)].width = min(60, max(10, longest + 2))
    wb.save(os.path.join(out, "design_catalogue.xlsx"))


GRADE_COLOR = {"A": "#1b7f4d", "B": "#3a8f3a", "C": "#b88a00", "D": "#c06000", "F": "#b3261e", "HOLD": "#6b3fa0"}
PLAIN = {"Scale": "How much design data there is", "Structure and completeness": "How complete and connected the projects are",
         "Native richness": "How much is in native, editable CAD form", "Hygiene": "How clean the files are",
         "Originality": "How original and unique the data is"}


def _card(m):
    e = html.escape
    bars = "".join(
        f"<div class='row'><div class='lab'><b>{e(k)}</b><span>{e(PLAIN[k])}</span></div><div class='bar'><i style='width:{0 if v is None else round(100 * v)}%'></i></div>"
        f"<div class='val'>{'n/a' if v is None else round(100 * v)}</div></div><div class='why'>{e('; '.join(notes))}</div>"
        for k, (v, notes) in m["_pillars"].items())
    flags = "".join(f"<li>{e(f)}</li>" for f in (m["QC Flags"].split(", ") if m["QC Flags"] else [])) or "<li>None</li>"
    caps = "".join(f"<li>{e(c)}</li>" for c in (m["Caps and Notes"].split("; ") if m["Caps and Notes"] else [])) or "<li>None</li>"
    yrs = m["_years"]
    vint = "".join(f"<div class='yr'><i style='height:{max(2, round(60 * n / max(yrs.values())))}px'></i><span>{y}</span></div>" for y, n in sorted(yrs.items())[-12:])
    facts = [("Domain", f"{m['Domain']} ({m['Domain Confidence'] or 'n/a'} confidence)"), ("Native software", m["Native CAD Software"]),
             ("Files", f"{m['Total Files']:,} ({m['Total GB']} GB)"), ("Parts / assemblies / drawings", f"{m['Part Files']:,} / {m['Assembly Files']:,} / {m['Native 2D Drawings']:,}"),
             ("References resolved", "n/a" if m["References Resolved %"] is None else f"{m['References Resolved %']}% of {m['References Found']:,}"),
             ("Names in the profile", m["Names"]), ("Profiler", m["Tool Version"] or "unknown")]
    rows = "".join(f"<tr><td>{e(a)}</td><td>{e(str(b))}</td></tr>" for a, b in facts)
    gc = GRADE_COLOR.get(m["Grade"], "#444")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>GildDesign Score: {e(m['Dataset ID'])}</title>
<style>body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f5f6f8;color:#1d2433}}
.card{{max-width:860px;margin:24px auto;background:#fff;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.08);padding:28px 32px}}
.top{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #e6e8ec;padding-bottom:16px}}
h1{{font-size:20px;margin:0}} .sub{{color:#5b6475;font-size:13px;margin-top:4px}}
.grade{{text-align:center}} .grade b{{display:block;font-size:44px;color:{gc};line-height:1}} .grade span{{font-size:13px;color:#5b6475}}
.row{{display:grid;grid-template-columns:300px 1fr 44px;gap:12px;align-items:center;margin-top:16px}} .lab span{{display:block;font-size:12px;color:#5b6475}}
.bar{{background:#eef0f3;border-radius:6px;height:12px;overflow:hidden}} .bar i{{display:block;height:100%;background:#2f6fd6}}
.val{{text-align:right;font-weight:600}} .why{{font-size:11.5px;color:#5b6475;margin:4px 0 0 0}}
h2{{font-size:14px;margin:24px 0 8px}} ul{{margin:0;padding-left:18px;font-size:13px}} table{{border-collapse:collapse;font-size:13px;width:100%}}
td{{padding:5px 8px;border-bottom:1px solid #eef0f3}} td:first-child{{color:#5b6475;width:240px}}
.vint{{display:flex;gap:6px;align-items:flex-end;height:80px}} .yr{{display:flex;flex-direction:column;align-items:center;font-size:10.5px;color:#5b6475}}
.yr i{{display:block;width:22px;background:#9bb7e6;border-radius:3px 3px 0 0}} .foot{{font-size:11px;color:#8a92a3;margin-top:20px}}</style></head>
<body><div class="card"><div class="top"><div><h1>{e(m['Project'])}</h1><div class="sub">Seller {e(m['Seller'])} &middot; Dataset {e(m['Dataset ID'])}</div></div>
<div class="grade"><b>{e(m['Grade'])}</b><span>GildDesign Score {m['GildDesign Score']}</span></div></div>
{bars}<h2>Red flags and caps</h2><ul>{caps}</ul><h2>QC flags</h2><ul>{flags}</ul><h2>Key facts</h2><table>{rows}</table>
<h2>Files by last modified year (shown, not scored)</h2><div class="vint">{vint or '<span>no dates</span>'}</div>
<div class="foot">Scored at GildData from the seller's metrics zip; no file contents were seen. Thresholds are starting values (see Method Notes in design_catalogue.xlsx).</div>
</div></body></html>"""


def _write_cards(out, datasets):
    d = os.path.join(out, "cards")
    os.makedirs(d, exist_ok=True)
    links = []
    for m in sorted(datasets, key=lambda x: -x["GildDesign Score"]):
        fn = re.sub(r"[^A-Za-z0-9_.-]", "_", m["Dataset ID"]) + ".html"
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            f.write(_card(m))
        links.append(f"<tr><td><a href='{html.escape(fn)}'>{html.escape(m['Dataset ID'])}</a></td><td>{html.escape(m['Domain'])}</td>"
                     f"<td>{m['GildDesign Score']}</td><td><b>{html.escape(m['Grade'])}</b></td><td>{html.escape(m['QC Flags'])}</td></tr>")
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><head><meta charset='utf-8'><title>GildDesign Scores</title><style>body{font-family:system-ui,sans-serif;margin:32px;color:#1d2433}"
                "table{border-collapse:collapse;font-size:14px}td,th{padding:6px 12px;border-bottom:1px solid #e6e8ec;text-align:left}</style></head><body>"
                "<h1>GildDesign Scores</h1><table><tr><th>Dataset</th><th>Domain</th><th>Score</th><th>Grade</th><th>QC flags</th></tr>"
                + "".join(links) + "</table></body></html>")
