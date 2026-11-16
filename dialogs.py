"""dialogs.py — UI helpers, WelcomeDialog and SettingsDialog for Istari."""

import copy

from PyQt6.QtWidgets import (
    QApplication, QWidget, QDialog, QLabel, QHBoxLayout, QVBoxLayout,
    QSlider, QCheckBox, QPushButton, QComboBox,
    QFrame, QColorDialog, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QPoint, QRect, QRectF
from PyQt6.QtGui  import QColor, QPainter, QPainterPath

from themes import is_high_contrast, THEMES, make_settings_style
from cfg import (
    SENSOR_CATALOG, DEFAULT_CFG,
    save_cfg, default_color,
    is_startup_enabled, set_startup, startup_value, restore_startup_value,
)
from logger import LOG_FILE, get_logger
_log = get_logger("istari.dialogs")

_FONT = "'Bahnschrift','Segoe UI'"
_SCREEN_MARGIN = 24      # space kept free around a dialog that had to be shrunk


def _theme(name: str) -> dict:
    return THEMES.get(name, THEMES["dark"])


def _make_opaque_or_translucent(dlg: QWidget) -> None:
    """Rounded painted panel normally; plain system-palette window in High Contrast."""
    if is_high_contrast():
        dlg.setAutoFillBackground(True)
    else:
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


# ── UI helpers ─────────────────────────────────────────────────────────────────

def hline(color: str, height: int = 1) -> QFrame:
    """Horizontal rule in a theme colour; a native line in High Contrast."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(height)
    if not is_high_contrast():
        line.setStyleSheet(f"background: {color}; color: {color}; border: none;")
    return line


def section_label(text: str, theme: str = "dark") -> QWidget:
    w   = QWidget()
    w.setStyleSheet("background: transparent;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 10, 0, 3)
    lay.setSpacing(8)
    lbl = QLabel(text)
    lbl.setObjectName("section")
    line = hline(_theme(theme)["dlg_sep"])
    lay.addWidget(lbl)
    lay.addWidget(line, 1)
    return w


def slider_row(label: str, lo: int, hi: int, value: int, fmt: str = "{v}%"):
    row   = QHBoxLayout()
    lbl   = QLabel(label)
    lbl.setFixedWidth(110)
    sld   = QSlider(Qt.Orientation.Horizontal)
    sld.setRange(lo, hi)
    sld.setValue(value)
    val_l = QLabel(fmt.format(v=value))
    val_l.setFixedWidth(36)
    val_l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    sld.valueChanged.connect(lambda v, l=val_l, f=fmt: l.setText(f.format(v=v)))
    row.addWidget(lbl)
    row.addWidget(sld)
    row.addWidget(val_l)
    return row, sld, val_l


def dot_btn_style(color: str, theme: str = "dark") -> str:
    t = _theme(theme)
    return (
        f"QPushButton {{ background:{color}; border:2px solid {t['dlg_input_border']};"
        f" border-radius:11px; min-width:0; max-width:22px; padding:0; }}"
        f"QPushButton:hover {{ border-color:{t['dlg_text']}; }}"
    )


def _inline(css: str) -> str:
    """Inline label style; empty in High Contrast so the system palette wins."""
    return "" if is_high_contrast() else css


# ── Settings panel (painted rounded background) ───────────────────────────────

class SPanel(QWidget):
    RADIUS = 18.0

    def __init__(self, parent=None, bg: str = "#0d0e1e", border: str = "#181a38"):
        super().__init__(parent)
        self._bg     = QColor(bg)
        self._border = QColor(border)
        if is_high_contrast():
            self.setAutoFillBackground(True)

    def paintEvent(self, event):
        if is_high_contrast():
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        p.fillPath(path, self._bg)
        p.setPen(self._border)
        p.drawPath(path)
        p.end()


# ── Welcome dialog (shown once on first run) ───────────────────────────────────

class WelcomeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Istari")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        _make_opaque_or_translucent(self)
        self.setFixedWidth(370)
        self._drag_pos: QPoint | None = None
        self.setStyleSheet("" if is_high_contrast() else make_settings_style("dark"))
        self._build()
        self.adjustSize()

    def _build(self):
        t = _theme("dark")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        panel = SPanel(self, bg=t["panel_bg"], border=t["panel_border"])
        root.addWidget(panel)
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(24, 20, 24, 20)
        inner.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        ico = QLabel("⚡")
        ico.setStyleSheet(_inline(
            f"color:{t['dlg_header_ico']}; font:16pt; background:transparent; padding:0;"))
        title = QLabel("ISTARI")
        title.setStyleSheet(_inline(
            f"color:{t['dlg_header_ttl']}; font:bold 10pt {_FONT};"
            " letter-spacing:4px; background:transparent;"
        ))
        hdr.addWidget(ico)
        hdr.addWidget(title)
        hdr.addStretch()
        inner.addLayout(hdr)

        inner.addWidget(hline(t["dlg_sep"]))

        # Body
        def _line(text, small=False, color=t["dlg_text"]):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            sz  = "8pt" if small else "9pt"
            lbl.setStyleSheet(_inline(
                f"color:{color}; font:{sz} {_FONT}; background:transparent;"
            ))
            return lbl

        inner.addWidget(_line("Welcome! Istari reads sensor data from "
                              "<b>MSI Afterburner</b>."))
        inner.addWidget(_line("To see live sensor values:"))

        for bullet in (
            "① Install & launch <b>MSI Afterburner</b>",
            "② Enable <b>Hardware Monitor</b> in Afterburner settings",
            "③ Right-click the overlay to open <b>Settings</b>",
        ):
            row = QHBoxLayout()
            row.setContentsMargins(8, 0, 0, 0)
            row.addWidget(_line(bullet, color=t["dlg_muted"]))
            inner.addLayout(row)

        inner.addWidget(_line(
            "RAM and ping work without Afterburner.",
            small=True, color=t["dlg_muted"],
        ))

        inner.addWidget(hline(t["dlg_sep"]))

        # Footer
        btn = QPushButton("Got it")
        btn.setObjectName("btn_ok")
        btn.setFixedHeight(32)
        btn.clicked.connect(self.accept)
        btn.setDefault(True)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(btn)
        inner.addLayout(footer)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _e):
        self._drag_pos = None

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self.accept()
        else:
            super().keyPressEvent(e)


# ── Settings dialog ────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    HEADER_H = 46
    FOOTER_H = 52

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg               = cfg
        # Working copy of the colour choices: cfg["colors"] is only written by _apply,
        # so Cancel can never leak a half-edited state into the live settings.
        self.picked_colors     = dict(cfg["colors"])
        self._saved_colors     = dict(cfg["colors"])
        self._saved_theme      = cfg.get("theme", "dark")
        self._saved_layout     = cfg.get("layout", "card")
        self._saved_active     = list(cfg.get("active_sensors",
                                              DEFAULT_CFG["active_sensors"]))
        self._active_keys: list[str] = list(self._saved_active)
        self._active_rows: list[dict] = []
        self.color_btns        = {}
        self._drag_pos: QPoint | None = None

        self.setWindowTitle("Settings")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        _make_opaque_or_translucent(self)
        self.setFixedWidth(400)
        self.setStyleSheet(make_settings_style(cfg.get("theme", "dark")))

        self._build()
        self._update_dialog_css()
        self._fit()

    # ── Geometry: never taller than the screen, header/footer always visible ──

    def _screen_rect(self) -> QRect:
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry()

    def _fit(self):
        """Size the dialog to its content, capped to the screen; the body scrolls."""
        self._content.layout().activate()
        content_h = self._content.sizeHint().height()
        err_h = 0
        if not self._error_lbl.isHidden():
            self._error_lbl.setFixedHeight(
                self._error_lbl.heightForWidth(self.width() - 36))
            err_h = self._error_lbl.height()
        chrome = self.HEADER_H + 1 + err_h + 1 + self.FOOTER_H
        avail  = self._screen_rect().height() - 2 * _SCREEN_MARGIN
        body_h = max(80, min(content_h, avail - chrome))
        self._body_scroll.setFixedHeight(body_h)
        self.setFixedHeight(chrome + body_h)

    def _clamp_to_screen(self):
        r, g = self._screen_rect(), self.geometry()
        x = max(r.left(), min(g.x(), r.right() - g.width() + 1))
        y = max(r.top(),  min(g.y(), r.bottom() - g.height() + 1))
        if (x, y) != (g.x(), g.y()):
            self.move(x, y)

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()
        self._clamp_to_screen()

    def keyPressEvent(self, e):
        # QDialog would click the default button (Apply) on Enter from any control,
        # so Enter on a slider or combo box saved and closed. Only a focused
        # button may act on Enter, and then it is that button that fires.
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not isinstance(
                self.focusWidget(), QPushButton):
            e.accept()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _e):
        self._drag_pos = None

    def _make_dot_btn(self, color: str, tooltip: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(22, 22)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(dot_btn_style(color, self.cfg.get("theme", "dark")))
        return btn

    def _build(self):
        theme = self.cfg.get("theme", "dark")
        t = _theme(theme)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._panel = SPanel(self, bg=t["panel_bg"], border=t["panel_border"])
        root.addWidget(self._panel)

        inner = QVBoxLayout(self._panel)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        self._header = hdr = QWidget()
        hdr.setFixedHeight(self.HEADER_H)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 14, 0)
        hl.setSpacing(8)
        ico_lbl = QLabel("⚙")
        ico_lbl.setStyleSheet(_inline(
            f"color:{t['dlg_header_ico']}; font:14pt; background:transparent; padding:0;"))
        ttl_lbl = QLabel("SETTINGS")
        ttl_lbl.setStyleSheet(_inline(
            f"color:{t['dlg_header_ttl']}; font:bold 9pt {_FONT};"
            " letter-spacing:3px; background:transparent;"
        ))
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("btn_close")
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.setAccessibleName("Close settings")
        self.btn_close.clicked.connect(self.reject)
        hl.addWidget(ico_lbl)
        hl.addWidget(ttl_lbl)
        hl.addStretch()
        hl.addWidget(self.btn_close)
        inner.addWidget(hdr)
        inner.addWidget(hline(t["dlg_sep"]))

        # ── Content (the only part that scrolls) ──────────────────────────────
        self._content = content_w = QWidget()
        layout = QVBoxLayout(content_w)
        layout.setSpacing(5)
        layout.setContentsMargins(18, 10, 18, 8)

        self._body_scroll = QScrollArea()
        self._body_scroll.setWidgetResizable(True)
        self._body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # scrolls to the focused control
        self._body_scroll.setWidget(content_w)
        inner.addWidget(self._body_scroll)

        # ── APPEARANCE ────────────────────────────────────────────────────────
        layout.addWidget(section_label("APPEARANCE", theme))

        row_op, self.sld_op, _ = slider_row(
            "Opacity", 20, 100, self.cfg["opacity"])
        self.sld_op.setAccessibleName("Overlay opacity")
        self.sld_op.setAccessibleDescription("Controls the base opacity of the overlay (20–100%)")
        layout.addLayout(row_op)

        row_hv, self.sld_hv, _ = slider_row(
            "Hover Opacity", 5, 80, self.cfg.get("hover_opacity", 20))
        self.sld_hv.setAccessibleName("Hover opacity")
        self.sld_hv.setAccessibleDescription("Opacity when the mouse hovers over the overlay (5–80%)")
        layout.addLayout(row_hv)

        row_sc, self.sld_sc, _ = slider_row(
            "Size", 60, 200, self.cfg.get("scale", 100), fmt="{v}%")
        self.sld_sc.setAccessibleName("Overlay size")
        self.sld_sc.setAccessibleDescription("Scale of the overlay widget (60–200%)")
        layout.addLayout(row_sc)

        row_upd = QHBoxLayout()
        row_upd.addWidget(QLabel("Update Interval"))
        row_upd.addStretch()
        self.cmb = QComboBox()
        self.cmb.setAccessibleName("Update interval")
        self.cmb.setAccessibleDescription("How often sensor data is refreshed")
        for txt, ms in [("500 ms", 500), ("1 Second", 1000),
                        ("2 Seconds", 2000), ("5 Seconds", 5000)]:
            self.cmb.addItem(txt, ms)
        self._saved_update_ms = self.cfg["update_ms"]
        self._set_combo(self.cmb, self._saved_update_ms)
        row_upd.addWidget(self.cmb)
        layout.addLayout(row_upd)

        row_theme = QHBoxLayout()
        row_theme.addWidget(QLabel("Theme"))
        row_theme.addStretch()
        self.cmb_theme = QComboBox()
        self.cmb_theme.setAccessibleName("Theme")
        self.cmb_theme.addItem("Dark",  "dark")
        self.cmb_theme.addItem("Light", "light")
        self._set_combo(self.cmb_theme, self._saved_theme)
        row_theme.addWidget(self.cmb_theme)
        layout.addLayout(row_theme)

        row_layout = QHBoxLayout()
        row_layout.addWidget(QLabel("Layout"))
        row_layout.addStretch()
        self.cmb_layout = QComboBox()
        self.cmb_layout.setAccessibleName("Layout")
        self.cmb_layout.addItem("Card",  "card")
        self.cmb_layout.addItem("Bar",   "bar")
        self._set_combo(self.cmb_layout, self._saved_layout)
        row_layout.addWidget(self.cmb_layout)
        layout.addLayout(row_layout)

        row_pos = QHBoxLayout()
        row_pos.addWidget(QLabel("Position"))
        row_pos.addStretch()
        self.cmb_pos = QComboBox()
        self.cmb_pos.setAccessibleName("Screen position")
        self.cmb_pos.setAccessibleDescription("Pin the overlay to a screen edge, or move it freely by dragging")
        for txt, code in [("Free (drag)", ""),   ("Top Left", "tl"),
                          ("Top Center", "tc"),  ("Top Right", "tr"),
                          ("Bottom Left", "bl"), ("Bottom Center", "bc"),
                          ("Bottom Right", "br")]:
            self.cmb_pos.addItem(txt, code)
        self._saved_anchor = self.cfg.get("anchor", "")
        self._set_combo(self.cmb_pos, self._saved_anchor)
        row_pos.addWidget(self.cmb_pos)
        layout.addLayout(row_pos)

        self.chk_top = QCheckBox("  Always on Top")
        self._saved_top = self.cfg.get("always_on_top", True)
        self.chk_top.setChecked(self._saved_top)
        self.chk_top.setAccessibleName("Always on top")
        self.chk_top.setAccessibleDescription("Keep the overlay above all other windows")
        layout.addWidget(self.chk_top)

        self.chk_startup = QCheckBox("  Launch at Windows startup")
        self._saved_startup = is_startup_enabled()
        self.chk_startup.setChecked(self._saved_startup)
        self.chk_startup.setAccessibleName("Launch at Windows startup")
        self.chk_startup.setAccessibleDescription("Automatically start Istari when Windows boots")
        layout.addWidget(self.chk_startup)

        # ── SENSORS ───────────────────────────────────────────────────────────
        layout.addWidget(section_label("SENSORS", theme))

        hint_row = QHBoxLayout()
        self._hint_lbl = QLabel("Click a dot to change its color")
        # may shrink instead of widening the dialog past its fixed width
        self._hint_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._hint_lbl.setStyleSheet(
            f"font:8pt {_FONT}; padding-bottom:1px; background:transparent;")
        hint_row.addWidget(self._hint_lbl, 1)
        self.btn_last = QPushButton("\u27f3  Last Saved")
        self.btn_last.setObjectName("btn_reset")
        self.btn_last.setFixedHeight(20)
        self.btn_last.setToolTip(
            "Undo every change made in this window (settings, sensors and colors)")
        self.btn_last.setAccessibleName("Revert to last saved settings")
        self.btn_last.clicked.connect(self._revert_saved)
        hint_row.addWidget(self.btn_last)
        hint_row.addSpacing(4)
        self.btn_default = QPushButton("\u21ba  Default")
        self.btn_default.setObjectName("btn_reset")
        self.btn_default.setFixedHeight(20)
        self.btn_default.setToolTip(
            "Reset sensor colors to the original defaults (other settings, "
            "including the theme, are not changed)")
        self.btn_default.setAccessibleName("Reset colors to default")
        self.btn_default.clicked.connect(self._reset_colors)
        hint_row.addWidget(self.btn_default)
        layout.addLayout(hint_row)

        # ── Active-sensor list (grows with the content; the body scrolls) ─────
        self._sensor_list_widget = QWidget()
        self._sensor_list_widget.setStyleSheet("background: transparent;")
        self._sensor_list_layout = QVBoxLayout(self._sensor_list_widget)
        self._sensor_list_layout.setContentsMargins(0, 2, 0, 2)
        self._sensor_list_layout.setSpacing(2)
        layout.addWidget(self._sensor_list_widget)

        # ── Add sensor row ─────────────────────────────────────────────────────
        layout.addSpacing(4)
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 2, 0, 0)
        add_row.setSpacing(6)
        self._add_combo = QComboBox()
        self._add_combo.setMinimumWidth(140)
        self._add_combo.setAccessibleName("Select sensor to add")
        self._add_combo.setAccessibleDescription("Choose a sensor from the list to add to the overlay")
        self._populate_add_combo()
        self.btn_add = QPushButton("+ Add")
        self.btn_add.setObjectName("btn_add")
        self.btn_add.setFixedHeight(28)
        self.btn_add.setAccessibleName("Add sensor")
        self.btn_add.setAccessibleDescription("Add the selected sensor to the overlay")
        self.btn_add.clicked.connect(self._add_sensor)
        add_row.addWidget(self._add_combo)
        add_row.addWidget(self.btn_add)
        add_row.addStretch()
        layout.addLayout(add_row)

        # ── Error line (hidden until a save fails) ─────────────────────────────
        self._error_lbl = QLabel()
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setAccessibleName("Error")
        self._error_lbl.setContentsMargins(18, 4, 18, 4)
        self._error_lbl.setStyleSheet(_inline(
            f"color:{t['dlg_remove']}; font:8pt {_FONT}; background:transparent;"))
        self._error_lbl.hide()
        inner.addWidget(self._error_lbl)

        # ── Footer separator + buttons ────────────────────────────────────────
        inner.addWidget(hline(t["dlg_sep"]))

        self._footer = footer_w = QWidget()
        footer_w.setFixedHeight(self.FOOTER_H)
        fl = QHBoxLayout(footer_w)
        fl.setContentsMargins(18, 0, 18, 0)
        fl.addStretch()
        self.btn_cancel = QPushButton("  Cancel  ")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_cancel.setAccessibleName("Cancel")
        self.btn_cancel.setToolTip("Discard changes and close (Esc)")
        self.btn_ok = QPushButton("  Apply  ")
        self.btn_ok.setObjectName("btn_ok")
        self.btn_ok.clicked.connect(self._apply)
        self.btn_ok.setAccessibleName("Apply settings")
        self.btn_ok.setToolTip("Save and apply settings")
        self.btn_ok.setDefault(True)
        fl.addWidget(self.btn_cancel)
        fl.addSpacing(8)
        fl.addWidget(self.btn_ok)
        inner.addWidget(footer_w)

        self._rebuild_sensor_list()

    @staticmethod
    def _set_combo(cmb: QComboBox, data):
        cmb.setCurrentIndex(max(0, cmb.findData(data)))

    # ── Tab order ──────────────────────────────────────────────────────────────

    def _refresh_tab_order(self):
        """Reading order: settings, reset buttons, sensor rows, add, then Cancel/Apply."""
        if not hasattr(self, "btn_ok"):
            return                          # still building
        chain = [self.sld_op, self.sld_hv, self.sld_sc, self.cmb, self.cmb_theme,
                 self.cmb_layout, self.cmb_pos, self.chk_top, self.chk_startup,
                 self.btn_last, self.btn_default]
        for row in self._active_rows:
            chain += [row["color_btn"], row["remove_btn"]]
        chain += [self._add_combo, self.btn_add, self.btn_cancel, self.btn_ok,
                  self.btn_close]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

    # ── Sensor list management ─────────────────────────────────────────────────

    def _populate_add_combo(self):
        self._add_combo.clear()
        for key, s in SENSOR_CATALOG.items():
            if key not in self._active_keys:
                unit_str = f"  [{s.unit}]" if s.unit else ""
                self._add_combo.addItem(f"{s.label}{unit_str}", key)
        has_items = self._add_combo.count() > 0
        self._add_combo.setEnabled(has_items)
        if not has_items:
            self._add_combo.addItem("All sensors added")

    def _add_sensor(self):
        key = self._add_combo.currentData()
        if key and key not in self._active_keys:
            self._active_keys.append(key)
            self._rebuild_sensor_list()
            self._populate_add_combo()

    def _remove_sensor(self, key: str):
        if key in self._active_keys:
            self._active_keys.remove(key)
            self._rebuild_sensor_list()
            self._populate_add_combo()

    def _rebuild_sensor_list(self):
        while self._sensor_list_layout.count():
            item = self._sensor_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)        # leaves the focus chain now, not at deleteLater
                w.deleteLater()
        self._active_rows.clear()
        self.color_btns.clear()
        theme = self.cfg.get("theme", "dark")

        for key in self._active_keys:
            s = SENSOR_CATALOG.get(key)
            if s is None:
                continue
            cur_color = self.picked_colors.get(key, s.color)
            row_w = QWidget()
            row_w.setStyleSheet("background: transparent;")
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(2, 1, 2, 1)
            rl.setSpacing(6)

            cbtn = self._make_dot_btn(cur_color, f"Change {s.label} color")
            cbtn.setAccessibleName(f"{s.label} color")
            cbtn.setAccessibleDescription(f"Click to change the color for {s.label}")
            cbtn.clicked.connect(lambda _, k=key, b=cbtn: self._pick_color(k, b))

            text = s.label + (f"  \u2022  {s.unit}" if s.unit else "")
            name_lbl = QLabel(text)

            rm_btn = QPushButton("× Remove")
            rm_btn.setObjectName("btn_remove")
            rm_btn.setFixedHeight(26)
            rm_btn.setToolTip(f"Remove {s.label}")
            rm_btn.setAccessibleName(f"Remove {s.label}")
            rm_btn.clicked.connect(lambda _, k=key: self._remove_sensor(k))

            rl.addWidget(cbtn)
            rl.addWidget(name_lbl)
            rl.addStretch()
            rl.addWidget(rm_btn)
            self._sensor_list_layout.addWidget(row_w)

            self._active_rows.append(
                {"key": key, "color_btn": cbtn, "remove_btn": rm_btn})
            self.color_btns[key] = cbtn

        self._refresh_tab_order()
        if hasattr(self, "btn_ok"):          # after the first build: resize to fit
            self._fit()
            if self.isVisible():
                self._clamp_to_screen()

    # ── Dynamic stylesheet ────────────────────────────────────────────────────

    def _update_dialog_css(self):
        if is_high_contrast():
            self.setStyleSheet("")
            self._hint_lbl.setStyleSheet("")
        else:
            theme = self.cfg.get("theme", "dark")
            self.setStyleSheet(make_settings_style(theme))
            t = _theme(theme)
            self._hint_lbl.setStyleSheet(
                f"color:{t['dlg_muted']}; font:8pt {_FONT};"
                " padding-bottom:1px; background:transparent;"
            )

    # ── Color pickers ─────────────────────────────────────────────────────────

    def _dot_style(self, color: str) -> str:
        return dot_btn_style(color, self.cfg.get("theme", "dark"))

    def _pick_color(self, key: str, btn: QPushButton):
        current = self.picked_colors.get(key, default_color(key))
        c = QColorDialog.getColor(QColor(current), self, "Pick Color")
        if c.isValid():
            hex_c = c.name()
            self.picked_colors[key] = hex_c
            btn.setStyleSheet(self._dot_style(hex_c))

    def _paint_dots(self):
        for row in self._active_rows:
            s = SENSOR_CATALOG.get(row["key"])
            fallback = s.color if s else "#e8e8e8"
            row["color_btn"].setStyleSheet(
                self._dot_style(self.picked_colors.get(row["key"], fallback)))

    def _revert_saved(self):
        """Put every control back to what it was when the window opened."""
        self.sld_op.setValue(self.cfg["opacity"])
        self.sld_hv.setValue(self.cfg.get("hover_opacity", 20))
        self.sld_sc.setValue(self.cfg.get("scale", 100))
        self._set_combo(self.cmb, self._saved_update_ms)
        self._set_combo(self.cmb_theme, self._saved_theme)
        self._set_combo(self.cmb_layout, self._saved_layout)
        self._set_combo(self.cmb_pos, self._saved_anchor)
        self.chk_top.setChecked(self._saved_top)
        self.chk_startup.setChecked(self._saved_startup)
        self.picked_colors = dict(self._saved_colors)
        self._active_keys = list(self._saved_active)
        self._rebuild_sensor_list()
        self._populate_add_combo()

    def _reset_colors(self):
        """Sensor colors back to the catalogue defaults. Nothing else changes."""
        self.picked_colors = {}
        self._paint_dots()

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _show_error(self, text: str):
        self._error_lbl.setText(text.replace("\\", "\\\u200b"))   # allow wrapping paths
        self._error_lbl.setVisible(bool(text))
        self._fit()
        if self.isVisible():
            self._clamp_to_screen()

    def _apply(self):
        self._show_error("")
        want_startup = self.chk_startup.isChecked()
        prev_startup = is_startup_enabled()
        prev_startup_value = startup_value()   # exact string, restored if the save fails
        if want_startup != prev_startup and not set_startup(want_startup):
            # Windows refused the change; show what is actually registered.
            self.chk_startup.setChecked(is_startup_enabled())
            self._show_error(
                f"Could not change the Windows startup setting, see the log at {LOG_FILE}.")
            return

        before = copy.deepcopy(self.cfg)
        self.cfg["opacity"]       = self.sld_op.value()
        self.cfg["hover_opacity"] = self.sld_hv.value()
        self.cfg["scale"]         = self.sld_sc.value()
        self.cfg["update_ms"]     = self.cmb.currentData()
        self.cfg["always_on_top"] = self.chk_top.isChecked()
        self.cfg["theme"]  = self.cmb_theme.currentData()
        self.cfg["layout"] = self.cmb_layout.currentData()
        self.cfg["anchor"] = self.cmb_pos.currentData()
        self.cfg["active_sensors"] = list(self._active_keys)
        self.cfg["visible"] = {key: True for key in self._active_keys}
        self.cfg["colors"] = {k: v for k, v in self.picked_colors.items()
                              if k in self._active_keys}
        # save_cfg returns False on failure; older builds returned None for success.
        if save_cfg(self.cfg) is False:
            self.cfg.clear()
            self.cfg.update(before)          # the live settings must not claim a save
            if want_startup != prev_startup and not restore_startup_value(prev_startup_value):
                _log.error("Could not restore the Windows startup entry after a failed save.")
            self.chk_startup.setChecked(is_startup_enabled())
            self._show_error(f"Could not save settings, see the log at {LOG_FILE}.")
            return
        self.accept()
