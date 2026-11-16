"""manifest.json: the first thing GildData's compile step reads from a seller's zip.

It says which tool and version made the zip, what kind of zip it is (quick = Step 1, profile = Step 2), the detail level, whether
names are coded or real (and that real names were the seller's own choice), and a SHA256 of every other member so a zip that was
edited after the run is noticed. It holds no file names, paths or contents. Standard library only.
"""
import datetime
import hashlib
import json
import zipfile

import gd_version

SCHEMA = "gilddesign.manifest/1"
MEMBER = "manifest.json"


def build(zip_path, kind, detail_level=None, names_coded=False, project_depth=None, engine_version="", extra=None):
    members = {}
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.filename == MEMBER or info.is_dir():
                continue
            h = hashlib.sha256()
            with z.open(info) as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            members[info.filename] = {"sha256": h.hexdigest(), "bytes": info.file_size}
    m = {
        "schema": SCHEMA,
        "tool": gd_version.TOOL_NAME,
        "tool_version": gd_version.TOOL_VERSION,
        "edition": gd_version.edition(),
        "engine": "folder-profiler",
        "engine_version": engine_version,
        "engine_upstream_commit": gd_version.upstream_commit(),
        "kind": kind,
        "detail_level": detail_level,
        "names": "coded" if names_coded else "real (seller's choice)",
        "project_depth": project_depth,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "members": members,
    }
    if extra:
        m.update(extra)
    return m


def stamp(zip_path, kind, **kw):
    """Add manifest.json to a finished zip (append mode; the other members are untouched). Returns the manifest dict."""
    m = build(zip_path, kind, **kw)
    with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as z:
        if MEMBER in z.namelist():
            raise ValueError(f"{zip_path} already has a {MEMBER}")
        z.writestr(MEMBER, json.dumps(m, indent=2, sort_keys=True))
    return m


def read(zip_path):
    """The manifest of a zip, or None for zips made before manifests existed (upstream Folder Profiler zips)."""
    with zipfile.ZipFile(zip_path) as z:
        if MEMBER not in z.namelist():
            return None
        return json.loads(z.read(MEMBER).decode("utf-8"))


def verify(zip_path):
    """-> (ok, problems). Checks every listed member is present with the same SHA256, and nothing was added."""
    m = read(zip_path)
    if m is None:
        return False, ["no manifest.json (made by an older or upstream profiler)"]
    problems = []
    if m.get("schema") != SCHEMA:
        problems.append(f"unknown manifest schema {m.get('schema')!r}")
    with zipfile.ZipFile(zip_path) as z:
        names = {i.filename for i in z.infolist() if not i.is_dir()} - {MEMBER}
        for name, meta in m.get("members", {}).items():
            if name not in names:
                problems.append(f"missing member {name}")
                continue
            h = hashlib.sha256()
            with z.open(name) as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            if h.hexdigest() != meta.get("sha256"):
                problems.append(f"changed after the run: {name}")
        for name in sorted(names - set(m.get("members", {}))):
            problems.append(f"added after the run: {name}")
    return not problems, problems
