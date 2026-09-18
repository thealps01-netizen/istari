#!/usr/bin/env python3
"""istari.py — ISTARI hardware monitor overlay (UI + entry point)."""

import sys, os, time, ctypes
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout,
    QPushButton, QMenu, QSystemTrayIcon,
)
from PyQt6.QtCore import (
    Qt, QPoint, QRectF, QTimer, QPropertyAnimation, QEasingCurve, QThread,
    QParallelAnimationGroup,
)
from PyQt6.QtGui  import QIcon, QPainter, QPainterPath, QPen, QColor, QFont, QRegion

import crash_handler
crash_handler.install()

from logger import get_logger, LOG_DIR
_log = get_logger("istari")

from hw      import get_data, HardwareWorker
from updater import UpdateChecker, prompt_and_install
from themes  import is_high_contrast, THEMES, make_widget_css, build_menu_css
from dialogs import WelcomeDialog, SettingsDialog

# ── GitHub repo — update these before each release ────────────────────────────
_GITHUB_OWNER = "thealps01-netizen"
_GITHUB_REPO  = "istari"                 # ← repo name
from cfg import (
    SENSOR_CATALOG, SETTINGS_FILE,
    load_cfg, save_cfg, eff_color, default_color,
    active_sensor_defs,
    is_startup_enabled, set_startup, purge_dead_legacy_startup,
)



