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
