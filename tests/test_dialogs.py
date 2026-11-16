"""tests/test_dialogs.py — SettingsDialog / WelcomeDialog behaviour and theme contrast."""

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Contrast helpers (WCAG 2.x) ───────────────────────────────────────────────

def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# (foreground token, background tokens, minimum ratio)
_TEXT = 4.5
_UI = 3.0
_PAIRS = [
    # text, WCAG 1.4.3
    ("dlg_text",       ("panel_bg", "dlg_input_bg", "dlg_btn_bg", "dlg_btn_hover", "dlg_sel_bg"), _TEXT),
    ("dlg_muted",      ("panel_bg", "dlg_input_bg", "dlg_btn_bg", "dlg_btn_hover", "dlg_sel_bg"), _TEXT),
    ("dlg_section",    ("panel_bg",), _TEXT),
    ("dlg_header_ttl", ("panel_bg",), _TEXT),
    ("dlg_accent",     ("dlg_btn_bg", "dlg_btn_hover"), _TEXT),
    ("dlg_add",        ("dlg_btn_bg", "dlg_btn_hover"), _TEXT),
    ("dlg_remove",     ("dlg_btn_bg", "dlg_btn_hover", "panel_bg"), _TEXT),
    ("title",          ("bg",), _TEXT),
    ("src",            ("bg",), _TEXT),
    ("menu_text",      ("bg", "menu_hover_bg"), _TEXT),
    ("menu_hover_text", ("menu_hover_bg",), _TEXT),
    # UI components and graphics, WCAG 1.4.11
    ("dlg_header_ico",   ("panel_bg",), _UI),
    ("gear",             ("bg",), _UI),
    ("dlg_input_border", ("panel_bg", "dlg_input_bg", "dlg_btn_bg"), _UI),
    ("dlg_groove",       ("panel_bg",), _UI),
    ("dlg_accent",       ("panel_bg",), _UI),
    ("dlg_scroll_handle", ("dlg_scrollbar",), _UI),
]


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("fg,bgs,need", _PAIRS)
def test_palette_meets_wcag_aa(theme, fg, bgs, need):
    from themes import THEMES
    t = THEMES[theme]
    for bg in bgs:
        got = ratio(t[fg], t[bg])
        assert got >= need, f"{theme}: {fg} {t[fg]} on {bg} {t[bg]} is {got:.2f}:1, need {need}"


# ── Qt fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp_instance():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def cfg():
    from cfg import DEFAULT_CFG
    return copy.deepcopy(DEFAULT_CFG)


@pytest.fixture
def dialogs(qapp_instance, monkeypatch):
    """dialogs module with the registry and the settings file stubbed out."""
    import dialogs as d
    monkeypatch.setattr(d, "save_cfg", lambda c: True)
    monkeypatch.setattr(d, "set_startup", lambda e: True)
    monkeypatch.setattr(d, "is_startup_enabled", lambda: False)
    return d


def _tall_screen(monkeypatch, dialogs, h=2000):
    from PyQt6.QtCore import QRect
    monkeypatch.setattr(dialogs.SettingsDialog, "_screen_rect",
                        lambda self: QRect(0, 0, 1920, h))


# ── UI-1: edits stay in the dialog until Apply ────────────────────────────────

def test_cancel_after_default_keeps_live_colors(dialogs, cfg):
    cfg["colors"] = {"fps": "#123456"}
    dlg = dialogs.SettingsDialog(cfg)
    dlg._reset_colors()
    dlg.reject()
    assert cfg["colors"] == {"fps": "#123456"}


def test_cancel_after_add_remove_keeps_visible_and_sensors(dialogs, cfg):
    before_visible = copy.deepcopy(cfg["visible"])
    before_active = list(cfg["active_sensors"])
    dlg = dialogs.SettingsDialog(cfg)
    dlg._remove_sensor("fps")
    dlg._add_sensor()
    assert cfg["visible"] == before_visible
    dlg.reject()
    assert cfg["visible"] == before_visible
    assert cfg["active_sensors"] == before_active


def test_last_saved_does_not_touch_cfg_colors(dialogs, cfg):
    cfg["colors"] = {"fps": "#123456"}
    dlg = dialogs.SettingsDialog(cfg)
    dlg._reset_colors()
    dlg._revert_saved()
    assert cfg["colors"] == {"fps": "#123456"}


# ── UI-2: height clamp ────────────────────────────────────────────────────────