# ── Main widget ────────────────────────────────────────────────────────────────
class Istari(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg            = load_cfg()
        self._drag_pos      = QPoint()
        self._press_pos     = QPoint()
        self._cells         = {}
        self._prev_vals     = {}
        self._last_src      = None
        self._home_pos      = None
        self._sliding       = False
        self._slide_anim    = None
        self._quitting      = False

        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._apply_widget_css()
        self.setWindowOpacity(self.cfg["opacity"] / 100)

        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(350)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._build()

        if self.cfg.get("anchor"):
            self.adjustSize()
            self._apply_anchor()
        elif self.cfg["pos_x"] >= 0:
            x, y = self.cfg["pos_x"], self.cfg["pos_y"]
            cx, cy = x + self.width() // 2, y + self.height() // 2
            if any(s.geometry().contains(cx, cy) for s in QApplication.screens()):
                self.move(x, y)
            else:
                scr = QApplication.primaryScreen().availableGeometry()
                self.move(scr.width() - self.width() - 20, 20)
        else:
            scr = QApplication.primaryScreen().geometry()
            self.adjustSize()
            self.move(scr.width() - self.width() - 20, 20)

        # ── Background hardware worker (non-blocking) ──────────────────────────
        self._hw_worker = HardwareWorker(
            active_sensor_defs(self.cfg),
            interval_ms=self.cfg["update_ms"],
        )
        self._hw_thread = QThread(self)
        self._hw_worker.moveToThread(self._hw_thread)
        self._hw_thread.started.connect(self._hw_worker.run)
        self._hw_worker.data_ready.connect(self._on_data)
        self._hw_thread.start()
        self._start_time = time.monotonic()
        _log.info("Istari started.")

        self._tray = self._setup_tray()

        # ── Heartbeat log every 10 minutes ────────────────────────────────────
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(10 * 60 * 1000)
        self._heartbeat_timer.timeout.connect(self._log_heartbeat)
        self._heartbeat_timer.start()

        # ── MAHM connectivity check (45s — warn if no sensor data yet) ──────────
        QTimer.singleShot(45_000, self._check_mahm_connected)

        # ── Background update check (30s delay — don't slow down startup) ──────
        QTimer.singleShot(30_000, self._check_for_updates)

    # ── System tray ───────────────────────────────────────────────────────────
    def _setup_tray(self):
        tray = QSystemTrayIcon(self)
        ico  = _icon_path()
        if os.path.exists(ico):
            tray.setIcon(QIcon(ico))
        tray.setToolTip("Istari")

        menu = QMenu()
        act_settings = menu.addAction("\u2699  Settings")
        act_updates  = menu.addAction("\u27f3  Check for Updates")
        menu.addSeparator()
        act_quit = menu.addAction("\u2715  Quit Istari")

        act_settings.triggered.connect(self._open_settings)
        act_updates.triggered.connect(lambda: self._check_for_updates(manual=True))
        act_quit.triggered.connect(self._quit)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _log_heartbeat(self) -> None:
        elapsed = time.monotonic() - self._start_time
        h, rem  = divmod(int(elapsed), 3600)
        m       = rem // 60
        _log.info("app alive — uptime %dh%02dm", h, m)

    def _check_mahm_connected(self) -> None:
        """Warn via tray if MSI Afterburner hasn't delivered any data yet."""
        if self._last_src in (None, "N/A"):
            _log.warning("No sensor data after 45s — MSI Afterburner may not be running.")
            self._tray.showMessage(
                "Istari — No Sensor Data",
                "MSI Afterburner does not appear to be running.\n"
                "Launch Afterburner to enable live sensor data.",
                QSystemTrayIcon.MessageIcon.Warning,
                6000,
            )

    def _check_for_updates(self, manual: bool = False) -> None:
        if getattr(self, "_updater_running", False):
            return   # already checking
        self._updater_running = True
        self._updater = UpdateChecker(_GITHUB_OWNER, _GITHUB_REPO, parent=self)
        self._updater.update_available.connect(
            lambda tag, url, notes: self._on_update_available(tag, url, notes)
        )
        if manual:
            self._updater.no_update.connect(self._on_no_update)
            self._updater.check_failed.connect(self._on_check_failed)
        self._updater.no_update.connect(lambda: setattr(self, "_updater_running", False))
        self._updater.check_failed.connect(lambda: setattr(self, "_updater_running", False))
        self._updater.update_available.connect(lambda *_: setattr(self, "_updater_running", False))
        self._updater.start()

    def _on_update_available(self, tag: str, url: str, notes: str) -> None:
        prompt_and_install(tag, url, notes, parent=self)

    def _on_no_update(self) -> None:
        self._tray.showMessage(
            "Istari",
            "You're up to date! No new version available.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def _on_check_failed(self) -> None:
        self._tray.showMessage(
            "Istari",
            "Could not reach the update server. Check your connection.",
            QSystemTrayIcon.MessageIcon.Warning,
            4000,
        )

    def _quit(self):
        _log.info("Istari shutting down.")
        self._quitting = True
        if self.isVisible():
            self._play_outro()
        else:
            self._actual_quit()

    def _actual_quit(self):
        self._hw_worker.stop()
        self._hw_thread.quit()
        self._hw_thread.wait(2000)
        self._tray.hide()
        QApplication.instance().quit()

    def _play_outro(self):
        """Slide down and fade out on quit."""
        self._anim.stop()
        cfg_opacity = self.cfg["opacity"] / 100
        self.setWindowOpacity(cfg_opacity)
        start = self.pos()
        end   = QPoint(start.x(), start.y() + 30)

        pos_anim = QPropertyAnimation(self, b"pos")
        pos_anim.setDuration(400)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(end)
        pos_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        fade_anim = QPropertyAnimation(self, b"windowOpacity")
        fade_anim.setDuration(400)
        fade_anim.setStartValue(cfg_opacity)
        fade_anim.setEndValue(0.0)
        fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        self._outro_group = QParallelAnimationGroup(self)
        self._outro_group.addAnimation(pos_anim)
        self._outro_group.addAnimation(fade_anim)
        self._outro_group.start()
        QTimer.singleShot(420, self._actual_quit)

    # ── Tray left-click: slide overlay down/up ────────────────────────────────
    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_overlay()

    def _toggle_overlay(self):
        if self._sliding:
            return
        if self.isVisible():
            self._home_pos = self.pos()
            self._slide_out()
        else:
            self._slide_in()

    def _slide_out(self):
        self._sliding = True
        scr  = (QApplication.screenAt(self.pos()) or QApplication.primaryScreen()).availableGeometry()
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(280)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(self.x(), scr.bottom() + self.height()))
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        def _done():
            self.hide()
            self._sliding = False
        anim.finished.connect(_done)
        self._slide_anim = anim
        anim.start()

    def _play_intro(self):
        """Slide down from above and fade in on startup."""
        target = self.pos()
        start  = QPoint(target.x(), target.y() - 30)
        self.move(start)
        self.setWindowOpacity(0.0)

        pos_anim = QPropertyAnimation(self, b"pos")
        pos_anim.setDuration(500)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(target)
        pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        fade_anim = QPropertyAnimation(self, b"windowOpacity")
        fade_anim.setDuration(500)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(self.cfg["opacity"] / 100)
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._intro_group = QParallelAnimationGroup(self)
        self._intro_group.addAnimation(pos_anim)
        self._intro_group.addAnimation(fade_anim)
        self._intro_group.start()

    def _slide_in(self):
        self._sliding = True
        _target_pos = self._home_pos or (
            QPoint(self.cfg["pos_x"], self.cfg["pos_y"]) if self.cfg.get("pos_x", -1) >= 0 else None
        )
        scr = (
            (QApplication.screenAt(_target_pos) if _target_pos else None)
            or QApplication.primaryScreen()
        ).availableGeometry()
        target = _target_pos if _target_pos is not None else QPoint(scr.width() - self.width() - 20, 20)
        self.move(target.x(), scr.bottom() + self.height())
        self.show()
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(280)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        def _done():
            self._sliding = False
        anim.finished.connect(_done)
        self._slide_anim = anim
        anim.start()

    def _apply_widget_css(self):
        if not is_high_contrast():
            self.setStyleSheet(make_widget_css(
                self.cfg.get("theme", "dark"), self.cfg.get("layout", "card")
            ))
        self._apply_corner_mask()

    def _apply_corner_mask(self):
        """Clip the window to the CSS border-radius.

        QSS border-radius alone leaves the corner pixels outside the rounded
        rect unpainted (black artifacts, visible over light backgrounds after
        the overlay is moved). A window mask cuts them off for real.
        """
        if is_high_contrast():
            self.clearMask()
            return
        radius = 18.0 if self.cfg.get("layout", "card") == "card" else 10.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_corner_mask()

    def _s(self, px: int) -> int:
        """Scale a pixel value by the current scale factor."""
        return max(1, round(px * self.cfg.get("scale", 100) / 100))

    def _sp(self, pt: int) -> int:
        """Scale a font point size by the current scale factor."""
        return max(6, round(pt * self.cfg.get("scale", 100) / 100))

    def _apply_window_flags(self):
        flags = (Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.Tool)
        if self.cfg.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    # ── Screen anchor (pin position presets) ──────────────────────────────────
    ANCHOR_LABELS = [
        ("Free (drag)",   ""),
        ("Top Left",      "tl"),
        ("Top Center",    "tc"),
        ("Top Right",     "tr"),
        ("Bottom Left",   "bl"),
        ("Bottom Center", "bc"),
        ("Bottom Right",  "br"),
    ]

    def _apply_anchor(self, save: bool = False):
        """Snap the widget to the configured screen-edge preset."""
        a = self.cfg.get("anchor", "")
        if not a:
            return
        scr = (QApplication.screenAt(self.pos())
               or QApplication.primaryScreen()).availableGeometry()
        m = 16
        w, h = self.width(), self.height()
        if   a[1] == "l": x = scr.left() + m
        elif a[1] == "c": x = scr.left() + (scr.width() - w) // 2
        else:             x = scr.left() + scr.width() - w - m
        y = scr.top() + m if a[0] == "t" else scr.top() + scr.height() - h - m
        self.move(x, y)
        self._home_pos = self.pos()
        self.cfg["pos_x"], self.cfg["pos_y"] = self.x(), self.y()
        if save:
            save_cfg(self.cfg)

    def _set_anchor(self, preset: str):
        self.cfg["anchor"] = preset
        if preset:
            self.adjustSize()
            self._apply_anchor(save=True)
        else:
            save_cfg(self.cfg)
        _log.info("Anchor set to %r", preset)

    def _apply_no_activate(self):
        """Set WS_EX_NOACTIVATE so the overlay never steals focus from games."""
        try:
            GWL_EXSTYLE      = -20
            WS_EX_NOACTIVATE = 0x08000000
            hwnd = int(self.winId())
            cur  = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cur | WS_EX_NOACTIVATE)
        except Exception as e:
            # Losing this silently means the overlay starts stealing focus from
            # the game — the one behaviour that must never regress unnoticed.
            _log.warning("WS_EX_NOACTIVATE could not be applied (%s: %s) — "
                         "the overlay may steal focus", type(e).__name__, e)

    # ── Hover animation ───────────────────────────────────────────────────────
    def enterEvent(self, e):
        super().enterEvent(e)
        if not self._quitting:
            self._fade_to(self.cfg.get("hover_opacity", 20) / 100)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        if not self._quitting:
            self._fade_to(self.cfg["opacity"] / 100)

    def _fade_to(self, target):
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(target)
        self._anim.start()

    # ── Layout ────────────────────────────────────────────────────────────────
    def _clear_layout(self):
        """Tear down the current layout and all of its child widgets."""
        layout = self.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()
            elif item.layout():
                self._clear_sub_layout(item.layout())
        QWidget().setLayout(layout)

    def _clear_sub_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()
            elif item.layout():
                self._clear_sub_layout(item.layout())

    def _build(self):
        self._clear_layout()
        self._cells.clear()
        self._prev_vals.clear()
        # Card-only widgets — None in bar mode
        self._title_lbl = None
        self._src_lbl   = None
        self._sep = self._sep2 = None
        self._gap1 = self._gap2 = self._gap3 = None
        self._title_row_layout = None
        self._bar_seps = []

        if self.cfg.get("layout", "card") == "bar":
            self._build_bar()
        else:
            self._build_card()

    def _build_card(self):
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setSpacing(0)
        self._root_layout.setContentsMargins(self._s(18), self._s(14), self._s(18), self._s(14))

        self._title_row_layout = QHBoxLayout()
        self._title_row_layout.setContentsMargins(0, 0, 0, self._s(10))
        self._title_lbl = QLabel("ISTARI")
        self._gear = QLabel("\u22ee")
        self._gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gear.setToolTip("Settings")
        self._title_row_layout.addWidget(self._title_lbl)
        self._title_row_layout.addStretch()
        self._title_row_layout.addWidget(self._gear)
        self._root_layout.addLayout(self._title_row_layout)

        self._sep = QWidget()
        self._sep.setFixedHeight(1)
        self._root_layout.addWidget(self._sep)
        self._gap1 = QWidget(); self._gap1.setFixedHeight(self._s(9))
        self._root_layout.addWidget(self._gap1)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._root_layout.addWidget(self._rows_container)

        self._gap2 = QWidget(); self._gap2.setFixedHeight(self._s(9))
        self._root_layout.addWidget(self._gap2)
        self._sep2 = QWidget()
        self._sep2.setFixedHeight(1)
        self._root_layout.addWidget(self._sep2)
        self._gap3 = QWidget(); self._gap3.setFixedHeight(self._s(4))
        self._root_layout.addWidget(self._gap3)

        self._src_lbl = QLabel("connecting...")
        self._src_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._root_layout.addWidget(self._src_lbl)

        self._rebuild_sensors()
        self._apply_theme()

    def _build_bar(self):
        self._root_layout = QHBoxLayout(self)
        self._root_layout.setSpacing(0)
        self._root_layout.setContentsMargins(self._s(10), self._s(5), self._s(6), self._s(5))

        self._rows_container = QWidget()
        self._rows_layout = QHBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._root_layout.addWidget(self._rows_container)

        self._gear = QLabel("\u22ee")
        self._gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gear.setToolTip("Settings")
        self._root_layout.addWidget(self._gear)

        self._rebuild_sensors()
        self._apply_theme()

    def _rebuild_sensors(self):
        """Tear down and recreate all sensor row widgets from cfg['active_sensors']."""
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cells.clear()
        self._prev_vals.clear()
        self._bar_seps = []

        is_bar = self.cfg.get("layout", "card") == "bar"
        sensors = active_sensor_defs(self.cfg)

        if is_bar:
            for i, s in enumerate(sensors):
                color = eff_color(self.cfg, s.key)
                if i > 0:
                    sep = QWidget()
                    sep.setFixedSize(self._s(1), self._s(16))
                    _t = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])
                    sep.setStyleSheet(f"background:{_t['sep']};")
                    self._rows_layout.addWidget(sep)
                    self._bar_seps.append(sep)

                cell_w = QWidget()
                cl = QHBoxLayout(cell_w)
                cl.setContentsMargins(self._s(8), 0, self._s(8), 0)
                cl.setSpacing(self._s(4))

                desc_lbl = QLabel(s.label)
                desc_lbl.setStyleSheet(
                    f"color:{color}; font:bold {self._sp(7)}pt 'Bahnschrift','Segoe UI';")

                val_lbl = QLabel("---")
                val_lbl.setFixedWidth(self._s(40))
                val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                val_lbl.setStyleSheet(
                    f"color:{color}; font:bold {self._sp(9)}pt 'Bahnschrift',Consolas;")

                cl.addWidget(desc_lbl)
                cl.addWidget(val_lbl)
                self._rows_layout.addWidget(cell_w)
                self._cells[s.key] = (cell_w, None, val_lbl, None, 0, s.unit, s.bar_max, desc_lbl)
        else:
            for s in sensors:
                color = eff_color(self.cfg, s.key)
                row_w = QWidget()
                row_w.setFixedHeight(self._s(28))
                rl = QHBoxLayout(row_w)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(self._s(9))

                dot = QLabel("\u25cf")
                dot.setFixedWidth(self._s(10))
                dot.setStyleSheet(f"color:{color}; font:{self._sp(7)}pt; padding:0;")

                desc = QLabel(s.label)
                desc.setFixedWidth(self._s(68))
                desc.setStyleSheet(f"color:{color}; font:bold {self._sp(8)}pt 'Bahnschrift','Segoe UI';")

                bar_bg = QWidget()
                bar_bg.setFixedSize(self._s(76), self._s(5))
                _t = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])
                bar_bg.setStyleSheet(f"background:{_t['bar_bg']}; border-radius:3px;")

                bar_fill = QWidget(bar_bg)
                bar_fill.setFixedHeight(self._s(5))
                bar_fill.setFixedWidth(0)
                bar_fill.setStyleSheet(f"background:{color}; border-radius:3px;")

                val_lbl = QLabel("---")
                val_lbl.setFixedWidth(self._s(52))
                val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                val_lbl.setStyleSheet(f"color:{color}; font:bold {self._sp(11)}pt 'Bahnschrift',Consolas;")

                rl.addWidget(dot)
                rl.addWidget(desc)
                rl.addWidget(bar_bg)
                rl.addWidget(val_lbl)
                self._rows_layout.addWidget(row_w)
                self._cells[s.key] = (row_w, dot, val_lbl, bar_fill, self._s(76), s.unit, s.bar_max, desc)

        self._apply_visibility()
        self.adjustSize()

    def _apply_visibility(self):
        for key, (row_w, *_) in self._cells.items():
            row_w.setVisible(self.cfg["visible"].get(key, True))
        self.adjustSize()

    def _apply_theme(self):
        if is_high_contrast():
            return
        t = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])
        is_bar = self.cfg.get("layout", "card") == "bar"
        if self._title_lbl:
            self._title_lbl.setStyleSheet(
                f"color:{t['title']}; font:bold {self._sp(8)}pt 'Bahnschrift','Segoe UI'; letter-spacing:2px;"
            )
        if self._src_lbl:
            self._src_lbl.setStyleSheet(f"color:{t['src']}; font:{self._sp(7)}pt 'Bahnschrift','Segoe UI';")
        if is_bar:
            self._gear.setStyleSheet(
                f"color:{t['gear']}; font:{self._sp(12)}pt; padding:0 {self._s(4)}px;")
        else:
            self._gear.setStyleSheet(
                f"color:{t['gear']}; font:{self._sp(14)}pt; padding:0 2px; margin-top:-2px;")
        if self._sep:
            self._sep.setStyleSheet(f"background:{t['sep']};")
        if self._sep2:
            self._sep2.setStyleSheet(f"background:{t['sep']};")
        for sep in self._bar_seps:
            sep.setStyleSheet(f"background:{t['sep']};")

    def _apply_colors(self):
        is_bar = self.cfg.get("layout", "card") == "bar"
        for key, (row_w, dot, val_lbl, bar_fill, _, unit, mx, desc) in self._cells.items():
            c = eff_color(self.cfg, key)
            if dot:
                dot.setStyleSheet(f"color:{c}; font:{self._sp(7)}pt; padding:0;")
            if bar_fill:
                bar_fill.setStyleSheet(f"background:{c}; border-radius:2px;")
            if is_bar:
                val_lbl.setStyleSheet(f"color:{c}; font:bold {self._sp(9)}pt 'Bahnschrift',Consolas;")
                desc.setStyleSheet(f"color:{c}; font:bold {self._sp(7)}pt 'Bahnschrift','Segoe UI';")
            else:
                val_lbl.setStyleSheet(f"color:{c}; font:bold {self._sp(11)}pt 'Bahnschrift',Consolas;")
                desc.setStyleSheet(f"color:{c}; font:bold {self._sp(8)}pt 'Bahnschrift','Segoe UI';")

    def _apply_outer_layout(self):
        """Update outer margins and spacings for the current scale."""
        if self.cfg.get("layout", "card") == "bar":
            self._root_layout.setContentsMargins(
                self._s(10), self._s(5), self._s(6), self._s(5))
        else:
            self._root_layout.setContentsMargins(
                self._s(18), self._s(14), self._s(18), self._s(14))
            if self._title_row_layout:
                self._title_row_layout.setContentsMargins(0, 0, 0, self._s(10))
            if self._gap1:
                self._gap1.setFixedHeight(self._s(9))
            if self._gap2:
                self._gap2.setFixedHeight(self._s(9))
            if self._gap3:
                self._gap3.setFixedHeight(self._s(4))

    # ── Settings ──────────────────────────────────────────────────────────────
    def _open_settings(self):
        old_layout = self.cfg.get("layout", "card")
        dlg = SettingsDialog(self.cfg, self)
        dlg.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        dlg.move(
            screen.x() + (screen.width()  - dlg.width())  // 2,
            screen.y() + (screen.height() - dlg.height()) // 2,
        )
        if dlg.exec():
            layout_changed = old_layout != self.cfg.get("layout", "card")
            self._apply_widget_css()
            self.setWindowOpacity(self.cfg["opacity"] / 100)
            self._hw_worker.set_interval(self.cfg["update_ms"])
            self._hw_worker.set_sensors(active_sensor_defs(self.cfg))
            if layout_changed:
                self._build()
            else:
                self._apply_outer_layout()
                self._rebuild_sensors()
                self._apply_colors()
                self._apply_theme()
            self._apply_window_flags()
            self.show()
            # setWindowFlags() recreates the native window — WS_EX_NOACTIVATE
            # must be re-applied or the overlay starts stealing focus from games.
            self._apply_no_activate()
            self._rows_layout.activate()
            self._root_layout.activate()
            self.setMinimumSize(0, 0)
            self.adjustSize()
            self._apply_anchor()   # keep pinned position after size changes
            _log.info("Settings applied (interval=%dms, scale=%d%%, layout=%s, sensors=%s)",
                      self.cfg["update_ms"], self.cfg.get("scale", 100),
                      self.cfg.get("layout", "card"), self.cfg["active_sensors"])

    # ── Context menu ──────────────────────────────────────────────────────────
    def _make_menu_css(self):
        t = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])
        return build_menu_css(
            t["bg"], t["menu_text"], t["menu_hover_text"],
            t["menu_hover_bg"], t["menu_border"], t["menu_sep"],
        )

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setStyleSheet(self._make_menu_css())
        act_set  = menu.addAction("  \u2699  Settings")
        act_upd  = menu.addAction("  \u27f3  Check for Updates")
        menu.addSeparator()
        pos_menu = menu.addMenu("  \U0001F4CC  Position")
        pos_menu.setStyleSheet(self._make_menu_css())
        cur_anchor = self.cfg.get("anchor", "")
        anchor_acts = {}
        for label, code in self.ANCHOR_LABELS:
            mark = "\u25cf" if code == cur_anchor else "\u25cb"
            anchor_acts[pos_menu.addAction(f"  {mark}  {label}")] = code
        if self.cfg.get("locked"):
            act_lock = menu.addAction("  \U0001F513  Unlock")
        else:
            act_lock = menu.addAction("  \U0001F512  Lock")
        menu.addSeparator()
        act_quit = menu.addAction("  \u2715  Quit")
        action = menu.exec(e.globalPos())
        if   action == act_set:  self._open_settings()
        elif action == act_upd:  self._check_for_updates(manual=True)
        elif action in anchor_acts:
            self._set_anchor(anchor_acts[action])
        elif action == act_lock:
            self.cfg["locked"] = not self.cfg.get("locked", False)
            save_cfg(self.cfg)
        elif action == act_quit: self._quit()

    def closeEvent(self, e):
        """Ignore external close requests — only _quit() may close the overlay."""
        if getattr(self, '_quitting', False):
            e.accept()
        else:
            e.ignore()

    # ── Drag to move ──────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._gear.geometry().contains(e.pos()):
                self._open_settings()
                return
            if not self.cfg.get("locked"):
                self._drag_pos = (
                    e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                self._press_pos = self.pos()

    def mouseMoveEvent(self, e):
        if (
            e.buttons() == Qt.MouseButton.LeftButton
            and not self.cfg.get("locked")
            and not self._drag_pos.isNull()
        ):
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton
                and not self._drag_pos.isNull()
                and self.pos() != getattr(self, "_press_pos", self.pos())):
            # Only a real drag (position changed) saves pos and unpins the anchor;
            # a plain click must not reset the position preset.
            self.cfg["pos_x"] = self.x()
            self.cfg["pos_y"] = self.y()
            self.cfg["anchor"] = ""   # manual drag switches back to free positioning
            self._home_pos = self.pos()
            save_cfg(self.cfg)
        self._drag_pos = QPoint()

    # ── Data slot (called from HardwareWorker signal, UI thread via Qt signal) ──
    def _on_data(self, data: dict, maxes: dict, src: str):
        try:
            if src != self._last_src:
                if self._src_lbl:
                    self._src_lbl.setText(src)
                self._last_src = src
            for key, (row_w, dot, val_lbl, bar_fill, bar_w, unit, bar_max, desc) in self._cells.items():
                v = data.get(key)
                if v is None:
                    text, w = "  N/A", 0
                else:
                    if unit == "MHz":
                        text = f"{v / 1000:.1f}G"
                    elif unit == "V":
                        text = f"{v:.2f}V"
                    else:
                        text = f"{v:.0f}{unit}"
                    dyn_max = maxes.get(key) or bar_max
                    w = max(int(bar_w * min(v / dyn_max, 1.0)), 0) if bar_w else 0
                if self._prev_vals.get(key) != (text, w):
                    val_lbl.setText(text)
                    if bar_fill:
                        bar_fill.setFixedWidth(w)
                    self._prev_vals[key] = (text, w)
        except Exception as e:
            _log.error("UI update error: %s", e)


