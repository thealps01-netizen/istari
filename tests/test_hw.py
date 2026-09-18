"""tests/test_hw.py — Unit tests for hw.py (sensor picking, fallback logic)."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import hw
from cfg import SENSOR_CATALOG, active_sensor_defs, DEFAULT_CFG

# read_mahm() now returns {name: (val, max_val)} tuples
_RAW_ONE   = {"gpu1 usage": (78.5, 90.0), "cpu usage": (42.0, 55.0)}
_RAW_TEMP  = {"gpu1 temperature value": (65.0, 80.0)}
_RAW_MULTI = {"gpu1 usage": (90.0, 95.0), "gpu usage": (85.0, 88.0)}
_RAW_FPS   = {"framerate": (120.0, 144.0)}
_RAW_OTHER = {"some_other_sensor": (1.0, 1.0)}


# ── _pick_sensor ──────────────────────────────────────────────────────────────

def test_pick_sensor_exact_match():
    val, mx = hw._pick_sensor(_RAW_ONE, ("gpu1 usage",))
    assert val == pytest.approx(78.5)
    assert mx  == pytest.approx(90.0)


def test_pick_sensor_substring_match():
    val, mx = hw._pick_sensor(_RAW_TEMP, ("gpu1 temperature",))
    assert val == pytest.approx(65.0)
    assert mx  == pytest.approx(80.0)


def test_pick_sensor_first_candidate_wins():
    val, mx = hw._pick_sensor(_RAW_MULTI, ("gpu1 usage", "gpu usage"))
    assert val == pytest.approx(90.0)
    assert mx  == pytest.approx(95.0)


def test_pick_sensor_returns_none_when_no_match():
    val, mx = hw._pick_sensor(_RAW_OTHER, ("framerate",))
    assert val is None
    assert mx  is None


def test_pick_sensor_empty_raw():
    val, mx = hw._pick_sensor({}, ("framerate",))
    assert val is None
    assert mx  is None


def test_pick_sensor_exact_match_beats_substring():
    """'framerate' must pick the exact 'framerate' entry, not 'framerate 1% low'
    — even when the 1%-low entry comes first in the dict."""
    raw = {
        "framerate 1% low": (48.0, 60.0),
        "framerate":        (120.0, 144.0),
    }
    val, mx = hw._pick_sensor(raw, ("framerate", "frame rate"))
    assert val == pytest.approx(120.0)
    assert mx  == pytest.approx(144.0)


# ── get_data fallback for Windows-API sensors ─────────────────────────────────

def test_get_data_ram_fallback(monkeypatch):
    """RAM sensor should use Windows API fallback even when MAHM is empty."""

    monkeypatch.setattr(hw, "read_mahm", lambda: {})

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["ram_usage"]
    cfg["visible"]        = {"ram_usage": True}
    sensors = active_sensor_defs(cfg)

    data, maxes, src = hw.get_data(sensors)

    assert "ram_usage" in data
    assert data["ram_usage"] is not None
    assert 0 <= data["ram_usage"] <= 100
    assert maxes["ram_usage"] == SENSOR_CATALOG["ram_usage"].bar_max
    assert src == "N/A"


def test_get_data_mahm_sensor_missing_returns_none(monkeypatch):
    """When MAHM is running but doesn't have a sensor, return None."""

    monkeypatch.setattr(hw, "read_mahm", lambda: _RAW_OTHER)
    monkeypatch.setattr(hw, "read_rtss_fps", lambda: None)

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["fps"]
    cfg["visible"]        = {"fps": True}
    sensors = active_sensor_defs(cfg)

    data, maxes, src = hw.get_data(sensors)

    assert data["fps"] is None
    assert maxes["fps"] is None
    assert src == "MSI Afterburner"


def test_get_data_source_label_when_mahm_unavailable(monkeypatch):
    monkeypatch.setattr(hw, "read_mahm", lambda: {})
    monkeypatch.setattr(hw, "read_rtss_fps", lambda: None)

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["fps"]
    cfg["visible"]        = {"fps": True}
    sensors = active_sensor_defs(cfg)

    _, _mx, src = hw.get_data(sensors)
    assert src == "N/A"


