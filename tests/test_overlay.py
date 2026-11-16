"""tests/test_overlay.py — regression tests for the Istari overlay widget (istari.py)."""

import copy
import os
import sys

import pytest
from PyQt6.QtCore import QObject, QPoint, QRect, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="session")
def qapp_instance():
    return QApplication.instance() or QApplication(sys.argv)


class _Sig:
    def connect(self, *_):
        pass


class FakeScreen:
    """Minimal QScreen stand-in: a geometry, a work area and a dummy signal."""

    def __init__(self, x, y, w, h, avail_h=None):
        self._g = QRect(x, y, w, h)
        self._a = QRect(x, y, w, avail_h if avail_h is not None else h)
        self.availableGeometryChanged = _Sig()

    def geometry(self):
        return self._g

    def availableGeometry(self):
        return self._a


class FakeWorker(QObject):
    data_ready = pyqtSignal(dict, dict, str)

    def __init__(self, *a, **k):
        super().__init__()

    def run(self): pass
    def stop(self): pass
    def set_interval(self, ms): pass
    def set_sensors(self, s): pass


@pytest.fixture
def make(qapp_instance, monkeypatch, tmp_path):
    """Factory: build an Istari with in-memory cfg, fake sensors and fake screens."""
    import cfg as cfgmod
    import istari

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cfgmod, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(istari, "save_cfg", lambda c: None)
    monkeypatch.setattr(istari, "HardwareWorker", FakeWorker)
    made = []

    def _make(screens=None, **overrides):
        cfg = copy.deepcopy(cfgmod.DEFAULT_CFG)
        cfg.update(overrides)
        monkeypatch.setattr(istari, "load_cfg", lambda: cfg)
        if screens is not None:
            monkeypatch.setattr(QApplication, "screens", staticmethod(lambda: list(screens)))
            monkeypatch.setattr(QApplication, "primaryScreen", staticmethod(lambda: screens[0]))
            monkeypatch.setattr(QApplication, "screenAt", staticmethod(
                lambda p: next((s for s in screens if s.geometry().contains(p)), None)))
        w = istari.Istari()
        made.append(w)
        return w

    yield _make
    for w in made:
        w._quitting = True
        w._hw_thread.quit()
        w._hw_thread.wait(2000)
        w._tray.hide()
        w.close()


S1 = lambda: FakeScreen(0, 0, 1920, 1080)
S2 = lambda: FakeScreen(1920, 0, 1920, 1080)
SLEFT = lambda: FakeScreen(-1920, 0, 1920, 1080)


# ── OV-1 ──────────────────────────────────────────────────────────────────────
def test_negative_saved_position_is_restored(make):
    w = make([S1(), SLEFT()], pos_x=-1500, pos_y=100)
    assert (w.x(), w.y()) == (-1500, 100)


def test_unset_marker_still_means_default(make):
    w = make([S1()], pos_x=-1, pos_y=-1)
    assert w.x() == 1920 - w.width() - 20 and w.y() == 20


# ── OV-2 ──────────────────────────────────────────────────────────────────────
def test_settings_apply_keeps_tray_hidden_overlay_hidden(make, monkeypatch):
    import istari

    class Dlg:
        def __init__(self, cfg, parent=None): pass
        def adjustSize(self): pass
        def width(self): return 400
        def height(self): return 600
        def move(self, *_): pass
        def exec(self): return True

    monkeypatch.setattr(istari, "SettingsDialog", Dlg)
    w = make([S1()])
    w.show()
    w._home_pos = w.pos()
    w.hide()                       # tray-hidden state
    w.setGeometry(100, 1200, w.width(), w.height())
    w.cfg["always_on_top"] = True
    # force a flag change so the old code path (unconditional show) would run
    w._apply_window_flags = lambda: w.setWindowFlags(w.windowFlags())
    w._open_settings()
    assert not w.isVisible()


