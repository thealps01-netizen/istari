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



# ══ Sensor/RTSS/ping regressions (audit HW-*) ═════════════════════════════════
import ctypes
import logging
import threading
import time


class _View:
    """A zeroed, addressable byte buffer standing in for a mapped view."""

    def __init__(self, size):
        self.size = size
        self.buf = (ctypes.c_byte * size)()
        self.addr = ctypes.addressof(self.buf)

    def put(self, offset, data: bytes):
        ctypes.memmove(self.addr + offset, data, len(data))


def _mahm_view(names_vals, entry_size=None, claimed_num=None):
    entry_size = entry_size or hw._ENTRY_SIZE
    n = len(names_vals)
    v = _View(hw._HDR_SIZE + n * entry_size)
    hdr = hw._Hdr(sig=hw.MAHM_SIG, ver=0x20000, headerSize=hw._HDR_SIZE,
                  num=claimed_num if claimed_num is not None else n,
                  entrySize=entry_size)
    v.put(0, bytes(hdr))
    for i, (name, val) in enumerate(names_vals):
        e = hw._Entry(srcName=name.encode(), data=val, max_limit=100.0)
        v.put(hw._HDR_SIZE + i * entry_size, bytes(e)[:entry_size])
    return v


# ── HW-1: RTSS prefers the foreground process ────────────────────────────────

def _rtss_view(apps):
    """apps: [(pid, time0, time1, frames)]"""
    v = _View(hw._RTSS_HDR_SIZE + len(apps) * hw._RTSS_APP_SIZE)
    hdr = hw._RtssHdr(dwSignature=hw.RTSS_SIG, dwVersion=0x00020005,
                      dwAppEntrySize=hw._RTSS_APP_SIZE, dwAppArrOffset=hw._RTSS_HDR_SIZE,
                      dwAppArrSize=len(apps))
    v.put(0, bytes(hdr))
    for i, (pid, t0, t1, frames) in enumerate(apps):
        e = hw._RtssAppEntry(dwProcessID=pid, dwTime0=t0, dwTime1=t1, dwFrames=frames)
        v.put(hw._RTSS_HDR_SIZE + i * hw._RTSS_APP_SIZE, bytes(e))
    return v


def test_hw1_rtss_prefers_foreground_process():
    # pid 10 = game (60 fps), pid 20 = browser (more recent, 30 fps)
    v = _rtss_view([(10, 9000, 10000, 60), (20, 9000, 10100, 30)])
    assert hw._parse_rtss(v.addr, v.size, 10200, fg_pid=10) == pytest.approx(60 * 1000 / 1000)
    assert hw._parse_rtss(v.addr, v.size, 10200, fg_pid=20) == pytest.approx(30 * 1000 / 1100)


def test_hw1_rtss_falls_back_to_most_recent_without_foreground_match():
    v = _rtss_view([(10, 9000, 10000, 60), (20, 9000, 10100, 30)])
    assert hw._parse_rtss(v.addr, v.size, 10200, fg_pid=999) == pytest.approx(30 * 1000 / 1100)
    assert hw._parse_rtss(v.addr, v.size, 10200, fg_pid=0) == pytest.approx(30 * 1000 / 1100)


# ── HW-8: tick wraparound ────────────────────────────────────────────────────

def test_hw8_rtss_fps_survives_tick_count_wrap():
    t0, t1 = 0xFFFFFF00, 0x000000F0           # window straddles the 32-bit wrap
    v = _rtss_view([(10, t0, t1, 60)])
    dt = (t1 - t0) & 0xFFFFFFFF               # 496 ms
    assert hw._parse_rtss(v.addr, v.size, 0x100, fg_pid=10) == pytest.approx(60 * 1000 / dt)


# ── HW-2: stop() before run() ────────────────────────────────────────────────

def test_hw2_stop_before_run_is_not_lost(monkeypatch):
    monkeypatch.setattr(hw, "get_data", lambda sensors: ({}, {}, "N/A"))
    w = hw.HardwareWorker([], interval_ms=100)
    w.stop()                                   # arrives before run() begins
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    t.join(1.5)
    alive = t.is_alive()
    w.stop()                                   # release a thread the bug would leave spinning
    t.join(1.0)
    assert not alive


# ── HW-3: reads bounded by the mapped view ───────────────────────────────────

def _record_memmove(monkeypatch, view):
    calls = []
    real = ctypes.memmove

    def spy(dst, src, n):
        if isinstance(src, int):
            calls.append((src - view.addr, n))
        return real(dst, src, n)
    monkeypatch.setattr(hw.ctypes, "memmove", spy)
    return calls


