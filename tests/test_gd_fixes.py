"""Regression tests for the fixes found by GildData's real file test campaign (16 Nov 2026).
Run: python3 tests/test_gd_fixes.py   (optional GD_CORPUS=/path/to/corpus adds checks on real DWG files)"""
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "claude-skill", "profile-compile", "scripts"))
import cad_links  # noqa: E402
import dwg_sheets  # noqa: E402
import file_profiler as fp  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": {got!r} (wanted {want!r})"))
    if not ok:
        FAILS.append(label)


def sig_of(data, ext):
    t = tempfile.NamedTemporaryFile(delete=False, suffix="." + ext)
    t.write(data)
    t.close()
    try:
        return fp.signature(t.name, ext, len(data))
    finally:
        os.unlink(t.name)


# 1. authoring tool from the header, not from DATA words
ifc_revit = (b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
             b"FILE_NAME('a.ifc','2021-01-01',(''),(''),'The EXPRESS Data Manager Version 5.02','21.0.0.383 - Exporter 21.0.0.383','');\n"
             b"FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n#1=IFCPERSON($,$,'',$,$,$,$,$);\n#5=IFCAPPLICATION(#1,'2021','Autodesk Revit 2021 (ENU)','Revit');\n"
             b"#9=IFCPRODUCTDEFINITIONSHAPE($,$,(#10));\n")
check("IFC: IFCAPPLICATION names Revit; IFCPRODUCTDEFINITIONSHAPE is not Onshape", sig_of(ifc_revit, "ifc"), "IFC:IFC4:Revit")
ifc_plain = ifc_revit.replace(b"#5=IFCAPPLICATION(#1,'2021','Autodesk Revit 2021 (ENU)','Revit');\n", b"")
check("IFC: without an application record, a DATA word gives no tool", sig_of(ifc_plain, "ifc"), "IFC:IFC4:other")
step_occ = (b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\nFILE_NAME('m','2008',('--- Datakit ---'),(''),' Release Version','Open CASCADE 6.1',' ');\n"
            b"FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n#1=APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#2);\n"
            b"#20=UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#5,'distance_accuracy_value','confusion accuracy');\n"
            b"#21=GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT('fusion accuracy');\n")
check("STEP: 'fusion accuracy' in DATA is not Fusion 360; originating system wins", sig_of(step_occ, "stp"), "STEP:AP214:OpenCascade")
step_kicad = step_occ.replace(b"' Release Version','Open CASCADE 6.1'", b"'Open CASCADE STEP processor 7.7','KiCad to STEP converter'")
check("STEP: originating system before preprocessor (KiCad over Open CASCADE)", sig_of(step_kicad, "step"), "STEP:AP214:KiCad")
line = lambda text, sec, n: text.ljust(72)[:72] + sec + str(n).rjust(7).encode() + b"\n"
iges = (line(b"Some start text", b"S", 1) + line(b"1H,,1H;,7HMyPart,8Hpart.igs,18HRhinoceros ( Apr 9,8H06/06/20", b"G", 1)
        + line(b"     110       1       0       0       0", b"D", 1) + line(b"onshape fusion", b"P", 1))
check("IGES: tool from the Global section only", sig_of(iges, "igs"), "IGES:Rhino")

# 2. SolidWorks content tag
check("SolidWorks container marker -> SWX:SolidWorks", sig_of(b"\x00" * 13 + b"\x14\x00\x06\x00\x08\x00" + b"\x00" * 300, "sldprt"), "SWX:SolidWorks")
check("marker beyond 32 bytes is not SolidWorks", sig_of(b"\x00" * 64 + b"\x14\x00\x06\x00\x08\x00" + b"\x00" * 300, "bin"), "BINARY")

