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


def startup_value():
    """The raw autostart command currently registered for Istari, or None."""
    return _query_startup_value(_APP_NAME)


def restore_startup_value(prev) -> bool:
    """Put the autostart entry back to exactly `prev` (None = no entry).

    Unlike set_startup(True) this never substitutes the current command, so a
    rolled-back change leaves the registry as it was. True only when verified.
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_SET_VALUE
        )
    except OSError as e:
        _log.warning("Could not open the startup registry key (%s: %s)", type(e).__name__, e)
        return False
    try:
        if prev is None:
            try:
                winreg.DeleteValue(key, _APP_NAME)
            except OSError:
                pass   # already absent
        else:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, prev)
    except OSError as e:
        _log.warning("Could not restore the startup entry (%s: %s)", type(e).__name__, e)
        return False
    finally:
        winreg.CloseKey(key)
    return startup_value() == prev


def purge_dead_legacy_startup() -> bool:
    """Remove the pre-rename "Palantir" autostart value when its target is gone.

    After the rename that value pointed at C:\\Program Files\\Palantir\\Palantir.exe
    and nothing ever touched it again, so Windows kept trying to start a path
    that no longer exists. Only removed when the target file is missing — an old
    install still on disk keeps its entry. When it is removed, Istari's own
    autostart entry is enabled in its place. Returns True when it was removed.
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
    # The user had autostart under the old name and the installer registers
    # none: carry it over, or the upgrade silently turns autostart off.
    if set_startup(True):
        _log.info("Autostart carried over to '%s'.", _APP_NAME)
    else:
        _log.warning("Could not carry the autostart over to '%s' — the user must "
                     "re-enable it in Settings.", _APP_NAME)
    return True


# ── Settings file path ────────────────────────────────────────────────────────
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
_DIR = os.path.join(_LOCALAPPDATA, "Istari")
# Directory the pre-rename build wrote to; only its settings.json is adopted
# (logs and install files stay where they are).
_LEGACY_DIR = os.path.join(_LOCALAPPDATA, "Palantir")
try:
    os.makedirs(_DIR, exist_ok=True)
except OSError as _e:
    # load_cfg/save_cfg report the real failure; do not kill the import.
    _log.error("Could not create the settings directory %s (%s)", _DIR, _e)

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

# Version of the settings file layout. Bump when a change needs a migration.
# A file with a larger number was written by a newer build and is left alone.
SCHEMA_VERSION = 1

DEFAULT_PING_TARGET = "1.1.1.1:53"

DEFAULT_CFG = {
    "schema":          SCHEMA_VERSION,
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
    "ping_target":     DEFAULT_PING_TARGET,
}


# ── Settings validation ───────────────────────────────────────────────────────
_HEX_RE  = re.compile(r'^#[0-9a-fA-F]{6}$')
_HOST_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$')


def parse_ping_target(spec) -> "tuple[str, int] | None":
    """Parse 'host:port' into (host, port); None when it is not a valid target."""
    if not isinstance(spec, str):
        return None
    host, sep, port = spec.strip().rpartition(":")
    if not sep or not _HOST_RE.match(host) or not port.isdigit():
        return None
    port = int(port)
    return (host, port) if 1 <= port <= 65535 else None


