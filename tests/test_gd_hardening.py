"""0.4.0 hardening: output folders that cannot be written give a message and exit 1, not a traceback; the seller
answers column map renames intake form headings; the Windows bundle builder adds python/ with the app on its path.
Run:  python tests/test_gd_hardening.py"""
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from _helpers import zopen  # noqa: E402
import gd_catalogue  # noqa: E402
import build_release  # noqa: E402

bad = []
def check(label, got, want):
    ok = got == want; print(("ok   " if ok else "FAIL ") + f"{label}: {got}" + ("" if ok else f"   (wanted {want})")); bad.append(not ok)

def run(*args):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "gilddesign.py"), *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr

with tempfile.TemporaryDirectory() as t:
    src = os.path.join(t, "data", "P"); os.makedirs(src)
    with open(os.path.join(src, "a.step"), "w") as f:
        f.write("ISO-10303-21;\n")
    # ---- output path is a file
    afile = os.path.join(t, "afile.txt"); open(afile, "w").write("x")
    rc, out = run("extract", os.path.join(t, "data"), "--out", afile)
    check("output path is a file: exit 1 with a plain message", (rc, "Cannot write to the output folder" in out, "Traceback" in out), (1, True, False))
    rc, out = run("quick", os.path.join(t, "data"), "--out", afile)
    check("quick: same check", (rc, "Traceback" in out), (1, False))
    # ---- output folder not writable (POSIX, not root)
    if os.name != "nt" and not (hasattr(os, "geteuid") and os.geteuid() == 0):
        ro = os.path.join(t, "ro"); os.makedirs(ro); os.chmod(ro, 0o555)
        try:
            rc, out = run("extract", os.path.join(t, "data"), "--out", os.path.join(ro, "out"))
            check("read only output folder: exit 1 with a plain message", (rc, "Cannot write to the output folder" in out, "Traceback" in out), (1, True, False))
        finally:
            os.chmod(ro, 0o755)
    else:
        print("skip read only output folder (Windows or root)")
    # ---- a good run still works and the folder is created
    rc, out = run("extract", os.path.join(t, "data"), "--out", os.path.join(t, "new", "deeper"))
    check("output folder is created when missing", (rc, os.path.isdir(os.path.join(t, "new", "deeper"))), (0, True))

    # ---- answers column map
    answers = os.path.join(t, "form.csv")
    with open(answers, "w", encoding="utf-8", newline="") as f:
        f.write("Which project?,Seller,Describe the project,Can you sell it (Y/N),Who made it\n")
        f.write("Alpha,Acme,A bracket family,Y,in house\n")
    amap = os.path.join(t, "map.csv")
    with open(amap, "w", encoding="utf-8", newline="") as f:
        f.write("form_column,field\nWhich project?,Project Name\nDescribe the project,Project Description\n"
                "Can you sell it (Y/N),Rights to sell (Y/N)\nWho made it,Original author (in house / client / third party)\n")
    got = gd_catalogue._read_answers(answers, gd_catalogue._read_answers_map(amap))
    row = got.get(("Acme", "Alpha"))
    check("intake form headings renamed through the map", (row or {}).get("Rights to sell (Y/N)"), "Y")
    loose = gd_catalogue._read_answers(answers, {"  which PROJECT? ": "Project Name", "describe the  Project": "Project Description"})
    check("map matching ignores case and spacing", loose.get(("Acme", "Alpha"), {}).get("Project Description"), "A bracket family")
    check("without a map, no 'Project Name' column gives no rows", gd_catalogue._read_answers(answers), {})
    jmap = os.path.join(t, "map.json"); json.dump({"Which project?": "Project Name"}, open(jmap, "w"))
    check("JSON map works too", list(gd_catalogue._read_answers(answers, gd_catalogue._read_answers_map(jmap)).keys()), [("Acme", "Alpha")])

    # ---- Windows bundle builder (no network: a fake embeddable zip stands in for the download)
    fake = os.path.join(t, "python-embed.zip")
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("python.exe", b"MZ"); z.writestr("python312._pth", b"python312.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n")
    real_embed, real_sha, real_root = build_release.embeddable_python, build_release.sha256, build_release.ROOT
    build_release.embeddable_python = lambda: fake
    dist = os.path.join(t, "dist"); os.makedirs(dist)
    path = build_release.build_windows(dist)
    with zopen(path) as z:
        names = z.namelist(); top = names[0].split("/")[0]
        pth = z.read(f"{top}/python/python312._pth").decode()
        check("bundle holds the supplier files, EDITION=supplier and python/", (f"{top}/gilddesign.py" in names, z.read(f"{top}/EDITION").decode().strip(), f"{top}/python/python.exe" in names), (True, "supplier", True))
        check("the app folder is on the embedded Python's path", pth.rstrip().endswith(".."), True)
        check("no internal file in the bundle", any("gd_catalogue" in n or "/tests/" in n or "profile-compile" in n for n in names), False)
    # ---- the checksum pin is enforced: a download that does not match is deleted and refused
    import urllib.request
    real_open = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: io.BytesIO(b"PK\x05\x06" + b"\0" * 18)
    build_release.embeddable_python, build_release.sha256, build_release.ROOT = real_embed, (lambda p: "0" * 64), t
    try:
        build_release.embeddable_python(); refused = False
    except SystemExit as e:
        refused = "checksum" in str(e)
    finally:
        urllib.request.urlopen = real_open
        build_release.sha256, build_release.ROOT = real_sha, real_root
    check("a download with the wrong checksum is refused and removed", (refused, os.listdir(os.path.join(t, "dist"))), (True, [os.path.basename(path)]))

# ---- the launchers and compose file name the image after the release version: catch drift when TOOL_VERSION is bumped
import gd_version
for name in ("run-docker.sh", "run-docker.bat", "docker-compose.yml"):
    text = open(os.path.join(ROOT, name), encoding="utf-8").read()
    check(f"{name} uses the gilddesign:{gd_version.TOOL_VERSION} image", f"gilddesign:{gd_version.TOOL_VERSION}" in text, True)
for name in ("run-docker.sh", "run-docker.bat", "docker-compose.yml"):
    text = open(os.path.join(ROOT, name), encoding="utf-8").read()
    check(f"{name} gives the sealed container a writable /tmp", "tmpfs" in text, True)

sys.exit(1 if any(bad) else 0)
