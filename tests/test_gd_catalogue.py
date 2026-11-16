"""Milestone 3: design catalogue, QC flags, seller answers merge, GildDesign Score and cards (gd_catalogue).
Run: python3 tests/test_gd_catalogue.py"""
import csv
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import file_profiler as fp  # noqa: E402
import gd_catalogue as gc  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": {got!r} (wanted {want!r})"))
    if not ok:
        FAILS.append(label)


def put(base, rel, data):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


def step(name, extra=""):
    return (f"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('{extra}'),'2;1');\nFILE_NAME('{name}','2024',(''),(''),'','SolidWorks 2023','');\n"
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n" + "x" * 3000)


SW = b"\x00" * 13 + b"\x14\x00\x06\x00\x08\x00"

# 1. score arithmetic on a fixed dataset (hand checked)
m = {"Domain": "Mechanical", "native_3d": 5000, "Assembly Files": 0, "Native 2D Drawings": 0, "References Resolved %": 90.0,
     "Drawings Linked to Assembly %": "70", "Complete Project (Y/N)": "Y", "BOM Present (Y/N)": "", "Native Share of 3D %": 80.0,
     "Paired Sets %": 50.0, "Native CAD Software": "SolidWorks", "Duplicate %": 0.0, "Stub Parts %": 0.0, "Backup Files %": None,
     "Unreadable %": 0.0, "Library Part Share %": 10.0, "Possible Copy Of": "", "Cross Seller Duplicate %": 0.0, "Scan Only References": False,
     "no_native": False, "Export Marked Files": 0}
score, grade, pillars, caps = gc.score_dataset(m)
check("a dataset at every full marks threshold scores 100, grade A", (score, grade), (100.0, "A"))
m2 = dict(m, **{"Duplicate %": 15.0})                       # hygiene: 15% is half way from 5 to 25 -> 0.5; backup unknown, so mean of 3 parts = 0.8333
s2, *_ = gc.score_dataset(m2)
check("duplicates at 15%: hygiene 83.3 -> score 100 - 15 x 0.1667 = 97.5", s2, 97.5)
s3, g3, _p, c3 = gc.score_dataset(dict(m, **{"Possible Copy Of": "Other project"}))
check("copy of another project: capped at 40", (s3, g3), (40.0, "D"))
s4, g4, *_ = gc.score_dataset(dict(m, **{"Export Marked Files": 2}))
check("export marking: compliance HOLD, score kept", (s4, g4), (100.0, "HOLD"))
s5, g5, p5, c5 = gc.score_dataset(dict(m, **{"Library Part Share %": None, "Cross Seller Duplicate %": None}))
check("unknown library share and fingerprints: originality from the copy check alone", round(p5["Originality"][0], 2), 1.0)
s6, *_ = gc.score_dataset(dict(m, **{"no_native": True}))
check("no native files: capped at 70", s6, 70.0)
s7, g7, p7, c7 = gc.score_dataset(dict(m, **{"Scan Only References": True, "References Resolved %": 0.0, "Drawings Linked to Assembly %": "0",
                                            "Complete Project (Y/N)": "N"}))
check("text search references only: structure at half weight", round(s7, 1), round(100 * (15 + 0 + 20 + 15 + 25) / 87.5, 1))

# 2. end to end: two sellers, a copy sold twice, a marked file, seller answers
t = tempfile.mkdtemp()
try:
    a, b = os.path.join(t, "seller_a"), os.path.join(t, "seller_b")
    for i in range(6):
        put(a, f"Machine/part{i}.sldprt", SW + os.urandom(3000))
    put(a, "Machine/machine.sldasm", SW + os.urandom(4000))
    put(a, "Machine/machine.step", step("machine"))
    put(a, "Secret/turbine.step", step("turbine", "ITAR controlled"))
    shared = step("bracket") + "unique-bytes-123"
    put(a, "Brackets/bracket.step", shared)
    put(b, "Bought/renamed_bracket.step", shared)
    put(b, "Bought/own_part.sldprt", SW + os.urandom(5000))
    out = os.path.join(t, "zips")
    za, *_ = fp.profile(a, out, log=lambda *x: None, design_fp=True, anonymize_names=False)
    zb, *_ = fp.profile(b, out, log=lambda *x: None, design_fp=True, anonymize_names=True)
    ans = os.path.join(t, "answers.csv")
    with open(ans, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Seller", "Project Name", "Project Description", "Rights to sell (Y/N)", "Original author (in house / client / third party)", "Part Files"])
        w.writerow(["A", "Machine", "A small machine", "Y", "in house", "9"])
    sellers = os.path.join(t, "sellers.csv")
    with open(sellers, "w", newline="") as f:
        f.write(f"zip,seller\n{os.path.basename(za)},A\n{os.path.basename(zb)},B\n")
    co = os.path.join(t, "cat")
    ds = gc.build([za, zb], co, sellers_csv=sellers, answers_path=ans, log=lambda *x: None)
    by = {d["Dataset ID"]: d for d in ds}
    check("one dataset per seller project", sorted(by)[:4], ["A:Brackets", "A:Machine", "A:Secret", sorted(by)[3]])
    check("seller B's project name stays a code", sorted(by)[3].startswith("B:P-"), True)
    check("the bracket sold by both sellers: cross seller duplicate", (by["A:Brackets"]["Cross Seller Duplicate %"], "CROSS_SELLER_DUPLICATE" in by["A:Brackets"]["QC Flags"]), (100.0, True))
    check("a project with nothing shared: 0% cross seller", by["A:Machine"]["Cross Seller Duplicate %"], 0.0)
    check("ITAR marking: HOLD and flagged", (by["A:Secret"]["Grade"], "EXPORT_MARKING" in by["A:Secret"]["QC Flags"]), ("HOLD", True))
    conf = list(csv.DictReader(open(os.path.join(co, "qc", "conflicts.csv"), encoding="utf-8-sig")))
    check("seller says 9 parts, 6 measured: CONFLICT, measured kept", [(c["Dataset ID"], c["field"], c["seller answer"], c["measured (kept)"]) for c in conf],
          [("A:Machine", "Part Files", "9", "6")])
    miss = {(r["Dataset ID"], r["field"]) for r in csv.DictReader(open(os.path.join(co, "qc", "missing_fields.csv"), encoding="utf-8-sig"))}
    check("answered project has no missing fields; unanswered ones do", (any(d == "A:Machine" for d, _ in miss), ("A:Secret", "Rights to sell (Y/N)") in miss), (False, True))
    dup = list(csv.DictReader(open(os.path.join(co, "qc", "duplicate_groups.csv"), encoding="utf-8-sig")))
    check("duplicate group across 2 sellers listed", [(r["copies"], r["sellers"]) for r in dup], [("2", "2")])
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(co, "design_catalogue.xlsx"))
    check("workbook tabs", wb.sheetnames, ["Catalogue", "Sellers", "Scores", "QC Flags", "Conflicts", "Missing Fields", "Duplicate Groups", "Format Status", "Method Notes"])
    cards = sorted(os.listdir(os.path.join(co, "cards")))
    check("one card per dataset plus an index", len(cards), len(ds) + 1)
    btext = open(os.path.join(co, "cards", [c for c in cards if c.startswith("B_")][0]), encoding="utf-8").read()
    check("seller B's card shows no real name", any(s in btext for s in ("Bought", "renamed_bracket", "own_part")), False)
    check("compiled buyer workbook kept per seller", os.path.exists(os.path.join(co, "compiled", "A", "compiled.xlsx")), True)
finally:
    shutil.rmtree(t, ignore_errors=True)

print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
