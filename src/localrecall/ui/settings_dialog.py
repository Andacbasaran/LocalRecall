"""Ayarlar ve gizlilik kara listesi yönetim penceresi."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from localrecall.config import AppConfig


class SettingsDialog(QDialog):
    """Yakalama, OCR, saklama ve gizlilik kurallarını düzenleme iletişim kutusu."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LocalRecall Ayarları")
        self.setMinimumWidth(480)
        self._config = config

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.5, 60.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setSuffix(" sn")
        self.interval_spin.setValue(config.capture_interval_sec)
        form.addRow("Yakalama Aralığı:", self.interval_spin)

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

        self.ocr_check = QCheckBox("RapidOCR (ONNX CPU) ile otomatik metin çıkar")
        self.ocr_check.setChecked(config.ocr_enabled)
        form.addRow("OCR Motoru:", self.ocr_check)

        layout.addLayout(form)

        layout.addWidget(QLabel("Hariç Tutulan Uygulamalar (her satıra bir süreç adı, örn. 1password.exe):"))
        self.processes_edit = QPlainTextEdit()
        self.processes_edit.setMaximumHeight(110)
        self.processes_edit.setPlainText("\n".join(config.blocked_processes))
        layout.addWidget(self.processes_edit)

        layout.addWidget(QLabel("Hariç Tutulan Pencere Başlığı Anahtar Kelimeleri (her satıra bir kelime):"))
        self.keywords_edit = QPlainTextEdit()
        self.keywords_edit.setMaximumHeight(110)
        self.keywords_edit.setPlainText("\n".join(config.blocked_title_keywords))
        layout.addWidget(self.keywords_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_updated_config(self) -> AppConfig:
        """Formdaki değerleri mevcut AppConfig kopyasına uygular."""
        self._config.capture_interval_sec = float(self.interval_spin.value())
        self._config.diff_threshold = float(self.diff_spin.value())
        self._config.webp_quality = int(self.quality_spin.value())
        self._config.retention_days = int(self.retention_spin.value())
        self._config.ocr_enabled = self.ocr_check.isChecked()
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
