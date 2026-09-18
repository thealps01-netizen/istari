"""logger.py — Centralised logging setup for Istari.

Creates a rotating log file under %LOCALAPPDATA%/Istari/logs/
and exposes a get_logger() helper used by every module.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# ── Log directory ──────────────────────────────────────────────────────────────
# Runtime data always lives in the application's own folder, frozen or not:
# keeping development logs inside the repository mixes them with tracked files
# and, on a synced working copy, pushes them into the cloud.
_BASE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Istari",
)

LOG_DIR  = os.path.join(_BASE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "istari.log")

os.makedirs(LOG_DIR, exist_ok=True)

# ── Root logger ────────────────────────────────────────────────────────────────
_fmt = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=1 * 1024 * 1024,  # 1 MB per file
    backupCount=2,              # max ~3 MB total on disk
    encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.DEBUG)

_root = logging.getLogger("istari")
_root.setLevel(logging.DEBUG)
if not _root.handlers:
    _root.addHandler(_file_handler)
_root.propagate = False


def get_logger(name: str = "istari") -> logging.Logger:
    """Return a child logger under the 'istari' namespace."""
    if name == "istari":
        return _root
    return _root.getChild(name.replace("istari.", ""))
