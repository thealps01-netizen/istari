"""updater.py — Auto-update via GitHub Releases.

Checks the latest release tag on GitHub in a background QThread.
If a newer version exists, emits `update_available(version, download_url)`.

Usage in istari.py:
    from updater import UpdateChecker, prompt_and_install
    checker = UpdateChecker("thealps01-netizen", "istari")   # ← GitHub user/repo
    checker.update_available.connect(on_update)
    checker.start()

GitHub Release convention:
    Tag:   v1.2.3
    Asset: Istari_Setup.exe   (the installer)
"""

import re
import os
import sys
import ssl
import hashlib
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
import json

from PyQt6.QtCore    import QThread, pyqtSignal, QObject, Qt, QPoint, QRectF, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QApplication, QFrame, QWidget,
)
from PyQt6.QtGui     import QFont, QPainter, QColor, QPainterPath

from version import __version__
from logger  import get_logger

_log = get_logger("updater")

# Keeps downloader + progress dialog alive until download finishes (prevents GC)
_active: list = []

# ── Version comparison ─────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _parse(tag) -> tuple[int, int, int] | None:
    """'v1.2.3' → (1, 2, 3); anything that is not exactly MAJOR.MINOR.PATCH → None.

    Pre-release, build-metadata and four-part tags are refused rather than
    guessed at: release.yml only ever publishes vMAJOR.MINOR.PATCH, so any other
    shape is a hand-made release the updater must not offer.
    """
    if not isinstance(tag, str):
        return None
    m = _TAG_RE.match(tag.strip())
    return tuple(int(n) for n in m.groups()) if m else None


def _is_newer(remote_tag, current: str = __version__) -> bool:
    remote, local = _parse(remote_tag), _parse(current)
    if remote is None:
        _log.warning("Ignoring release tag %r: not vMAJOR.MINOR.PATCH", remote_tag)
        return False
    if local is None:
        _log.warning("Current version %r is not MAJOR.MINOR.PATCH; no update offered", current)
        return False
    return remote > local


# ── GitHub API fetch ───────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
TIMEOUT    = 8   # seconds


# Why a check failed → what the user is told (UP-9). Keys are the reason codes
# returned by _fetch_release().
_FAILURE_TEXT = {
    "rate_limit": "GitHub rate limit reached. Try again in a while.",
    "not_found":  "No Istari release was found on GitHub.",
    "http":       "GitHub returned an error. Try again later.",
    "network":    "Could not reach the update server. Check your connection.",
    "invalid":    "The update server sent an unexpected reply.",
    "error":      "The update check failed. See the log for details.",
}


def failure_text(reason: str) -> str:
    return _FAILURE_TEXT.get(reason, _FAILURE_TEXT["error"])


def _fetch_latest(owner: str, repo: str) -> dict | None:
    return _fetch_release(owner, repo)[0]


def _fetch_release(owner: str, repo: str) -> tuple[dict | None, str]:
    """(release, "") on success, (None, reason) on failure — see _FAILURE_TEXT."""
    url = GITHUB_API.format(owner=owner, repo=repo)
    req = urllib.request.Request(
        url,
        headers={
            "Accept":     "application/vnd.github+json",
            "User-Agent": f"Istari-Updater/{__version__}",
        },
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return json.loads(r.read().decode()), ""
    except urllib.error.HTTPError as e:
        _log.warning("GitHub API HTTP %s for %s/%s", e.code, owner, repo)
        if e.code in (403, 429):
            return None, "rate_limit"
        return None, "not_found" if e.code == 404 else "http"
    except urllib.error.URLError as e:
        _log.warning("Update check skipped (no network?): %s", e.reason)
        return None, "network"
    except ValueError as e:   # json.JSONDecodeError / UnicodeDecodeError
        _log.error("Update check: unreadable reply: %s", e)
        return None, "invalid"
    except Exception as e:
        _log.error("Update check error: %s", e)
        return None, "error"


INSTALLER_NAME = "Istari_Setup.exe"


def _find_installer_asset(release: dict) -> str | None:
    """Download URL of the asset named Istari_Setup.exe, or None.

    Selected by name, not by extension: any other .exe attached to a release is
    not the installer and must never be downloaded and run elevated.
    """
    assets = release.get("assets") if isinstance(release, dict) else None
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("name", "")).lower() == INSTALLER_NAME.lower():
            return asset.get("browser_download_url")
    return None


class ChecksumMissing(RuntimeError):
    """The release publishes no readable SHA256 for the installer."""


