"""tests/test_logger.py — runtime data belongs to the application folder.

Development runs used to write logs into the repository working copy, which mixes
runtime state with tracked files (and syncs it when the project folder is synced).
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logger

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_log_dir_is_the_application_folder():
    assert logger.LOG_DIR.startswith(os.environ["LOCALAPPDATA"])
    assert logger.LOG_DIR.endswith(os.path.join("Istari", "logs"))


def test_log_dir_is_not_inside_the_repository():
    assert not os.path.abspath(logger.LOG_DIR).startswith(os.path.abspath(REPO_ROOT))


def test_logger_writes_into_that_folder():
    logger.get_logger("test").info("logger path check")
    for handler in logging.getLogger("istari").handlers:
        handler.flush()

    assert os.path.exists(logger.LOG_FILE)
    assert os.path.abspath(logger.LOG_FILE).startswith(os.path.abspath(logger.LOG_DIR))


# ══ Regression tests: import never fails, rotation tolerates a locked file ═══

import tempfile


def test_unwritable_log_folder_falls_back_to_the_temp_folder(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    fallback = tmp_path / "fallback" / "logs"

    folder, warning = logger._prepare_log_dir(str(blocker / "logs"), str(fallback))

    assert folder == str(fallback) and fallback.is_dir()
    assert "not usable" in warning and str(fallback) in warning


def test_no_usable_folder_returns_none_instead_of_raising(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")

    folder, warning = logger._prepare_log_dir(str(blocker / "a"), str(blocker / "b"))

    assert folder is None
    assert "file logging is off" in warning


def test_rotation_blocked_by_another_open_handle_does_not_lose_records(tmp_path):
    """Windows refuses to rename a log another process holds open (REL: two instances)."""
    path = tmp_path / "istari.log"
    handler = logger._TolerantRotatingFileHandler(str(path), maxBytes=2000, backupCount=2,
                                                  encoding="utf-8")
    errors = []
    handler.handleError = lambda record: errors.append(record)
    lg = logging.getLogger("istari.test_rotation")
    lg.propagate = False
    lg.addHandler(handler)
    holder = open(path, "a")        # the other instance: blocks the rename
    try:
        for i in range(60):
            lg.warning("record %03d %s", i, "x" * 60)
        handler.flush()
    finally:
        holder.close()
        lg.removeHandler(handler)
        handler.close()

    text = path.read_text(encoding="utf-8")
    assert errors == []
    assert "record 059" in text     # the last record still reached the file
    assert "record 000" in text     # nothing was dropped
    assert path.stat().st_size > 2000   # kept appending instead of rotating


def test_rotation_resumes_once_the_file_is_free(tmp_path):
    path = tmp_path / "istari.log"
    handler = logger._TolerantRotatingFileHandler(str(path), maxBytes=500, backupCount=1,
                                                  encoding="utf-8")
    handler.RETRY_AFTER = 0.0
    lg = logging.getLogger("istari.test_rotation_resume")
    lg.propagate = False
    lg.addHandler(handler)
    try:
        for i in range(30):
            lg.warning("record %03d %s", i, "x" * 60)
    finally:
        lg.removeHandler(handler)
        handler.close()

    assert (tmp_path / "istari.log.1").exists()
