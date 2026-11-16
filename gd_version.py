"""GildData Design Data Profiler: tool name, version and edition.

The profiling engine underneath is the Folder Profiler (data847/folder-profiler, upstream commit in UPSTREAM_COMMIT). This file names
OUR release; file_profiler.VERSION stays the engine version so profiles remain comparable with upstream ones.

Edition: "internal" (GildData: compile, compare, buyer templates, scoring) or "supplier" (what sellers run: check, quick, extract,
cloud, ui). The release builder writes the word into the file EDITION; a checkout with no EDITION file is internal.
"""
import os

TOOL_NAME = "GildData Design Data Profiler"
TOOL_VERSION = "0.2.0"
HERE = os.path.dirname(os.path.abspath(__file__))


def edition():
    try:
        with open(os.path.join(HERE, "EDITION"), encoding="utf-8") as f:
            word = f.read().strip().lower()
        return word if word in ("internal", "supplier") else "internal"
    except OSError:
        return "internal"


def upstream_commit():
    try:
        with open(os.path.join(HERE, "UPSTREAM_COMMIT"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""
