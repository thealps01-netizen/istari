"""cfg.py — App configuration: constants, settings persistence, Windows startup."""

import sys, os, json, winreg, re, copy
from typing import NamedTuple

from logger import get_logger

_log = get_logger("cfg")

# ── Windows startup registry ──────────────────────────────────────────────────
_STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME    = "Istari"
# Name this app registered its autostart under before the Palantir → Istari
# rename. Nothing removes that value any more, so it is cleaned up by
# purge_dead_legacy_startup() when its target no longer exists.
_LEGACY_APP_NAME = "Palantir"


def _startup_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return f'"{pythonw}" "{os.path.abspath(sys.argv[0])}"'


def _query_startup_value(name):
    """Raw autostart command registered under `name`, or None.

    None also covers "the value is not set", which is the normal off state;
    a key that cannot be read at all is logged, because silently reporting
    "off" would hide a permissions problem.
    """
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY)
    except OSError as e:
        _log.warning("Could not open the startup registry key (%s: %s)", type(e).__name__, e)
        return None
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)


def _delete_startup_value(name):
    """Remove the autostart value `name`, tolerating a missing value/key."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_SET_VALUE
        )
    except OSError:
        return
    try:
        winreg.DeleteValue(key, name)
    except OSError:
        pass
    finally:
        winreg.CloseKey(key)


def is_startup_enabled():
    return _query_startup_value(_APP_NAME) is not None


def set_startup(enabled) -> bool:
    """Add or remove the Istari autostart entry.

    Returns True only when the registry state afterwards matches `enabled`:
    a failed write used to look exactly like a successful one, so the checkbox
    could claim "Launch at Windows startup" with nothing registered.
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_SET_VALUE
        )
    except OSError as e:
        _log.warning("Could not open the startup registry key (%s: %s)", type(e).__name__, e)
        return False
    try:
        if enabled:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _startup_cmd())
        else:
            try:
                winreg.DeleteValue(key, _APP_NAME)
            except OSError:
                pass   # already absent
    except OSError as e:
        _log.warning("Could not %s the startup entry (%s: %s)",
                     "write" if enabled else "remove", type(e).__name__, e)
        return False
    finally:
        winreg.CloseKey(key)
    return is_startup_enabled() if enabled else not is_startup_enabled()


def purge_dead_legacy_startup() -> bool:
    """Remove the pre-rename "Palantir" autostart value when its target is gone.

    After the rename that value pointed at C:\\Program Files\\Palantir\\Palantir.exe
    and nothing ever touched it again, so Windows kept trying to start a path
    that no longer exists. Only removed when the target file is missing — an old
    install still on disk keeps its entry. Returns True when it was removed.
    """
    cmd = _query_startup_value(_LEGACY_APP_NAME)
    if not cmd:
        return False
    target = cmd.strip()
    if target.startswith('"'):
        target = target[1:].split('"', 1)[0]
    if os.path.exists(target):
        _log.info("Legacy '%s' startup entry kept — target still exists (%s)",
                  _LEGACY_APP_NAME, target)
        return False
    _delete_startup_value(_LEGACY_APP_NAME)
    _log.info("Removed stale '%s' startup entry (%s)", _LEGACY_APP_NAME, cmd)
    return True


# ── Settings file path ────────────────────────────────────────────────────────
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
_DIR = os.path.join(_LOCALAPPDATA, "Istari")
# Directory the pre-rename build wrote to; only its settings.json is adopted
# (logs and install files stay where they are).
_LEGACY_DIR = os.path.join(_LOCALAPPDATA, "Palantir")
os.makedirs(_DIR, exist_ok=True)

SETTINGS_FILE        = os.path.join(_DIR, "settings.json")
LEGACY_SETTINGS_FILE = os.path.join(_LEGACY_DIR, "settings.json")


# ── Sensor definitions ────────────────────────────────────────────────────────
class SensorDef(NamedTuple):
    key:        str
    label:      str
    unit:       str
    color:      str
    bar_max:    float
    mahm_names: tuple   # MAHM source-name substrings; empty = Windows API fallback

