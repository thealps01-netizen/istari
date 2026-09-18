"""tests/test_version_sync.py — the version metadata has exactly one writer.

The build and the release workflow both call tools/version_sync.py; these tests
pin the behaviour that replaced the two hand-written PowerShell rewriters.
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import version_sync

VERSION_PY_SAMPLE = '__version__      = "1.0.22"\n__version_tuple__ = (1, 0, 22)\nAPP_NAME = "Istari"\n'

INFO_SAMPLE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1, 0, 12, 0), prodvers=(1, 0, 12, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('FileVersion', '1.0.12.0'),
      StringStruct('ProductVersion', '1.0.12.0')])])])
"""

ISS_SAMPLE = '#ifndef AppVersion\n  #define AppVersion "1.0.12"\n#endif\n'


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """version_sync pointed at a throwaway copy of the three files."""
    (tmp_path / "version.py").write_text(VERSION_PY_SAMPLE, encoding="utf-8")
    (tmp_path / "file_version_info.txt").write_text(INFO_SAMPLE, encoding="utf-8")
    (tmp_path / "istari.iss").write_text(ISS_SAMPLE, encoding="utf-8")
    monkeypatch.setattr(version_sync, "REPO", tmp_path)
    monkeypatch.setattr(version_sync, "VERSION_PY", tmp_path / "version.py")
    monkeypatch.setattr(version_sync, "VERSION_INFO", tmp_path / "file_version_info.txt")
    monkeypatch.setattr(version_sync, "ISS", tmp_path / "istari.iss")
    return tmp_path


def test_read_version_comes_from_the_file(tree):
    assert version_sync.read_version() == "1.0.22"


def test_inject_writes_both_derived_files(tree):
    written = version_sync.inject()

    assert written == ["file_version_info.txt -> 1.0.22", "istari.iss AppVersion -> 1.0.22"]
    info = (tree / "file_version_info.txt").read_text()
    assert "filevers=(1, 0, 22, 0)" in info
    assert "'FileVersion', '1.0.22.0'" in info
    assert "'ProductVersion', '1.0.22.0'" in info
    assert '#define AppVersion "1.0.22"' in (tree / "istari.iss").read_text()
    assert version_sync.drift() == []


def test_inject_is_idempotent(tree):
    version_sync.inject()

    assert version_sync.inject() == []


def test_from_tag_writes_version_py_and_is_idempotent(tree):
    assert version_sync.sync_version_py("v1.0.23") is True

    text = (tree / "version.py").read_text()
    assert '__version__      = "1.0.23"' in text
    assert "__version_tuple__ = (1, 0, 23)" in text
    assert version_sync.sync_version_py("v1.0.23") is False


def test_from_tag_rejects_a_non_semver_tag(tree):
    """The tag reaches this function unvalidated (CI passes the ref), so garbage
    must be rejected before anything is written."""
    with pytest.raises(SystemExit):
        version_sync.sync_version_py("v1.0.23; rm -rf /")

    assert (tree / "version.py").read_text() == VERSION_PY_SAMPLE


def test_drift_lists_stale_files(tree):
    assert version_sync.drift() == ["file_version_info.txt", "istari.iss"]