class ChecksumMismatch(ValueError):
    """The downloaded installer does not match its published SHA256."""


def _fetch_expected_sha256(installer_url: str) -> str | None:
    """SHA256 published beside the installer (`<url>.sha256`), or None.

    None means no usable checksum could be read — missing asset, network
    failure, empty body. The caller must refuse to install in that case: the
    downloaded file is about to be executed with administrator rights.
    """
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(
            urllib.request.Request(
                installer_url + ".sha256",
                headers={"User-Agent": "Istari-Updater/1.0"},
            ),
            timeout=TIMEOUT,
            context=ctx,
        ) as r:
            parts = r.read().decode("utf-8", errors="replace").split()
    except urllib.error.HTTPError as e:
        _log.warning("Checksum sidecar missing for %s (HTTP %s)", installer_url, e.code)
        return None
    except Exception as e:
        _log.warning("Could not fetch checksum sidecar for %s (%s: %s)",
                     installer_url, type(e).__name__, e)
        return None
    return parts[0].strip().lower() if parts else None


def _sha256_of(path: str) -> str:
    """SHA256 of a file, read in chunks so a large installer is not buffered."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Background checker ─────────────────────────────────────────────────────────

class UpdateChecker(QObject):
    """Runs a single version check on a background QThread.

    Signals:
        update_available(str tag, str download_url, str release_notes)
        no_update()
        check_failed(str message)   # user-facing reason; slots may ignore it

    Exactly one of the three signals is emitted per run, whatever the reply
    looks like, and the thread always ends — callers reset their "checking"
    flag from these signals.
    """

    update_available = pyqtSignal(str, str, str)  # (tag, download_url, notes)
    no_update        = pyqtSignal()
    check_failed     = pyqtSignal(str)

    def __init__(self, owner: str, repo: str, manual: bool = False):
        super().__init__()
        self._owner = owner
        self._repo  = repo
        self._manual = manual   # a manual check ignores "Skip This Version"
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)

    def start(self) -> None:
        """Start the background check (non-blocking)."""
        self._thread.start()

    def _run(self) -> None:
        try:
            self._check()
        except Exception as e:
            _log.exception("Update check crashed: %s", e)
            self.check_failed.emit(failure_text("error"))
        finally:
            self._thread.quit()

    def _check(self) -> None:
        _log.debug("Checking for updates (%s/%s, current=%s)",
                   self._owner, self._repo, __version__)

        # Import here to avoid circular imports at module load time
        from cfg import load_cfg
        skipped = load_cfg().get("skipped_version", "")

        release, reason = _fetch_release(self._owner, self._repo)
        if release is None:
            self.check_failed.emit(failure_text(reason))
            return
        tag = release.get("tag_name") if isinstance(release, dict) else None
        if not isinstance(tag, str) or not tag:
            _log.error("Update check: reply has no usable tag_name: %.200r", release)
            self.check_failed.emit(failure_text("invalid"))
            return

        if tag == skipped and not self._manual:
            _log.debug("Version %s skipped by user.", tag)
            self.no_update.emit()
        elif _is_newer(tag):
            url   = _find_installer_asset(release)
            notes = release.get("body") or ""
            if url:
                _log.info("Update available: %s (asset: %s)", tag, url)
                self.update_available.emit(tag, url, str(notes))
            else:
                _log.info("Update %s found but no %s asset attached.", tag, INSTALLER_NAME)
                self.no_update.emit()
        else:
            _log.debug("Already up to date (%s).", __version__)
            self.no_update.emit()


# ── Download + launch installer ────────────────────────────────────────────────

DOWNLOAD_TIMEOUT = 30          # seconds without data before a download gives up
_CHUNK           = 64 * 1024
_TMP_PREFIX      = "istari_update_"
_STALE_AGE       = 3600        # seconds; older leftover update dirs are deleted


def _cleanup_stale_update_dirs(max_age: float = _STALE_AGE) -> None:
    """Remove `istari_update_*` temp dirs left by earlier runs.

    A successful update leaves its installer behind (it is still running when the
    app quits), so only dirs older than `max_age` are touched.
    """
    base = tempfile.gettempdir()
    try:
        names = os.listdir(base)
    except OSError as e:
        _log.warning("Could not list %s to clean old updates: %s", base, e)
        return
    now = time.time()
    for name in names:
        if not name.startswith(_TMP_PREFIX):
            continue
        path = os.path.join(base, name)
        try:
            if now - os.path.getmtime(path) > max_age:
                shutil.rmtree(path)
                _log.info("Removed stale update folder %s", path)
        except OSError as e:
            _log.warning("Could not remove stale update folder %s: %s", path, e)


class InstallerDownloader(QObject):
    """Downloads the installer to a temp file, verifies it, then reports its path."""

    progress  = pyqtSignal(int)    # 0-100
    finished  = pyqtSignal(str)    # path to downloaded, verified installer
    error     = pyqtSignal(str)
    cancelled = pyqtSignal()

    _cancel = False

    def __init__(self, url: str, parent=None):
        super().__init__()
        self._url    = url
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        """Ask the download to stop; checked between chunks (thread-safe flag)."""
        self._cancel = True

    def _run(self) -> None:
        tmp_dir = None
        ok = False
        try:
            _cleanup_stale_update_dirs()

            # Checksum first: a release without one is refused before any
            # megabytes are fetched.
            expected_hash = _fetch_expected_sha256(self._url)
            if not expected_hash:
                raise ChecksumMissing(
                    "No SHA256 checksum published for this release, so the "
                    "installer cannot be verified."
                )

            name    = os.path.basename(urllib.parse.urlsplit(self._url).path) or INSTALLER_NAME
            tmp_dir = tempfile.mkdtemp(prefix=_TMP_PREFIX)
            dest    = os.path.join(tmp_dir, name)
            _log.info("Downloading update from %s → %s", self._url, dest)

            if not self._download(dest) or self._cancel:   # Cancel after the last chunk counts
                _log.info("Update download cancelled by the user.")
                self.cancelled.emit()
                return
            self.progress.emit(100)
            _log.info("Download complete: %s", dest)

            actual_hash = _sha256_of(dest)
            if actual_hash != expected_hash:
                raise ChecksumMismatch(
                    f"SHA256 mismatch: expected {expected_hash}, got {actual_hash}")
            _log.info("SHA256 verified OK: %s", actual_hash)

            ok = True
            self.finished.emit(dest)
        except Exception as e:
            _log.error("Download failed: %s", e)
            self.error.emit(str(e))
        finally:
            # Keep the folder only when the verified installer is about to run.
            if tmp_dir and not ok:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            self._thread.quit()

    def _download(self, dest: str) -> bool:
        """Stream the URL into `dest` via a .part file. False when cancelled."""
        part = dest + ".part"
        req = urllib.request.Request(
            self._url, headers={"User-Agent": f"Istari-Updater/{__version__}"})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT, context=ctx) as r, \
                open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done  = 0
            while True:
                if self._cancel:
                    return False
                chunk = r.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total > 0:
                    self.progress.emit(min(done * 100 // total, 99))
        if total > 0 and done != total:
            raise OSError(f"Download incomplete: got {done} of {total} bytes")
        os.replace(part, dest)
        return True


# ── Reusable UI helpers ────────────────────────────────────────────────────────

class _Panel(QWidget):
    """Opaque rounded dark panel — reliable background on WA_TranslucentBackground."""
    BG     = QColor("#141420")
    BORDER = QColor("#2a2a45")
    RADIUS = 10.0

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        p.fillPath(path, self.BG)
        p.setPen(self.BORDER)
        p.drawPath(path)
        p.end()


class _DraggableDialog(QDialog):
    """Frameless dialog that can be dragged by clicking anywhere."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _e):
        self._drag_pos = None

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.x() + (screen.width()  - self.width())  // 2,
            screen.y() + (screen.height() - self.height()) // 2,
        )


