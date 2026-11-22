"""Modern koyu tema (QSS) ve programatik uygulama ikonu."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

DARK_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #0f1117;
    color: #e6edf3;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}

QWidget {
    color: #e6edf3;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #e6edf3;
    selection-background-color: #1f6feb;
}

QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: #58a6ff;
}

QPushButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 12px;
    color: #e6edf3;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
}

QPushButton:pressed, QPushButton:checked {
    background-color: #1f3a5f;
    border-color: #58a6ff;
}

QPushButton#primaryButton {
    background-color: #238636;
    border-color: #2ea043;
    color: #ffffff;
}

QPushButton#primaryButton:hover {
    background-color: #2ea043;
}

QPushButton#dangerButton {
    background-color: #da3633;
    border-color: #f85149;
    color: #ffffff;
}

QPushButton#dangerButton:hover {
    background-color: #f85149;
}

QListWidget {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}

QListWidget::item {
    border-radius: 6px;
    padding: 6px;
    margin: 2px 0;
    border: 1px solid transparent;
}

QListWidget::item:hover {
    background-color: #1f242c;
}

QListWidget::item:selected {
    background-color: #1f3a5f;
    border: 1px solid #58a6ff;
}

QTabWidget::pane {
    border: 1px solid #30363d;
    border-radius: 6px;
    background-color: #12161d;
    padding: 8px;
}

QTabBar::tab {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 14px;
    margin-right: 4px;
    color: #8b949e;
}

QTabBar::tab:selected {
    background-color: #1f242c;
    color: #e6edf3;
    border-color: #58a6ff;
}

QProgressBar {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 5px;
    height: 18px;
    text-align: center;
    color: #e6edf3;
}

QProgressBar::chunk {
    background-color: #1f6feb;
    border-radius: 4px;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #30363d;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #58a6ff;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #e6edf3;
    border: 2px solid #58a6ff;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 8px;
}

QSplitter::handle {
    background-color: #21262d;
    width: 2px;
    height: 2px;
}

QStatusBar {
    background-color: #161b22;
    border-top: 1px solid #30363d;
    color: #8b949e;
}

QLabel#metaLabel {
    color: #8b949e;
    font-size: 12px;
}
"""


def create_app_icon(paused: bool = False) -> QIcon:
    """Harici dosya gerektirmeden temiz vektörel bir uygulama/tray ikonu üretir."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    bg_color = QColor("#6e7681") if paused else QColor("#1f6feb")
    painter.setBrush(bg_color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 14, 14)

    pen = QPen(QColor("#ffffff"), 5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(16, 16, 32, 32, 45 * 16, 270 * 16)

    if paused:
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(25, 24, 5, 16, 2, 2)
        painter.drawRoundedRect(34, 24, 5, 16, 2, 2)
    else:
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(27, 27, 10, 10)

    painter.end()
    return QIcon(pixmap)
