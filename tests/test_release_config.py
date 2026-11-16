"""tests/test_release_config.py — the release plumbing that CI and the installer run.

None of this can be executed here (no GitHub runner, no Inno Setup); these tests pin the
properties that are cheap to check as text, so a careless edit cannot quietly undo them.
"""

import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import version_sync


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


WORKFLOW = _read(".github", "workflows", "release.yml")
ISS = _read("istari.iss")


# ── release.yml ───────────────────────────────────────────────────────────────

def test_workflow_is_valid_yaml():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(WORKFLOW)
    assert set(doc["jobs"]) == {"build", "release"}


def test_every_action_is_pinned_to_a_commit_sha_with_the_tag_in_a_comment():
    uses = re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)(.*)$", WORKFLOW, re.M)
    assert uses, "no actions found"
    for ref, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"not pinned to a SHA: {ref}"
        assert re.search(r"#\s*v\d", rest), f"no tag comment on {ref}"


def test_only_the_publish_job_can_write():
    assert re.search(r"^permissions:\s*\{\}\s*$", WORKFLOW, re.M)
    writes = [m.start() for m in re.finditer(r"contents:\s*write", WORKFLOW)]
    assert len(writes) == 1
    assert writes[0] > WORKFLOW.index("\n  release:")
    assert "contents: read" in WORKFLOW[:WORKFLOW.index("\n  release:")]


def test_runner_and_inno_setup_are_pinned():
    assert "windows-latest" not in WORKFLOW
    assert re.search(r"choco install innosetup --version=\d+\.\d+\.\d+", WORKFLOW)


def test_release_is_guarded_by_main_ancestry_and_tag_order():
    assert "git merge-base --is-ancestor" in WORKFLOW and "origin/main" in WORKFLOW
    assert "version_sync.py --check-tag" in WORKFLOW
    assert "fetch-depth: 0" in WORKFLOW
    guard = WORKFLOW.index("--check-tag")
    assert guard < WORKFLOW.index("pip install"), "guard must run before anything is built"


def test_workflow_smoke_checks_the_exe_version_resource_before_publishing():
    assert "VersionInfo" in WORKFLOW and "dist/Istari/Istari.exe" in WORKFLOW
    assert WORKFLOW.index("Smoke-check") < WORKFLOW.index("Upload the release files")


# ── istari.iss ────────────────────────────────────────────────────────────────

def _section(name):
    m = re.search(rf"^\[{name}\]\s*$(.*?)(?=^\[|\Z)", ISS, re.M | re.S)
    assert m, f"[{name}] missing"
    return m.group(1)


def test_every_app_launch_after_install_runs_as_the_original_user():
    launches = [l for l in _section("Run").splitlines()
                if re.match(r'\s*Filename:\s*"\{app\}\\\{#AppExe\}"', l)]
    assert len(launches) == 2
    for line in launches:
        assert "runasoriginaluser" in line, line


def test_uninstaller_removes_the_startup_value():
    entries = [l for l in _section("Registry").splitlines() if l.strip().startswith("Root:")]
    assert any(
        "HKCU" in l and r"CurrentVersion\Run" in l and 'ValueName: "Istari"' in l
        and "uninsdeletevalue" in l and "dontcreatekey" in l
        for l in entries), entries


def test_the_startup_value_name_matches_what_the_app_writes():
    import cfg
    assert cfg._APP_NAME == "Istari" and cfg._STARTUP_KEY.endswith(r"CurrentVersion\Run")


# ── one publisher name ────────────────────────────────────────────────────────

def test_publisher_is_the_same_everywhere():
    p = version_sync.PUBLISHER
    assert re.search(rf"^AppPublisher={re.escape(p)}\s*$", ISS, re.M)
    assert re.search(rf"^VersionInfoCompany={re.escape(p)}\s*$", ISS, re.M)
    assert re.search(rf"'CompanyName',\s*u?'{re.escape(p)}'", _read("file_version_info.txt"))
    assert f'name="{p}.Istari"' in _read("istari.manifest")


# ── build.bat ─────────────────────────────────────────────────────────────────

def test_build_bat_names_the_real_output_and_fails_without_inno_setup():
    bat = _read("build.bat")
    assert "dist\\Istari.exe" not in bat.replace("dist\\Istari\\Istari.exe", "")
    tail = bat[bat.index("if defined ISCC"):]
    assert "exit /b 2" in tail
    assert "pytest" in bat
    assert "WARNING: Icon generation failed" not in bat
