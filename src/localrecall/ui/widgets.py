"""LocalRecall Studio 2.0 — Reusable HiDPI PyQt6 Widgets, Vector Icons & Visual Timeline Ribbon."""

from __future__ import annotations

import hashlib
import os
import sys
from typing import Optional, Sequence

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from localrecall.hardware import get_app_base_dir
from localrecall.storage.database import CaptureRecord

_APP_COLOR_MAP: dict[str, str] = {
    "vs code": "#38BDF8",
    "code": "#38BDF8",
    "cursor": "#38BDF8",
    "chrome": "#3B82F6",
    "google chrome": "#3B82F6",
    "firefox": "#F97316",
    "safari": "#0EA5E9",
    "msedge": "#06B6D4",
    "terminal": "#22C55E",
    "iterm2": "#22C55E",
    "windowsterminal": "#22C55E",
    "figma": "#EC4899",
    "slack": "#A855F7",
    "discord": "#818CF8",
    "libreoffice calc": "#10B981",
    "excel": "#10B981",
    "notion": "#E4E4E7",
    "obsidian": "#A78BFA",
}

_FALLBACK_COLORS: tuple[str, ...] = (
    "#38BDF8",
    "#10B981",
    "#F59E0B",
    "#A855F7",
    "#EC4899",
    "#06B6D4",
    "#22C55E",
    "#6366F1",
)


def app_color_for_name(app_name: str) -> str:
    """Returns a deterministic high-contrast Studio color for a given application name."""
    norm = (app_name or "").strip().lower()
    for suffix in (".exe", ".app"):
        if norm.endswith(suffix):
            norm = norm[: -len(suffix)]
    if norm in _APP_COLOR_MAP:
        return _APP_COLOR_MAP[norm]
    if not norm:
        return "#71717A"
    digest = hashlib.md5(norm.encode("utf-8")).digest()
    return _FALLBACK_COLORS[digest[0] % len(_FALLBACK_COLORS)]


def make_flat_icon(kind: str, color_hex: str = "#FAFAFA", size: int = 14) -> QIcon:
    """Renders crisp 2x HiDPI flat vector icons without relying on platform emojis."""
    px = max(16, int(size) * 2)
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(color_hex)
        pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        if kind == "search":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(px * 0.16, px * 0.16, px * 0.48, px * 0.48))
            p.drawLine(QPointF(px * 0.58, px * 0.58), QPointF(px * 0.84, px * 0.84))
        elif kind == "camera":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(px * 0.14, px * 0.26, px * 0.72, px * 0.52), 4, 4)
            p.drawEllipse(QPointF(px * 0.50, px * 0.52), px * 0.14, px * 0.14)
            p.drawLine(QPointF(px * 0.36, px * 0.26), QPointF(px * 0.42, px * 0.16))
            p.drawLine(QPointF(px * 0.42, px * 0.16), QPointF(px * 0.58, px * 0.16))
            p.drawLine(QPointF(px * 0.58, px * 0.16), QPointF(px * 0.64, px * 0.26))
        elif kind == "play":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            poly = QPolygonF(
                [
                    QPointF(px * 0.28, px * 0.18),
                    QPointF(px * 0.82, px * 0.50),
                    QPointF(px * 0.28, px * 0.82),
                ]
            )
            p.drawPolygon(poly)
        elif kind == "pause":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(px * 0.24, px * 0.20, px * 0.18, px * 0.60), 2, 2)
            p.drawRoundedRect(QRectF(px * 0.58, px * 0.20, px * 0.18, px * 0.60), 2, 2)
        elif kind == "stop":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(px * 0.24, px * 0.24, px * 0.52, px * 0.52), 3, 3)
        elif kind == "shield":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(px * 0.50, px * 0.12)
            path.lineTo(px * 0.82, px * 0.25)
            path.lineTo(px * 0.82, px * 0.52)
            path.quadTo(px * 0.82, px * 0.78, px * 0.50, px * 0.88)
            path.quadTo(px * 0.18, px * 0.78, px * 0.18, px * 0.52)
            path.lineTo(px * 0.18, px * 0.25)
            path.closeSubpath()
            p.drawPath(path)
        elif kind == "pin":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(px * 0.50, px * 0.34), px * 0.18, px * 0.18)
            p.drawLine(QPointF(px * 0.50, px * 0.52), QPointF(px * 0.50, px * 0.86))
        elif kind == "copy":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(px * 0.34, px * 0.30, px * 0.48, px * 0.52), 3, 3)
            p.drawLine(QPointF(px * 0.22, px * 0.66), QPointF(px * 0.22, px * 0.20))
            p.drawLine(QPointF(px * 0.22, px * 0.20), QPointF(px * 0.64, px * 0.20))
        elif kind == "download":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.50, px * 0.18), QPointF(px * 0.50, px * 0.66))
            p.drawLine(QPointF(px * 0.32, px * 0.48), QPointF(px * 0.50, px * 0.66))
            p.drawLine(QPointF(px * 0.68, px * 0.48), QPointF(px * 0.50, px * 0.66))
            p.drawLine(QPointF(px * 0.20, px * 0.82), QPointF(px * 0.80, px * 0.82))
        elif kind == "trash":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.20, px * 0.26), QPointF(px * 0.80, px * 0.26))
            p.drawRoundedRect(QRectF(px * 0.28, px * 0.26, px * 0.44, px * 0.58), 3, 3)
            p.drawLine(QPointF(px * 0.40, px * 0.16), QPointF(px * 0.60, px * 0.16))
        elif kind == "boxes":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(px * 0.14, px * 0.18, px * 0.72, px * 0.64), 3, 3)
            p.drawLine(QPointF(px * 0.28, px * 0.40), QPointF(px * 0.72, px * 0.40))
            p.drawLine(QPointF(px * 0.28, px * 0.60), QPointF(px * 0.58, px * 0.60))
        elif kind == "rewind":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(px * 0.18, px * 0.18, px * 0.64, px * 0.64)
            p.drawArc(rect, 35 * 16, 290 * 16)
            p.drawLine(QPointF(px * 0.22, px * 0.26), QPointF(px * 0.22, px * 0.44))
            p.drawLine(QPointF(px * 0.22, px * 0.44), QPointF(px * 0.40, px * 0.44))
        elif kind == "bolt":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            poly = QPolygonF(
                [
                    QPointF(px * 0.56, px * 0.12),
                    QPointF(px * 0.24, px * 0.54),
                    QPointF(px * 0.48, px * 0.54),
                    QPointF(px * 0.42, px * 0.88),
                    QPointF(px * 0.76, px * 0.46),
                    QPointF(px * 0.52, px * 0.46),
                ]
            )
            p.drawPolygon(poly)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(px / 2.0, px / 2.0), px * 0.26, px * 0.26)
    finally:
        p.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix)


