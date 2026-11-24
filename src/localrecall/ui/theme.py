"""LocalRecall Studio 2.0 — Studio Graphite QSS theme with Sky Blue (#38BDF8) signature accent."""

from __future__ import annotations

from localrecall.hardware import get_ui_font_family
from localrecall.ui.widgets import create_app_icon, create_app_pixmap

ACCENT_SKY = "#38BDF8"
ACCENT_SKY_SOFT = "rgba(56, 189, 248, 0.14)"
ACCENT_AMBER = "#F59E0B"
ACCENT_EMERALD = "#10B981"
ACCENT_ROSE = "#E11D48"

SURFACE_CANVAS = "#0A0A0C"
SURFACE_SIDEBAR = "#111113"
SURFACE_CARD = "#141417"
SURFACE_BORDER = "#24242A"
INK_PRIMARY = "#FAFAFA"
INK_SECONDARY = "#A1A1AA"
INK_MUTED = "#71717A"


def build_studio_stylesheet() -> str:
    ui_font = get_ui_font_family()
    return f"""
QMainWindow, QDialog, QWidget#centralWidget, QScrollArea, QWidget#scrollContent {{
    background-color: {SURFACE_CANVAS};
    color: {INK_PRIMARY};
    font-family: '{ui_font}', 'Segoe UI', 'Inter', -apple-system, sans-serif;
    font-size: 9pt;
}}

QLabel {{
    background-color: transparent;
    color: #E4E4E7;
    font-family: '{ui_font}', 'Segoe UI', 'Inter', -apple-system, sans-serif;
}}

QLabel#pageTitle {{
    color: {INK_PRIMARY};
    font-size: 14pt;
    font-weight: 700;
    letter-spacing: -0.3px;
}}

QLabel#pageSubtitle {{
    color: {INK_MUTED};
    font-size: 8.6pt;
    font-weight: 500;
}}

QLabel#sectionTitle {{
    color: {INK_PRIMARY};
    font-size: 9.6pt;
    font-weight: 700;
}}

QLabel#metaLabel {{
    color: {INK_SECONDARY};
    font-size: 8.3pt;
}}

QFrame#sidebarRail {{
    background-color: {SURFACE_SIDEBAR};
    border: none;
    border-right: 1px solid #222227;
}}

QFrame#studioCard {{
    background-color: {SURFACE_CARD};
    border: 1px solid {SURFACE_BORDER};
    border-radius: 10px;
}}

QFrame#stagePanel {{
    background-color: #111114;
    border: 1px solid {SURFACE_BORDER};
    border-radius: 10px;
}}

QFrame#shieldHero {{
    background-color: #0E1815;
    border: 1px solid #1C3A2F;
    border-radius: 10px;
}}

QFrame#panicCard {{
    background-color: #1A1014;
    border: 1px solid #3D1A26;
    border-radius: 10px;
}}

QFrame#permissionBanner {{
    background-color: #1F1910;
    border: 1px solid #4A3716;
    border-radius: 8px;
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {SURFACE_CARD};
    border: 1px solid {SURFACE_BORDER};
    border-radius: 7px;
    padding: 6px 10px;
    color: {INK_PRIMARY};
    selection-background-color: rgba(56, 189, 248, 0.30);
    font-size: 8.8pt;
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT_SKY};
    background-color: #16161B;
}}

QComboBox {{
    background-color: {SURFACE_CARD};
    border: 1px solid {SURFACE_BORDER};
    border-radius: 7px;
    padding: 5px 4px 5px 10px;
    min-height: 22px;
    color: {INK_PRIMARY};
    font-size: 8.6pt;
    font-weight: 500;
}}

QComboBox:hover {{
    border-color: #3F3F4A;
    background-color: #1A1A20;
}}

QComboBox:focus {{
    border-color: {ACCENT_SKY};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: #16161A;
    color: #F4F4F5;
    selection-background-color: #24242E;
    selection-color: #FFFFFF;
    border: 1px solid #32323C;
    outline: none;
    padding: 4px;
}}

QPushButton {{
    background-color: #1B1B21;
    color: #E4E4E7;
    border: 1px solid #2B2B34;
    border-radius: 7px;
    padding: 6px 12px;
    font-size: 8.6pt;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: #23232B;
    border-color: #3F3F4A;
    color: #FFFFFF;
}}

QPushButton:pressed {{
    background-color: #16161B;
}}

QPushButton:checked {{
    background-color: rgba(56, 189, 248, 0.16);
    border-color: {ACCENT_SKY};
    color: {ACCENT_SKY};
}}

QPushButton:disabled {{
    background-color: #121216;
    color: #52525B;
    border-color: #1E1E24;
}}

QPushButton#primaryButton {{
    background-color: {ACCENT_SKY};
    border-color: {ACCENT_SKY};
    color: #09090B;
    font-weight: 700;
}}

QPushButton#primaryButton:hover {{
    background-color: #7DD3FC;
    border-color: #7DD3FC;
    color: #09090B;
}}

QPushButton#emeraldButton {{
    background-color: rgba(16, 185, 129, 0.16);
    border-color: #10B981;
    color: #34D399;
}}

QPushButton#emeraldButton:hover {{
    background-color: rgba(16, 185, 129, 0.26);
    color: #ECFDF5;
}}

QPushButton#dangerButton {{
    background-color: rgba(225, 29, 72, 0.16);
    border-color: {ACCENT_ROSE};
    color: #FDA4AF;
}}

QPushButton#dangerButton:hover {{
    background-color: {ACCENT_ROSE};
    border-color: #F43F5E;
    color: #FFFFFF;
}}

QPushButton#subtleButton {{
    background-color: transparent;
    border: 1px solid {SURFACE_BORDER};
    color: {INK_SECONDARY};
    padding: 5px 9px;
    font-size: 8.2pt;
}}

QPushButton#subtleButton:hover {{
    background-color: #1A1A20;
    color: {INK_PRIMARY};
    border-color: #3A3A44;
}}

QListWidget {{
    background-color: #0E0E11;
    border: 1px solid #202026;
    border-radius: 9px;
    color: #E4E4E7;
    outline: none;
    padding: 4px;
}}

QListWidget::item {{
    border-radius: 7px;
    padding: 0px;
    margin: 2px 0px;
    border: 1px solid transparent;
}}

QListWidget::item:hover {{
    background-color: #17171C;
}}

QListWidget::item:selected {{
    background-color: rgba(56, 189, 248, 0.12);
    border: 1px solid rgba(56, 189, 248, 0.45);
}}

QSplitter::handle {{
    background-color: #1E1E24;
    width: 2px;
    height: 2px;
}}

QProgressBar {{
    background-color: #1A1A20;
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {ACCENT_SKY};
    border-radius: 3px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 2px 0;
}}

QScrollBar::handle:vertical {{
    background: #2A2A32;
    border-radius: 3px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: #52525E;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    margin: 0 2px;
}}

QScrollBar::handle:horizontal {{
    background: #2A2A32;
    border-radius: 3px;
    min-width: 24px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QStatusBar {{
    background-color: {SURFACE_SIDEBAR};
    border-top: 1px solid #222227;
    color: {INK_MUTED};
    font-size: 8.2pt;
}}

QMenu {{
    background-color: #16161B;
    border: 1px solid #2C2C35;
    border-radius: 8px;
    padding: 4px;
    color: #E4E4E7;
}}

QMenu::item {{
    padding: 6px 14px;
    border-radius: 5px;
}}

QMenu::item:selected {{
    background-color: rgba(56, 189, 248, 0.16);
    color: {ACCENT_SKY};
}}
"""


DARK_STYLESHEET = build_studio_stylesheet()

__all__ = [
    "ACCENT_AMBER",
    "ACCENT_EMERALD",
    "ACCENT_ROSE",
    "ACCENT_SKY",
    "ACCENT_SKY_SOFT",
    "DARK_STYLESHEET",
    "build_studio_stylesheet",
    "create_app_icon",
    "create_app_pixmap",
]
