"""themes.py — Theme definitions and stylesheet builders for Istari."""

import ctypes
import functools

# ── Windows High Contrast detection ───────────────────────────────────────────

def is_high_contrast() -> bool:
    """Return True if Windows High Contrast accessibility mode is active."""
    try:
        class _HIGHCONTRAST(ctypes.Structure):
            _fields_ = [
                ("cbSize",             ctypes.c_uint),
                ("dwFlags",            ctypes.c_uint),
                ("lpszDefaultScheme",  ctypes.c_wchar_p),
            ]
        hc = _HIGHCONTRAST()
        hc.cbSize = ctypes.sizeof(hc)
        ctypes.windll.user32.SystemParametersInfoW(0x0042, hc.cbSize, ctypes.byref(hc), 0)
        return bool(hc.dwFlags & 0x0001)   # HCF_HIGHCONTRASTON
    except Exception:
        return False


# ── Theme palettes ─────────────────────────────────────────────────────────────

THEMES = {
    "dark": {
        # overlay widget
        "bg": "#0d0e1e", "border": "#181a38", "sep": "#13142c",
        "bar_bg": "#141530", "title": "#8080e0", "src": "#7878c6", "gear": "#6666aa",
        # settings panel background
        "panel_bg": "#0d0e1e", "panel_border": "#181a38",
        "dlg_sep": "#1a1a32", "dlg_header_ico": "#6474f0", "dlg_header_ttl": "#8888cc",
        # dialog controls
        "dlg_text": "#c0c8f0", "dlg_muted": "#a8b0d8", "dlg_section": "#7c7cd0",
        "dlg_input_bg": "#0e0f22", "dlg_input_border": "#5a5ea8", "dlg_sel_bg": "#1e2048",
        "dlg_btn_bg": "#0e0f22", "dlg_btn_hover": "#181a38",
        "dlg_scrollbar": "#0c0d20", "dlg_scroll_handle": "#5458b8",
        # accent / state colours, groove and handle (per theme so they keep contrast)
        "dlg_accent": "#7281f1", "dlg_add": "#66bb6a", "dlg_remove": "#e05555",
        "dlg_groove": "#515ab8", "dlg_handle": "#ffffff",
        # context menu
        "menu_text": "#a8b0d8", "menu_hover_text": "#c8d0f0",
        "menu_hover_bg": "#151730", "menu_border": "#1e2040", "menu_sep": "#181930",
    },
    "light": {
        # overlay widget
        "bg": "#f5f6ff", "border": "#d0d4f8", "sep": "#d8dcf8",
        "bar_bg": "#e8ebff", "title": "#3a3a90", "src": "#686aa8", "gear": "#7070c0",
        # settings panel background
        "panel_bg": "#f0f2fe", "panel_border": "#c8cef8",
        "dlg_sep": "#d0d4f8", "dlg_header_ico": "#6474f0", "dlg_header_ttl": "#5050a0",
        # dialog controls
        "dlg_text": "#2a2a60", "dlg_muted": "#5050a0", "dlg_section": "#6060b0",
        "dlg_input_bg": "#e8ebff", "dlg_input_border": "#6a78e0", "dlg_sel_bg": "#d0d8ff",
        "dlg_btn_bg": "#e8ebff", "dlg_btn_hover": "#d8dbff",
        "dlg_scrollbar": "#dde0fa", "dlg_scroll_handle": "#6a76cc",
        "dlg_accent": "#3248e6", "dlg_add": "#276a2b", "dlg_remove": "#b32424",
        "dlg_groove": "#7a86d8", "dlg_handle": "#e8ebff",
        # context menu
        "menu_text": "#2a2a60", "menu_hover_text": "#1a1a50",
        "menu_hover_bg": "#e0e4fc", "menu_border": "#c8cef8", "menu_sep": "#dde0fc",
    },
}

# ── Stylesheet builders ────────────────────────────────────────────────────────

_WIDGET_CSS_TPL = """
Istari {{
    background: {bg};
    border: 1px solid {border};
    border-radius: {radius};
}}
"""


def make_widget_css(theme: str = "dark", layout: str = "card") -> str:
    t = THEMES.get(theme, THEMES["dark"])
    radius = "18px" if layout == "card" else "10px"
    return _WIDGET_CSS_TPL.format(bg=t["bg"], border=t["border"], radius=radius)


