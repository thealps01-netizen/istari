"""crash_handler.py — Global unhandled exception handler for Istari.

Intercepts uncaught exceptions (main thread, worker threads, unraisable ones),
writes a timestamped crash log under %LOCALAPPDATA%/Istari/logs/, and shows a
user-friendly dialog with options to open the log folder or copy the traceback.

The dialog is only ever built on the GUI thread, and only one is open at a time.
"""

import itertools
import sys
import os
import threading
import traceback
import datetime

from logger import LOG_DIR, get_logger

_log = get_logger("crash_handler")

KEEP_CRASH_LOGS = 10

_counter = itertools.count(1)
_lock = threading.Lock()
_showing = False       # a crash dialog is open or queued for the GUI thread
_bridge = None         # QObject on the GUI thread, created by install()


def _prune_crash_logs(keep: int = KEEP_CRASH_LOGS) -> None:
    """Delete all but the newest `keep` crash logs (names sort chronologically)."""
    try:
        names = sorted(n for n in os.listdir(LOG_DIR)
                       if n.startswith("crash_") and n.endswith(".log"))
        for name in names[:-keep]:
            os.remove(os.path.join(LOG_DIR, name))
    except OSError as e:
        _log.warning("Could not prune old crash logs in %s (%s: %s)",
                     LOG_DIR, type(e).__name__, e)


def _write_crash_log(exc_type, exc_value, exc_tb) -> tuple[str | None, str]:
    """Write crash details to a unique timestamped file. Returns (path, traceback).

    `path` is None when the file could not be written, so the dialog can say so
    instead of claiming a report that does not exist.
    """
    now  = datetime.datetime.now()
    stem = f"crash_{now:%Y%m%d_%H%M%S_%f}_{next(_counter):03d}"
    tb   = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    path = os.path.join(LOG_DIR, stem + ".log")
    try:
        # "x": never overwrite another crash report (e.g. from a second process).
        with open(path, "x", encoding="utf-8") as f:
            f.write(f"Istari crash report — {now}\n")
            f.write("=" * 60 + "\n\n")
            f.write(tb)
    except Exception as e:
        _log.error("Could not write crash log to %s (%s: %s)", path, type(e).__name__, e)
        return None, tb
    _prune_crash_logs()
    return path, tb


def _crash_message(crash_path: str | None) -> str:
    """Body text of the crash dialog — names a log file only if one was saved."""
    if crash_path:
        return ("Istari hit an unexpected error.\n\n"
                f"Crash log saved to:\n{crash_path}")
    return ("Istari hit an unexpected error.\n\n"
            "The crash log could not be written (the log folder is not writable).\n"
            "The details are below.")


def _show_crash_dialog(crash_path: str | None, tb_text: str) -> None:
    """Show a Qt dialog if QApplication is running. GUI thread only."""
    try:
        from PyQt6.QtWidgets import QMessageBox, QApplication
        app = QApplication.instance()
        if app is None:
            _log.warning("No QApplication: crash dialog not shown.")
            return

        msg = QMessageBox()
        msg.setWindowTitle("Istari — Unexpected Error")
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText(_crash_message(crash_path))
        msg.setDetailedText(tb_text)

        open_btn = msg.addButton("Open Log Folder", QMessageBox.ButtonRole.ActionRole)
        copy_btn = msg.addButton("Copy",            QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Close",                      QMessageBox.ButtonRole.RejectRole)

        msg.exec()

        if msg.clickedButton() == open_btn:
            os.startfile(LOG_DIR)
        elif msg.clickedButton() == copy_btn:
            QApplication.clipboard().setText(tb_text)
    except Exception as e:
        _log.error("Could not show the crash dialog (%s: %s)", type(e).__name__, e)


def _run_dialog(crash_path: str | None, tb_text: str) -> None:
    """Show the dialog on the current (GUI) thread, then allow the next one."""
    global _showing
    try:
        _show_crash_dialog(crash_path, tb_text)
    finally:
        with _lock:
            _showing = False


def _make_bridge():
    """QObject living on the thread that calls install(); worker threads emit to it."""
    from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

    class _Bridge(QObject):
        crashed = pyqtSignal(object, str)

        def __init__(self):
            super().__init__()
            self.crashed.connect(self._on_crashed)

        @pyqtSlot(object, str)
        def _on_crashed(self, crash_path, tb_text):
            _run_dialog(crash_path, tb_text)

    return _Bridge()


def _handle(exc_type, exc_value, exc_tb) -> None:
    """Log, save and (once, on the GUI thread) show an unhandled exception."""
    global _showing
    # Let KeyboardInterrupt through normally
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _log.critical("Unhandled exception (thread %s):\n%s",
                  threading.current_thread().name, tb_str)

    crash_path, tb_text = _write_crash_log(exc_type, exc_value, exc_tb)

    with _lock:
        if _showing:
            _log.warning("A crash dialog is already open; this error was logged only.")
            return
        on_gui_thread = threading.current_thread() is threading.main_thread()
        if not on_gui_thread and _bridge is None:
            _log.warning("Crash on a worker thread without a dialog bridge: logged only.")
            return
        _showing = True

    if on_gui_thread:
        _run_dialog(crash_path, tb_text)
    else:
        _bridge.crashed.emit(crash_path, tb_text)   # queued → runs on the GUI thread


def _thread_hook(args) -> None:
    if args.exc_type is SystemExit:
        return
    _handle(args.exc_type, args.exc_value, args.exc_traceback)


def _unraisable_hook(unraisable) -> None:
    _log.error("Unraisable exception in %r: %s: %s", unraisable.object,
               getattr(unraisable.exc_type, "__name__", unraisable.exc_type),
               unraisable.exc_value)


def install() -> None:
    """Route every kind of unhandled exception through Istari's crash handler.

    Call from the GUI (main) thread.
    """
    global _bridge
    try:
        _bridge = _make_bridge()
    except Exception as e:
        _log.error("Crash dialog bridge unavailable (%s: %s); worker-thread "
                   "crashes will be logged only.", type(e).__name__, e)
        _bridge = None

    sys.excepthook = _handle
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable_hook
    _log.debug("Crash handler installed.")