# ── RTSS direct-read FPS fallback ─────────────────────────────────────────────

def test_get_data_fps_falls_back_to_rtss(monkeypatch):
    """MAHM has no framerate entry → FPS comes from RTSS shared memory."""
    monkeypatch.setattr(hw, "read_mahm", lambda: _RAW_OTHER)
    monkeypatch.setattr(hw, "read_rtss_fps", lambda: 237.4)

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["fps"]
    cfg["visible"]        = {"fps": True}
    sensors = active_sensor_defs(cfg)

    data, _mx, src = hw.get_data(sensors)
    assert data["fps"] == pytest.approx(237.4)
    assert src == "MSI Afterburner"   # MAHM still connected for other sensors


def test_get_data_fps_rtss_only_source_label(monkeypatch):
    """MAHM completely absent but RTSS hooked → src label is 'RTSS'."""
    monkeypatch.setattr(hw, "read_mahm", lambda: {})
    monkeypatch.setattr(hw, "read_rtss_fps", lambda: 144.0)

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["fps"]
    cfg["visible"]        = {"fps": True}
    sensors = active_sensor_defs(cfg)

    data, _mx, src = hw.get_data(sensors)
    assert data["fps"] == pytest.approx(144.0)
    assert src == "RTSS"


def test_get_data_fps_zero_mahm_uses_rtss(monkeypatch):
    """MAHM reports framerate 0 (not hooked) → RTSS value wins."""
    monkeypatch.setattr(hw, "read_mahm", lambda: {"framerate": (0.0, 0.0)})
    monkeypatch.setattr(hw, "read_rtss_fps", lambda: 99.0)

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["fps"]
    cfg["visible"]        = {"fps": True}
    sensors = active_sensor_defs(cfg)

    data, _mx, _src = hw.get_data(sensors)
    assert data["fps"] == pytest.approx(99.0)


def test_read_rtss_fps_is_none_or_a_plausible_framerate():
    """read_rtss_fps must never raise, and any value it returns has to be a
    framerate RTSS could actually report (the old assertion accepted anything:
    `is None or isinstance(x, float)` is always true)."""
    fps = hw.read_rtss_fps()

    assert fps is None or (isinstance(fps, float) and 1.0 < fps < 2000.0), \
        f"read_rtss_fps() returned an implausible value: {fps!r}"


def test_get_data_source_label_when_mahm_available(monkeypatch):
    monkeypatch.setattr(hw, "read_mahm", lambda: _RAW_FPS)

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["fps"]
    cfg["visible"]        = {"fps": True}
    sensors = active_sensor_defs(cfg)

    data, maxes, src = hw.get_data(sensors)
    assert src == "MSI Afterburner"
    assert data["fps"]  == pytest.approx(120.0)
    assert maxes["fps"] == pytest.approx(144.0)


# ── Candidate lists must not bind another component's sensor ──────────────────

def test_gpu_power_does_not_bind_cpu_power():
    """The old bare 'power' candidate matched whichever MAHM entry came first:
    a machine exposing only 'cpu power' reported CPU package power as GPU PWR
    (live on this project's dev machine, 'gpu power' does not exist — only
    'gpu1 power' and 'cpu power')."""
    raw = {"cpu power": (65.0, 200.0), "cpu usage": (40.0, 100.0)}

    assert hw._pick_sensor(raw, SENSOR_CATALOG["gpu_power"].mahm_names) == (None, None)


def test_gpu_power_binds_indexed_source():
    raw = {"gpu1 power": (53.0, 300.0), "gpu2 power": (135.0, 300.0), "cpu power": (65.0, 200.0)}

    val, mx = hw._pick_sensor(raw, SENSOR_CATALOG["gpu_power"].mahm_names)

    assert val == pytest.approx(53.0)
    assert mx  == pytest.approx(300.0)