def test_hw3_v1_entries_do_not_read_past_the_view(monkeypatch):
    v = _mahm_view([("gpu1 usage", 11.0), ("cpu usage", 22.0)], entry_size=1312)
    calls = _record_memmove(monkeypatch, v)
    out = hw._parse_mahm(v.addr, v.size)
    assert out["gpu1 usage"][0] == pytest.approx(11.0)
    assert out["cpu usage"][0] == pytest.approx(22.0)
    assert calls and max(off + n for off, n in calls) <= v.size


def test_hw3_entry_count_larger_than_the_view_is_clamped(monkeypatch):
    v = _mahm_view([("gpu1 usage", 11.0), ("cpu usage", 22.0)], claimed_num=50)
    calls = _record_memmove(monkeypatch, v)
    out = hw._parse_mahm(v.addr, v.size)
    assert set(out) == {"gpu1 usage", "cpu usage"}
    assert max(off + n for off, n in calls) <= v.size


def test_hw3_rtss_array_larger_than_the_view_is_clamped(monkeypatch):
    v = _rtss_view([(10, 9000, 10000, 60)])
    hdr = hw._RtssHdr(dwSignature=hw.RTSS_SIG, dwVersion=0x00020005,
                      dwAppEntrySize=hw._RTSS_APP_SIZE, dwAppArrOffset=hw._RTSS_HDR_SIZE,
                      dwAppArrSize=200)
    v.put(0, bytes(hdr))
    calls = _record_memmove(monkeypatch, v)
    assert hw._parse_rtss(v.addr, v.size, 10100, fg_pid=10) == pytest.approx(60.0)
    assert max(off + n for off, n in calls) <= v.size


# ── HW-4: FPS never binds a 1% / 0.1% low sensor ─────────────────────────────

def test_hw4_fps_does_not_bind_one_percent_low():
    names = SENSOR_CATALOG["fps"].mahm_names
    assert hw._pick_sensor({"framerate 1% low": (40.0, None)}, names) == (None, None)
    assert hw._pick_sensor({"framerate 0.1% low": (30.0, None)}, names) == (None, None)
    assert hw._pick_sensor({"framerate avg": (70.0, None)}, names) == (None, None)


def test_hw4_fps_1pct_sensor_still_binds_its_own_low_key():
    names = SENSOR_CATALOG["fps_1pct"].mahm_names
    assert hw._pick_sensor({"framerate 1% low": (40.0, None)}, names)[0] == pytest.approx(40.0)


def test_hw4_fps_falls_through_to_rtss_when_only_low_is_exposed(monkeypatch):
    monkeypatch.setattr(hw, "read_mahm", lambda: {"framerate 1% low": (40.0, None)})
    monkeypatch.setattr(hw, "read_rtss_fps", lambda: 144.0)
    data, _m, _s = hw.get_data([SENSOR_CATALOG["fps"]])
    assert data["fps"] == pytest.approx(144.0)


# ── HW-5: ping failures are logged on state change only; target configurable ─

@pytest.fixture
def ping_state(monkeypatch):
    monkeypatch.setattr(hw, "_ping_target", hw.DEFAULT_PING_TARGET)
    monkeypatch.setattr(hw, "_ping_ok", None)
    monkeypatch.setattr(hw, "_ping_cache", None)
    monkeypatch.setattr(hw, "_ping_thread", None)


def test_hw5_failure_logged_once_then_recovery_logged(ping_state, monkeypatch, caplog):
    def fail(*_a, **_k):
        raise OSError("blocked")
    monkeypatch.setattr(hw.socket, "create_connection", fail)
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(hw._log, "propagate", True)
    for _ in range(3):
        hw._ping_worker("1.1.1.1", 53, 0.1)
    fails = [r for r in caplog.records if r.levelno == logging.WARNING and "Ping probe" in r.getMessage()]
    assert len(fails) == 1 and hw._ping_cache is None

    class _Ok:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(hw.socket, "create_connection", lambda *a, **k: _Ok())
    hw._ping_worker("1.1.1.1", 53, 0.1)
    assert hw._ping_cache is not None
    assert any("recovered" in r.getMessage() for r in caplog.records)


def test_hw5_set_ping_target_is_used_by_the_probe(ping_state, monkeypatch):
    seen = []

    class _Ok:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(hw.socket, "create_connection",
                        lambda addr, timeout=None: seen.append(addr) or _Ok())
    hw.set_ping_target("example.org:443")
    hw.get_ping_ms()
    for _ in range(100):
        if seen:
            break
        time.sleep(0.02)
    assert seen == [("example.org", 443)]


def test_hw5_invalid_ping_target_keeps_default(ping_state):
    hw.set_ping_target("garbage")
    assert hw._ping_target == hw.DEFAULT_PING_TARGET
