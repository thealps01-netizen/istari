r"""tests/conftest.py — keep the suite away from the real machine state.

LOCALAPPDATA is redirected *before* any app module is imported, because logger.py
and cfg.py derive their folders from it at import time. Without this, importing
istari wrote into the real %LOCALAPPDATA%\Istari\logs. Any registry write that a
test did not fake itself fails the test.
"""

import atexit
import os
import shutil
import tempfile
import winreg

import pytest

_SESSION_DIR = tempfile.mkdtemp(prefix="istari-tests-")
os.environ["LOCALAPPDATA"] = _SESSION_DIR
atexit.register(shutil.rmtree, _SESSION_DIR, ignore_errors=True)


_WRITE_ACCESS = winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY


@pytest.fixture(autouse=True)
def _no_real_registry(monkeypatch):
    """Registry writes (and write-access opens) not faked by the test fail it."""
    def blocked(*_a, **_k):
        raise RuntimeError("test touched the real registry")

    for name in ("CreateKey", "CreateKeyEx", "SetValueEx", "SetValue",
                 "DeleteValue", "DeleteKey", "DeleteKeyEx"):
        monkeypatch.setattr(winreg, name, blocked)

    real_open = winreg.OpenKey

    def guarded_open(key, sub_key, reserved=0, access=winreg.KEY_READ):
        if access & _WRITE_ACCESS:
            blocked()
        return real_open(key, sub_key, reserved, access)

    monkeypatch.setattr(winreg, "OpenKey", guarded_open)


@pytest.fixture(autouse=True)
def _fresh_cfg_save_block(monkeypatch):
    """`cfg._save_block` is session-sticky; do not let it leak between tests."""
    import cfg
    monkeypatch.setattr(cfg, "_save_block", None)