SENSOR_CATALOG: dict[str, "SensorDef"] = {s.key: s for s in [
    # ── Core sensors (default set) ─────────────────────────────────────────────
    SensorDef("fps",        "FPS",      "",    "#e8e8f8", 360,  ("framerate", "frame rate")),
    SensorDef("fps_1pct",   "FPS 1%",   "",    "#b8c0e8", 360,  ("1% low framerate", "1% low fps", "1% low", "fps 1% low", "framerate 1% low", "frame rate 1%")),
    SensorDef("gpu_usage",  "GPU USE",  "%",   "#6474f0", 100,  ("gpu1 usage",       "gpu usage")),
    SensorDef("gpu_temp",   "GPU TEMP", "°",   "#ef5350", 110,  ("gpu1 temperature", "gpu temperature")),
    SensorDef("gpu_hotspot","GPU HOT",  "°",   "#ff1744", 115,  ("hot spot", "junction temperature", "gpu hot spot", "hotspot", "junction temp", "gpu1 hot spot")),
    SensorDef("gpu_power",  "GPU PWR",  "W",   "#ff7043", 400,  ("gpu power", "gpu1 power")),
    SensorDef("gpu_clock",  "GPU CLK",  "MHz", "#b07cf5", 3000, ("gpu1 core clock", "gpu core clock", "core clock", "gpu clock")),
    SensorDef("gpu_fan",    "GPU FAN",  "%",   "#78909c", 100,  ("fan speed", "fan tachometer")),
    SensorDef("vram_usage", "VRAM USE", "%",   "#4f8ef7", 100,  ("fb usage", "vram usage")),
    SensorDef("gpu2_usage", "GPU2 USE", "%",   "#7986cb", 100,  ("gpu2 usage",)),
    SensorDef("cpu_usage",  "CPU USE",  "%",   "#66bb6a", 100,  ("cpu usage", "cpu total")),
    SensorDef("cpu_temp",   "CPU TEMP", "°",   "#ffa726", 110,  ("cpu temperature",)),
    SensorDef("cpu_power",  "CPU PWR",  "W",   "#ffe57f", 350,  ("cpu power", "package power", "cpu package power", "cpu pkg power", "processor power")),
    SensorDef("cpu_clock",  "CPU CLK",  "MHz", "#c8e6c9", 7000, ("cpu clock", "cpu core clock", "core #1 clock", "cpu frequency")),
    SensorDef("ram_usage",    "RAM USE",  "%",  "#9b59f5", 100,  ()),  # Windows API
    SensorDef("net_latency",  "PING",     "ms", "#26c6da", 200,  ()),  # Windows API
]}

_DEFAULT_ACTIVE = ["fps", "gpu_usage", "gpu_temp", "cpu_usage", "cpu_temp", "ram_usage"]

# Screen anchor presets: "" = free (drag), others snap to screen edges
ANCHOR_PRESETS = ("", "tl", "tc", "tr", "bl", "bc", "br")

DEFAULT_CFG = {
    "opacity":         90,
    "hover_opacity":   20,
    "update_ms":       1000,
    "locked":          False,
    "always_on_top":   True,
    "pos_x":           -1,
    "pos_y":           -1,
    "anchor":          "",
    "theme":           "dark",
    "scale":           100,
    "layout":          "card",
    "active_sensors":  list(_DEFAULT_ACTIVE),
    "visible":         {k: True for k in _DEFAULT_ACTIVE},
    "colors":          {},
    "skipped_version": "",
}


# ── Settings validation ───────────────────────────────────────────────────────
_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _sanitize_cfg(cfg: dict) -> dict:
    """Clamp/coerce every scalar field so bad values in settings.json can't crash the app."""
    def clamp_int(v, lo, hi, default):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, v))

    def valid_color(v, default):
        return v if isinstance(v, str) and _HEX_RE.match(v) else default

    def snap_ms(v):
        opts = [500, 1000, 2000, 5000]
        try:
            v = int(v)
        except (TypeError, ValueError):
            return DEFAULT_CFG["update_ms"]
        return min(opts, key=lambda x: abs(x - v))

    def get(key):
        """Field value, falling back to its default instead of raising KeyError."""
        return cfg.get(key, DEFAULT_CFG[key])

    cfg["opacity"]       = clamp_int(get("opacity"),       20,  100, DEFAULT_CFG["opacity"])
    cfg["hover_opacity"] = clamp_int(get("hover_opacity"),  5,   80, DEFAULT_CFG["hover_opacity"])
    cfg["scale"]         = clamp_int(get("scale"),          60,  200, DEFAULT_CFG["scale"])
    cfg["update_ms"]     = snap_ms(get("update_ms"))
    cfg["locked"]        = bool(get("locked"))
    cfg["always_on_top"] = bool(get("always_on_top"))
    try:
        cfg["pos_x"] = int(get("pos_x"))
        cfg["pos_y"] = int(get("pos_y"))
    except (TypeError, ValueError):
        cfg["pos_x"] = DEFAULT_CFG["pos_x"]
        cfg["pos_y"] = DEFAULT_CFG["pos_y"]
    cfg["anchor"] = get("anchor") if get("anchor") in ANCHOR_PRESETS else ""
    cfg["theme"] = get("theme") if get("theme") in ("dark", "light") else "dark"
    cfg["layout"] = get("layout") if get("layout") in ("card", "bar") else "card"
    saved_colors = get("colors")
    if not isinstance(saved_colors, dict):
        # A wrong type here used to raise out of _sanitize_cfg and take every
        # other saved setting down with it.
        _log.warning("settings.json 'colors' is %s, expected an object — ignoring it.",
                     type(saved_colors).__name__)
        saved_colors = {}
    cfg["colors"] = {
        k: v for k, v in saved_colors.items()
        if k in SENSOR_CATALOG and isinstance(v, str) and _HEX_RE.match(v)
    }
    return cfg