def _sanitize_cfg(cfg: dict) -> dict:
    """Clamp/coerce every field so bad values in settings.json can't crash the app.

    Each field is validated on its own: a bad value costs that field only.
    """
    def clamp_int(v, lo, hi, default):
        try:
            v = int(v)
        except (TypeError, ValueError, OverflowError):   # OverflowError: int(inf)
            return default
        return max(lo, min(hi, v))

    def snap_ms(v):
        opts = [500, 1000, 2000, 5000]
        try:
            v = int(v)
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_CFG["update_ms"]
        return min(opts, key=lambda x: abs(x - v))

    def get(key):
        """Field value, falling back to its default instead of raising KeyError."""
        return cfg.get(key, DEFAULT_CFG[key])

    def boolean(key):
        v = get(key)
        return v if isinstance(v, bool) else DEFAULT_CFG[key]

    cfg["opacity"]       = clamp_int(get("opacity"),       20,  100, DEFAULT_CFG["opacity"])
    cfg["hover_opacity"] = clamp_int(get("hover_opacity"),  5,   80, DEFAULT_CFG["hover_opacity"])
    cfg["scale"]         = clamp_int(get("scale"),          60,  200, DEFAULT_CFG["scale"])
    cfg["update_ms"]     = snap_ms(get("update_ms"))
    cfg["locked"]        = boolean("locked")
    cfg["always_on_top"] = boolean("always_on_top")
    cfg["pos_x"] = clamp_int(get("pos_x"), -10**6, 10**6, DEFAULT_CFG["pos_x"])
    cfg["pos_y"] = clamp_int(get("pos_y"), -10**6, 10**6, DEFAULT_CFG["pos_y"])
    cfg["anchor"] = get("anchor") if get("anchor") in ANCHOR_PRESETS else ""
    cfg["theme"] = get("theme") if get("theme") in ("dark", "light") else "dark"
    cfg["layout"] = get("layout") if get("layout") in ("card", "bar") else "card"
    sv = get("skipped_version")
    cfg["skipped_version"] = sv if isinstance(sv, str) else ""
    pt = get("ping_target")
    target = parse_ping_target(pt)
    if target is None:
        if "ping_target" in cfg:
            _log.warning("settings.json 'ping_target' %r is not host:port — using %s.",
                         pt, DEFAULT_PING_TARGET)
        cfg["ping_target"] = DEFAULT_PING_TARGET
    else:
        cfg["ping_target"] = f"{target[0]}:{target[1]}"
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
    # active_sensors: known keys only, no duplicates, original order.
    active = get("active_sensors")
    if not isinstance(active, list):
        active = list(_DEFAULT_ACTIVE)
    seen = []
    for k in active:
        if isinstance(k, str) and k in SENSOR_CATALOG and k not in seen:
            seen.append(k)
    cfg["active_sensors"] = seen
    # visible: one real bool per active sensor, True when not (validly) saved.
    vis = get("visible")
    vis = vis if isinstance(vis, dict) else {}
    cfg["visible"] = {k: (vis[k] if isinstance(vis.get(k), bool) else True) for k in seen}
    cfg["schema"] = SCHEMA_VERSION
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
    tmp = SETTINGS_FILE + ".tmp"
    try:
        with open(LEGACY_SETTINGS_FILE, "rb") as src:
            data = src.read()
        _write_atomic(tmp, SETTINGS_FILE, data)   # a kill mid-copy leaves no partial file
    except OSError as e:
        _log.warning("Could not migrate legacy settings from %s: %s",
                     LEGACY_SETTINGS_FILE, e)
        _remove_quietly(tmp)
        return False
    _log.info("Migrated pre-rename settings from %s", LEGACY_SETTINGS_FILE)
    return True


# ── Load / save ───────────────────────────────────────────────────────────────
# Why save_cfg must not write: None, "unreadable" (the file exists but could not
# be read — the in-memory settings are only defaults) or "newer" (written by a
# newer build). Either way the file on disk holds settings we must not clobber.
# Both are sticky for the rest of the session.
_save_block: "str | None" = None


def _remove_quietly(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        _log.warning("Could not remove %s (%s)", path, e)


def _write_atomic(tmp: str, dest: str, data: bytes) -> None:
    """Write `data` to `tmp`, flush it to disk, then replace `dest` with it."""
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())   # else a power loss can leave a zero-length file
    os.replace(tmp, dest)


def is_first_run() -> bool:
    """True when there are no settings to adopt or load.

    Runs the legacy (pre-rename) migration first, so an upgraded user who just
    had their settings adopted is not shown the first-run welcome dialog.
    """
    _migrate_legacy_settings()
    return not os.path.exists(SETTINGS_FILE)