# ── Splash screen ─────────────────────────────────────────────────────────────
class SplashScreen(QWidget):
    """Startup spinner drawn in the middle of the screen."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(160, 160)

        scr = QApplication.primaryScreen().geometry()
        self.move(
            scr.x() + (scr.width()  - 160) // 2,
            scr.y() + (scr.height() - 160) // 2,
        )

        self._angle    = 0
        self._callback = None
        self._held     = False

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(16)
        self._tick_timer.timeout.connect(self._tick)

    def start(self, callback):
        self._callback = callback
        self.show()
        self._tick_timer.start()

    def _tick(self):
        self._angle = min(self._angle + 5, 360)
        self.update()
        if self._angle >= 360 and not self._held:
            self._held = True
            self._tick_timer.stop()
            QTimer.singleShot(150, self._fade_out)

    def _fade_out(self):
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(250)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        def _done():
            self.close()
            if self._callback:
                self._callback()
        anim.finished.connect(_done)
        self._fade_anim = anim
        anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy, r = 80, 80, 54

        p.fillRect(self.rect(), QColor(8, 9, 22))

        # Arka plan dairesi
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(8, 9, 22))
        p.drawEllipse(cx - r - 14, cy - r - 14, (r + 14) * 2, (r + 14) * 2)

        # Track
        track_pen = QPen(QColor(25, 27, 55), 5)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Progress arc
        arc_pen = QPen(QColor(100, 116, 240), 5)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arc_pen)
        p.drawArc(cx - r, cy - r, r * 2, r * 2,
                  90 * 16, -int(self._angle * 16))

        # Metin
        p.setPen(QPen(QColor(160, 165, 210)))
        font = QFont("Bahnschrift", 8)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "ISTARI")

        p.end()


# ── Entry point ────────────────────────────────────────────────────────────────
def _icon_path():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "istari.ico")


if __name__ == "__main__":
    import ctypes as _ct

    # ── Windows App User Model ID — proper taskbar grouping & pin support ────
    try:
        _ct.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "thealps01-netizen.Istari"
        )
    except Exception:
        pass

    # ── Single-instance guard ──────────────────────────────────────────────────
    _mutex = _ct.windll.kernel32.CreateMutexW(None, False, "IstariSingleInstanceMutex")
    if _ct.windll.kernel32.GetLastError() == 183:
        _log.warning("Another instance is already running. Exiting.")
        sys.exit(0)

    # ── High DPI (Windows 11 / mixed-DPI multi-monitor) ───────────────────────
    from PyQt6.QtCore import Qt as _Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        _Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    _log.info("Starting Istari (Python %s)", sys.version.split()[0])

    app = QApplication(sys.argv)
    app.setApplicationName("Istari")
    app.setApplicationDisplayName("Istari")

    ico = _icon_path()
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))

    is_first_run = not os.path.exists(SETTINGS_FILE)

    # ── Startup registry: keep our own entry fresh, drop the pre-rename one ───
    # The old build registered "Palantir" pointing at a path the rename removed;
    # nothing else ever cleans it up.
    if purge_dead_legacy_startup():
        _log.info("Legacy 'Palantir' startup entry removed.")
    if is_startup_enabled():
        set_startup(True)
        _log.info("Startup registry entry refreshed.")

    w = Istari()
    w._apply_no_activate()
    _log.info("Log directory: %s", LOG_DIR)

    def _show_welcome():
        dlg = WelcomeDialog(w)
        screen = QApplication.primaryScreen().availableGeometry()
        dlg.move(
            screen.x() + (screen.width()  - dlg.width())  // 2,
            screen.y() + (screen.height() - dlg.height()) // 2,
        )
        dlg.exec()

    def _after_splash():
        w.show()
        QTimer.singleShot(0, w._play_intro)
        if is_first_run:
            QTimer.singleShot(650, _show_welcome)

    splash = SplashScreen()
    splash.start(_after_splash)

    sys.exit(app.exec())