def create_app_pixmap(size: int = 64, paused: bool = False) -> QPixmap:
    """
    Renders the LocalRecall obsidian geometric icon (Rewind-Shutter Eye + Timeline) at 2x HiDPI.
    """
    target_px = max(16, int(size) * 2)
    if not paused:
        search_roots = [get_app_base_dir()]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and meipass not in search_roots:
            search_roots.append(meipass)
        for root in search_roots:
            for fname in ("app_icon.png", "app_icon.ico"):
                icon_path = os.path.join(root, "assets", fname)
                if os.path.exists(icon_path):
                    src_pix = QPixmap(icon_path)
                    if not src_pix.isNull():
                        scaled = src_pix.scaled(
                            target_px,
                            target_px,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        scaled.setDevicePixelRatio(2.0)
                        return scaled

    pix = QPixmap(target_px, target_px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = target_px / 512.0

        # Matte Obsidian Flat Tile
        p.setBrush(QColor("#111114"))
        p.setPen(QPen(QColor("#27272E"), max(1.0, 6.0 * k)))
        p.drawRoundedRect(QRectF(12 * k, 12 * k, 488 * k, 488 * k), 114 * k, 114 * k)

        # Geometric Rewind Arc (270 deg counter-clockwise rewind ring)
        arc_color = QColor("#71717A") if paused else QColor("#FAFAFA")
        arc_pen = QPen(
            arc_color,
            max(2.0, 26.0 * k),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        p.setPen(arc_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(118 * k, 102 * k, 276 * k, 276 * k), 35 * 16, 265 * 16)

        # Rewind Arrow Head at top-left
        arrow = QPainterPath()
        arrow.moveTo(148 * k, 134 * k)
        arrow.lineTo(106 * k, 174 * k)
        arrow.lineTo(164 * k, 184 * k)
        p.drawPath(arrow)

        # Center Shutter Core / Pause Bars
        accent_col = QColor("#F59E0B") if paused else QColor("#38BDF8")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent_col)
        if paused:
            p.drawRoundedRect(QRectF(214 * k, 198 * k, 28 * k, 84 * k), 10 * k, 10 * k)
            p.drawRoundedRect(QRectF(270 * k, 198 * k, 28 * k, 84 * k), 10 * k, 10 * k)
        else:
            p.drawEllipse(QPointF(256 * k, 240 * k), 44 * k, 44 * k)
            p.setBrush(QColor("#111114"))
            p.drawEllipse(QPointF(256 * k, 240 * k), 18 * k, 18 * k)

        # Bottom Minimal Timeline Track
        p.setBrush(QColor("#27272E"))
        p.drawRoundedRect(QRectF(114 * k, 412 * k, 284 * k, 22 * k), 11 * k, 11 * k)
        p.setBrush(accent_col)
        p.drawRoundedRect(QRectF(114 * k, 412 * k, 178 * k, 22 * k), 11 * k, 11 * k)
    finally:
        p.end()
    pix.setDevicePixelRatio(2.0)
    return pix


def create_app_icon(paused: bool = False) -> QIcon:
    return QIcon(create_app_pixmap(64, paused=paused))


class SidebarNavButton(QPushButton):
    """Studio 2.0 sidebar navigation item with Sky Blue active dot and optional status badge."""

    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._label_text = label
        self._badge_text = ""
        self._badge_kind = "muted"
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setText("")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(9)

        self._dot = QFrame(self)
        self._dot.setFixedSize(6, 6)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._dot)

        self._lbl = QLabel(label, self)
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._lbl, stretch=1)

        self._badge = QLabel("", self)
        self._badge.setFixedHeight(19)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._badge.hide()
        lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self._refresh_style()

    def set_nav_text(self, label: str) -> None:
        self._label_text = label
        self._lbl.setText(label)

    def set_badge(self, text: str, kind: str = "muted") -> None:
        self._badge_text = str(text or "").strip()
        self._badge_kind = kind
        if not self._badge_text:
            self._badge.hide()
            return
        self._badge.setText(self._badge_text)
        if kind == "live":
            self._badge.setStyleSheet(
                "color: #38BDF8; background-color: rgba(56, 189, 248, 0.14); border: 1px solid rgba(56, 189, 248, 0.35); "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        elif kind == "shield":
            self._badge.setStyleSheet(
                "color: #10B981; background-color: rgba(16, 185, 129, 0.14); border: 1px solid rgba(16, 185, 129, 0.35); "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        elif kind == "paused":
            self._badge.setStyleSheet(
                "color: #F59E0B; background-color: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.35); "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        else:
            self._badge.setStyleSheet(
                "color: #A1A1AA; background-color: #1B1B21; border: 1px solid #2A2A32; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        self._badge.show()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                "QPushButton { background-color: #1B1D23; border: 1px solid #2C303A; border-radius: 7px; }"
            )
            self._dot.setStyleSheet("background-color: #38BDF8; border-radius: 3px; border: none;")
            self._lbl.setStyleSheet(
                "color: #FAFAFA; font-size: 8.9pt; font-weight: 600; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 7px; }"
                "QPushButton:hover { background-color: #18181D; }"
            )
            self._dot.setStyleSheet("background-color: #52525B; border-radius: 3px; border: none;")
            self._lbl.setStyleSheet(
                "color: #A1A1AA; font-size: 8.9pt; font-weight: 500; background: transparent; border: none;"
            )


class FlatSwitch(QCheckBox):
    """Studio 2.0 minimalist toggle switch (QCheckBox API compatible)."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, accent: str = "#38BDF8") -> None:
        super().__init__(text, parent)
        self._accent = accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        return QSize(34 + 10 + text_w + 8, max(24, fm.height() + 6))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            track_w, track_h = 34, 18
            y = (self.height() - track_h) // 2
            checked = self.isChecked()

            if checked:
                track_col = QColor(self._accent)
                border_col = QColor(self._accent)
                knob_col = QColor("#09090B")
            else:
                track_col = QColor("#24242B")
                border_col = QColor("#32323B")
                knob_col = QColor("#A1A1AA")

            p.setBrush(track_col)
            p.setPen(QPen(border_col, 1))
            p.drawRoundedRect(1, y, track_w, track_h, track_h / 2.0, track_h / 2.0)

            knob_d = 12
            knob_x = (track_w - knob_d - 2) if checked else 4
            knob_y = y + (track_h - knob_d) // 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(knob_col)
            p.drawEllipse(knob_x, knob_y, knob_d, knob_d)

            txt_col = QColor("#E4E4E7") if (self.isEnabled() and checked) else (QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B"))
            p.setPen(txt_col)
            p.setFont(self.font())
            text_rect = QRect(track_w + 10, 0, max(0, self.width() - track_w - 10), self.height())
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        finally:
            p.end()


class FlatComboBox(QComboBox):
    """Flat QComboBox with a clean vector chevron arrow across Windows/macOS/Linux."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            col = QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B")
            pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            cx = self.width() - 14
            cy = self.height() // 2
            p.drawLine(QPointF(cx - 3.5, cy - 1.8), QPointF(cx, cy + 2.0))
            p.drawLine(QPointF(cx, cy + 2.0), QPointF(cx + 3.5, cy - 1.8))
        finally:
            p.end()


class TelemetryCard(QFrame):
    """Studio 2.0 flat KPI card with subtle accent bar."""

    def __init__(
        self,
        title: str,
        badge_text: str,
        initial_val: str,
        sub_text: str,
        accent_hex: str = "#38BDF8",
        initial_pct: int = 35,
    ) -> None:
        super().__init__()
        self.accent_hex = accent_hex
        self.setObjectName("telemetryCard")
        self.setStyleSheet(
            """
            QFrame#telemetryCard {
                background-color: #141417;
                border: 1px solid #24242A;
                border-radius: 9px;
            }
            QFrame#telemetryCard QLabel {
                background-color: transparent;
                border: none;
            }
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 11, 13, 11)
        lay.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #71717A; font-size: 7.3pt; font-weight: 700; letter-spacing: 0.6px;"
        )
        hdr.addWidget(self.lbl_title)

        self.lbl_badge = QLabel(badge_text)
        self.lbl_badge.setStyleSheet(f"color: {accent_hex}; font-size: 7pt; font-weight: 700;")
        hdr.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(hdr)

        self.lbl_val = QLabel(initial_val)
        self.lbl_val.setStyleSheet(
            "color: #FAFAFA; font-size: 14.5pt; font-weight: 700; letter-spacing: -0.3px;"
        )
        lay.addWidget(self.lbl_val)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(max(4, min(100, int(initial_pct))))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: none;
                background-color: #24242A;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_hex};
                border-radius: 1px;
            }}
            """
        )
        lay.addWidget(self.bar)

        self.lbl_sub = QLabel(sub_text)
        self.lbl_sub.setStyleSheet("color: #71717A; font-size: 7.4pt; font-weight: 500;")
        lay.addWidget(self.lbl_sub)

    def set_title(self, title: str) -> None:
        self.lbl_title.setText(title)

    def set_metric(
        self,
        val_text: str,
        sub_text: Optional[str] = None,
        badge_text: Optional[str] = None,
        bar_pct: Optional[int] = None,
    ) -> None:
        self.lbl_val.setText(val_text)
        if sub_text is not None:
            self.lbl_sub.setText(sub_text)
        if badge_text is not None:
            self.lbl_badge.setText(badge_text)
        if bar_pct is not None:
            self.bar.setValue(max(4, min(100, int(round(bar_pct)))))


class TimelineRibbonWidget(QWidget):
    """
    App-Colored Visual Timeline Ribbon with clickable/draggable scrubber playhead
    and pinned-moment amber markers.
    """

    index_changed = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(30)
        self.setMaximumHeight(34)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._records: list[CaptureRecord] = []
        self._current_index: int = -1
        self._hover_index: int = -1
        self._dragging = False

    def set_records(self, records: Sequence[CaptureRecord], current_index: int = -1) -> None:
        self._records = list(records)
        if not self._records:
            self._current_index = -1
        elif 0 <= current_index < len(self._records):
            self._current_index = current_index
        else:
            self._current_index = len(self._records) - 1
        self.update()

    def set_current_index(self, index: int, emit_signal: bool = False) -> None:
        if not self._records:
            self._current_index = -1
            self.update()
            return
        clamped = max(0, min(len(self._records) - 1, int(index)))
        if clamped != self._current_index:
            self._current_index = clamped
            self.update()
            if emit_signal:
                self.index_changed.emit(clamped)

    @property
    def current_index(self) -> int:
        return self._current_index

    def _index_for_x(self, x: float) -> int:
        n = len(self._records)
        if n <= 0:
            return -1
        pad = 8.0
        usable = max(1.0, self.width() - (2.0 * pad))
        rel = max(0.0, min(0.9999, (x - pad) / usable))
        return int(rel * n)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None or event.button() != Qt.MouseButton.LeftButton or not self._records:
            return
        self._dragging = True
        idx = self._index_for_x(event.position().x())
        if idx >= 0:
            self.set_current_index(idx, emit_signal=True)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None or not self._records:
            return
        idx = self._index_for_x(event.position().x())
        if idx != self._hover_index:
            self._hover_index = idx
            self.update()
        if 0 <= idx < len(self._records):
            rec = self._records[idx]
            ts = rec.timestamp.replace("T", " ")
            tip = f"{ts} · {rec.app_name or 'Screen'}\n{rec.window_title[:60]}"
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        if self._dragging and idx >= 0:
            self.set_current_index(idx, emit_signal=True)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = float(self.width())
            h = float(self.height())
            track_rect = QRectF(4.0, 6.0, max(1.0, w - 8.0), max(1.0, h - 12.0))

            # Track surface
            p.setBrush(QColor("#141418"))
            p.setPen(QPen(QColor("#24242A"), 1.0))
            p.drawRoundedRect(track_rect, 6.0, 6.0)

            n = len(self._records)
            if n <= 0:
                p.setPen(QColor("#52525B"))
                p.setFont(QFont("Sans", 8))
                p.drawText(track_rect, Qt.AlignmentFlag.AlignCenter, "—")
                return

            inner_x = track_rect.left() + 4.0
            inner_w = max(1.0, track_rect.width() - 8.0)
            seg_w = inner_w / float(n)
            gap = 1.5 if seg_w > 6.0 else 0.0

            for i, rec in enumerate(self._records):
                x0 = inner_x + (i * seg_w) + (gap * 0.5)
                sw = max(1.5, seg_w - gap)
                col = QColor(app_color_for_name(rec.app_name))
                is_cur = i == self._current_index
                is_hov = i == self._hover_index
                col.setAlpha(235 if is_cur else (190 if is_hov else 120))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                seg_rect = QRectF(x0, track_rect.top() + 3.0, sw, track_rect.height() - 6.0)
                p.drawRoundedRect(seg_rect, 2.0, 2.0)

                if rec.pinned:
                    cx = x0 + sw * 0.5
                    cy = track_rect.top() + 1.0
                    p.setBrush(QColor("#F59E0B"))
                    p.drawEllipse(QPointF(cx, cy), 3.0, 3.0)

            # Scrubber Playhead
            if 0 <= self._current_index < n:
                px = inner_x + ((self._current_index + 0.5) * seg_w)
                p.setPen(QPen(QColor("#FAFAFA"), 2.0))
                p.drawLine(QPointF(px, 2.0), QPointF(px, h - 2.0))
                p.setBrush(QColor("#38BDF8"))
                p.setPen(QPen(QColor("#09090B"), 1.5))
                p.drawEllipse(QPointF(px, h * 0.5), 5.0, 5.0)
        finally:
            p.end()


class HourlyActivityChartWidget(QWidget):
    """Minimalist Studio 2.0 24-hour vertical activity bar chart."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        self._buckets: list[tuple[int, int]] = [(h, 0) for h in range(24)]

    def set_data(self, buckets: Sequence[tuple[int, int]]) -> None:
        self._buckets = list(buckets) if buckets else [(h, 0) for h in range(24)]
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = float(self.width())
            h = float(self.height())

            p.setBrush(QColor("#111114"))
            p.setPen(QPen(QColor("#222228"), 1.0))
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 8.0, 8.0)

            pad_l, pad_r, pad_t, pad_b = 14.0, 14.0, 14.0, 24.0
            chart_w = max(1.0, w - pad_l - pad_r)
            chart_h = max(1.0, h - pad_t - pad_b)
            max_val = max((cnt for _, cnt in self._buckets), default=1) or 1

            # Baseline
            p.setPen(QPen(QColor("#24242A"), 1.0))
            p.drawLine(QPointF(pad_l, pad_t + chart_h), QPointF(w - pad_r, pad_t + chart_h))

            n = max(1, len(self._buckets))
            slot_w = chart_w / float(n)
            bar_w = max(3.0, slot_w * 0.62)

            label_font = QFont(self.font())
            label_font.setPointSize(7)
            p.setFont(label_font)

            for i, (hour, cnt) in enumerate(self._buckets):
                bx = pad_l + i * slot_w + (slot_w - bar_w) * 0.5
                bh = max(3.0, (cnt / float(max_val)) * (chart_h - 4.0)) if cnt > 0 else 2.0
                by = pad_t + chart_h - bh

                col = QColor("#38BDF8") if cnt > 0 else QColor("#24242A")
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 2.0, 2.0)

                if hour % 4 == 0:
                    p.setPen(QColor("#71717A"))
                    lbl_rect = QRectF(bx - 8.0, pad_t + chart_h + 4.0, bar_w + 16.0, 16.0)
                    p.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, f"{hour:02d}")
        finally:
            p.end()
