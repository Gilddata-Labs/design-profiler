"""Helpers shared by the test files. Windows refuses to delete a file that is still open, so the
tests read result zips and workbooks into memory instead of keeping a handle on the file."""
import io
import zipfile


def zopen(path):
    """zipfile.ZipFile over an in memory copy of the file; the file itself is closed at once."""
    with open(path, "rb") as fh:
        return zipfile.ZipFile(io.BytesIO(fh.read()))


def wopen(path, **kw):
    """openpyxl workbook from an in memory copy (read_only workbooks otherwise keep the file open)."""
    import openpyxl
    with open(path, "rb") as fh:
        return openpyxl.load_workbook(io.BytesIO(fh.read()), **kw)


def plain(path):
    """A path as the test wrote it: without the Windows \\\\?\\ (long path) prefix the profiler adds."""
    if isinstance(path, bytes):
        path = path.decode("utf-8", "replace")
    path = str(path)
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return path


def under(path, root):
    """True when `path` (as passed to open or scandir) lies inside `root`, on any OS."""
    import os
    return os.path.normcase(plain(path)).startswith(os.path.normcase(plain(root)))
