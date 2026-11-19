# Changelog

## 0.4.0

The first release built and tested from GildData's GitHub, ready for sellers.

- Tests pass on Windows, macOS and Linux (Python 3.9 and 3.12), in the sealed Docker image, and the release zips build in CI.
- Windows bundle: `tools/build_release.py --windows` adds the official embeddable Python (pinned by checksum) to the supplier zip, so a seller with no Python installed double clicks `run.bat`. CI builds and runs it on Windows.
- Release signing: a tag `vX.Y.Z` builds all zips, signs them with Sigstore (keyless) and publishes a GitHub release with checksums and signatures (`.github/workflows/release.yml`).
- Seller answers from any intake form: `catalogue --answers-map map.csv` renames the form's headings to the catalogue's field names; an answers file with no usable rows is reported instead of silently flagging every field.
- Every command checks that the output folder can be written and says so plainly instead of a traceback (read only folder, path that is a file).
- The sealed Docker container and the seller launchers mount a memory only `/tmp` for the listing cache (the 0.3.0 launchers failed on a read only container).
- The compiler lives in `profile-compile/`.
- Customer README; the engine's own documentation moved to `docs/ENGINE.md`.

## 0.3.0

Milestone 2 readers and Milestone 3 catalogue (see `docs/ENGINE.md` and the test report).
