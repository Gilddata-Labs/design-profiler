"""Milestone 2 readers (gd_signals): compliance markings, DXF xrefs, Revit facts and links, opt in fingerprints; their path through the
profiler (Files.csv columns signals / fp, Links.csv kinds xref / revit_link) and what must never leave the machine.
Run: python3 tests/test_gd_m2.py"""
import csv
import io
import os
import shutil
import struct
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import file_profiler as fp  # noqa: E402
import gd_signals  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": {got!r} (wanted {want!r})"))
    if not ok:
        FAILS.append(label)


def cfb(streams):
    """A minimal valid Compound File (v3, 512 byte sectors) holding the given {name: bytes} streams, each padded to >= 4096 bytes so no
    mini stream is needed. Enough for the profiler's OLE reader and tag."""
    END, FREE, FATSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF
    items = [(n, d.ljust(max(4096, (len(d) + 511) // 512 * 512), b"\x00")) for n, d in streams.items()]
    fat, data, starts, sec = [FATSECT, END], b"", [], 2
    for _n, d in items:
        k = len(d) // 512
        starts.append(sec)
        fat += [sec + i + 1 for i in range(k - 1)] + [END]
        data += d
        sec += k
    fat += [FREE] * (128 - len(fat))

    def entry(name, typ, left, right, child, start, size):
        nm = name.encode("utf-16-le") + b"\x00\x00"
        return (nm.ljust(64, b"\x00") + struct.pack("<HBB", len(nm), typ, 1) + struct.pack("<III", left, right, child)
                + b"\x00" * 16 + b"\x00" * 4 + b"\x00" * 16 + struct.pack("<IQ", start, size))
    ents = [entry("Root Entry", 5, NOSTREAM, NOSTREAM, 1, END, 0)]
    for i, ((n, d), st) in enumerate(zip(items, starts)):
        ents.append(entry(n, 2, NOSTREAM, i + 2 if i + 1 < len(items) else NOSTREAM, NOSTREAM, st, len(d)))   # padded size: >= 4096, so regular sectors
    dirsec = b"".join(ents).ljust(512, b"\x00")
    hdr = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
           + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, END, 0, END, 0) + struct.pack("<I", 0) + struct.pack("<108I", *([FREE] * 108)))
    return hdr + struct.pack("<128I", *fat) + dirsec + data


def put(base, rel, data):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def scan_bytes(data, ext, key=None):
    t = tempfile.NamedTemporaryFile(delete=False)
    t.write(data)
    t.close()
    try:
        with open(t.name, "rb") as fh:
            return gd_signals.scan(fh, ext, len(data), key)
    finally:
        os.unlink(t.name)


# 1. markings: counts only, word bounded, ASCII and UTF-16
r = scan_bytes(b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ITAR controlled','ECCN 9E991'),'2;1');\nENDSEC;\n", "stp")
check("STEP header: ITAR and EAR counted", gd_signals.parse(r["signals"]), {"ITAR": 1, "EAR": 1})
r = scan_bytes(b"\xd0\xcf\x11\xe0" + "Company Confidential / Export Controlled".encode("utf-16-le"), "dft")
check("UTF-16 property text: CONFIDENTIAL and EXPORT counted", gd_signals.parse(r["signals"]), {"CONFIDENTIAL": 1, "EXPORT": 1})
r = scan_bytes(b"  0\nTEXT\n  1\nCAPITAR SPEARS GEAR CONFIDENTIALITY confidentially\n", "dxf")
check("no false alarm inside other words (CAPITAR, GEAR, CONFIDENTIALITY)", r["signals"], "")
r = scan_bytes(b"(kicad_pcb (version 20240108))\n", "kicad_pcb")
check("clean file: no signals", r["signals"], "")

# 2. DXF xrefs: names only, xref flag required
dxf = (b"  0\nSECTION\n  2\nBLOCKS\n  0\nBLOCK\n  2\nTITLE\n 70\n     0\n  1\nnot_an_xref.dwg\n  0\nENDBLK\n"
       b"  0\nBLOCK\n  2\nSITE\n 70\n     4\n  1\nC:\\Clients\\Acme\\site plan.dwg\n  0\nENDBLK\n"
       b"  0\nBLOCK\n  2\nGRID\n 70\n    12\n  1\n../shared/grid.dxf\n  0\nENDBLK\n  0\nENDSEC\n  0\nEOF\n")
r = scan_bytes(dxf, "dxf")
check("DXF: only xref blocks, base names only", r["xrefs"], ["grid.dxf", "site plan.dwg"])
check("DXF: XREFS count in signals", gd_signals.parse(r["signals"]).get("XREFS"), 2)

# 3. Revit: version, workshared, links; never the user name or paths
basic = "Worksharing: Not enabled\r\nUsername: jdoe_secret\r\nCentral Model Path: \\\\fileserver\\Acme\\central.rvt\r\nFormat: 2021\r\nBuild: 20210224_1515(x64)\r\n"
trans = "<ExternalFileReference><Path>C:\\Acme\\Links\\Structure_Model.rvt</Path></ExternalFileReference><Path>..\\cad\\SitePlan.dwg</Path>"
rvt = cfb({"BasicFileInfo": basic.encode("utf-16-le"), "TransmissionData": trans.encode("utf-16-le")})
facts, links = gd_signals.revit_info(rvt)
check("Revit: version year and workshared read", facts, {"REVIT_VERSION": 2021, "REVIT_WORKSHARED": 0})
check("Revit: linked file names, no paths", links, ["SitePlan.dwg", "Structure_Model.rvt"])

# 4. fingerprints
a = os.urandom(300_000)
k = b"test-key"
fa, fa2 = scan_bytes(a, "stp", k)["fp"], scan_bytes(a, "step", k)["fp"]
fb = scan_bytes(a[:-1] + bytes([a[-1] ^ 1]), "stp", k)["fp"]
check("fingerprint: same content, same fingerprint", fa, fa2)
check("fingerprint: last byte changed, different fingerprint", fa != fb, True)
check("fingerprint: another key gives another fingerprint", fa != scan_bytes(a, "stp", b"other")["fp"], True)
check("no key: no fingerprint", scan_bytes(a, "stp")["fp"], "")

# 5. through the profiler: columns, links, run info, nothing leaked; off by default
t = tempfile.mkdtemp()
try:
    src = os.path.join(t, "data")
    put(src, "Proj/model.rvt", rvt)
    put(src, "Proj/plan.dxf", dxf)
    put(src, "Proj/part.stp", b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ITAR'),'2;1');\nFILE_NAME('a','',(''),(''),'','','');\nENDSEC;\nDATA;\nENDSEC;\n")
    put(src, "Proj/photo.jpg", b"\xff\xd8\xff" + os.urandom(5000))
    z, *_ = fp.profile(src, os.path.join(t, "o1"), log=lambda *a: None)
    with zipfile.ZipFile(z) as zf:
        rows = {r["rel_path"]: r for r in csv.DictReader(io.StringIO(zf.read("Files.csv").decode("utf-8-sig")))}
        links = list(csv.DictReader(io.StringIO(zf.read("Links.csv").decode("utf-8-sig"))))
        info = dict(r[:2] for r in csv.reader(io.StringIO(zf.read("Run_info.csv").decode("utf-8-sig"))) if len(r) >= 2)
        alltext = "".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())
    check("profile: Revit tagged and its facts in signals", (rows["model.rvt"]["header_signature"], gd_signals.parse(rows["model.rvt"]["signals"])),
          ("OLE2:Revit", {"REVIT_VERSION": 2021, "REVIT_WORKSHARED": 0}))
    check("profile: STEP marking counted", gd_signals.parse(rows["part.stp"]["signals"]), {"ITAR": 1})
    check("profile: fingerprints OFF by default", any(r["fp"] for r in rows.values()), False)
    check("profile: xref and Revit links in Links.csv", sorted((l["kind"], l["child"]) for l in links if l["kind"] in ("xref", "revit_link")),
          [("revit_link", "SitePlan.dwg"), ("revit_link", "Structure_Model.rvt"), ("xref", "grid.dxf"), ("xref", "site plan.dwg")])
    check("profile: Run_info counts marked files", (info.get("files_with_signals"), info.get("files_marked_ITAR")), ("3", "1"))
    check("profile: no user name, server path or folder of a link leaves", any(s in alltext for s in ("jdoe_secret", "fileserver", "C:\\Acme", "Clients\\Acme")), False)
    z2, *_ = fp.profile(src, os.path.join(t, "o2"), log=lambda *a: None, design_fp=True)
    with zipfile.ZipFile(z2) as zf:
        rows2 = {r["rel_path"]: r for r in csv.DictReader(io.StringIO(zf.read("Files.csv").decode("utf-8-sig")))}
        info2 = dict(r[:2] for r in csv.reader(io.StringIO(zf.read("Run_info.csv").decode("utf-8-sig"))) if len(r) >= 2)
    check("fingerprint ON: design files fingerprinted, the photo is not", (bool(rows2["part.stp"]["fp"]), bool(rows2["photo.jpg"]["fp"])), (True, False))
    check("fingerprint ON: Run_info says what was hashed", info2["hashing"].startswith("keyed partial fingerprint"), True)
    z3, *_ = fp.profile(src, os.path.join(t, "o3"), log=lambda *a: None, tier=1)
    with zipfile.ZipFile(z3) as zf:
        hdr = zf.read("Files.csv").decode("utf-8-sig").splitlines()[0]
    check("level 1: no signals or fp columns (level 2 only)", ("signals" in hdr, "fp" in hdr), (False, False))
finally:
    shutil.rmtree(t, ignore_errors=True)

print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
