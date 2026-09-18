"""crash_handler.py — Global unhandled exception handler for Istari.

Intercepts uncaught exceptions, writes a timestamped crash log under
%LOCALAPPDATA%/Istari/logs/, and shows a user-friendly dialog with
options to open the log folder or copy the traceback to clipboard.
"""

import sys
import os
import traceback
import datetime

from logger import LOG_DIR, get_logger

_log = get_logger("crash_handler")


def _write_crash_log(exc_type, exc_value, exc_tb) -> tuple[str | None, str]:
    """Write crash details to a timestamped file. Returns (path, traceback).

    `path` is None when the file could not be written, so the dialog can say so
    instead of claiming a report that does not exist.
    """
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, f"crash_{ts}.log")
    tb   = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Istari crash report — {datetime.datetime.now()}\n")
            f.write("=" * 60 + "\n\n")
            f.write(tb)
    except Exception as e:
        _log.error("Could not write crash log to %s (%s: %s)", path, type(e).__name__, e)
        return None, tb
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
    """Show a Qt dialog if QApplication is running, otherwise print."""
    try:
        from PyQt6.QtWidgets import QMessageBox, QApplication
        app = QApplication.instance()
        if app is None:
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
    except Exception:
        pass


def install() -> None:
    """Replace sys.excepthook with Istari's crash handler."""

    def _handler(exc_type, exc_value, exc_tb):
        # Let KeyboardInterrupt through normally
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _log.critical("Unhandled exception:\n%s", tb_str)

        crash_path, tb_text = _write_crash_log(exc_type, exc_value, exc_tb)
        _show_crash_dialog(crash_path, tb_text)

    sys.excepthook = _handler
    _log.debug("Crash handler installed.")
