"""GildData Milestone 2 readers: facts about a design file that buyers and QC need, written as a CLOSED vocabulary only. Standard library.

    scan(fh, ext, size, fingerprint_key=None) -> {"signals": "ITAR=1;CONFIDENTIAL=2;REVIT_VERSION=2021", "fp": "...", "xrefs": [...],
                                                   "links": [...]}

Never kept: any text of the file. Only a count per marking word, a version year, yes/no facts, the NAMES of referenced files (which go
through the same name coding as Links.csv), and a keyed fingerprint.

1. Compliance markings (counts): ITAR, EAR (EAR99 / ECCN / "export administration regulations"), EXPORT ("export controlled" /
   "export control"), CONFIDENTIAL, PROPRIETARY. Searched in the first SCAN_BYTES of text based CAD files (DXF, STEP, IFC, IGES, KiCad)
   and of OLE based CAD files (Solid Edge, Inventor, Revit, whose properties are UTF-16: NUL bytes are removed before searching, so both
   ASCII and UTF-16 text match). AutoCAD DWG and SolidWorks keep their text compressed, so markings there are NOT seen (said in the
   format status table).
2. AutoCAD xrefs from DXF: BLOCK records with the xref flag (group 70, bit 4); the base name of the path in group 1.
3. Revit (.rvt / .rfa, OLE): the version year and workshared yes/no from the BasicFileInfo stream (user names and paths there are NOT
   kept), and the names of linked files from the TransmissionData stream. Written from the published descriptions of these streams;
   NOT yet checked on real Revit files (no public samples were available to the test campaign).
4. Fingerprint (opt in): BLAKE2b keyed with GildData's key over the size, the first 64 KB and the last 64 KB. Same file = same
   fingerprint at every seller, so copies sold twice are found at GildData; without the key a fingerprint says nothing about a file.
"""
import hashlib
import re

SCAN_BYTES = 4 * 1024 * 1024
FP_PART = 64 * 1024
MAX_OLE_BYTES = 256 * 1024 * 1024        # a Revit file is parsed whole; bigger ones get markings and fingerprint only

TEXT_EXTS = frozenset("dxf step stp ifc igs iges kicad_pcb kicad_sch sch brd".split())
OLE_EXTS = frozenset("par psm asm pwd dft ipt iam idw ipn rvt rfa rte".split())
SIGNAL_EXTS = TEXT_EXTS | OLE_EXTS
FP_CLASSES = frozenset(("PART", "ASSEMBLY", "DRAWING", "NEUTRAL3D", "EDA"))   # fingerprinted when on: design files only, not images or office files

MARKINGS = [  # (code, pattern) - word bounded, case insensitive; the code is all that is kept
    ("ITAR", re.compile(rb"\bITAR\b|international\s+traffic\s+in\s+arms", re.I)),
    ("EAR", re.compile(rb"\bEAR99\b|\bECCN\b|export\s+administration\s+regulations", re.I)),
    ("EXPORT", re.compile(rb"export[\s_-]?controll?ed\b|\bexport\s+control\b", re.I)),
    ("CONFIDENTIAL", re.compile(rb"\bconfidential\b", re.I)),
    ("PROPRIETARY", re.compile(rb"\bproprietary\b", re.I)),
]
COMPLIANCE_CODES = ("ITAR", "EAR", "EXPORT")

_LINKABLE = r"rvt|rfa|dwg|dxf|ifc|nwc|nwd|dgn|skp|sat|3dm|rcp|rcs"
_REVIT_LINK = re.compile(r"([^\\/:*?\"<>|\x00-\x1f]{1,200}\.(?:" + _LINKABLE + r"))\b", re.I)


# Cheap first pass: the lowercase keyword each pattern needs. Almost no file carries a marking, so the exact (word bounded) regex runs only
# when its keyword occurs at all; bytes.find is C speed, the regexes were 0.4 s per 4 MB file (the corpus run went from 8 s to 34 s).
_KEYS = {"ITAR": (b"itar", b"international traffic"), "EAR": (b"ear99", b"eccn", b"export administration"),
         "EXPORT": (b"export",), "CONFIDENTIAL": (b"confidential",), "PROPRIETARY": (b"proprietary",)}