# ── Modern update dialog ───────────────────────────────────────────────────────

_STYLE = """
QDialog {
    background: transparent;
}
QLabel#title {
    color: #ffffff;
    font-size: 16px;
    font-weight: bold;
}
QLabel#subtitle {
    color: #8888aa;
    font-size: 11px;
}
QLabel#version_current {
    color: #8888aa;
    font-size: 13px;
}
QLabel#version_new {
    color: #00d4ff;
    font-size: 13px;
    font-weight: bold;
}
QLabel#notes_label {
    color: #aaaacc;
    font-size: 11px;
}
QFrame#separator {
    color: #2a2a45;
}
QPushButton#btn_update {
    background-color: #00d4ff;
    color: #0a0a14;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton#btn_update:hover {
    background-color: #33ddff;
}
QPushButton#btn_later {
    background-color: #1e1e35;
    color: #aaaacc;
    border: 1px solid #2a2a45;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
}
QPushButton#btn_later:hover {
    background-color: #28283f;
    color: #ccccee;
}
QPushButton#btn_skip {
    background-color: transparent;
    color: #555577;
    border: none;
    padding: 8px 12px;
    font-size: 11px;
}
QPushButton#btn_skip:hover {
    color: #8888aa;
}
QProgressBar {
    background-color: #1e1e35;
    border: 1px solid #2a2a45;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #00d4ff;
    border-radius: 4px;
}
"""


