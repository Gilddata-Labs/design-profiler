# Changelog

## Unreleased

- Local testing replaces CI: `tools/run_tests.py` runs the whole suite on any OS, and `.githooks/pre-push` runs it before every push (switch on with `git config core.hooksPath .githooks`). README section "Changing the code".

## 0.4.0

The first release built and tested from GildData's GitHub, ready for sellers.

- Tests pass on Windows, macOS and Linux (Python 3.9 and 3.12), in the sealed Docker image, and the release zips build in CI.
- Windows bundle: `tools/build_release.py --windows` adds the official embeddable Python (pinned by checksum) to the supplier zip, so a seller with no Python installed double clicks `run.bat`. CI builds and runs it on Windows.
- Release signing: a tag `vX.Y.Z` builds all zips, signs them with Sigstore (keyless) and publishes a GitHub release with checksums and signatures (`.github/workflows/release.yml`).
- Seller answers from any intake form: `catalogue --answers-map map.csv` renames the form's headings to the catalogue's field names; an answers file with no usable rows is reported instead of silently flagging every field.
- Every command checks that the output folder can be written and says so plainly instead of a traceback (read only folder, path that is a file).
- The sealed Docker container and the seller launchers mount a memory only `/tmp` for the listing cache (the 0.3.0 launchers failed on a read only container).
- The compiler lives in `profile-compile/`.
- Sellers run from the repository itself: a checkout with no `EDITION` file is the seller edition (check, quick, extract, cloud, ui); GildData switches the internal commands on with `GILDDESIGN_EDITION=internal` or a local `EDITION` file (git ignored). Before, a checkout was the internal edition.
- README written around cloning or downloading the repository, with what to send when something fails; the engine's own documentation moved to `docs/ENGINE.md`.

## 0.3.0

Milestone 2 readers and Milestone 3 catalogue (see `docs/ENGINE.md` and the test report).