def default_cfg() -> dict:
    """Return a fresh copy of DEFAULT_CFG.

    Deep, because the settings dialog mutates cfg["colors"] / ["visible"] in
    place: a shallow copy would let those edits leak into the module-level
    defaults for the rest of the session.
    """
    return copy.deepcopy(DEFAULT_CFG)


def _migrate_legacy_settings() -> bool:
    """Adopt a pre-rename Palantir settings.json when there is none of our own.

    Before the rename the app wrote %LOCALAPPDATA%\\Palantir\\settings.json, so
    after it every user setting silently came back as a default. The legacy file
    is copied, never moved: a migration must not destroy the only copy. Returns
    True when a legacy file was adopted.
    """
    if os.path.exists(SETTINGS_FILE) or not os.path.exists(LEGACY_SETTINGS_FILE):
        return False
    try:
        with open(LEGACY_SETTINGS_FILE, "rb") as src:
            data = src.read()
        with open(SETTINGS_FILE, "wb") as dst:
            dst.write(data)
    except OSError as e:
        _log.warning("Could not migrate legacy settings from %s: %s",
                     LEGACY_SETTINGS_FILE, e)
        return False
    _log.info("Migrated pre-rename settings from %s", LEGACY_SETTINGS_FILE)
    return True


# ── Load / save ───────────────────────────────────────────────────────────────
def load_cfg():
    _migrate_legacy_settings()
    try:
        with open(SETTINGS_FILE) as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            raise ValueError(f"root is {type(saved).__name__}, expected an object")
        cfg = default_cfg()
        # Scalar fields
        for k in ("opacity", "hover_opacity", "update_ms", "locked",
                  "always_on_top", "pos_x", "pos_y", "anchor", "theme", "scale",
                  "layout", "skipped_version"):
            if k in saved:
                cfg[k] = saved[k]

        saved_colors = saved.get("colors")
        cfg["colors"] = saved_colors if isinstance(saved_colors, dict) else {}

        # Container fields: a wrong type must degrade to the default for that
        # field only — never abort the load and discard everything else.
        saved_vis     = saved.get("visible")
        saved_vis     = saved_vis if isinstance(saved_vis, dict) else {}
        saved_active  = saved.get("active_sensors")

        # active_sensors — new field; derive from old "visible" if absent
        if isinstance(saved_active, list):
            cfg["active_sensors"] = [
                k for k in saved_active if k in SENSOR_CATALOG
            ]
        else:
            derived = [k for k in SENSOR_CATALOG if saved_vis.get(k, False)]
            cfg["active_sensors"] = derived if derived else list(_DEFAULT_ACTIVE)

        # visible: only keys in active_sensors; default True if not saved
        cfg["visible"] = {
            k: saved_vis.get(k, True) for k in cfg["active_sensors"]
        }
        cfg = _sanitize_cfg(cfg)
        _log.info("Settings loaded from %s", SETTINGS_FILE)
        return cfg
    except FileNotFoundError:
        _log.info("No settings file found, using defaults.")
        return default_cfg()
    except json.JSONDecodeError as e:
        _log.warning("Settings file corrupted (%s), using defaults.", e)
        _backup_corrupt_settings()
        return default_cfg()
    except Exception as e:
        # Any other read/parse/validation failure: keep the user's file as a
        # backup, because the next save_cfg would otherwise overwrite it with
        # defaults and the original settings would be gone for good.
        _log.error("Failed to load settings (%s: %s), using defaults.",
                   type(e).__name__, e)
        _backup_corrupt_settings()
        return default_cfg()


def _backup_corrupt_settings():
    """Rename corrupt settings file so it is not overwritten silently."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = SETTINGS_FILE + f".corrupt_{ts}"
    try:
        os.rename(SETTINGS_FILE, backup)
        _log.warning("Corrupt settings backed up to %s", backup)
    except Exception:
        pass


def save_cfg(cfg):
    """Atomically write cfg to SETTINGS_FILE (write-then-rename pattern)."""
    tmp = SETTINGS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        # Atomic replace — avoids partial writes corrupting the file
        if os.path.exists(SETTINGS_FILE):
            os.replace(tmp, SETTINGS_FILE)
        else:
            os.rename(tmp, SETTINGS_FILE)
        _log.debug("Settings saved.")
    except Exception as e:
        _log.error("Failed to save settings: %s", e)
        try:
            os.remove(tmp)
        except Exception:
            pass


# ── Active sensor helpers ─────────────────────────────────────────────────────
def active_sensor_defs(cfg) -> list[SensorDef]:
    """Return ordered SensorDef list for sensors active in cfg."""
    return [SENSOR_CATALOG[k] for k in cfg["active_sensors"] if k in SENSOR_CATALOG]


# ── Colour helpers ────────────────────────────────────────────────────────────
def default_color(key: str) -> str:
    s = SENSOR_CATALOG.get(key)
    return s.color if s else "#e8e8e8"


def eff_color(cfg, key: str) -> str:
    """Return the active sensor colour: custom if set, else catalog default."""
    return cfg["colors"].get(key, default_color(key))
