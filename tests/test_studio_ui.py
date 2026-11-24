"""Offscreen PyQt6 Studio 2.0 UI integration tests for MainWindow & InteractivePreviewWidget."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QApplication

from localrecall.capture.monitor import CaptureService
from localrecall.capture.pii import PII_MODE_REDACT_TEXT
from localrecall.config import AppConfig
from localrecall.ocr.engine import OCRBox
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore
from localrecall.ui.main_window import MainWindow
from localrecall.ui.preview_widget import InteractivePreviewWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def studio_env(tmp_path, qapp, monkeypatch):
    # Prevent UI tests from touching OS login autostart registries/plists
    monkeypatch.setattr("localrecall.ui.main_window.set_autostart", lambda _enabled: True)

    cfg = AppConfig(
        data_dir=str(tmp_path),
        ui_language="en",
        check_updates_on_startup=False,
        pause_on_start=True,
        ocr_enabled=False,
        monitor_index=1,
    )
    cfg.save()
    db = Database(cfg.db_path)
    media = MediaStore(cfg.captures_dir, quality=75, max_width=1280)
    svc = CaptureService(config=cfg, db=db, media=media)
    win = MainWindow(config=cfg, db=db, media=media, capture_service=svc)
    win.resize(1140, 680)
    try:
        yield win, cfg, db, media, svc, qapp
    finally:
        win.request_quit()
        svc.stop()
        qapp.processEvents()
        db.close()
        win.deleteLater()
        qapp.processEvents()


def test_main_window_switches_all_four_tabs_and_retranslates(studio_env):
    win, cfg, _db, _media, _svc, qapp = studio_env

    for tab_idx in (0, 1, 2, 3, 0):
        win.switch_tab(tab_idx)
        qapp.processEvents()
        assert win.stack.currentIndex() == tab_idx
        assert win._current_tab == tab_idx

    # Live bilingual EN -> TR -> EN switch via Settings language combo
    tr_idx = win.lang_combo.findData("tr")
    assert tr_idx >= 0
    win.lang_combo.setCurrentIndex(tr_idx)
    qapp.processEvents()
    assert win.i18n.lang == "tr"
    assert cfg.ui_language == "tr"
    assert "Çevrimdışı" in win.windowTitle()
    assert win.btn_nav_privacy._lbl.text() == "Gizlilik Kalkanı"

    en_idx = win.lang_combo.findData("en")
    assert en_idx >= 0
    win.lang_combo.setCurrentIndex(en_idx)
    qapp.processEvents()
    assert win.i18n.lang == "en"
    assert "Offline" in win.windowTitle()
    assert win.btn_nav_privacy._lbl.text() == "Privacy Shield"


def test_demo_timeline_loader_search_pin_and_notes(studio_env):
    win, _cfg, db, _media, _svc, qapp = studio_env

    win.load_demo_timeline()
    qapp.processEvents()
    assert db.get_stats()["total"] == 8
    assert win.results_list.count() == 8
    assert len(win._timeline_records) == 8

    # Search with Amber match box highlighting
    win.search_input.setText("LocalRecall")
    win.refresh_results(sync=True)
    qapp.processEvents()
    assert win.results_list.count() >= 5
    assert win.preview_widget.matched_box_count >= 1

    # Save bookmark note & toggle pin on current record
    assert win._current_record is not None
    cur_id = win._current_record.id
    orig_pinned = win._current_record.pinned
    win.note_input.setText("Verified Studio UI note")
    win._save_current_note()
    win._toggle_pin_current()
    qapp.processEvents()

    refreshed = db.get_capture(cur_id)
    assert refreshed is not None
    assert refreshed.note == "Verified Studio UI note"
    assert refreshed.pinned is (not orig_pinned)

    # Insights tab populates telemetry & app breakdown cleanly
    win.switch_tab(1)
    qapp.processEvents()
    assert win.kpi_captures.lbl_val.text() == "8"
    assert win.apps_breakdown_layout.count() >= 4


def test_monitor_index_zero_all_monitors_and_privacy_rules_persist(studio_env):
    win, cfg, _db, _media, svc, qapp = studio_env

    # Ensure option 0 ("All Monitors") exists in monitor_combo
    zero_idx = win.monitor_combo.findData(0)
    if zero_idx < 0:
        win.monitor_combo.insertItem(0, "All Monitors (3840×1080)", 0)
        zero_idx = 0
    win.monitor_combo.setCurrentIndex(zero_idx)
    assert win.monitor_combo.currentData() == 0

    win.save_settings_from_page()
    qapp.processEvents()
    assert cfg.monitor_index == 0

    reloaded = AppConfig.load(cfg.data_path)
    assert reloaded.monitor_index == 0

    # Privacy page persistence
    win.switch_tab(2)
    mode_idx = win.pii_mode_combo.findData(PII_MODE_REDACT_TEXT)
    assert mode_idx >= 0
    win.pii_mode_combo.setCurrentIndex(mode_idx)
    win.processes_edit.setPlainText("bitwarden\nmysecretvault")
    win._save_privacy_rules()
    qapp.processEvents()

    assert cfg.pii_redaction_mode == PII_MODE_REDACT_TEXT
    assert svc.pii_redactor.mode == PII_MODE_REDACT_TEXT
    reloaded_priv = AppConfig.load(cfg.data_path)
    assert "mysecretvault" in reloaded_priv.blocked_processes


def test_interactive_preview_widget_zoom_and_box_highlights(qapp):
    widget = InteractivePreviewWidget()
    widget.resize(640, 360)

    pix = QPixmap(800, 450)
    pix.fill(QColor("#141418"))

    zoom_events: list[int] = []
    widget.zoom_changed.connect(zoom_events.append)

    widget.set_image(pix)
    assert widget.zoom_percent == 100

    widget.zoom_in()
    assert widget.zoom_percent == 120
    widget.set_zoom(10.0)  # Clamps at 400%
    assert widget.zoom_percent == 400
    widget.set_zoom(0.1)  # Clamps at 50%
    assert widget.zoom_percent == 50
    widget.reset_zoom()
    assert widget.zoom_percent == 100
    assert 400 in zoom_events and 50 in zoom_events

    boxes = [
        OCRBox(text="LocalRecall hızlı ekran hafızası", x=0.1, y=0.2, w=0.5, h=0.08, score=0.98),
        OCRBox(text="Unrelated terminal line", x=0.1, y=0.4, w=0.4, h=0.08, score=0.95),
    ]
    widget.set_ocr_boxes(boxes)
    widget.set_highlight_query('app:code "hizli ekran"')
    assert widget.matched_box_count == 1

    widget.set_show_all_boxes(True)
    annotated = widget.render_annotated_pixmap(include_all_boxes=True)
    assert annotated is not None
    assert not annotated.isNull()
    assert annotated.width() == 800 and annotated.height() == 450

    rendered = widget.grab()
    assert not rendered.isNull()
    widget.close()
