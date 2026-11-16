"""hw.py — Hardware data sources: MSI Afterburner shared memory + Windows RAM.

Also provides HardwareWorker — a QThread-based poller that emits sensor data
on a configurable interval without blocking the UI thread.
"""

import ctypes, math, re, socket, time
from logger import get_logger

_log = get_logger("hw")

# ── MSI Afterburner shared memory (MAHM v2.0) ─────────────────────────────────
FILE_MAP_READ = 0x0004
MAX_PATH      = 260
MAHM_SIG      = 0x4D41484D


class _Hdr(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("sig",          ctypes.c_uint32),
        ("ver",          ctypes.c_uint32),
        ("headerSize",   ctypes.c_uint32),
        ("num",          ctypes.c_uint32),
        ("entrySize",    ctypes.c_uint32),
        ("time",         ctypes.c_uint32),
        ("numGpu",       ctypes.c_uint32),
        ("gpuEntrySize", ctypes.c_uint32),
    ]


class _Entry(ctypes.LittleEndianStructure):
    """MAHM_SHARED_MEMORY_ENTRY as declared in MSI Afterburner's SDK header.

    Field names follow the SDK because the last two floats are minLimit and
    maxLimit — the range of the sensor's own graph, not observed session
    values. Reading maxLimit as a "session max" produced bars pinned at full
    width. Offsets and total size are unchanged.
    """

    _pack_ = 1
    _fields_ = [
        ("srcName",   ctypes.c_char * MAX_PATH),
        ("srcUnits",  ctypes.c_char * MAX_PATH),
        ("locName",   ctypes.c_char * MAX_PATH),
        ("locUnits",  ctypes.c_char * MAX_PATH),
        ("locFormat", ctypes.c_char * MAX_PATH),   # szRecommendedFormat
        ("data",      ctypes.c_float),
        ("min_limit", ctypes.c_float),             # minimum limit for graphs
        ("max_limit", ctypes.c_float),             # maximum limit for graphs
        ("flags",     ctypes.c_uint32),
        ("gpu",       ctypes.c_uint32),            # v2.0+ data source GPU index
        ("src_id",    ctypes.c_uint32),            # v2.0+ data source ID
    ]


# ── Pre-computed sizes, kernel32 setup (once at import) ───────────────────────
_HDR_SIZE   = ctypes.sizeof(_Hdr)
_ENTRY_SIZE = ctypes.sizeof(_Entry)

_mahm_sensor_count: int = 0   # tracks last reported count to avoid log spam

_k32 = ctypes.windll.kernel32
_k32.OpenFileMappingW.restype  = ctypes.c_void_p
_k32.MapViewOfFile.restype     = ctypes.c_void_p
_k32.UnmapViewOfFile.argtypes  = [ctypes.c_void_p]
_k32.CloseHandle.argtypes      = [ctypes.c_void_p]
_k32.GetTickCount.restype      = ctypes.c_uint32
_k32.VirtualQuery.argtypes     = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
_k32.VirtualQuery.restype      = ctypes.c_size_t
_u32 = ctypes.windll.user32
_u32.GetForegroundWindow.restype      = ctypes.c_void_p
_u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
_u32.GetWindowThreadProcessId.restype  = ctypes.c_uint32

# v1.x MAHM entries (no gpu / src_id fields) are 12 bytes shorter than v2.0.
_MIN_ENTRY_SIZE = _ENTRY_SIZE - 12

# Problems seen on every poll are logged once, then again after a good read.
_warned: set = set()