# ── OV-3 ──────────────────────────────────────────────────────────────────────
def test_source_label_updates_after_layout_switch(make):
    w = make([S1()], layout="bar")
    w._on_data({}, {}, "MSI Afterburner")
    w.cfg["layout"] = "card"
    w._build()
    w._on_data({}, {}, "MSI Afterburner")
    assert w._src_lbl.text() == "MSI Afterburner"


# ── OV-4 ──────────────────────────────────────────────────────────────────────
def test_anchored_overlay_stays_on_its_saved_monitor(make):
    s1, s2 = S1(), S2()
    w = make([s1, s2], anchor="tr", pos_x=2000, pos_y=50)
    assert s2.geometry().contains(w.geometry().center())
    assert w.x() + w.width() <= s2.geometry().right() + 1


# ── OV-5 ──────────────────────────────────────────────────────────────────────
def test_overlay_is_pulled_back_when_its_monitor_disappears(make, monkeypatch):
    s1, s2 = S1(), S2()
    screens = [s1, s2]
    w = make(screens, pos_x=2000, pos_y=50)
    w.show()
    assert w.x() == 2000
    screens.remove(s2)
    w._on_screens_changed()
    assert s1.geometry().contains(w.geometry().center())


def test_anchored_overlay_resnaps_when_work_area_changes(make):
    s1 = S1()
    w = make([s1], anchor="br")
    s1._a = QRect(0, 0, 1280, 720)
    w._on_screens_changed()
    assert w.x() + w.width() <= 1280 and w.y() + w.height() <= 720


# ── OV-6 ──────────────────────────────────────────────────────────────────────
def test_default_position_uses_primary_screen_origin(make):
    s = FakeScreen(1920, 0, 1920, 1080, avail_h=1040)
    w = make([s])
    assert w.x() == 1920 + 1920 - w.width() - 20
    assert w.y() == 20


# ── OV-8 ──────────────────────────────────────────────────────────────────────
class _Ev:
    def __init__(self, spontaneous):
        self._s, self.accepted = spontaneous, None

    def spontaneous(self): return self._s
    def accept(self): self.accepted = True
    def ignore(self): self.accepted = False


def test_stray_window_close_is_ignored(make):
    w = make([S1()])
    e = _Ev(spontaneous=True)
    w.closeEvent(e)
    assert e.accepted is False


def test_programmatic_close_is_accepted(make):
    w = make([S1()])
    e = _Ev(spontaneous=False)
    w.closeEvent(e)
    assert e.accepted is True


def test_app_quit_ends_the_event_loop(make, qapp_instance):
    w = make()
    w.show()
    done = []
    QTimer.singleShot(50, qapp_instance.quit)
    QTimer.singleShot(3000, lambda: (done.append("timeout"), qapp_instance.exit(1)))
    rc = qapp_instance.exec()
    assert rc == 0 and not done


# ── OV-9 ──────────────────────────────────────────────────────────────────────
def _fake_dialog(mutate=None):
    class Dlg:
        def __init__(self, cfg, parent=None):
            if mutate:
                mutate(cfg)
        def adjustSize(self): pass
        def width(self): return 400
        def height(self): return 600
        def move(self, *_): pass
        def exec(self): return True
    return Dlg


def test_settings_apply_does_not_recreate_window_when_flag_unchanged(make, monkeypatch):
    import istari
    monkeypatch.setattr(istari, "SettingsDialog", _fake_dialog())
    w = make([S1()])
    w.show()
    calls = []
    w._apply_window_flags = lambda: calls.append(1)
    w._open_settings()
    assert calls == []


def test_settings_apply_recreates_window_when_always_on_top_changes(make, monkeypatch):
    import istari
    monkeypatch.setattr(istari, "SettingsDialog",
                        _fake_dialog(lambda c: c.__setitem__("always_on_top", not c["always_on_top"])))
    w = make([S1()])
    w.show()
    calls = []
    w._apply_window_flags = lambda: calls.append(1)
    w._open_settings()
    assert calls == [1]


