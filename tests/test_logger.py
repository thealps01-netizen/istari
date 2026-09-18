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