def load_cfg(read_only=False):
    """Load the settings.

    Only the startup load (the result becomes the live cfg) may set the sticky
    "unreadable" save block. `read_only=True` is for later loads (update checker,
    Skip): it never changes that block, and returns None when the file could not
    be read, so callers cannot mistake defaults for the user's settings.
    """
    # _save_block is never cleared here: a load racing with a save (the updater
    # thread reloads ~30 s after start) must not lift a block set earlier.
    global _save_block
    _migrate_legacy_settings()
    try:
        # utf-8-sig: Notepad writes a BOM, which plain utf-8 json.load rejects.
        with open(SETTINGS_FILE, encoding="utf-8-sig") as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            raise ValueError(f"root is {type(saved).__name__}, expected an object")
    except FileNotFoundError:
        _log.info("No settings file found, using defaults.")
        return default_cfg()
    except OSError as e:
        # Locked by antivirus/backup/sync, or a permissions problem: the file
        # may be perfectly good, so it stays where it is and is not overwritten.
        _log.error("Could not read settings (%s: %s) — using defaults for this "
                   "session; the file is left untouched.", type(e).__name__, e)
        if read_only:
            return None
        _save_block = "unreadable"
        return default_cfg()
    except (ValueError, RecursionError) as e:   # bad JSON/UTF-8, non-object root, absurd nesting
        _log.warning("Settings file corrupted (%s: %s), using defaults.", type(e).__name__, e)
        _backup_corrupt_settings()
        return default_cfg()

    try:
        raw_schema = saved.get("schema", 0)
        schema = raw_schema if isinstance(raw_schema, int) and not isinstance(raw_schema, bool) else 0
        if schema > SCHEMA_VERSION:
            _save_block = "newer"
            _log.warning("settings.json has schema %d, newer than the %d this build "
                         "understands — loading what is recognised and leaving the "
                         "file unchanged.", schema, SCHEMA_VERSION)
        cfg = default_cfg()
        # Unknown keys ride along untouched so a rollback / newer build keeps them.
        for k, v in saved.items():
            if k not in DEFAULT_CFG:
                cfg[k] = v
        for k in DEFAULT_CFG:
            if k in saved and k not in ("active_sensors", "visible"):
                cfg[k] = saved[k]

        # Container fields: a wrong type must degrade to the default for that
        # field only — never abort the load and discard everything else.
        saved_vis    = saved.get("visible")
        saved_vis    = saved_vis if isinstance(saved_vis, dict) else {}
        saved_active = saved.get("active_sensors")
        if isinstance(saved_active, list):
            cfg["active_sensors"] = saved_active
        else:
            # Pre-active_sensors files only had "visible".
            derived = [k for k in SENSOR_CATALOG if saved_vis.get(k) is True]
            cfg["active_sensors"] = derived if derived else list(_DEFAULT_ACTIVE)
        cfg["visible"] = saved_vis
        cfg = _sanitize_cfg(cfg)
        _log.info("Settings loaded from %s", SETTINGS_FILE)
        return cfg
    except Exception as e:
        # A bug, not bad data: keep the file as it is rather than renaming it.
        _log.exception("Failed to apply settings (%s: %s), using defaults.",
                       type(e).__name__, e)
        if read_only:
            return None
        _save_block = _save_block or "unreadable"
        return default_cfg()


def _backup_corrupt_settings():
    """Rename corrupt settings file so it is not overwritten silently."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = SETTINGS_FILE + f".corrupt_{ts}"
    try:
        os.rename(SETTINGS_FILE, backup)
        _log.warning("Corrupt settings backed up to %s", backup)
    except OSError as e:
        _log.error("Could not back up corrupt settings to %s (%s: %s) — the next save "
                   "will overwrite them.", backup, type(e).__name__, e)


def save_cfg(cfg) -> bool:
    """Atomically write cfg to SETTINGS_FILE (write, fsync, replace).

    Returns True only when the file was written and replaced; False (and a log
    line) on any failure or when saving would clobber a file we could not read
    or that a newer build wrote.
    """
    if _save_block == "unreadable":
        # The load failed, so cfg may be plain defaults. Sticky for the session:
        # even if the file is readable now, the user's real settings were never loaded.
        _log.error("Settings not saved: %s could not be read at startup; restart "
                   "Istari to load and edit it.", SETTINGS_FILE)
        return False
    if _save_block == "newer":
        _log.error("Settings not saved: %s was written by a newer build.", SETTINGS_FILE)
        return False
    tmp = SETTINGS_FILE + ".tmp"
    try:
        data = json.dumps({**cfg, "schema": SCHEMA_VERSION}, indent=2).encode("utf-8")
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        _write_atomic(tmp, SETTINGS_FILE, data)
        _log.debug("Settings saved.")
        return True
    except Exception as e:
        _log.error("Failed to save settings: %s", e)
        _remove_quietly(tmp)
        return False


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
