"""tests/test_cfg.py — Unit tests for cfg.py (settings load/save/recovery)."""

import json
import os
import sys
import tempfile
import pytest

# Make parent directory importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import cfg


# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """Redirect SETTINGS_FILE to a temporary path for each test.

    The pre-rename legacy path is redirected as well: otherwise a real
    %LOCALAPPDATA%\\Palantir\\settings.json on the machine leaks into the test
    result through the one-off migration.
    """
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(cfg, "SETTINGS_FILE", str(settings))
    monkeypatch.setattr(cfg, "LEGACY_SETTINGS_FILE",
                        str(tmp_path / "Palantir" / "settings.json"))
    return settings


# ── load_cfg ──────────────────────────────────────────────────────────────────

def test_load_cfg_defaults_when_no_file(tmp_settings):
    result = cfg.load_cfg()
    assert result["opacity"]       == cfg.DEFAULT_CFG["opacity"]
    assert result["update_ms"]     == cfg.DEFAULT_CFG["update_ms"]
    assert result["active_sensors"] == cfg.DEFAULT_CFG["active_sensors"]


def test_load_cfg_reads_saved_values(tmp_settings):
    data = dict(cfg.DEFAULT_CFG)
    data["opacity"] = 55
    data["update_ms"] = 2000
    tmp_settings.write_text(json.dumps(data))

    result = cfg.load_cfg()
    assert result["opacity"]   == 55
    assert result["update_ms"] == 2000


def test_load_cfg_unknown_sensors_filtered(tmp_settings):
    data = dict(cfg.DEFAULT_CFG)
    data["active_sensors"] = ["fps", "nonexistent_sensor"]
    tmp_settings.write_text(json.dumps(data))

    result = cfg.load_cfg()
    assert "nonexistent_sensor" not in result["active_sensors"]
    assert "fps" in result["active_sensors"]


def test_load_cfg_corrupt_json_falls_back_to_defaults(tmp_settings):
    tmp_settings.write_text("{ this is not valid json !!!")

    result = cfg.load_cfg()
    assert result["opacity"] == cfg.DEFAULT_CFG["opacity"]


def test_load_cfg_corrupt_json_creates_backup(tmp_settings):
    tmp_settings.write_text("{ bad json")

    cfg.load_cfg()

    # Original file should be gone; a .corrupt_ backup should exist
    assert not tmp_settings.exists()
    backups = list(tmp_settings.parent.glob("settings.json.corrupt_*"))
    assert len(backups) == 1


# ── save_cfg ──────────────────────────────────────────────────────────────────

def test_save_cfg_writes_file(tmp_settings):
    data = dict(cfg.DEFAULT_CFG)
    data["opacity"] = 77
    cfg.save_cfg(data)

    assert tmp_settings.exists()
    saved = json.loads(tmp_settings.read_text())
    assert saved["opacity"] == 77


def test_save_cfg_no_tmp_leftover(tmp_settings):
    cfg.save_cfg(dict(cfg.DEFAULT_CFG))

    leftover = str(tmp_settings) + ".tmp"
    assert not os.path.exists(leftover)


def test_save_and_reload_roundtrip(tmp_settings):
    original = dict(cfg.DEFAULT_CFG)
    original["opacity"]        = 42
    original["theme"]          = "light"
    original["active_sensors"] = ["fps", "cpu_usage"]
    original["visible"]        = {"fps": True, "cpu_usage": False}

    cfg.save_cfg(original)
    loaded = cfg.load_cfg()

    assert loaded["opacity"]   == 42
    assert loaded["theme"]     == "light"
    assert loaded["active_sensors"] == ["fps", "cpu_usage"]
    assert loaded["visible"]["cpu_usage"] is False


# ── Anchor presets ────────────────────────────────────────────────────────────

def test_load_cfg_valid_anchor_kept(tmp_settings):
    data = dict(cfg.DEFAULT_CFG)
    data["anchor"] = "tr"
    tmp_settings.write_text(json.dumps(data))

    result = cfg.load_cfg()
    assert result["anchor"] == "tr"


def test_load_cfg_invalid_anchor_reset(tmp_settings):
    data = dict(cfg.DEFAULT_CFG)
    data["anchor"] = "bogus"
    tmp_settings.write_text(json.dumps(data))

    result = cfg.load_cfg()
    assert result["anchor"] == ""


def test_load_cfg_missing_anchor_defaults_empty(tmp_settings):
    data = dict(cfg.DEFAULT_CFG)
    del data["anchor"]
    tmp_settings.write_text(json.dumps(data))

    result = cfg.load_cfg()
    assert result["anchor"] == ""


# ── Color helpers ─────────────────────────────────────────────────────────────

def test_default_color_known_sensor():
    color = cfg.default_color("fps")
    assert color.startswith("#")
    assert len(color) == 7


def test_default_color_unknown_sensor():
    color = cfg.default_color("does_not_exist")
    assert color == "#e8e8e8"


def test_eff_color_uses_custom_if_set():
    c = dict(cfg.DEFAULT_CFG)
    c["colors"] = {"fps": "#abcdef"}
    assert cfg.eff_color(c, "fps") == "#abcdef"


def test_eff_color_falls_back_to_default():
    c = dict(cfg.DEFAULT_CFG)
    c["colors"] = {}
    assert cfg.eff_color(c, "fps") == cfg.default_color("fps")


# ── Defaults must not be shared, and a bad field must not wipe the rest ───────

def test_load_cfg_defaults_are_not_shared_with_default_cfg(tmp_settings):
    """First run (no settings file): the returned containers must be copies.

    The settings dialog mutates cfg["colors"] / ["visible"] / ["active_sensors"]
    in place, so sharing them with DEFAULT_CFG would let one session's edits
    become the new "factory defaults".
    """
    result = cfg.load_cfg()
    result["colors"]["fps"] = "#ff0000"
    result["visible"]["fps"] = False
    result["active_sensors"].append("net_latency")

    assert cfg.DEFAULT_CFG["colors"] == {}
    assert cfg.DEFAULT_CFG["visible"]["fps"] is True
    assert "net_latency" not in cfg.DEFAULT_CFG["active_sensors"]


def test_load_cfg_wrong_type_field_keeps_other_settings(tmp_settings):
    """A wrong-typed container field must cost only that field, not everything.

    Before, 'colors' as a list raised inside _sanitize_cfg, the whole load fell
    back to defaults and the user's opacity/theme were silently discarded — and
    the next save_cfg then overwrote them on disk.
    """
    tmp_settings.write_text(json.dumps(
        {"opacity": 77, "theme": "light", "colors": ["#ff0000"]}
    ))

    result = cfg.load_cfg()

    assert result["opacity"] == 77
    assert result["theme"] == "light"
    assert result["colors"] == {}


def test_load_cfg_wrong_type_active_sensors_falls_back_to_defaults(tmp_settings):
    tmp_settings.write_text(json.dumps(
        {"opacity": 60, "active_sensors": "fps", "visible": ["fps"]}
    ))

    result = cfg.load_cfg()

    assert result["opacity"] == 60
    assert result["active_sensors"] == list(cfg.DEFAULT_CFG["active_sensors"])


def test_load_cfg_non_object_root_backs_up_the_file(tmp_settings):
    """Valid JSON that is not an object: defaults + the file kept as a backup,
    not left in place to be overwritten with defaults by the next save."""
    tmp_settings.write_text("[1, 2, 3]")

    result = cfg.load_cfg()

    assert result["opacity"] == cfg.DEFAULT_CFG["opacity"]
    assert not tmp_settings.exists()
    assert len(list(tmp_settings.parent.glob("settings.json.corrupt_*"))) == 1


# ── Pre-rename (Palantir) leftovers ───────────────────────────────────────────

def test_load_cfg_adopts_pre_rename_settings(tmp_settings, tmp_path, monkeypatch):
    """Settings saved under the old name must be adopted, not silently ignored.

    Without this the app read its new path, found nothing and came up with
    defaults — the user's layout/anchor/opacity looked lost.
    """
    legacy = tmp_path / "Palantir" / "settings.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"opacity": 95, "layout": "bar", "anchor": "tc"}))
    monkeypatch.setattr(cfg, "LEGACY_SETTINGS_FILE", str(legacy))

    result = cfg.load_cfg()

    assert result["opacity"] == 95
    assert result["layout"]  == "bar"
    assert result["anchor"]  == "tc"
    assert tmp_settings.exists()      # adopted at the new path
    assert legacy.exists()            # the migration never moves the original


def test_load_cfg_keeps_its_own_settings_over_legacy(tmp_settings, tmp_path, monkeypatch):
    legacy = tmp_path / "Palantir" / "settings.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"opacity": 40}))
    monkeypatch.setattr(cfg, "LEGACY_SETTINGS_FILE", str(legacy))
    tmp_settings.write_text(json.dumps({"opacity": 80}))

    result = cfg.load_cfg()

    assert result["opacity"] == 80


def test_load_cfg_without_legacy_settings_writes_nothing(tmp_settings, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "LEGACY_SETTINGS_FILE", str(tmp_path / "nope" / "settings.json"))

    result = cfg.load_cfg()

    assert result["opacity"] == cfg.DEFAULT_CFG["opacity"]
    assert not tmp_settings.exists()


def test_purge_dead_legacy_startup_removes_entry_with_missing_target(tmp_path, monkeypatch):
    """The old autostart value pointed at a path the rename deleted."""
    deleted = []
    monkeypatch.setattr(cfg, "_query_startup_value",
                        lambda name: f'"{tmp_path / "gone" / "Palantir.exe"}"')
    monkeypatch.setattr(cfg, "_delete_startup_value", deleted.append)

    assert cfg.purge_dead_legacy_startup() is True
    assert deleted == [cfg._LEGACY_APP_NAME]


def test_purge_dead_legacy_startup_keeps_entry_with_live_target(tmp_path, monkeypatch):
    """An old install that is still on disk keeps its autostart entry."""
    exe = tmp_path / "Palantir.exe"
    exe.write_text("stub")
    deleted = []
    monkeypatch.setattr(cfg, "_query_startup_value", lambda name: f'"{exe}"')
    monkeypatch.setattr(cfg, "_delete_startup_value", deleted.append)

    assert cfg.purge_dead_legacy_startup() is False
    assert deleted == []


def test_purge_dead_legacy_startup_without_entry(monkeypatch):
    monkeypatch.setattr(cfg, "_query_startup_value", lambda name: None)

    assert cfg.purge_dead_legacy_startup() is False


# ── "Launch at Windows startup" must not lie about a failed registry write ────

class _FakeKey:
    pass


def test_set_startup_reports_false_when_the_key_cannot_be_opened(monkeypatch):
    def deny(*_a, **_k):
        raise PermissionError("access denied")

    monkeypatch.setattr(cfg.winreg, "OpenKey", deny)

    assert cfg.set_startup(True) is False


def test_set_startup_reports_true_only_after_reading_it_back(monkeypatch):
    written = []
    monkeypatch.setattr(cfg.winreg, "OpenKey", lambda *a, **k: _FakeKey())
    monkeypatch.setattr(cfg.winreg, "SetValueEx",
                        lambda key, name, reserved, kind, value: written.append((name, value)))
    monkeypatch.setattr(cfg.winreg, "CloseKey", lambda key: None)
    monkeypatch.setattr(cfg, "_query_startup_value", lambda name: '"C:\\x\\Istari.exe"')

    assert cfg.set_startup(True) is True
    assert written and written[0][0] == "Istari"


def test_set_startup_reports_false_when_the_write_did_not_land(monkeypatch):
    """The write raised nothing but the value is not there afterwards."""
    monkeypatch.setattr(cfg.winreg, "OpenKey", lambda *a, **k: _FakeKey())
    monkeypatch.setattr(cfg.winreg, "SetValueEx", lambda *a: None)
    monkeypatch.setattr(cfg.winreg, "CloseKey", lambda key: None)
    monkeypatch.setattr(cfg, "_query_startup_value", lambda name: None)

    assert cfg.set_startup(True) is False


def test_set_startup_reports_true_when_removal_succeeded(monkeypatch):
    monkeypatch.setattr(cfg.winreg, "OpenKey", lambda *a, **k: _FakeKey())
    monkeypatch.setattr(cfg.winreg, "DeleteValue", lambda key, name: None)
    monkeypatch.setattr(cfg.winreg, "CloseKey", lambda key: None)
    monkeypatch.setattr(cfg, "_query_startup_value", lambda name: None)

    assert cfg.set_startup(False) is True
