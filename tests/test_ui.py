"""tests/test_ui.py — UI smoke tests for istari.py (SettingsDialog + Istari widget)."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp_instance():
    """Single QApplication for the test session."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def default_cfg():
    from cfg import DEFAULT_CFG
    import copy
    return copy.deepcopy(DEFAULT_CFG)


# ── SettingsDialog smoke tests ─────────────────────────────────────────────────

def test_settings_dialog_opens(qapp_instance, default_cfg):
    """SettingsDialog should open without errors."""
    from istari import SettingsDialog
    dlg = SettingsDialog(default_cfg)
    assert dlg is not None
    dlg.close()


def test_settings_dialog_has_apply_button(qapp_instance, default_cfg):
    """Apply button should be present and enabled."""
    from PyQt6.QtWidgets import QPushButton
    from istari import SettingsDialog
    dlg = SettingsDialog(default_cfg)
    apply_buttons = [w for w in dlg.findChildren(QPushButton)
                     if "Apply" in w.text() or w.objectName() == "btn_ok"]
    assert len(apply_buttons) >= 1, "Apply button not found"
    assert apply_buttons[0].isEnabled()
    dlg.close()


def test_settings_dialog_closes_on_reject(qapp_instance, default_cfg):
    """Pressing Escape / calling reject() should close the dialog."""
    from istari import SettingsDialog
    dlg = SettingsDialog(default_cfg)
    dlg.reject()
    assert not dlg.isVisible()


def test_settings_dialog_accessible_names(qapp_instance, default_cfg):
    """All interactive widgets should have accessible names set."""
    from PyQt6.QtWidgets import QPushButton, QCheckBox, QSlider
    from istari import SettingsDialog
    dlg = SettingsDialog(default_cfg)
    missing = []
    for widget_type in (QPushButton, QCheckBox, QSlider):
        for w in dlg.findChildren(widget_type):
            if not w.accessibleName():
                missing.append(f"{type(w).__name__}: '{w.objectName()}'")
    dlg.close()
    assert not missing, f"Widgets missing accessible names: {missing}"


# ── _is_high_contrast smoke test ───────────────────────────────────────────────

def test_is_high_contrast_returns_bool(qapp_instance):
    """_is_high_contrast() should return a bool without raising."""
    from themes import is_high_contrast
    result = is_high_contrast()
    assert isinstance(result, bool)


# ── Failures the user must be able to see ─────────────────────────────────────

class _RecordingLog:
    def __init__(self):
        self.warnings = []

    def warning(self, *args):
        self.warnings.append(args)

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_startup_checkbox_reverts_when_the_registry_write_fails(qapp_instance, default_cfg, monkeypatch):
    """Ticking "Launch at Windows startup" used to stick even when nothing was
    registered, so the window claimed an autostart that did not exist."""
    import dialogs

    monkeypatch.setattr(dialogs, "save_cfg", lambda cfg: None)
    monkeypatch.setattr(dialogs, "set_startup", lambda enabled: False)
    monkeypatch.setattr(dialogs, "is_startup_enabled", lambda: False)

    dlg = dialogs.SettingsDialog(default_cfg)
    dlg.chk_startup.setChecked(True)

    dlg._apply()

    assert dlg.chk_startup.isChecked() is False
    dlg.close()


def test_no_activate_failure_is_reported_not_swallowed(qapp_instance, monkeypatch):
    """WS_EX_NOACTIVATE silently failing removes the no-focus-steal guarantee."""
    import istari

    def deny(*_a):
        raise OSError("access denied")

    rec = _RecordingLog()
    monkeypatch.setattr(istari, "_log", rec)
    monkeypatch.setattr(istari.ctypes.windll.user32, "SetWindowLongW", deny)

    class _FakeWidget:
        def winId(self):
            return 1234

    istari.Istari._apply_no_activate(_FakeWidget())   # must not raise

    assert any("WS_EX_NOACTIVATE" in str(w) for w in rec.warnings)
