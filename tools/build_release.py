"""Build the release zips and their checksums.

    python3 tools/build_release.py            -> dist/gilddesign-<ver>-supplier.zip, dist/gilddesign-<ver>-internal.zip, dist/SHA256SUMS.txt
    python3 tools/build_release.py --windows  -> also dist/gilddesign-<ver>-supplier-windows.zip: the supplier zip plus a python/ folder
                                                 with the embeddable Python, for sellers who have no Python installed (run.bat and
                                                 run-ui.bat use python\python.exe when that folder exists)

supplier: what sellers run (check, quick, extract, cloud, ui). No compiler, no tests, no buyer templates, EDITION=supplier.
internal: everything GildData needs (compile, compare, verify, tests, the profile-compile skill), EDITION=internal.
Each zip unpacks into one folder gilddesign-<ver>/. Nothing in the release can update itself: a new version is a new zip.
Standard library only. Builds are reproducible: fixed file order and fixed timestamps, so the same tree gives the same checksums.
"""
import hashlib
import io
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import gd_version  # noqa: E402

SUPPLIER = [
    "gilddesign.py", "gd_version.py", "gd_manifest.py", "gd_check.py", "gd_signals.py",
    "file_profiler.py", "cad_links.py", "dwg_sheets.py", "name_anon.py", "sysmetrics.py", "diag.py", "ui.py",
    "fusion_cloud_profiler.py", "ext_classes.csv", "UPSTREAM_COMMIT",
    "run.bat", "run.command", "run-ui.bat", "run-ui.command", "run-docker.bat", "run-docker.sh",
    "Dockerfile", "docker-compose.yml", ".dockerignore", ".env.example", "README_FIRST.txt",
]
EXCLUDE_DIRS = {".git", "dist", "output", "__pycache__", ".resume", "python", ".venv", "venv"}
# Windows bundle: the official embeddable Python (standard library only, no installer, no registry). Pinned by checksum so the
# bundle is reproducible; to move to a newer Python update all three values together.
EMBED_PY_VERSION = "3.12.10"
EMBED_PY_URL = f"https://www.python.org/ftp/python/{EMBED_PY_VERSION}/python-{EMBED_PY_VERSION}-embed-amd64.zip"
EMBED_PY_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
EXECUTABLE = (".sh", ".command")


def internal_files():
    out = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(x for x in dirs if x not in EXCLUDE_DIRS)
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, "/")
            if rel != "EDITION" and not f.endswith(".pyc"):
                out.append(rel)
    return out


def build(edition, files, dist):
    top = f"gilddesign-{gd_version.TOOL_VERSION}"
    path = os.path.join(dist, f"{top}-{edition}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files):
            src = os.path.join(ROOT, rel)
            if not os.path.exists(src):
                raise SystemExit(f"missing for the {edition} release: {rel}")
            info = zipfile.ZipInfo(f"{top}/{rel}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if rel.endswith(EXECUTABLE) else 0o644) << 16
            with open(src, "rb") as f:
                z.writestr(info, f.read())
        info = zipfile.ZipInfo(f"{top}/EDITION", FIXED_TIME)
        info.external_attr = 0o644 << 16
        z.writestr(info, edition + "\n")
    return path


def embeddable_python():
    """The embeddable Python zip, downloaded once into dist/ and checked against the pinned SHA256."""
    cache = os.path.join(ROOT, "dist", os.path.basename(EMBED_PY_URL))
    if not os.path.exists(cache):
        print(f"downloading {EMBED_PY_URL}")
        with urllib.request.urlopen(EMBED_PY_URL, timeout=120) as r, open(cache, "wb") as f:
            f.write(r.read())
    if sha256(cache) != EMBED_PY_SHA256:
        os.remove(cache)
        raise SystemExit("the embeddable Python download does not match the pinned checksum; refusing to bundle it")
    return cache


def build_windows(dist):
    """Supplier zip plus python/: the embeddable Python with the app folder added to its path."""
    top = f"gilddesign-{gd_version.TOOL_VERSION}"
    path = os.path.join(dist, f"{top}-supplier-windows.zip")
    with zipfile.ZipFile(embeddable_python()) as py, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(SUPPLIER):
            info = zipfile.ZipInfo(f"{top}/{rel}", FIXED_TIME); info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if rel.endswith(EXECUTABLE) else 0o644) << 16
            with open(os.path.join(ROOT, rel), "rb") as f:
                z.writestr(info, f.read())
        info = zipfile.ZipInfo(f"{top}/EDITION", FIXED_TIME); info.external_attr = 0o644 << 16
        z.writestr(info, "supplier\n")
        for name in sorted(py.namelist()):
            data = py.read(name)
            if name.endswith("._pth"):
                # the embeddable Python only searches the entries in this file: add the app folder (one level up)
                data = data.rstrip(b"\r\n") + b"\r\n..\r\n"
            info = zipfile.ZipInfo(f"{top}/python/{name}", FIXED_TIME); info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        info = zipfile.ZipInfo(f"{top}/python/README.txt", FIXED_TIME); info.external_attr = 0o644 << 16
        z.writestr(info, f"Embeddable Python {EMBED_PY_VERSION} from python.org, unchanged except for the added '..' line in the "
                         f"._pth file so the profiler next to this folder can be imported. SHA256 of the original download: "
                         f"{EMBED_PY_SHA256}\n")
    return path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    built = [build("supplier", SUPPLIER, dist), build("internal", internal_files(), dist)]
    if "--windows" in sys.argv[1:]:
        built.append(build_windows(dist))
    sums = os.path.join(dist, "SHA256SUMS.txt")
    with open(sums, "w", encoding="utf-8", newline="\n") as f:
        for p in built:
            f.write(f"{sha256(p)}  {os.path.basename(p)}\n")
    for p in built:
        print(f"{os.path.basename(p)}  {os.path.getsize(p) / 1024:.0f} KB")
    print(open(sums).read().strip())
    print("Publish SHA256SUMS.txt separately from the zips (e.g. in the email or on the release page), so a seller can check the download.")


if __name__ == "__main__":
    main()
