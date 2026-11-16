"""compare: two profiler zips side by side (internal edition).

Uses: our zip against an upstream Folder Profiler zip of the same folder (the counts must be identical), Step 1 against Step 2 of
one run, or two runs of one seller months apart. Reads Extensions.csv from each zip (both Step 1 and Step 2 zips have it, as do
upstream zips) and compares file counts and bytes per file type, overall and per project. When one zip has coded names and the
other real names, projects cannot be matched, so only the overall totals are compared and the report says so.
Writes compare_<stamp>.csv; returns (identical, rows, notes). Standard library only.
"""
import collections
import csv
import datetime
import io
import os
import zipfile

import gd_manifest

FIELDS = ["scope", "project", "ext", "a_files", "b_files", "diff_files", "a_bytes", "b_bytes", "diff_bytes"]


def _kind(names):
    if "Files.csv" in names:
        return "profile (Step 2)"
    if "Extensions_All.csv" in names:
        return "quick (Step 1)"
    return "unknown"


def load(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        if "Extensions.csv" not in names:
            raise SystemExit(f"{os.path.basename(zip_path)}: no Extensions.csv, not a profiler zip")
        rows = list(csv.DictReader(io.StringIO(z.read("Extensions.csv").decode("utf-8-sig"))))
        info = {}
        if "Run_info.csv" in names:
            for r in csv.reader(io.StringIO(z.read("Run_info.csv").decode("utf-8-sig"))):
                if len(r) >= 2:
                    info.setdefault(r[0], r[1])
    per = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        k = (r["project"], (r["ext"] or "").lower())
        per[k][0] += int(r["file_count"] or 0)
        per[k][1] += int(r["total_bytes"] or 0)
    try:
        man = gd_manifest.read(zip_path)
    except Exception:  # noqa: BLE001
        man = None
    coded = (man or {}).get("names", "").startswith("coded") if man else info.get("names_anonymized") == "yes"
    return {"path": zip_path, "kind": _kind(names), "per": per, "coded": coded, "manifest": man, "info": info}


def compare(a_path, b_path, out_dir=None, log=print):
    A, B = load(a_path), load(b_path)
    notes = [f"A: {os.path.basename(a_path)} | {A['kind']} | names {'coded' if A['coded'] else 'real'} | "
             f"{'manifest ' + A['manifest']['tool_version'] if A['manifest'] else 'no manifest (upstream or older zip)'}",
             f"B: {os.path.basename(b_path)} | {B['kind']} | names {'coded' if B['coded'] else 'real'} | "
             f"{'manifest ' + B['manifest']['tool_version'] if B['manifest'] else 'no manifest (upstream or older zip)'}"]
    rows = []

    def add(scope, proj, ext, a, b):
        if a != b:
            rows.append([scope, proj, ext, a[0], b[0], b[0] - a[0], a[1], b[1], b[1] - a[1]])

    tot_a, tot_b = collections.defaultdict(lambda: [0, 0]), collections.defaultdict(lambda: [0, 0])
    for (p, e), v in A["per"].items():
        tot_a[e][0] += v[0]; tot_a[e][1] += v[1]
    for (p, e), v in B["per"].items():
        tot_b[e][0] += v[0]; tot_b[e][1] += v[1]
    for e in sorted(set(tot_a) | set(tot_b)):
        add("overall", "", e, tot_a.get(e, [0, 0]), tot_b.get(e, [0, 0]))

    projects_a = {p for p, _ in A["per"]}
    projects_b = {p for p, _ in B["per"]}
    if A["coded"] != B["coded"] or (projects_a and not projects_a & projects_b):
        notes.append("project names do not match (coded in one zip, real in the other, or different folders): compared overall totals only")
    else:
        for k in sorted(set(A["per"]) | set(B["per"])):
            add("project", k[0], k[1], A["per"].get(k, [0, 0]), B["per"].get(k, [0, 0]))
        only = sorted(projects_a ^ projects_b)
        if only:
            notes.append(f"{len(only)} project(s) appear in only one zip")

    fa, fb = sum(v[0] for v in tot_a.values()), sum(v[0] for v in tot_b.values())
    ba, bb = sum(v[1] for v in tot_a.values()), sum(v[1] for v in tot_b.values())
    notes.append(f"totals: A {fa:,} files {ba:,} bytes | B {fb:,} files {bb:,} bytes")
    identical = not rows
    notes.append("IDENTICAL counts and bytes per file type" if identical else f"{len(rows)} difference(s)")
    for n in notes:
        log(n)
    path = ""
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"compare_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            w.writerows(rows)
            w.writerow([])
            for n in notes:
                w.writerow(["note", n])
        log(f"report: {path}")
    return identical, rows, notes
