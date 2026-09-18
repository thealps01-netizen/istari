"""tools/version_sync.py — the one writer of Istari's version metadata.

Three files carry the version: `version.py` (the source of truth), the Windows
resource file `file_version_info.txt` and the Inno Setup script `istari.iss`.
The two derived files used to be rewritten by hand-written regexes living in
both `build.bat` and the release workflow, so one of them could silently keep an
old version. This script owns both, and `--check` turns any drift into a failure.

Usage (from the repository root, or with paths given explicitly):

    python tools/version_sync.py --from-tag v1.0.23   # tag   -> version.py
    python tools/version_sync.py --inject             # version.py -> derived files
    python tools/version_sync.py --check              # verify only; exit 1 on drift
"""

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

VERSION_PY   = REPO / "version.py"
VERSION_INFO = REPO / "file_version_info.txt"
ISS          = REPO / "istari.iss"

_SEMVER      = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_RELEASE_VER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version() -> str:
    """Version string from version.py — parsed from the source, never imported."""
    match = re.search(r'^__version__\s*=\s*"([^"]+)"',
                      VERSION_PY.read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit(f"could not find __version__ in {VERSION_PY}")
    value = match.group(1).strip()
    if not _RELEASE_VER.fullmatch(value):
        raise SystemExit(f"__version__ is not MAJOR.MINOR.PATCH: {value!r}")
    return value


def sync_version_py(tag: str) -> bool:
    """Write version.py from a release tag. Returns True when the file changed."""
    match = _SEMVER.match(tag.strip())
    if not match:
        raise SystemExit(f"tag is not vMAJOR.MINOR.PATCH: {tag!r}")
    version = ".".join(match.groups())
    tuple_literal = ", ".join(match.groups())

    src = VERSION_PY.read_text(encoding="utf-8")
    new = re.sub(r'^__version__\s*=\s*"[^"]*"',
                 f'__version__      = "{version}"', src, flags=re.M)
    new = re.sub(r"^__version_tuple__\s*=\s*\([^)]*\)",
                 f"__version_tuple__ = ({tuple_literal})", new, flags=re.M)
    if new == src:
        return False
    VERSION_PY.write_text(new, encoding="utf-8")
    return True


def _expected_version_info(version: str) -> str:
    parts = ", ".join(version.split("."))
    text = VERSION_INFO.read_text(encoding="utf-8")
    text = re.sub(r"filevers=\([^)]*\)", f"filevers=({parts}, 0)", text)
    text = re.sub(r"prodvers=\([^)]*\)", f"prodvers=({parts}, 0)", text)
    # PyInstaller writes the string fields with a `u` prefix (`u'FileVersion'`); an
    # optional prefix in the pattern keeps them in step with filevers/prodvers, where
    # a plain `'FileVersion'` match silently left them at whatever they were.
    text = re.sub(r"(u?'FileVersion',\s*u?)'[^']*'", rf"\g<1>'{version}.0'", text)
    text = re.sub(r"(u?'ProductVersion',\s*u?)'[^']*'",
                  rf"\g<1>'{version}.0'", text)
    return text


def _expected_iss(version: str) -> str:
    """istari.iss with its AppVersion fallback set to `version`.

    The fallback is only used when ISCC is run without /DAppVersion; keeping it
    in step means a manual build does not silently stamp an ancient version.
    """
    text = ISS.read_text(encoding="utf-8")
    return re.sub(r'(#define AppVersion\s+)"[^"]*"', rf'\g<1>"{version}"', text, count=1)


def drift(version: str | None = None) -> list[str]:
    """Files whose committed content does not match version.py."""
    version = version or read_version()
    stale = []
    if VERSION_INFO.read_text(encoding="utf-8") != _expected_version_info(version):
        stale.append(str(VERSION_INFO.relative_to(REPO)))
    if ISS.read_text(encoding="utf-8") != _expected_iss(version):
        stale.append(str(ISS.relative_to(REPO)))
    return stale


def inject() -> list[str]:
    """Rewrite the derived files from version.py. Returns the files written."""
    version = read_version()
    written = []

    expected = _expected_version_info(version)
    current = VERSION_INFO.read_text(encoding="utf-8")
    if expected != current:
        VERSION_INFO.write_text(expected, encoding="utf-8")
        written.append(f"{VERSION_INFO.name} -> {version}")

    expected_iss = _expected_iss(version)
    current_iss = ISS.read_text(encoding="utf-8")
    if expected_iss != current_iss:
        ISS.write_text(expected_iss, encoding="utf-8")
        written.append(f"{ISS.name} AppVersion -> {version}")

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-tag", metavar="TAG",
                       help="write version.py from a release tag (CI)")
    group.add_argument("--inject", action="store_true",
                       help="rewrite the derived files from version.py (build)")
    group.add_argument("--check", action="store_true",
                       help="report drift and exit 1 without writing anything")
    args = parser.parse_args(argv)

    if args.from_tag is not None:
        # Dispatch on `is not None`, never on truthiness: a workflow that fails to
        # expand its tag variable passes an empty string, and treating that as "not
        # requested" let the step report success without writing anything.
        tag = args.from_tag.strip()
        if not tag:
            print("--from-tag needs a tag, got an empty value", file=sys.stderr)
            return 2
        changed = sync_version_py(tag)
        print(f"version.py -> {read_version()}" if changed
              else f"version.py already at {read_version()}")
        for line in inject():
            print(line)
        stale = drift()
        if stale:
            print("version metadata still out of sync after writing: "
                  + ", ".join(stale), file=sys.stderr)
            return 1
        return 0

    if args.inject:
        written = inject()
        for line in written:
            print(line)
        if not written:
            print(f"version metadata already in sync ({read_version()})")
        return 0

    stale = drift()
    if stale:
        print("version metadata out of sync with version.py: " + ", ".join(stale),
              file=sys.stderr)
        return 1
    print(f"version metadata in sync ({read_version()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
