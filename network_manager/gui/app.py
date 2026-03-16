"""
Main application GUI — PySide6 version with true glass transparency.
bg.png is painted on the main window; every panel uses rgba() for see-through glass.
"""
import sys, os, re, json, time, threading, ipaddress, base64
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QLineEdit, QPlainTextEdit, QComboBox,
    QCheckBox, QListWidget, QListWidgetItem, QScrollArea, QSplitter,
    QMessageBox, QInputDialog, QFileDialog, QDialog, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QMenuBar,
    QSizePolicy, QAbstractItemView, QStackedWidget, QToolTip,
)
from PySide6.QtCore import Qt, QTimer, QSize, Signal, QMetaObject, Q_ARG, QThread
from PySide6.QtGui import (
    QPixmap, QPainter, QFont, QColor, QIcon, QPalette, QAction,
    QFontDatabase,
)

# ── helper functions (kept from original) ───────────────────────────────

def _obfuscate(plaintext: str) -> str:
    if not plaintext:
        return ""
    return base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

def _deobfuscate(stored: str) -> str:
    if not stored:
        return ""
    try:
        return base64.b64decode(stored.encode("ascii")).decode("utf-8")
    except Exception:
        return stored

def _truncate(text: str, max_chars: int = 22) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "\u2026"

# ── project imports ─────────────────────────────────────────────────────

from ..config import DB_PATH, GNS3_DEFAULT_URL, CONFIG_FILE, conn, cur, db_lock, _db_error
from ..models import DeviceModel, RouterModel, SwitchModel, CoreSwitchModel
from ..network import Sender, GNS3Connector
from .utils import apply_responsive_geometry

try:
    import requests
except Exception:
    requests = None

# ── glass stylesheet ────────────────────────────────────────────────────

GLASS_PANEL = """
    QFrame[glassPanel="true"] {
        background-color: rgba(7, 16, 31, 160);
        border-radius: 16px;
        border: 1px solid rgba(70, 140, 230, 60);
    }
"""

GLASS_STYLE = """
    * {
        font-family: 'Segoe UI', 'Inter', sans-serif;
        color: #C9D1D9;
    }

    QMainWindow {
        background: transparent;
    }

    QFrame[glassPanel="true"] {
        background-color: rgba(7, 16, 31, 160);
        border-radius: 16px;
        border: 1px solid rgba(70, 140, 230, 60);
    }

    QFrame[topBar="true"] {
        background-color: rgba(7, 16, 31, 180);
        border-radius: 0px;
        border: none;
        border-bottom: 1px solid rgba(70, 140, 230, 40);
    }

    QLabel {
        background: transparent;
        border: none;
    }

    QPushButton {
        background-color: rgba(55, 65, 81, 200);
        color: #9ca3af;
        border: none;
        border-radius: 8px;
        padding: 6px 14px;
        font-size: 13px;
    }
    QPushButton:hover {
        background-color: rgba(75, 85, 99, 220);
        color: #FFFFFF;
    }
    QPushButton:pressed {
        background-color: rgba(88, 166, 255, 200);
    }
    QPushButton:disabled {
        background-color: rgba(40, 50, 60, 150);
        color: #555;
    }

    QPushButton[accent="true"] {
        background-color: rgba(37, 99, 235, 220); /* Figma's vibrant blue */
        color: white;
        font-weight: 700;
    }
    QPushButton[accent="true"]:hover {
        background-color: rgba(59, 130, 246, 255);
    }
    
    QPushButton[pill="true"] {
        border-radius: 20px;
        padding: 8px 20px;
        font-size: 14px;
        font-weight: 700;
    }

    QPushButton[teal="true"] {
        background-color: rgba(13, 148, 136, 220);
        color: white;
        font-weight: bold;
    }
    QPushButton[teal="true"]:hover {
        background-color: rgba(15, 118, 110, 240);
    }

    QPushButton[outlined="true"] {
        background-color: transparent;
        color: #4A9EFF;
        border: 1px solid #4A9EFF;
    }
    QPushButton[outlined="true"]:hover {
        background-color: rgba(12, 24, 40, 180);
    }

    QPushButton[danger="true"] {
        background-color: transparent;
        color: #EF4444;
        border: 1px solid #EF4444;
    }
    QPushButton[danger="true"]:hover {
        background-color: rgba(26, 10, 10, 180);
    }
    
    /* Top Nav Tabs Active/Inactive Styling */
    QPushButton[navTab="active"] {
        background: transparent;
        color: #3B82F6;
        font-size: 16px;
        font-weight: 800;
        border: none;
        border-bottom: 2px solid #3B82F6;
        border-radius: 0px;
        padding: 6px 16px;
    }
    QPushButton[navTab="inactive"] {
        background: transparent;
        color: #6B7280;
        font-size: 16px;
        font-weight: 600;
        border: none;
        border-radius: 0px;
        padding: 6px 16px;
    }
    QPushButton[navTab="inactive"]:hover {
        color: #D1D5DB;
        background: transparent;
    }

    QLineEdit {
        background-color: rgba(43, 50, 63, 200);
        color: #FFFFFF;
        border: 1px solid #6B7280;
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 13px;
    }
    QLineEdit:disabled {
        background-color: rgba(96, 101, 111, 150);
        border-color: #777D81;
        color: #666;
    }
    QLineEdit:focus {
        border-color: #58A6FF;
    }

    QPlainTextEdit {
        background-color: rgba(22, 27, 34, 220);
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 13px;
        padding: 8px;
    }

    QComboBox {
        background-color: rgba(12, 26, 46, 200);
        color: #FFFFFF;
        border: 1px solid rgba(70, 140, 230, 40);
        border-radius: 8px;
        padding: 6px 12px;
        font-size: 13px;
    }
    QComboBox::drop-down {
        border: none;
        width: 24px;
    }
    QComboBox QAbstractItemView {
        background-color: #0C1A2E;
        color: #FFFFFF;
        selection-background-color: #1A2840;
        border: 1px solid rgba(70, 140, 230, 40);
    }

    QCheckBox {
        background: transparent;
        spacing: 6px;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border: 1px solid #6B7280;
        border-radius: 4px;
        background: rgba(43, 50, 63, 200);
    }
    QCheckBox::indicator:checked {
        background: #58A6FF;
        border-color: #58A6FF;
    }

    QListWidget {
        background-color: rgba(12, 26, 46, 180);
        border: 1px solid rgba(26, 40, 64, 200);
        border-radius: 8px;
        padding: 4px;
        font-size: 12px;
    }
    QListWidget::item {
        padding: 8px 10px;
        border-radius: 4px;
    }
    QListWidget::item:selected {
        background-color: rgba(88, 166, 255, 60);
        color: #FFFFFF;
    }
    QListWidget::item:hover {
        background-color: rgba(88, 166, 255, 30);
    }

    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }

    QScrollBar:vertical {
        background: rgba(12, 26, 46, 100);
        width: 8px;
        border-radius: 4px;
    }
    QScrollBar::handle:vertical {
        background: rgba(88, 166, 255, 80);
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }

    QTableWidget {
        background-color: rgba(22, 27, 34, 200);
        color: #C9D1D9;
        border: none;
        border-radius: 8px;
        gridline-color: rgba(48, 54, 61, 150);
        font-size: 12px;
    }
    QTableWidget::item:selected {
        background-color: rgba(38, 79, 120, 200);
        color: #FFFFFF;
    }
    QHeaderView::section {
        background-color: rgba(31, 38, 48, 220);
        color: #8B949E;
        border: none;
        padding: 6px;
        font-weight: bold;
    }

    QMenuBar {
        background-color: rgba(7, 16, 31, 200);
        color: #C9D1D9;
    }
    QMenuBar::item:selected {
        background-color: rgba(88, 166, 255, 80);
    }
    QMenu {
        background-color: #0C1A2E;
        color: #C9D1D9;
        border: 1px solid rgba(70, 140, 230, 40);
    }
    QMenu::item:selected {
        background-color: rgba(88, 166, 255, 80);
    }
"""

# ── Main Window ─────────────────────────────────────────────────────────