@functools.lru_cache(maxsize=16)
def build_menu_css(bg: str, text: str, hover_text: str,
                   hover_bg: str, border: str, sep: str) -> str:
    return f"""
QMenu {{
    background: {bg}; border: 1px solid {border};
    color: {text}; font: 9pt 'Bahnschrift','Segoe UI'; padding: 5px 0;
}}
QMenu::item {{ padding: 6px 24px 6px 14px; border-radius: 4px; margin: 1px 5px; }}
QMenu::item:selected {{ background: {hover_bg}; color: {hover_text}; }}
QMenu::separator {{ height: 1px; background: {sep}; margin: 4px 10px; }}
"""


def make_settings_style(theme_name: str) -> str:
    t = THEMES.get(theme_name, THEMES["dark"])
    accent = t["dlg_accent"]
    return f"""
QDialog {{ background: transparent; }}
QWidget {{ background: transparent; }}
QLabel {{
    color: {t['dlg_text']};
    font: 9pt 'Bahnschrift', 'Segoe UI';
    background: transparent;
}}
QLabel#section {{
    color: {t['dlg_section']};
    font: bold 7pt 'Bahnschrift', 'Segoe UI';
    letter-spacing: 3px;
    background: transparent;
}}
QCheckBox {{
    color: {t['dlg_muted']};
    font: 9pt 'Bahnschrift', 'Segoe UI';
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    background: {t['dlg_input_bg']};
    border: 1px solid {t['dlg_input_border']};
    border-radius: 4px;
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
QSlider::groove:horizontal {{
    background: {t['dlg_groove']}; height: 3px; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {t['dlg_handle']}; width: 14px; height: 14px;
    margin: -6px 0; border-radius: 7px;
    border: 2px solid {accent};
}}
QSlider::sub-page:horizontal {{
    background: {accent}; border-radius: 2px;
}}
QComboBox {{
    background: {t['dlg_input_bg']}; border: 1px solid {t['dlg_input_border']};
    color: {t['dlg_muted']}; font: 9pt 'Bahnschrift', 'Segoe UI';
    padding: 5px 10px; border-radius: 6px; min-width: 110px;
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {t['dlg_input_bg']}; color: {t['dlg_muted']};
    selection-background-color: {t['dlg_sel_bg']};
    border: 1px solid {t['dlg_input_border']};
    font: 9pt 'Bahnschrift', 'Segoe UI';
}}
QPushButton {{
    background: {t['dlg_btn_bg']}; border: 1px solid {t['dlg_input_border']};
    color: {t['dlg_muted']}; font: 9pt 'Bahnschrift', 'Segoe UI';
    padding: 6px 20px; border-radius: 6px; min-width: 72px;
}}
QPushButton:hover {{ background: {t['dlg_btn_hover']}; border-color: {accent}; color: {t['dlg_text']}; }}
QPushButton#btn_ok {{
    background: {t['dlg_btn_bg']}; border: 1px solid {accent};
    color: {accent}; font: bold 9pt 'Bahnschrift', 'Segoe UI';
}}
QPushButton#btn_ok:hover {{ background: {t['dlg_btn_hover']}; }}
QPushButton#btn_close {{
    background: transparent; border: none;
    color: {t['dlg_muted']}; font: bold 13pt; padding: 0; min-width: 0;
    border-radius: 5px;
}}
QPushButton#btn_close:hover {{ color: {t['dlg_remove']}; background: rgba(200,0,0,0.12); }}
QPushButton#btn_reset {{
    background: transparent; border: 1px solid {t['dlg_input_border']};
    color: {t['dlg_muted']}; font: 7pt 'Bahnschrift', 'Segoe UI';
    border-radius: 4px; padding: 0 8px; min-width: 0; min-height: 20px;
}}
QPushButton#btn_reset:hover {{ border-color: {accent}; color: {t['dlg_text']}; }}
QPushButton#btn_add {{
    background: {t['dlg_btn_bg']}; border: 1px solid {t['dlg_input_border']};
    color: {t['dlg_add']}; font: 9pt 'Bahnschrift', 'Segoe UI';
    padding: 5px 14px; border-radius: 6px; min-width: 60px;
}}
QPushButton#btn_add:hover {{ background: {t['dlg_btn_hover']}; border-color: {t['dlg_add']}; }}
QPushButton#btn_remove {{
    background: {t['dlg_btn_bg']}; border: 1px solid {t['dlg_input_border']};
    color: {t['dlg_remove']}; font: 9pt 'Bahnschrift', 'Segoe UI';
    padding: 4px 10px; border-radius: 5px; min-width: 60px;
}}
QPushButton#btn_remove:hover {{ background: {t['dlg_btn_hover']}; border-color: {t['dlg_remove']}; }}
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
    background: transparent; border: none;
}}
QScrollBar:vertical {{ background: {t['dlg_scrollbar']}; width: 4px; border-radius: 2px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t['dlg_scroll_handle']}; border-radius: 2px; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""
