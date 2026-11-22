"""LocalRecall ana penceresi: Arama, Ekran Görüntüsü Önizleme, OCR Metni ve Zaman Çizelgesi."""

from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from localrecall.capture.monitor import CaptureService
from localrecall.config import AppConfig
from localrecall.storage.database import CaptureRecord, Database
from localrecall.storage.media import MediaStore

from .settings_dialog import SettingsDialog
from .theme import create_app_icon


class _PreviewLabel(QLabel):
    """Pencere yeniden boyutlandırıldığında pixmap'i oranını koruyarak ölçekleyen etiket."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("previewFrame")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 200)
        self._pixmap: QPixmap | None = None

    def set_full_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self._refresh_scaled()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._refresh_scaled()

    def _refresh_scaled(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self.setPixmap(QPixmap())
            if not self.text():
                self.setText("Henüz seçili ekran görüntüsü yok.")
            return
        self.setText("")
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


class MainWindow(QMainWindow):
    """LocalRecall ana arayüz penceresi."""

    capture_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    pause_state_changed = pyqtSignal(bool)

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        media: MediaStore,
        capture_service: CaptureService,
    ) -> None:
        super().__init__()
        self.config = config
        self.db = db
        self.media = media
        self.capture_service = capture_service

        self._force_quit = False
        self._timeline_records: list[CaptureRecord] = []
        self._current_record: CaptureRecord | None = None
        self._syncing_slider = False

        self.setWindowTitle("LocalRecall — Offline Ekran Hafızası")
        self.setWindowIcon(create_app_icon(paused=capture_service.is_paused))
        self.resize(1240, 780)

        self._build_ui()

        # Debounce arama zamanlayıcısı
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.refresh_results)

        # Arka plan sinyallerini UI thread'ine bağla
        self.capture_updated.connect(self._on_capture_updated)
        self.status_updated.connect(self._on_status_updated)

        self.refresh_all()

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 8)
        root_layout.setSpacing(10)

        # --- Üst Araç Çubuğu ---
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Ekran metinlerinde, pencere başlıklarında veya uygulamalarda ara…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(lambda _: self._search_timer.start())
        top_bar.addWidget(self.search_input, stretch=4)

        self.app_filter = QComboBox()
        self.app_filter.setMinimumWidth(150)
        self.app_filter.addItem("Tüm Uygulamalar", "")
        self.app_filter.currentIndexChanged.connect(lambda _: self.refresh_results())
        top_bar.addWidget(self.app_filter, stretch=1)

        self.date_filter = QComboBox()
        self.date_filter.addItem("Tüm Zamanlar", "all")
        self.date_filter.addItem("Bugün", "today")
        self.date_filter.addItem("Son 7 Gün", "7d")
        self.date_filter.addItem("Son 30 Gün", "30d")
        self.date_filter.currentIndexChanged.connect(lambda _: self.refresh_results())
        top_bar.addWidget(self.date_filter)

        self.pause_btn = QPushButton("Duraklat")
        self.pause_btn.clicked.connect(self.toggle_pause)
        top_bar.addWidget(self.pause_btn)

        self.capture_now_btn = QPushButton("Şimdi Yakala")
        self.capture_now_btn.setObjectName("primaryButton")
        self.capture_now_btn.clicked.connect(self.capture_now)
        top_bar.addWidget(self.capture_now_btn)

        self.settings_btn = QPushButton("Ayarlar")
        self.settings_btn.clicked.connect(self.open_settings)
        top_bar.addWidget(self.settings_btn)

        root_layout.addLayout(top_bar)

        # --- Orta Bölünmüş Alan (Sonuç Listesi | Önizleme + OCR) ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Sol: Sonuç listesi
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.results_header = QLabel("Kayıtlar (0)")
        self.results_header.setObjectName("metaLabel")
        left_layout.addWidget(self.results_header)

        self.results_list = QListWidget()
        self.results_list.currentItemChanged.connect(self._on_result_selected)
        left_layout.addWidget(self.results_list)
        main_splitter.addWidget(left_panel)

        # Sağ: Görüntü önizleme + OCR metni
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)

        meta_bar = QHBoxLayout()
        self.meta_label = QLabel("Seçili kayıt yok")
        self.meta_label.setObjectName("metaLabel")
        meta_bar.addWidget(self.meta_label, stretch=1)

        self.copy_ocr_btn = QPushButton("OCR Metnini Kopyala")
        self.copy_ocr_btn.clicked.connect(self._copy_ocr_text)
        meta_bar.addWidget(self.copy_ocr_btn)

        self.delete_btn = QPushButton("Kaydı Sil")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._delete_current_record)
        meta_bar.addWidget(self.delete_btn)

        preview_layout.addLayout(meta_bar)

        self.preview_label = _PreviewLabel()
        preview_layout.addWidget(self.preview_label, stretch=1)
        right_splitter.addWidget(preview_container)

        # Alt sağ: OCR metni
        ocr_container = QWidget()
        ocr_layout = QVBoxLayout(ocr_container)
        ocr_layout.setContentsMargins(0, 4, 0, 0)
        ocr_layout.setSpacing(4)

        ocr_title = QLabel("Çıkarılan Metin (OCR)")
        ocr_title.setObjectName("metaLabel")
        ocr_layout.addWidget(ocr_title)

        self.ocr_view = QPlainTextEdit()
        self.ocr_view.setReadOnly(True)
        self.ocr_view.setPlaceholderText("Seçili ekran görüntüsünden çıkarılan metin burada görünür…")
        ocr_layout.addWidget(self.ocr_view)
        right_splitter.addWidget(ocr_container)

        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 1)

        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)

        root_layout.addWidget(main_splitter, stretch=1)

        # --- Alt Zaman Çizelgesi (Timeline) ---
        timeline_bar = QHBoxLayout()
        timeline_bar.setSpacing(10)

        timeline_title = QLabel("Zaman Çizelgesi:")
        timeline_title.setObjectName("metaLabel")
        timeline_bar.addWidget(timeline_title)

        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(0)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.valueChanged.connect(self._on_timeline_moved)
        timeline_bar.addWidget(self.timeline_slider, stretch=1)

        self.timeline_label = QLabel("—")
        self.timeline_label.setObjectName("metaLabel")
        self.timeline_label.setMinimumWidth(145)
        self.timeline_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        timeline_bar.addWidget(self.timeline_label)

        root_layout.addLayout(timeline_bar)

        self.setCentralWidget(central)

        # Durum çubuğu
        self.stats_label = QLabel("")
        self.statusBar().addPermanentWidget(self.stats_label)
        self._update_pause_ui(self.capture_service.is_paused)

    # --- Genel İşlemler ---

    def request_quit(self) -> None:
        self._force_quit = True
        self.close()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        if self._force_quit:
            if event:
                event.accept()
            return
        # Pencere kapatıldığında sistem tepsisine gizle
        self.hide()
        if event:
            event.ignore()

    def toggle_pause(self) -> None:
        paused = self.capture_service.toggle_pause()
        self._update_pause_ui(paused)
        self.pause_state_changed.emit(paused)

    def _update_pause_ui(self, paused: bool) -> None:
        self.pause_btn.setText("Devam Et" if paused else "Duraklat")
        self.setWindowIcon(create_app_icon(paused=paused))

    def capture_now(self) -> None:
        capture_id = self.capture_service.capture_once(force=True)
        if capture_id is None:
            self.statusBar().showMessage("Yakalama gizlilik filtresi nedeniyle atlandı.", 4000)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.config, parent=self)
        if dlg.exec():
            updated = dlg.build_updated_config()
            updated.save()
            self.capture_service.apply_config(updated)
            self.statusBar().showMessage("Ayarlar kaydedildi ve uygulandı.", 4000)

    # --- Veri Yenileme ---

    def refresh_all(self) -> None:
        self._refresh_apps_combo()
        self._refresh_timeline()
        self.refresh_results()
        self._refresh_stats()

    def _refresh_apps_combo(self) -> None:
        current = self.app_filter.currentData() or ""
        apps = self.db.list_apps()
        self.app_filter.blockSignals(True)
        self.app_filter.clear()
        self.app_filter.addItem("Tüm Uygulamalar", "")
        for app in apps:
            self.app_filter.addItem(app, app)
        idx = self.app_filter.findData(current)
        if idx >= 0:
            self.app_filter.setCurrentIndex(idx)
        self.app_filter.blockSignals(False)

    def _refresh_timeline(self) -> None:
        self._timeline_records = self.db.get_timeline(limit=1000)
        self._syncing_slider = True
        count = len(self._timeline_records)
        if count > 0:
            self.timeline_slider.setEnabled(True)
            self.timeline_slider.setMinimum(0)
            self.timeline_slider.setMaximum(count - 1)
            if self._current_record:
                for i, rec in enumerate(self._timeline_records):
                    if rec.id == self._current_record.id:
                        self.timeline_slider.setValue(i)
                        break
            else:
                self.timeline_slider.setValue(count - 1)
        else:
            self.timeline_slider.setEnabled(False)
            self.timeline_slider.setMaximum(0)
            self.timeline_label.setText("—")
        self._syncing_slider = False

    def _get_date_range(self) -> tuple[datetime | None, datetime | None]:
        mode = self.date_filter.currentData()
        now = datetime.now()
        if mode == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0), None
        if mode == "7d":
            return now - timedelta(days=7), None
        if mode == "30d":
            return now - timedelta(days=30), None
        return None, None

    def refresh_results(self) -> None:
        query = self.search_input.text().strip()
        app_name = self.app_filter.currentData() or None
        start_dt, end_dt = self._get_date_range()

        results = self.db.search(
            query=query,
            app_name=app_name,
            start=start_dt,
            end=end_dt,
            limit=150,
        )

        selected_id = self._current_record.id if self._current_record else None
        self.results_list.blockSignals(True)
        self.results_list.clear()

        restored_row = -1
        for idx, res in enumerate(results):
            rec = res.record
            ts_short = rec.timestamp.replace("T", " ")
            title = rec.window_title[:60] if rec.window_title else "(Başlıksız)"
            snippet_line = res.snippet.replace("\n", " ").strip()[:80]
            label = f"{ts_short}  •  {rec.app_name or 'Ekran'}\n{title}"
            if snippet_line:
                label += f"\n{snippet_line}"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, rec.id)
            self.results_list.addItem(item)
            if selected_id is not None and rec.id == selected_id:
                restored_row = idx

        self.results_list.blockSignals(False)
        self.results_header.setText(f"Kayıtlar ({len(results)})")

        if restored_row >= 0:
            self.results_list.setCurrentRow(restored_row)
            rec = self.db.get_capture(selected_id)
            if rec:
                self._show_record(rec)
        elif results:
            self.results_list.setCurrentRow(0)
            self._show_record(results[0].record)
        else:
            self._show_record(None)

    def _refresh_stats(self) -> None:
        stats = self.db.get_stats()
        size_mb = self.media.total_size_bytes() / (1024 * 1024)
        pending = self.capture_service.ocr_worker.pending_count
        self.stats_label.setText(
            f"Toplam: {stats['total']}  |  OCR: {stats['ocr_done']} (Kuyruk: {pending})  |  Disk: {size_mb:.1f} MB"
        )

    # --- Seçim ve Görüntüleme ---

    def _on_result_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        capture_id = current.data(Qt.ItemDataRole.UserRole)
        if capture_id is None:
            return
        rec = self.db.get_capture(int(capture_id))
        if rec:
            self._show_record(rec)

    def _on_timeline_moved(self, index: int) -> None:
        if self._syncing_slider:
            return
        if 0 <= index < len(self._timeline_records):
            rec = self._timeline_records[index]
            fresh = self.db.get_capture(rec.id) or rec
            self._show_record(fresh, sync_slider=False)

    def _show_record(self, record: CaptureRecord | None, sync_slider: bool = True) -> None:
        self._current_record = record
        if record is None:
            self.meta_label.setText("Seçili kayıt yok")
            self.preview_label.set_full_pixmap(None)
            self.ocr_view.setPlainText("")
            self.timeline_label.setText("—")
            return

        ts_human = record.timestamp.replace("T", " ")
        self.meta_label.setText(
            f"{ts_human}  |  {record.app_name or 'Bilinmiyor'}  |  {record.window_title or '(Başlıksız)'}"
        )
        self.timeline_label.setText(ts_human)

        img_path = self.media.resolve_path(record.image_path)
        if img_path.exists():
            pixmap = QPixmap(str(img_path))
            self.preview_label.set_full_pixmap(pixmap)
        else:
            self.preview_label.setText("Görüntü dosyası bulunamadı.")
            self.preview_label.set_full_pixmap(None)

        if record.ocr_done:
            self.ocr_view.setPlainText(record.ocr_text or "(Metin bulunamadı)")
        else:
            self.ocr_view.setPlainText("OCR işleniyor…")

        if sync_slider and self._timeline_records:
            self._syncing_slider = True
            for i, item in enumerate(self._timeline_records):
                if item.id == record.id:
                    self.timeline_slider.setValue(i)
                    break
            self._syncing_slider = False

    def _copy_ocr_text(self) -> None:
        text = self.ocr_view.toPlainText().strip()
        if text:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
            self.statusBar().showMessage("OCR metni panoya kopyalandı.", 3000)

    def _delete_current_record(self) -> None:
        if not self._current_record:
            return
        reply = QMessageBox.question(
            self,
            "Kaydı Sil",
            "Seçili ekran görüntüsü ve OCR kaydı kalıcı olarak silinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        capture_id = self._current_record.id
        rel_path = self.db.delete_capture(capture_id)
        if rel_path:
            self.media.delete_image(rel_path)
        self._current_record = None
        self.refresh_all()
        self.statusBar().showMessage("Kayıt silindi.", 3000)

    # --- Arka Plan Sinyalleri ---

    def _on_capture_updated(self, capture_id: int) -> None:
        self._refresh_apps_combo()
        self._refresh_timeline()
        self._refresh_stats()
        # Eğer kullanıcı aktif olarak arama yapmıyorsa veya görüntülediği kayıt güncellendiyse yenile
        if not self.search_input.text().strip():
            self.refresh_results()
        elif self._current_record and self._current_record.id == capture_id:
            rec = self.db.get_capture(capture_id)
            if rec:
                self._show_record(rec)

    def _on_status_updated(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
