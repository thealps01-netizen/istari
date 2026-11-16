"""logger.py — Centralised logging setup for Istari.

Creates a rotating log file under %LOCALAPPDATA%/Istari/logs/
and exposes a get_logger() helper used by every module.

Importing this module never raises: an unwritable log folder falls back to the
temp folder, and failing that to a no-op handler, with the reason kept in
`LOG_WARNING`.
"""

import logging
import os
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler

# ── Log directory ──────────────────────────────────────────────────────────────
# Runtime data always lives in the application's own folder, frozen or not:
# keeping development logs inside the repository mixes them with tracked files
# and, on a synced working copy, pushes them into the cloud.
_BASE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Istari",
)

_PRIMARY_DIR  = os.path.join(_BASE, "logs")
_FALLBACK_DIR = os.path.join(tempfile.gettempdir(), "Istari", "logs")


def _prepare_log_dir(primary: str, fallback: str) -> tuple[str | None, str]:
    """Create the first usable log folder. Returns (folder or None, warning text)."""
    try:
        os.makedirs(primary, exist_ok=True)
        return primary, ""
    except OSError as e:
        warning = f"Log folder {primary} is not usable ({type(e).__name__}: {e})."
    try:
        os.makedirs(fallback, exist_ok=True)
        return fallback, warning + f" Logging to {fallback} instead."
    except OSError as e:
        return None, warning + f" Fallback {fallback} failed too ({type(e).__name__}: {e}); file logging is off."


_dir, LOG_WARNING = _prepare_log_dir(_PRIMARY_DIR, _FALLBACK_DIR)
LOG_DIR  = _dir or _PRIMARY_DIR
LOG_FILE = os.path.join(LOG_DIR, "istari.log")


class _TolerantRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that survives a rename Windows refuses.

    Windows cannot rename a log file another process still has open (a second
    Istari instance, or a source run next to the installed app). The stock
    handler then loses every later record; this one keeps appending to the
    current file and retries the rotation after a pause.
    """

    RETRY_AFTER = 60.0   # seconds between rotation attempts after a failure
    _retry_at = 0.0

    def shouldRollover(self, record):
        if time.monotonic() < self._retry_at:
            return False
        return super().shouldRollover(record)

    def doRollover(self):
        try:
            super().doRollover()
        except OSError as e:
            self._retry_at = time.monotonic() + self.RETRY_AFTER
            if self.stream is None:          # the failed rotation closed it
                self.stream = self._open()
            if sys.stderr is not None:
                print(f"Istari: log rotation skipped ({type(e).__name__}: {e})",
                      file=sys.stderr)


# ── Root logger ────────────────────────────────────────────────────────────────
_fmt = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _make_handler() -> logging.Handler:
    if _dir is not None:
        try:
            h = _TolerantRotatingFileHandler(
                LOG_FILE,
                maxBytes=1 * 1024 * 1024,  # 1 MB per file
                backupCount=2,              # max ~3 MB total on disk
                encoding="utf-8",
            )
            h.setFormatter(_fmt)
            h.setLevel(logging.DEBUG)
            return h
        except OSError as e:
            global LOG_WARNING
            LOG_WARNING = (LOG_WARNING + " " if LOG_WARNING else "") + \
                f"Could not open {LOG_FILE} ({type(e).__name__}: {e}); file logging is off."
    return logging.NullHandler()


_file_handler = _make_handler()

_root = logging.getLogger("istari")
_root.setLevel(logging.DEBUG)
if not _root.handlers:
    _root.addHandler(_file_handler)
_root.propagate = False

if LOG_WARNING:
    _root.warning(LOG_WARNING)
    if sys.stderr is not None:
        print(f"Istari: {LOG_WARNING}", file=sys.stderr)


def get_logger(name: str = "istari") -> logging.Logger:
    """Return a child logger under the 'istari' namespace."""
    if name == "istari":
        return _root
    return _root.getChild(name.replace("istari.", ""))