# 3. STEP product names: a Part 21 line break inside a name is not part of it
step_wrapped = (b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1=PRODUCT('top_asm','top_asm','',(#9));\n#2=PRODUCT('long_part_na\r\nme','long_part_na\r\nme','',(#9));\n"
                b"#3=PRODUCT_DEFINITION_FORMATION('','',#1);\n#4=PRODUCT_DEFINITION_FORMATION('','',#2);\n#5=PRODUCT_DEFINITION('d','',#3,#9);\n"
                b"#6=PRODUCT_DEFINITION('d','',#4,#9);\n#7=NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','','',#5,#6,$);\nENDSEC;\nEND-ISO-10303-21;\n")
r = cad_links.step_structure_bytes(step_wrapped)
check("STEP: wrapped product name joined (no line break kept)", r and r["parents"].get("top_asm"), ["long_part_name"])

# 4. DXF sheet statuses
def dxf(body, ver=b"AC1032", eof=True):
    return (b"  0\nSECTION\n  2\nHEADER\n  9\n$ACADVER\n  1\n" + ver + b"\n  0\nENDSEC\n  0\nSECTION\n  2\nOBJECTS\n" + body
            + b"  0\nENDSEC\n" + (b"  0\nEOF\n" if eof else b""))


lay = lambda name: b"  0\nLAYOUT\n  5\n1\n100\nAcDbPlotSettings\n100\nAcDbLayout\n  1\n" + name + b"\n"
r = dwg_sheets.dxf_sheets(dxf(b""))
check("DXF 2018 with no LAYOUT objects: status no-layout-objects (not the version's fault)", (r["sheets"], r["code"]), (None, "no-layout-objects"))
r = dwg_sheets.dxf_sheets(dxf(b"", ver=b"AC1009"))
check("DXF R12: no-layouts-in-version", r["code"], "no-layouts-in-version")
r = dwg_sheets.dxf_sheets(dxf(lay(b"Model") + lay(b"Layout1") + lay(b"Layout2")))
check("DXF intact: 2 sheets, confidence 99", (r["sheets"], r["confidence"], r["code"]), (2, 99, "ok"))
broken = dxf(lay(b"Model") + lay(b"Layout1") + lay(b"Layout2").replace(b"\nLAYOUT\n", b"\nLAYOUU\n", 1))
r = dwg_sheets.dxf_sheets(broken)
check("DXF with a damaged LAYOUT record: flagged, confidence below 90", (r["code"], r["confidence"] < 90), ("dxf-inconsistent", True))
r = dwg_sheets.dxf_sheets(dxf(lay(b"Model") + lay(b"Layout1"), eof=False))
check("DXF without EOF: dxf-incomplete, confidence below 90", (r["code"], r["confidence"] < 90), ("dxf-incomplete", True))

# 5. DWG truncation (real files, optional)
corpus = os.environ.get("GD_CORPUS")
if corpus and os.path.isdir(corpus):
    real = []
    for d, _, fs in os.walk(corpus):
        for f in fs:
            if f.lower().endswith(".dwg"):
                data = open(os.path.join(d, f), "rb").read()
                if data[:6] in (b"AC1018", b"AC1024", b"AC1027", b"AC1032"):
                    real.append(data)
    check("real R2004+ DWGs: none flagged as truncated", sum(bool(dwg_sheets._truncated_r2004(x)) for x in real), 0)
    check("real R2004+ DWGs cut to 95%: all flagged", all(dwg_sheets.count_sheets_bytes(x[:int(len(x) * .95)], "dwg")["code"] == "truncated" for x in real), True)
else:
    print("skip real DWG truncation checks (set GD_CORPUS)")

# 6. compiler: a stray file of a specific tool does not decide a project's domain; KiCad files are mapped
t = tempfile.mkdtemp()
try:
    src = os.path.join(t, "parent")
    for i in range(40):
        p = os.path.join(src, "Models", f"m{i}.fcstd")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(b"PK\x03\x04" + os.urandom(100))
    open(os.path.join(src, "Models", "stray.asc"), "w").write("Version 4\nSHEET 1 880 680\n")
    for n in ("board.kicad_pcb", "fp.kicad_mod", "sym.kicad_sym", "proj.kicad_pro"):
        p = os.path.join(src, "Board", n)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("(kicad_pcb (version 20240108))\n" if n.endswith("pcb") else "(x)\n")
    os.makedirs(os.path.join(src, "Loop"), exist_ok=True)
    os.symlink(os.path.join(src, "Loop", "missing_target"), os.path.join(src, "Loop", "dangling.sldprt"))
    open(os.path.join(src, "Loop", "ok.sldprt"), "wb").write(b"x")
    out = os.path.join(t, "out")
    z, *_ = fp.profile(src, out, log=lambda *a: None, anonymize_names=True)
    check("coded run: zip file name carries the folder's code, not 'parent'", os.path.basename(z).startswith("profile_P-"), True)
    zr, *_ = fp.profile(src, os.path.join(t, "out_real"), log=lambda *a: None)
    with zipfile.ZipFile(zr) as zf:
        unread = zf.read("Unreadable.csv").decode("utf-8-sig").strip().splitlines()[1:]
    check("a dangling link is listed once in Unreadable.csv", len(unread), 1)
    import compile_profiles as cp
    runs = cp.load_profiles([zr])
    ext_map, soft = cp.load_mapping(os.path.join(ROOT, "claude-skill", "profile-compile", "scripts", "mapping"))
    co = os.path.join(t, "compiled")
    os.makedirs(co)
    sys.argv = ["compile_profiles.py", zr, "--out", co]
    try:
        cp.main()
    except SystemExit:
        pass
    import csv
    stats = {r["Project Name"]: r for r in csv.DictReader(open(os.path.join(co, "Project_Compiled.csv"), encoding="utf-8-sig"))}
    check("1 stray LTspice file among 40 FreeCAD models does not make the project Electronics", stats["Models"]["Domain"] != "Electronics", True)
    unm = open(os.path.join(co, "Review.csv"), encoding="utf-8-sig").read()
    check("KiCad footprint / symbol / project files are mapped", any(x in unm for x in (".kicad_mod", ".kicad_sym", ".kicad_pro")), False)
finally:
    shutil.rmtree(t, ignore_errors=True)

print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
