"""OCR bounding box vurgulamalı, yakınlaştırılabilir ekran görüntüsü önizleme bileşeni."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QWidget

from localrecall.ocr.engine import OCRBox
from localrecall.search.hybrid import normalize_for_matching


class InteractivePreviewWidget(QWidget):
    """Ekran görüntüsü önizleme + aranan kelime kutusu vurgulama + zoom + tıklayarak metin kopyalama."""

    box_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 220)
        self.setMouseTracking(True)
        self._pixmap: QPixmap | None = None
        self._boxes: list[OCRBox] = []
        self._highlight_tokens: list[str] = []
        self._show_all_boxes = False
        self._zoom = 1.0
        self._placeholder = "Henüz seçili ekran görüntüsü yok."
        self._last_draw_rect = QRectF()

    def set_image(self, pixmap: QPixmap | None, placeholder: str = "Henüz seçili ekran görüntüsü yok.") -> None:
        self._pixmap = pixmap
        self._placeholder = placeholder
        self._zoom = 1.0
        self.update()

    def set_ocr_boxes(self, boxes: list[OCRBox]) -> None:
        self._boxes = boxes
        self.update()

    def set_highlight_query(self, query: str) -> None:
        norm = normalize_for_matching(query)
        self._highlight_tokens = [t for t in norm.split() if len(t) >= 2]
        self.update()

    def set_show_all_boxes(self, enabled: bool) -> None:
        self._show_all_boxes = enabled
        self.update()

    def reset_zoom(self) -> None:
        self._zoom = 1.0
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

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None or self._pixmap is None or self._pixmap.isNull():
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else (1.0 / 1.15)
            self._zoom = max(0.5, min(3.5, self._zoom * factor))
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        self.reset_zoom()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._last_draw_rect.isEmpty() and self._boxes:
            pos = event.position()
            for box in self._boxes:
                rect = self._box_to_widget_rect(box)
                if rect.contains(pos):
                    self.box_clicked.emit(box.text)
                    break
        super().mousePressEvent(event)

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Arka plan çerçevesi
        bg_rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QColor("#0b0e14"))
        painter.setPen(QPen(QColor("#30363d"), 1.0))
        painter.drawRoundedRect(bg_rect, 8, 8)

        if self._pixmap is None or self._pixmap.isNull():
            self._last_draw_rect = QRectF()
            painter.setPen(QColor("#8b949e"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            painter.end()
            return

        # Oranı koruyarak çizim alanını hesapla
        avail_w = max(1.0, self.width() - 12.0)
        avail_h = max(1.0, self.height() - 12.0)
        pm_w = float(self._pixmap.width())
        pm_h = float(self._pixmap.height())
        base_scale = min(avail_w / pm_w, avail_h / pm_h)
        scale = base_scale * self._zoom

        draw_w = pm_w * scale
        draw_h = pm_h * scale
        left = (self.width() - draw_w) / 2.0
        top = (self.height() - draw_h) / 2.0
        draw_rect = QRectF(left, top, draw_w, draw_h)
        self._last_draw_rect = draw_rect

        painter.setClipRect(self.rect().adjusted(2, 2, -2, -2))
        painter.drawPixmap(draw_rect.toRect(), self._pixmap)

        # OCR kutularını çiz
        if self._boxes:
            for box in self._boxes:
                matched = self._is_match(box)
                if not matched and not self._show_all_boxes:
                    continue
                box_rect = self._box_to_widget_rect(box).adjusted(-2, -2, 2, 2)
                if matched:
                    painter.setBrush(QColor(255, 208, 0, 72))
                    painter.setPen(QPen(QColor(255, 208, 0, 235), 2.0))
                else:
                    painter.setBrush(QColor(88, 166, 255, 32))
                    painter.setPen(QPen(QColor(88, 166, 255, 140), 1.0))
                painter.drawRoundedRect(box_rect, 3, 3)

        # Zoom göstergesi
        if abs(self._zoom - 1.0) > 0.02:
            badge = QRectF(self.width() - 96, 12, 82, 24)
            painter.setBrush(QColor(15, 17, 23, 200))
            painter.setPen(QPen(QColor("#30363d"), 1.0))
            painter.drawRoundedRect(badge, 5, 5)
            painter.setPen(QColor("#e6edf3"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"{int(self._zoom * 100)}%")

        painter.end()
