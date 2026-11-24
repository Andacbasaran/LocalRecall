"""LocalRecall Studio 2.0 Main Window — 4-Page Sidebar Architecture, Async Search & Timeline Ribbon."""

from __future__ import annotations

import shutil
import time
import webbrowser
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from localrecall import __version__
from localrecall.capture.diff import FrameDiffLock
from localrecall.capture.monitor import CaptureService
from localrecall.capture.pii import (
    PII_MODE_OFF,
    PII_MODE_REDACT_AND_BLUR,
    PII_MODE_REDACT_TEXT,
    PII_MODE_SKIP,
    PIIRedactor,
)
from localrecall.capture.window_info import (
    has_screen_recording_permission,
    list_monitors,
    request_screen_recording_permission,
)
from localrecall.config import AppConfig, get_default_hotkey, set_autostart
from localrecall.demo import export_daily_markdown_digest, populate_demo_timeline
from localrecall.hardware import (
    PROFILE_AUTO,
    PROFILE_BALANCED,
    PROFILE_ECO,
    PROFILE_PERFORMANCE,
    format_hardware_summary,
    get_ui_font_family,
)
from localrecall.i18n import LanguageManager
from localrecall.ocr.engine import OCRResult
from localrecall.search.hybrid import HybridSearchEngine
from localrecall.storage.database import CaptureRecord, Database, SearchResult
from localrecall.storage.media import MediaStore
from localrecall.updater import (
    UpdateCheckerThread,
    UpdateDownloadThread,
    UpdateInfo,
    apply_downloaded_update,
)

from .preview_widget import InteractivePreviewWidget
from .widgets import (
    FlatComboBox,
    FlatSwitch,
    HourlyActivityChartWidget,
    SidebarNavButton,
    TelemetryCard,
    TimelineRibbonWidget,
    app_color_for_name,
    create_app_icon,
    create_app_pixmap,
    make_flat_icon,
)

_ROLE_RECORD = Qt.ItemDataRole.UserRole + 1
_ROLE_SNIPPET = Qt.ItemDataRole.UserRole + 2
_ROLE_MATCH_TYPE = Qt.ItemDataRole.UserRole + 3
_ROLE_THUMB = Qt.ItemDataRole.UserRole + 4


def _format_relative_time(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts)
        diff = datetime.now() - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return dt.strftime("%H:%M")
        return dt.strftime("%b %d %H:%M")
    except Exception:
        return iso_ts[11:16] if len(iso_ts) >= 16 else iso_ts


