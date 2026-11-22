"""LocalRecall ana penceresi: Hibrit Arama, OCR Kutu Vurgulama, Önizleme ve Zaman Çizelgesi."""

from __future__ import annotations

import shutil
from collections import OrderedDict
from datetime import datetime, timedelta

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
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
from localrecall.config import AppConfig, set_windows_autostart
from localrecall.ocr.engine import OCRResult
from localrecall.search.hybrid import HybridSearchEngine
from localrecall.storage.database import CaptureRecord, Database
from localrecall.storage.media import MediaStore

from .preview_widget import InteractivePreviewWidget
from .settings_dialog import SettingsDialog
from .stats_dialog import StatsDialog
from .theme import create_app_icon


class MainWindow(QMainWindow):
    """LocalRecall ana arayüz penceresi."""

    capture_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    pause_state_changed = pyqtSignal(bool)
    config_changed = pyqtSignal(object)

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
        self.search_engine = HybridSearchEngine(db)

        self._force_quit = False
        self._timeline_records: list[CaptureRecord] = []
        self._current_record: CaptureRecord | None = None
        self._syncing_slider = False
        self._thumb_cache: OrderedDict[str, QIcon] = OrderedDict()

        self.setWindowTitle("LocalRecall — Offline Ekran Hafızası")
        self.setWindowIcon(create_app_icon(paused=capture_service.is_paused))
        self.resize(1320, 820)

        self._build_ui()
        self._setup_shortcuts()

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
        self.search_input.setPlaceholderText("Ara (Ctrl+F): Ekran metni, pencere başlığı veya uygulama…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        top_bar.addWidget(self.search_input, stretch=4)

        self.search_mode_combo = QComboBox()
        self.search_mode_combo.addItem("Hibrit (Akıllı)", "hybrid")
        self.search_mode_combo.addItem("Tam Metin (FTS5)", "fts")
        mode_idx = self.search_mode_combo.findData(self.config.search_mode)
        if mode_idx >= 0:
            self.search_mode_combo.setCurrentIndex(mode_idx)
        self.search_mode_combo.currentIndexChanged.connect(self._on_search_mode_changed)
        top_bar.addWidget(self.search_mode_combo)

        self.app_filter = QComboBox()
        self.app_filter.setMinimumWidth(145)
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

        self.stats_btn = QPushButton("İstatistik")
        self.stats_btn.clicked.connect(self.open_stats)
        top_bar.addWidget(self.stats_btn)

        self.settings_btn = QPushButton("Ayarlar")
        self.settings_btn.clicked.connect(self.open_settings)
        top_bar.addWidget(self.settings_btn)

        root_layout.addLayout(top_bar)

        # --- Orta Bölünmüş Alan (Sonuç Listesi | Önizleme + OCR) ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Sol: Küçük resimli sonuç listesi
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.results_header = QLabel("Kayıtlar (0)")
        self.results_header.setObjectName("metaLabel")
        left_layout.addWidget(self.results_header)

        self.results_list = QListWidget()
        self.results_list.setIconSize(QSize(96, 54))
        self.results_list.setWordWrap(True)
        self.results_list.currentItemChanged.connect(self._on_result_selected)
        left_layout.addWidget(self.results_list)
        main_splitter.addWidget(left_panel)

        # Sağ: İnteraktif görüntü önizleme + OCR metni
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)

        meta_bar = QHBoxLayout()
        meta_bar.setSpacing(6)
        self.meta_label = QLabel("Seçili kayıt yok")
        self.meta_label.setObjectName("metaLabel")
        meta_bar.addWidget(self.meta_label, stretch=1)

        self.show_boxes_btn = QPushButton("OCR Kutuları")
        self.show_boxes_btn.setCheckable(True)
        self.show_boxes_btn.setToolTip("Görüntü üzerinde tespit edilen tüm metin kutularını göster")
        self.show_boxes_btn.toggled.connect(self._on_toggle_all_boxes)
        meta_bar.addWidget(self.show_boxes_btn)

        self.export_btn = QPushButton("Görseli Kaydet")
        self.export_btn.clicked.connect(self._export_current_image)
        meta_bar.addWidget(self.export_btn)

        self.copy_ocr_btn = QPushButton("Metni Kopyala")
        self.copy_ocr_btn.clicked.connect(self._copy_ocr_text)
        meta_bar.addWidget(self.copy_ocr_btn)

        self.delete_btn = QPushButton("Sil")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._delete_current_record)
        meta_bar.addWidget(self.delete_btn)

        preview_layout.addLayout(meta_bar)

        self.preview_widget = InteractivePreviewWidget()
        self.preview_widget.setToolTip("Ctrl + Tekerlek: Yakınlaştır | Çift tık: Sıfırla | Metin kutusuna tıkla: Kopyala")
        self.preview_widget.box_clicked.connect(self._on_box_clicked)
        preview_layout.addWidget(self.preview_widget, stretch=1)
        right_splitter.addWidget(preview_container)

        # Alt sağ: OCR metni
        ocr_container = QWidget()
        ocr_layout = QVBoxLayout(ocr_container)
        ocr_layout.setContentsMargins(0, 4, 0, 0)
        ocr_layout.setSpacing(4)

        self.ocr_header = QLabel("Çıkarılan Metin (OCR)")
        self.ocr_header.setObjectName("metaLabel")
        ocr_layout.addWidget(self.ocr_header)

        self.ocr_view = QPlainTextEdit()
        self.ocr_view.setReadOnly(True)
        self.ocr_view.setPlaceholderText("Seçili ekran görüntüsünden çıkarılan metin burada görünür…")
        ocr_layout.addWidget(self.ocr_view)
        right_splitter.addWidget(ocr_container)

        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 1)

        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 5)

        root_layout.addWidget(main_splitter, stretch=1)

        # --- Alt Zaman Çizelgesi (Timeline) ---
        timeline_bar = QHBoxLayout()
        timeline_bar.setSpacing(8)

        timeline_title = QLabel("Zaman Çizelgesi:")
        timeline_title.setObjectName("metaLabel")
        timeline_bar.addWidget(timeline_title)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedWidth(34)
        self.prev_btn.setToolTip("Önceki kayıt (Sol Ok)")
        self.prev_btn.clicked.connect(lambda: self._step_timeline(-1))
        timeline_bar.addWidget(self.prev_btn)

        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(0)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.valueChanged.connect(self._on_timeline_moved)
        timeline_bar.addWidget(self.timeline_slider, stretch=1)

        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedWidth(34)
        self.next_btn.setToolTip("Sonraki kayıt (Sağ Ok)")
        self.next_btn.clicked.connect(lambda: self._step_timeline(1))
        timeline_bar.addWidget(self.next_btn)

        self.timeline_label = QLabel("—")
        self.timeline_label.setObjectName("metaLabel")
        self.timeline_label.setMinimumWidth(155)
        self.timeline_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        timeline_bar.addWidget(self.timeline_label)

        root_layout.addLayout(timeline_bar)

        self.setCentralWidget(central)

        # Durum çubuğu
        self.stats_label = QLabel("")
        self.statusBar().addPermanentWidget(self.stats_label)
        self._update_pause_ui(self.capture_service.is_paused)

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self._step_timeline(-1))
        QShortcut(QKeySequence("Alt+Right"), self, activated=lambda: self._step_timeline(1))
        QShortcut(QKeySequence("Delete"), self, activated=self._delete_current_record)

    # --- Genel İşlemler ---

    def bring_to_front_and_focus_search(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.focus_search()

    def focus_search(self) -> None:
        self.search_input.setFocus()
        self.search_input.selectAll()

    def request_quit(self) -> None:
        self._force_quit = True
        self.close()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        if self._force_quit:
            if event:
                event.accept()
            return
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

    def purge_last_15_minutes(self) -> None:
        removed = self.capture_service.purge_last_minutes(15)
        self._current_record = None
        self._thumb_cache.clear()
        self.refresh_all()
        self.statusBar().showMessage(f"Son 15 dakikadan {removed} kayıt kalıcı olarak silindi.", 5000)

    def open_stats(self) -> None:
        dlg = StatsDialog(self.db, self.media, self.capture_service, parent=self)
        dlg.exec()
        if dlg.changed:
            self._current_record = None
            self._thumb_cache.clear()
            self.refresh_all()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.config, parent=self)
        if dlg.exec():
            updated = dlg.build_updated_config()
            updated.save()
            set_windows_autostart(updated.auto_start)
            self.capture_service.apply_config(updated)
            self.config_changed.emit(updated)
            self.statusBar().showMessage("Ayarlar kaydedildi ve uygulandı.", 4000)

    # --- Veri Yenileme ---

    def refresh_all(self) -> None:
        self._refresh_apps_combo()
        self._refresh_timeline()
        self.refresh_results()
        self._refresh_stats()

    def _get_thumbnail(self, rel_path: str) -> QIcon:
        cached = self._thumb_cache.get(rel_path)
        if cached is not None:
            self._thumb_cache.move_to_end(rel_path)
            return cached

        full_path = self.media.resolve_path(rel_path)
        if not full_path.exists():
            return QIcon()

        pm = QPixmap(str(full_path))
        if pm.isNull():
            return QIcon()

        thumb = pm.scaled(
            96,
            54,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        icon = QIcon(thumb)
        self._thumb_cache[rel_path] = icon
        if len(self._thumb_cache) > 250:
            self._thumb_cache.popitem(last=False)
        return icon

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

    def _on_search_text_changed(self, text: str) -> None:
        self.preview_widget.set_highlight_query(text)
        self._search_timer.start()

    def _on_search_mode_changed(self) -> None:
        mode = str(self.search_mode_combo.currentData() or "hybrid")
        self.config.search_mode = mode
        self.config.save()
        self.refresh_results()

    def refresh_results(self) -> None:
        query = self.search_input.text().strip()
        mode = str(self.search_mode_combo.currentData() or "hybrid")
        app_name = self.app_filter.currentData() or None
        start_dt, end_dt = self._get_date_range()

        results = self.search_engine.search(
            query=query,
            mode=mode,
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
            title = rec.window_title[:52] if rec.window_title else "(Başlıksız)"
            snippet_line = res.snippet.replace("\n", " ").strip()[:72]
            badge = " [Yakın]" if res.match_type == "fuzzy" else ""
            label = f"{ts_short}  •  {rec.app_name or 'Ekran'}{badge}\n{title}"
            if snippet_line:
                label += f"\n{snippet_line}"

            item = QListWidgetItem(self._get_thumbnail(rec.image_path), label)
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

    # --- Seçim, Zaman Çizelgesi ve Görüntüleme ---

    def _step_timeline(self, delta: int) -> None:
        if not self._timeline_records:
            return
        new_val = max(0, min(len(self._timeline_records) - 1, self.timeline_slider.value() + delta))
        self.timeline_slider.setValue(new_val)

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

    def _on_toggle_all_boxes(self, checked: bool) -> None:
        self.preview_widget.set_show_all_boxes(checked)

    def _on_box_clicked(self, text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard and text:
            clipboard.setText(text)
            self.statusBar().showMessage(f"Kutu metni kopyalandı: {text[:60]}", 3000)

    def _show_record(self, record: CaptureRecord | None, sync_slider: bool = True) -> None:
        self._current_record = record
        if record is None:
            self.meta_label.setText("Seçili kayıt yok")
            self.preview_widget.set_image(None)
            self.preview_widget.set_ocr_boxes([])
            self.ocr_view.setPlainText("")
            self.ocr_header.setText("Çıkarılan Metin (OCR)")
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
            self.preview_widget.set_image(pixmap)
        else:
            self.preview_widget.set_image(None, placeholder="Görüntü dosyası bulunamadı.")

        boxes = OCRResult.parse_boxes(record.ocr_boxes)
        self.preview_widget.set_ocr_boxes(boxes)
        self.preview_widget.set_highlight_query(self.search_input.text())

        matched_cnt = self.preview_widget.matched_box_count
        if matched_cnt > 0:
            self.ocr_header.setText(
                f"Çıkarılan Metin (OCR) — Görselde {matched_cnt} eşleşen kutu vurgulandı"
            )
        else:
            self.ocr_header.setText(f"Çıkarılan Metin (OCR) — {len(boxes)} metin kutusu")

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

    def _export_current_image(self) -> None:
        if not self._current_record:
            return
        src = self.media.resolve_path(self._current_record.image_path)
        if not src.exists():
            self.statusBar().showMessage("Kaynak görüntü dosyası bulunamadı.", 4000)
            return
        default_name = f"localrecall_{self._current_record.timestamp.replace(':', '-')}.png"
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Ekran Görüntüsünü Kaydet",
            default_name,
            "PNG Görüntü (*.png);;WebP Görüntü (*.webp)",
        )
        if not target_path:
            return
        if target_path.lower().endswith(".webp"):
            shutil.copy2(src, target_path)
        else:
            pm = QPixmap(str(src))
            pm.save(target_path, "PNG")
        self.statusBar().showMessage(f"Görüntü kaydedildi: {target_path}", 4000)

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
            self._thumb_cache.pop(rel_path, None)
            self.media.delete_image(rel_path)
        self._current_record = None
        self.refresh_all()
        self.statusBar().showMessage("Kayıt silindi.", 3000)

    # --- Arka Plan Sinyalleri ---

    def _on_capture_updated(self, capture_id: int) -> None:
        self._refresh_apps_combo()
        self._refresh_timeline()
        self._refresh_stats()
        if not self.search_input.text().strip():
            self.refresh_results()
        elif self._current_record and self._current_record.id == capture_id:
            rec = self.db.get_capture(capture_id)
            if rec:
                self._show_record(rec)

    def _on_status_updated(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
