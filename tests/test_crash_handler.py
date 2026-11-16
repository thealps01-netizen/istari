"""tests/test_crash_handler.py — the crash dialog must not claim a saved report.

`_write_crash_log` used to swallow a failed write and still hand back a path, so
the dialog told the user "crash log saved" for a file that was never created.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import crash_handler


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    d.mkdir()
    monkeypatch.setattr(crash_handler, "LOG_DIR", str(d))
    return d


def _write_a_crash():
    """Run a real exception through _write_crash_log."""
    try:
        raise ValueError("kaboom")
    except ValueError:
        return crash_handler._write_crash_log(*sys.exc_info())


def test_write_crash_log_reports_the_file_it_wrote(log_dir):
    path, tb = _write_a_crash()

    assert path is not None
    assert os.path.exists(path)
    assert path.startswith(str(log_dir))
    assert "ValueError: kaboom" in open(path, encoding="utf-8").read()
    assert "ValueError: kaboom" in tb


def test_write_crash_log_returns_none_when_it_cannot_write(tmp_path, monkeypatch):
    """Unwritable log directory: no path, no exception, traceback still usable."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("a file where a directory is expected")
    monkeypatch.setattr(crash_handler, "LOG_DIR", str(blocker / "logs"))

    path, tb = _write_a_crash()

    assert path is None
    assert "ValueError: kaboom" in tb


def test_crash_message_names_a_log_file_only_when_one_was_saved(log_dir):
    saved, _ = _write_a_crash()

    assert str(saved) in crash_handler._crash_message(saved)
    assert "Crash log saved to:" in crash_handler._crash_message(saved)

    unsaved = crash_handler._crash_message(None)
    assert "could not be written" in unsaved
    assert "Crash log saved to:" not in unsaved


# ══ Regression tests: where the dialog runs, how often, how many files ═══════

import datetime as _dt
import logging
import threading
import time
import types


@pytest.fixture
def clean_handler(monkeypatch):
    """Isolate the module's global state and the process-wide hooks."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    monkeypatch.setattr(crash_handler, "_showing", False)
    monkeypatch.setattr(crash_handler, "_bridge", None)


def _exc():
    try:
        raise RuntimeError("worker blew up")
    except RuntimeError:
        return sys.exc_info()


def test_dialog_from_a_worker_thread_runs_on_the_gui_thread(qtbot, log_dir, clean_handler, monkeypatch):
    from PyQt6.QtCore import QThread
    seen = []
    monkeypatch.setattr(crash_handler, "_show_crash_dialog",
                        lambda path, tb: seen.append(QThread.currentThread()))
    crash_handler.install()
    gui = QThread.currentThread()

    def worker():
        raise RuntimeError("worker blew up")
    t = threading.Thread(target=worker)
    t.start()
    t.join()

    qtbot.waitUntil(lambda: bool(seen), timeout=5000)
    assert seen == [gui]
    assert crash_handler._showing is False        # released after the dialog closed


def test_worker_thread_crash_is_written_even_without_a_dialog_bridge(log_dir, clean_handler, monkeypatch):
    shown = []
    monkeypatch.setattr(crash_handler, "_show_crash_dialog", lambda *a: shown.append(a))
    monkeypatch.setattr(threading, "excepthook", crash_handler._thread_hook)

    t = threading.Thread(target=lambda: 1 / 0)
    t.start()
    t.join()

    assert shown == []                            # never built off the GUI thread
    files = list(log_dir.glob("crash_*.log"))
    assert len(files) == 1 and "ZeroDivisionError" in files[0].read_text(encoding="utf-8")


def test_install_registers_thread_and_unraisable_hooks(clean_handler):
    crash_handler.install()
    assert sys.excepthook is crash_handler._handle
    assert threading.excepthook is crash_handler._thread_hook
    assert sys.unraisablehook is crash_handler._unraisable_hook


def test_second_crash_while_a_dialog_is_open_shows_no_second_dialog(log_dir, clean_handler, monkeypatch):
    calls = []

    def dialog(path, tb):
        calls.append(path)
        if len(calls) == 1:                       # an exception raised inside the dialog's event loop
            crash_handler._handle(*_exc())
    monkeypatch.setattr(crash_handler, "_show_crash_dialog", dialog)

    crash_handler._handle(*_exc())

    assert len(calls) == 1
    assert len(list(log_dir.glob("crash_*.log"))) == 2     # both are still saved
    assert crash_handler._showing is False
    crash_handler._handle(*_exc())                          # and the next one shows again
    assert len(calls) == 2


def test_two_crashes_in_the_same_instant_get_two_files(log_dir, monkeypatch):
    fixed = _dt.datetime(2026, 11, 16, 12, 0, 0, 5)

    class _D:
        @staticmethod
        def now():
            return fixed
    monkeypatch.setattr(crash_handler, "datetime", types.SimpleNamespace(datetime=_D))

    first, _ = _write_a_crash()
    second, _ = _write_a_crash()

    assert first != second
    assert os.path.exists(first) and os.path.exists(second)


def test_only_the_newest_crash_logs_are_kept(log_dir):
    for i in range(crash_handler.KEEP_CRASH_LOGS + 5):
        _write_a_crash()
        time.sleep(0.001)
    kept = sorted(p.name for p in log_dir.glob("crash_*.log"))

    assert len(kept) == crash_handler.KEEP_CRASH_LOGS
    newest, _ = _write_a_crash()
    assert os.path.basename(newest) in sorted(p.name for p in log_dir.glob("crash_*.log"))


def test_failure_to_show_the_dialog_is_logged(qtbot, monkeypatch):
    import PyQt6.QtWidgets as qw
    records = []
    h = logging.Handler()
    h.emit = records.append
    crash_handler._log.addHandler(h)
    try:
        monkeypatch.setattr(qw, "QMessageBox", lambda: (_ for _ in ()).throw(RuntimeError("no display")))
        crash_handler._show_crash_dialog(None, "tb")
    finally:
        crash_handler._log.removeHandler(h)

    assert any("Could not show the crash dialog" in r.getMessage() for r in records)