class ResultCardDelegate(QStyledItemDelegate):
    """High-DPI custom card renderer for search results (16:9 thumb, app pill, snippet, badges)."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 74)

    def paint(self, painter: QPainter, option, index) -> None:
        rec: CaptureRecord | None = index.data(_ROLE_RECORD)
        if rec is None:
            super().paint(painter, option, index)
            return

        snippet: str = str(index.data(_ROLE_SNIPPET) or "")
        match_type: str = str(index.data(_ROLE_MATCH_TYPE) or "")
        thumb: QPixmap | None = index.data(_ROLE_THUMB)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(option.rect).adjusted(3, 2, -3, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setBrush(QColor(56, 189, 248, 28))
            painter.setPen(QPen(QColor(56, 189, 248, 130), 1.0))
        elif hovered:
            painter.setBrush(QColor("#17171D"))
            painter.setPen(QPen(QColor("#2A2A34"), 1.0))
        else:
            painter.setBrush(QColor("#121216"))
            painter.setPen(QPen(QColor("#1F1F26"), 1.0))
        painter.drawRoundedRect(rect, 7, 7)

        # 16:9 Thumbnail box on the left
        thumb_w = 96.0
        thumb_h = 54.0
        thumb_rect = QRectF(rect.left() + 8, rect.top() + (rect.height() - thumb_h) / 2.0, thumb_w, thumb_h)
        painter.setBrush(QColor("#0A0A0D"))
        painter.setPen(QPen(QColor("#25252D"), 1.0))
        painter.drawRoundedRect(thumb_rect, 4, 4)

        if thumb is not None and not thumb.isNull():
            painter.drawPixmap(thumb_rect.adjusted(1, 1, -1, -1).toRect(), thumb)
        else:
            painter.setPen(QColor("#52525B"))
            f_tiny = QFont(option.font)
            f_tiny.setPointSize(7)
            painter.setFont(f_tiny)
            lbl = "OCR ONLY" if rec.image_archived else "…"
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, lbl)

        # Right column metadata
        tx = thumb_rect.right() + 10.0
        tw = max(40.0, rect.right() - tx - 8.0)

        # Row 1: App colored pill + badges + relative time
        app_col = QColor(app_color_for_name(rec.app_name))
        app_text = (rec.app_name or "Screen")[:18]
        f_pill = QFont(option.font)
        f_pill.setPointSize(7)
        f_pill.setBold(True)
        painter.setFont(f_pill)
        fm_pill = QFontMetrics(f_pill)
        pill_w = min(tw * 0.55, fm_pill.horizontalAdvance(app_text) + 14.0)
        pill_rect = QRectF(tx, rect.top() + 7.0, pill_w, 16.0)

        pill_bg = QColor(app_col)
        pill_bg.setAlpha(38)
        painter.setBrush(pill_bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(pill_rect, 4, 4)
        painter.setPen(app_col)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, app_text)

        badge_x = pill_rect.right() + 5.0
        if rec.pinned:
            pin_rect = QRectF(badge_x, rect.top() + 7.0, 32.0, 16.0)
            painter.setBrush(QColor(245, 158, 11, 42))
            painter.drawRoundedRect(pin_rect, 4, 4)
            painter.setPen(QColor("#F59E0B"))
            painter.drawText(pin_rect, Qt.AlignmentFlag.AlignCenter, "PIN")
            badge_x = pin_rect.right() + 4.0
        if rec.pii_redacted:
            pii_rect = QRectF(badge_x, rect.top() + 7.0, 34.0, 16.0)
            painter.setBrush(QColor(16, 185, 129, 42))
            painter.drawRoundedRect(pii_rect, 4, 4)
            painter.setPen(QColor("#10B981"))
            painter.drawText(pii_rect, Qt.AlignmentFlag.AlignCenter, "PII")
            badge_x = pii_rect.right() + 4.0
        elif match_type == "fuzzy":
            fuz_rect = QRectF(badge_x, rect.top() + 7.0, 40.0, 16.0)
            painter.setBrush(QColor(56, 189, 248, 36))
            painter.drawRoundedRect(fuz_rect, 4, 4)
            painter.setPen(QColor("#38BDF8"))
            painter.drawText(fuz_rect, Qt.AlignmentFlag.AlignCenter, "FUZZY")

        # Relative time right-aligned
        time_str = _format_relative_time(rec.timestamp)
        painter.setPen(QColor("#71717A"))
        painter.drawText(
            QRectF(tx, rect.top() + 7.0, tw, 16.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            time_str,
        )

        # Row 2: Window title
        f_title = QFont(option.font)
        f_title.setPointSize(8)
        f_title.setBold(True)
        painter.setFont(f_title)
        fm_title = QFontMetrics(f_title)
        title_str = fm_title.elidedText(rec.window_title or "(Untitled)", Qt.TextElideMode.ElideRight, int(tw))
        painter.setPen(QColor("#FAFAFA"))
        painter.drawText(QRectF(tx, rect.top() + 26.0, tw, 18.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title_str)

        # Row 3: Highlighted OCR snippet
        f_snip = QFont(option.font)
        f_snip.setPointSize(7)
        painter.setFont(f_snip)
        fm_snip = QFontMetrics(f_snip)
        clean_snip = snippet.replace("\n", " ").strip()
        elided_snip = fm_snip.elidedText(clean_snip, Qt.TextElideMode.ElideRight, int(tw))
        painter.setPen(QColor("#F59E0B") if "[" in clean_snip else QColor("#A1A1AA"))
        painter.drawText(QRectF(tx, rect.top() + 46.0, tw, 18.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_snip)

        painter.restore()


class MainWindow(QMainWindow):
    """LocalRecall v1.0.0 Studio 2.0 Main Window."""

    capture_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    pause_state_changed = pyqtSignal(bool)
    config_changed = pyqtSignal(object)
    language_changed = pyqtSignal(str)

    _search_ready = pyqtSignal(int, list, float)
    _thumb_ready = pyqtSignal(str, object)

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
        self.i18n = LanguageManager(config.ui_language)

        self._force_quit = False
        self._timeline_records: list[CaptureRecord] = []
        self._current_record: CaptureRecord | None = None
        self._current_tab = 0
        self._search_gen = 0
        self._thumb_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._thumb_inflight: set[str] = set()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="LocalRecall-UI")
        self._update_thread: UpdateCheckerThread | None = None
        self._download_thread: UpdateDownloadThread | None = None
        self._latest_update_info: UpdateInfo | None = None

        self.setWindowTitle(self.i18n.t("app_title"))
        self.setWindowIcon(create_app_icon(paused=capture_service.is_paused))

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        min_w = min(920, max(800, avail.width() - 40))
        min_h = min(600, max(540, avail.height() - 40))
        init_w = min(1140, max(min_w, avail.width() - 60))
        init_h = min(680, max(min_h, avail.height() - 60))
        self.setMinimumSize(min_w, min_h)
        self.resize(init_w, init_h)

        self._build_ui()
        self._setup_shortcuts()

        # Debounced search timer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(lambda: self.refresh_results(sync=False))

        # Timeline rewind playback timer
        self._rewind_timer = QTimer(self)
        self._rewind_timer.setInterval(350)
        self._rewind_timer.timeout.connect(self._on_rewind_tick)

        self.capture_updated.connect(self._on_capture_updated)
        self.status_updated.connect(self._on_status_updated)
        self._search_ready.connect(self._apply_search_results)
        self._thumb_ready.connect(self._on_thumb_loaded)

        self.retranslate_ui()
        self.refresh_all(sync=True)

        if self.config.check_updates_on_startup and UpdateCheckerThread is not None:
            QTimer.singleShot(2500, self._start_silent_update_check)

    # ═════════════════════════════════════════════════════════════════════════
    # UI CONSTRUCTION — STUDIO 2.0 SIDEBAR + 4 STACKED PAGES
    # ═════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        ui_font = get_ui_font_family()
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left Navigation Sidebar (218px) ---
        sidebar = QFrame()
        sidebar.setObjectName("sidebarRail")
        sidebar.setFixedWidth(218)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(14, 16, 14, 14)
        sb.setSpacing(16)

        # Brand row
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(2, 0, 2, 0)
        brand_row.setSpacing(10)

        self.logo_lbl = QLabel()
        self.logo_lbl.setPixmap(create_app_pixmap(32, paused=self.capture_service.is_paused))
        self.logo_lbl.setFixedSize(32, 32)
        brand_row.addWidget(self.logo_lbl)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        brand_top = QHBoxLayout()
        brand_top.setSpacing(6)
        lbl_name = QLabel("LocalRecall")
        lbl_name.setFont(QFont(ui_font, 11, QFont.Weight.Bold))
        lbl_name.setStyleSheet("color: #FAFAFA; letter-spacing: -0.2px;")
        brand_top.addWidget(lbl_name)
        lbl_ver = QLabel(f"v{__version__}")
        lbl_ver.setStyleSheet("color: #38BDF8; font-size: 7.4pt; font-weight: 700;")
        brand_top.addWidget(lbl_ver)
        brand_top.addStretch(1)
        brand_col.addLayout(brand_top)

        self.lbl_brand_sub = QLabel()
        self.lbl_brand_sub.setStyleSheet("color: #71717A; font-size: 7.6pt; font-weight: 500;")
        brand_col.addWidget(self.lbl_brand_sub)
        brand_row.addLayout(brand_col, stretch=1)
        sb.addLayout(brand_row)

        # 4 Navigation buttons
        nav_col = QVBoxLayout()
        nav_col.setSpacing(4)
        self.btn_nav_timeline = SidebarNavButton("Timeline & Recall")
        self.btn_nav_insights = SidebarNavButton("Activity & Insights")
        self.btn_nav_privacy = SidebarNavButton("Privacy Shield")
        self.btn_nav_settings = SidebarNavButton("Settings & Engine")
        self._nav_buttons = [
            self.btn_nav_timeline,
            self.btn_nav_insights,
            self.btn_nav_privacy,
            self.btn_nav_settings,
        ]
        for idx, btn in enumerate(self._nav_buttons):
            btn.clicked.connect(lambda checked=False, i=idx: self.switch_tab(i))
            nav_col.addWidget(btn)
        sb.addLayout(nav_col)
        sb.addStretch(1)

        # Bottom Privacy & Engine Status Card + Hotkey keycap
        status_card = QFrame()
        status_card.setStyleSheet(
            "QFrame { background-color: #141418; border: 1px solid #23232B; border-radius: 9px; }"
        )
        sc = QVBoxLayout(status_card)
        sc.setContentsMargins(11, 10, 11, 10)
        sc.setSpacing(7)

        st_row = QHBoxLayout()
        st_row.setSpacing(7)
        self._sb_dot = QFrame()
        self._sb_dot.setFixedSize(8, 8)
        self._sb_dot.setStyleSheet("background-color: #10B981; border-radius: 4px; border: none;")
        st_row.addWidget(self._sb_dot)
        self.lbl_sb_status = QLabel()
        self.lbl_sb_status.setStyleSheet("color: #FAFAFA; font-size: 8.3pt; font-weight: 600; border: none;")
        st_row.addWidget(self.lbl_sb_status, stretch=1)
        sc.addLayout(st_row)

        self.lbl_sb_meta = QLabel()
        self.lbl_sb_meta.setStyleSheet("color: #71717A; font-size: 7.3pt; font-weight: 600; border: none;")
        sc.addWidget(self.lbl_sb_meta)

        hk_col = QVBoxLayout()
        hk_col.setSpacing(4)
        self.lbl_sb_hk_hint = QLabel()
        self.lbl_sb_hk_hint.setStyleSheet("color: #71717A; font-size: 7.2pt; border: none;")
        hk_col.addWidget(self.lbl_sb_hk_hint)
        self.lbl_sb_keycap = QLabel(self.config.global_hotkey)
        self.lbl_sb_keycap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sb_keycap.setStyleSheet(
            "color: #38BDF8; background-color: rgba(56, 189, 248, 0.12); "
            "border: 1px solid rgba(56, 189, 248, 0.30); border-radius: 4px; "
            "padding: 3px 6px; font-size: 7.3pt; font-weight: 700;"
        )
        hk_col.addWidget(self.lbl_sb_keycap)
        sc.addLayout(hk_col)
        sb.addWidget(status_card)

        root.addWidget(sidebar)

        # --- Right Stacked Content Pages ---
        self.stack = QStackedWidget()
        self.page_timeline = self._build_timeline_page()
        self.page_insights = self._build_insights_page()
        self.page_privacy = self._build_privacy_page()
        self.page_settings = self._build_settings_page()

        self.stack.addWidget(self.page_timeline)
        self.stack.addWidget(self.page_insights)
        self.stack.addWidget(self.page_privacy)
        self.stack.addWidget(self.page_settings)
        root.addWidget(self.stack, stretch=1)

        # Status bar
        self.stats_label = QLabel("")
        self.statusBar().addPermanentWidget(self.stats_label)
        self.switch_tab(0)
        self._update_pause_ui(self.capture_service.is_paused)

    # ── Page 1: Timeline & Recall ────────────────────────────────────────────

    def _build_timeline_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(10)

        # Optional macOS Screen Recording Permission Warning Banner
        self.perm_banner = QFrame()
        self.perm_banner.setObjectName("permissionBanner")
        pb = QHBoxLayout(self.perm_banner)
        pb.setContentsMargins(12, 7, 12, 7)
        self.lbl_perm_banner = QLabel()
        self.lbl_perm_banner.setStyleSheet("color: #FCD34D; font-size: 8.3pt; font-weight: 600;")
        pb.addWidget(self.lbl_perm_banner, stretch=1)
        self.btn_grant_perm = QPushButton()
        self.btn_grant_perm.clicked.connect(self._request_screen_permission)
        pb.addWidget(self.btn_grant_perm)
        self.perm_banner.setVisible(not has_screen_recording_permission())
        lay.addWidget(self.perm_banner)

        # Top Search Command Bar
        cmd_bar = QHBoxLayout()
        cmd_bar.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setMinimumWidth(220)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        cmd_bar.addWidget(self.search_input, stretch=4)

        self.search_mode_combo = FlatComboBox()
        self.search_mode_combo.setMinimumWidth(98)
        self.search_mode_combo.addItem("Hybrid", "hybrid")
        self.search_mode_combo.addItem("FTS5", "fts")
        idx = self.search_mode_combo.findData(self.config.search_mode)
        if idx >= 0:
            self.search_mode_combo.setCurrentIndex(idx)
        self.search_mode_combo.currentIndexChanged.connect(self._on_search_mode_changed)
        cmd_bar.addWidget(self.search_mode_combo)

        self.app_filter = FlatComboBox()
        self.app_filter.setMinimumWidth(116)
        self.app_filter.addItem("All Apps", "")
        self.app_filter.currentIndexChanged.connect(lambda _: self.refresh_results(sync=False))
        cmd_bar.addWidget(self.app_filter)

        self.date_filter = FlatComboBox()
        self.date_filter.setMinimumWidth(106)
        self.date_filter.addItem("All Time", "all")
        self.date_filter.addItem("Today", "today")
        self.date_filter.addItem("7 Days", "7d")
        self.date_filter.addItem("30 Days", "30d")
        self.date_filter.currentIndexChanged.connect(lambda _: self.refresh_results(sync=False))
        cmd_bar.addWidget(self.date_filter)

        self.pinned_filter_btn = QPushButton()
        self.pinned_filter_btn.setCheckable(True)
        self.pinned_filter_btn.setIcon(make_flat_icon("pin", "#F59E0B", 12))
        self.pinned_filter_btn.toggled.connect(lambda _: self.refresh_results(sync=False))
        cmd_bar.addWidget(self.pinned_filter_btn)

        self.pause_btn = QPushButton()
        self.pause_btn.setIcon(make_flat_icon("pause", "#E4E4E7", 12))
        self.pause_btn.clicked.connect(self.toggle_pause)
        pause_menu = QMenu(self.pause_btn)
        self._act_pause_15 = pause_menu.addAction("Pause 15m", lambda: self.pause_for_minutes(15))
        self._act_pause_60 = pause_menu.addAction("Pause 1h", lambda: self.pause_for_minutes(60))
        self.pause_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pause_btn.customContextMenuRequested.connect(
            lambda pos: pause_menu.exec(self.pause_btn.mapToGlobal(pos))
        )
        cmd_bar.addWidget(self.pause_btn)

        self.capture_now_btn = QPushButton()
        self.capture_now_btn.setObjectName("primaryButton")
        self.capture_now_btn.setIcon(make_flat_icon("camera", "#09090B", 12))
        self.capture_now_btn.clicked.connect(self.capture_now)
        cmd_bar.addWidget(self.capture_now_btn)

        lay.addLayout(cmd_bar)

        # Center Split View: Left Result Cards | Right Live Preview + OCR + Note
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left column
        left_panel = QWidget()
        left_lay = QVBoxLayout(left_panel)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.setSpacing(6)

        lh_row = QHBoxLayout()
        self.results_header = QLabel("Captures (0)")
        self.results_header.setObjectName("metaLabel")
        lh_row.addWidget(self.results_header, stretch=1)

        self.btn_demo_quick = QPushButton()
        self.btn_demo_quick.setObjectName("subtleButton")
        self.btn_demo_quick.clicked.connect(self.load_demo_timeline)
        lh_row.addWidget(self.btn_demo_quick)
        left_lay.addLayout(lh_row)

        self.results_list = QListWidget()
        self.results_list.setItemDelegate(ResultCardDelegate(self.results_list))
        self.results_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_list.setMouseTracking(True)
        self.results_list.currentItemChanged.connect(self._on_result_selected)
        left_lay.addWidget(self.results_list, stretch=1)
        splitter.addWidget(left_panel)

        # Right column
        right_panel = QWidget()
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(6, 0, 0, 0)
        right_lay.setSpacing(6)

        # Metadata header line + clean action toolbar (zero text clipping!)
        self.meta_label = QLabel()
        self.meta_label.setObjectName("metaLabel")
        right_lay.addWidget(self.meta_label)

        action_bar = QHBoxLayout()
        action_bar.setSpacing(5)

        self.pin_btn = QPushButton()
        self.pin_btn.setCheckable(True)
        self.pin_btn.setObjectName("subtleButton")
        self.pin_btn.setIcon(make_flat_icon("pin", "#F59E0B", 12))
        self.pin_btn.clicked.connect(self._toggle_pin_current)
        action_bar.addWidget(self.pin_btn)

        self.show_boxes_btn = QPushButton()
        self.show_boxes_btn.setCheckable(True)
        self.show_boxes_btn.setObjectName("subtleButton")
        self.show_boxes_btn.setIcon(make_flat_icon("boxes", "#38BDF8", 12))
        self.show_boxes_btn.toggled.connect(self._on_toggle_all_boxes)
        action_bar.addWidget(self.show_boxes_btn)

        # Zoom Pill (- | 100% | + | Fit)
        zoom_pill = QFrame()
        zoom_pill.setStyleSheet(
            "QFrame { background-color: #141417; border: 1px solid #24242A; border-radius: 6px; }"
            "QPushButton { background: transparent; border: none; padding: 2px 6px; font-size: 8pt; color: #A1A1AA; }"
            "QPushButton:hover { color: #FAFAFA; background-color: #202028; border-radius: 4px; }"
        )
        zp = QHBoxLayout(zoom_pill)
        zp.setContentsMargins(4, 1, 4, 1)
        zp.setSpacing(2)
        btn_z_out = QPushButton("−")
        btn_z_out.setFixedWidth(22)
        btn_z_out.clicked.connect(lambda: self.preview_widget.zoom_out())
        self.lbl_zoom_pct = QLabel("100%")
        self.lbl_zoom_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_zoom_pct.setMinimumWidth(36)
        self.lbl_zoom_pct.setStyleSheet("color: #FAFAFA; font-size: 7.8pt; font-weight: 700;")
        btn_z_in = QPushButton("+")
        btn_z_in.setFixedWidth(22)
        btn_z_in.clicked.connect(lambda: self.preview_widget.zoom_in())
        self.btn_z_fit = QPushButton("Fit")
        self.btn_z_fit.setMinimumWidth(28)
        self.btn_z_fit.clicked.connect(lambda: self.preview_widget.reset_zoom())
        zp.addWidget(btn_z_out)
        zp.addWidget(self.lbl_zoom_pct)
        zp.addWidget(btn_z_in)
        zp.addWidget(self.btn_z_fit)
        action_bar.addWidget(zoom_pill)

        action_bar.addStretch(1)

        self.export_btn = QPushButton()
        self.export_btn.setObjectName("subtleButton")
        self.export_btn.setIcon(make_flat_icon("download", "#E4E4E7", 12))
        self.export_btn.clicked.connect(self._export_current_image)
        action_bar.addWidget(self.export_btn)

        self.copy_ocr_btn = QPushButton()
        self.copy_ocr_btn.setObjectName("subtleButton")
        self.copy_ocr_btn.setIcon(make_flat_icon("copy", "#E4E4E7", 12))
        self.copy_ocr_btn.clicked.connect(self._copy_ocr_text)
        action_bar.addWidget(self.copy_ocr_btn)

        self.delete_btn = QPushButton()
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.setStyleSheet("padding: 4px 9px; font-size: 8.1pt;")
        self.delete_btn.setIcon(make_flat_icon("trash", "#FDA4AF", 12))
        self.delete_btn.clicked.connect(self._delete_current_record)
        action_bar.addWidget(self.delete_btn)
        right_lay.addLayout(action_bar)

        # Vertical splitter: Preview Stage + Slim OCR / Note Drawer
        right_split = QSplitter(Qt.Orientation.Vertical)

        self.preview_widget = InteractivePreviewWidget()
        self.preview_widget.box_clicked.connect(self._on_box_clicked)
        self.preview_widget.zoom_changed.connect(lambda pct: self.lbl_zoom_pct.setText(f"{pct}%"))
        right_split.addWidget(self.preview_widget)

        ocr_drawer = QWidget()
        od_lay = QVBoxLayout(ocr_drawer)
        od_lay.setContentsMargins(0, 4, 0, 0)
        od_lay.setSpacing(5)

        od_top = QHBoxLayout()
        self.ocr_header = QLabel()
        self.ocr_header.setObjectName("metaLabel")
        od_top.addWidget(self.ocr_header, stretch=1)
        od_lay.addLayout(od_top)

        self.ocr_view = QPlainTextEdit()
        self.ocr_view.setReadOnly(True)
        self.ocr_view.setMaximumHeight(92)
        od_lay.addWidget(self.ocr_view)

        note_row = QHBoxLayout()
        note_row.setSpacing(6)
        self.note_input = QLineEdit()
        note_row.addWidget(self.note_input, stretch=1)
        self.btn_save_note = QPushButton()
        self.btn_save_note.setObjectName("subtleButton")
        self.btn_save_note.clicked.connect(self._save_current_note)
        note_row.addWidget(self.btn_save_note)
        od_lay.addLayout(note_row)

        right_split.addWidget(ocr_drawer)
        right_split.setStretchFactor(0, 4)
        right_split.setStretchFactor(1, 1)
        right_lay.addWidget(right_split, stretch=1)

        splitter.addWidget(right_panel)
        splitter.setSizes([315, 535])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        lay.addWidget(splitter, stretch=1)

        # Bottom App-Colored Visual Timeline Ribbon
        ribbon_frame = QFrame()
        ribbon_frame.setObjectName("studioCard")
        rb = QHBoxLayout(ribbon_frame)
        rb.setContentsMargins(10, 6, 10, 6)
        rb.setSpacing(7)

        self.lbl_timeline_title = QLabel()
        self.lbl_timeline_title.setStyleSheet("color: #71717A; font-size: 8pt; font-weight: 700;")
        rb.addWidget(self.lbl_timeline_title)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedWidth(30)
        self.prev_btn.clicked.connect(lambda: self._step_timeline(-1))
        rb.addWidget(self.prev_btn)

        self.rewind_btn = QPushButton()
        self.rewind_btn.setIcon(make_flat_icon("play", "#38BDF8", 12))
        self.rewind_btn.setFixedWidth(32)
        self.rewind_btn.clicked.connect(self._toggle_rewind_playback)
        rb.addWidget(self.rewind_btn)

        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedWidth(30)
        self.next_btn.clicked.connect(lambda: self._step_timeline(1))
        rb.addWidget(self.next_btn)

        self.timeline_ribbon = TimelineRibbonWidget()
        self.timeline_ribbon.index_changed.connect(self._on_timeline_moved)
        rb.addWidget(self.timeline_ribbon, stretch=1)

        self.timeline_label = QLabel("—")
        self.timeline_label.setStyleSheet("color: #A1A1AA; font-size: 8pt; font-weight: 600;")
        self.timeline_label.setMinimumWidth(132)
        self.timeline_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rb.addWidget(self.timeline_label)

        lay.addWidget(ribbon_frame)
        return page

    # ── Page 2: Activity & Insights ──────────────────────────────────────────

    def _build_insights_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("scrollContent")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)

        self.lbl_insights_title = QLabel()
        self.lbl_insights_title.setObjectName("pageTitle")
        lay.addWidget(self.lbl_insights_title)

        self.lbl_insights_sub = QLabel()
        self.lbl_insights_sub.setObjectName("pageSubtitle")
        lay.addWidget(self.lbl_insights_sub)

        # 4 TelemetryCard KPIs
        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(10)
        self.kpi_captures = TelemetryCard("TOTAL CAPTURES", "SQLITE", "0", "0 OCR indexed", "#38BDF8", 20)
        self.kpi_dedup = TelemetryCard("DEDUP SAVINGS", "RING-8", "0%", "0 skipped", "#10B981", 20)
        self.kpi_storage = TelemetryCard("STORAGE USED", "WEBP", "0.0 MB", "Quota 5.0 GB", "#F59E0B", 12)
        self.kpi_privacy = TelemetryCard("PRIVACY BLOCKS", "SHIELD", "0", "0 PII redacted", "#10B981", 25)
        kpi_grid.addWidget(self.kpi_captures, 0, 0)
        kpi_grid.addWidget(self.kpi_dedup, 0, 1)
        kpi_grid.addWidget(self.kpi_storage, 0, 2)
        kpi_grid.addWidget(self.kpi_privacy, 0, 3)
        lay.addLayout(kpi_grid)

        # Two-column content: App Breakdown + Hourly Chart & Maintenance
        cols = QHBoxLayout()
        cols.setSpacing(12)

        # Left card: App breakdown
        apps_card = QFrame()
        apps_card.setObjectName("studioCard")
        ac = QVBoxLayout(apps_card)
        ac.setContentsMargins(14, 12, 14, 12)
        ac.setSpacing(10)

        self.lbl_top_apps = QLabel()
        self.lbl_top_apps.setObjectName("sectionTitle")
        ac.addWidget(self.lbl_top_apps)

        self.apps_breakdown_layout = QVBoxLayout()
        self.apps_breakdown_layout.setSpacing(7)
        ac.addLayout(self.apps_breakdown_layout)
        ac.addStretch(1)
        cols.addWidget(apps_card, stretch=3)

        # Right column: 24h Chart + Maintenance
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        chart_card = QFrame()
        chart_card.setObjectName("studioCard")
        cc = QVBoxLayout(chart_card)
        cc.setContentsMargins(14, 12, 14, 12)
        cc.setSpacing(8)
        self.lbl_hourly_title = QLabel()
        self.lbl_hourly_title.setObjectName("sectionTitle")
        cc.addWidget(self.lbl_hourly_title)
        self.hourly_chart = HourlyActivityChartWidget()
        cc.addWidget(self.hourly_chart)
        right_col.addWidget(chart_card)

        maint_card = QFrame()
        maint_card.setObjectName("studioCard")
        mc = QVBoxLayout(maint_card)
        mc.setContentsMargins(14, 12, 14, 12)
        mc.setSpacing(8)
        self.lbl_maint_title = QLabel()
        self.lbl_maint_title.setObjectName("sectionTitle")
        mc.addWidget(self.lbl_maint_title)

        self.btn_export_digest = QPushButton()
        self.btn_export_digest.setObjectName("primaryButton")
        self.btn_export_digest.setIcon(make_flat_icon("download", "#09090B", 13))
        self.btn_export_digest.clicked.connect(self._export_daily_digest)
        mc.addWidget(self.btn_export_digest)

        btn_row = QHBoxLayout()
        self.btn_vacuum = QPushButton()
        self.btn_vacuum.clicked.connect(self._run_vacuum)
        btn_row.addWidget(self.btn_vacuum)

        self.btn_retention = QPushButton()
        self.btn_retention.clicked.connect(self._run_retention)
        btn_row.addWidget(self.btn_retention)
        mc.addLayout(btn_row)

        self.btn_insights_demo = QPushButton()
        self.btn_insights_demo.setObjectName("subtleButton")
        self.btn_insights_demo.clicked.connect(self.load_demo_timeline)
        mc.addWidget(self.btn_insights_demo)

        right_col.addWidget(maint_card)
        right_col.addStretch(1)
        cols.addLayout(right_col, stretch=2)

        lay.addLayout(cols, stretch=1)
        scroll.setWidget(container)
        return scroll

    # ── Page 3: Privacy Shield & Vault ───────────────────────────────────────

    def _build_privacy_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("scrollContent")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(9)

        self.lbl_privacy_title = QLabel()
        self.lbl_privacy_title.setObjectName("pageTitle")
        lay.addWidget(self.lbl_privacy_title)

        # Hero Emerald Privacy Shield Card
        hero = QFrame()
        hero.setObjectName("shieldHero")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(14)

        shield_badge = QLabel()
        shield_badge.setPixmap(make_flat_icon("shield", "#10B981", 28).pixmap(28, 28))
        shield_badge.setFixedSize(36, 36)
        shield_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shield_badge.setStyleSheet("background-color: rgba(16, 185, 129, 0.14); border-radius: 8px;")
        hl.addWidget(shield_badge)

        h_txt = QVBoxLayout()
        h_txt.setSpacing(3)
        self.lbl_priv_hero_title = QLabel()
        self.lbl_priv_hero_title.setStyleSheet("color: #34D399; font-size: 11pt; font-weight: 700;")
        h_txt.addWidget(self.lbl_priv_hero_title)
        self.lbl_priv_hero_sub = QLabel()
        self.lbl_priv_hero_sub.setStyleSheet("color: #A7F3D0; font-size: 8.4pt;")
        self.lbl_priv_hero_sub.setWordWrap(True)
        h_txt.addWidget(self.lbl_priv_hero_sub)
        hl.addLayout(h_txt, stretch=1)

        self.lbl_priv_hero_stat = QLabel("0 BLOCKED")
        self.lbl_priv_hero_stat.setStyleSheet(
            "color: #10B981; background-color: rgba(16, 185, 129, 0.16); "
            "border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 7px; "
            "padding: 6px 12px; font-size: 8.5pt; font-weight: 700;"
        )
        hl.addWidget(self.lbl_priv_hero_stat)
        lay.addWidget(hero)

        # Guards & PII Redaction Card
        guards_card = QFrame()
        guards_card.setObjectName("studioCard")
        gc = QVBoxLayout(guards_card)
        gc.setContentsMargins(14, 12, 14, 12)
        gc.setSpacing(9)

        self.lbl_pii_sec = QLabel()
        self.lbl_pii_sec.setObjectName("sectionTitle")
        gc.addWidget(self.lbl_pii_sec)

        pii_row = QHBoxLayout()
        self.lbl_pii_mode = QLabel()
        pii_row.addWidget(self.lbl_pii_mode)
        self.pii_mode_combo = FlatComboBox()
        self.pii_mode_combo.setMinimumWidth(300)
        self.pii_mode_combo.addItem("Redact & Blur", PII_MODE_REDACT_AND_BLUR)
        self.pii_mode_combo.addItem("Redact Text", PII_MODE_REDACT_TEXT)
        self.pii_mode_combo.addItem("Skip Capture", PII_MODE_SKIP)
        self.pii_mode_combo.addItem("Off", PII_MODE_OFF)
        p_idx = self.pii_mode_combo.findData(self.config.pii_redaction_mode)
        if p_idx >= 0:
            self.pii_mode_combo.setCurrentIndex(p_idx)
        pii_row.addWidget(self.pii_mode_combo)
        pii_row.addStretch(1)
        gc.addLayout(pii_row)

        self.lbl_pii_desc = QLabel()
        self.lbl_pii_desc.setObjectName("metaLabel")
        self.lbl_pii_desc.setWordWrap(True)
        gc.addWidget(self.lbl_pii_desc)

        self.sw_pm_guard = FlatSwitch("", accent="#10B981")
        self.sw_pm_guard.setChecked(self.config.password_manager_guard)
        gc.addWidget(self.sw_pm_guard)

        self.sw_incognito_guard = FlatSwitch("", accent="#10B981")
        self.sw_incognito_guard.setChecked(self.config.incognito_guard)
        gc.addWidget(self.sw_incognito_guard)

        self.sw_idle_guard = FlatSwitch("", accent="#38BDF8")
        self.sw_idle_guard.setChecked(self.config.idle_pause_sec > 0)
        gc.addWidget(self.sw_idle_guard)

        lay.addWidget(guards_card)

        # Process & Keyword Blocklists
        bl_row = QHBoxLayout()
        bl_row.setSpacing(10)

        proc_card = QFrame()
        proc_card.setObjectName("studioCard")
        pl = QVBoxLayout(proc_card)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.setSpacing(6)
        self.lbl_bl_proc = QLabel()
        self.lbl_bl_proc.setObjectName("sectionTitle")
        pl.addWidget(self.lbl_bl_proc)
        self.processes_edit = QPlainTextEdit()
        self.processes_edit.setPlainText("\n".join(self.config.blocked_processes))
        self.processes_edit.setMinimumHeight(86)
        self.processes_edit.setMaximumHeight(112)
        pl.addWidget(self.processes_edit)
        bl_row.addWidget(proc_card)

        kw_card = QFrame()
        kw_card.setObjectName("studioCard")
        kl = QVBoxLayout(kw_card)
        kl.setContentsMargins(12, 10, 12, 10)
        kl.setSpacing(6)
        self.lbl_bl_kw = QLabel()
        self.lbl_bl_kw.setObjectName("sectionTitle")
        kl.addWidget(self.lbl_bl_kw)
        self.keywords_edit = QPlainTextEdit()
        self.keywords_edit.setPlainText("\n".join(self.config.blocked_title_keywords))
        self.keywords_edit.setMinimumHeight(86)
        self.keywords_edit.setMaximumHeight(112)
        kl.addWidget(self.keywords_edit)
        bl_row.addWidget(kw_card)
        lay.addLayout(bl_row)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.btn_save_privacy = QPushButton()
        self.btn_save_privacy.setObjectName("emeraldButton")
        self.btn_save_privacy.clicked.connect(self._save_privacy_rules)
        save_row.addWidget(self.btn_save_privacy)
        lay.addLayout(save_row)

        # Panic Privacy Controls Card (Rose)
        panic_card = QFrame()
        panic_card.setObjectName("panicCard")
        pc = QVBoxLayout(panic_card)
        pc.setContentsMargins(14, 12, 14, 12)
        pc.setSpacing(8)
        self.lbl_panic_title = QLabel()
        self.lbl_panic_title.setStyleSheet("color: #FB7185; font-size: 9.8pt; font-weight: 700;")
        pc.addWidget(self.lbl_panic_title)
        self.lbl_panic_sub = QLabel()
        self.lbl_panic_sub.setStyleSheet("color: #FDA4AF; font-size: 8.2pt;")
        pc.addWidget(self.lbl_panic_sub)

        p_btns = QHBoxLayout()
        p_btns.setSpacing(8)
        self.btn_pause_15 = QPushButton()
        self.btn_pause_15.clicked.connect(lambda: self.pause_for_minutes(15))
        p_btns.addWidget(self.btn_pause_15)

        self.btn_pause_60 = QPushButton()
        self.btn_pause_60.clicked.connect(lambda: self.pause_for_minutes(60))
        p_btns.addWidget(self.btn_pause_60)

        self.btn_purge_15 = QPushButton()
        self.btn_purge_15.setObjectName("dangerButton")
        self.btn_purge_15.clicked.connect(lambda: self._confirm_and_purge_minutes(15))
        p_btns.addWidget(self.btn_purge_15)

        self.btn_purge_60 = QPushButton()
        self.btn_purge_60.setObjectName("dangerButton")
        self.btn_purge_60.clicked.connect(lambda: self._confirm_and_purge_minutes(60))
        p_btns.addWidget(self.btn_purge_60)

        self.btn_purge_today = QPushButton()
        self.btn_purge_today.setObjectName("dangerButton")
        self.btn_purge_today.clicked.connect(self._confirm_and_purge_today)
        p_btns.addWidget(self.btn_purge_today)
        p_btns.addStretch(1)
        pc.addLayout(p_btns)

        lay.addWidget(panic_card)
        scroll.setWidget(container)
        return scroll

    # ── Page 4: Settings & Engine ────────────────────────────────────────────

    def _build_settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("scrollContent")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        self.lbl_settings_title = QLabel()
        self.lbl_settings_title.setObjectName("pageTitle")
        lay.addWidget(self.lbl_settings_title)

        hw = self.capture_service.hw_profile
        tuning = self.capture_service.tuning
        self.lbl_hw_summary = QLabel(format_hardware_summary(hw, tuning, lang=self.i18n.lang))
        self.lbl_hw_summary.setStyleSheet(
            "color: #38BDF8; background-color: rgba(56, 189, 248, 0.10); "
            "border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 7px; "
            "padding: 6px 11px; font-size: 8.1pt; font-weight: 600;"
        )
        lay.addWidget(self.lbl_hw_summary)

        # 4 Hardware / Engine TelemetryCards
        st_kpi = QGridLayout()
        st_kpi.setSpacing(8)
        self.set_kpi_cpu = TelemetryCard(
            "PROCESSOR", hw.arch.upper(), f"{hw.physical_cores}C / {hw.logical_cores}T", hw.short_cpu_label[:22], "#38BDF8", 75
        )
        self.set_kpi_budget = TelemetryCard(
            "ONNX CPU BUDGET", tuning.effective_profile.upper(), f"{tuning.ocr_intra_threads} Thread(s)", "Target <1% idle CPU", "#10B981", 35
        )
        self.set_kpi_vram = TelemetryCard(
            "GPU / VRAM", "100% CPU", "0 MB", "Zero GPU contention", "#F59E0B", 8
        )
        self.set_kpi_vault = TelemetryCard(
            "VAULT POLICY", "SQLITE WAL", f"{self.config.retention_days}d / {self.config.max_storage_gb:g} GB", "Local WebP + FTS5", "#A78BFA", 45
        )
        for col_i, card in enumerate((self.set_kpi_cpu, self.set_kpi_budget, self.set_kpi_vram, self.set_kpi_vault)):
            st_kpi.addWidget(card, 0, col_i)
            st_kpi.setColumnStretch(col_i, 1)
        lay.addLayout(st_kpi)

        # Two-column settings forms (strictly proportioned for 1080px!)
        grid_cards = QHBoxLayout()
        grid_cards.setSpacing(10)

        # Capture & Storage Card
        cap_card = QFrame()
        cap_card.setObjectName("studioCard")
        cap_lay = QGridLayout(cap_card)
        cap_lay.setContentsMargins(13, 10, 13, 10)
        cap_lay.setSpacing(6)
        cap_lay.setColumnStretch(0, 1)
        cap_lay.setColumnStretch(1, 1)

        self.lbl_sec_capture = QLabel()
        self.lbl_sec_capture.setObjectName("sectionTitle")
        cap_lay.addWidget(self.lbl_sec_capture, 0, 0, 1, 2)

        self.lbl_monitor = QLabel()
        self.monitor_combo = FlatComboBox()
        self.monitor_combo.setMaximumWidth(235)
        for idx, lbl in list_monitors(lang=self.config.ui_language):
            self.monitor_combo.addItem(lbl, idx)
        mon_pos = self.monitor_combo.findData(self.config.monitor_index)
        if mon_pos >= 0:
            self.monitor_combo.setCurrentIndex(mon_pos)
        cap_lay.addWidget(self.lbl_monitor, 1, 0)
        cap_lay.addWidget(self.monitor_combo, 1, 1)

        self.lbl_interval = QLabel()
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setMaximumWidth(195)
        self.interval_spin.setRange(0.5, 60.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setValue(self.config.capture_interval_sec)
        cap_lay.addWidget(self.lbl_interval, 2, 0)
        cap_lay.addWidget(self.interval_spin, 2, 1)

        self.lbl_idle = QLabel()
        self.idle_spin = QSpinBox()
        self.idle_spin.setMaximumWidth(195)
        self.idle_spin.setRange(0, 600)
        self.idle_spin.setSingleStep(15)
        self.idle_spin.setValue(int(self.config.idle_pause_sec))
        cap_lay.addWidget(self.lbl_idle, 3, 0)
        cap_lay.addWidget(self.idle_spin, 3, 1)

        self.lbl_diff = QLabel()
        self.diff_spin = QDoubleSpinBox()
        self.diff_spin.setMaximumWidth(195)
        self.diff_spin.setRange(0.001, 0.5)
        self.diff_spin.setDecimals(3)
        self.diff_spin.setSingleStep(0.005)
        self.diff_spin.setValue(self.config.diff_threshold)
        cap_lay.addWidget(self.lbl_diff, 4, 0)
        cap_lay.addWidget(self.diff_spin, 4, 1)

        self.lbl_quality = QLabel()
        self.quality_spin = QSpinBox()
        self.quality_spin.setMaximumWidth(195)
        self.quality_spin.setRange(30, 100)
        self.quality_spin.setValue(self.config.webp_quality)
        cap_lay.addWidget(self.lbl_quality, 5, 0)
        cap_lay.addWidget(self.quality_spin, 5, 1)

        self.lbl_quota = QLabel()
        self.quota_spin = QDoubleSpinBox()
        self.quota_spin.setMaximumWidth(195)
        self.quota_spin.setRange(0.0, 500.0)
        self.quota_spin.setSingleStep(1.0)
        self.quota_spin.setDecimals(1)
        self.quota_spin.setValue(self.config.max_storage_gb)
        cap_lay.addWidget(self.lbl_quota, 6, 0)
        cap_lay.addWidget(self.quota_spin, 6, 1)

        self.lbl_retention = QLabel()
        self.retention_spin = QSpinBox()
        self.retention_spin.setMaximumWidth(195)
        self.retention_spin.setRange(1, 365)
        self.retention_spin.setValue(self.config.retention_days)
        cap_lay.addWidget(self.lbl_retention, 7, 0)
        cap_lay.addWidget(self.retention_spin, 7, 1)

        self.lbl_archival = QLabel()
        self.archival_spin = QSpinBox()
        self.archival_spin.setMaximumWidth(195)
        self.archival_spin.setRange(0, 365)
        self.archival_spin.setValue(self.config.archive_images_after_days)
        cap_lay.addWidget(self.lbl_archival, 8, 0)
        cap_lay.addWidget(self.archival_spin, 8, 1)

        grid_cards.addWidget(cap_card, stretch=1)

        # Engine & System Card
        eng_card = QFrame()
        eng_card.setObjectName("studioCard")
        eng_lay = QVBoxLayout(eng_card)
        eng_lay.setContentsMargins(13, 10, 13, 10)
        eng_lay.setSpacing(7)

        self.lbl_sec_engine = QLabel()
        self.lbl_sec_engine.setObjectName("sectionTitle")
        eng_lay.addWidget(self.lbl_sec_engine)

        prof_row = QHBoxLayout()
        self.lbl_cpu_profile = QLabel()
        prof_row.addWidget(self.lbl_cpu_profile)
        self.cpu_profile_combo = FlatComboBox()
        self.cpu_profile_combo.addItem("Auto", PROFILE_AUTO)
        self.cpu_profile_combo.addItem("Eco", PROFILE_ECO)
        self.cpu_profile_combo.addItem("Balanced", PROFILE_BALANCED)
        self.cpu_profile_combo.addItem("Performance", PROFILE_PERFORMANCE)
        cp_idx = self.cpu_profile_combo.findData(self.config.cpu_profile)
        if cp_idx >= 0:
            self.cpu_profile_combo.setCurrentIndex(cp_idx)
        prof_row.addWidget(self.cpu_profile_combo, stretch=1)
        eng_lay.addLayout(prof_row)

        lang_row = QHBoxLayout()
        self.lbl_language = QLabel()
        lang_row.addWidget(self.lbl_language)
        self.lang_combo = FlatComboBox()
        self.lang_combo.addItem("English (EN)", "en")
        self.lang_combo.addItem("Türkçe (TR)", "tr")
        l_idx = self.lang_combo.findData(self.config.ui_language)
        if l_idx >= 0:
            self.lang_combo.setCurrentIndex(l_idx)
        self.lang_combo.currentIndexChanged.connect(self._on_language_combo_changed)
        lang_row.addWidget(self.lang_combo, stretch=1)
        eng_lay.addLayout(lang_row)

        hk_row = QHBoxLayout()
        self.lbl_hotkey = QLabel()
        hk_row.addWidget(self.lbl_hotkey)
        self.hotkey_edit = QLineEdit(self.config.global_hotkey)
        self.hotkey_edit.setPlaceholderText(get_default_hotkey())
        hk_row.addWidget(self.hotkey_edit, stretch=1)
        eng_lay.addLayout(hk_row)

        self.sw_ocr = FlatSwitch("", accent="#38BDF8")
        self.sw_ocr.setChecked(self.config.ocr_enabled)
        eng_lay.addWidget(self.sw_ocr)

        self.sw_hotkey = FlatSwitch("", accent="#38BDF8")
        self.sw_hotkey.setChecked(self.config.global_hotkey_enabled)
        eng_lay.addWidget(self.sw_hotkey)

        self.sw_autostart = FlatSwitch("", accent="#38BDF8")
        self.sw_autostart.setChecked(self.config.auto_start)
        eng_lay.addWidget(self.sw_autostart)

        self.sw_tray = FlatSwitch("", accent="#38BDF8")
        self.sw_tray.setChecked(self.config.minimize_to_tray)
        eng_lay.addWidget(self.sw_tray)

        perm_row = QHBoxLayout()
        self.lbl_perm_status = QLabel()
        self.lbl_perm_status.setObjectName("metaLabel")
        perm_row.addWidget(self.lbl_perm_status, stretch=1)
        self.btn_check_perm = QPushButton()
        self.btn_check_perm.setObjectName("subtleButton")
        self.btn_check_perm.clicked.connect(self._request_screen_permission)
        perm_row.addWidget(self.btn_check_perm)
        eng_lay.addLayout(perm_row)

        eng_lay.addStretch(1)
        self.btn_save_settings = QPushButton()
        self.btn_save_settings.setObjectName("primaryButton")
        self.btn_save_settings.clicked.connect(self.save_settings_from_page)
        eng_lay.addWidget(self.btn_save_settings)

        grid_cards.addWidget(eng_card, stretch=1)
        lay.addLayout(grid_cards)

        # Updates & Local Benchmark Card
        upd_card = QFrame()
        upd_card.setObjectName("studioCard")
        uc = QVBoxLayout(upd_card)
        uc.setContentsMargins(13, 10, 13, 10)
        uc.setSpacing(6)

        self.lbl_sec_updates = QLabel()
        self.lbl_sec_updates.setObjectName("sectionTitle")
        uc.addWidget(self.lbl_sec_updates)

        u_row = QHBoxLayout()
        self.sw_auto_update = FlatSwitch("", accent="#38BDF8")
        self.sw_auto_update.setChecked(self.config.check_updates_on_startup)
        u_row.addWidget(self.sw_auto_update, stretch=1)

        self.btn_check_update = QPushButton()
        self.btn_check_update.clicked.connect(self._check_updates_manual)
        u_row.addWidget(self.btn_check_update)

        self.btn_download_update = QPushButton()
        self.btn_download_update.setObjectName("primaryButton")
        self.btn_download_update.hide()
        self.btn_download_update.clicked.connect(self._download_latest_update)
        u_row.addWidget(self.btn_download_update)

        self.btn_run_bench = QPushButton()
        self.btn_run_bench.setIcon(make_flat_icon("bolt", "#F59E0B", 13))
        self.btn_run_bench.clicked.connect(self._run_inline_benchmark)
        u_row.addWidget(self.btn_run_bench)
        uc.addLayout(u_row)

        self.lbl_update_status = QLabel(f"LocalRecall v{__version__}")
        self.lbl_update_status.setObjectName("metaLabel")
        uc.addWidget(self.lbl_update_status)

        lay.addWidget(upd_card)
        scroll.setWidget(container)
        return scroll

    # ═════════════════════════════════════════════════════════════════════════
    # NAVIGATION & LIVE RETRANSLATION (EN / TR)
    # ═════════════════════════════════════════════════════════════════════════

    def switch_tab(self, index: int) -> None:
        clamped = max(0, min(self.stack.count() - 1, int(index)))
        self._current_tab = clamped
        self.stack.setCurrentIndex(clamped)
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == clamped)
        if clamped == 1:
            self._refresh_insights_page()
        elif clamped == 2:
            self._refresh_privacy_badges()
        elif clamped == 3:
            self._refresh_permission_indicator()

    def _on_language_combo_changed(self) -> None:
        lang = str(self.lang_combo.currentData() or "en")
        if lang != self.i18n.lang:
            self.i18n.set_language(lang)
            self.config.ui_language = lang
            self.config.save()
            self.retranslate_ui()
            self.language_changed.emit(lang)

    def retranslate_ui(self) -> None:
        t = self.i18n.t
        self.setWindowTitle(t("app_title"))
        self.lbl_brand_sub.setText(t("brand_subtitle"))
        self.btn_nav_timeline.set_nav_text(t("nav_timeline"))
        self.btn_nav_insights.set_nav_text(t("nav_insights"))
        self.btn_nav_privacy.set_nav_text(t("nav_privacy"))
        self.btn_nav_settings.set_nav_text(t("nav_settings"))
        self.lbl_sb_meta.setText(t("status_meta"))
        self.lbl_sb_hk_hint.setText(t("hotkey_hint"))

        self.lbl_perm_banner.setText(t("perm_banner_text"))
        self.btn_grant_perm.setText(t("perm_banner_btn"))

        self.search_input.setPlaceholderText(t("search_placeholder"))
        self.search_mode_combo.setItemText(0, t("mode_hybrid"))
        self.search_mode_combo.setItemText(1, t("mode_fts"))
        if self.app_filter.count() > 0:
            self.app_filter.setItemText(0, t("all_apps"))
        self.date_filter.setItemText(0, t("date_all"))
        self.date_filter.setItemText(1, t("date_today"))
        self.date_filter.setItemText(2, t("date_7d"))
        self.date_filter.setItemText(3, t("date_30d"))
        self.pinned_filter_btn.setText(t("pinned_only"))
        self.capture_now_btn.setText(t("btn_capture_now"))
        self.btn_demo_quick.setText(t("btn_demo_load"))
        self.pin_btn.setText(t("btn_pinned") if (self._current_record and self._current_record.pinned) else t("btn_pin"))
        self.show_boxes_btn.setText(t("btn_boxes"))
        self.btn_z_fit.setText(t("btn_fit"))
        self.export_btn.setText(t("btn_export_png"))
        self.copy_ocr_btn.setText(t("btn_copy_ocr"))
        self.delete_btn.setText(t("btn_delete"))
        self.ocr_view.setPlaceholderText(t("ocr_placeholder"))
        self.note_input.setPlaceholderText(t("note_placeholder"))
        self.btn_save_note.setText(t("btn_save_note"))
        self.lbl_timeline_title.setText(t("timeline_label"))

        # Insights
        self.lbl_insights_title.setText(t("insights_title"))
        self.lbl_insights_sub.setText(t("insights_sub"))
        self.kpi_captures.set_title(t("kpi_captures"))
        self.kpi_dedup.set_title(t("kpi_dedup"))
        self.kpi_storage.set_title(t("kpi_storage"))
        self.kpi_privacy.set_title(t("kpi_privacy"))
        self.lbl_top_apps.setText(t("top_apps_title"))
        self.lbl_hourly_title.setText(t("hourly_title"))
        self.lbl_maint_title.setText(t("maintenance_title"))
        self.btn_export_digest.setText(t("btn_export_digest"))
        self.btn_vacuum.setText(t("btn_vacuum"))
        self.btn_retention.setText(t("btn_retention"))
        self.btn_insights_demo.setText(t("btn_demo_load"))

        # Privacy
        self.lbl_privacy_title.setText(t("privacy_title"))
        self.lbl_priv_hero_title.setText(t("privacy_hero_title"))
        self.lbl_priv_hero_sub.setText(t("privacy_hero_sub"))
        self.lbl_pii_sec.setText(t("pii_section_title"))
        self.lbl_pii_mode.setText(t("pii_mode_label"))
        self.pii_mode_combo.setItemText(0, t("pii_mode_blur"))
        self.pii_mode_combo.setItemText(1, t("pii_mode_text"))
        self.pii_mode_combo.setItemText(2, t("pii_mode_skip"))
        self.pii_mode_combo.setItemText(3, t("pii_mode_off"))
        self.lbl_pii_desc.setText(t("pii_desc"))
        self.sw_pm_guard.setText(t("guard_pm"))
        self.sw_incognito_guard.setText(t("guard_incognito"))
        self.sw_idle_guard.setText(t("guard_idle"))
        self.lbl_bl_proc.setText(t("blocklist_proc_title"))
        self.lbl_bl_kw.setText(t("blocklist_kw_title"))
        self.btn_save_privacy.setText(t("btn_save_privacy"))
        self.lbl_panic_title.setText(t("panic_title"))
        self.lbl_panic_sub.setText(t("panic_sub"))
        self.btn_pause_15.setText(t("btn_pause_15"))
        self.btn_pause_60.setText(t("btn_pause_60"))
        self.btn_purge_15.setText(t("btn_purge_15"))
        self.btn_purge_60.setText(t("btn_purge_60"))
        self.btn_purge_today.setText(t("btn_purge_today"))

        # Settings
        self.lbl_settings_title.setText(t("settings_title"))
        self.lbl_hw_summary.setText(
            format_hardware_summary(self.capture_service.hw_profile, self.capture_service.tuning, lang=self.i18n.lang)
        )
        self.set_kpi_cpu.set_title(t("kpi_cpu"))
        self.set_kpi_budget.set_title(t("kpi_budget"))
        self.set_kpi_vram.set_title(t("kpi_vram"))
        self.set_kpi_vault.set_title(t("kpi_archive"))
        self.lbl_sec_capture.setText(t("sec_capture_title"))
        self.lbl_monitor.setText(t("lbl_monitor"))
        self.lbl_interval.setText(t("lbl_interval"))
        self.lbl_idle.setText(t("lbl_idle"))
        self.lbl_diff.setText(t("lbl_diff"))
        self.lbl_quality.setText(t("lbl_quality"))
        self.lbl_quota.setText(t("lbl_quota"))
        self.lbl_retention.setText(t("lbl_retention"))
        self.lbl_archival.setText(t("lbl_archival"))
        self.lbl_sec_engine.setText(t("sec_engine_title"))
        self.lbl_cpu_profile.setText(t("lbl_cpu_profile"))
        self.cpu_profile_combo.setItemText(0, t("prof_auto"))
        self.cpu_profile_combo.setItemText(1, t("prof_eco"))
        self.cpu_profile_combo.setItemText(2, t("prof_balanced"))
        self.cpu_profile_combo.setItemText(3, t("prof_perf"))
        self.lbl_language.setText(t("lbl_language"))
        self.lbl_hotkey.setText(t("lbl_hotkey"))
        self.sw_ocr.setText(t("chk_ocr"))
        self.sw_hotkey.setText(t("chk_hotkey"))
        self.sw_autostart.setText(t("chk_autostart"))
        self.sw_tray.setText(t("chk_tray"))
        self.btn_save_settings.setText(t("btn_save_settings"))
        self.lbl_sec_updates.setText(t("sec_updates_title"))
        self.sw_auto_update.setText(t("chk_auto_update"))
        self.btn_check_update.setText(t("btn_check_update"))
        self.btn_download_update.setText(t("update_download"))
        self.btn_run_bench.setText(t("btn_run_bench"))
        self.btn_check_perm.setText(t("perm_banner_btn"))

        self._update_pause_ui(self.capture_service.is_paused)
        self._refresh_permission_indicator()

    # ═════════════════════════════════════════════════════════════════════════
    # SHORTCUTS & LIFECYCLE
    # ═════════════════════════════════════════════════════════════════════════

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self._step_timeline(-1))
        QShortcut(QKeySequence("Alt+Right"), self, activated=lambda: self._step_timeline(1))
        QShortcut(QKeySequence("Delete"), self, activated=self._delete_current_record)

    def bring_to_front_and_focus_search(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.switch_tab(0)
        self.focus_search()

    def focus_search(self) -> None:
        self.search_input.setFocus()
        self.search_input.selectAll()

    def open_settings(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.switch_tab(3)

    def request_quit(self) -> None:
        self._force_quit = True
        self._rewind_timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.close()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        can_tray = bool(QSystemTrayIcon.isSystemTrayAvailable()) and self.config.minimize_to_tray
        if self._force_quit or not can_tray:
            self._rewind_timer.stop()
            self._executor.shutdown(wait=False, cancel_futures=True)
            if event:
                event.accept()
            return
        self.hide()
        if event:
            event.ignore()

    # ═════════════════════════════════════════════════════════════════════════
    # CAPTURE & PRIVACY CONTROLS
    # ═════════════════════════════════════════════════════════════════════════

    def toggle_pause(self) -> None:
        paused = self.capture_service.toggle_pause()
        self._update_pause_ui(paused)
        self.pause_state_changed.emit(paused)

    def pause_for_minutes(self, minutes: int) -> None:
        self.capture_service.pause_for_minutes(minutes)
        self._update_pause_ui(True)
        self.pause_state_changed.emit(True)
        self.statusBar().showMessage(f"Capture paused for {minutes}m.", 4000)

    def _update_pause_ui(self, paused: bool) -> None:
        t = self.i18n.t
        self.pause_btn.setText(t("btn_resume") if paused else t("btn_pause"))
        self.pause_btn.setIcon(make_flat_icon("play" if paused else "pause", "#38BDF8" if paused else "#E4E4E7", 12))
        self.setWindowIcon(create_app_icon(paused=paused))
        self.logo_lbl.setPixmap(create_app_pixmap(32, paused=paused))
        if paused:
            self.btn_nav_timeline.set_badge(t("badge_paused"), kind="paused")
            self._sb_dot.setStyleSheet("background-color: #F59E0B; border-radius: 4px; border: none;")
            self.lbl_sb_status.setText(t("status_shield_paused"))
        else:
            self.btn_nav_timeline.set_badge(t("badge_rec"), kind="live")
            self._sb_dot.setStyleSheet("background-color: #10B981; border-radius: 4px; border: none;")
            self.lbl_sb_status.setText(t("status_shield_on"))

    def capture_now(self) -> None:
        capture_id = self.capture_service.capture_once(force=True)
        if capture_id is None:
            self.statusBar().showMessage("Capture skipped by Privacy Shield or permission guard.", 4000)
        else:
            self.refresh_all(sync=True)

    def load_demo_timeline(self) -> None:
        count = populate_demo_timeline(self.db, self.media)
        self._thumb_cache.clear()
        self.refresh_all(sync=True)
        self.statusBar().showMessage(self.i18n.t("btn_demo_loaded", count=count), 5000)

    def purge_last_15_minutes(self) -> None:
        removed = self.capture_service.purge_last_minutes(15)
        self._current_record = None
        self._thumb_cache.clear()
        self.refresh_all(sync=True)
        self.statusBar().showMessage(self.i18n.t("msg_purged", count=removed), 5000)

    def _confirm_and_purge_minutes(self, minutes: int) -> None:
        reply = QMessageBox.question(
            self,
            self.i18n.t("confirm_purge_title"),
            self.i18n.t("confirm_purge_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = self.capture_service.purge_last_minutes(minutes)
        self._current_record = None
        self._thumb_cache.clear()
        self.refresh_all(sync=True)
        self.statusBar().showMessage(self.i18n.t("msg_purged", count=removed), 5000)

    def _confirm_and_purge_today(self) -> None:
        reply = QMessageBox.question(
            self,
            self.i18n.t("confirm_purge_title"),
            self.i18n.t("confirm_purge_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = self.capture_service.purge_today()
        self._current_record = None
        self._thumb_cache.clear()
        self.refresh_all(sync=True)
        self.statusBar().showMessage(self.i18n.t("msg_purged", count=removed), 5000)

    def _save_privacy_rules(self) -> None:
        self.config.pii_redaction_mode = str(self.pii_mode_combo.currentData() or PII_MODE_REDACT_AND_BLUR)
        self.config.password_manager_guard = self.sw_pm_guard.isChecked()
        self.config.incognito_guard = self.sw_incognito_guard.isChecked()
        if not self.sw_idle_guard.isChecked():
            self.config.idle_pause_sec = 0.0
            self.idle_spin.setValue(0)
        elif self.config.idle_pause_sec <= 0:
            self.config.idle_pause_sec = 60.0
            self.idle_spin.setValue(60)
        self.config.blocked_processes = [
            ln.strip() for ln in self.processes_edit.toPlainText().splitlines() if ln.strip()
        ]
        self.config.blocked_title_keywords = [
            ln.strip() for ln in self.keywords_edit.toPlainText().splitlines() if ln.strip()
        ]
        self.config.save()
        self.capture_service.apply_config(self.config)
        self.config_changed.emit(self.config)
        self._refresh_privacy_badges()
        self.statusBar().showMessage(self.i18n.t("msg_privacy_saved"), 4000)

    def save_settings_from_page(self) -> None:
        """Saves Settings page to AppConfig (Bug #2 fix: preserves monitor_index=0!)."""
        mon_val = self.monitor_combo.currentData()
        self.config.monitor_index = 1 if mon_val is None else int(mon_val)
        self.config.capture_interval_sec = float(self.interval_spin.value())
        self.config.idle_pause_sec = float(self.idle_spin.value())
        self.sw_idle_guard.setChecked(self.config.idle_pause_sec > 0)
        self.config.diff_threshold = float(self.diff_spin.value())
        self.config.webp_quality = int(self.quality_spin.value())
        self.config.max_storage_gb = float(self.quota_spin.value())
        self.config.retention_days = int(self.retention_spin.value())
        self.config.archive_images_after_days = int(self.archival_spin.value())
        self.config.cpu_profile = str(self.cpu_profile_combo.currentData() or PROFILE_AUTO)
        self.config.ocr_enabled = self.sw_ocr.isChecked()
        self.config.global_hotkey_enabled = self.sw_hotkey.isChecked()
        self.config.global_hotkey = self.hotkey_edit.text().strip() or get_default_hotkey()
        self.config.auto_start = self.sw_autostart.isChecked()
        self.config.minimize_to_tray = self.sw_tray.isChecked()
        self.config.check_updates_on_startup = self.sw_auto_update.isChecked()
        self.config.ui_language = str(self.lang_combo.currentData() or "en")

        self.config.save()
        set_autostart(self.config.auto_start)
        self.capture_service.apply_config(self.config)
        self.lbl_sb_keycap.setText(self.config.global_hotkey)
        self.set_kpi_budget.set_metric(
            f"{self.capture_service.tuning.ocr_intra_threads} Thread(s)",
            badge_text=self.capture_service.tuning.effective_profile.upper(),
        )
        self.set_kpi_vault.set_metric(
            f"{self.config.retention_days}d / {self.config.max_storage_gb:g} GB"
        )
        self.lbl_hw_summary.setText(
            format_hardware_summary(self.capture_service.hw_profile, self.capture_service.tuning, lang=self.i18n.lang)
        )
        self.config_changed.emit(self.config)
        self.statusBar().showMessage(self.i18n.t("msg_saved"), 4000)

    def _request_screen_permission(self) -> None:
        granted = request_screen_recording_permission()
        self._refresh_permission_indicator()
        if not granted:
            self.statusBar().showMessage(self.i18n.t("perm_missing"), 5000)

    def _refresh_permission_indicator(self) -> None:
        ok = has_screen_recording_permission()
        self.perm_banner.setVisible(not ok)
        self.lbl_perm_status.setText(self.i18n.t("perm_ok") if ok else self.i18n.t("perm_missing"))
        self.lbl_perm_status.setStyleSheet(
            "color: #10B981; font-size: 8.2pt; font-weight: 600;"
            if ok
            else "color: #F59E0B; font-size: 8.2pt; font-weight: 600;"
        )

    # ═════════════════════════════════════════════════════════════════════════
    # ASYNC DATA REFRESH, SEARCH & THUMBNAILS (BUG #6 FIX)
    # ═════════════════════════════════════════════════════════════════════════

    def refresh_all(self, sync: bool = False) -> None:
        self._refresh_apps_combo()
        self._refresh_timeline()
        self.refresh_results(sync=sync)
        self._refresh_stats()
        self._refresh_privacy_badges()
        if self._current_tab == 1:
            self._refresh_insights_page()

    def _refresh_apps_combo(self) -> None:
        current = self.app_filter.currentData() or ""
        apps = self.db.list_apps()
        self.app_filter.blockSignals(True)
        self.app_filter.clear()
        self.app_filter.addItem(self.i18n.t("all_apps"), "")
        for app in apps:
            self.app_filter.addItem(app, app)
        idx = self.app_filter.findData(current)
        if idx >= 0:
            self.app_filter.setCurrentIndex(idx)
        self.app_filter.blockSignals(False)

    def _refresh_timeline(self) -> None:
        self._timeline_records = self.db.get_timeline(limit=1000)
        cur_idx = -1
        if self._current_record:
            for i, rec in enumerate(self._timeline_records):
                if rec.id == self._current_record.id:
                    cur_idx = i
                    break
        if cur_idx < 0 and self._timeline_records:
            cur_idx = len(self._timeline_records) - 1
        self.timeline_ribbon.set_records(self._timeline_records, cur_idx)
        if 0 <= cur_idx < len(self._timeline_records):
            self.timeline_label.setText(self._timeline_records[cur_idx].timestamp.replace("T", " "))
        else:
            self.timeline_label.setText("—")

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
        self.refresh_results(sync=False)

    def refresh_results(self, sync: bool = False) -> None:
        query = self.search_input.text().strip()
        mode = str(self.search_mode_combo.currentData() or "hybrid")
        app_name = self.app_filter.currentData() or None
        start_dt, end_dt = self._get_date_range()
        pinned_only = self.pinned_filter_btn.isChecked()

        self._search_gen += 1
        gen = self._search_gen

        def _do_search() -> tuple[list[SearchResult], float]:
            t0 = time.perf_counter()
            res = self.search_engine.search(
                query=query,
                mode=mode,
                app_name=app_name,
                start=start_dt,
                end=end_dt,
                pinned_only=pinned_only,
                limit=150,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return res, elapsed_ms

        if sync:
            results, ms = _do_search()
            self._apply_search_results(gen, results, ms, sync_thumbs=True)
        else:
            def _bg() -> None:
                try:
                    results, ms = _do_search()
                    self._search_ready.emit(gen, results, ms)
                except Exception:
                    pass

            self._executor.submit(_bg)

    def _load_thumb_qimage(self, rel_path: str) -> QImage | None:
        if not rel_path:
            return None
        full_path = self.media.resolve_path(rel_path)
        if not full_path.exists():
            return None
        img = QImage(str(full_path))
        if img.isNull():
            return None
        return img.scaled(
            192,
            108,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _request_thumb_async(self, rel_path: str) -> QPixmap | None:
        if not rel_path:
            return None
        cached = self._thumb_cache.get(rel_path)
        if cached is not None:
            self._thumb_cache.move_to_end(rel_path)
            return cached
        if rel_path in self._thumb_inflight:
            return None
        self._thumb_inflight.add(rel_path)

        def _bg_thumb() -> None:
            qimg = self._load_thumb_qimage(rel_path)
            self._thumb_ready.emit(rel_path, qimg)

        self._executor.submit(_bg_thumb)
        return None

    def _on_thumb_loaded(self, rel_path: str, qimg: object) -> None:
        self._thumb_inflight.discard(rel_path)
        if not isinstance(qimg, QImage) or qimg.isNull():
            return
        pm = QPixmap.fromImage(qimg)
        self._thumb_cache[rel_path] = pm
        if len(self._thumb_cache) > 300:
            self._thumb_cache.popitem(last=False)

        for i in range(self.results_list.count()):
            item = self.results_list.item(i)
            if item is None:
                continue
            rec: CaptureRecord | None = item.data(_ROLE_RECORD)
            if rec and rec.image_path == rel_path:
                item.setData(_ROLE_THUMB, pm)
        self.results_list.viewport().update()

    def _apply_search_results(
        self,
        gen: int,
        results: list[SearchResult],
        elapsed_ms: float,
        sync_thumbs: bool = False,
    ) -> None:
        if gen != self._search_gen:
            return

        selected_id = self._current_record.id if self._current_record else None
        self.results_list.blockSignals(True)
        self.results_list.clear()

        restored_row = -1
        for idx, res in enumerate(results):
            rec = res.record
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, rec.id)
            item.setData(_ROLE_RECORD, rec)
            item.setData(_ROLE_SNIPPET, res.snippet)
            item.setData(_ROLE_MATCH_TYPE, res.match_type)

            thumb: QPixmap | None = None
            if not rec.image_archived and rec.image_path:
                if sync_thumbs:
                    thumb = self._thumb_cache.get(rec.image_path)
                    if thumb is None:
                        qimg = self._load_thumb_qimage(rec.image_path)
                        if qimg is not None and not qimg.isNull():
                            thumb = QPixmap.fromImage(qimg)
                            self._thumb_cache[rec.image_path] = thumb
                else:
                    thumb = self._request_thumb_async(rec.image_path)
            item.setData(_ROLE_THUMB, thumb)

            self.results_list.addItem(item)
            if selected_id is not None and rec.id == selected_id:
                restored_row = idx

        self.results_list.blockSignals(False)
        if self.search_input.text().strip():
            self.results_header.setText(self.i18n.t("results_header_ms", count=len(results), ms=elapsed_ms))
        else:
            self.results_header.setText(self.i18n.t("results_header", count=len(results)))

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
        # O(1) SQL stats — zero filesystem walk on UI thread (Bug #6 fix!)
        stats = self.db.get_stats()
        size_mb = stats["total_image_bytes"] / (1024.0 * 1024.0)
        pending = self.capture_service.ocr_worker.pending_count
        self.btn_nav_insights.set_badge(str(stats["total"]), kind="muted")
        self.stats_label.setText(
            f"Captures: {stats['total']}  ·  OCR: {stats['ocr_done']} (Q:{pending})  ·  "
            f"Shield: {stats['privacy_blocks']}  ·  Disk: {size_mb:.1f} MB  ·  0 MB VRAM"
        )

    def _refresh_privacy_badges(self) -> None:
        stats = self.db.get_stats()
        blocks = stats["privacy_blocks"]
        self.btn_nav_privacy.set_badge(
            f"{blocks}" if blocks > 0 else self.i18n.t("badge_shield"),
            kind="shield",
        )
        self.lbl_priv_hero_stat.setText(f"{blocks} BLOCKED · {stats['pii_redactions']} PII")

    def _refresh_insights_page(self) -> None:
        t = self.i18n.t
        stats = self.db.get_stats()
        total = stats["total"]
        img_mb = stats["total_image_bytes"] / (1024.0 * 1024.0)
        db_mb = self.db.db_path.stat().st_size / (1024.0 * 1024.0) if self.db.db_path.exists() else 0.0

        checked = max(stats["dedup_checked"], self.capture_service.diff_lock.total_checked)
        skipped = max(stats["dedup_skipped"], self.capture_service.diff_lock.total_skipped)
        savings_pct = (skipped / float(checked) * 100.0) if checked > 0 else 0.0

        quota_str = f"{self.config.max_storage_gb:g} GB" if self.config.max_storage_gb > 0 else "∞"
        quota_pct = (
            min(100, int((img_mb / max(1.0, self.config.max_storage_gb * 1024.0)) * 100.0))
            if self.config.max_storage_gb > 0
            else 15
        )

        self.kpi_captures.set_metric(
            f"{total:,}",
            sub_text=t("kpi_ocr_sub", done=stats["ocr_done"], pinned=stats["pinned"]),
            bar_pct=min(100, max(10, int((stats["ocr_done"] / max(1, total)) * 100))),
        )
        self.kpi_dedup.set_metric(
            f"{savings_pct:.1f}%",
            sub_text=t("kpi_dedup_sub", skipped=skipped, checked=checked),
            bar_pct=int(savings_pct),
        )
        self.kpi_storage.set_metric(
            f"{img_mb:.1f} MB",
            sub_text=t("kpi_storage_sub", db_mb=db_mb, quota=quota_str),
            bar_pct=max(6, quota_pct),
        )
        self.kpi_privacy.set_metric(
            f"{stats['privacy_blocks']}",
            sub_text=t("kpi_privacy_sub", pii=stats["pii_redactions"]),
            bar_pct=min(100, max(12, stats["privacy_blocks"] * 4)),
        )

        # Hourly chart
        self.hourly_chart.set_data(self.db.get_hourly_activity(days=7))

        # Rebuild app breakdown rows
        while self.apps_breakdown_layout.count():
            item = self.apps_breakdown_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

        breakdown = self.db.get_app_breakdown(limit=10)
        max_cnt = breakdown[0][1] if breakdown else 1
        if not breakdown:
            empty = QLabel(t("no_selection"))
            empty.setObjectName("metaLabel")
            self.apps_breakdown_layout.addWidget(empty)
        else:
            for app_name, cnt in breakdown:
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(8)

                dot = QFrame()
                dot.setFixedSize(8, 8)
                col = app_color_for_name(app_name)
                dot.setStyleSheet(f"background-color: {col}; border-radius: 4px;")
                rl.addWidget(dot)

                lbl = QLabel(app_name)
                lbl.setMinimumWidth(115)
                lbl.setStyleSheet("color: #FAFAFA; font-size: 8.6pt; font-weight: 600;")
                rl.addWidget(lbl)

                bar = QProgressBar()
                bar.setMaximum(max_cnt)
                bar.setValue(cnt)
                bar.setTextVisible(False)
                bar.setFixedHeight(8)
                bar.setStyleSheet(
                    f"QProgressBar {{ background-color: #1D1D24; border-radius: 4px; }}"
                    f"QProgressBar::chunk {{ background-color: {col}; border-radius: 4px; }}"
                )
                rl.addWidget(bar, stretch=1)

                cnt_lbl = QLabel(str(cnt))
                cnt_lbl.setMinimumWidth(34)
                cnt_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                cnt_lbl.setStyleSheet("color: #A1A1AA; font-size: 8.2pt; font-weight: 700;")
                rl.addWidget(cnt_lbl)

                btn_flt = QPushButton(t("btn_filter_app"))
                btn_flt.setObjectName("subtleButton")
                btn_flt.clicked.connect(lambda checked=False, a=app_name: self._filter_by_app(a))
                rl.addWidget(btn_flt)

                btn_prg = QPushButton(t("btn_purge_app"))
                btn_prg.setObjectName("dangerButton")
                btn_prg.setStyleSheet("padding: 3px 8px; font-size: 7.8pt;")
                btn_prg.clicked.connect(lambda checked=False, a=app_name: self._purge_app_confirm(a))
                rl.addWidget(btn_prg)

                self.apps_breakdown_layout.addWidget(row)

    def _filter_by_app(self, app_name: str) -> None:
        self.switch_tab(0)
        idx = self.app_filter.findData(app_name)
        if idx >= 0:
            self.app_filter.setCurrentIndex(idx)
        else:
            self.search_input.setText(f'app:"{app_name}"')
        self.refresh_results(sync=True)

    def _purge_app_confirm(self, app_name: str) -> None:
        reply = QMessageBox.question(
            self,
            self.i18n.t("confirm_purge_title"),
            f"{self.i18n.t('confirm_purge_body')}\n\nApp: {app_name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = self.capture_service.purge_app(app_name)
        self._current_record = None
        self._thumb_cache.clear()
        self.refresh_all(sync=True)
        self.statusBar().showMessage(self.i18n.t("msg_purged", count=removed), 5000)

    # ═════════════════════════════════════════════════════════════════════════
    # SELECTION, TIMELINE REWIND, PINNING & EXPORT
    # ═════════════════════════════════════════════════════════════════════════

    def _step_timeline(self, delta: int) -> None:
        if not self._timeline_records:
            return
        cur = self.timeline_ribbon.current_index
        if cur < 0:
            cur = len(self._timeline_records) - 1
        new_val = max(0, min(len(self._timeline_records) - 1, cur + delta))
        self.timeline_ribbon.set_current_index(new_val, emit_signal=True)

    def _toggle_rewind_playback(self) -> None:
        if self._rewind_timer.isActive():
            self._rewind_timer.stop()
            self.rewind_btn.setIcon(make_flat_icon("play", "#38BDF8", 12))
        else:
            if not self._timeline_records:
                return
            if self.timeline_ribbon.current_index <= 0:
                self.timeline_ribbon.set_current_index(len(self._timeline_records) - 1, emit_signal=True)
            self._rewind_timer.start()
            self.rewind_btn.setIcon(make_flat_icon("stop", "#F59E0B", 12))

    def _on_rewind_tick(self) -> None:
        if not self._timeline_records:
            self._toggle_rewind_playback()
            return
        cur = self.timeline_ribbon.current_index
        if cur <= 0:
            self._toggle_rewind_playback()
            return
        self.timeline_ribbon.set_current_index(cur - 1, emit_signal=True)

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
        if 0 <= index < len(self._timeline_records):
            rec = self._timeline_records[index]
            fresh = self.db.get_capture(rec.id) or rec
            self._show_record(fresh, sync_ribbon=False)

    def _on_toggle_all_boxes(self, checked: bool) -> None:
        self.preview_widget.set_show_all_boxes(checked)

    def _on_box_clicked(self, text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard and text:
            clipboard.setText(text)
            self.statusBar().showMessage(self.i18n.t("msg_box_copied", text=text[:60]), 3500)

    def _toggle_pin_current(self) -> None:
        if not self._current_record:
            self.pin_btn.setChecked(False)
            return
        new_state = not self._current_record.pinned
        self.db.set_pinned(self._current_record.id, new_state)
        fresh = self.db.get_capture(self._current_record.id)
        if fresh:
            self._current_record = fresh
        self.refresh_all(sync=True)

    def _save_current_note(self) -> None:
        if not self._current_record:
            return
        note = self.note_input.text().strip()
        self.db.update_note(self._current_record.id, note)
        fresh = self.db.get_capture(self._current_record.id)
        if fresh:
            self._current_record = fresh
        self.statusBar().showMessage(self.i18n.t("msg_note_saved"), 3000)

    def _show_record(self, record: CaptureRecord | None, sync_ribbon: bool = True) -> None:
        self._current_record = record
        t = self.i18n.t
        if record is None:
            self.meta_label.setText(t("no_selection"))
            self.preview_widget.set_image(None, placeholder=t("preview_empty"))
            self.preview_widget.set_ocr_boxes([])
            self.ocr_view.setPlainText("")
            self.note_input.setText("")
            self.ocr_header.setText(t("ocr_header"))
            self.timeline_label.setText("—")
            self.pin_btn.setChecked(False)
            self.pin_btn.setText(t("btn_pin"))
            return

        ts_human = record.timestamp.replace("T", " ")
        self.meta_label.setText(
            f"{ts_human}  ·  {record.app_name or 'Screen'}  ·  {record.window_title or '(Untitled)'}"
        )
        self.timeline_label.setText(ts_human)
        self.pin_btn.setChecked(record.pinned)
        self.pin_btn.setText(t("btn_pinned") if record.pinned else t("btn_pin"))
        self.note_input.setText(record.note)

        if record.image_archived:
            self.preview_widget.set_image(None, placeholder=t("preview_archived"))
        else:
            img_path = self.media.resolve_path(record.image_path)
            if img_path.exists():
                self.preview_widget.set_image(QPixmap(str(img_path)))
            else:
                self.preview_widget.set_image(None, placeholder=t("preview_missing"))

        boxes = OCRResult.parse_boxes(record.ocr_boxes)
        self.preview_widget.set_ocr_boxes(boxes)
        self.preview_widget.set_highlight_query(self.search_input.text())

        matched_cnt = self.preview_widget.matched_box_count
        if matched_cnt > 0:
            self.ocr_header.setText(t("ocr_header_matched", count=matched_cnt))
        else:
            self.ocr_header.setText(t("ocr_header_boxes", count=len(boxes)))

        if record.ocr_done:
            self.ocr_view.setPlainText(record.ocr_text or "(No text extracted)")
        else:
            self.ocr_view.setPlainText("Running offline RapidOCR…")

        if sync_ribbon and self._timeline_records:
            for i, item in enumerate(self._timeline_records):
                if item.id == record.id:
                    self.timeline_ribbon.set_current_index(i, emit_signal=False)
                    break

    def _export_current_image(self) -> None:
        if not self._current_record:
            return
        src = self.media.resolve_path(self._current_record.image_path)
        if not src.exists():
            self.statusBar().showMessage(self.i18n.t("preview_missing"), 4000)
            return
        default_name = f"localrecall_{self._current_record.timestamp.replace(':', '-')}.png"
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Annotated Screenshot",
            default_name,
            "Annotated PNG (*.png);;Original WebP (*.webp)",
        )
        if not target_path:
            return
        if target_path.lower().endswith(".webp"):
            shutil.copy2(src, target_path)
        else:
            annotated = self.preview_widget.render_annotated_pixmap(include_all_boxes=self.show_boxes_btn.isChecked())
            if annotated is not None:
                annotated.save(target_path, "PNG")
            else:
                QPixmap(str(src)).save(target_path, "PNG")
        self.statusBar().showMessage(self.i18n.t("msg_png_saved", path=target_path), 4000)

    def _export_daily_digest(self) -> None:
        default_name = f"localrecall_digest_{datetime.now().strftime('%Y-%m-%d')}.md"
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            self.i18n.t("btn_export_digest"),
            default_name,
            "Markdown (*.md)",
        )
        if not target_path:
            return
        records = self.db.get_timeline(limit=500)
        export_daily_markdown_digest(records, Path(target_path))
        self.statusBar().showMessage(self.i18n.t("msg_digest_saved", path=target_path), 4500)

    def _copy_ocr_text(self) -> None:
        text = self.ocr_view.toPlainText().strip()
        if text:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
            self.statusBar().showMessage(self.i18n.t("msg_copied"), 3000)

    def _delete_current_record(self) -> None:
        if not self._current_record:
            return
        reply = QMessageBox.question(
            self,
            self.i18n.t("confirm_delete_title"),
            self.i18n.t("confirm_delete_body"),
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
        self.refresh_all(sync=True)
        self.statusBar().showMessage(self.i18n.t("msg_deleted"), 3000)

    def _run_vacuum(self) -> None:
        self.db.vacuum()
        self._refresh_insights_page()
        self.statusBar().showMessage(self.i18n.t("msg_vacuumed"), 4000)

    def _run_retention(self) -> None:
        removed = self.capture_service.run_retention_cleanup()
        self._thumb_cache.clear()
        self.refresh_all(sync=True)
        self.statusBar().showMessage(self.i18n.t("msg_purged", count=removed), 4000)

    # ═════════════════════════════════════════════════════════════════════════
    # AUTO-UPDATER & BUILT-IN LOCAL BENCHMARK
    # ═════════════════════════════════════════════════════════════════════════

    def _start_silent_update_check(self) -> None:
        if UpdateCheckerThread is None or (self._update_thread and self._update_thread.isRunning()):
            return
        self._update_thread = UpdateCheckerThread(current_version=__version__, parent=self)
        self._update_thread.update_checked.connect(lambda info: self._on_update_checked(info, silent=True))
        self._update_thread.start()

    def _check_updates_manual(self) -> None:
        if UpdateCheckerThread is None:
            return
        self.lbl_update_status.setText(self.i18n.t("update_checking"))
        self.btn_check_update.setEnabled(False)
        self._update_thread = UpdateCheckerThread(current_version=__version__, parent=self)
        self._update_thread.update_checked.connect(lambda info: self._on_update_checked(info, silent=False))
        self._update_thread.start()

    def _on_update_checked(self, info: UpdateInfo, silent: bool = False) -> None:
        self.btn_check_update.setEnabled(True)
        self._latest_update_info = info
        if info.error:
            if not silent:
                self.lbl_update_status.setText(self.i18n.t("update_error"))
            return
        if info.is_update_available:
            self.lbl_update_status.setText(
                self.i18n.t("update_available", latest=info.latest_version, current=info.current_version)
            )
            self.btn_download_update.show()
        elif not silent:
            self.lbl_update_status.setText(self.i18n.t("update_up_to_date", version=info.current_version))

    def _download_latest_update(self) -> None:
        info = self._latest_update_info
        if not info:
            return
        if not info.has_direct_installer or UpdateDownloadThread is None:
            webbrowser.open(info.release_url)
            return
        self.btn_download_update.setEnabled(False)
        dest = str(self.config.data_path / "updates")
        self._download_thread = UpdateDownloadThread(info=info, dest_dir=dest, parent=self)
        self._download_thread.progress_changed.connect(
            lambda dl, tot: self.lbl_update_status.setText(
                f"Downloading {info.asset_name}: {dl / (1024 * 1024):.1f} / {max(1, tot) / (1024 * 1024):.1f} MB"
            )
        )
        self._download_thread.download_finished.connect(self._on_update_downloaded)
        self._download_thread.start()

    def _on_update_downloaded(self, path: str, err: str) -> None:
        self.btn_download_update.setEnabled(True)
        if err or not path:
            self.lbl_update_status.setText(f"Update download failed: {err}")
            return
        should_exit, msg = apply_downloaded_update(path)
        self.lbl_update_status.setText(msg)
        if should_exit:
            self.request_quit()
            QApplication.quit()

    def _run_inline_benchmark(self) -> None:
        from PIL import Image

        lock = FrameDiffLock(threshold=0.015, history_size=8)
        img = Image.new("RGB", (1920, 1080), color=(24, 28, 36))
        lock.has_changed(img)
        t0 = time.perf_counter()
        for _ in range(50):
            lock.has_changed(img)
        diff_ms = ((time.perf_counter() - t0) * 1000.0) / 50.0

        redactor = PIIRedactor()
        sample = "API key sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz1234 and IBAN TR330006100519786457841326"
        t1 = time.perf_counter()
        for _ in range(200):
            redactor.redact_text(sample)
        pii_us = ((time.perf_counter() - t1) * 1_000_000.0) / 200.0

        t2 = time.perf_counter()
        self.search_engine.search("LocalRecall", mode="hybrid")
        search_ms = (time.perf_counter() - t2) * 1000.0

        summary = (
            f"Benchmark: DiffLock {diff_ms:.2f} ms/frame · FTS5+RRF Search {search_ms:.2f} ms · "
            f"PII Shield {pii_us:.0f} µs/frame · 0 MB VRAM"
        )
        self.lbl_update_status.setText(summary)
        self.statusBar().showMessage(summary, 6000)

    # ═════════════════════════════════════════════════════════════════════════
    # BACKGROUND SIGNALS
    # ═════════════════════════════════════════════════════════════════════════

    def _on_capture_updated(self, capture_id: int) -> None:
        self._refresh_apps_combo()
        self._refresh_timeline()
        self._refresh_stats()
        self._refresh_privacy_badges()
        if not self.search_input.text().strip():
            self.refresh_results(sync=False)
        elif self._current_record and self._current_record.id == capture_id:
            rec = self.db.get_capture(capture_id)
            if rec:
                self._show_record(rec)

    def _on_status_updated(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
        self._refresh_privacy_badges()