def test_dialog_fits_a_short_screen(dialogs, cfg, monkeypatch):
    from PyQt6.QtCore import QRect
    screen = QRect(0, 0, 1366, 560)
    monkeypatch.setattr(dialogs.SettingsDialog, "_screen_rect", lambda self: screen)
    dlg = dialogs.SettingsDialog(cfg)
    dlg.move(-50, -300)
    dlg.show()
    assert screen.contains(dlg.frameGeometry()), dlg.frameGeometry()
    # header and footer stay visible; the body is what scrolls
    assert dlg._body_scroll.verticalScrollBar().maximum() > 0
    assert dlg._footer.isVisible() and dlg._header.isVisible()
    dlg.close()


def test_dialog_keeps_natural_height_on_a_tall_screen(dialogs, cfg, monkeypatch):
    _tall_screen(monkeypatch, dialogs)
    dlg = dialogs.SettingsDialog(cfg)
    dlg.show()
    assert dlg._body_scroll.verticalScrollBar().maximum() == 0
    dlg.close()


# ── UI-4: High Contrast gets an opaque system background ──────────────────────

@pytest.mark.parametrize("make", ["settings", "welcome"])
def test_high_contrast_dialogs_are_opaque(dialogs, cfg, monkeypatch, make):
    from PyQt6.QtCore import Qt
    monkeypatch.setattr(dialogs, "is_high_contrast", lambda: True)
    _tall_screen(monkeypatch, dialogs)
    dlg = dialogs.SettingsDialog(cfg) if make == "settings" else dialogs.WelcomeDialog()
    assert not dlg.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert dlg.autoFillBackground()
    dlg.show()
    img = dlg.grab().toImage()
    assert (img.pixel(5, img.height() // 2) >> 24) & 0xFF == 0xFF
    dlg.close()


def test_normal_mode_keeps_translucent_corners(dialogs, cfg):
    from PyQt6.QtCore import Qt
    dlg = dialogs.SettingsDialog(cfg)
    assert dlg.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dlg.close()


# ── UI-5: tab order and accessible names ──────────────────────────────────────

def _focus_ring(dlg):
    from PyQt6.QtCore import Qt
    start = dlg.sld_op
    ring, w = [start], start.nextInFocusChain()
    while w is not start and len(ring) < 200:
        if w.isVisibleTo(dlg) and w.focusPolicy() & Qt.FocusPolicy.TabFocus:
            ring.append(w)
        w = w.nextInFocusChain()
    return ring


def test_tab_order_is_logical(dialogs, cfg, monkeypatch, qapp_instance):
    from PyQt6.QtWidgets import QPushButton
    _tall_screen(monkeypatch, dialogs)
    dlg = dialogs.SettingsDialog(cfg)
    dlg.show()
    dlg._remove_sensor("ram")      # rebuilt rows must stay in order
    qapp_instance.processEvents()
    ring = _focus_ring(dlg)
    i_combo = ring.index(dlg._add_combo)
    assert ring[i_combo + 1].accessibleName() == "Add sensor"
    names = [w.accessibleName() for w in ring if isinstance(w, QPushButton)]
    # Cancel, Apply come after every sensor row and the add controls
    assert names.index("Cancel") > names.index("Add sensor")
    assert names.index("Cancel") > max(i for i, n in enumerate(names) if n.startswith("Remove"))
    assert names.index("Apply settings") == names.index("Cancel") + 1
    # the reset buttons sit before the sensor rows they act on
    assert names.index("Reset colors to default") < min(
        i for i, n in enumerate(names) if n.startswith("Remove"))
    dlg.close()


def test_theme_and_layout_combos_have_accessible_names(dialogs, cfg):
    dlg = dialogs.SettingsDialog(cfg)
    assert dlg.cmb_theme.accessibleName() == "Theme"
    assert dlg.cmb_layout.accessibleName() == "Layout"
    dlg.close()


# ── UI-6: save failures are reported ──────────────────────────────────────────

def test_save_failure_keeps_dialog_open_and_names_the_log(dialogs, cfg, monkeypatch):
    from logger import LOG_FILE
    monkeypatch.setattr(dialogs, "save_cfg", lambda c: False)
    dlg = dialogs.SettingsDialog(cfg)
    dlg.show()
    dlg.sld_op.setValue(33)
    dlg._apply()
    assert dlg.result() != dlg.DialogCode.Accepted
    assert dlg.isVisible()
    assert dlg._error_lbl.isVisible()
    assert "save" in dlg._error_lbl.text().lower()
    assert LOG_FILE.replace("\u200b", "") in dlg._error_lbl.text().replace("\u200b", "")
    assert cfg["opacity"] != 33, "a failed save must not leave the live cfg changed"
    dlg.close()


def test_startup_failure_keeps_dialog_open(dialogs, cfg, monkeypatch):
    monkeypatch.setattr(dialogs, "set_startup", lambda e: False)
    dlg = dialogs.SettingsDialog(cfg)
    dlg.show()
    dlg.chk_startup.setChecked(True)
    dlg._apply()
    assert dlg.isVisible()
    assert dlg._error_lbl.isVisible()
    assert "startup" in dlg._error_lbl.text().lower()
    assert dlg.chk_startup.isChecked() is False
    dlg.close()


def test_none_from_save_cfg_still_counts_as_success(dialogs, cfg, monkeypatch):
    monkeypatch.setattr(dialogs, "save_cfg", lambda c: None)
    dlg = dialogs.SettingsDialog(cfg)
    dlg._apply()
    assert dlg.result() == dlg.DialogCode.Accepted


def test_successful_apply_closes(dialogs, cfg):
    dlg = dialogs.SettingsDialog(cfg)
    dlg.sld_op.setValue(55)
    dlg._apply()
    assert dlg.result() == dlg.DialogCode.Accepted
    assert cfg["opacity"] == 55


# ── UI-7: a removed sensor's colour is not saved ──────────────────────────────

def test_removed_sensor_colour_is_not_saved(dialogs, cfg):
    dlg = dialogs.SettingsDialog(cfg)
    dlg.picked_colors["fps"] = "#abcdef"
    dlg.picked_colors["cpu_temp"] = "#fedcba"
    dlg._remove_sensor("fps")
    dlg._apply()
    assert "fps" not in cfg["colors"]
    assert cfg["colors"].get("cpu_temp") == "#fedcba"


# ── UI-8: Default / Last Saved ────────────────────────────────────────────────

def test_default_resets_colours_but_not_the_theme(dialogs, cfg):
    cfg["theme"] = "light"
    dlg = dialogs.SettingsDialog(cfg)
    dlg._reset_colors()
    assert dlg.cmb_theme.currentData() == "light"
    assert "colour" in dlg.btn_default.toolTip().lower() or "color" in dlg.btn_default.toolTip().lower()


def test_default_resets_picked_and_saved_colours_on_apply(dialogs, cfg):
    cfg["colors"] = {"fps": "#123456"}
    dlg = dialogs.SettingsDialog(cfg)
    dlg._reset_colors()
    dlg._apply()
    assert cfg["colors"] == {}


def test_last_saved_reverts_sliders_and_combos(dialogs, cfg):
    dlg = dialogs.SettingsDialog(cfg)
    base = (cfg["opacity"], cfg["hover_opacity"], cfg["scale"])
    dlg.sld_op.setValue(30)
    dlg.sld_hv.setValue(10)
    dlg.sld_sc.setValue(150)
    dlg.cmb_theme.setCurrentIndex(1)
    dlg.cmb_layout.setCurrentIndex(1)
    dlg.cmb_pos.setCurrentIndex(2)
    dlg.chk_top.setChecked(not cfg["always_on_top"])
    dlg._revert_saved()
    assert (dlg.sld_op.value(), dlg.sld_hv.value(), dlg.sld_sc.value()) == base
    assert dlg.cmb_theme.currentData() == cfg["theme"]
    assert dlg.cmb_layout.currentData() == cfg["layout"]
    assert dlg.cmb_pos.currentData() == cfg["anchor"]
    assert dlg.chk_top.isChecked() == cfg["always_on_top"]


def test_last_saved_reverts_colours_and_sensor_list(dialogs, cfg):
    cfg["colors"] = {"fps": "#123456"}
    dlg = dialogs.SettingsDialog(cfg)
    dlg.picked_colors["fps"] = "#ffffff"
    dlg._remove_sensor("fps")
    dlg._revert_saved()
    assert "fps" in dlg._active_keys
    dlg._apply()
    assert cfg["colors"] == {"fps": "#123456"}
    assert "fps" in cfg["active_sensors"]


# ── UI-9: the sensor list is not clipped ──────────────────────────────────────

@pytest.mark.parametrize("n", [3, 6, 7, 16])
def test_sensor_rows_are_fully_visible(dialogs, cfg, monkeypatch, n):
    from cfg import SENSOR_CATALOG
    _tall_screen(monkeypatch, dialogs, 3000)
    cfg["active_sensors"] = list(SENSOR_CATALOG)[:n]
    dlg = dialogs.SettingsDialog(cfg)
    dlg.show()
    assert dlg._body_scroll.verticalScrollBar().maximum() == 0
    need = dlg._sensor_list_widget.sizeHint().height()
    assert dlg._sensor_list_widget.height() >= need
    dlg.close()


# ── UI-11: no dark literals on the Light theme ────────────────────────────────

def test_light_theme_uses_theme_tokens_for_rules_and_dots(dialogs):
    from themes import THEMES
    t = THEMES["light"]
    from PyQt6.QtWidgets import QFrame
    w = dialogs.section_label("X", "light")
    rule = [f for f in w.findChildren(QFrame)
            if f.frameShape() == QFrame.Shape.HLine][0]
    assert t["dlg_sep"] in rule.styleSheet()
    css = dialogs.dot_btn_style("#ff0000", "light")
    assert t["dlg_input_border"] in css
    assert "#2a2a50" not in css


def test_no_hardcoded_dark_literals_left_in_dialogs():
    src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "dialogs.py"),
               encoding="utf-8").read().lower()
    for lit in ("#1e1e3c", "#2a2a50", "#1c1e3c", "#b0b0d0", "#9090c8", "#8080e0"):
        assert lit not in src, lit