class App(QMainWindow):
    """Main application window with glass-transparent panels over bg.png."""

    _main_thread_call = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANCS - Network Manager")
        screen = QApplication.primaryScreen().geometry()
        w = min(1180, screen.width() - 80)
        h = min(720, screen.height() - 80)
        self.resize(w, h)
        self.setMinimumSize(650, 450)

        # Load bg.png
        gui_dir = os.path.dirname(os.path.abspath(__file__))
        bg_path = os.path.join(gui_dir, "bg.png")
        self._bg_pixmap = QPixmap(bg_path) if os.path.exists(bg_path) else QPixmap()

        # Load logo
        self._logo_pixmap = QPixmap()
        for name in ("ancs_logo.png", "logo.png", "ANCS_Logo.png"):
            lp = os.path.join(gui_dir, name)
            if os.path.exists(lp):
                self._logo_pixmap = QPixmap(lp)
                break

        self.setStyleSheet(GLASS_STYLE)

        # State
        self.device_types = {"router": RouterModel, "switch": SwitchModel, "core switch": CoreSwitchModel}
        self.devices: list[tuple[str, DeviceModel, dict]] = []
        self.current_device: Optional[tuple[str, DeviceModel, dict]] = None
        self.selected_device_name = None
        self.selected_template_name = None
        self.gns3: Optional[GNS3Connector] = None
        self.last_gns3_project = None
        self._last_gns3_url = self._load_gns3_url()
        self._send_in_progress = False
        self.right_sidebar_visible = True
        self._main_thread_call.connect(self._execute_main_thread_call)

        self._build_ui()

        if _db_error:
            QTimer.singleShot(200, lambda: QMessageBox.warning(
                self, "Database Error",
                f"Could not open the database:\n{_db_error}\n\n"
                "The app will run in read-only mode."))

        # Auto-connect after 2s (uses saved URL from last Import)
        QTimer.singleShot(2000, lambda: threading.Thread(target=self._auto_connect_gns3, daemon=True).start())

    def _config_path(self) -> str:
        """Path to config file (from config module; exe dir when frozen)."""
        return CONFIG_FILE

    def _load_gns3_url(self) -> str:
        """Load last used GNS3 URL from config file."""
        try:
            cfg_path = self._config_path()
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("gns3_url", GNS3_DEFAULT_URL)
        except Exception:
            pass
        return GNS3_DEFAULT_URL

    def _save_gns3_url(self, url: str):
        """Save GNS3 URL for next auto-connect."""
        try:
            cfg_path = self._config_path()
            data = {}
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["gns3_url"] = url
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _select_from_list(self, title: str, prompt: str, items: list[str]) -> tuple[int, bool]:
        """Show scrollable list dialog; returns (selected_index, ok)."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(prompt))
        lst = QListWidget()
        lst.addItems(items)
        lst.setMinimumHeight(min(300, 50 + len(items) * 24))
        lst.setCurrentRow(0)
        layout.addWidget(lst)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return lst.currentRow(), True
        return -1, False

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self._refresh_button_styles)

    def _refresh_button_styles(self):
        """Ensure buttons with setProperty get correct styling after layout."""
        for w in self.findChildren(QPushButton):
            try:
                w.style().unpolish(w)
                w.style().polish(w)
            except Exception:
                pass

    # ── bg.png painting ─────────────────────────────────────────────────

    def paintEvent(self, event):
        if not self._bg_pixmap.isNull():
            painter = QPainter(self)
            scaled = self._bg_pixmap.scaled(
                self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(0, 0, scaled)
            painter.end()

    # ── UI construction ─────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setAttribute(Qt.WA_TranslucentBackground)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── TOP BAR ─────────────────────────────────────────────────────
        top = QFrame()
        top.setProperty("topBar", True)
        top.setFixedHeight(70)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(8, 8, 8, 8)

        # Logo
        logo_frame = QHBoxLayout()
        logo_frame.setSpacing(8)
        if not self._logo_pixmap.isNull():
            logo_lbl = QLabel()
            logo_lbl.setPixmap(self._logo_pixmap.scaled(
                50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            logo_frame.addWidget(logo_lbl)
        else:
            badge = QLabel("AI")
            badge.setFixedSize(40, 40)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                "background-color: #1A3A6B; color: white; border-radius: 20px; "
                "font-weight: bold; font-size: 14px;")
            logo_frame.addWidget(badge)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        lbl_title = QLabel("ANCS")
        lbl_title.setStyleSheet("color: #4A9EFF; font-size: 20px; font-weight: bold;")
        title_col.addWidget(lbl_title)
        lbl_sub = QLabel("Auto Network Configuration System")
        lbl_sub.setStyleSheet("color: #8B9AB0; font-size: 9px;")
        title_col.addWidget(lbl_sub)
        logo_frame.addLayout(title_col)
        top_layout.addLayout(logo_frame)

        top_layout.addStretch()

        # Nav tabs
        self.btn_main_nav = QPushButton("Main")
        self.btn_main_nav.setProperty("navTab", "active")
        self.btn_main_nav.clicked.connect(lambda: self._switch_tab("main"))

        self.btn_logs_nav = QPushButton("Logs")
        self.btn_logs_nav.setProperty("navTab", "inactive")
        self.btn_logs_nav.clicked.connect(lambda: self._switch_tab("logs"))

        top_layout.addWidget(self.btn_main_nav)
        top_layout.addWidget(self.btn_logs_nav)
        top_layout.addStretch()

        root_layout.addWidget(top)

        # ── BODY (stacked: main view vs logs view) ──────────────────────
        self._stack = QStackedWidget()
        self._stack.setAttribute(Qt.WA_TranslucentBackground)
        root_layout.addWidget(self._stack, 1)

        # --- Main page ---
        main_page = QWidget()
        main_page.setAttribute(Qt.WA_TranslucentBackground)
        main_layout = QHBoxLayout(main_page)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(28)

        # LEFT PANEL (~1/5 width, fixed)
        left_panel = QFrame()
        left_panel.setProperty("glassPanel", True)
        left_panel.setFixedWidth(320)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(8)

        lbl_devices = QLabel("Devices")
        lbl_devices.setStyleSheet("color: #F0F2F4; font-size: 18px; font-weight: bold;")
        left_layout.addWidget(lbl_devices)

        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(120)
        self.device_list.currentRowChanged.connect(self._on_device_row_changed)
        left_layout.addWidget(self.device_list)

        dev_btns = QHBoxLayout()
        btn_add = QPushButton("+ Add")
        btn_add.clicked.connect(self.add_device_prompt)
        btn_remove = QPushButton("Remove")
        btn_remove.clicked.connect(self.remove_selected_device)
        dev_btns.addWidget(btn_add)
        dev_btns.addWidget(btn_remove)
        left_layout.addLayout(dev_btns)

        lbl_templates = QLabel("Templates")
        lbl_templates.setStyleSheet("color: #F0F2F4; font-size: 18px; font-weight: bold;")
        left_layout.addWidget(lbl_templates)

        self.template_list = QListWidget()
        self.template_list.currentRowChanged.connect(self._on_template_row_changed)
        left_layout.addWidget(self.template_list)

        tpl_btns = QHBoxLayout()
        btn_tpl_add = QPushButton("+ Add")
        btn_tpl_add.clicked.connect(self.add_template_dialog)
        btn_tpl_edit = QPushButton("Edit")
        btn_tpl_edit.clicked.connect(self.edit_template_dialog)
        tpl_btns.addWidget(btn_tpl_add)
        tpl_btns.addWidget(btn_tpl_edit)
        left_layout.addLayout(tpl_btns)

        # Action buttons
        btn_guided = QPushButton("Guided Setup")
        btn_guided.setProperty("teal", True)
        btn_guided.clicked.connect(self.guided_setup)
        left_layout.addWidget(btn_guided)

        btn_deploy = QPushButton("Deploy All (Ordered)")
        btn_deploy.setProperty("accent", True)
        btn_deploy.setProperty("pill", True)
        btn_deploy.clicked.connect(self.deploy_all_ordered)
        left_layout.addWidget(btn_deploy)

        btn_monitor = QPushButton("Monitor Devices")
        btn_monitor.setProperty("outlined", True)
        btn_monitor.clicked.connect(self.open_monitor)
        left_layout.addWidget(btn_monitor)

        btn_topo = QPushButton("Topology")
        btn_topo.clicked.connect(self.open_topology)
        left_layout.addWidget(btn_topo)

        btn_subnet = QPushButton("Subnet Calculator")
        btn_subnet.clicked.connect(lambda: self._open_subnet_calculator())
        left_layout.addWidget(btn_subnet)

        btn_history = QPushButton("Send History")
        btn_history.clicked.connect(self.open_audit_log)
        left_layout.addWidget(btn_history)

        self.btn_rollback = QPushButton("Rollback Config")
        self.btn_rollback.setProperty("danger", True)
        self.btn_rollback.clicked.connect(self.rollback_device)
        self.btn_rollback.setVisible(False)
        left_layout.addWidget(self.btn_rollback)

        left_layout.addStretch()

        # CENTER PANEL
        center_panel = QFrame()
        center_panel.setProperty("glassPanel", True)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(12)

        center_top = QHBoxLayout()
        lbl_preview = QLabel("Preview")
        lbl_preview.setStyleSheet("color: #C9D1D9; font-size: 24px; font-weight: bold;")
        center_top.addWidget(lbl_preview)
        center_top.addStretch()

        btn_export = QPushButton("Export Project")
        btn_export.setProperty("outlined", True)
        btn_export.clicked.connect(self.export_project)
        center_top.addWidget(btn_export)

        btn_import = QPushButton("Import Project")
        btn_import.setProperty("outlined", True)
        btn_import.clicked.connect(self.import_project)
        center_top.addWidget(btn_import)
        center_layout.addLayout(center_top)

        self.preview = QPlainTextEdit()
        self.preview.setPlaceholderText("Configuration preview will appear here...")
        center_layout.addWidget(self.preview, 1)

        center_bottom = QHBoxLayout()
        btn_generate = QPushButton("Generate")
        btn_generate.setProperty("accent", True)
        btn_generate.setProperty("pill", True)
        btn_generate.setFixedHeight(42)
        btn_generate.clicked.connect(self.generate_full)
        center_bottom.addWidget(btn_generate)
        center_bottom.addStretch()
        btn_clear = QPushButton("Clear Preview")
        btn_clear.setProperty("danger", True)
        btn_clear.setFixedHeight(42)
        btn_clear.clicked.connect(self.clear_preview)
        center_bottom.addWidget(btn_clear)
        center_layout.addLayout(center_bottom)

        # RIGHT PANEL (~1/5 width, fixed)
        self.right_panel = QFrame()
        self.right_panel.setProperty("glassPanel", True)
        self.right_panel.setMinimumWidth(300)
        right_scroll = QScrollArea()
        right_scroll.setWidget(self.right_panel)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setStyleSheet("background: transparent;")
        right_scroll.setFixedWidth(320)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(8)

        # GNS3 section
        lbl_gns3 = QLabel("GNS3 Project")
        lbl_gns3.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")
        right_layout.addWidget(lbl_gns3)

        gns3_row = QHBoxLayout()
        self.lbl_gns3_project_name = QLabel("No project")
        self.lbl_gns3_project_name.setStyleSheet("color: #8B949E; font-size: 13px;")
        gns3_row.addWidget(self.lbl_gns3_project_name, 1)
        self.lbl_gns3_status = QLabel("Click Import")
        self.lbl_gns3_status.setStyleSheet(
            "color: #9BA3AF; background-color: rgba(12,26,46,200); "
            "border-radius: 6px; padding: 4px 10px; font-size: 12px;")
        gns3_row.addWidget(self.lbl_gns3_status)
        right_layout.addLayout(gns3_row)

        gns3_btns = QHBoxLayout()
        btn_gns3_import = QPushButton("Import")
        btn_gns3_import.setProperty("accent", True)
        btn_gns3_import.clicked.connect(self.gns3_list_projects)
        btn_gns3_refresh = QPushButton("Refresh")
        btn_gns3_refresh.clicked.connect(self.refresh_gns3_connection)
        gns3_btns.addWidget(btn_gns3_import)
        gns3_btns.addWidget(btn_gns3_refresh)
        right_layout.addLayout(gns3_btns)

        # Send / Connect section
        lbl_send = QLabel("Send / Connect")
        lbl_send.setStyleSheet("color: #F0F2F4; font-size: 18px; font-weight: bold;")
        right_layout.addWidget(lbl_send)

        self.send_method = QComboBox()
        self.send_method.addItems(["Telnet", "Serial", "SSH"])
        self.send_method.currentTextChanged.connect(self._on_protocol_changed)
        right_layout.addWidget(self.send_method)

        # Serial fields
        self.lbl_serial_title = QLabel("Serial")
        self.lbl_serial_title.setStyleSheet("color: #C9D1D9; font-size: 15px; font-weight: bold;")
        right_layout.addWidget(self.lbl_serial_title)
        self.ent_serial_port = QLineEdit()
        self.ent_serial_port.setPlaceholderText("COM3 or /dev/ttyUSB0")
        right_layout.addWidget(self.ent_serial_port)
        self.ent_serial_baud = QLineEdit()
        self.ent_serial_baud.setPlaceholderText("9600")
        right_layout.addWidget(self.ent_serial_baud)

        # Network fields
        self.lbl_network_title = QLabel("Network")
        self.lbl_network_title.setStyleSheet("color: #C9D1D9; font-size: 15px; font-weight: bold;")
        right_layout.addWidget(self.lbl_network_title)
        self.ent_host = QLineEdit()
        self.ent_host.setPlaceholderText("Host or IP")
        right_layout.addWidget(self.ent_host)
        self.ent_port = QLineEdit()
        self.ent_port.setPlaceholderText("Port")
        right_layout.addWidget(self.ent_port)
        self.ent_user = QLineEdit()
        self.ent_user.setPlaceholderText("Username")
        right_layout.addWidget(self.ent_user)
        self.ent_pass = QLineEdit()
        self.ent_pass.setPlaceholderText("Password")
        self.ent_pass.setEchoMode(QLineEdit.Password)
        right_layout.addWidget(self.ent_pass)

        lbl_optional = QLabel("Optional")
        lbl_optional.setStyleSheet("color: #9BA3AF; font-size: 12px;")
        right_layout.addWidget(lbl_optional)
        enable_row = QHBoxLayout()
        self.ent_enable = QLineEdit()
        self.ent_enable.setPlaceholderText("Enable Password")
        self.enable_checkbox = QCheckBox()
        enable_row.addWidget(self.ent_enable, 1)
        enable_row.addWidget(self.enable_checkbox)
        right_layout.addLayout(enable_row)

        self.btn_send = QPushButton("Send")
        self.btn_send.setProperty("accent", True)
        self.btn_send.setProperty("pill", True)
        self.btn_send.setFixedHeight(40)
        self.btn_send.clicked.connect(self.send_now)
        right_layout.addWidget(self.btn_send)

        btn_save_creds = QPushButton("Save Credentials")
        btn_save_creds.setProperty("outlined", True)
        btn_save_creds.clicked.connect(self.save_credentials)
        right_layout.addWidget(btn_save_creds)

        btn_terminal = QPushButton("Open Terminal")
        btn_terminal.setProperty("outlined", True)
        btn_terminal.clicked.connect(self.open_terminal)
        right_layout.addWidget(btn_terminal)

        right_layout.addStretch()

        self.serial_widgets = [self.lbl_serial_title, self.ent_serial_port, self.ent_serial_baud]
        self.network_widgets = [self.lbl_network_title, self.ent_host, self.ent_port,
                                self.ent_user, self.ent_pass, self.ent_enable, self.enable_checkbox]
        self._on_protocol_changed("Telnet")

        # Layout: left | gap | center (preview) | gap | right — gaps between panels, center widest
        main_layout.addWidget(left_panel)
        main_layout.addSpacing(28)
        main_layout.addWidget(center_panel, 1)
        main_layout.addSpacing(28)
        main_layout.addWidget(right_scroll)

        self._stack.addWidget(main_page)

        # --- Logs page ---
        logs_page = QWidget()
        logs_page.setAttribute(Qt.WA_TranslucentBackground)
        logs_layout = QVBoxLayout(logs_page)
        logs_layout.setContentsMargins(16, 16, 16, 16)

        logs_panel = QFrame()
        logs_panel.setProperty("glassPanel", True)
        logs_inner = QVBoxLayout(logs_panel)
        logs_inner.setContentsMargins(24, 24, 24, 24)
        logs_inner.setSpacing(12)

        logs_top = QHBoxLayout()
        lbl_logs_title = QLabel("Logs")
        lbl_logs_title.setStyleSheet("color: #C9D1D9; font-size: 24px; font-weight: bold;")
        logs_top.addWidget(lbl_logs_title)

        self.logs_device_var = QComboBox()
        self.logs_device_var.addItem("All")
        self.logs_device_var.setFixedWidth(200)
        self.logs_device_var.currentTextChanged.connect(lambda: self._refresh_logs_history())
        logs_top.addWidget(self.logs_device_var)

        btn_refresh_logs = QPushButton("Refresh")
        btn_refresh_logs.setProperty("outlined", True)
        btn_refresh_logs.clicked.connect(self._refresh_logs_history)
        logs_top.addWidget(btn_refresh_logs)
        logs_top.addStretch()
        logs_inner.addLayout(logs_top)

        lbl_hist = QLabel("History (by device)")
        lbl_hist.setStyleSheet("color: #9ca3af; font-size: 14px; font-weight: bold;")
        logs_inner.addWidget(lbl_hist)

        self.logs_history_table = QTableWidget(0, 4)
        self.logs_history_table.setHorizontalHeaderLabels(["ID", "Device", "Action", "Time"])
        self.logs_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.logs_history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.logs_history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        logs_inner.addWidget(self.logs_history_table)

        lbl_live = QLabel("Live output")
        lbl_live.setStyleSheet("color: #9ca3af; font-size: 14px; font-weight: bold;")
        logs_inner.addWidget(lbl_live)

        self.txt_logs = QPlainTextEdit()
        self.txt_logs.setReadOnly(True)
        logs_inner.addWidget(self.txt_logs, 1)

        btn_clear_logs = QPushButton("Clear output")
        btn_clear_logs.setProperty("outlined", True)
        btn_clear_logs.clicked.connect(lambda: self.txt_logs.clear())
        logs_inner.addWidget(btn_clear_logs, alignment=Qt.AlignRight)

        logs_layout.addWidget(logs_panel)
        self._stack.addWidget(logs_page)

        # Menu bar
        menubar = self.menuBar()
        gns3_menu = menubar.addMenu("GNS3")
        act_import = gns3_menu.addAction("Import from GNS3")
        act_import.triggered.connect(self.gns3_list_projects)

        # DB tree stubs (kept for compatibility — database tab hidden)
        self.tree_devices = None
        self.tree_configs = None
        self.tree_users = None
        self.tree_tasks = None
        self.tree_logs = None
        self.tree_ai_models = None
        self.tree_training = None
        self.db_tabview = None

    # ── Tab switching ───────────────────────────────────────────────────

    def _switch_tab(self, tab: str):
        if tab == "main":
            self._stack.setCurrentIndex(0)
            self.btn_main_nav.setProperty("navTab", "active")
            self.btn_logs_nav.setProperty("navTab", "inactive")
        else:
            self._stack.setCurrentIndex(1)
            self.btn_main_nav.setProperty("navTab", "inactive")
            self.btn_logs_nav.setProperty("navTab", "active")
            self._refresh_logs_history()
            
        self.btn_main_nav.style().unpolish(self.btn_main_nav)
        self.btn_main_nav.style().polish(self.btn_main_nav)
        self.btn_logs_nav.style().unpolish(self.btn_logs_nav)
        self.btn_logs_nav.style().polish(self.btn_logs_nav)

    # ── Thread-safe UI helpers (replaces self.after) ────────────────────

    def _execute_main_thread_call(self, fn):
        try:
            fn()
        except Exception:
            pass

    def _run_on_main(self, fn):
        app = QApplication.instance()
        if app is not None and QThread.currentThread() == app.thread():
            self._execute_main_thread_call(fn)
            return
        self._main_thread_call.emit(fn)

    # ── Device list ─────────────────────────────────────────────────────

    def add_device_instance(self, type_key, name, metadata=None):
        cls = self.device_types.get(type_key)
        if not cls:
            return
        obj = cls(name)
        if metadata is None:
            metadata = {}
        self.devices.append((name, obj, metadata))

    def refresh_device_list(self):
        self.device_list.blockSignals(True)
        self.device_list.clear()
        self.selected_device_name = None
        for idx, (n, obj, meta) in enumerate(self.devices):
            icon = ""
            if isinstance(obj, RouterModel):
                icon = "\U0001F4E1 "
            elif isinstance(obj, CoreSwitchModel):
                icon = "\U0001F500 "
            elif isinstance(obj, SwitchModel):
                icon = "\U0001F500 "
            else:
                icon = "\U0001F6E1 "
            label = f"{icon}{n} ({obj.__class__.__name__})"
            if meta.get("gns3_node"):
                label += " [gns3]"
            self.device_list.addItem(label)
        self.device_list.blockSignals(False)
        if self.device_list.count() > 0:
            self.device_list.setCurrentRow(0)

    def add_device_prompt(self):
        dtype, ok = QInputDialog.getText(self, "Add Device",
                                          "Device type: router / switch / core switch")
        if not ok or not dtype:
            return
        dtype = dtype.strip().lower()
        if dtype not in self.device_types:
            QMessageBox.critical(self, "Error", "Unknown device type")
            return
        name, ok = QInputDialog.getText(self, "Name", "Device name (e.g. router2)")
        if not ok or not name:
            return
        self.add_device_instance(dtype, name.strip())
        self.refresh_device_list()

    def remove_selected_device(self):
        if not self.selected_device_name:
            QMessageBox.information(self, "Info", "Select a device first")
            return
        idx = None
        for i, (n, _, _) in enumerate(self.devices):
            if n == self.selected_device_name:
                idx = i
                break
        if idx is None:
            return
        name = self.devices[idx][0]
        ret = QMessageBox.question(self, "Confirm", f"Remove {name}?")
        if ret == QMessageBox.Yes:
            del self.devices[idx]
            self.refresh_device_list()

    def _on_device_row_changed(self, row):
        if row < 0 or row >= len(self.devices):
            return
        dname, model, meta = self.devices[row]
        self.selected_device_name = dname
        self.current_device = (dname, model, meta)
        self._refresh_template_list()
        if meta.get("gns3_node"):
            host = meta.get("console_host", "localhost")
            port = str(meta.get("console_port", ""))
            self.ent_host.setText(host)
            self.ent_port.setText(port)
            self.send_method.setCurrentText("Telnet")
            self._on_protocol_changed("Telnet")
        self._load_credentials(dname)
        self.preview.setPlainText(f"! device: {dname}\n")
        if model.has_snapshots():
            self.btn_rollback.setVisible(True)
        else:
            self.btn_rollback.setVisible(False)

    # ── Template list ───────────────────────────────────────────────────

    def _refresh_template_list(self):
        self.template_list.blockSignals(True)
        self.template_list.clear()
        self.selected_template_name = None
        if self.current_device:
            for tname in self.current_device[1].get_template_names():
                self.template_list.addItem(tname)
        self.template_list.blockSignals(False)

    def _on_template_row_changed(self, row):
        if row < 0 or not self.current_device:
            return
        tnames = self.current_device[1].get_template_names()
        if row >= len(tnames):
            return
        name = tnames[row]
        self.selected_template_name = name
        txt = self.current_device[1].get_template(name).replace(
            "{name}", self.current_device[0])
        self.preview.setPlainText(txt)

    def add_template_dialog(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first")
            return
        name, ok = QInputDialog.getText(self, "Template Name", "Template name:")
        if not ok or not name:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, f"New Template: {name}", "Template content:", "")
        if ok and text is not None:
            self.current_device[1].set_template(name, text)
            self._refresh_template_list()

    def edit_template_dialog(self):
        if not self.selected_template_name:
            QMessageBox.information(self, "Info", "Select a template first")
            return
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first")
            return
        tname = self.selected_template_name
        current = self.current_device[1].get_template(tname)
        text, ok = QInputDialog.getMultiLineText(
            self, f"Edit Template: {tname}", "Template content:", current)
        if ok and text is not None:
            self.current_device[1].set_template(tname, text)
            self._refresh_template_list()

    def on_device_select(self):
        row = self.device_list.currentRow()
        if row >= 0:
            self._on_device_row_changed(row)

    def on_template_select(self):
        row = self.template_list.currentRow()
        if row >= 0:
            self._on_template_row_changed(row)

    # ── Protocol field toggling ─────────────────────────────────────────

    def _on_protocol_changed(self, value):
        protocol = value.lower()
        if protocol == "telnet":
            self.ent_host.setEnabled(True)
            self.ent_port.setEnabled(True)
            self.ent_user.setEnabled(False)
            self.ent_pass.setEnabled(False)
            self.ent_enable.setEnabled(False)
            self.enable_checkbox.setEnabled(False)
            for w in self.serial_widgets:
                w.setEnabled(False)
            self.lbl_network_title.setStyleSheet("color: #C9D1D9; font-size: 15px; font-weight: bold;")
            self.lbl_serial_title.setStyleSheet("color: #4b5563; font-size: 15px; font-weight: bold;")
        elif protocol == "serial":
            for w in self.serial_widgets:
                w.setEnabled(True)
            self.ent_host.setEnabled(False)
            self.ent_port.setEnabled(False)
            self.ent_user.setEnabled(False)
            self.ent_pass.setEnabled(False)
            self.ent_enable.setEnabled(False)
            self.enable_checkbox.setEnabled(False)
            self.lbl_serial_title.setStyleSheet("color: #C9D1D9; font-size: 15px; font-weight: bold;")
            self.lbl_network_title.setStyleSheet("color: #4b5563; font-size: 15px; font-weight: bold;")
        elif protocol == "ssh":
            self.ent_host.setEnabled(True)
            self.ent_port.setEnabled(True)
            self.ent_user.setEnabled(True)
            self.ent_pass.setEnabled(True)
            self.ent_enable.setEnabled(True)
            self.enable_checkbox.setEnabled(True)
            for w in self.serial_widgets:
                w.setEnabled(False)
            self.lbl_network_title.setStyleSheet("color: #C9D1D9; font-size: 15px; font-weight: bold;")
            self.lbl_serial_title.setStyleSheet("color: #4b5563; font-size: 15px; font-weight: bold;")

    # ── Generate / Preview ──────────────────────────────────────────────

    def generate_selected(self):
        if not self.selected_template_name:
            QMessageBox.information(self, "Info", "Select a template first")
            return
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first")
            return
        txt = self.current_device[1].get_template(self.selected_template_name).replace(
            "{name}", self.current_device[0])
        self.preview.setPlainText(txt)

    def generate_full(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first")
            return
        txt = self.current_device[1].build_full_config().replace(
            "{name}", self.current_device[0])
        self.preview.setPlainText(txt)

    def clear_preview(self):
        self._run_on_main(lambda: self.preview.setPlainText(""))

    # ── Logging ─────────────────────────────────────────────────────────

    def log(self, msg):
        def _do():
            ts = time.strftime("%H:%M:%S")
            self.txt_logs.appendPlainText(f"[{ts}] {msg}")
        self._run_on_main(_do)

    def _refresh_logs_history(self):
        try:
            device_filter = self.logs_device_var.currentText()
            if device_filter == "All":
                cur.execute(
                    "SELECT id, device_name, action, timestamp FROM logs ORDER BY id DESC LIMIT 200")
            else:
                cur.execute(
                    "SELECT id, device_name, action, timestamp FROM logs "
                    "WHERE device_name=? ORDER BY id DESC LIMIT 200",
                    (device_filter,))
            rows = cur.fetchall()
            self.logs_history_table.setRowCount(0)
            for row in rows:
                r = self.logs_history_table.rowCount()
                self.logs_history_table.insertRow(r)
                for c, val in enumerate(row):
                    self.logs_history_table.setItem(r, c, QTableWidgetItem(str(val or "")))

            # Update device filter dropdown
            try:
                cur.execute("SELECT DISTINCT device_name FROM logs WHERE device_name IS NOT NULL")
                names = [r[0] for r in cur.fetchall() if r[0]]
                current = self.logs_device_var.currentText()
                self.logs_device_var.blockSignals(True)
                self.logs_device_var.clear()
                self.logs_device_var.addItem("All")
                for n in sorted(names):
                    self.logs_device_var.addItem(n)
                idx = self.logs_device_var.findText(current)
                if idx >= 0:
                    self.logs_device_var.setCurrentIndex(idx)
                self.logs_device_var.blockSignals(False)
            except Exception:
                pass
        except Exception:
            pass

    def _write_audit_log(self, device_name, action, details="", config_content=""):
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with db_lock:
                cur.execute(
                    "INSERT INTO logs (device_name, action, details, config_snapshot, timestamp) "
                    "VALUES (?,?,?,?,?)",
                    (device_name, action, details, config_content, ts))
                conn.commit()
            self._run_on_main(self._refresh_logs_history)
        except Exception:
            pass

    # ── Send / Deploy ───────────────────────────────────────────────────

    def _set_send_busy(self, busy: bool):
        self._send_in_progress = busy
        try:
            self.btn_send.setEnabled(not busy)
            self.btn_send.setText("Sending\u2026" if busy else "Send")
        except Exception:
            pass

    def send_now(self):
        content = self.preview.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "Info", "Nothing to send")
            return

        try:
            from .validators import ConfigValidator
            warnings = ConfigValidator.check_all(self.devices)
            if warnings:
                msg = "The following issues were detected:\n\n" + "\n".join(
                    f"\u2022 {w}" for w in warnings) + "\n\nSend anyway?"
                ret = QMessageBox.question(self, "Config Warnings", msg)
                if ret != QMessageBox.Yes:
                    return
        except Exception:
            pass

        method = self.send_method.currentText().lower()
        self._set_send_busy(True)

        if method == "serial":
            port = self.ent_serial_port.text().strip()
            try:
                baud = int(self.ent_serial_baud.text().strip() or "9600")
            except Exception:
                self._set_send_busy(False)
                QMessageBox.critical(self, "Error", "Invalid baud rate")
                return
            if not port:
                self._set_send_busy(False)
                QMessageBox.critical(self, "Error", "Enter serial port")
                return
            threading.Thread(target=self._thread_serial,
                             args=(port, baud, content), daemon=True).start()
        elif method == "telnet":
            host = self.ent_host.text().strip()
            if not host:
                self._set_send_busy(False)
                QMessageBox.critical(self, "Error", "Enter host")
                return
            try:
                port = int(self.ent_port.text().strip() or "23")
            except Exception:
                self._set_send_busy(False)
                QMessageBox.critical(self, "Error", "Invalid port")
                return
            user = self.ent_user.text().strip()
            pw = self.ent_pass.text().strip()
            enable = self.ent_enable.text().strip() if self.enable_checkbox.isChecked() else ""
            threading.Thread(target=self._thread_telnet,
                             args=(host, port, user, pw, enable, content), daemon=True).start()
        elif method == "ssh":
            host = self.ent_host.text().strip()
            if not host:
                self._set_send_busy(False)
                QMessageBox.critical(self, "Error", "Enter host")
                return
            try:
                port = int(self.ent_port.text().strip() or "22")
            except Exception:
                self._set_send_busy(False)
                QMessageBox.critical(self, "Error", "Invalid port")
                return
            user = self.ent_user.text().strip()
            pw = self.ent_pass.text().strip()
            enable = self.ent_enable.text().strip() if self.enable_checkbox.isChecked() else ""
            threading.Thread(target=self._thread_ssh,
                             args=(host, port, user, pw, enable, content), daemon=True).start()
        else:
            self._set_send_busy(False)
            QMessageBox.critical(self, "Error", "Unknown send method")

    def _thread_serial(self, port, baud, content):
        self.log(f"starting serial to {port}@{baud}")
        try:
            ok = Sender.send_serial(self.log, port, baud, content)
            self.log(f"serial finished: {ok}")
            if ok:
                self.clear_preview()
                device_name = self.current_device[0] if self.current_device else "unknown"
                self._write_audit_log(device_name, "serial", f"port={port} baud={baud}", config_content=content)
        finally:
            self._run_on_main(lambda: self._set_send_busy(False))

    def _thread_telnet(self, host, port, user, pw, enable, content):
        self.log(f"starting telnet to {host}:{port}")
        try:
            ok = Sender.send_telnet(self.log, host, port, user, pw, enable, content)
            self.log(f"telnet finished: {ok}")
            if ok:
                self.clear_preview()
                device_name = self.current_device[0] if self.current_device else "unknown"
                self._write_audit_log(device_name, "telnet", f"host={host} port={port}", config_content=content)
                cmds = ["show ip interface brief"]
                try:
                    if self.current_device:
                        _, mdl, _ = self.current_device
                        if isinstance(mdl, (CoreSwitchModel, SwitchModel)):
                            cmds.append("show vlan-switch")
                except Exception:
                    pass
                self.log("[verify] running post-send verification...")
                results = Sender.verify_telnet(self.log, host, port, cmds,
                                               username=user, password=pw, enable_pw=enable)
                if results:
                    self._run_on_main(lambda r=results: self._show_verify_dialog(r))
        finally:
            self._run_on_main(lambda: self._set_send_busy(False))

    def _thread_ssh(self, host, port, user, pw, enable, content):
        self.log(f"starting ssh to {host}:{port} as {user}")
        try:
            ok = Sender.send_ssh(self.log, host, port, user, pw, enable, content)
            self.log(f"ssh finished: {ok}")
            if ok:
                self.clear_preview()
                device_name = self.current_device[0] if self.current_device else "unknown"
                self._write_audit_log(device_name, "ssh", f"host={host} port={port} user={user}", config_content=content)
        finally:
            self._run_on_main(lambda: self._set_send_busy(False))

    def _dialog_style(self) -> str:
        return """
            QDialog { background-color: #0D1117; color: #C9D1D9; }
            QLabel { color: #C9D1D9; }
            QPlainTextEdit {
                background-color: #161B22;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 8px;
                padding: 8px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
            }
            QTableWidget {
                background-color: #161B22;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 8px;
                gridline-color: #30363D;
                alternate-background-color: #1F2630;
            }
            QHeaderView::section {
                background-color: #1F2630;
                color: #8B949E;
                border: none;
                padding: 6px;
                font-weight: 600;
            }
            QPushButton {
                background-color: #374151;
                color: #C9D1D9;
                border: none;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #4B5563; color: #FFFFFF; }
            QPushButton:disabled { background-color: #2B3340; color: #6B7280; }
        """

    def _style_table_widget(self, table: QTableWidget):
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _show_verify_dialog(self, results: dict):
        dlg = QDialog(self)
        dlg.setWindowTitle("Post-Send Verification")
        dlg.resize(860, 560)
        dlg.setStyleSheet(self._dialog_style())
        layout = QVBoxLayout(dlg)
        title = QLabel("Post-Send Verification")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #E6EDF3;")
        layout.addWidget(title)
        for cmd, output in results.items():
            lbl = QLabel(f"Command: {cmd}")
            lbl.setStyleSheet("color: #58A6FF; font-weight: 700; padding-top: 6px;")
            layout.addWidget(lbl)
            txt = QPlainTextEdit()
            txt.setPlainText(output)
            txt.setReadOnly(True)
            txt.setMinimumHeight(170)
            layout.addWidget(txt)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)
        dlg.exec()

    # ── Credentials ─────────────────────────────────────────────────────

    def save_credentials(self):
        if not self.selected_device_name:
            QMessageBox.information(self, "Save Credentials", "Select a device first.")
            return
        try:
            host = self.ent_host.text().strip()
            port = self.ent_port.text().strip()
            username = self.ent_user.text().strip()
            password = _obfuscate(self.ent_pass.text().strip())
            enable = _obfuscate(self.ent_enable.text().strip())
            protocol = self.send_method.currentText().lower()
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with db_lock:
                cur.execute(
                    """INSERT INTO credentials
                       (device_name, host, port, username, password, enable_password, protocol, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(device_name) DO UPDATE SET
                       host=excluded.host, port=excluded.port,
                       username=excluded.username, password=excluded.password,
                       enable_password=excluded.enable_password,
                       protocol=excluded.protocol, updated_at=excluded.updated_at""",
                    (self.selected_device_name, host, port, username, password, enable, protocol, ts))
                conn.commit()
            QMessageBox.information(self, "Credentials Saved",
                                    f"Credentials for '{self.selected_device_name}' saved.")
            self.log(f"[creds] saved credentials for {self.selected_device_name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save credentials:\n{e}")

    def _load_credentials(self, device_name: str):
        try:
            cur.execute(
                "SELECT host, port, username, password, enable_password, protocol "
                "FROM credentials WHERE device_name=?", (device_name,))
            row = cur.fetchone()
            if not row:
                return
            host, port, username, password, enable, protocol = row
            if host:
                self.ent_host.setEnabled(True)
                self.ent_host.setText(host)
            if port:
                self.ent_port.setEnabled(True)
                self.ent_port.setText(str(port))
            if username:
                self.ent_user.setEnabled(True)
                self.ent_user.setText(username)
            if password:
                self.ent_pass.setEnabled(True)
                self.ent_pass.setText(_deobfuscate(password))
            if enable:
                self.ent_enable.setEnabled(True)
                self.ent_enable.setText(_deobfuscate(enable))
            if protocol and protocol in ("telnet", "serial", "ssh"):
                display = protocol.capitalize() if protocol != "ssh" else "SSH"
                self.send_method.setCurrentText(display)
                self._on_protocol_changed(display)
            else:
                self._on_protocol_changed(self.send_method.currentText())
        except Exception:
            pass

    # ── Export / Import ─────────────────────────────────────────────────

    def export_project(self):
        if not self.devices:
            QMessageBox.information(self, "Export", "No devices to export.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export ANCS Project", "", "ANCS Project (*.ancs);;JSON (*.json);;All files (*.*)")
        if not filepath:
            return
        try:
            export_data = {"version": "1.0", "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"), "devices": []}
            type_map = {"RouterModel": "router", "SwitchModel": "switch", "CoreSwitchModel": "core switch"}
            for name, model, meta in self.devices:
                type_key = type_map.get(model.__class__.__name__, "router")
                safe_meta = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, list, type(None)))}
                export_data["devices"].append({"name": name, "type_key": type_key, "metadata": safe_meta, "templates": dict(model.templates)})
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            QMessageBox.information(self, "Export Complete", f"Exported {len(self.devices)} device(s) to:\n{filepath}")
            self.log(f"[export] saved project to {filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def import_project(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Import ANCS Project", "", "ANCS Project (*.ancs);;JSON (*.json);;All files (*.*)")
        if not filepath:
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Could not read file:\n{e}")
            return
        devices_data = data.get("devices", [])
        if not devices_data:
            QMessageBox.information(self, "Import", "No devices found in file.")
            return
        if self.devices:
            ret = QMessageBox.question(
                self, "Import Project",
                f"This will add {len(devices_data)} device(s) to the current workspace.\n"
                "Devices with duplicate names will be skipped.\n\nContinue?")
            if ret != QMessageBox.Yes:
                return
        added = 0
        skipped = 0
        for dev in devices_data:
            name = dev.get("name", "unnamed")
            type_key = dev.get("type_key", "router").lower()
            meta = dev.get("metadata", {})
            templates = dev.get("templates", {})
            if type_key not in self.device_types:
                type_key = "router"
            if any(d[0] == name for d in self.devices):
                skipped += 1
                continue
            self.add_device_instance(type_key, name, metadata=meta)
            _, model, _ = self.devices[-1]
            for tname, ttext in templates.items():
                model.set_template(tname, ttext)
            added += 1
        self.refresh_device_list()
        QMessageBox.information(
            self, "Import Complete",
            f"Imported {added} device(s)." + (f"\nSkipped {skipped} duplicate(s)." if skipped else ""))
        self.log(f"[import] loaded {added} device(s) from {filepath}")

    # ── Cross-device context extraction ─────────────────────────────────

    def _build_project_context(self, exclude_name: str) -> dict:
        ctx = {
            "vlans": [], "routing_entries": [], "dhcp_pools": [], "acl_rules": [],
            "static_routes": [], "isp_gateway": "", "rip_enabled": False,
            "domain": "", "enable_pw": "", "ip_scheme": "192.168",
            "vlan_source": "", "routing_source": "", "dhcp_source_device": "",
            "routing_device": "", "routing_device_type": "",
        }
        for dname, model, _meta in self.devices:
            if dname == exclude_name:
                continue
            tmpls = model.templates
            if not ctx["vlans"] and "guided_vlans" in tmpls:
                text = tmpls["guided_vlans"]
                for m in re.finditer(r"vlan\s+(\d+)\s*\nname\s+(\S+)", text, re.IGNORECASE):
                    ctx["vlans"].append({"id": m.group(1), "name": m.group(2)})
                if ctx["vlans"]:
                    ctx["vlan_source"] = dname
            if not ctx["routing_entries"] and "guided_routing" in tmpls:
                text = tmpls["guided_routing"]
                for m in re.finditer(
                    r"(?:interface\s+\S*?(\d+)[.\s].*?\n.*?)?ip\s+address\s+([\d.]+)\s+([\d.]+)",
                    text, re.IGNORECASE | re.DOTALL):
                    ip, mask = m.group(2), m.group(3)
                    if ip and mask:
                        parts = ip.split(".")
                        vid = parts[2] if len(parts) == 4 else ""
                        ctx["routing_entries"].append({"vlan": vid, "name": f"VLAN{vid}", "ip": ip, "mask": mask})
                        if len(parts) >= 2:
                            ctx["ip_scheme"] = f"{parts[0]}.{parts[1]}"
                if ctx["routing_entries"]:
                    ctx["routing_source"] = dname
                    if "guided_vlans" in tmpls:
                        vtext = tmpls["guided_vlans"]
                        vlan_names = {}
                        for m in re.finditer(r"vlan\s+(\d+)\s*\nname\s+(\S+)", vtext, re.IGNORECASE):
                            vlan_names[m.group(1)] = m.group(2)
                        for entry in ctx["routing_entries"]:
                            if entry["vlan"] in vlan_names:
                                entry["name"] = vlan_names[entry["vlan"]]
            if not ctx["routing_device"] and "guided_routing" in tmpls and tmpls["guided_routing"].strip():
                if isinstance(model, RouterModel):
                    ctx["routing_device"] = dname
                    ctx["routing_device_type"] = "router"
                elif isinstance(model, CoreSwitchModel):
                    ctx["routing_device"] = dname
                    ctx["routing_device_type"] = "core"
            if not ctx["dhcp_pools"] and "guided_dhcp" in tmpls:
                text = tmpls["guided_dhcp"]
                pools = []
                for pool_block in re.split(r"ip dhcp pool\s+", text, flags=re.IGNORECASE):
                    if not pool_block.strip():
                        continue
                    pname = pool_block.split()[0] if pool_block.split() else ""
                    net_m = re.search(r"network\s+([\d.]+)\s+([\d.]+)", pool_block, re.IGNORECASE)
                    gw_m = re.search(r"default-router\s+([\d.]+)", pool_block, re.IGNORECASE)
                    dns_m = re.search(r"dns-server\s+([\d.]+)", pool_block, re.IGNORECASE)
                    if net_m:
                        pools.append({"pool": pname, "network": net_m.group(1), "mask": net_m.group(2),
                                       "gateway": gw_m.group(1) if gw_m else "", "dns": dns_m.group(1) if dns_m else "8.8.8.8"})
                if pools:
                    ctx["dhcp_pools"] = pools
                    ctx["dhcp_source_device"] = dname
            if not ctx["isp_gateway"] and "guided_static_routes" in tmpls:
                text = tmpls["guided_static_routes"]
                m = re.search(r"ip\s+route\s+0\.0\.0\.0\s+0\.0\.0\.0\s+([\d.]+)", text, re.IGNORECASE)
                if m:
                    ctx["isp_gateway"] = m.group(1)
                    ctx["static_routes"].append({"network": "0.0.0.0", "mask": "0.0.0.0", "next-hop": m.group(1), "description": "Default route to ISP"})
            if not ctx["rip_enabled"] and "guided_rip" in tmpls:
                if re.search(r"router\s+rip", tmpls["guided_rip"], re.IGNORECASE):
                    ctx["rip_enabled"] = True
            if "guided_identity" in tmpls:
                text = tmpls["guided_identity"]
                if not ctx["domain"]:
                    dm = re.search(r"ip\s+domain[-\s]name\s+(\S+)", text, re.IGNORECASE)
                    if dm:
                        ctx["domain"] = dm.group(1)
                if not ctx["enable_pw"]:
                    em = re.search(r"enable\s+secret\s+(\S+)", text, re.IGNORECASE)
                    if em:
                        ctx["enable_pw"] = em.group(1)
        return ctx

    # ── Guided Setup ────────────────────────────────────────────────────

    def guided_setup(self):
        if not self.devices:
            QMessageBox.information(self, "Info", "Add a device first")
            return
        choice = self._prompt_guided_device_choice()
        if not choice:
            return
        name, model, meta = choice
        if isinstance(model, RouterModel):
            device_role = "router"
        elif isinstance(model, CoreSwitchModel):
            device_role = "core"
        else:
            device_role = "access"
        if device_role == "access":
            ret = QMessageBox.question(
                self, "Layer 2 device",
                f"{name} is a Layer 2 switch. It cannot run routing or DHCP services.\n\n"
                "The guided wizard will only configure VLANs, uplinks, and limited ACLs here.\n\n"
                "Continue with this switch?")
            if ret != QMessageBox.Yes:
                return
        project_context = self._build_project_context(exclude_name=name)
        from .wizards import GuidedSetupWizard
        win = GuidedSetupWizard(self, name, model, device_role=device_role,
                                 known_interfaces=meta.get("interfaces", []),
                                 project_context=project_context)
        accepted = False
        if hasattr(win, "exec"):
            accepted = bool(win.exec())
        if not accepted:
            return
        self.on_device_select()
        try:
            self.generate_full()
        except Exception:
            pass
        QMessageBox.information(self, "Guided Setup Complete",
                                "Guided templates were saved for this device.")
        self._offer_apply_to_similar(name, model, device_role, win)

    def _offer_apply_to_similar(self, configured_name, configured_model, device_role, win):
        if device_role == "access":
            targets = [(n, m, mt) for n, m, mt in self.devices
                       if isinstance(m, SwitchModel) and n != configured_name
                       and not any(k.startswith("guided_") for k in m.templates)]
            apply_what = "VLANs + trunk uplink"
        elif device_role == "core":
            targets = [(n, m, mt) for n, m, mt in self.devices
                       if isinstance(m, (SwitchModel, CoreSwitchModel)) and n != configured_name
                       and not any(k.startswith("guided_") for k in m.templates)]
            apply_what = "VLANs"
        elif device_role == "router":
            targets = [(n, m, mt) for n, m, mt in self.devices
                       if isinstance(m, RouterModel) and n != configured_name
                       and not any(k.startswith("guided_") for k in m.templates)]
            apply_what = "domain name and admin password"
        else:
            return
        if not targets:
            return
        names_str = ", ".join(n for n, _, _ in targets[:5])
        if len(targets) > 5:
            names_str += f" and {len(targets) - 5} more"
        ret = QMessageBox.question(
            self, "Apply to similar devices",
            f"{len(targets)} other unconfigured device(s) found:\n  {names_str}\n\n"
            f"Apply the same {apply_what} to them now?")
        if ret != QMessageBox.Yes:
            return
        from .wizards import GuidedSetupWizard
        for tname, tmodel, tmeta in targets:
            role = ("router" if isinstance(tmodel, RouterModel)
                    else "core" if isinstance(tmodel, CoreSwitchModel) else "access")
            headless = GuidedSetupWizard(self, tname, tmodel, device_role=role,
                                          known_interfaces=tmeta.get("interfaces", []), headless=True)
            headless.vlans = list(win.vlans)
            headless.identity_data = {"hostname": tname,
                                       "domain": win.identity_data.get("domain", ""),
                                       "enable": win.identity_data.get("enable", "ChangeMe123!")}
            if device_role in ("access", "core"):
                ifaces = tmeta.get("interfaces", [])
                uplink_port = ifaces[-1] if ifaces else ("Ethernet3/3" if role == "access" else "FastEthernet1/0")
                headless.uplinks = [{"ports": uplink_port, "mode": "trunk",
                                      "allowed vlans": ",".join(v["id"] for v in win.vlans) or "all"}]
            headless._write_templates()
            headless.destroy()
        QMessageBox.information(self, "Done", f"Config applied to {len(targets)} device(s):\n  {names_str}")
        self.on_device_select()

    def _prompt_guided_device_choice(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Guided Setup \u2014 Select Device")
        dlg.setFixedSize(480, 420)
        dlg.setStyleSheet("background-color: #0D1117;")
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 18)

        lbl = QLabel("Which device do you want to configure?")
        lbl.setStyleSheet("color: #C9D1D9; font-size: 13px; font-weight: bold;")
        layout.addWidget(lbl)
        hint = QLabel("Recommended: start with the router or core switch.")
        hint.setStyleSheet("color: #8B949E; font-size: 9px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        listbox = QListWidget()
        for name, model, meta in self.devices:
            if isinstance(model, RouterModel):
                role = "Router / Gateway"
                icon = "\U0001F500"
            elif isinstance(model, CoreSwitchModel):
                role = "Core Switch (Layer 3)"
                icon = "\U0001F536"
            else:
                role = "Access Switch (Layer 2)"
                icon = "\U0001F537"
            listbox.addItem(f"  {icon}  {name}  \u2014  {role}")
        if listbox.count() > 0:
            listbox.setCurrentRow(0)
        layout.addWidget(listbox, 1)

        btns = QHBoxLayout()
        btn_ok = QPushButton("Configure Selected \u2192")
        btn_ok.setProperty("accent", True)
        btn_cancel = QPushButton("Cancel")
        btns.addWidget(btn_ok)
        btns.addStretch()
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

        choice = {"value": None}

        def confirm():
            row = listbox.currentRow()
            if row >= 0 and row < len(self.devices):
                choice["value"] = self.devices[row]
            dlg.accept()

        btn_ok.clicked.connect(confirm)
        btn_cancel.clicked.connect(dlg.reject)
        listbox.itemDoubleClicked.connect(lambda: confirm())
        dlg.exec()
        return choice["value"]

    # ── Topology / Rollback / Monitor / Terminal ────────────────────────

    def open_topology(self):
        project_id = getattr(self, "gns3_project_id", None)
        if not project_id:
            QMessageBox.information(self, "Topology",
                                    "No GNS3 project loaded.\nConnect to GNS3 and import devices first.")
            return
        try:
            connector = GNS3Connector()
            from .topology_viewer import TopologyViewer
            TopologyViewer(self, connector, project_id, self.devices)
        except Exception as exc:
            QMessageBox.critical(self, "Topology Error", str(exc))

    def rollback_device(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first.")
            return
        name, model, meta = self.current_device
        if not model.has_snapshots():
            QMessageBox.information(self, "Info", "No rollback snapshot available.")
            return
        ret = QMessageBox.question(self, "Rollback Config",
                                    f"Restore the previous configuration for '{name}'?")
        if ret != QMessageBox.Yes:
            return
        model.restore_snapshot()
        self._refresh_template_list()
        if not model.has_snapshots():
            self.btn_rollback.setVisible(False)
        QMessageBox.information(self, "Rollback Complete",
                                f"Previous configuration restored for '{name}'.")

    def open_monitor(self):
        try:
            from .monitor import DeviceMonitor
            DeviceMonitor(self, self.devices, self.gns3,
                          getattr(self, "gns3_project_id", None))
        except Exception as e:
            QMessageBox.critical(self, "Monitor Error", str(e))

    def open_terminal(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first.")
            return
        dname, model, meta = self.current_device
        host = meta.get("console_host") or self.ent_host.text().strip()
        port_raw = meta.get("console_port") or self.ent_port.text().strip()
        if not host:
            QMessageBox.information(self, "Info", "No host/IP available for this device.")
            return
        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            QMessageBox.critical(self, "Error", f"Invalid port: {port_raw}")
            return
        username = ""
        password = ""
        enable_pw = ""
        try:
            with db_lock:
                cur.execute("SELECT username, password, enable_password FROM credentials WHERE device_name=?", (dname,))
                row = cur.fetchone()
            if row:
                username = row[0] or ""
                password = _deobfuscate(row[1]) if row[1] else ""
                enable_pw = _deobfuscate(row[2]) if row[2] else ""
        except Exception:
            pass
        try:
            from .terminal_panel import TerminalPanel
            TerminalPanel(self, host, port, dname, username=username,
                          password=password, enable_pw=enable_pw)
        except Exception as e:
            QMessageBox.critical(self, "Terminal Error", str(e))

    def _open_subnet_calculator(self):
        try:
            from .calculators import SubnetCalculator
            SubnetCalculator(self)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ── Deploy All ──────────────────────────────────────────────────────

    def deploy_all_ordered(self):
        if not self.devices:
            QMessageBox.information(self, "Deploy All", "No devices in workspace.")
            return

        def _priority(item):
            _, model, __ = item
            if isinstance(model, RouterModel): return 0
            elif isinstance(model, CoreSwitchModel): return 1
            return 2

        ordered = sorted(self.devices, key=_priority)
        deploy_list = []
        for name, model, meta in ordered:
            config = model.build_full_config().strip()
            if not config or config.startswith("!"):
                lines = [l for l in config.splitlines() if l.strip() and not l.strip().startswith("!")]
                if not lines:
                    deploy_list.append((name, model, meta, None, None, "", "", "", "no config"))
                    continue
            host = meta.get("console_host") or meta.get("ip", "")
            port_raw = meta.get("console_port") or meta.get("port", "")
            username = meta.get("username", "")
            password = meta.get("password", "")
            enable_pw = meta.get("enable_pw", "")
            try:
                with db_lock:
                    cur.execute("SELECT host, port, username, password, enable_password FROM credentials WHERE device_name=?", (name,))
                    row = cur.fetchone()
                if row:
                    if row[0] and not host: host, port_raw = row[0], row[1]
                    if row[2] and not username: username = row[2]
                    if row[3] and not password: password = _deobfuscate(row[3])
                    if row[4] and not enable_pw: enable_pw = _deobfuscate(row[4])
            except Exception:
                pass
            if not host:
                deploy_list.append((name, model, meta, None, None, "", "", "", "no host"))
                continue
            try:
                port = int(port_raw)
            except (ValueError, TypeError):
                deploy_list.append((name, model, meta, None, None, "", "", "", f"bad port: {port_raw}"))
                continue
            deploy_list.append((name, model, meta, host, port, username, password, enable_pw, "ready"))

        self._show_deploy_progress(deploy_list)

    def _show_deploy_progress(self, deploy_list):
        dlg = QDialog(self)
        dlg.setWindowTitle("Deploy All \u2014 Progress")
        dlg.resize(900, 600)
        dlg.setStyleSheet(self._dialog_style())
        layout = QVBoxLayout(dlg)

        summary = QLabel("Deploying configurations in priority order (Router -> Core -> Access).")
        summary.setStyleSheet("color: #8B949E; font-size: 12px;")
        layout.addWidget(summary)

        table = QTableWidget(len(deploy_list), 3)
        table.setHorizontalHeaderLabels(["Device", "Status", "Details"])
        self._style_table_widget(table)
        for i, (name, *_, status) in enumerate(deploy_list):
            table.setItem(i, 0, QTableWidgetItem(name))
            table.setItem(i, 1, QTableWidgetItem(status))
            if status == "ready":
                host = deploy_list[i][3]
                port = deploy_list[i][4]
                table.setItem(i, 2, QTableWidgetItem(f"target={host}:{port}"))
            else:
                table.setItem(i, 2, QTableWidgetItem(status))
        layout.addWidget(table)

        btn_close = QPushButton("Close")
        btn_close.setEnabled(False)
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)
        dlg.show()

        def worker():
            for i, item in enumerate(deploy_list):
                name, model, meta, host, port, user, pw, enable, status = item
                if status != "ready":
                    continue
                config = model.build_full_config().strip()
                self._run_on_main(lambda r=i: table.setItem(r, 1, QTableWidgetItem("Deploying...")))
                try:
                    ok = Sender.send_telnet(self.log, host, port, user, pw, enable, config)
                    result = "Success" if ok else "Failed"
                    detail = f"target={host}:{port}" if ok else "Send failed; check Logs tab"
                    if ok:
                        self._write_audit_log(name, "deploy-all", f"host={host}:{port}", config_content=config)
                except Exception as e:
                    result = f"Error: {e}"
                    detail = "Unexpected exception while sending"
                self._run_on_main(lambda r=i, s=result: table.setItem(r, 1, QTableWidgetItem(s)))
                self._run_on_main(lambda r=i, d=detail: table.setItem(r, 2, QTableWidgetItem(d)))
            self._run_on_main(lambda: btn_close.setEnabled(True))

        threading.Thread(target=worker, daemon=True).start()

    # ── Audit log ───────────────────────────────────────────────────────

    def open_audit_log(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Send History")
        dlg.resize(980, 640)
        dlg.setStyleSheet(self._dialog_style())
        layout = QVBoxLayout(dlg)

        title = QLabel("Send History")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #E6EDF3;")
        layout.addWidget(title)

        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["ID", "Device", "Action", "Details", "Time"])
        self._style_table_widget(table)
        try:
            cur.execute("SELECT id, device_name, action, details, timestamp FROM logs ORDER BY id DESC LIMIT 200")
            for row in cur.fetchall():
                r = table.rowCount()
                table.insertRow(r)
                for c, val in enumerate(row):
                    table.setItem(r, c, QTableWidgetItem(str(val or "")))
        except Exception:
            pass
        layout.addWidget(table)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)
        dlg.exec()

    # ── GNS3 ────────────────────────────────────────────────────────────

    def refresh_gns3_connection(self):
        """Retry GNS3 connection (same as Import but reuses last URL)."""
        self._set_gns3_status("Connecting...", False, "")
        threading.Thread(target=self._auto_connect_gns3, daemon=True).start()

    def _set_gns3_status(self, text: str, connected: bool = False, project_name: str = ""):
        """Update GNS3 status (thread-safe: use QTimer to run on main thread)."""
        def _do():
            try:
                self.lbl_gns3_status.setText(text)
                self.lbl_gns3_status.setStyleSheet(
                    "color: #085D3A; background-color: #ECFDF3; "
                    "border-radius: 6px; padding: 4px 10px; font-size: 12px;" if connected else
                    "color: #9BA3AF; background-color: rgba(12,26,46,200); "
                    "border-radius: 6px; padding: 4px 10px; font-size: 12px;")
                self.lbl_gns3_project_name.setText(project_name or "No project")
                self.lbl_gns3_project_name.setStyleSheet(
                    "color: #C9D1D9; font-size: 13px;" if project_name else "color: #8B949E; font-size: 13px;")
            except Exception:
                pass
        self._run_on_main(_do)

    def _auto_connect_gns3(self):
        if requests is None:
            self._set_gns3_status("requests not installed; GNS3 disabled", False, "")
            return
        try:
            g = GNS3Connector(self._last_gns3_url)
            projs = g.get_projects()
            if not projs:
                self._set_gns3_status("No projects on server", False, "")
                return
            # Prefer opened project (status can be 'opened' or 'opened')
            proj = None
            for p in projs:
                if p.get('is_open') or str(p.get('status', '')).lower() == 'opened':
                    proj = p
                    break
            if not proj:
                try:
                    proj = sorted(projs, key=lambda x: x.get('name', ''), reverse=True)[0]
                except Exception:
                    proj = projs[0]
            self.gns3 = g
            self.last_gns3_project = proj
            project_id = proj.get('project_id') or proj.get('projectId') or proj.get('id')
            self.gns3_project_id = project_id
            if not project_id:
                self._set_gns3_status("Project missing ID", False, "")
                return
            nodes = self.gns3.get_nodes(project_id)
            _SKIP_TYPES = {"vpcs", "cloud", "nat", "ethernet_switch", "ethernet_hub", "frame_relay_switch", "atm_switch"}
            l3_keywords = ['l3 switch', 'layer3', 'layer 3', 'esw', 'c3640', 'c3560', 'c3750', 'multilayer']
            rtr_keywords = ['router', 'ios', 'csr', 'isr', 'iosv', 'firepower', 'asa', 'xrv', 'nxos',
                            'c2691', 'c2600', 'c7200', 'c3725', 'c3745', 'c3660', 'c3845', 'c1900', 'c2900',
                            'adventerprisek9', 'advipservices']
            new_devices = []
            for node in nodes:
                raw_type = node.get('node_type', '')
                if raw_type.lower() in _SKIP_TYPES:
                    self.log(f"[gns3] skipping: {node.get('name')} ({raw_type})")
                    continue
                name = node.get('name') or f"node-{str(node.get('node_id','') or node.get('id',''))[:6]}"
                console_host = node.get('console_host') or 'localhost'
                console_port = node.get('console') or node.get('console_port') or ''
                node_id = node.get('node_id') or node.get('id')
                platform = node.get('platform', '')
                console_type = node.get('console_type', '')
                image_name = (node.get('properties') or {}).get('image', '')
                full_desc = " ".join([raw_type, platform, console_type, image_name, name]).lower()
                if any(k in full_desc for k in l3_keywords):
                    ntype = 'core switch'
                elif any(k in full_desc for k in rtr_keywords):
                    ntype = 'router'
                else:
                    ntype = 'switch'
                interfaces = []
                try:
                    ports_data = self.gns3.get_node_ports(project_id, node_id)
                    interfaces = [p["name"] for p in ports_data if p.get("name")]
                except Exception:
                    pass
                new_devices.append({"name": name, "ntype": ntype, "node_id": node_id,
                                     "console_host": console_host, "console_port": str(console_port),
                                     "project_id": project_id, "interfaces": interfaces})
            proj_name = proj.get('name', '')
            self._run_on_main(lambda nd=new_devices, pn=proj_name: self._apply_gns3_import(nd, pn))
        except Exception as exc:
            err = str(exc)
            if "Cannot reach" in err or "Connection" in err or "did not respond" in err:
                self._set_gns3_status("GNS3 not running", False, "")
            else:
                self._set_gns3_status(err[:40] + "…" if len(err) > 40 else err, False, "")

    def _apply_gns3_import(self, new_devices, proj_name):
        imported = 0
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        project_id = self.gns3_project_id if hasattr(self, 'gns3_project_id') else ""
        for d in new_devices:
            name, node_id = d["name"], d["node_id"]
            already = any(x[2].get("node_id") == node_id and x[2].get("project_id") == project_id for x in self.devices)
            if already:
                continue
            dev_name = name
            i = 1
            while any(x[0] == dev_name for x in self.devices):
                dev_name = f"{name}-{i}"; i += 1
            meta = {"gns3_node": True, "project_id": project_id, "node_id": node_id,
                     "console_host": d["console_host"], "console_port": d["console_port"],
                     "interfaces": d["interfaces"]}
            self.add_device_instance(d["ntype"], dev_name, metadata=meta)
            try:
                with db_lock:
                    cur.execute("INSERT OR REPLACE INTO devices (name,type,ip,port,connection_type,added_from_gns3,project_id,node_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                (dev_name, d["ntype"], d["console_host"], d["console_port"], 'gns3-console', 1, project_id, node_id, ts))
                    conn.commit()
                imported += 1
            except Exception as exc:
                self.log(f"[db] error saving GNS3 device: {exc}")
        if imported > 0:
            self.refresh_device_list()
            self.log(f"Auto-imported {imported} GNS3 node(s) from '{proj_name}'")
        self._set_gns3_status("\u2713 Connected", connected=True, project_name=proj_name or "Unknown project")

    def gns3_list_projects(self):
        if requests is None:
            QMessageBox.critical(self, "Error", "requests not installed")
            return
        url, ok = QInputDialog.getText(self, "GNS3 URL",
                                        "Enter GNS3 server URL:", text=self._last_gns3_url)
        if not ok or not url:
            return
        url = url.strip().rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        self._last_gns3_url = url
        self._save_gns3_url(url)
        self.gns3 = GNS3Connector(server_url=url)
        try:
            projs = self.gns3.get_projects()
            if not projs:
                QMessageBox.information(self, "GNS3", "No projects found on server")
                return
            choices = [f"{p.get('name', '<unnamed>')} ({p.get('project_id') or p.get('projectId')})" for p in projs]
            idx, ok = self._select_from_list("Select Project", "Choose a project:", choices)
            if not ok or idx < 0:
                return
            project = projs[idx]
            self.last_gns3_project = project
            self.gns3_project_id = project.get('project_id') or project.get('projectId') or project.get('id')
            proj_name = project.get('name', '')
            self._set_gns3_status("\u2713 Connected", connected=True, project_name=proj_name or "Unknown project")
            QMessageBox.information(self, "GNS3", f"Selected {proj_name}")
            self.gns3_list_nodes(project.get('project_id') or project.get('projectId'))
        except Exception as e:
            QMessageBox.critical(self, "GNS3 Error", str(e))

    def gns3_list_nodes(self, project_id=None):
        if self.gns3 is None:
            QMessageBox.critical(self, "Error", "GNS3 connector not initialized")
            return
        if project_id is None:
            project_id = (getattr(self, "last_gns3_project", {}) or {}).get("project_id") or \
                          (getattr(self, "last_gns3_project", {}) or {}).get("projectId")
            if not project_id:
                QMessageBox.information(self, "Info", "Call list projects first")
                return
        try:
            nodes = self.gns3.get_nodes(project_id)
        except Exception as e:
            QMessageBox.critical(self, "GNS3 Error", str(e))
            return
        _SKIP = {"vpcs", "cloud", "nat", "ethernet_switch", "ethernet_hub", "frame_relay_switch", "atm_switch"}
        nodes = [n for n in nodes if n.get('node_type', '').lower() not in _SKIP]
        if not nodes:
            QMessageBox.information(self, "GNS3", "No configurable network devices found.")
            return
        labels = [f"{n.get('name')}  ({n.get('node_type')})  console:{n.get('console_host','localhost')}:{n.get('console') or n.get('console_port') or ''}" for n in nodes]
        idx, ok = self._select_from_list("Select Node", "Choose a node to import:", labels)
        if not ok or idx < 0:
            return
        node = nodes[idx]
        node_id = node.get("node_id") or node.get("id")
        already = any(d[2].get("node_id") == node_id and d[2].get("project_id") == project_id for d in self.devices)
        if already:
            QMessageBox.information(self, "Already in workspace", "This device is already in the workspace.")
            return
        console_host = node.get("console_host", "localhost")
        console_port = node.get("console") or node.get("console_port") or ""
        name = node.get("name") or f"node-{str(node_id or '')[:6]}"
        dtype, ok = QInputDialog.getText(self, "Device Type",
                                          "Device type for imported node (router/switch/core switch):", text="router")
        if not ok or not dtype:
            return
        dtype = dtype.strip().lower()
        if dtype not in self.device_types:
            QMessageBox.critical(self, "Error", "Unknown type")
            return
        meta = {"gns3_node": True, "project_id": project_id, "node_id": node_id,
                "console_host": console_host, "console_port": console_port}
        try:
            ports_data = self.gns3.get_node_ports(project_id, node_id)
            meta["interfaces"] = [p["name"] for p in ports_data if p.get("name")]
        except Exception:
            meta["interfaces"] = []
        base = name; dev_name = base; i = 1
        while any(d[0] == dev_name for d in self.devices):
            dev_name = f"{base}-{i}"; i += 1
        self.add_device_instance(dtype, dev_name, metadata=meta)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            cur.execute("INSERT OR REPLACE INTO devices (name,type,ip,port,connection_type,added_from_gns3,project_id,node_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (dev_name, dtype, console_host, str(console_port), "gns3-console", 1, project_id, node_id, ts))
            conn.commit()
        except Exception as e:
            self.log(f"[db] error saving gns3 device: {e}")
        self.refresh_device_list()
        QMessageBox.information(self, "GNS3", f"Imported node as '{dev_name}' (saved to DB)")

    # ── Close guard ─────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._send_in_progress:
            ret = QMessageBox.question(
                self, "Send in progress",
                "A configuration is currently being sent.\nClose anyway?")
            if ret != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()

    # ── DB stubs (kept for compatibility) ───────────────────────────────

    def _show_rows_dialog(self, title: str, headers: list[str], rows: list[tuple]):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(900, 520)
        dlg.setStyleSheet(self._dialog_style())
        layout = QVBoxLayout(dlg)
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        self._style_table_widget(table)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(str(val or "")))
        layout.addWidget(table)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)
        dlg.exec()

    def save_config_to_db(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first.")
            return
        content = self.preview.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "Info", "Nothing to save.")
            return
        dname = self.current_device[0]
        cfg_name, ok = QInputDialog.getText(self, "Save Config", "Config name:", text="manual_save")
        if not ok or not cfg_name.strip():
            return
        try:
            with db_lock:
                cur.execute("SELECT id FROM devices WHERE name=?", (dname,))
                row = cur.fetchone()
                if row:
                    dev_id = row[0]
                else:
                    cur.execute(
                        "INSERT INTO devices (name,type,ip,port,connection_type,created_at) VALUES (?,?,?,?,?,?)",
                        (dname, self.current_device[1].__class__.__name__.replace("Model", "").lower(), "", "", "manual", time.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    dev_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO configs (device_id, config_name, content, created_at) VALUES (?,?,?,?)",
                    (dev_id, cfg_name.strip(), content, time.strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
            QMessageBox.information(self, "Saved", f"Saved '{cfg_name.strip()}' for {dname}.")
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))

    def view_saved_configs(self):
        try:
            with db_lock:
                cur.execute(
                    "SELECT c.id, d.name, c.config_name, c.created_at "
                    "FROM configs c LEFT JOIN devices d ON d.id=c.device_id "
                    "ORDER BY c.id DESC LIMIT 300"
                )
                rows = cur.fetchall()
            if not rows:
                QMessageBox.information(self, "Saved Configs", "No saved configs found.")
                return
            self._show_rows_dialog("Saved Configs", ["ID", "Device", "Config Name", "Created"], rows)
        except Exception as exc:
            QMessageBox.critical(self, "DB Error", str(exc))

    def save_device_to_db(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first.")
            return
        dname, model, meta = self.current_device
        ip = self.ent_host.text().strip() or meta.get("console_host", "")
        port = self.ent_port.text().strip() or str(meta.get("console_port", ""))
        dtype = "router" if isinstance(model, RouterModel) else ("core switch" if isinstance(model, CoreSwitchModel) else "switch")
        try:
            with db_lock:
                cur.execute(
                    "INSERT OR REPLACE INTO devices (name,type,ip,port,connection_type,created_at) VALUES (?,?,?,?,?,?)",
                    (dname, dtype, ip, port, self.send_method.currentText().lower(), time.strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
            QMessageBox.information(self, "Saved", f"Device '{dname}' saved to DB.")
        except Exception as exc:
            QMessageBox.critical(self, "DB Error", str(exc))

    def refresh_devices_tree(self):
        self.refresh_device_list()

    def refresh_configs_tree(self):
        self.view_saved_configs()

    def refresh_users_tree(self):
        QMessageBox.information(self, "Users", "Users tree is not available in the current UI.")

    def refresh_tasks_tree(self):
        QMessageBox.information(self, "Tasks", "Tasks tree is not available in the current UI.")

    def refresh_logs_tree(self):
        self._refresh_logs_history()

    def refresh_ai_models_tree(self):
        QMessageBox.information(self, "AI Models", "AI models tree is not available in the current UI.")

    def refresh_training_tree(self):
        QMessageBox.information(self, "Training", "Training tree is not available in the current UI.")

    def import_device_from_tree(self):
        QMessageBox.information(self, "Import Device", "Use GNS3 -> Import or + Add in Devices.")

    def load_config_into_preview(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first.")
            return
        self.generate_full()

    def _check_and_refresh_db_tab(self):
        self._refresh_logs_history()

    def _refresh_config_status(self):
        pass

    def vlan_popup(self):
        self.vlan_gui_wizard()

    def vlan_gui_wizard(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first.")
            return
        from .wizards import VlanGuiWindow
        win = VlanGuiWindow(self)
        if win.exec() and getattr(win, "result", None):
            self.current_device[1].set_template("vlan_wizard_gui", win.result)
            self._refresh_template_list()
            self.generate_full()

    def stp_popup(self):
        self.stp_gui_wizard()

    def stp_gui_wizard(self):
        if not self.current_device:
            QMessageBox.information(self, "Info", "Select a device first.")
            return
        from .wizards import StpGuiWindow
        win = StpGuiWindow(self)
        if win.exec() and getattr(win, "result", None):
            self.current_device[1].set_template("stp_wizard_gui", win.result)
            self._refresh_template_list()
            self.generate_full()

    def open_ai_assistant(self):
        QMessageBox.information(self, "AI Assistant", "AI assistant panel is not available in the current UI build.")

    def view_saved_devices(self):
        try:
            with db_lock:
                cur.execute("SELECT id, name, type, ip, port, created_at FROM devices ORDER BY id DESC LIMIT 300")
                rows = cur.fetchall()
            if not rows:
                QMessageBox.information(self, "Saved Devices", "No devices found in DB.")
                return
            self._show_rows_dialog("Saved Devices", ["ID", "Name", "Type", "IP", "Port", "Created"], rows)
        except Exception as exc:
            QMessageBox.critical(self, "DB Error", str(exc))

    def subnet_calculator(self):
        self._open_subnet_calculator()

    # ── mainloop compatibility ──────────────────────────────────────────

    def mainloop(self):
        """Compatibility shim: QApplication event loop is managed by main.py."""
        self.show()
