"""GildData layer: gilddesign CLI, manifest, coded names by default, check, compare, editions.
Run: python3 tests/test_gd.py   (optional env GD_UPSTREAM=/path/to/data847/folder-profiler for the parity test against upstream)"""
import json
import os
os.environ.setdefault("PROFILER_NO_REVEAL", "1"); os.environ.setdefault("PROFILER_NO_BROWSER", "1")
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import gd_compare  # noqa: E402
import gd_manifest  # noqa: E402

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


def run(*args, cwd=ROOT, root=ROOT):
    r = subprocess.run([sys.executable, os.path.join(root, "gilddesign.py"), *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def zips(out, prefix):
    return sorted(os.path.join(out, f) for f in os.listdir(out) if f.startswith(prefix) and f.endswith(".zip"))


def all_text(zpath):
    with zipfile.ZipFile(zpath) as z:
        return b"".join(z.read(n) for n in z.namelist()).decode("utf-8", "replace")


t = tempfile.mkdtemp()
try:
    data = os.path.join(t, "data")
    put(data, "SecretClientAlpha/bracket_TOPSECRET.sldprt", os.urandom(20000))
    put(data, "SecretClientAlpha/sub/frame.sldasm", os.urandom(30000))
    put(data, "SecretClientAlpha/frame.step", "ISO-10303-21;\nHEADER;\nFILE_NAME('a','2024',(''),(''),'','SolidWorks 2022','');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    put(data, "ProjectBeta/plan.dxf", "  0\nSECTION\n  2\nHEADER\n  9\n$ACADVER\n  1\nAC1027\n  0\nENDSEC\n  0\nEOF\n")
    put(data, "ProjectBeta/model.rvt", os.urandom(9000))
    out = os.path.join(t, "out")

    # check: counts only, no names
    rc, txt = run("check", data, "--out", out, "--seconds", "5")
    check("check runs and passes", rc, 0)
    rep = json.load(open(sorted(f for f in (os.path.join(out, x) for x in os.listdir(out)) if f.endswith(".json"))[-1]))
    check("check counted every file", rep["listing"]["files"], 5)
    check("check report holds no folder or file names", any(s in json.dumps(rep) for s in ("SecretClientAlpha", "TOPSECRET", "ProjectBeta")), False)

    # quick + extract: names coded by default, manifest stamped and valid
    rc, txt = run("quick", data, "--out", out)
    check("quick runs", rc, 0)
    rc, txt = run("extract", data, "--out", out)
    check("extract runs", rc, 0)
    q, p = zips(out, "quick_")[-1], zips(out, "profile_")[-1]
    for label, z in (("quick", q), ("profile", p)):
        m = gd_manifest.read(z)
        check(f"{label}: manifest present", m is not None)
        check(f"{label}: manifest kind", m and m["kind"], label)
        check(f"{label}: names coded by default", m and m["names"], "coded")
        check(f"{label}: verify OK", gd_manifest.verify(z)[0])
        check(f"{label}: no real names anywhere in the zip", any(s in all_text(z) for s in ("SecretClientAlpha", "TOPSECRET", "ProjectBeta")), False)
    check("profile: detail level 2 by default", gd_manifest.read(p)["detail_level"], 2)
    check("name map kept outside the profile zip", bool(zips(out, "name_map_")))

    # compare: Step 1 vs Step 2 identical
    same, rows, notes = gd_compare.compare(q, p, log=lambda *_: None)
    check("compare: Step 1 equals Step 2", same)

    # tamper: a changed member is caught
    bad = os.path.join(t, "tampered.zip")
    with zipfile.ZipFile(p) as src, zipfile.ZipFile(bad, "w") as dst:
        for n in src.namelist():
            b = src.read(n)
            dst.writestr(n, b + b"\r\nextra,1" if n == "Projects.csv" else b)
    ok, problems = gd_manifest.verify(bad)
    check("verify catches a member changed after the run", (ok, any("Projects.csv" in x for x in problems)), (False, True))
    rc, txt = run("verify", bad)
    check("verify command exits 1 on a tampered zip", rc, 1)

    # real names only on request, recorded in the manifest
    out2 = os.path.join(t, "out_real")
    rc, txt = run("extract", data, "--out", out2, "--real-names")
    p2 = zips(out2, "profile_")[-1]
    check("--real-names: manifest says real (seller's choice)", gd_manifest.read(p2)["names"], "real (seller's choice)")
    check("--real-names: real names present", "SecretClientAlpha" in all_text(p2))
    same, rows, notes = gd_compare.compare(p, p2, log=lambda *_: None)
    check("coded vs real: totals identical, projects not matched", (same, any("overall totals only" in n for n in notes)), (True, True))

    # compile through gilddesign
    rc, txt = run("compile", out, "--", "--out", os.path.join(t, "compiled"))
    check("compile runs", rc, 0)
    check("compile wrote Project_Compiled.csv", os.path.exists(os.path.join(t, "compiled", "Project_Compiled.csv")))

    # supplier edition: internal commands refused
    sup = os.path.join(t, "supplier")
    shutil.copytree(ROOT, sup, ignore=shutil.ignore_patterns("tests", "profile-compile", ".git", "output", "__pycache__", "dist"))
    open(os.path.join(sup, "EDITION"), "w").write("supplier\n")
    rc, txt = run("compile", out, root=sup, cwd=sup)
    check("supplier edition refuses compile", (rc, "internal edition" in txt), (2, True))
    rc, txt = run("--version", root=sup, cwd=sup)
    check("supplier edition reports itself", "(supplier)" in txt)

    # parity with upstream (optional): same folder, same counts
    up = os.environ.get("GD_UPSTREAM")
    if up and os.path.exists(os.path.join(up, "file_profiler.py")):
        out3 = os.path.join(t, "out_up")
        subprocess.run([sys.executable, os.path.join(up, "file_profiler.py"), data, "--out", out3], capture_output=True, timeout=300)
        u = zips(out3, "profile_")[-1]
        same, rows, notes = gd_compare.compare(u, p2, log=lambda *_: None)
        check("parity: upstream profile and ours give identical counts and bytes", same)
        check("parity: upstream zip has no manifest", gd_manifest.read(u), None)
    else:
        print("skip parity with upstream (set GD_UPSTREAM)")
finally:
    shutil.rmtree(t, ignore_errors=True)

print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
