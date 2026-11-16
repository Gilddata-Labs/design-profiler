"""check: a short, safe first run on the seller's machine before Step 1 and Step 2.

It answers: will the profiler run here, can it read the folder, where will the zip go, how big is the job, and roughly how long will
Step 1 take. It opens no file (it only lists folders, like Step 1) and stops listing after a time budget, so it is quick on a huge
file server too. The report holds counts only: no file or folder names. Standard library only.
"""
import datetime
import json
import os
import platform
import shutil
import sys
import time

import gd_version

MIN_PY = (3, 9)


def _is_network(path):
    p = os.path.abspath(path)
    if p.startswith("\\\\"):
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            drive = os.path.splitdrive(p)[0] + "\\"
            return ctypes.windll.kernel32.GetDriveTypeW(drive) == 4  # DRIVE_REMOTE
        except Exception:  # noqa: BLE001
            return False
    try:  # Linux / macOS: look the mount up
        import subprocess
        fs = subprocess.run(["df", "-P", "-T", p] if sys.platform.startswith("linux") else ["df", "-P", p],
                            capture_output=True, text=True, timeout=5).stdout.splitlines()[-1].split()
        return any(t in fs for t in ("nfs", "nfs4", "cifs", "smbfs", "smb3", "afpfs", "fuse.sshfs"))
    except Exception:  # noqa: BLE001
        return False


def list_budget(root, budget_s=20.0, project_depth=1):
    """Walk the tree (no file opened, links not followed) until done or budget_s runs out."""
    t0 = time.time()
    files = dirs = nbytes = unreadable = links = 0
    exts = set()
    projects = 0
    stack = [(root, 0)]
    complete = True
    while stack:
        if time.time() - t0 > budget_s:
            complete = False
            break
        d, depth = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            links += 1
                            continue
                        if e.is_dir(follow_symlinks=False):
                            dirs += 1
                            if depth + 1 == project_depth:
                                projects += 1
                            stack.append((e.path, depth + 1))
                        elif e.is_file(follow_symlinks=False):
                            files += 1
                            nbytes += e.stat(follow_symlinks=False).st_size
                            n = e.name.lower()
                            if "." in n:
                                exts.add(n.rsplit(".", 1)[1][:12])
                    except OSError:
                        unreadable += 1
        except OSError:
            unreadable += 1
    secs = max(time.time() - t0, 1e-3)
    return {"complete": complete, "seconds": round(secs, 1), "files": files, "folders": dirs, "bytes": nbytes,
            "projects_seen": projects, "distinct_extensions": len(exts), "unreadable": unreadable, "links_skipped": links,
            "files_per_second": round(files / secs)}


def run(folder, out_dir, budget_s=20.0, project_depth=1, log=print):
    rep = {"tool": gd_version.TOOL_NAME, "tool_version": gd_version.TOOL_VERSION, "edition": gd_version.edition(),
           "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "checks": [], "listing": None}

    def item(name, ok, detail):
        rep["checks"].append({"check": name, "result": "OK" if ok is True else ("WARN" if ok is None else "FAIL"), "detail": detail})
        log(f"  [{'OK' if ok is True else ('WARN' if ok is None else 'FAIL')}] {name}: {detail}")

    log(f"{gd_version.TOOL_NAME} {gd_version.TOOL_VERSION}: check\n")
    py = sys.version_info
    item("Python", py >= MIN_PY, f"{py.major}.{py.minor}.{py.micro} on {platform.system()} {platform.release()} (needs {MIN_PY[0]}.{MIN_PY[1]} or newer)")
    here = os.path.dirname(os.path.abspath(__file__))
    missing = [m for m in ("file_profiler.py", "cad_links.py", "dwg_sheets.py", "name_anon.py", "sysmetrics.py", "ext_classes.csv")
               if not os.path.exists(os.path.join(here, m))]
    item("Program files", not missing, "all present" if not missing else "missing: " + ", ".join(missing))

    ok_folder = bool(folder) and os.path.isdir(folder)
    item("Folder", ok_folder, "found and is a folder" if ok_folder else "not found or not a folder")
    if ok_folder:
        try:
            os.listdir(folder)
            item("Read access", True, "the folder can be listed")
        except OSError as e:
            item("Read access", False, f"cannot list the folder ({type(e).__name__})")
            ok_folder = False
        net = _is_network(folder)
        item("Location", True, "network share (Step 2 uses more reader threads)" if net else "local disk")
        rep["network_share"] = net

    try:
        os.makedirs(out_dir, exist_ok=True)
        probe = os.path.join(out_dir, ".write_probe")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        free = shutil.disk_usage(out_dir).free
        item("Output folder", True if free > 2 * 1024**3 else None, f"writable, {free / 1024**3:.1f} GB free"
             + ("" if free > 2 * 1024**3 else " (under 2 GB: very large folders may need more)"))
    except OSError as e:
        item("Output folder", False, f"cannot write there ({type(e).__name__})")

    if ok_folder:
        log(f"\n  Listing the folder for up to {int(budget_s)} seconds (no file is opened)...")
        L = list_budget(folder, budget_s, project_depth)
        rep["listing"] = L
        size = f"{L['files']:,} files, {L['bytes'] / 1e9:.1f} GB, {L['projects_seen']:,} projects, {L['distinct_extensions']} file types"
        if L["complete"]:
            item("Size of the job", True, size + f" (listed in {L['seconds']} s)")
            item("Step 1 time", True, f"about {max(1, round(L['seconds']))} s (Step 1 lists the folder the same way)")
        else:
            item("Size of the job", None, f"at least {size}; listing not finished in {int(budget_s)} s "
                                          f"({L['files_per_second']:,} files a second so far)")
            item("Step 1 time", None, "longer than the check; Step 1 uses several threads and is usually faster than this listing")
        if L["unreadable"]:
            item("Unreadable", None, f"{L['unreadable']} folders or entries could not be read; they will be listed in Unreadable.csv")
        item("Step 2 time", True, "depends on how many CAD files are opened; the zip's run_stats show it afterwards")

    rep["verdict"] = "FAIL" if any(c["result"] == "FAIL" for c in rep["checks"]) else (
        "OK with warnings" if any(c["result"] == "WARN" for c in rep["checks"]) else "OK")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"check_{stamp}.json") if os.path.isdir(out_dir) else ""
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    log(f"\nResult: {rep['verdict']}" + (f"\nReport (counts only, safe to share): {path}" if path else ""))
    return rep, path