# ── UI-12: Enter on a non-button control does not apply ──────────────────────

def test_enter_on_a_slider_does_not_apply(dialogs, cfg, qapp_instance):
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtGui import QKeyEvent
    dlg = dialogs.SettingsDialog(cfg)
    dlg.show()
    dlg.sld_op.setFocus()
    dlg.sld_op.setValue(44)
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    qapp_instance.sendEvent(dlg.sld_op, ev)
    assert dlg.result() != dlg.DialogCode.Accepted
    assert cfg["opacity"] != 44
    dlg.close()


def test_apply_is_still_the_default_button(dialogs, cfg):
    from PyQt6.QtWidgets import QPushButton
    dlg = dialogs.SettingsDialog(cfg)
    defaults = [b for b in dlg.findChildren(QPushButton) if b.isDefault()]
    assert [b.accessibleName() for b in defaults] == ["Apply settings"]


def test_escape_still_cancels(dialogs, cfg, qapp_instance):
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtGui import QKeyEvent
    dlg = dialogs.SettingsDialog(cfg)
    dlg.show()
    qapp_instance.sendEvent(dlg, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                           Qt.KeyboardModifier.NoModifier))
    assert dlg.result() == dlg.DialogCode.Rejected


# ── UI-14: copy ───────────────────────────────────────────────────────────────