def test_settings_apply_keeps_last_values_instead_of_dashes(make, monkeypatch):
    import istari
    monkeypatch.setattr(istari, "SettingsDialog", _fake_dialog())
    w = make([S1()])
    key = next(iter(w._cells))
    w._on_data({key: 42.0}, {}, "MSI Afterburner")
    before = w._cells[key][2].text()
    assert before != "---"
    w._open_settings()
    assert w._cells[key][2].text() == before


# ── OV-10 (istari side) ───────────────────────────────────────────────────────
def test_worker_wait_timeout_is_logged(make, monkeypatch):
    import istari

    class Rec:
        def __init__(self): self.warnings = []
        def warning(self, msg, *a): self.warnings.append(msg % a if a else msg)
        def info(self, *a, **k): pass
        def error(self, *a, **k): pass
        def debug(self, *a, **k): pass

    rec = Rec()
    monkeypatch.setattr(istari, "_log", rec)
    w = make([S1()])
    w._hw_thread.wait = lambda ms: False
    w._stop_worker()
    assert any("did not stop" in m for m in rec.warnings)


# ── OV-11 ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ok, expect", [(True, "info"), (False, "warning")])
def test_startup_refresh_reports_the_real_outcome(monkeypatch, ok, expect):
    import istari
    seen = []

    class Rec:
        def info(self, msg, *a): seen.append(("info", msg))
        def warning(self, msg, *a): seen.append(("warning", msg))

    monkeypatch.setattr(istari, "_log", Rec())
    monkeypatch.setattr(istari, "is_startup_enabled", lambda: True)
    monkeypatch.setattr(istari, "set_startup", lambda enabled: ok)
    istari._refresh_startup_entry()
    assert [lvl for lvl, _ in seen] == [expect]


# ── OV-12 (istari side) ───────────────────────────────────────────────────────
def test_update_checkers_stay_referenced_while_their_thread_runs(make, monkeypatch):
    import istari

    class FakeThread:
        def isRunning(self): return True

    class FakeChecker(QObject):
        update_available = pyqtSignal(str, str, str)
        no_update = pyqtSignal()
        check_failed = pyqtSignal()

        def __init__(self, owner, repo, parent=None):
            super().__init__()
            self._thread = FakeThread()

        def start(self): pass

    monkeypatch.setattr(istari, "UpdateChecker", FakeChecker)
    w = make([S1()])
    w._check_for_updates()
    first = w._updater
    w._updater_running = False      # first check "finished" its signal, thread still running
    w._check_for_updates()
    assert first in w._updater_refs and w._updater in w._updater_refs


# ── OV-14 ─────────────────────────────────────────────────────────────────────
def test_quit_is_idempotent(make):
    w = make([S1()])
    w.show()
    calls = []
    w._play_outro = lambda: calls.append(1)
    w._quit()
    w._quit()
    assert calls == [1]


def test_tray_toggle_ignored_while_quitting(make):
    w = make([S1()])
    w.show()
    w._quitting = True
    w._toggle_overlay()
    assert not w._sliding


# ── UI-3 ──────────────────────────────────────────────────────────────────────
def test_settings_dialog_opens_on_the_overlays_monitor(make, monkeypatch):
    import istari
    moves = []

    class Dlg:
        def __init__(self, cfg, parent=None): pass
        def adjustSize(self): pass
        def width(self): return 400
        def height(self): return 600
        def move(self, x, y): moves.append((x, y))
        def exec(self): return False

    monkeypatch.setattr(istari, "SettingsDialog", Dlg)
    s1, s2 = S1(), S2()
    w = make([s1, s2])
    w.screen = lambda: s2
    w._open_settings()
    x, y = moves[0]
    assert s2.geometry().contains(x + 200, y + 300)