def _markings(blob):
    text = blob.replace(b"\x00", b"") if b"\x00" in blob[:65536] else blob    # UTF-16 text (OLE properties) becomes plain ASCII
    low = text.lower()
    out = {}
    for code, rx in MARKINGS:
        if not any(k in low for k in _KEYS[code]):
            continue
        n = len(rx.findall(text))
        if n:
            out[code] = n
    return out


def dxf_xrefs(data):
    """Base names of xref'd drawings in a DXF's BLOCKS section (closed: names only)."""
    m = re.search(rb"\n[ \t]*2[ \t]*\r?\n[ \t]*BLOCKS[ \t]*\r?\n", data)
    if not m:
        return []
    end = re.search(rb"\n[ \t]*0[ \t]*\r?\n[ \t]*ENDSEC[ \t]*\r?\n", data[m.end():])
    sec = data[m.end(): m.end() + end.start()] if end else data[m.end():]
    lines = sec.decode("latin-1").splitlines()
    out, i, in_block, flags, path = [], 0, False, 0, ""
    while i + 1 < len(lines):
        code, val = lines[i].strip(), lines[i + 1].strip()
        i += 2
        if code == "0":
            if in_block and flags & 4 and path:
                out.append(re.split(r"[\\/]", path)[-1])
            in_block, flags, path = val == "BLOCK", 0, ""
        elif in_block and code == "70":
            try:
                flags = int(val)
            except ValueError:
                flags = 0
        elif in_block and code == "1":
            path = val
    return sorted(set(out), key=str.lower)


def revit_info(data):
    """-> ({"REVIT_VERSION": year, "REVIT_WORKSHARED": 0/1}, [linked file names]) from an OLE Revit file; ({}, []) if not readable."""
    try:
        import cad_links
        cfb = cad_links._CFB(data)
    except Exception:  # noqa: BLE001
        return {}, []
    facts, links = {}, set()
    for name, blob in cfb.streams():
        base = name.split("/")[-1]
        if base == "BasicFileInfo":
            text = blob.decode("utf-16-le", "ignore") + " " + blob.decode("latin-1", "ignore")
            m = re.search(r"Format:\s*(20\d\d)", text) or re.search(r"Autodesk Revit (?:\w+ )?(20\d\d)", text)
            if m:
                facts["REVIT_VERSION"] = int(m.group(1))
            w = re.search(r"Worksharing:\s*([A-Za-z ]+)", text)
            if w:
                facts["REVIT_WORKSHARED"] = 0 if "not" in w.group(1).lower() else 1
        elif base == "TransmissionData":
            text = blob.decode("utf-16-le", "ignore")
            for m in _REVIT_LINK.finditer(text):
                links.add(re.split(r"[\\/]", m.group(1).strip())[-1])
    return facts, sorted(links, key=str.lower)


def fingerprint(fh, size, key):
    h = hashlib.blake2b(key=key[:64], digest_size=12)
    h.update(str(size).encode())
    fh.seek(0)
    h.update(fh.read(FP_PART))
    if size > FP_PART:
        fh.seek(max(FP_PART, size - FP_PART))
        h.update(fh.read(FP_PART))
    return h.hexdigest()


def scan(fh, ext, size, fingerprint_key=None, want_signals=True):
    out = {"signals": "", "fp": "", "xrefs": [], "links": []}
    facts = {}
    if want_signals and ext in SIGNAL_EXTS and size > 0:
        fh.seek(0)
        if ext in ("rvt", "rfa", "rte") and size <= MAX_OLE_BYTES:
            data = fh.read()
            facts.update(_markings(data[:SCAN_BYTES]))
            rf, out["links"] = revit_info(data)
            facts.update(rf)
        else:
            head = fh.read(SCAN_BYTES)
            facts.update(_markings(head))
            if ext == "dxf":
                out["xrefs"] = dxf_xrefs(head)
                if out["xrefs"]:
                    facts["XREFS"] = len(out["xrefs"])
    if fingerprint_key and size > 0:
        out["fp"] = fingerprint(fh, size, fingerprint_key)
    out["signals"] = ";".join(f"{k}={v}" for k, v in sorted(facts.items()))
    return out


def parse(signals):
    """'ITAR=1;CONFIDENTIAL=2' -> {'ITAR': 1, 'CONFIDENTIAL': 2}"""
    out = {}
    for part in (signals or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                out[k] = int(v)
            except ValueError:
                pass
    return out