def _warn_once(key: str, msg: str, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        _log.warning(msg, *args)


class _MemInfo(ctypes.Structure):
    """MEMORY_BASIC_INFORMATION (64-bit layout, with PartitionId)."""
    _fields_ = [
        ("BaseAddress",       ctypes.c_void_p),
        ("AllocationBase",    ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_uint32),
        ("PartitionId",       ctypes.c_uint16),
        ("RegionSize",        ctypes.c_size_t),
        ("State",             ctypes.c_uint32),
        ("Protect",           ctypes.c_uint32),
        ("Type",              ctypes.c_uint32),
    ]


def _view_size(pv) -> int:
    """Bytes mapped at `pv` (0 when the query fails)."""
    mi = _MemInfo()
    if _k32.VirtualQuery(pv, ctypes.byref(mi), ctypes.sizeof(mi)) == 0:
        return 0
    return int(mi.RegionSize)


def _foreground_pid() -> int:
    """PID of the foreground window's process (0 when unknown)."""
    try:
        hwnd = _u32.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = ctypes.c_uint32(0)
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception as e:
        _log.debug("Foreground PID unavailable (%s: %s)", type(e).__name__, e)
        return 0


def _usable_max(value: float, limit: float) -> float | None:
    """Return the progress-bar scale for a sensor, or None to use its bar_max.

    MAHM reports minLimit/maxLimit — the sensor's own graph range, not a session
    maximum. It is unusable when it is missing or zero (older layouts report 0)
    and also when the live value has outgrown it: a 5455 MHz clock on a
    5000 MHz scale would clamp at full width and stop conveying anything.
    """
    if not (math.isfinite(limit) and 0 < limit < 3.4e38):
        return None
    if math.isfinite(value) and value > limit:
        return None
    return limit


def _parse_mahm(pv: int, size: int) -> dict:
    """Parse a MAHM view of `size` mapped bytes starting at address `pv`.

    Every read is bounded by `size`: a header that claims more entries than
    the view holds, or v1.x entries 12 bytes shorter than ours, must not read
    past the end of the mapping (an access violation is a hard crash).
    """
    if size < _HDR_SIZE:
        _warn_once("mahm-size", "MAHM view is only %d bytes — ignoring it", size)
        return {}
    # Local buffers — read_mahm() is called from both the worker thread and
    # the UI thread (Settings dialog); shared module-level buffers would race.
    _hdr_buf   = (ctypes.c_byte * _HDR_SIZE)()
    _entry_buf = (ctypes.c_byte * _ENTRY_SIZE)()
    ctypes.memmove(_hdr_buf, pv, _HDR_SIZE)
    hdr = _Hdr.from_buffer(_hdr_buf)
    if hdr.sig != MAHM_SIG:
        _log.debug("MAHM signature mismatch — Afterburner not running?")
        return {}
    num    = hdr.num
    hdr_sz = hdr.headerSize or _HDR_SIZE
    sz     = hdr.entrySize  or _ENTRY_SIZE
    if num > 512 or sz < _MIN_ENTRY_SIZE or sz > 8192 or hdr_sz < _HDR_SIZE or hdr_sz > size:
        _warn_once("mahm-header", "MAHM header sanity check failed (num=%d, hdr=%d, sz=%d, view=%d)",
                   num, hdr_sz, sz, size)
        return {}
    fits = (size - hdr_sz) // sz
    if num > fits:
        _warn_once("mahm-trunc", "MAHM header claims %d entries but the view holds %d — "
                   "reading %d", num, fits, fits)
        num = fits
    _warned.difference_update(("mahm-size", "mahm-header"))
    copy_n = min(sz, _ENTRY_SIZE)
    out = {}
    for i in range(num):
        try:
            ctypes.memset(_entry_buf, 0, _ENTRY_SIZE)   # no stale tail from the last entry
            ctypes.memmove(_entry_buf, pv + hdr_sz + i * sz, copy_n)
            e = _Entry.from_buffer(_entry_buf)
            n = e.srcName.decode("utf-8", errors="ignore").rstrip("\x00").lower()
            if n:
                v = e.data
                if math.isfinite(v) and v < 3.4e38:
                    out[n] = (v, _usable_max(v, e.max_limit))
        except Exception as e:
            _log.warning("MAHM entry %d unreadable (%s: %s) — returning the %d sensor(s) "
                         "read so far", i, type(e).__name__, e, len(out))
            break
    if out:
        global _mahm_sensor_count
        if len(out) != _mahm_sensor_count:
            _mahm_sensor_count = len(out)
            _log.info("MAHM connected — %d sensors available", len(out))
    return out


def read_mahm() -> dict:
    hm = _k32.OpenFileMappingW(FILE_MAP_READ, False, "MAHMSharedMemory")
    if not hm:
        return {}
    pv = _k32.MapViewOfFile(hm, FILE_MAP_READ, 0, 0, 0)
    if not pv:
        _k32.CloseHandle(hm)
        return {}
    try:
        return _parse_mahm(pv, _view_size(pv))
    except Exception as e:
        _log.error("MAHM read error: %s", e)
        return {}
    finally:
        _k32.UnmapViewOfFile(pv)
        _k32.CloseHandle(hm)


def list_mahm_sensors() -> dict[str, float]:
    """Return all available MAHM sensor names → current values.

    Used by the Settings dialog dropdown to show what Afterburner is exposing.
    Returns empty dict if Afterburner is not running.
    """
    return {k: v for k, (v, _mx) in read_mahm().items()}


# ── RTSS shared memory (direct FPS fallback) ──────────────────────────────────
# Afterburner's "Framerate" sensor is fed by RTSS. Some games (e.g. CS2) or
# configurations don't surface it through MAHM, so we also read RTSS's own
# shared memory ("RTSSSharedMemoryV2") directly as a fallback.
RTSS_SIG = 0x52545353   # 'RTSS'


class _RtssHdr(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("dwSignature",    ctypes.c_uint32),
        ("dwVersion",      ctypes.c_uint32),
        ("dwAppEntrySize", ctypes.c_uint32),
        ("dwAppArrOffset", ctypes.c_uint32),
        ("dwAppArrSize",   ctypes.c_uint32),
        ("dwOSDEntrySize", ctypes.c_uint32),
        ("dwOSDArrOffset", ctypes.c_uint32),
        ("dwOSDArrSize",   ctypes.c_uint32),
        ("dwOSDFrame",     ctypes.c_uint32),
    ]


class _RtssAppEntry(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("dwProcessID", ctypes.c_uint32),
        ("szName",      ctypes.c_char * MAX_PATH),
        ("dwFlags",     ctypes.c_uint32),
        ("dwTime0",     ctypes.c_uint32),
        ("dwTime1",     ctypes.c_uint32),
        ("dwFrames",    ctypes.c_uint32),
        ("dwFrameTime", ctypes.c_uint32),
    ]


_RTSS_HDR_SIZE = ctypes.sizeof(_RtssHdr)
_RTSS_APP_SIZE = ctypes.sizeof(_RtssAppEntry)


def _parse_rtss(pv: int, size: int, now: int, fg_pid: int) -> float | None:
    """FPS of the live hooked app in an RTSS view of `size` bytes.

    Prefers the app whose PID is `fg_pid` (the game in front); otherwise the
    most recently updated one. Reads stay inside the `size` mapped bytes.
    """
    if size < _RTSS_HDR_SIZE:
        return None
    hdr_buf = (ctypes.c_byte * _RTSS_HDR_SIZE)()
    ctypes.memmove(hdr_buf, pv, _RTSS_HDR_SIZE)
    hdr = _RtssHdr.from_buffer(hdr_buf)
    if hdr.dwSignature != RTSS_SIG or hdr.dwVersion < 0x00020000:
        return None
    n_apps     = hdr.dwAppArrSize
    entry_size = hdr.dwAppEntrySize
    # RTSS 7.3.x uses 12416-byte app entries; allow generous headroom.
    if n_apps > 256 or entry_size < _RTSS_APP_SIZE or entry_size > 65536:
        return None
    if hdr.dwAppArrOffset > size:
        return None
    n_apps = min(n_apps, (size - hdr.dwAppArrOffset) // entry_size)
    # dwTime0/dwTime1 are in GetTickCount() milliseconds — only entries
    # updated within the last few seconds are live (RTSS keeps stale slots
    # around for idle apps that rendered a frame long ago).
    mask = 0xFFFFFFFF
    best:    tuple | None = None   # (age, fps) of the most recent live app
    best_fg: tuple | None = None   # same, restricted to the foreground PID
    ebuf = (ctypes.c_byte * _RTSS_APP_SIZE)()
    for i in range(n_apps):
        ctypes.memmove(ebuf, pv + hdr.dwAppArrOffset + i * entry_size, _RTSS_APP_SIZE)
        e = _RtssAppEntry.from_buffer(ebuf)
        if not e.dwProcessID:
            continue
        age = (now - e.dwTime1) & mask             # tick-count wraparound safe
        if age > 3000:
            continue
        dt = (e.dwTime1 - e.dwTime0) & mask        # wraps like the age above
        if dt > 0 and e.dwFrames > 0:
            fps = e.dwFrames * 1000.0 / dt
            if 1 < fps < 2000:
                if best is None or age <= best[0]:
                    best = (age, fps)
                if fg_pid and e.dwProcessID == fg_pid and (best_fg is None or age <= best_fg[0]):
                    best_fg = (age, fps)
    pick = best_fg or best
    return pick[1] if pick else None


def read_rtss_fps() -> float | None:
    """Read current framerate directly from RTSS shared memory.

    Returns FPS of the hooked 3D app in the foreground, else of the most
    recently updated one, or None when RTSS is not running / no app is hooked.
    """
    hm = _k32.OpenFileMappingW(FILE_MAP_READ, False, "RTSSSharedMemoryV2")
    if not hm:
        return None
    pv = _k32.MapViewOfFile(hm, FILE_MAP_READ, 0, 0, 0)
    if not pv:
        _k32.CloseHandle(hm)
        return None
    try:
        return _parse_rtss(pv, _view_size(pv), _k32.GetTickCount(), _foreground_pid())
    except Exception as e:
        _log.debug("RTSS read error: %s", e)
        return None
    finally:
        _k32.UnmapViewOfFile(pv)
        _k32.CloseHandle(hm)


# ── Windows RAM (GlobalMemoryStatusEx) ────────────────────────────────────────
class _MemStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength",                ctypes.c_ulong),
        ("dwMemoryLoad",            ctypes.c_ulong),
        ("ullTotalPhys",            ctypes.c_ulonglong),
        ("ullAvailPhys",            ctypes.c_ulonglong),
        ("ullTotalPageFile",        ctypes.c_ulonglong),
        ("ullAvailPageFile",        ctypes.c_ulonglong),
        ("ullTotalVirtual",         ctypes.c_ulonglong),
        ("ullAvailVirtual",         ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_ram_pct() -> float:
    ms = _MemStatus()
    ms.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
    return float(ms.dwMemoryLoad)


# ── Network latency (TCP ping — runs in its own thread, cached) ───────────────
import threading as _threading

_ping_lock:   "_threading.Lock"  = _threading.Lock()
_ping_cache:  float | None       = None
_ping_thread: "_threading.Thread | None" = None


DEFAULT_PING_TARGET = ("1.1.1.1", 53)
_ping_target: tuple = DEFAULT_PING_TARGET
_ping_ok: "bool | None" = None   # last probe outcome for the current target


def set_ping_target(spec) -> None:
    """Set the probe target from a 'host:port' string (cfg 'ping_target').

    An invalid spec keeps the default and is logged.
    """
    global _ping_target, _ping_ok, _ping_cache
    from cfg import parse_ping_target
    target = parse_ping_target(spec) or DEFAULT_PING_TARGET
    if parse_ping_target(spec) is None:
        _log.warning("Invalid ping target %r — using %s:%d", spec, *DEFAULT_PING_TARGET)
    with _ping_lock:
        if target != _ping_target:
            _ping_target, _ping_ok, _ping_cache = target, None, None


def _ping_worker(host: str, port: int, timeout: float) -> None:
    global _ping_cache, _ping_ok
    err = None
    try:
        t0 = time.perf_counter()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        result = round((time.perf_counter() - t0) * 1000)
    except Exception as e:
        result, err = None, e
    with _ping_lock:
        if (host, port) == _ping_target:
            _ping_cache = result
            # Log state changes only: a poll every second would flood the log.
            if err is not None and _ping_ok is not False:
                _log.warning("Ping probe to %s:%d failed (%s: %s) — PING will show N/A "
                             "until it recovers", host, port, type(err).__name__, err)
            elif err is None and _ping_ok is False:
                _log.info("Ping probe to %s:%d recovered", host, port)
            _ping_ok = err is None
    global _ping_thread
    _ping_thread = None


def get_ping_ms(host: "str | None" = None, port: "int | None" = None,
                timeout: float = 2.0) -> float | None:
    """Return cached round-trip latency in ms; fires a background update each call."""
    global _ping_thread
    with _ping_lock:
        cached = _ping_cache
        th, tp = _ping_target
    host = th if host is None else host
    port = tp if port is None else port
    # Fire a new probe only when no probe is already running
    if _ping_thread is None or not _ping_thread.is_alive():
        t = _threading.Thread(target=_ping_worker, args=(host, port, timeout), daemon=True)
        _ping_thread = t
        t.start()
    return cached


# ── Windows API fallback dispatch ─────────────────────────────────────────────
_WIN_FALLBACKS = {
    "ram_usage":   get_ram_pct,
    "net_latency": get_ping_ms,
}


# ── Sensor pick helpers ───────────────────────────────────────────────────────
_STAT_RE = re.compile(r"\b(?:low|min|avg|max)\b")


def _pick_sensor(raw: dict, candidates: tuple) -> tuple[float | None, float | None]:
    """Return (current_val, bar_scale) for the first matching candidate.

    Exact name match wins over substring match, so e.g. the "framerate"
    candidate picks "framerate" and not "framerate 1% low".

    Candidates must stay component-specific: a bare generic entry such as
    "power" matches whichever MAHM source comes first and silently reports
    another component's value (GPU PWR showing CPU package power).
    """
    for c in candidates:
        tup = raw.get(c)
        if tup is not None:
            return tup   # (val, max_val)
    for c in candidates:
        for k, tup in raw.items():
            if c in k:
                # "framerate 1% low" / "... avg" are statistics of the sensor,
                # not the sensor: only a candidate that names them may bind them.
                if _STAT_RE.search(k) and not _STAT_RE.search(c):
                    continue
                return tup
    return (None, None)


def get_data(sensors: list) -> tuple[dict, dict, str]:
    """Return ({key: val}, {key: bar_scale}, source_label).

    sensors: list of SensorDef (from cfg.active_sensor_defs(cfg))
    bar_scale is MAHM's graph max limit when usable (see _usable_max), else
    None — the overlay then falls back to the sensor's catalogue bar_max.
    Windows API sensors always report bar_max.
    """
    raw = read_mahm()
    vals: dict  = {}
    maxes: dict = {}
    rtss_used = False
    for s in sensors:
        if s.mahm_names:
            v, mx = _pick_sensor(raw, s.mahm_names)
            # FPS fallback: read RTSS shared memory directly when MAHM has no
            # (or zero) framerate — e.g. sensor unchecked in Afterburner, or
            # games where MAHM doesn't surface it while RTSS is still hooked.
            if s.key == "fps" and not v:
                rtss_v = read_rtss_fps()
                if rtss_v is not None:
                    v, mx = rtss_v, None
                    rtss_used = True
                else:
                    # Last resort: Afterburner's "Frametime" sensor (ms/frame)
                    ft = raw.get("frametime")
                    if ft and ft[0] > 0:
                        v, mx = 1000.0 / ft[0], None
            vals[s.key]  = v
            maxes[s.key] = mx
        else:
            fn = _WIN_FALLBACKS.get(s.key)
            if fn:
                try:
                    vals[s.key] = fn()
                except Exception as e:
                    _log.warning("Sensor %s read failed (%s: %s)", s.key, type(e).__name__, e)
                    vals[s.key] = None
            else:
                vals[s.key] = None
            maxes[s.key] = s.bar_max   # Windows API sensors use fixed bar_max
    if raw:
        src = "MSI Afterburner"
    elif rtss_used:
        src = "RTSS"
    else:
        src = "N/A"
    return vals, maxes, src


# ── QThread-based async hardware worker ───────────────────────────────────────
# Import PyQt6 lazily so hw.py can still be used without Qt (e.g. in unit tests)
try:
    from PyQt6.QtCore import QThread, pyqtSignal, QObject

    class HardwareWorker(QObject):
        """Polls hardware data on a background QThread.

        Usage:
            worker = HardwareWorker(sensors, interval_ms=1000)
            thread = QThread()
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.data_ready.connect(my_slot)
            thread.start()
            # to stop:
            worker.stop()
            thread.quit()
        """

        data_ready = pyqtSignal(dict, dict, str)   # (vals, maxes, source_label)

        def __init__(self, sensors: list, interval_ms: int = 1000):
            super().__init__()
            self._sensors     = sensors
            self._interval_ms = interval_ms
            # True from construction: a stop() issued before the thread reaches
            # run() must not be overwritten.
            self._running     = True

        def set_sensors(self, sensors: list) -> None:
            self._sensors = sensors

        def set_interval(self, interval_ms: int) -> None:
            self._interval_ms = interval_ms

        def run(self) -> None:
            _log.debug("HardwareWorker started (interval=%dms)", self._interval_ms)
            while self._running:
                try:
                    vals, maxes, src = get_data(self._sensors)
                    self.data_ready.emit(vals, maxes, src)
                except Exception as e:
                    _log.error("HardwareWorker poll error: %s", e)
                # Sleep in short chunks so stop() takes effect quickly even
                # with a 5s interval (thread.wait(2000) would time out otherwise).
                slept = 0
                while self._running and slept < self._interval_ms:
                    step = min(100, self._interval_ms - slept)
                    QThread.msleep(step)
                    slept += step
            _log.debug("HardwareWorker stopped.")

        def stop(self) -> None:
            self._running = False

except ImportError:
    # PyQt6 not available — HardwareWorker simply won't exist
    pass