def test_sensor_hint_is_a_sentence(dialogs, cfg):
    dlg = dialogs.SettingsDialog(cfg)
    assert dlg._hint_lbl.text() == "Click a dot to change its color"
    dlg.close()


def test_rui1_failed_save_restores_the_startup_entry(dialogs, cfg, monkeypatch):
    state = {"on": False}
    calls = []

    def set_startup(enabled):
        calls.append(enabled)
        state["on"] = enabled
        return True
    monkeypatch.setattr(dialogs, "set_startup", set_startup)
    monkeypatch.setattr(dialogs, "is_startup_enabled", lambda: state["on"])
    monkeypatch.setattr(dialogs, "startup_value", lambda: "x" if state["on"] else None)

    def restore(prev):
        calls.append(prev is not None)
        state["on"] = prev is not None
        return True
    monkeypatch.setattr(dialogs, "restore_startup_value", restore)
    monkeypatch.setattr(dialogs, "save_cfg", lambda c: False)
    dlg = dialogs.SettingsDialog(cfg)
    dlg.chk_startup.setChecked(True)
    dlg._apply()
    assert calls == [True, False]
    assert state["on"] is False
    assert dlg.chk_startup.isChecked() is False
    assert dlg._error_lbl.text()


def test_r2_3_failed_save_restores_the_original_startup_string(dialogs, cfg, monkeypatch):
    old = '"C:/old/Istari.exe" --flag'
    restored = []
    monkeypatch.setattr(dialogs, "set_startup", lambda enabled: True)
    monkeypatch.setattr(dialogs, "is_startup_enabled", lambda: True)
    monkeypatch.setattr(dialogs, "startup_value", lambda: old, raising=False)
    monkeypatch.setattr(dialogs, "restore_startup_value",
                        lambda v: restored.append(v) or True, raising=False)
    monkeypatch.setattr(dialogs, "save_cfg", lambda c: False)
    dlg = dialogs.SettingsDialog(cfg)
    dlg.chk_startup.setChecked(False)
    dlg._apply()
    assert restored == [old]
