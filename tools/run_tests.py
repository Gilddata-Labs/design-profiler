"""Run every test file and print one summary line per file. Exit 1 if any fails.

    python3 tools/run_tests.py            # all 53 test files (a few minutes)
    python3 tools/run_tests.py quick      # only the files whose name contains "quick"

Used by the pre-push hook (.githooks/pre-push), so nothing reaches GitHub without passing. Works the same on Windows,
macOS and Linux. Needs openpyxl (pip install openpyxl) for the compiler and catalogue tests; the profiler itself does not.
"""
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("openpyxl is missing: run  python3 -m pip install openpyxl  and try again.")
        return 1
    pattern = argv[0] if argv else ""
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "tests", "test_*.py")) if pattern in os.path.basename(f))
    if not files:
        print(f"no test file matches '{pattern}'")
        return 1
    env = dict(os.environ, GILDDESIGN_EDITION="internal", PROFILER_NO_REVEAL="1", PROFILER_NO_BROWSER="1", PYTHONDONTWRITEBYTECODE="1")
    failed, t0 = [], time.time()
    for i, f in enumerate(files, 1):
        name = os.path.relpath(f, ROOT)
        start = time.time()
        r = subprocess.run([sys.executable, f], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok = r.returncode == 0
        print(f"[{i:>2}/{len(files)}] {'ok  ' if ok else 'FAIL'} {name}  ({time.time() - start:.0f}s)", flush=True)
        if not ok:
            failed.append(name)
            tail = (r.stdout + r.stderr).strip().splitlines()[-15:]
            print("      " + "\n      ".join(tail))
    took = time.time() - t0
    if failed:
        print(f"\n{len(failed)} of {len(files)} test files FAILED in {took:.0f}s: " + " ".join(failed))
        return 1
    print(f"\nAll {len(files)} test files passed in {took:.0f}s.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
