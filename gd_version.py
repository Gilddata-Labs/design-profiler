"""GildData Design Data Profiler: tool name, version and edition.

The profiling engine underneath is the Folder Profiler (data847/folder-profiler, upstream commit in UPSTREAM_COMMIT). This file names
OUR release; file_profiler.VERSION stays the engine version so profiles remain comparable with upstream ones.

Edition: "internal" (GildData: compile, compare, verify, catalogue, scoring) or "supplier" (what sellers run: check, quick, extract,
cloud, ui). The release builder writes the word into the file EDITION. A checkout of the repository has no EDITION file and is the
supplier edition, so a seller who clones it gets exactly the seller commands; GildData staff set GILDDESIGN_EDITION=internal (or
create a file EDITION containing "internal", which git ignores).
"""
import os

TOOL_NAME = "GildData Design Data Profiler"
TOOL_VERSION = "0.4.0"
HERE = os.path.dirname(os.path.abspath(__file__))

# Key for the opt in design file fingerprints (gd_signals.fingerprint). The same key in every release, so the same file gives the same
# fingerprint at every seller and copies sold twice can be found at GildData. Changing it makes old and new fingerprints incomparable.
FINGERPRINT_KEY = b"gilddata-design-fingerprint-v1"


def edition():
    try:
        with open(os.path.join(HERE, "EDITION"), encoding="utf-8") as f:
            word = f.read().strip().lower()
        if word in ("internal", "supplier"):
            return word
    except OSError:
        pass
    env = os.environ.get("GILDDESIGN_EDITION", "").strip().lower()
    return env if env in ("internal", "supplier") else "supplier"


def upstream_commit():
    try:
        with open(os.path.join(HERE, "UPSTREAM_COMMIT"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""