def test_gpu_hotspot_does_not_bind_vram_temperature():
    """'temperature 2' is the VRAM/memory sensor on cards that expose it, so
    GPU HOT reported the memory temperature under a hotspot label."""
    raw = {"gpu1 temperature 2": (52.0, 100.0), "gpu1 memory temperature": (52.0, 100.0)}

    assert hw._pick_sensor(raw, SENSOR_CATALOG["gpu_hotspot"].mahm_names) == (None, None)


def test_gpu_hotspot_binds_real_hotspot_when_present():
    raw = {"gpu1 hot spot": (78.0, 110.0), "gpu1 temperature": (60.0, 100.0)}

    val, mx = hw._pick_sensor(raw, SENSOR_CATALOG["gpu_hotspot"].mahm_names)

    assert val == pytest.approx(78.0)
    assert mx  == pytest.approx(110.0)


def test_gpu_clock_prefers_gpu_specific_source():
    """'core clock' alone also matches 'cpu core clock'."""
    raw = {"cpu core clock": (5455.0, 5000.0), "gpu1 core clock": (228.0, 2500.0)}

    val, _mx = hw._pick_sensor(raw, SENSOR_CATALOG["gpu_clock"].mahm_names)

    assert val == pytest.approx(228.0)


# ── Bar scale from MAHM's graph limits ────────────────────────────────────────

def test_usable_max_returns_limit():
    assert hw._usable_max(53.0, 300.0) == pytest.approx(300.0)


def test_usable_max_is_none_when_limit_missing():
    """Older layouts report 0; substituting the live value pinned the bar full."""
    assert hw._usable_max(53.0, 0.0) is None
    assert hw._usable_max(53.0, float("nan")) is None


def test_usable_max_is_none_when_value_outgrew_the_scale():
    """cpu clock reads 5455 MHz against a 5000 MHz graph scale."""
    assert hw._usable_max(5455.0, 5000.0) is None


def test_usable_max_accepts_value_at_the_limit():
    assert hw._usable_max(5000.0, 5000.0) == pytest.approx(5000.0)


def test_get_data_reports_none_scale_so_ui_can_fall_back(monkeypatch):
    """With maxes[key] = None, _on_data uses maxes.get(key) or bar_max."""
    monkeypatch.setattr(hw, "read_mahm", lambda: {"gpu1 usage": (13.0, None)})

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["gpu_usage"]
    cfg["visible"]        = {"gpu_usage": True}

    data, maxes, _src = hw.get_data(active_sensor_defs(cfg))

    assert data["gpu_usage"] == pytest.approx(13.0)
    assert maxes["gpu_usage"] is None
    assert SENSOR_CATALOG["gpu_usage"].bar_max == 100


# ── A failing sensor must be visible, not silently blank ─────────────────────

class _RecordingLog:
    """Stand-in for the module logger, so a test can see what was reported."""

    def __init__(self):
        self.warnings = []

    def warning(self, *args):
        self.warnings.append(args)

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_sensor_read_failure_is_logged_and_poll_continues(monkeypatch):
    """An exception from a Windows-API sensor used to leave the row silently
    blank; it is now logged and the rest of the poll still runs."""
    def boom():
        raise OSError("GlobalMemoryStatusEx unavailable")

    rec = _RecordingLog()
    monkeypatch.setattr(hw, "_log", rec)
    monkeypatch.setitem(hw._WIN_FALLBACKS, "ram_usage", boom)
    monkeypatch.setattr(hw, "read_mahm", lambda: {})

    cfg = dict(DEFAULT_CFG)
    cfg["active_sensors"] = ["ram_usage", "net_latency"]
    cfg["visible"]        = {k: True for k in cfg["active_sensors"]}

    data, _maxes, _src = hw.get_data(active_sensor_defs(cfg))

    assert data["ram_usage"] is None
    assert "net_latency" in data            # the poll survived the failure
    assert any("ram_usage" in str(w) for w in rec.warnings)
