"""Ayarlar ve gizlilik kara listesi yönetim penceresi."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from localrecall.capture.window_info import list_monitors
from localrecall.config import AppConfig


class SettingsDialog(QDialog):
    """Yakalama, OCR, kısayol, başlangıç ve gizlilik kurallarını düzenleme penceresi."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LocalRecall Ayarları")
        self.setMinimumSize(520, 500)
        self._config = config

        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # --- Sekme 1: Genel & Yakalama ---
        general_tab = QWidget()
        form = QFormLayout(general_tab)
        form.setSpacing(10)

        self.monitor_combo = QComboBox()
        for idx, label in list_monitors():
            self.monitor_combo.addItem(label, idx)
        mon_pos = self.monitor_combo.findData(config.monitor_index)
        if mon_pos >= 0:
            self.monitor_combo.setCurrentIndex(mon_pos)
        form.addRow("Monitör:", self.monitor_combo)

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.5, 60.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setSuffix(" sn")
        self.interval_spin.setValue(config.capture_interval_sec)
        form.addRow("Yakalama Aralığı:", self.interval_spin)

        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(0, 600)
        self.idle_spin.setSingleStep(15)
        self.idle_spin.setSuffix(" sn (0 = kapalı)")
        self.idle_spin.setValue(int(config.idle_pause_sec))
        form.addRow("Boşta Uyku Süresi:", self.idle_spin)

        self.diff_spin = QDoubleSpinBox()
        self.diff_spin.setRange(0.001, 0.5)
        self.diff_spin.setDecimals(3)
        self.diff_spin.setSingleStep(0.005)
        self.diff_spin.setValue(config.diff_threshold)
        form.addRow("Frame Diff Eşiği:", self.diff_spin)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(30, 100)
        self.quality_spin.setSuffix(" %")
        self.quality_spin.setValue(config.webp_quality)
        form.addRow("WebP Kalitesi:", self.quality_spin)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 365)
        self.retention_spin.setSuffix(" gün")
        self.retention_spin.setValue(config.retention_days)
        form.addRow("Saklama Süresi:", self.retention_spin)

        self.ocr_check = QCheckBox("RapidOCR (ONNX CPU) ile otomatik metin ve konum çıkar")
        self.ocr_check.setChecked(config.ocr_enabled)
        form.addRow("OCR Motoru:", self.ocr_check)

        self.hotkey_check = QCheckBox("Global kısayol tuşunu etkinleştir")
        self.hotkey_check.setChecked(config.global_hotkey_enabled)
        form.addRow("Kısayol:", self.hotkey_check)

        self.hotkey_edit = QLineEdit(config.global_hotkey)
        self.hotkey_edit.setPlaceholderText("Örn: Ctrl+Shift+Space veya Alt+Space")
        form.addRow("Kısayol Tuşu:", self.hotkey_edit)

        self.autostart_check = QCheckBox("Windows açılışında sistem tepsisinde otomatik başlat")
        self.autostart_check.setChecked(config.auto_start)
        form.addRow("Başlangıç:", self.autostart_check)

        tabs.addTab(general_tab, "Genel ve Yakalama")

        # --- Sekme 2: Gizlilik Kara Listesi ---
        privacy_tab = QWidget()
        p_layout = QVBoxLayout(privacy_tab)
        p_layout.setSpacing(8)

        p_layout.addWidget(QLabel("Hariç Tutulan Uygulamalar (her satıra bir süreç adı, örn. 1password.exe):"))
        self.processes_edit = QPlainTextEdit()
        self.processes_edit.setPlainText("\n".join(config.blocked_processes))
        p_layout.addWidget(self.processes_edit, stretch=1)

        p_layout.addWidget(QLabel("Hariç Tutulan Pencere Başlığı Anahtar Kelimeleri (her satıra bir kelime):"))
        self.keywords_edit = QPlainTextEdit()
        self.keywords_edit.setPlainText("\n".join(config.blocked_title_keywords))
        p_layout.addWidget(self.keywords_edit, stretch=1)

        tabs.addTab(privacy_tab, "Gizlilik Filtresi")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_updated_config(self) -> AppConfig:
        """Formdaki değerleri mevcut AppConfig kopyasına uygular."""
        self._config.monitor_index = int(self.monitor_combo.currentData() or 1)
        self._config.capture_interval_sec = float(self.interval_spin.value())
        self._config.idle_pause_sec = float(self.idle_spin.value())
        self._config.diff_threshold = float(self.diff_spin.value())
        self._config.webp_quality = int(self.quality_spin.value())
        self._config.retention_days = int(self.retention_spin.value())
        self._config.ocr_enabled = self.ocr_check.isChecked()
        self._config.global_hotkey_enabled = self.hotkey_check.isChecked()
        self._config.global_hotkey = self.hotkey_edit.text().strip() or "Ctrl+Shift+Space"
        self._config.auto_start = self.autostart_check.isChecked()
        self._config.blocked_processes = [
            line.strip()
            for line in self.processes_edit.toPlainText().splitlines()
            if line.strip()
        ]
        self._config.blocked_title_keywords = [
            line.strip()
            for line in self.keywords_edit.toPlainText().splitlines()
            if line.strip()
        ]
        return self._config
