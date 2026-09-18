"""dialogs.py — UI helpers, WelcomeDialog and SettingsDialog for Istari."""

from PyQt6.QtWidgets import (
    QWidget, QDialog, QLabel, QHBoxLayout, QVBoxLayout,
    QSlider, QCheckBox, QPushButton, QComboBox,
    QFrame, QColorDialog, QScrollArea,
)
from PyQt6.QtCore import Qt, QPoint, QRectF
from PyQt6.QtGui  import QColor, QPainter, QPainterPath

from themes import is_high_contrast, THEMES, make_settings_style
from cfg import (
    SENSOR_CATALOG, DEFAULT_CFG,
    save_cfg, default_color,
    is_startup_enabled, set_startup,
)


# ── UI helpers ─────────────────────────────────────────────────────────────────

def section_label(text: str) -> QWidget:
    w   = QWidget()
    w.setStyleSheet("background: transparent;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 10, 0, 3)
    lay.setSpacing(8)
    lbl = QLabel(text)
    lbl.setObjectName("section")
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #1e1e3c;")
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


def dot_btn_style(color: str) -> str:
    return (
        f"QPushButton {{ background:{color}; border:2px solid #2a2a50;"
        f" border-radius:11px; min-width:0; max-width:22px; padding:0; }}"
        "QPushButton:hover { border-color:#ffffff; }"
    )


# ── Settings panel (painted rounded background) ───────────────────────────────

class SPanel(QWidget):
    RADIUS = 18.0

    def __init__(self, parent=None, bg: str = "#0d0e1e", border: str = "#181a38"):
        super().__init__(parent)
        self._bg     = QColor(bg)
        self._border = QColor(border)

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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(370)
        self._drag_pos: QPoint | None = None
        self.setStyleSheet(make_settings_style("dark"))
        self._build()
        self.adjustSize()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        panel = SPanel(self)
        root.addWidget(panel)
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(24, 20, 24, 20)
        inner.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        ico = QLabel("⚡")
        ico.setStyleSheet("color:#6474f0; font:16pt; background:transparent; padding:0;")
        title = QLabel("ISTARI")
        title.setStyleSheet(
            "color:#8080e0; font:bold 10pt 'Bahnschrift','Segoe UI';"
            " letter-spacing:4px; background:transparent;"
        )
        hdr.addWidget(ico)
        hdr.addWidget(title)
        hdr.addStretch()
        inner.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#1c1e3c;")
        inner.addWidget(sep)

        # Body
        def _line(text, small=False):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            sz  = "8pt" if small else "9pt"
            lbl.setStyleSheet(
                f"color:#b0b0d0; font:{sz} 'Bahnschrift','Segoe UI';"
                " background:transparent;"
            )
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
            lbl = QLabel(bullet)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                "color:#9090c8; font:9pt 'Bahnschrift','Segoe UI';"
                " background:transparent;"
            )
            row.addWidget(lbl)
            inner.addLayout(row)

        inner.addWidget(_line(
            "RAM and ping work without Afterburner.",
            small=True,
        ))

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background:#1a1a32;")
        inner.addWidget(sep2)

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
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg               = cfg
        self.picked_colors     = {}
        self._saved_colors     = dict(cfg["colors"])
        self._saved_theme      = cfg.get("theme", "dark")
        self._saved_layout     = cfg.get("layout", "card")
        self._saved_visible    = dict(cfg.get("visible", {}))
        self._active_keys: list[str] = list(cfg.get("active_sensors",
            DEFAULT_CFG["active_sensors"]))
        self._active_rows: list[dict] = []
        self.color_btns        = {}
        self._drag_pos: QPoint | None = None

        self.setWindowTitle("Settings")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(400)
        self.setStyleSheet(make_settings_style(cfg.get("theme", "dark")))

        self._build()
        self._update_dialog_css()
        self.adjustSize()

    def reject(self):
        self.cfg["visible"] = self._saved_visible
        super().reject()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._apply()
        elif e.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
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
        btn.setStyleSheet(dot_btn_style(color))
        return btn

    def _build(self):
        t = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._panel = SPanel(self, bg=t["panel_bg"], border=t["panel_border"])
        root.addWidget(self._panel)

        inner = QVBoxLayout(self._panel)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(46)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 14, 0)
        hl.setSpacing(8)
        ico_lbl = QLabel("⚙")
        ico_lbl.setStyleSheet(
            f"color:{t['dlg_header_ico']}; font:14pt; background:transparent; padding:0;")
        ttl_lbl = QLabel("SETTINGS")
        ttl_lbl.setStyleSheet(
            f"color:{t['dlg_header_ttl']}; font:bold 9pt 'Bahnschrift','Segoe UI';"
            " letter-spacing:3px; background:transparent;"
        )
        btn_close = QPushButton("✕")
        btn_close.setObjectName("btn_close")
        btn_close.setFixedSize(26, 26)
        btn_close.setAccessibleName("Close settings")
        btn_close.clicked.connect(self.reject)
        hl.addWidget(ico_lbl)
        hl.addWidget(ttl_lbl)
        hl.addStretch()
        hl.addWidget(btn_close)
        inner.addWidget(hdr)

        sep_hdr = QWidget()
        sep_hdr.setFixedHeight(1)
        sep_hdr.setStyleSheet(f"background: {t['dlg_sep']};")
        inner.addWidget(sep_hdr)

        # ── Content ───────────────────────────────────────────────────────────
        content_w = QWidget()
        layout = QVBoxLayout(content_w)
        layout.setSpacing(5)
        layout.setContentsMargins(18, 10, 18, 8)
        inner.addWidget(content_w)

        # ── APPEARANCE ────────────────────────────────────────────────────────
        layout.addWidget(section_label("APPEARANCE"))

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
        for i in range(self.cmb.count()):
            if self.cmb.itemData(i) == self.cfg["update_ms"]:
                self.cmb.setCurrentIndex(i); break
        row_upd.addWidget(self.cmb)
        layout.addLayout(row_upd)

        row_theme = QHBoxLayout()
        row_theme.addWidget(QLabel("Theme"))
        row_theme.addStretch()
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItem("Dark",  "dark")
        self.cmb_theme.addItem("Light", "light")
        idx = self.cmb_theme.findData(self.cfg.get("theme", "dark"))
        self.cmb_theme.setCurrentIndex(max(0, idx))
        row_theme.addWidget(self.cmb_theme)
        layout.addLayout(row_theme)

        row_layout = QHBoxLayout()
        row_layout.addWidget(QLabel("Layout"))
        row_layout.addStretch()
        self.cmb_layout = QComboBox()
        self.cmb_layout.addItem("Card",  "card")
        self.cmb_layout.addItem("Bar",   "bar")
        idx_lay = self.cmb_layout.findData(self.cfg.get("layout", "card"))
        self.cmb_layout.setCurrentIndex(max(0, idx_lay))
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
        idx_pos = self.cmb_pos.findData(self.cfg.get("anchor", ""))
        self.cmb_pos.setCurrentIndex(max(0, idx_pos))
        row_pos.addWidget(self.cmb_pos)
        layout.addLayout(row_pos)

        self.chk_top = QCheckBox("  Always on Top")
        self.chk_top.setChecked(self.cfg.get("always_on_top", True))
        self.chk_top.setAccessibleName("Always on top")
        self.chk_top.setAccessibleDescription("Keep the overlay above all other windows")
        layout.addWidget(self.chk_top)

        self.chk_startup = QCheckBox("  Launch at Windows startup")
        self.chk_startup.setChecked(is_startup_enabled())
        self.chk_startup.setAccessibleName("Launch at Windows startup")
        self.chk_startup.setAccessibleDescription("Automatically start Istari when Windows boots")
        layout.addWidget(self.chk_startup)

        # ── SENSORS ───────────────────────────────────────────────────────────
        layout.addWidget(section_label("SENSORS"))

        hint_row = QHBoxLayout()
        self._hint_lbl = QLabel("Sensor color \u2192 click dot")
        self._hint_lbl.setStyleSheet(
            "font:8pt 'Bahnschrift','Segoe UI'; padding-bottom:1px; background:transparent;")
        hint_row.addWidget(self._hint_lbl)
        hint_row.addStretch()
        btn_last = QPushButton("\u27f3  Last Saved")
        btn_last.setObjectName("btn_reset")
        btn_last.setFixedHeight(20)
        btn_last.setToolTip("Revert to last applied colors")
        btn_last.setAccessibleName("Revert to last saved colors")
        btn_last.clicked.connect(self._revert_saved)
        hint_row.addWidget(btn_last)
        hint_row.addSpacing(4)
        btn_default = QPushButton("\u21ba  Default")
        btn_default.setObjectName("btn_reset")
        btn_default.setFixedHeight(20)
        btn_default.setToolTip("Reset all colors to original defaults")
        btn_default.setAccessibleName("Reset colors to default")
        btn_default.clicked.connect(self._reset_colors)
        hint_row.addWidget(btn_default)
        layout.addLayout(hint_row)

        # ── Scrollable active-sensor list ─────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._sensor_list_widget = QWidget()
        self._sensor_list_widget.setStyleSheet("background: transparent;")
        self._sensor_list_layout = QVBoxLayout(self._sensor_list_widget)
        self._sensor_list_layout.setContentsMargins(0, 2, 4, 2)
        self._sensor_list_layout.setSpacing(2)
        self._scroll.setWidget(self._sensor_list_widget)
        self._scroll.setMinimumHeight(50)
        self._scroll.setMaximumHeight(220)
        layout.addWidget(self._scroll)

        self._rebuild_sensor_list()

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
        btn_add = QPushButton("+ Add")
        btn_add.setObjectName("btn_add")
        btn_add.setFixedHeight(28)
        btn_add.setAccessibleName("Add sensor")
        btn_add.setAccessibleDescription("Add the selected sensor to the overlay")
        btn_add.clicked.connect(self._add_sensor)
        add_row.addWidget(self._add_combo)
        add_row.addWidget(btn_add)
        add_row.addStretch()
        layout.addLayout(add_row)

        # ── Footer separator + buttons ────────────────────────────────────────
        sep_ftr = QWidget()
        sep_ftr.setFixedHeight(1)
        sep_ftr.setStyleSheet(f"background: {t['dlg_sep']};")
        inner.addWidget(sep_ftr)

        footer_w = QWidget()
        footer_w.setFixedHeight(52)
        fl = QHBoxLayout(footer_w)
        fl.setContentsMargins(18, 0, 18, 0)
        fl.addStretch()
        btn_cancel = QPushButton("  Cancel  ")
        btn_cancel.clicked.connect(self.reject)
        btn_cancel.setAccessibleName("Cancel")
        btn_cancel.setToolTip("Discard changes and close (Esc)")
        btn_ok = QPushButton("  Apply  ")
        btn_ok.setObjectName("btn_ok")
        btn_ok.clicked.connect(self._apply)
        btn_ok.setAccessibleName("Apply settings")
        btn_ok.setToolTip("Save and apply settings (Enter)")
        btn_ok.setDefault(True)
        fl.addWidget(btn_cancel)
        fl.addSpacing(8)
        fl.addWidget(btn_ok)
        inner.addWidget(footer_w)

        # ── Tab order ─────────────────────────────────────────────────────────
        QWidget.setTabOrder(self.sld_op,    self.sld_hv)
        QWidget.setTabOrder(self.sld_hv,    self.sld_sc)
        QWidget.setTabOrder(self.sld_sc,    self.cmb)
        QWidget.setTabOrder(self.cmb,        self.cmb_theme)
        QWidget.setTabOrder(self.cmb_theme,  self.cmb_layout)
        QWidget.setTabOrder(self.cmb_layout, self.cmb_pos)
        QWidget.setTabOrder(self.cmb_pos,    self.chk_top)
        QWidget.setTabOrder(self.chk_top,   self.chk_startup)
        QWidget.setTabOrder(self.chk_startup, self._add_combo)
        QWidget.setTabOrder(self._add_combo,  btn_cancel)
        QWidget.setTabOrder(btn_cancel,       btn_ok)

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
            self.cfg["visible"][key] = True
            self._rebuild_sensor_list()
            self._populate_add_combo()

    def _remove_sensor(self, key: str):
        if key in self._active_keys:
            self._active_keys.remove(key)
            self.cfg["visible"].pop(key, None)
            self._rebuild_sensor_list()
            self._populate_add_combo()

    def _rebuild_sensor_list(self):
        while self._sensor_list_layout.count():
            item = self._sensor_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._active_rows.clear()
        self.color_btns.clear()

        for key in self._active_keys:
            s = SENSOR_CATALOG.get(key)
            if s is None:
                continue
            cur_color = self.picked_colors.get(
                key, self.cfg["colors"].get(key, s.color))
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

            entry = {"key": key, "color_btn": cbtn}
            self._active_rows.append(entry)
            self.color_btns[key] = cbtn

        self._sensor_list_layout.addStretch()

        row_h  = 28
        needed = max(50, min(len(self._active_keys) * row_h + 8, 230))
        self._scroll.setMinimumHeight(needed)
        self._scroll.setMaximumHeight(max(needed, 230))

    # ── Dynamic stylesheet ────────────────────────────────────────────────────

    def _update_dialog_css(self):
        if is_high_contrast():
            self.setStyleSheet("")
            self._hint_lbl.setStyleSheet("")
        else:
            theme = self.cfg.get("theme", "dark")
            self.setStyleSheet(make_settings_style(theme))
            t = THEMES.get(theme, THEMES["dark"])
            self._hint_lbl.setStyleSheet(
                f"color:{t['dlg_muted']}; font:8pt 'Bahnschrift','Segoe UI';"
                " padding-bottom:1px; background:transparent;"
            )

    # ── Color pickers ─────────────────────────────────────────────────────────

    def _pick_color(self, key: str, btn: QPushButton):
        current = self.picked_colors.get(key, self.cfg["colors"].get(key, default_color(key)))
        c = QColorDialog.getColor(QColor(current), self, "Pick Color")
        if c.isValid():
            hex_c = c.name()
            self.picked_colors[key] = hex_c
            btn.setStyleSheet(dot_btn_style(hex_c))

    def _revert_saved(self):
        self.cfg["colors"] = dict(self._saved_colors)
        self.picked_colors = {}
        idx = self.cmb_theme.findData(self._saved_theme)
        self.cmb_theme.setCurrentIndex(max(0, idx))
        idx_lay = self.cmb_layout.findData(self._saved_layout)
        self.cmb_layout.setCurrentIndex(max(0, idx_lay))
        for row in self._active_rows:
            key = row["key"]
            s   = SENSOR_CATALOG.get(key)
            cur = self._saved_colors.get(key, s.color if s else "#e8e8e8")
            row["color_btn"].setStyleSheet(dot_btn_style(cur))

    def _reset_colors(self):
        self.cfg["colors"] = {}
        self.picked_colors = {}
        self.cmb_theme.setCurrentIndex(max(0, self.cmb_theme.findData("dark")))
        for row in self._active_rows:
            s = SENSOR_CATALOG.get(row["key"])
            row["color_btn"].setStyleSheet(dot_btn_style(s.color if s else "#e8e8e8"))

    def _apply(self):
        self.cfg["opacity"]       = self.sld_op.value()
        self.cfg["hover_opacity"] = self.sld_hv.value()
        self.cfg["scale"]         = self.sld_sc.value()
        self.cfg["update_ms"]     = self.cmb.currentData()
        self.cfg["always_on_top"] = self.chk_top.isChecked()
        if not set_startup(self.chk_startup.isChecked()):
            # Windows refused the change; show what is actually registered
            # instead of leaving the box claiming a state that is not there.
            self.chk_startup.setChecked(is_startup_enabled())
        self.cfg["theme"] = self.cmb_theme.currentData()
        self.cfg["layout"] = self.cmb_layout.currentData()
        self.cfg["anchor"] = self.cmb_pos.currentData()
        self.cfg["active_sensors"] = list(self._active_keys)
        self.cfg["visible"] = {key: True for key in self._active_keys}
        for key, hex_c in self.picked_colors.items():
            self.cfg["colors"][key] = hex_c
        save_cfg(self.cfg)
        self.accept()
