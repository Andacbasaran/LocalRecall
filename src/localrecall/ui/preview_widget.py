"""Interactive Live-Text Screenshot Preview with Zoom/Pan, OCR Hover Tooltips & Annotated PNG Export."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QToolTip, QWidget

from localrecall.ocr.engine import OCRBox
from localrecall.search.hybrid import normalize_for_matching, parse_search_query


class InteractivePreviewWidget(QWidget):
    """
    Studio 2.0 Interactive Preview Stage:
    - Amber (#F59E0B) highlighted OCR match boxes & Sky Blue (#38BDF8) all-boxes overlay
    - Click any OCR box to copy its text directly to clipboard
    - Smooth Ctrl+Wheel zoom (50%..400%) + left-drag panning when zoomed
    - Export full-resolution annotated PNG with highlight boxes or privacy blur
    """

    box_clicked = pyqtSignal(str)
    zoom_changed = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 220)
        self.setMouseTracking(True)
        self._pixmap: QPixmap | None = None
        self._boxes: list[OCRBox] = []
        self._highlight_tokens: list[str] = []
        self._show_all_boxes = False
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._drag_origin: QPointF | None = None
        self._drag_pan_start = QPointF(0.0, 0.0)
        self._did_drag = False
        self._hovered_box: OCRBox | None = None
        self._placeholder = "No screen capture selected."
        self._last_draw_rect = QRectF()

    @property
    def zoom_percent(self) -> int:
        return int(round(self._zoom * 100))

    def set_image(self, pixmap: QPixmap | None, placeholder: str = "No screen capture selected.") -> None:
        self._pixmap = pixmap
        self._placeholder = placeholder
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._hovered_box = None
        self.zoom_changed.emit(self.zoom_percent)
        self.update()

    def set_ocr_boxes(self, boxes: list[OCRBox]) -> None:
        self._boxes = boxes
        self._hovered_box = None
        self.update()

    def set_highlight_query(self, query: str) -> None:
        parsed = parse_search_query(query)
        norm = normalize_for_matching(parsed.highlight_query)
        self._highlight_tokens = [t for t in norm.split() if len(t) >= 2]
        self.update()

    def set_show_all_boxes(self, enabled: bool) -> None:
        self._show_all_boxes = bool(enabled)
        self.update()

    def set_zoom(self, zoom: float) -> None:
        clamped = max(0.5, min(4.0, float(zoom)))
        if abs(clamped - self._zoom) > 0.005:
            self._zoom = clamped
            if self._zoom <= 1.01:
                self._pan = QPointF(0.0, 0.0)
            self.zoom_changed.emit(self.zoom_percent)
            self.update()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.2)

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.zoom_changed.emit(self.zoom_percent)
        self.update()

    @property
    def matched_box_count(self) -> int:
        if not self._highlight_tokens:
            return 0
        return sum(1 for b in self._boxes if self._is_match(b))

    def _is_match(self, box: OCRBox) -> bool:
        if not self._highlight_tokens:
            return False
        norm_box = normalize_for_matching(box.text)
        return any(tok in norm_box for tok in self._highlight_tokens)

    def render_annotated_pixmap(self, include_all_boxes: bool = False) -> QPixmap | None:
        """Renders the full-resolution screenshot with Amber/Sky OCR overlays for PNG export."""
        if self._pixmap is None or self._pixmap.isNull():
            return None
        out = QPixmap(self._pixmap)
        p = QPainter(out)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = float(out.width())
            h = float(out.height())
            for box in self._boxes:
                matched = self._is_match(box)
                if not matched and not (include_all_boxes or self._show_all_boxes):
                    continue
                rect = QRectF(box.x * w, box.y * h, box.w * w, box.h * h).adjusted(-3, -3, 3, 3)
                if matched:
                    p.setBrush(QColor(245, 158, 11, 72))
                    p.setPen(QPen(QColor("#F59E0B"), 2.5))
                else:
                    p.setBrush(QColor(56, 189, 248, 28))
                    p.setPen(QPen(QColor(56, 189, 248, 150), 1.2))
                p.drawRoundedRect(rect, 4, 4)
        finally:
            p.end()
        return out

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None or self._pixmap is None or self._pixmap.isNull():
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else (1.0 / 1.15)
            self.set_zoom(self._zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        self.reset_zoom()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._did_drag = False
        if self._zoom > 1.02:
            self._drag_origin = event.position()
            self._drag_pan_start = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        pos = event.position()
        if self._drag_origin is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = pos - self._drag_origin
            if abs(delta.x()) > 3.0 or abs(delta.y()) > 3.0:
                self._did_drag = True
            self._pan = self._drag_pan_start + delta
            self.update()
            return

        # Hover detection over OCR boxes
        found: OCRBox | None = None
        if not self._last_draw_rect.isEmpty() and self._boxes:
            for box in self._boxes:
                if self._box_to_widget_rect(box).contains(pos):
                    found = box
                    break

        if found is not self._hovered_box:
            self._hovered_box = found
            self.update()
            if found is not None:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"Click to copy:\n{found.text[:140]}",
                    self,
                )
            else:
                self.setCursor(
                    Qt.CursorShape.OpenHandCursor if self._zoom > 1.02 else Qt.CursorShape.ArrowCursor
                )

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        was_drag = self._did_drag
        self._drag_origin = None
        self._did_drag = False
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if self._zoom > 1.02 else Qt.CursorShape.ArrowCursor
        )
        if not was_drag and event.button() == Qt.MouseButton.LeftButton:
            if not self._last_draw_rect.isEmpty() and self._boxes:
                pos = event.position()
                for box in self._boxes:
                    if self._box_to_widget_rect(box).contains(pos):
                        self.box_clicked.emit(box.text)
                        break
        super().mouseReleaseEvent(event)

    def _box_to_widget_rect(self, box: OCRBox) -> QRectF:
        r = self._last_draw_rect
        return QRectF(
            r.left() + box.x * r.width(),
            r.top() + box.y * r.height(),
            box.w * r.width(),
            box.h * r.height(),
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            bg_rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setBrush(QColor("#0B0B0E"))
            painter.setPen(QPen(QColor("#24242A"), 1.0))
            painter.drawRoundedRect(bg_rect, 9, 9)

            if self._pixmap is None or self._pixmap.isNull():
                self._last_draw_rect = QRectF()
                painter.setPen(QColor("#71717A"))
                painter.drawText(
                    self.rect().adjusted(24, 24, -24, -24),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    self._placeholder,
                )
                return

            avail_w = max(1.0, self.width() - 14.0)
            avail_h = max(1.0, self.height() - 14.0)
            pm_w = float(self._pixmap.width())
            pm_h = float(self._pixmap.height())
            base_scale = min(avail_w / pm_w, avail_h / pm_h)
            scale = base_scale * self._zoom

            draw_w = pm_w * scale
            draw_h = pm_h * scale
            left = (self.width() - draw_w) / 2.0 + self._pan.x()
            top = (self.height() - draw_h) / 2.0 + self._pan.y()
            draw_rect = QRectF(left, top, draw_w, draw_h)
            self._last_draw_rect = draw_rect

            painter.setClipRect(self.rect().adjusted(2, 2, -2, -2))
            painter.drawPixmap(draw_rect.toRect(), self._pixmap)

            # OCR highlight & interactive boxes
            if self._boxes:
                for box in self._boxes:
                    matched = self._is_match(box)
                    hovered = box is self._hovered_box
                    if not matched and not hovered and not self._show_all_boxes:
                        continue
                    box_rect = self._box_to_widget_rect(box).adjusted(-2.5, -2.5, 2.5, 2.5)
                    if matched:
                        painter.setBrush(QColor(245, 158, 11, 74))
                        painter.setPen(QPen(QColor("#F59E0B"), 2.0))
                    elif hovered:
                        painter.setBrush(QColor(56, 189, 248, 56))
                        painter.setPen(QPen(QColor("#38BDF8"), 1.6))
                    else:
                        painter.setBrush(QColor(56, 189, 248, 24))
                        painter.setPen(QPen(QColor(56, 189, 248, 125), 1.0))
                    painter.drawRoundedRect(box_rect, 3, 3)

            # Subtle zoom pill inside stage when zoomed
            if abs(self._zoom - 1.0) > 0.02:
                badge = QRectF(self.width() - 74, 12, 60, 22)
                painter.setBrush(QColor(17, 17, 20, 215))
                painter.setPen(QPen(QColor("#2E2E38"), 1.0))
                painter.drawRoundedRect(badge, 5, 5)
                painter.setPen(QColor("#38BDF8"))
                fnt = QFont(self.font())
                fnt.setPointSize(8)
                fnt.setBold(True)
                painter.setFont(fnt)
                painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"{self.zoom_percent}%")
        finally:
            painter.end()
