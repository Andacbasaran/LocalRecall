"""Depolama, uygulama dağılımı ve gizlilik temizlik penceresi."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from localrecall.capture.monitor import CaptureService
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore


class StatsDialog(QDialog):
    """Uygulama kullanım istatistikleri, disk alanı ve hızlı temizlik araçları."""

    def __init__(
        self,
        db: Database,
        media: MediaStore,
        capture_service: CaptureService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.media = media
        self.capture_service = capture_service
        self.changed = False

        self.setWindowTitle("LocalRecall — İstatistikler ve Depolama")
        self.setMinimumSize(520, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Özet kartı
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet(
            "background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; font-size: 13px;"
        )
        layout.addWidget(self.summary_label)

        # Uygulama dağılımı
        layout.addWidget(QLabel("En Çok Kayıt Alınan Uygulamalar:"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.apps_container = QWidget()
        self.apps_layout = QVBoxLayout(self.apps_container)
        self.apps_layout.setContentsMargins(0, 0, 0, 0)
        self.apps_layout.setSpacing(6)
        scroll.setWidget(self.apps_container)
        layout.addWidget(scroll, stretch=1)

        # Hızlı aksiyonlar
        actions_row = QHBoxLayout()

        btn_purge_15 = QPushButton("Son 15 Dakikayı Sil")
        btn_purge_15.setObjectName("dangerButton")
        btn_purge_15.clicked.connect(self._purge_last_15)
        actions_row.addWidget(btn_purge_15)

        btn_retention = QPushButton("Eski Kayıtları Temizle")
        btn_retention.clicked.connect(self._run_retention)
        actions_row.addWidget(btn_retention)

        btn_vacuum = QPushButton("Veritabanını Sıkıştır")
        btn_vacuum.clicked.connect(self._run_vacuum)
        actions_row.addWidget(btn_vacuum)

        layout.addLayout(actions_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Kapat")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        self._refresh()

    def _refresh(self) -> None:
        stats = self.db.get_stats()
        img_mb = self.media.total_size_bytes() / (1024 * 1024)
        db_mb = (
            self.db.db_path.stat().st_size / (1024 * 1024)
            if self.db.db_path.exists()
            else 0.0
        )
        self.summary_label.setText(
            f"<b>Toplam Yakalama:</b> {stats['total']} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>OCR Tamamlanan:</b> {stats['ocr_done']}<br>"
            f"<b>Görsel Disk Alanı:</b> {img_mb:.2f} MB &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>Veritabanı:</b> {db_mb:.2f} MB<br>"
            f"<b>Veri Dizini:</b> {self.db.db_path.parent}"
        )

        # Eski uygulama satırlarını temizle
        while self.apps_layout.count():
            item = self.apps_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()

        breakdown = self.db.get_app_breakdown(limit=15)
        max_cnt = breakdown[0][1] if breakdown else 1
        if not breakdown:
            empty = QLabel("Henüz kayıt bulunmuyor.")
            empty.setObjectName("metaLabel")
            self.apps_layout.addWidget(empty)
        else:
            for app_name, count in breakdown:
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)

                lbl = QLabel(app_name)
                lbl.setMinimumWidth(160)
                row_layout.addWidget(lbl)

                bar = QProgressBar()
                bar.setMaximum(max_cnt)
                bar.setValue(count)
                bar.setFormat(f"{count} kayıt")
                bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row_layout.addWidget(bar, stretch=1)

                self.apps_layout.addWidget(row_widget)
        self.apps_layout.addStretch()

    def _purge_last_15(self) -> None:
        reply = QMessageBox.question(
            self,
            "Son 15 Dakikayı Sil",
            "Son 15 dakika içinde alınan tüm ekran görüntüleri ve OCR metinleri kalıcı olarak silinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = self.capture_service.purge_last_minutes(15)
        self.changed = True
        self._refresh()
        QMessageBox.information(self, "Temizlendi", f"Son 15 dakikadan {removed} kayıt silindi.")

    def _run_retention(self) -> None:
        removed = self.capture_service.run_retention_cleanup()
        self.changed = True
        self._refresh()
        QMessageBox.information(self, "Temizlik Tamamlandı", f"Saklama süresi dolan {removed} kayıt temizlendi.")

    def _run_vacuum(self) -> None:
        self.db.vacuum()
        self._refresh()
        QMessageBox.information(self, "Sıkıştırıldı", "SQLite veritabanı başarıyla sıkıştırıldı (VACUUM).")