def _trim_notes(notes: str, limit: int = 320) -> str:
    """Release notes cut at a line/word boundary so markdown is not sliced mid-token."""
    s = notes.strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for sep in ("\n", " "):
        pos = cut.rfind(sep)
        if pos > limit // 2:
            cut = cut[:pos]
            break
    return cut.rstrip() + "…"


class UpdateDialog(_DraggableDialog):
    """Modern dark-themed update dialog."""

    # result codes
    SKIP  = 2
    UPDATE = 1
    LATER  = 0

    def __init__(self, tag: str, notes: str, parent=None):
        super().__init__(parent)
        self._tag   = tag
        self._choice = self.LATER

        self.setWindowTitle("Istari — Update Available")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(400)
        self.setStyleSheet(_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        container = _Panel(self)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(24, 24, 24, 20)
        inner.setSpacing(14)
        root.addWidget(container)

        # ── Header ────────────────────────────────────────────────────────────
        title = QLabel("New Update")
        title.setObjectName("title")
        subtitle = QLabel("An update is available for Istari.")
        subtitle.setObjectName("subtitle")
        inner.addWidget(title)
        inner.addWidget(subtitle)

        # ── Separator ─────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        inner.addWidget(sep)

        # ── Version row ───────────────────────────────────────────────────────
        ver_row = QHBoxLayout()
        ver_row.setSpacing(6)

        cur_lbl = QLabel("Current:")
        cur_lbl.setObjectName("version_current")
        cur_ver = QLabel(__version__)
        cur_ver.setObjectName("version_current")

        arrow = QLabel("→")
        arrow.setObjectName("subtitle")

        new_lbl = QLabel("New:")
        new_lbl.setObjectName("version_current")
        new_ver = QLabel(tag)
        new_ver.setObjectName("version_new")

        ver_row.addWidget(cur_lbl)
        ver_row.addWidget(cur_ver)
        ver_row.addWidget(arrow)
        ver_row.addWidget(new_lbl)
        ver_row.addWidget(new_ver)
        ver_row.addStretch()
        inner.addLayout(ver_row)

        # ── Release notes (trimmed) ────────────────────────────────────────────
        if notes and notes.strip():
            notes_lbl = QLabel(_trim_notes(notes))
            # Markdown, not AutoText: GitHub release notes are markdown, and Qt's
            # markdown reader does not treat <tags> as rich text.
            notes_lbl.setTextFormat(Qt.TextFormat.MarkdownText)
            notes_lbl.setObjectName("notes_label")
            notes_lbl.setWordWrap(True)
            inner.addWidget(notes_lbl)

        # ── Separator ─────────────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setObjectName("separator")
        sep2.setFrameShape(QFrame.Shape.HLine)
        inner.addWidget(sep2)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_skip = QPushButton("Skip This Version")
        self._btn_skip.setObjectName("btn_skip")
        self._btn_skip.clicked.connect(self._on_skip)

        btn_row.addWidget(self._btn_skip)
        btn_row.addStretch()

        self._btn_later = QPushButton("Later")
        self._btn_later.setObjectName("btn_later")
        self._btn_later.clicked.connect(self.reject)

        self._btn_update = QPushButton("Update")
        self._btn_update.setObjectName("btn_update")
        self._btn_update.setDefault(True)
        self._btn_update.clicked.connect(self._on_update)

        btn_row.addWidget(self._btn_later)
        btn_row.addWidget(self._btn_update)
        inner.addLayout(btn_row)

    def _on_update(self):
        self._choice = self.UPDATE
        self.accept()

    def _on_skip(self):
        self._choice = self.SKIP
        self.accept()

    def choice(self) -> int:
        return self._choice


class DownloadProgressDialog(_DraggableDialog):
    """Minimal dark progress dialog for installer download."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Istari — Downloading")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(360, 160)
        self.setStyleSheet(_STYLE)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        container = _Panel(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        root.addWidget(container)

        lbl = QLabel("Downloading update…")
        lbl.setObjectName("title")
        lbl.setFont(QFont(lbl.font().family(), 13))
        layout.addWidget(lbl)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(8)
        layout.addWidget(self._bar)

        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setObjectName("subtitle")
        self._pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._pct_lbl)

        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setObjectName("btn_later")
        self._btn_cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self._btn_cancel, 0, Qt.AlignmentFlag.AlignRight)

    def _on_cancel(self) -> None:
        self._btn_cancel.setEnabled(False)
        self.cancel_requested.emit()

    def reject(self) -> None:          # Esc = Cancel
        self._on_cancel()

    def set_progress(self, pct: int) -> None:
        self._bar.setValue(pct)
        self._pct_lbl.setText(f"{pct}%")
        QApplication.processEvents()

    def set_installing(self) -> None:
        self.setWindowTitle("Istari — Installing")
        for child in self.findChildren(QLabel):
            if child.objectName() == "title":
                child.setText("Installing update…")
                break
        self._bar.setRange(0, 0)
        self._btn_cancel.hide()
        self._pct_lbl.setText("please wait")
        QApplication.processEvents()


# ── Download error dialog ─────────────────────────────────────────────────────

def _friendly_error(raw: str) -> tuple[str, str]:
    """Return (title, body) user-friendly message from a raw exception string."""
    r = raw.lower()
    if "sha256 mismatch" in r:
        return (
            "Download Corrupted",
            "The downloaded installer did not match its published checksum,\n"
            "so it was deleted and not run. Please try again.\n"
            "If it keeps happening, download it manually from the release page.",
        )
    if "checksum" in r or "sha256" in r:
        return (
            "Update Could Not Be Verified",
            "This release does not publish a valid SHA256 checksum, so the\n"
            "installer was not run. Download it manually from the release page\n"
            "and install it yourself.",
        )
    if "getaddrinfo" in r or "name or service not known" in r or "nodename nor servname" in r:
        return (
            "No Internet Connection",
            "Could not reach the update server.\n"
            "Please check your internet connection and try again.",
        )
    if "timed out" in r or "timeout" in r:
        return (
            "Connection Timed Out",
            "The update server took too long to respond.\n"
            "Please try again in a moment.",
        )
    if "connection refused" in r:
        return (
            "Connection Refused",
            "The update server refused the connection.\n"
            "Please try again later.",
        )
    if "ssl" in r or "certificate" in r:
        return (
            "Secure Connection Failed",
            "Could not establish a secure connection to the server.\n"
            "Please check your system date/time and try again.",
        )
    return (
        "Download Failed",
        "An error occurred while downloading the update.\n"
        "Please try again later.",
    )


class _ErrorDialog(_DraggableDialog):
    """Styled error dialog matching the Istari dark theme."""

    def __init__(self, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Istari — Update Error")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(380)
        self.setStyleSheet(_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        container = _Panel(self)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(24, 22, 24, 20)
        inner.setSpacing(14)
        root.addWidget(container)

        # ── Header row ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        icon_lbl = QLabel("⚠")
        icon_lbl.setStyleSheet("color:#ff5555; font-size:20px; background:transparent;")
        title_lbl = QLabel(title)
        title_lbl.setObjectName("title")
        title_lbl.setWordWrap(True)
        hdr.addWidget(icon_lbl)
        hdr.addWidget(title_lbl, 1)
        inner.addLayout(hdr)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        inner.addWidget(sep)

        # ── Body text ─────────────────────────────────────────────────────────
        body_lbl = QLabel(body)
        body_lbl.setObjectName("subtitle")
        body_lbl.setWordWrap(True)
        body_lbl.setStyleSheet("color:#aaaacc; font-size:12px;")
        inner.addWidget(body_lbl)

        # ── OK button ─────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("  OK  ")
        btn_ok.setObjectName("btn_later")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        inner.addLayout(btn_row)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self.accept()
        else:
            super().keyPressEvent(e)


def _show_message(title: str, body: str, parent=None) -> None:
    dlg = _ErrorDialog(title, body, parent)
    dlg.adjustSize()
    dlg._center_on_screen()
    dlg.exec()


def _show_download_error(raw: str, parent=None) -> None:
    title, body = _friendly_error(raw)
    _log.warning("Download error shown to user: %s | raw: %s", title, raw)
    _show_message(title, body, parent)


ERROR_CANCELLED = 1223   # ERROR_CANCELLED: the user declined the UAC prompt


def _launch_installer(path: str) -> int | None:
    """Start the installer elevated. None when it started, else the Win32 error."""
    import ctypes

    # ShellExecuteExW — proper struct-based API, avoids return-type truncation
    # issues that plagued ShellExecuteW on 64-bit, and reliably passes args.
    class _SEI(ctypes.Structure):
        _fields_ = [
            ("cbSize",         ctypes.c_uint32),
            ("fMask",          ctypes.c_uint32),
            ("hwnd",           ctypes.c_void_p),
            ("lpVerb",         ctypes.c_wchar_p),
            ("lpFile",         ctypes.c_wchar_p),
            ("lpParameters",   ctypes.c_wchar_p),
            ("lpDirectory",    ctypes.c_wchar_p),
            ("nShow",          ctypes.c_int),
            ("hInstApp",       ctypes.c_void_p),
            ("lpIDList",       ctypes.c_void_p),
            ("lpClass",        ctypes.c_wchar_p),
            ("hkeyClass",      ctypes.c_void_p),
            ("dwHotKey",       ctypes.c_uint32),
            ("hIconOrMonitor", ctypes.c_void_p),
            ("hProcess",       ctypes.c_void_p),
        ]

    sei = _SEI()
    sei.cbSize       = ctypes.sizeof(_SEI)
    sei.lpVerb       = "runas"
    sei.lpFile       = path
    sei.lpParameters = "/VERYSILENT /NORESTART"
    sei.lpDirectory  = os.path.dirname(path)
    sei.nShow        = 1  # SW_SHOWNORMAL (so UAC dialog is visible)

    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteExW.restype = ctypes.c_bool
    if shell32.ShellExecuteExW(ctypes.byref(sei)):
        return None
    return ctypes.windll.kernel32.GetLastError()


def _start_install(path: str, prog, quit_fn, parent=None) -> bool:
    """Run the verified installer and quit only if it really started.

    On failure or a declined UAC prompt the app keeps running and the user is
    told; quitting here would leave them with no overlay and no update.
    """
    prog.set_installing()
    _log.info("Launching installer: %s", path)
    err = _launch_installer(path)
    if err is None:
        _log.info("Installer launched via ShellExecuteExW")
        QTimer.singleShot(500, quit_fn)
        return True

    _log.error("ShellExecuteExW failed (err=%d) — installer not launched", err)
    prog.done(0)
    shutil.rmtree(os.path.dirname(path), ignore_errors=True)
    if err == ERROR_CANCELLED:
        body = ("The update was not installed because administrator permission "
                "was not granted.\nIstari keeps running; you can update again "
                "from the tray menu.")
    else:
        body = (f"The installer could not be started (error {err}).\n"
                "Istari keeps running; you can try again from the tray menu.")
    _show_message("Update Not Installed", body, parent)
    return False


# ── High-level helper called from main UI ──────────────────────────────────────

def prompt_and_install(tag: str, download_url: str, notes: str = "", parent=None) -> None:
    """Show modern update dialog, then download & run installer if accepted."""
    from cfg import load_cfg, save_cfg

    dlg = UpdateDialog(tag, notes, parent)
    dlg.adjustSize()
    dlg._center_on_screen()
    dlg.exec()

    choice = dlg.choice()

    if choice == UpdateDialog.SKIP:
        cfg = load_cfg()
        cfg["skipped_version"] = tag
        save_cfg(cfg)
        _log.info("Version %s marked as skipped.", tag)
        return

    if choice != UpdateDialog.UPDATE:
        return

    # ── Download phase ────────────────────────────────────────────────────────
    prog = DownloadProgressDialog(parent)
    prog.adjustSize()
    prog._center_on_screen()
    prog.show()

    downloader = InstallerDownloader(download_url)
    _active.extend([downloader, prog])   # prevent GC while thread runs

    def _on_progress(pct: int):
        prog.set_progress(pct)

    quit_fn = (parent._quit if parent is not None and hasattr(parent, "_quit")
               else QApplication.instance().quit)

    def _on_finished(path: str):
        _active.clear()
        _start_install(path, prog, quit_fn, parent)

    def _on_cancelled():
        _active.clear()
        prog.done(0)

    def _on_error(msg_text: str):
        _active.clear()
        prog.done(0)
        _show_download_error(msg_text, parent)

    downloader.progress.connect(_on_progress)
    downloader.finished.connect(_on_finished)
    downloader.error.connect(_on_error)
    downloader.cancelled.connect(_on_cancelled)
    prog.cancel_requested.connect(downloader.cancel, Qt.ConnectionType.DirectConnection)
    downloader.start()
