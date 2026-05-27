"""
Main application GUI — PySide6 version with true glass transparency.
bg.png is painted on the main window; every panel uses rgba() for see-through glass.
"""
import sys, os, re, json, time, threading, ipaddress, base64, ctypes
from ctypes import wintypes
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QLineEdit, QPlainTextEdit, QComboBox,
    QCheckBox, QListWidget, QListWidgetItem, QScrollArea, QSplitter,
    QMessageBox, QInputDialog, QFileDialog, QDialog, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QMenuBar,
    QSizePolicy, QAbstractItemView, QStackedWidget, QToolTip,
    QGraphicsDropShadowEffect,
)
from PySide6.QtCore import (
    Qt, QTimer, QSize, Signal, QMetaObject, Q_ARG, QThread, QEvent, QPoint,
    QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
    QSequentialAnimationGroup, QAbstractAnimation, Property,
)
from PySide6.QtGui import (
    QPixmap, QPainter, QFont, QColor, QIcon, QPalette, QAction,
    QFontDatabase,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect

# ── Custom Dialogs ────────────────────────────────────────────────────────
class ActionConfirmDialog(QDialog):
    """Premium custom confirmation dialog replacing native OS warning boxes."""
    def __init__(self, parent, title, message, action_text, action_color="#1F6FEB", hover_color="#388BFD"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(450, 220)
        if hasattr(parent, "_dialog_style"):
            self.setStyleSheet(parent._dialog_style())
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 24)
        
        lbl_msg = QLabel(message)
        lbl_msg.setWordWrap(True)
        lbl_msg.setStyleSheet("font-size: 15px; color: #C9D1D9; line-height: 1.4;")
        layout.addWidget(lbl_msg)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedWidth(100)
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #484F58;
                border-radius: 6px;
                color: #C9D1D9;
            }
            QPushButton:hover { background-color: #21262D; }
        """)
        btn_cancel.clicked.connect(self.reject)
        
        btn_action = QPushButton(action_text)
        btn_action.setFixedWidth(160)
        btn_action.setFixedHeight(36)
        btn_action.setStyleSheet(f"""
            QPushButton {{
                background-color: {action_color};
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 6px;
                color: #FFFFFF;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {hover_color}; }}
        """)
        btn_action.clicked.connect(self.accept)
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_action.setDefault(True)
        btn_action.setAutoDefault(True)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addSpacing(12)
        btn_layout.addWidget(btn_action)
        layout.addLayout(btn_layout)


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


def _gui_path(*parts: str) -> str:
    """Absolute path helper rooted at this gui package directory."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)

# ── project imports ─────────────────────────────────────────────────────

from ..config import DB_PATH, GNS3_DEFAULT_URL, CONFIG_FILE, conn, cur, db_lock, _db_error
from ..models import DeviceModel, RouterModel, SwitchModel, CoreSwitchModel
from ..network import Sender, GNS3Connector
from .utils import apply_responsive_geometry, enable_global_dark_dialogs
from .outlined_label import OutlinedLabel
from .physical_discovery_dialog import PhysicalDiscoveryDialog

try:
    import requests
except Exception:
    requests = None

# ── glass stylesheet ────────────────────────────────────────────────────

GLASS_PANEL = """
    QFrame[glassPanel="true"] {
        background-color: rgba(10, 20, 35, 0.72);
        border-radius: 10px;
        border: 1px solid rgba(60, 100, 170, 0.45);
        padding: 10px;
    }
"""

GLASS_STYLE = """
    * {
        font-family: 'Segoe UI', sans-serif;
        color: #C9D1D9;
        font-size: 15px;
    }

    QMainWindow {
        background: transparent;
    }

    QFrame[glassPanel="true"] {
        background-color: rgba(10, 20, 35, 0.72);
        border-radius: 10px;
        border: 1px solid rgba(60, 100, 170, 0.45);
        padding: 10px;
    }

    QFrame[topBar="true"] {
        background-color: rgba(8, 18, 34, 200);
        border-radius: 0px;
        border: none;
        border-bottom: 1px solid rgba(86, 146, 228, 55);
    }

    QFrame[windowTitleBar="true"] {
        background-color: rgba(8, 18, 34, 240);
        border: none;
        border-bottom: 1px solid rgba(86, 146, 228, 58);
    }

    QLabel[windowTitleText="true"] {
        color: #E0E8F0;
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }

    QLabel {
        background: transparent;
        border: none;
    }

    /* ── TOOLTIP ── */
    QToolTip {
        background-color: rgba(13, 17, 23, 240);
        color: #E6EDF3;
        border: 1px solid rgba(88, 166, 255, 80);
        border-radius: 6px;
        padding: 6px 12px;
        font-size: 12px;
    }

    /* ── BUTTONS ── */
    QPushButton {
        background-color: rgba(49, 61, 78, 208);
        color: #A6B2C2;
        border: 1px solid rgba(80, 100, 130, 60);
        border-radius: 8px;
        padding: 7px 14px;
        font-size: 15px;
        min-height: 30px;
    }
    QPushButton:hover {
        background-color: rgba(68, 84, 108, 235);
        color: #FFFFFF;
        border: 1px solid rgba(88, 166, 255, 100);
    }
    QPushButton:pressed {
        background-color: rgba(55, 75, 100, 255);
        border: 1px solid rgba(88, 166, 255, 160);
    }
    QPushButton:disabled {
        background-color: rgba(35, 42, 52, 150);
        color: #4A5568;
        border: 1px solid rgba(80, 100, 130, 30);
    }
    QPushButton:focus {
        border: 1px solid rgba(147, 197, 253, 210);
    }

    QPushButton[accent="true"] {
        background-color: rgba(37, 99, 235, 230);
        color: white;
        font-weight: 700;
        border: 1px solid rgba(59, 130, 246, 120);
    }
    QPushButton[accent="true"]:hover {
        background-color: rgba(59, 130, 246, 255);
        border: 1px solid rgba(147, 197, 253, 180);
    }
    
    QPushButton[pill="true"] {
        border-radius: 20px;
        padding: 9px 20px;
        font-size: 16px;
        font-weight: 700;
    }

    QPushButton[teal="true"] {
        background-color: rgba(13, 148, 136, 225);
        color: white;
        font-weight: bold;
        border: 1px solid rgba(20, 184, 166, 100);
    }
    QPushButton[teal="true"]:hover {
        background-color: rgba(15, 118, 110, 245);
        border: 1px solid rgba(45, 212, 191, 150);
    }

    QPushButton[outlined="true"] {
        background-color: transparent;
        color: #58A6FF;
        border: 1px solid rgba(88, 166, 255, 130);
    }
    QPushButton[outlined="true"]:hover {
        background-color: rgba(88, 166, 255, 18);
        border: 1px solid rgba(88, 166, 255, 200);
        color: #93C5FD;
    }

    QPushButton[danger="true"] {
        background-color: transparent;
        color: #F87171;
        border: 1px solid rgba(248, 113, 113, 120);
    }
    QPushButton[danger="true"]:hover {
        background-color: rgba(248, 113, 113, 14);
        border: 1px solid rgba(248, 113, 113, 200);
        color: #FCA5A5;
    }
    
    /* Top Nav Tabs Active/Inactive Styling */
    QPushButton[navTab="active"] {
        background: transparent;
        color: #60A5FA;
        font-size: 17px;
        font-weight: 700;
        border: none;
        border-bottom: 2px solid #3B82F6;
        border-radius: 0px;
        padding: 8px 18px;
    }
    QPushButton[navTab="inactive"] {
        background: transparent;
        color: #6B7280;
        font-size: 17px;
        font-weight: 600;
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0px;
        padding: 8px 18px;
    }
    QPushButton[navTab="inactive"]:hover {
        color: #D1D5DB;
        background: transparent;
        border-bottom: 2px solid rgba(107, 114, 128, 80);
    }

    /* Preview panel tab strip */
    QPushButton[previewTab="active"] {
        background: transparent;
        color: #EAF2FF;
        font-size: 16px;
        font-weight: 700;
        border: none;
        border-bottom: 2px solid #58A6FF;
        border-radius: 0px;
        padding: 3px 12px;
        min-height: 26px;
    }
    QPushButton[previewTab="active"]:hover {
        background: transparent;
        color: #FFFFFF;
    }
    QPushButton[previewTab="inactive"] {
        background: transparent;
        color: #A6B5CA;
        font-size: 16px;
        font-weight: 500;
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0px;
        padding: 3px 12px;
        min-height: 26px;
    }
    QPushButton[previewTab="inactive"]:hover {
        background: transparent;
        color: #DCE9FA;
        border-bottom: 2px solid rgba(88, 166, 255, 120);
    }

    QPushButton[titleControl="true"] {
        background: transparent;
        color: #C9D1D9;
        border: none;
        border-radius: 6px;
        min-width: 40px;
        max-width: 40px;
        min-height: 28px;
        padding: 0px;
        font-size: 15px;
        font-weight: 600;
    }
    QPushButton[titleControl="true"]:hover {
        background-color: rgba(88, 166, 255, 72);
        color: #FFFFFF;
    }
    QPushButton[titleControlClose="true"] {
        background: transparent;
        color: #E6EDF3;
        border: none;
        border-radius: 6px;
        min-width: 40px;
        max-width: 40px;
        min-height: 28px;
        padding: 0px;
        font-size: 15px;
        font-weight: 700;
    }
    QPushButton[titleControlClose="true"]:hover {
        background-color: rgba(220, 38, 38, 208);
        color: #FFFFFF;
    }

    /* ── INPUT FIELDS ── */
    QLineEdit {
        background-color: rgba(22, 34, 52, 220);
        color: #FFFFFF;
        border: 1px solid rgba(88, 110, 145, 130);
        border-radius: 8px;
        padding: 9px 12px;
        font-size: 15px;
    }
    QLineEdit:disabled {
        background-color: rgba(50, 56, 66, 130);
        border: 1px solid rgba(100, 106, 116, 80);
        color: #5A6370;
    }
    QLineEdit:focus {
        border: 1px solid rgba(88, 166, 255, 220);
        background-color: rgba(25, 40, 60, 240);
    }
    QLineEdit::placeholder {
        color: #5C6B7E;
    }
    QLineEdit[hasError="true"] {
        border: 1px solid #F87171;
        background-color: rgba(58, 24, 28, 208);
    }

    QPlainTextEdit {
        background-color: rgba(16, 22, 30, 235);
        color: #E6EDF3;
        border: 1px solid rgba(48, 54, 61, 100);
        border-radius: 10px;
        font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
        font-size: 14px;
        padding: 12px;
    }
    QPlainTextEdit:focus {
        border: 1px solid rgba(88, 166, 255, 140);
    }

    /* ── COMBOBOX ── */
    QComboBox {
        background-color: rgba(18, 32, 54, 215);
        color: #FFFFFF;
        border: 1px solid rgba(88, 130, 200, 70);
        border-radius: 8px;
        padding: 7px 12px;
        font-size: 15px;
    }
    QComboBox:hover {
        border: 1px solid rgba(88, 166, 255, 120);
    }
    QComboBox:focus {
        border: 1px solid #58A6FF;
    }
    QComboBox::drop-down {
        border: none;
        width: 28px;
    }
    QComboBox QAbstractItemView {
        background-color: rgba(12, 26, 46, 250);
        color: #FFFFFF;
        selection-background-color: rgba(88, 166, 255, 50);
        border: 1px solid rgba(70, 140, 230, 50);
        border-radius: 6px;
        padding: 4px;
        outline: none;
    }

    /* ── CHECKBOX ── */
    QCheckBox {
        background: transparent;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border: 1.5px solid #5A6370;
        border-radius: 5px;
        background: rgba(35, 42, 55, 220);
    }
    QCheckBox::indicator:hover {
        border-color: #58A6FF;
    }
    QCheckBox::indicator:checked {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3B82F6, stop:1 #2563EB);
        border-color: #60A5FA;
    }

    /* ── LIST WIDGET ── */
    QListWidget {
        background-color: rgba(6, 14, 28, 235);
        border: 1px solid rgba(72, 124, 196, 110);
        border-radius: 10px;
        padding: 6px;
        font-size: 15px;
        outline: none;
    }
    QListWidget:focus {
        border: 1px solid rgba(88, 166, 255, 180);
    }
    QListWidget::item {
        padding: 10px 12px;
        border-radius: 6px;
        margin-bottom: 2px;
        border-left: 3px solid transparent;
    }
    QListWidget::item:selected {
        background-color: rgba(88, 166, 255, 50);
        color: #FFFFFF;
        border-left: 3px solid #3B82F6;
    }
    QListWidget::item:hover:!selected {
        background-color: rgba(88, 166, 255, 22);
    }

    /* ── SCROLL AREA ── */
    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }

    /* ── SCROLLBAR ── */
    QScrollBar:vertical {
        background: rgba(12, 26, 46, 60);
        width: 8px;
        border-radius: 4px;
        margin: 2px 0px;
    }
    QScrollBar::handle:vertical {
        background: rgba(88, 140, 210, 100);
        border-radius: 4px;
        min-height: 36px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(88, 166, 255, 170);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: none;
    }
    QScrollBar:horizontal {
        background: rgba(12, 26, 46, 60);
        height: 8px;
        border-radius: 4px;
    }
    QScrollBar::handle:horizontal {
        background: rgba(88, 140, 210, 100);
        border-radius: 4px;
        min-width: 36px;
    }
    QScrollBar::handle:horizontal:hover {
        background: rgba(88, 166, 255, 170);
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: none;
    }

    /* ── TABLE ── */
    QTableWidget {
        background-color: rgba(16, 22, 30, 220);
        color: #C9D1D9;
        border: none;
        border-radius: 10px;
        gridline-color: rgba(48, 54, 61, 100);
        font-size: 14px;
        alternate-background-color: rgba(22, 30, 42, 200);
        outline: none;
    }
    QTableWidget:focus {
        border: 1px solid rgba(88, 166, 255, 120);
    }
    QTableWidget::item {
        padding: 6px 10px;
        border-bottom: 1px solid rgba(48, 54, 61, 80);
    }
    QTableWidget::item:selected {
        background-color: rgba(38, 79, 120, 200);
        color: #FFFFFF;
    }
    QTableWidget::item:hover:!selected {
        background-color: rgba(88, 166, 255, 16);
    }
    QHeaderView::section {
        background-color: rgba(22, 30, 42, 240);
        color: #8B949E;
        border: none;
        border-bottom: 2px solid rgba(48, 54, 61, 150);
        padding: 8px 10px;
        font-weight: 600;
        font-size: 13px;
        letter-spacing: 0.3px;
    }

    /* ── MENUS ── */
    QMenuBar {
        background-color: rgba(7, 16, 31, 210);
        color: #C9D1D9;
    }
    QMenuBar::item:selected {
        background-color: rgba(88, 166, 255, 80);
    }
    QMenu {
        background-color: rgba(12, 26, 46, 250);
        color: #C9D1D9;
        border: 1px solid rgba(70, 140, 230, 50);
        border-radius: 8px;
        padding: 4px;
    }
    QMenu::item {
        padding: 8px 24px;
        border-radius: 4px;
    }
    QMenu::item:selected {
        background-color: rgba(88, 166, 255, 60);
    }
    QMenu::separator {
        height: 1px;
        background: rgba(48, 54, 61, 120);
        margin: 4px 12px;
    }

    /* Unified dialog theming */
    QDialog, QMessageBox, QInputDialog, QFileDialog {
        background-color: rgba(8, 18, 34, 240);
        color: #D3DCE8;
    }
    QMessageBox QLabel, QInputDialog QLabel, QFileDialog QLabel {
        color: #D3DCE8;
        font-size: 14px;
    }
    QDialogButtonBox QPushButton {
        min-width: 92px;
    }
    QFileDialog QTreeView, QFileDialog QListView {
        background-color: rgba(14, 28, 46, 235);
        color: #D3DCE8;
        border: 1px solid rgba(86, 146, 228, 50);
        border-radius: 8px;
        selection-background-color: rgba(88, 166, 255, 60);
    }
    QFileDialog QLineEdit {
        background-color: rgba(18, 32, 54, 225);
    }
"""

# ── Frameless resize grips ───────────────────────────────────────────────

class _EdgeGrip(QWidget):
    """Invisible widget placed on a window edge/corner to handle resize."""

    # edge is a combination of: 'left', 'right', 'top', 'bottom'
    _CURSORS = {
        'left':         Qt.SizeHorCursor,
        'right':        Qt.SizeHorCursor,
        'top':          Qt.SizeVerCursor,
        'bottom':       Qt.SizeVerCursor,
        'top-left':     Qt.SizeFDiagCursor,
        'bottom-right': Qt.SizeFDiagCursor,
        'top-right':    Qt.SizeBDiagCursor,
        'bottom-left':  Qt.SizeBDiagCursor,
    }

    def __init__(self, parent: QMainWindow, edge: str, thickness: int = 6):
        super().__init__(parent)
        self._edge = edge
        self._thickness = thickness
        self._drag_start_pos = None
        self._drag_start_geo = None
        self.setMouseTracking(True)
        self.setCursor(self._CURSORS.get(edge, Qt.ArrowCursor))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.raise_()

    def reposition(self):
        """Recompute geometry relative to parent window size."""
        pw = self.parent().width()
        ph = self.parent().height()
        t = self._thickness
        e = self._edge
        if e == 'left':
            self.setGeometry(0, t, t, ph - 2 * t)
        elif e == 'right':
            self.setGeometry(pw - t, t, t, ph - 2 * t)
        elif e == 'top':
            self.setGeometry(t, 0, pw - 2 * t, t)
        elif e == 'bottom':
            self.setGeometry(t, ph - t, pw - 2 * t, t)
        elif e == 'top-left':
            self.setGeometry(0, 0, t, t)
        elif e == 'top-right':
            self.setGeometry(pw - t, 0, t, t)
        elif e == 'bottom-left':
            self.setGeometry(0, ph - t, t, t)
        elif e == 'bottom-right':
            self.setGeometry(pw - t, ph - t, t, t)
        self.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_start_geo = self.parent().geometry()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is None or self._drag_start_geo is None:
            return
        delta = event.globalPosition().toPoint() - self._drag_start_pos
        geo = self._drag_start_geo
        parent = self.parent()
        min_w = parent.minimumWidth()
        min_h = parent.minimumHeight()

        new_x, new_y = geo.x(), geo.y()
        new_w, new_h = geo.width(), geo.height()

        e = self._edge
        if 'left' in e:
            proposed_w = geo.width() - delta.x()
            if proposed_w >= min_w:
                new_x = geo.x() + delta.x()
                new_w = proposed_w
        if 'right' in e:
            new_w = max(min_w, geo.width() + delta.x())
        if 'top' in e:
            proposed_h = geo.height() - delta.y()
            if proposed_h >= min_h:
                new_y = geo.y() + delta.y()
                new_h = proposed_h
        if 'bottom' in e:
            new_h = max(min_h, geo.height() + delta.y())

        parent.setGeometry(new_x, new_y, new_w, new_h)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        self._drag_start_geo = None
        super().mouseReleaseEvent(event)


# ── Main Window ─────────────────────────────────────────────────────────

class App(QMainWindow):
    """Main application window with glass-transparent panels over bg.png."""

    _main_thread_call = Signal(object)

    def __init__(self):
        super().__init__()
        self.txt_logs = None
        self._use_custom_title_bar = (sys.platform == "win32")
        self._title_drag_offset: Optional[QPoint] = None
        self._title_drag_widgets: tuple[QWidget, ...] = tuple()
        if self._use_custom_title_bar:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowTitle("ANCS - Network Manager")
        apply_responsive_geometry(
            self,
            desired_w=1360,
            desired_h=800,
            min_w=1240,
            min_h=700,
            margin=80,
        )

        # Load bg.png
        gui_dir = os.path.dirname(os.path.abspath(__file__))
        bg_path = _gui_path("bg.png")
        self._bg_pixmap = QPixmap(bg_path) if os.path.exists(bg_path) else QPixmap()

        # Load logo — use logo.png
        self._logo_pixmap = QPixmap()
        _logo_path = _gui_path("logo.png")
        if os.path.exists(_logo_path):
            self._logo_pixmap = QPixmap(_logo_path)

        # Load Montserrat/Orbitron/Michroma fonts so they are available as QFont families
        for _font_file in ("Michroma-Regular.ttf", "Orbitron-Bold.ttf", "Montserrat-ExtraBold.ttf", "Montserrat-Regular.ttf"):
            _fp = _gui_path(_font_file)
            if os.path.exists(_fp):
                QFontDatabase.addApplicationFont(_fp)

        self._icon_cache: dict[str, QIcon] = {}

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(GLASS_STYLE)
        self.setStyleSheet(GLASS_STYLE)

        # Set application & window icon (taskbar + title bar)
        for _icon_candidate in ("ancs_logo.ico", "logo_icon.png"):
            _icon_path = _gui_path(_icon_candidate)
            if os.path.exists(_icon_path):
                _app_icon = QIcon(_icon_path)
                self.setWindowIcon(_app_icon)
                if app is not None:
                    app.setWindowIcon(_app_icon)
                break

        # State
        self.device_types = {"router": RouterModel, "switch": SwitchModel, "core switch": CoreSwitchModel}
        
        # Apply dark title bars globally to all QDialog/QMessageBox popups
        enable_global_dark_dialogs(app)
        self.devices: list[tuple[str, DeviceModel, dict]] = []
        self.current_device: Optional[tuple[str, DeviceModel, dict]] = None
        self.selected_device_name = None
        self.selected_template_name = None
        self.gns3: Optional[GNS3Connector] = None
        self.last_gns3_project = None
        self._last_gns3_url = self._load_gns3_url()
        self._send_in_progress = False
        self.right_sidebar_visible = True
        self._project_sync_triggered = False
        self._main_thread_call.connect(self._execute_main_thread_call)

        # Purge leftover database devices, configs, and credentials on startup
        # to ensure the persistent DB represents ONLY the live active session.
        self._clear_all_devices_from_db()

        self._build_ui()
        self._apply_main_window_min_size()
        if self._use_custom_title_bar:
            self._update_max_restore_button()
        else:
            self._schedule_title_bar_theme_refresh()
        self.statusBar().showMessage("Ready")

        # ── Animation state ──────────────────────────────────────────
        self._fade_in_done = False
        self._tab_animating = False
        self._status_overlay = None
        self._setup_animations()

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

    def _apply_windows_dark_title_bar(self):
        """Request dark title bar on Windows for better visual match with app theme."""
        if self._use_custom_title_bar:
            return
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
            DWMWA_BORDER_COLOR = 34
            DWMWA_CAPTION_COLOR = 35
            DWMWA_TEXT_COLOR = 36
            value = ctypes.c_int(1)
            set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute

            # Try modern attribute first, then fallback for older Windows builds.
            hr = set_attr(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if hr != 0:
                set_attr(
                    ctypes.c_void_p(hwnd),
                    ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE_OLD),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )

            # Force caption colors for Windows builds that ignore immersive dark flag.
            # COLORREF is 0x00BBGGRR.
            caption_color = ctypes.c_uint(0x002E1A0C)  # rgb(12, 26, 46)
            text_color = ctypes.c_uint(0x00E8DCD3)     # rgb(211, 220, 232)
            border_color = ctypes.c_uint(0x00342818)   # rgb(24, 40, 52)
            set_attr(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(DWMWA_CAPTION_COLOR),
                ctypes.byref(caption_color),
                ctypes.sizeof(caption_color),
            )
            set_attr(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(DWMWA_TEXT_COLOR),
                ctypes.byref(text_color),
                ctypes.sizeof(text_color),
            )
            set_attr(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(DWMWA_BORDER_COLOR),
                ctypes.byref(border_color),
                ctypes.sizeof(border_color),
            )
        except Exception:
            pass

    def _schedule_title_bar_theme_refresh(self):
        """Re-apply title bar theming across startup timing differences on Windows."""
        if self._use_custom_title_bar:
            return
        if sys.platform != "win32":
            return
        for delay in (0, 80, 220, 500):
            QTimer.singleShot(delay, self._apply_windows_dark_title_bar)

    def changeEvent(self, event):
        if event.type() in (QEvent.WindowStateChange, QEvent.ActivationChange):
            pass # We trace state manually now, don't update button here because it causes loops
        super().changeEvent(event)

    def _toggle_max_restore(self):
        from PySide6.QtCore import QRect
        current_geo = self.geometry()

        if self._is_custom_maximized:
            # Restoring — animate from maximized to saved normal geometry
            target_geo = getattr(self, '_normal_geometry', current_geo)
            self._is_custom_maximized = False
            self._update_max_restore_button()

            # Temporarily stay at current size, animate geometry
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.show()
            self._geo_anim = QPropertyAnimation(self, b"geometry")
            self._geo_anim.setDuration(280)
            self._geo_anim.setStartValue(current_geo)
            self._geo_anim.setEndValue(target_geo)
            self._geo_anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._geo_anim.start()
        else:
            # Maximizing — save current geo, animate to screen
            self._normal_geometry = QRect(current_geo)
            screen = self.screen()
            if screen:
                available = screen.availableGeometry()
            else:
                available = QRect(0, 0, 1920, 1080)

            self._is_custom_maximized = True
            self._update_max_restore_button()

            self._geo_anim = QPropertyAnimation(self, b"geometry")
            self._geo_anim.setDuration(280)
            self._geo_anim.setStartValue(current_geo)
            self._geo_anim.setEndValue(available)
            self._geo_anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._geo_anim.start()

    def _animated_minimize(self):
        """Fade-out then minimize."""
        self._min_anim = QPropertyAnimation(self, b"windowOpacity")
        self._min_anim.setDuration(180)
        self._min_anim.setStartValue(1.0)
        self._min_anim.setEndValue(0.0)
        self._min_anim.setEasingCurve(QEasingCurve.InQuad)
        def do_minimize():
            self.showMinimized()
            self.setWindowOpacity(1.0)
        self._min_anim.finished.connect(do_minimize)
        self._min_anim.start()

    def _animated_close(self):
        """Fade-out then close."""
        self._close_anim = QPropertyAnimation(self, b"windowOpacity")
        self._close_anim.setDuration(220)
        self._close_anim.setStartValue(1.0)
        self._close_anim.setEndValue(0.0)
        self._close_anim.setEasingCurve(QEasingCurve.InQuad)
        self._close_anim.finished.connect(self.close)
        self._close_anim.start()

    def _update_max_restore_button(self):
        btn = getattr(self, "_btn_title_max", None)
        if btn is None:
            return
        btn.setText("❐" if self._is_custom_maximized else "□")

    def eventFilter(self, obj, event):
        if self._use_custom_title_bar and obj in self._title_drag_widgets:
            et = event.type()
            # Ignore events when the actual click target is a title-bar button
            # (min / max / close).
            child_at = obj.childAt(event.position().toPoint()) if hasattr(event, 'position') else None
            if isinstance(child_at, QPushButton):
                return False  # let the button handle it normally
            if et == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self._toggle_max_restore()
                return True
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                gp = event.globalPosition().toPoint()
                if self._is_custom_maximized:
                    # Restore to normal size for dragging
                    saved = getattr(self, '_normal_geometry', None)
                    w = saved.width() if saved else self.width() // 2
                    h = saved.height() if saved else self.height() // 2
                    self._is_custom_maximized = False
                    self._update_max_restore_button()
                    self._title_drag_offset = QPoint(w // 2, 16)
                    self.setGeometry(gp.x() - w // 2, gp.y() - 16, w, h)
                else:
                    self._title_drag_offset = gp - self.frameGeometry().topLeft()
                return True
            if et == QEvent.MouseMove and self._title_drag_offset is not None and (event.buttons() & Qt.LeftButton):
                gp = event.globalPosition().toPoint()
                self.move(gp - self._title_drag_offset)
                return True
            if et == QEvent.MouseButtonRelease:
                self._title_drag_offset = None
                return True
        return super().eventFilter(obj, event)


    def _get_export_path(self) -> str:
        """Open themed save-file dialog for project export."""
        dlg = QFileDialog(self, "Export ANCS Project")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setNameFilters(["ANCS Project (*.ancs)", "JSON (*.json)", "All files (*.*)"])
        dlg.setDefaultSuffix("ancs")
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return ""
        files = dlg.selectedFiles()
        return files[0] if files else ""

    def _get_import_path(self) -> str:
        """Open themed open-file dialog for project import."""
        dlg = QFileDialog(self, "Import ANCS Project")
        dlg.setAcceptMode(QFileDialog.AcceptOpen)
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilters(["ANCS Project (*.ancs)", "JSON (*.json)", "All files (*.*)"])
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return ""
        files = dlg.selectedFiles()
        return files[0] if files else ""

    def _apply_main_window_min_size(self):
        """Enforce a practical minimum size so the three-panel layout remains usable."""
        # Keep this aligned with _build_ui min widths and spacing values.
        layout_min_width = 220 + 560 + 350 + (18 * 2) + (20 * 2)
        layout_min_height = 700
        self.setMinimumSize(layout_min_width, layout_min_height)

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
        _ok = btns.button(QDialogButtonBox.StandardButton.Ok)
        if _ok:
            _ok.setDefault(True)
            _ok.setAutoDefault(True)
        _cancel = btns.button(QDialogButtonBox.StandardButton.Cancel)
        if _cancel:
            _cancel.setAutoDefault(False)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return lst.currentRow(), True
        return -1, False

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self._refresh_button_styles)
        if not self._use_custom_title_bar:
            self._schedule_title_bar_theme_refresh()
        # ── Fade-in on first show ────────────────────────────────────
        if not self._fade_in_done:
            self._fade_in_done = True
            self.setWindowOpacity(0.0)
            self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
            self._fade_anim.setDuration(420)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._fade_anim.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._use_custom_title_bar:
            # Reposition edge grips
            for grip in getattr(self, '_resize_grips', []):
                if self._is_custom_maximized: # Use custom state here
                    grip.hide()
                else:
                    grip.reposition()
                    grip.show()
        else:
            self._schedule_title_bar_theme_refresh()

    def _refresh_button_styles(self):
        """Ensure buttons with setProperty get correct styling after layout."""
        for w in self.findChildren(QPushButton):
            try:
                w.style().unpolish(w)
                w.style().polish(w)
            except Exception:
                pass

    def _icon(self, name: str) -> QIcon:
        cached = self._icon_cache.get(name)
        if cached is not None:
            return cached
        icon_path = _gui_path("icons", name)
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self._icon_cache[name] = icon
        return icon

    def _apply_icon(self, button: QPushButton, name: str, size: int = 16):
        icon = self._icon(name)
        if not icon.isNull():
            button.setIcon(icon)
            button.setIconSize(QSize(size, size))

    def _set_status_message(self, text: str, timeout_ms: int = 0):
        """Show an animated status notification."""
        try:
            self.statusBar().showMessage(text, timeout_ms)
            # Animated overlay notification
            self._show_status_toast(text, timeout_ms)
        except Exception:
            pass

    def _show_status_toast(self, text: str, timeout_ms: int = 0):
        """Show a floating toast notification that fades in and out."""
        try:
            if self._status_overlay is None:
                self._status_overlay = QLabel(self)
                self._status_overlay.setStyleSheet("""
                    background-color: rgba(13, 17, 23, 180);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 20px;
                    padding: 10px 24px;
                    font-size: 14px;
                    font-weight: 500;
                """)
                self._status_overlay.setAlignment(Qt.AlignCenter)
                self._status_overlay_effect = QGraphicsOpacityEffect(self._status_overlay)
                self._status_overlay.setGraphicsEffect(self._status_overlay_effect)

            overlay = self._status_overlay
            # Add a context icon to the text
            icon_emoji = "☁️ " if "backup" in text.lower() else ("✅ " if "success" in text.lower() or "complete" in text.lower() else "ℹ️ ")
            overlay.setText(icon_emoji + text)
            overlay.adjustSize()
            
            # Position at bottom-center
            x = (self.width() - overlay.width()) // 2
            start_y = self.height() - 20
            end_y = self.height() - overlay.height() - 60
            overlay.move(x, end_y)
            overlay.show()
            overlay.raise_()

            # Slide + Fade Animation
            slide = QPropertyAnimation(overlay, b"pos")
            slide.setDuration(400)
            slide.setStartValue(QPoint(x, start_y))
            slide.setEndValue(QPoint(x, end_y))
            slide.setEasingCurve(QEasingCurve.OutCubic)

            fade_in = QPropertyAnimation(self._status_overlay_effect, b"opacity")
            fade_in.setDuration(400)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            
            if timeout_ms <= 0:
                timeout_ms = 3500

            fade_out = QPropertyAnimation(self._status_overlay_effect, b"opacity")
            fade_out.setDuration(600)
            fade_out.setStartValue(1.0)
            fade_out.setEndValue(0.0)
            fade_out.setEasingCurve(QEasingCurve.InCubic)

            self._toast_seq = QSequentialAnimationGroup()
            self._toast_para = QParallelAnimationGroup()
            self._toast_para.addAnimation(slide)
            self._toast_para.addAnimation(fade_in)
            
            self._toast_seq.addAnimation(self._toast_para)
            self._toast_seq.addPause(max(timeout_ms - 1000, 1000))
            self._toast_seq.addAnimation(fade_out)
            self._toast_seq.finished.connect(lambda: overlay.hide())
            self._toast_seq.start()
        except Exception:
            pass

    def _set_field_error(self, field: QLineEdit, has_error: bool, tooltip: str = ""):
        try:
            field.setProperty("hasError", has_error)
            field.style().unpolish(field)
            field.style().polish(field)
            field.setToolTip(tooltip if has_error else "")
        except Exception:
            pass

    def _setup_animations(self):
        """Initialize recurring UI micro-animations."""
        # Accent button breathing glow
        self._glow_phase = 0.0
        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._tick_accent_glow)
        self._glow_timer.start(50)  # 20fps for smoothness

    def _tick_accent_glow(self):
        """Advance the breathing glow animation on accent buttons."""
        import math
        self._glow_phase += 0.06
        # Sine wave from 0.35 → 1.0 for subtle breathing
        t = (math.sin(self._glow_phase) + 1.0) / 2.0  # 0→1
        alpha = int(80 + t * 120)  # 80 → 200
        brightness = int(120 + t * 135)  # 120 → 255
        glow_color = f"rgba({brightness}, {min(brightness + 30, 255)}, 255, {alpha})"
        for btn in self.findChildren(QPushButton):
            if btn.property("accent") is True:
                # Only override the border — preserve background from global stylesheet
                btn.setStyleSheet(f"border: 1px solid {glow_color};")
            elif btn.property("teal") is True:
                # Teal buttons get a green-tinted glow
                g_alpha = int(60 + t * 100)
                g_brightness = int(80 + t * 75)
                teal_glow = f"rgba({g_brightness}, {min(g_brightness + 80, 255)}, {min(g_brightness + 60, 200)}, {g_alpha})"
                btn.setStyleSheet(f"border: 1px solid {teal_glow};")

    def _validate_send_inputs(self) -> tuple[bool, str]:
        method = self.send_method.currentText().lower()
        content = self.preview.toPlainText().strip()
        if not content:
            return False, "Generate a config first"

        # Reset field error state before checking.
        for field in (self.ent_serial_port, self.ent_serial_baud, self.ent_host,
                      self.ent_port, self.ent_user, self.ent_pass):
            self._set_field_error(field, False)

        if method == "serial":
            port = self.ent_serial_port.text().strip()
            baud_raw = self.ent_serial_baud.text().strip() or "9600"
            if not port:
                self._set_field_error(self.ent_serial_port, True, "Serial port is required")
                return False, "Serial port is required"
            try:
                int(baud_raw)
            except Exception:
                self._set_field_error(self.ent_serial_baud, True, "Baud rate must be a number")
                return False, "Baud rate is invalid"
            return True, "Ready to send over serial"

        host = self.ent_host.text().strip()
        if not host:
            self._set_field_error(self.ent_host, True, "Host or IP is required")
            return False, "Host is required"

        port_raw = self.ent_port.text().strip() or ("22" if method == "ssh" else "23")
        try:
            port_val = int(port_raw)
            if port_val <= 0 or port_val > 65535:
                raise ValueError()
        except Exception:
            self._set_field_error(self.ent_port, True, "Port must be between 1 and 65535")
            return False, "Port is invalid"

        if method == "ssh":
            user = self.ent_user.text().strip()
            pw = self.ent_pass.text().strip()
            if not user:
                self._set_field_error(self.ent_user, True, "Username is required for SSH")
                return False, "Username is required"
            if not pw:
                self._set_field_error(self.ent_pass, True, "Password is required for SSH")
                return False, "Password is required"

        return True, "Ready to send"

    def _update_send_button_state(self):
        if self._send_in_progress:
            return
        ok, reason = self._validate_send_inputs()
        self.btn_send.setEnabled(ok)
        self.btn_send.setToolTip("" if ok else reason)

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

        # Install invisible edge grips for frameless resize
        if self._use_custom_title_bar:
            self._resize_grips = []
            self._is_custom_maximized = False # Initialize custom maximized state
            for edge in ('left', 'right', 'top', 'bottom',
                         'top-left', 'top-right', 'bottom-left', 'bottom-right'):
                g = _EdgeGrip(self, edge, thickness=6)
                self._resize_grips.append(g)

        if self._use_custom_title_bar:
            title_bar = QFrame()
            title_bar.setProperty("windowTitleBar", True)
            title_bar.setFixedHeight(34)
            tb_layout = QHBoxLayout(title_bar)
            tb_layout.setContentsMargins(10, 4, 6, 4)
            tb_layout.setSpacing(6)

            title_lbl = QLabel(self.windowTitle())
            title_lbl.setProperty("windowTitleText", True)
            tb_layout.addWidget(title_lbl)
            tb_layout.addStretch()

            btn_min = QPushButton("—")
            btn_min.setProperty("titleControl", True)
            btn_min.clicked.connect(self._animated_minimize)
            btn_min.setAutoDefault(False)
            btn_min.setDefault(False)
            btn_min.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tb_layout.addWidget(btn_min)

            self._btn_title_max = QPushButton("□")
            self._btn_title_max.setProperty("titleControl", True)
            self._btn_title_max.clicked.connect(self._toggle_max_restore)
            self._btn_title_max.setAutoDefault(False)
            self._btn_title_max.setDefault(False)
            self._btn_title_max.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tb_layout.addWidget(self._btn_title_max)

            btn_close = QPushButton("✕")
            btn_close.setProperty("titleControlClose", True)
            btn_close.clicked.connect(self._animated_close)
            btn_close.setAutoDefault(False)
            btn_close.setDefault(False)
            btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tb_layout.addWidget(btn_close)

            self._title_drag_widgets = (title_bar, title_lbl)
            for w in self._title_drag_widgets:
                w.installEventFilter(self)

            root_layout.addWidget(title_bar)

        # ── TOP BAR ─────────────────────────────────────────────────────
        top = QFrame()
        top.setProperty("topBar", True)
        top.setFixedHeight(88)
        top_layout = QGridLayout(top)
        top_layout.setContentsMargins(14, 0, 14, 0)

        # ── Header: logo + title/subtitle ──────────────────────────────
        header_widget = QWidget()
        header_widget.setAttribute(Qt.WA_TranslucentBackground)
        header_widget.setStyleSheet("background: transparent;")
        header_row = QHBoxLayout(header_widget)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(14)
        header_row.setAlignment(Qt.AlignVCenter)

        # Logo — logo_cropped.png scaled to 76px height, aspect-ratio preserved
        logo_lbl = QLabel()
        logo_lbl.setAttribute(Qt.WA_TranslucentBackground)
        logo_lbl.setStyleSheet("background: transparent;")
        logo_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        _LOGO_H = 58
        if not self._logo_pixmap.isNull():
            logo_lbl.setPixmap(self._logo_pixmap.scaledToHeight(
                _LOGO_H, Qt.SmoothTransformation))
        else:
            logo_lbl.setText("A")
            logo_lbl.setFixedSize(60, 60)
            logo_lbl.setAlignment(Qt.AlignCenter)
            logo_lbl.setStyleSheet(
                "background-color: #1A3A6B; color: white; border-radius: 30px; "
                "font-weight: bold; font-size: 24px;")
        header_row.addWidget(logo_lbl)

        # Text container: ANCS title + subtitle stacked vertically
        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setAlignment(Qt.AlignVCenter)

        lbl_title = OutlinedLabel("ANCS", stroke_width=2)
        lbl_title.setAttribute(Qt.WA_TranslucentBackground)
        # Using 28pt Michroma with 3px letter spacing tightly equalizes to 8pt subtitle 
        lbl_title.setStyleSheet("background: transparent; color: #FFFFFF; font-family: 'Michroma'; font-size: 28pt; letter-spacing: 4px; font-weight: 800;")
        text_col.addWidget(lbl_title)

        lbl_sub = QLabel("Auto Network Configuration System")
        lbl_sub.setAttribute(Qt.WA_TranslucentBackground)
        lbl_sub.setStyleSheet("background: transparent; color: #A0B4C8; font-family: 'Montserrat'; font-size: 8pt; letter-spacing: 1px;")
        text_col.addWidget(lbl_sub)

        header_row.addLayout(text_col)
        top_layout.addWidget(header_widget, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)

        # Nav tabs container
        nav_container = QWidget()
        nav_layout = QHBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(10)
        
        self.btn_main_nav = QPushButton("Main")
        self.btn_main_nav.setProperty("navTab", "active")
        self.btn_main_nav.clicked.connect(lambda: self._switch_tab("main"))

        self.btn_logs_nav = QPushButton("Logs")
        self.btn_logs_nav.setProperty("navTab", "inactive")
        self.btn_logs_nav.clicked.connect(lambda: self._switch_tab("logs"))

        nav_layout.addWidget(self.btn_main_nav)
        nav_layout.addWidget(self.btn_logs_nav)
        
        top_layout.addWidget(nav_container, 0, 1, Qt.AlignCenter)
        
        # Balance the grid forces so column 1 is exactly geometric center
        top_layout.setColumnStretch(0, 1)
        top_layout.setColumnStretch(1, 0)
        top_layout.setColumnStretch(2, 1)

        root_layout.addWidget(top)

        # ── BODY (stacked: main view vs logs view) ──────────────────────
        self._stack = QStackedWidget()
        self._stack.setAttribute(Qt.WA_TranslucentBackground)
        root_layout.addWidget(self._stack, 1)

        # --- Main page ---
        main_page = QWidget()
        main_page.setAttribute(Qt.WA_TranslucentBackground)
        main_layout = QHBoxLayout(main_page)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(18)

        # LEFT PANEL (responsive width, scrollable)
        left_panel = QFrame()
        left_panel.setProperty("glassPanel", True)
        left_panel.setObjectName("leftPanel")
        left_panel.setAutoFillBackground(True)
        left_panel.setStyleSheet("""
            QFrame#leftPanel {
                background-color: rgba(11, 29, 50, 110);
                border-radius: 12px;
                border: 1px solid rgba(50, 85, 160, 65);
            }
        """)
        left_panel.setMinimumWidth(260)
        left_panel.setMaximumWidth(380)
        left_scroll = QScrollArea()
        left_scroll.setWidget(left_panel)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setStyleSheet("background: transparent;")
        left_scroll.setMinimumWidth(260)
        left_scroll.setMaximumWidth(380)
        left_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(8)

        lbl_devices = QLabel("  Devices")
        lbl_devices.setStyleSheet(
            "color: #F0F2F4; font-size: 19px; font-weight: 700; "
            "border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3B82F6, stop:1 #2563EB); "
            "padding-left: 10px; padding-top: 2px; padding-bottom: 2px; margin-bottom: 4px;"
        )
        left_layout.addWidget(lbl_devices)

        self.device_list = QListWidget()
        self.device_list.setIconSize(QSize(16, 16))
        self.device_list.setMinimumHeight(250)
        self.device_list.setAutoFillBackground(True)
        self.device_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(8, 22, 42, 200);
                border: 1px solid rgba(55, 100, 180, 80);
                border-radius: 10px;
                padding: 6px;
                font-size: 15px;
                outline: none;
            }
            QListWidget::item {
                padding: 10px 12px;
                border-radius: 6px;
                color: #C9D1D9;
                border-left: 3px solid transparent;
                margin-bottom: 2px;
            }
            QListWidget::item:selected {
                background-color: rgba(59, 130, 246, 55);
                color: #FFFFFF;
                border-left: 3px solid #3B82F6;
            }
            QListWidget::item:hover:!selected {
                background-color: rgba(88, 166, 255, 25);
            }
        """)
        self.device_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.device_list.customContextMenuRequested.connect(self._device_list_context_menu)
        self.device_list.currentRowChanged.connect(self._on_device_row_changed)
        left_layout.addWidget(self.device_list)

        dev_btns = QHBoxLayout()
        _capsule_btn_style = """
            QPushButton {
                background-color: rgba(30, 55, 85, 220);
                border: 1px solid rgba(88, 140, 210, 50);
                border-radius: 17px;
                color: #C9D1D9;
                font-size: 13px;
                font-weight: 600;
                padding: 4px 16px;
            }
            QPushButton:hover {
                background-color: rgba(45, 75, 115, 240);
                border: 1px solid rgba(88, 166, 255, 120);
                color: #FFFFFF;
            }
        """
        btn_add = QPushButton("+ Add")
        btn_add.setStyleSheet(_capsule_btn_style)
        btn_add.setFixedHeight(34)
        btn_add.clicked.connect(self.add_device_prompt)
        btn_remove = QPushButton("Remove")
        btn_remove.setStyleSheet(_capsule_btn_style)
        btn_remove.setFixedHeight(34)
        btn_remove.clicked.connect(self.remove_selected_device)
        dev_btns.addWidget(btn_add)
        dev_btns.addWidget(btn_remove)
        left_layout.addLayout(dev_btns)

        lbl_templates = QLabel("  Templates")
        lbl_templates.setStyleSheet(
            "color: #F0F2F4; font-size: 19px; font-weight: 700; "
            "border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8B5CF6, stop:1 #6D28D9); "
            "padding-left: 10px; padding-top: 2px; padding-bottom: 2px; margin-bottom: 4px;"
        )
        left_layout.addWidget(lbl_templates)

        self.template_list = QListWidget()
        self.template_list.setMinimumHeight(200)
        self.template_list.setAutoFillBackground(True)
        self.template_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(8, 22, 42, 200);
                border: 1px solid rgba(55, 100, 180, 80);
                border-radius: 10px;
                padding: 6px;
                font-size: 15px;
                outline: none;
            }
            QListWidget::item {
                padding: 10px 12px;
                border-radius: 6px;
                color: #C9D1D9;
                border-left: 3px solid transparent;
                margin-bottom: 2px;
            }
            QListWidget::item:selected {
                background-color: rgba(139, 92, 246, 45);
                color: #FFFFFF;
                border-left: 3px solid #8B5CF6;
            }
            QListWidget::item:hover:!selected {
                background-color: rgba(139, 92, 246, 18);
            }
        """)
        self.template_list.currentRowChanged.connect(self._on_template_row_changed)
        left_layout.addWidget(self.template_list)

        tpl_btns = QHBoxLayout()
        btn_tpl_add = QPushButton("+ Add")
        self._apply_icon(btn_tpl_add, "doc.svg")
        btn_tpl_add.setStyleSheet(_capsule_btn_style)
        btn_tpl_add.setFixedHeight(34)
        btn_tpl_add.clicked.connect(self.add_template_dialog)
        btn_tpl_edit = QPushButton("Edit")
        self._apply_icon(btn_tpl_edit, "doc.svg")
        btn_tpl_edit.setStyleSheet(_capsule_btn_style)
        btn_tpl_edit.setFixedHeight(34)
        btn_tpl_edit.clicked.connect(self.edit_template_dialog)
        tpl_btns.addWidget(btn_tpl_add)
        tpl_btns.addWidget(btn_tpl_edit)
        left_layout.addLayout(tpl_btns)

        left_sep_top = QFrame()
        left_sep_top.setFixedHeight(1)
        left_sep_top.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 transparent, stop:0.3 rgba(88,166,255,60), "
            "stop:0.7 rgba(88,166,255,60), stop:1 transparent); "
            "border: none; margin-top: 6px; margin-bottom: 6px;"
        )
        left_layout.addWidget(left_sep_top)

        btn_guided = QPushButton("✦  Guided Setup")
        btn_guided.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1B7A30, stop:1 #238636);
                border: 1px solid rgba(46, 160, 67, 80);
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2EA043);
                border: 1px solid rgba(63, 185, 80, 120);
            }
        """)
        btn_guided.setFixedHeight(38)
        btn_guided.clicked.connect(self.guided_setup)
        left_layout.addWidget(btn_guided)

        btn_deploy = QPushButton("⚡  Deploy All (Ordered)")
        btn_deploy.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1D4ED8, stop:1 #2563EB);
                border: 1px solid rgba(59, 130, 246, 80);
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #3B82F6);
                border: 1px solid rgba(96, 165, 250, 130);
            }
        """)
        btn_deploy.setFixedHeight(38)
        btn_deploy.clicked.connect(self.deploy_all_ordered)
        left_layout.addWidget(btn_deploy)

        btn_monitor = QPushButton("Monitor Devices")
        btn_monitor.setProperty("outlined", True)
        btn_monitor.clicked.connect(self.open_monitor)
        left_layout.addWidget(btn_monitor)

        btn_subnet = QPushButton("Subnet Calculator")
        btn_subnet.setProperty("outlined", True)
        btn_subnet.clicked.connect(lambda: self._open_subnet_calculator())
        left_layout.addWidget(btn_subnet)

        # Send History button removed — now natively in Logs page

        self.btn_rollback = QPushButton("Rollback Config")
        self.btn_rollback.setProperty("danger", True)
        self.btn_rollback.clicked.connect(self.rollback_device)
        self.btn_rollback.setVisible(False)
        left_layout.addWidget(self.btn_rollback)

        left_sep_bottom = QFrame()
        left_sep_bottom.setFixedHeight(1)
        left_sep_bottom.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 transparent, stop:0.3 rgba(88,166,255,40), "
            "stop:0.7 rgba(88,166,255,40), stop:1 transparent); "
            "border: none; margin-top: 4px; margin-bottom: 4px;"
        )
        left_layout.addWidget(left_sep_bottom)

        left_layout.addStretch()

        # CENTER COLUMN (header outside panel + panel content)
        center_column = QWidget()
        center_column.setAttribute(Qt.WA_TranslucentBackground)
        center_column.setMinimumWidth(560)
        center_column.setMaximumWidth(960)
        center_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_column_layout = QVBoxLayout(center_column)
        center_column_layout.setContentsMargins(0, 0, 0, 0)
        center_column_layout.setSpacing(8)

        center_header = QHBoxLayout()
        lbl_preview = QLabel("Preview")
        lbl_preview.setStyleSheet(
            "color: #F0F2F4; font-size: 26px; font-weight: 800; letter-spacing: 0.5px; "
            "border-bottom: 2px solid qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #3B82F6, stop:1 transparent); padding-bottom: 4px;"
        )
        center_header.addWidget(lbl_preview)
        center_header.addStretch()

        btn_export = QPushButton("Export Project")
        btn_export.setProperty("outlined", True)
        btn_export.setFixedHeight(36)
        btn_export.clicked.connect(self.export_project)
        center_header.addWidget(btn_export)

        btn_import = QPushButton("Import Project")
        btn_import.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3574C4, stop:1 #408CDB);
                border: 1px solid rgba(88, 166, 255, 60);
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #408CDB, stop:1 #58A6FF);
                border: 1px solid rgba(88, 166, 255, 130);
            }
        """)
        btn_import.setFixedHeight(36)
        btn_import.clicked.connect(self.import_project)
        center_header.addWidget(btn_import)
        center_column_layout.addLayout(center_header)

        center_panel = QFrame()
        center_panel.setProperty("glassPanel", True)
        center_panel.setMinimumHeight(470)
        center_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(14, 12, 14, 14)
        center_layout.setSpacing(10)

        center_tabs = QHBoxLayout()
        center_tabs.setSpacing(8)
        center_tabs.setContentsMargins(0, 0, 0, 2)
        btn_cfg_tab = QPushButton("Config Preview")
        btn_cfg_tab.setProperty("previewTab", "active")
        btn_cfg_tab.setFocusPolicy(Qt.NoFocus)
        btn_cfg_tab.setFixedHeight(32)
        center_tabs.addWidget(btn_cfg_tab)

        btn_topo_tab = QPushButton("GNS3 Topology View")
        btn_topo_tab.setProperty("previewTab", "inactive")
        btn_topo_tab.setFocusPolicy(Qt.NoFocus)
        btn_topo_tab.setFixedHeight(32)
        btn_topo_tab.clicked.connect(self.open_topology)
        center_tabs.addWidget(btn_topo_tab)
        center_tabs.addStretch()
        center_layout.addLayout(center_tabs)

        self.preview = QPlainTextEdit()
        self.preview.setPlaceholderText("Configuration preview will appear here...")
        self.preview.setFixedHeight(350)
        center_layout.addWidget(self.preview)

        center_bottom = QHBoxLayout()
        btn_generate = QPushButton("⚙  Generate")
        btn_generate.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #4F46E5);
                border: 1px solid rgba(99, 102, 241, 80);
                border-radius: 21px;
                color: #FFFFFF;
                font-size: 16px;
                font-weight: bold;
                padding: 0 28px;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #6366F1);
                border: 1px solid rgba(147, 197, 253, 130);
            }
        """)
        btn_generate.setFixedHeight(42)
        btn_generate.clicked.connect(self.generate_full)
        center_bottom.addWidget(btn_generate)
        center_bottom.addStretch()
        btn_clear = QPushButton("Clear Preview")
        btn_clear.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #9CA3AF;
                border: 1px solid rgba(156, 163, 175, 60);
                border-radius: 21px;
                font-size: 14px;
                padding: 0 20px;
            }
            QPushButton:hover {
                color: #F87171;
                border: 1px solid rgba(248, 113, 113, 100);
                background-color: rgba(248, 113, 113, 10);
            }
        """)
        btn_clear.setFixedHeight(42)
        btn_clear.clicked.connect(self.clear_preview)
        center_bottom.addWidget(btn_clear)
        center_layout.addLayout(center_bottom)
        center_column_layout.addWidget(center_panel)

        # RIGHT PANEL (~1/5 width, fixed)
        self.right_panel = QFrame()
        self.right_panel.setProperty("glassPanel", True)
        self.right_panel.setObjectName("rightPanel")
        self.right_panel.setAutoFillBackground(True)
        self.right_panel.setStyleSheet("""
            QFrame#rightPanel {
                background-color: rgba(11, 29, 50, 110);
                border-radius: 12px;
                border: 1px solid rgba(50, 85, 160, 65);
            }
        """)
        self.right_panel.setMinimumWidth(340)
        right_scroll = QScrollArea()
        right_scroll.setWidget(self.right_panel)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setStyleSheet("background: transparent;")
        right_scroll.setFixedWidth(350)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(10)

        # Import & Discovery section
        lbl_gns3 = QLabel("  Discovery & Import")
        lbl_gns3.setStyleSheet(
            "color: #F0F2F4; font-size: 18px; font-weight: 700; "
            "border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F59E0B, stop:1 #D97706); "
            "padding-left: 10px; padding-top: 2px; padding-bottom: 2px; margin-bottom: 4px;"
        )
        right_layout.addWidget(lbl_gns3)

        gns3_row = QHBoxLayout()
        self.lbl_gns3_project_name = QLabel("No project")
        self.lbl_gns3_project_name.setStyleSheet("color: #8B949E; font-size: 13px;")
        gns3_row.addWidget(self.lbl_gns3_project_name, 1)
        self.lbl_gns3_status = QLabel("Click Import")
        self.lbl_gns3_status.setStyleSheet(
            "color: #D1D7E0; background-color: rgba(18,34,56,210); "
            "border: 1px solid rgba(76,137,219,70); border-radius: 7px; "
            "padding: 5px 11px; font-size: 13px;")
        gns3_row.addWidget(self.lbl_gns3_status)
        right_layout.addLayout(gns3_row)

        gns3_btns = QGridLayout()
        gns3_btns.setHorizontalSpacing(6)
        gns3_btns.setVerticalSpacing(6)
        btn_gns3_import = QPushButton("Import")
        btn_gns3_import.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3574C4, stop:1 #408CDB);
                border: 1px solid rgba(88, 166, 255, 60);
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #408CDB, stop:1 #58A6FF);
                border: 1px solid rgba(88, 166, 255, 130);
            }
        """)
        btn_gns3_import.setFixedHeight(32)
        btn_gns3_import.clicked.connect(self.gns3_list_projects)
        
        btn_gns3_refresh = QPushButton("Refresh")
        btn_gns3_refresh.setStyleSheet("""
            QPushButton {
                background-color: rgba(50, 66, 85, 220);
                border: 1px solid rgba(100, 130, 170, 50);
                border-radius: 8px;
                color: #C9D1D9;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: rgba(65, 85, 110, 240);
                border: 1px solid rgba(88, 166, 255, 100);
                color: #FFFFFF;
            }
        """)
        btn_gns3_refresh.setFixedHeight(32)
        btn_gns3_refresh.clicked.connect(self.refresh_gns3_connection)
        
        btn_physical_discovery = QPushButton("Add Physical")
        btn_physical_discovery.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1B7A30, stop:1 #238636);
                border: 1px solid rgba(46, 160, 67, 60);
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2EA043);
                border: 1px solid rgba(63, 185, 80, 100);
            }
        """)
        btn_physical_discovery.setFixedHeight(32)
        btn_physical_discovery.clicked.connect(self.show_physical_discovery)
        
        btn_network_rescan = QPushButton("Rescan Networks")
        btn_network_rescan.setStyleSheet("""
            QPushButton {
                background-color: rgba(25, 50, 40, 200);
                border: 1px solid rgba(100, 200, 130, 45);
                border-radius: 8px;
                color: #86EFAC;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: rgba(35, 70, 50, 230);
                border: 1px solid rgba(134, 239, 172, 80);
            }
        """)
        btn_network_rescan.setFixedHeight(32)
        btn_network_rescan.clicked.connect(self._assign_network_ids)
        gns3_btns.addWidget(btn_gns3_import, 0, 0)
        gns3_btns.addWidget(btn_physical_discovery, 0, 1)
        gns3_btns.addWidget(btn_gns3_refresh, 1, 0)
        gns3_btns.addWidget(btn_network_rescan, 1, 1)
        right_layout.addLayout(gns3_btns)

        right_sep_top = QFrame()
        right_sep_top.setFixedHeight(1)
        right_sep_top.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 transparent, stop:0.3 rgba(88,166,255,50), "
            "stop:0.7 rgba(88,166,255,50), stop:1 transparent); "
            "border: none; margin-top: 6px; margin-bottom: 6px;"
        )
        right_layout.addWidget(right_sep_top)

        # Send / Connect section
        lbl_send = QLabel("  Send / Connect")
        lbl_send.setStyleSheet(
            "color: #F0F2F4; font-size: 18px; font-weight: 700; "
            "border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3B82F6, stop:1 #2563EB); "
            "padding-left: 10px; padding-top: 2px; padding-bottom: 2px; margin-bottom: 4px;"
        )
        right_layout.addWidget(lbl_send)

        self.send_method = QComboBox()
        self.send_method.addItems(["Telnet", "Serial", "SSH"])
        self.send_method.currentTextChanged.connect(self._on_protocol_changed)
        self.send_method.currentTextChanged.connect(lambda _: self._update_send_button_state())
        right_layout.addWidget(self.send_method)

        # Serial fields
        self.lbl_serial_title = QLabel("Serial")
        self.lbl_serial_title.setStyleSheet("color: #C9D1D9; font-size: 15px; font-weight: 700;")
        right_layout.addWidget(self.lbl_serial_title)
        self.ent_serial_port = QLineEdit()
        self.ent_serial_port.setPlaceholderText("COM3 or /dev/ttyUSB0")
        self.ent_serial_port.setAccessibleName("Serial Port")
        self.ent_serial_port.textChanged.connect(lambda _: self._update_send_button_state())
        right_layout.addWidget(self.ent_serial_port)
        self.ent_serial_baud = QLineEdit()
        self.ent_serial_baud.setPlaceholderText("9600")
        self.ent_serial_baud.setAccessibleName("Serial Baud")
        self.ent_serial_baud.textChanged.connect(lambda _: self._update_send_button_state())
        right_layout.addWidget(self.ent_serial_baud)

        # Network fields
        self.lbl_network_title = QLabel("Network")
        self.lbl_network_title.setStyleSheet("color: #C9D1D9; font-size: 15px; font-weight: 700;")
        right_layout.addWidget(self.lbl_network_title)
        self.ent_host = QLineEdit()
        self.ent_host.setPlaceholderText("Host or IP")
        self.ent_host.setAccessibleName("Host or IP")
        self.ent_host.textChanged.connect(lambda _: self._update_send_button_state())
        right_layout.addWidget(self.ent_host)
        self.ent_port = QLineEdit()
        self.ent_port.setPlaceholderText("Port")
        self.ent_port.setAccessibleName("Port")
        self.ent_port.textChanged.connect(lambda _: self._update_send_button_state())
        right_layout.addWidget(self.ent_port)
        self.ent_user = QLineEdit()
        self.ent_user.setPlaceholderText("Username")
        self.ent_user.setAccessibleName("Username")
        self.ent_user.textChanged.connect(lambda _: self._update_send_button_state())
        right_layout.addWidget(self.ent_user)
        self.ent_pass = QLineEdit()
        self.ent_pass.setPlaceholderText("Password")
        self.ent_pass.setEchoMode(QLineEdit.Password)
        self.ent_pass.setAccessibleName("Password")
        self.ent_pass.textChanged.connect(lambda _: self._update_send_button_state())
        right_layout.addWidget(self.ent_pass)

        lbl_optional = QLabel("Optional")
        lbl_optional.setStyleSheet("color: #9BA3AF; font-size: 13px;")
        right_layout.addWidget(lbl_optional)
        enable_row = QHBoxLayout()
        self.ent_enable = QLineEdit()
        self.ent_enable.setPlaceholderText("Enable Password")
        self.ent_enable.setAccessibleName("Enable Password")
        self.enable_checkbox = QCheckBox()
        enable_row.addWidget(self.ent_enable, 1)
        enable_row.addWidget(self.enable_checkbox)
        right_layout.addLayout(enable_row)

        for _le in (
            self.ent_serial_port,
            self.ent_serial_baud,
            self.ent_host,
            self.ent_port,
            self.ent_user,
            self.ent_pass,
            self.ent_enable,
        ):
            _le.returnPressed.connect(self._on_connection_field_return)

        self.btn_send = QPushButton("➤  Send")
        self.btn_send.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1D4ED8, stop:1 #2563EB);
                border: 1px solid rgba(59, 130, 246, 80);
                border-radius: 21px;
                color: #FFFFFF;
                font-size: 16px;
                font-weight: bold;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #3B82F6);
                border: 1px solid rgba(96, 165, 250, 140);
            }
            QPushButton:disabled {
                background: rgba(35, 42, 52, 180);
                color: #4A5568;
                border: 1px solid rgba(80, 100, 130, 40);
            }
        """)
        self.btn_send.setFixedHeight(42)
        self._apply_icon(self.btn_send, "router.svg")
        self.btn_send.clicked.connect(self.send_now)
        
        # New Premium AI Sparkle Button 
        send_row = QHBoxLayout()
        send_row.setSpacing(10)
        self.btn_ai = QPushButton("")
        self._apply_icon(self.btn_ai, "ai_sparkle.svg")
        self.btn_ai.setToolTip("AI Troubleshoot")
        self.btn_ai.setFixedSize(42, 42)
        self.btn_ai.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 #18112C, stop: 1 #2E1668);
                border: 1px solid #5a3a91;
                border-radius: 21px;
            }
            QPushButton:hover { 
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 #2a145e, stop: 1 #4A24A6); 
                border: 1px solid #a371f7;
            }
            QPushButton:pressed {
                background: #18112C;
                border: 1px solid #4A24A6;
            }
        """)
        self.btn_ai.clicked.connect(self.invoke_ai_agent)
        
        send_row.addWidget(self.btn_send, 1)
        send_row.addWidget(self.btn_ai, 0)
        right_layout.addLayout(send_row)

        _ghost_btn_style = """
            QPushButton {
                background-color: transparent;
                border: 1px solid rgba(88, 166, 255, 90);
                border-radius: 8px;
                color: #7CB8F0;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(88, 166, 255, 16);
                border: 1px solid rgba(88, 166, 255, 160);
                color: #93C5FD;
            }
        """
        btn_save_creds = QPushButton("Save Credentials")
        btn_save_creds.setStyleSheet(_ghost_btn_style)
        btn_save_creds.setFixedHeight(34)
        btn_save_creds.clicked.connect(self.save_credentials)
        right_layout.addWidget(btn_save_creds)

        btn_terminal = QPushButton("Open Terminal")
        btn_terminal.setStyleSheet(_ghost_btn_style)
        btn_terminal.setFixedHeight(34)
        btn_terminal.clicked.connect(self.open_terminal)
        right_layout.addWidget(btn_terminal)

        right_layout.addStretch()

        self.serial_widgets = [self.lbl_serial_title, self.ent_serial_port, self.ent_serial_baud]
        self.network_widgets = [self.lbl_network_title, self.ent_host, self.ent_port,
                                self.ent_user, self.ent_pass, self.ent_enable, self.enable_checkbox]
        self._on_protocol_changed("Telnet")
        self.preview.textChanged.connect(self._update_send_button_state)
        self._update_send_button_state()

        # Layout: left | gap | center (preview) | gap | right — gaps between panels, center widest
        main_layout.addStretch(1)
        main_layout.addWidget(left_scroll)
        main_layout.addSpacing(18)
        main_layout.addWidget(center_column, 2, Qt.AlignTop)
        main_layout.addSpacing(18)
        main_layout.addWidget(right_scroll)
        main_layout.addStretch(1)

        self._stack.addWidget(main_page)

        # --- Logs page ---
        logs_page = QWidget()
        logs_page.setAttribute(Qt.WA_TranslucentBackground)
        logs_layout = QVBoxLayout(logs_page)
        logs_layout.setContentsMargins(20, 20, 20, 20)

        logs_panel = QFrame()
        logs_panel.setProperty("glassPanel", True)
        logs_inner = QVBoxLayout(logs_panel)
        logs_inner.setContentsMargins(20, 20, 20, 20)
        logs_inner.setSpacing(14)

        logs_top = QHBoxLayout()
        lbl_logs_title = QLabel("Logs")
        lbl_logs_title.setStyleSheet("color: #C9D1D9; font-size: 24px; font-weight: 700;")
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
        lbl_hist.setStyleSheet("color: #9ca3af; font-size: 15px; font-weight: bold;")
        logs_inner.addWidget(lbl_hist)

        self.logs_history_table = QTableWidget(0, 5)
        self.logs_history_table.setHorizontalHeaderLabels(["ID", "Device", "Action", "Details", "Time"])
        self.logs_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.logs_history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.logs_history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.logs_history_table.itemDoubleClicked.connect(self._view_log_snapshot)
        logs_inner.addWidget(self.logs_history_table)

        lbl_live = QLabel("Live output")
        lbl_live.setStyleSheet("color: #9ca3af; font-size: 15px; font-weight: bold;")
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

        # Hide native menu bar (custom title bar + in-panel controls handle GNS3 actions).
        self.menuBar().setVisible(False)

        act_generate = QAction("Generate", self)
        act_generate.setShortcut("Ctrl+Return")
        act_generate.triggered.connect(self.generate_full)
        self.addAction(act_generate)

        act_send = QAction("Send", self)
        act_send.setShortcut("Ctrl+Shift+Return")
        act_send.triggered.connect(self.send_now)
        self.addAction(act_send)

        act_main_tab = QAction("Switch to Main", self)
        act_main_tab.setShortcut("Ctrl+1")
        act_main_tab.triggered.connect(lambda: self._switch_tab("main"))
        self.addAction(act_main_tab)

        act_logs_tab = QAction("Switch to Logs", self)
        act_logs_tab.setShortcut("Ctrl+2")
        act_logs_tab.triggered.connect(lambda: self._switch_tab("logs"))
        self.addAction(act_logs_tab)

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
        old_idx = self._stack.currentIndex()
        new_idx = 0 if tab == "main" else 1

        if tab == "main":
            self.btn_main_nav.setProperty("navTab", "active")
            self.btn_logs_nav.setProperty("navTab", "inactive")
        else:
            self.btn_main_nav.setProperty("navTab", "inactive")
            self.btn_logs_nav.setProperty("navTab", "active")
            self._refresh_logs_history()

        self.btn_main_nav.style().unpolish(self.btn_main_nav)
        self.btn_main_nav.style().polish(self.btn_main_nav)
        self.btn_logs_nav.style().unpolish(self.btn_logs_nav)
        self.btn_logs_nav.style().polish(self.btn_logs_nav)

        # ── Animated slide transition ────────────────────────────────
        if old_idx == new_idx or self._tab_animating:
            self._stack.setCurrentIndex(new_idx)
            return

        self._tab_animating = True
        incoming = self._stack.widget(new_idx)
        outgoing = self._stack.widget(old_idx)
        direction = 1 if new_idx > old_idx else -1  # slide left or right
        width = self._stack.width()

        # Set up the incoming widget off-screen
        self._stack.setCurrentIndex(new_idx)
        incoming.setGeometry(direction * width, 0, width, self._stack.height())
        outgoing.show()  # keep it visible during animation
        outgoing.raise_()

        # Animate outgoing sliding out
        anim_out = QPropertyAnimation(outgoing, b"pos")
        anim_out.setDuration(280)
        anim_out.setStartValue(outgoing.pos())
        anim_out.setEndValue(QPoint(-direction * width, 0))
        anim_out.setEasingCurve(QEasingCurve.InOutCubic)

        # Animate incoming sliding in
        anim_in = QPropertyAnimation(incoming, b"pos")
        anim_in.setDuration(280)
        anim_in.setStartValue(QPoint(direction * width, 0))
        anim_in.setEndValue(QPoint(0, 0))
        anim_in.setEasingCurve(QEasingCurve.InOutCubic)

        self._tab_group = QParallelAnimationGroup()
        self._tab_group.addAnimation(anim_out)
        self._tab_group.addAnimation(anim_in)

        def on_finished():
            self._tab_animating = False
            outgoing.hide()
            incoming.setGeometry(0, 0, width, self._stack.height())

        self._tab_group.finished.connect(on_finished)
        self._tab_group.start()

    # ── Thread-safe UI helpers (replaces self.after) ────────────────────

    def _execute_main_thread_call(self, func):
        func()

    def show_physical_discovery(self):
        """Shows the physical subnet/CDP discovery dialog and ingests findings."""
        dlg = PhysicalDiscoveryDialog(self)
        dlg.discovery_complete.connect(self._ingest_physical_devices)
        dlg.exec()

    def _ingest_physical_devices(self, found_devices):
        """Ingests list of {'name':..., 'ip':..., 'port':..., 'protocol':..., 'type':...}"""
        self._safe_bg_log(f"Importing {len(found_devices)} physical devices...")
        
        imported_count = 0
        assigned = set([dev.name for _, dev, _ in self.devices])
        
        for p_dev in found_devices:
            name = p_dev.get("name")
            dev_type = p_dev.get("type", "router")
            if not name or name in assigned:
                import uuid
                name = f"{name or 'Node'}-{str(uuid.uuid4())[:4]}"
            
            ModelClass = self.device_types.get(dev_type.lower(), DeviceModel)
            model = ModelClass(name)
            meta = {
                "ip": p_dev.get("ip"),
                "port": p_dev.get("port"),
                "protocol": p_dev.get("protocol"),
                "is_physical": True,
                "type": dev_type
            }
            imported_count += 1
            self.devices.append((name, model, meta))
            assigned.add(name)

        if imported_count > 0:
            # Trigger UI update
            self.lbl_gns3_project_name.setText(f"Physical/GNS3 Mixed")
            self.lbl_gns3_status.setText(f"Active")
            self.lbl_gns3_status.setStyleSheet(
                "color: #7EE787; background-color: rgba(30,56,36,210); "
                "border: 1px solid rgba(86,211,100,70); border-radius: 7px; "
                "padding: 5px 11px; font-weight: bold; font-size: 13px;"
            )
            QTimer.singleShot(0, self.update_device_list)
            QMessageBox.information(self, "Physical Discovery", f"Successfully imported {imported_count} devices from the physical network.")

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
        
        # Avoid duplicate additions to the in-memory list
        if not any(d[0] == name for d in self.devices):
            self.devices.append((name, obj, metadata))
            
        # Automatically insert/update the device in the SQLite database to keep DB in sync
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        ip = metadata.get("ip", metadata.get("console_host", ""))
        port = str(metadata.get("port", metadata.get("console_port", "")))
        conn_type = "gns3-console" if metadata.get("gns3_node") else "manual"
        added_gns3 = 1 if metadata.get("gns3_node") else 0
        proj_id = metadata.get("project_id", "")
        node_id = metadata.get("node_id", "")
        
        try:
            with db_lock:
                cur.execute(
                    "INSERT OR REPLACE INTO devices (name, type, ip, port, connection_type, added_from_gns3, project_id, node_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, type_key, ip, port, conn_type, added_gns3, proj_id, node_id, ts)
                )
                conn.commit()
        except Exception as e:
            self.log(f"[db] error auto-syncing added device '{name}': {e}")

    def refresh_device_list(self):
        self.device_list.blockSignals(True)
        self.device_list.clear()
        self.selected_device_name = None
        for idx, (n, obj, meta) in enumerate(self.devices):
            icon_name = ""
            if isinstance(obj, RouterModel):
                icon_name = "router.svg"
            elif isinstance(obj, CoreSwitchModel):
                icon_name = "layer-3-switch.svg"
            elif isinstance(obj, SwitchModel):
                icon_name = "workgroup-switch.svg"
            else:
                icon_name = "router.svg"
            label = f"{n} ({obj.__class__.__name__})"
            if meta.get("gns3_node"):
                label += " [gns3]"
            net_id = meta.get("network_id")
            if net_id and net_id != "default":
                label += f" [{net_id}]"
            item = QListWidgetItem(label)
            icon = self._icon(icon_name)
            if not icon.isNull():
                item.setIcon(icon)
            self.device_list.addItem(item)
        self.device_list.blockSignals(False)
        if self.device_list.count() > 0:
            self.device_list.setCurrentRow(0)

    def _device_list_context_menu(self, pos):
        item = self.device_list.itemAt(pos)
        if not item:
            return
        row = self.device_list.row(item)
        if row < 0 or row >= len(self.devices):
            return
        
        menu = QMenu(self)
        assign_menu = menu.addMenu("Assign to Network...")
        
        existing_nets = set()
        for _, _, m in self.devices:
            net = m.get("network_id")
            if net and net != "default":
                existing_nets.add(net)
        
        for net in sorted(existing_nets):
            action = QAction(net, self)
            action.triggered.connect(lambda checked, n=net, r=row: self._assign_user_network(r, n))
            assign_menu.addAction(action)
            
        assign_menu.addSeparator()
        new_action = QAction("New Network...", self)
        new_action.triggered.connect(lambda checked, r=row: self._assign_new_network(r))
        assign_menu.addAction(new_action)
        
        menu.exec(self.device_list.mapToGlobal(pos))
        
    def _assign_user_network(self, row, net_id):
        dname, model, meta = self.devices[row]
        meta["network_id"] = net_id
        self.refresh_device_list()
        
    def _assign_new_network(self, row):
        name, ok = QInputDialog.getText(self, "New Network", "Enter network name:")
        if ok and name.strip():
            self._assign_user_network(row, name.strip())

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

    def _clear_all_devices_from_db(self):
        """Purge leftover devices, configs, and credentials from the database to avoid ghost/old devices."""
        try:
            with db_lock:
                cur.execute("DELETE FROM configs")
                cur.execute("DELETE FROM credentials")
                cur.execute("DELETE FROM devices")
                conn.commit()
            self.log("[db] Cleared leftover devices, configs, and credentials from SQLite database.")
        except Exception as e:
            self.log(f"[db] error clearing database: {e}")

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
            # Clean up device and its configs from SQLite database
            try:
                with db_lock:
                    cur.execute("DELETE FROM configs WHERE device_id = (SELECT id FROM devices WHERE name = ?)", (name,))
                    cur.execute("DELETE FROM credentials WHERE device_name = ?", (name,))
                    cur.execute("DELETE FROM devices WHERE name = ?", (name,))
                    conn.commit()
                self.log(f"[db] Manually removed device '{name}' and its configs from database.")
            except Exception as e:
                self.log(f"[db] error deleting device '{name}': {e}")
            del self.devices[idx]
            self.refresh_device_list()

    def _on_device_row_changed(self, row):
        if row < 0 or row >= len(self.devices):
            return
        dname, model, meta = self.devices[row]
        self.selected_device_name = dname
        self.current_device = (dname, model, meta)
        self._refresh_template_list()
        self._load_credentials(dname)
        if meta.get("gns3_node"):
            host = meta.get("console_host", "localhost")
            port = str(meta.get("console_port", ""))
            self.ent_host.setText(host)
            self.ent_port.setText(port)
            self.send_method.setCurrentText("Telnet")
            self._on_protocol_changed("Telnet")
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
        self._update_send_button_state()

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
        self._set_status_message("Config generated", 2500)

    def clear_preview(self):
        self._run_on_main(lambda: self.preview.setPlainText(""))

    # ── Logging ─────────────────────────────────────────────────────────

    def log(self, msg):
        def _do():
            ts = time.strftime("%H:%M:%S")
            if hasattr(self, "txt_logs") and self.txt_logs is not None:
                self.txt_logs.appendPlainText(f"[{ts}] {msg}")
            else:
                print(f"[{ts}] {msg}")
        self._run_on_main(_do)

    def _refresh_logs_history(self):
        try:
            device_filter = self.logs_device_var.currentText()
            if device_filter == "All":
                cur.execute(
                    "SELECT id, device_name, action, details, timestamp FROM logs ORDER BY id DESC LIMIT 200")
            else:
                cur.execute(
                    "SELECT id, device_name, action, details, timestamp FROM logs "
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

    def _view_log_snapshot(self, item):
        row = item.row()
        log_id = self.logs_history_table.item(row, 0).text()
        try:
            with db_lock:
                cur.execute("SELECT config_snapshot FROM logs WHERE id=?", (log_id,))
                row_data = cur.fetchone()
            if row_data and row_data[0]:
                snap = row_data[0]
                dlg = QDialog(self)
                dlg.setWindowTitle("Sent Configuration Snapshot")
                dlg.resize(800, 600)
                dlg.setStyleSheet(self._dialog_style())
                layout = QVBoxLayout(dlg)
                
                title = QLabel(f"Configuration Payload (Log ID: {log_id})")
                title.setStyleSheet("font-size: 16px; font-weight: bold; color: #E6EDF3;")
                layout.addWidget(title)
                
                txt = QPlainTextEdit(snap)
                txt.setReadOnly(True)
                layout.addWidget(txt)
                
                btn = QPushButton("Close")
                btn.setFixedHeight(36)
                btn.setFixedWidth(120)
                btn.setStyleSheet("""
                    QPushButton { background-color: #21262D; border: 1px solid #30363D; border-radius: 6px; color: #C9D1D9; }
                    QPushButton:hover { background-color: #30363D; border-color: #8B949E; }
                """)
                btn.clicked.connect(dlg.accept)
                layout.addWidget(btn, alignment=Qt.AlignRight)
                
                dlg.exec()
            else:
                QMessageBox.information(self, "No Snapshot", "No configuration payload was stored for this log entry.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load snapshot: {e}")

    # ── Send / Deploy ───────────────────────────────────────────────────

    def _resolve_copilot_connection(self, preferred_name: Optional[str] = None) -> dict:
        """
        Resolve console host/port/credentials for Copilot from DB + device metadata.
        Returns: device_name, host, port, user, password, enable_password, protocol
        """
        out = {
            "device_name": None,
            "host": "",
            "port": 23,
            "user": "",
            "password": "",
            "enable_password": "",
            "protocol": "telnet",
        }
        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

        candidates: list[str] = []
        if preferred_name and str(preferred_name).strip():
            candidates.append(str(preferred_name).strip())
        last = cfg.get("last_copilot_device")
        if last and last not in candidates:
            candidates.append(last)
        if self.current_device and self.current_device[0] not in candidates:
            candidates.append(self.current_device[0])
        for n, _, _ in self.devices:
            if n not in candidates:
                candidates.append(n)
        if not candidates:
            try:
                with db_lock:
                    cur.execute("SELECT name FROM devices ORDER BY name")
                    for (n,) in cur.fetchall():
                        if n and n not in candidates:
                            candidates.append(n)
            except Exception:
                pass

        def _meta_for(name: str) -> dict:
            for n, _, meta in self.devices:
                if n == name:
                    return meta or {}
            return {}

        for name in candidates:
            meta = _meta_for(name)
            dip, dport = "", ""
            crow = None
            try:
                with db_lock:
                    cur.execute(
                        "SELECT ip, port FROM devices WHERE name=?",
                        (name,),
                    )
                    row = cur.fetchone()
                    if row:
                        dip = (row[0] or "").strip()
                        dport = str(row[1] or "").strip()
                    cur.execute(
                        "SELECT host, port, username, password, enable_password, protocol "
                        "FROM credentials WHERE device_name=?",
                        (name,),
                    )
                    crow = cur.fetchone()
            except Exception:
                crow = None

            host = ""
            port_str = ""
            user = ""
            pw = ""
            enable = ""
            protocol = "telnet"

            if crow:
                ch, cp, cu, cpw, ce, cprot = crow
                host = (ch or "").strip()
                port_str = str(cp or "").strip()
                user = (cu or "").strip()
                pw = _deobfuscate(cpw or "")
                enable = _deobfuscate(ce or "")
                if cprot and str(cprot).lower() in ("telnet", "ssh", "serial"):
                    protocol = str(cprot).lower()

            if meta.get("gns3_node"):
                # GNS3 console ports change on every project restart —
                # ALWAYS prefer the live metadata over stale credentials.
                gns3_host = (meta.get("console_host") or "").strip()
                gns3_port = str(meta.get("console_port") or "").strip()
                if gns3_host:
                    host = gns3_host
                if gns3_port:
                    port_str = gns3_port

            if not host and dip:
                host = dip
            if not port_str and dport:
                port_str = dport

            if not host:
                continue

            try:
                port_int = int(port_str) if str(port_str).isdigit() else 23
            except Exception:
                port_int = 23

            out["device_name"] = name
            out["host"] = host
            out["port"] = port_int
            out["user"] = user
            out["password"] = pw
            out["enable_password"] = enable
            out["protocol"] = protocol
            return out

        return out

    def _build_copilot_snapshot(self) -> str:
        """Build a comprehensive JSON snapshot of the entire project for the AI agent.

        Contains every device, its role, all generated IOS configs (templates),
        deploy history, and GNS3 console info — so the agent starts fully aware.
        """
        from network_manager.models.devices import RouterModel, CoreSwitchModel, SwitchModel
        snapshot = {"devices": [], "gns3_project": "", "total_devices": 0,
                    "configured_count": 0, "deployed_count": 0}

        # GNS3 project name
        gns3_name = getattr(self, "_gns3_project_name", "") or ""
        if not gns3_name:
            try:
                lbl = getattr(self, "lbl_gns3_project_name", None)
                if lbl:
                    gns3_name = lbl.text() or ""
            except Exception:
                pass
        snapshot["gns3_project"] = gns3_name

        for name, model, meta in self.devices:
            # Determine role
            if isinstance(model, RouterModel):
                role = "router"
            elif isinstance(model, CoreSwitchModel):
                role = "core"
            elif isinstance(model, SwitchModel):
                role = "access"
            else:
                role = "unknown"

            # Templates (actual IOS config text)
            templates = {}
            for tname, ttext in model.templates.items():
                if ttext and ttext.strip():
                    templates[tname] = ttext.strip()

            has_config = bool(templates)

            # Deploy history from audit DB
            deployed = False
            deploy_time = ""
            deploy_method = ""
            try:
                from network_manager.config import cur, db_lock
                with db_lock:
                    cur.execute(
                        "SELECT action, details, created_at FROM logs "
                        "WHERE action LIKE ? ORDER BY created_at DESC LIMIT 1",
                        (f"%{name}%",)
                    )
                    row = cur.fetchone()
                    if row and ("send" in (row[0] or "").lower() or "deploy" in (row[0] or "").lower()):
                        deployed = True
                        deploy_time = row[2] or ""
                        deploy_method = "telnet"  # default
                        if "ssh" in (row[1] or "").lower():
                            deploy_method = "ssh"
                        elif "serial" in (row[1] or "").lower():
                            deploy_method = "serial"
            except Exception:
                pass

            # GNS3 console info
            console = ""
            if meta.get("console_host") and meta.get("console_port"):
                console = f"{meta['console_host']}:{meta['console_port']}"

            dev_entry = {
                "name": name,
                "type": model.__class__.__name__,
                "role": role,
                "templates": templates,
                "has_config": has_config,
                "deployed": deployed,
            }
            if deploy_time:
                dev_entry["deploy_time"] = deploy_time
                dev_entry["deploy_method"] = deploy_method
            if console:
                dev_entry["gns3_console"] = console
            if meta.get("interfaces"):
                dev_entry["interfaces"] = meta["interfaces"]

            snapshot["devices"].append(dev_entry)
            if has_config:
                snapshot["configured_count"] += 1
            if deployed:
                snapshot["deployed_count"] += 1

        snapshot["total_devices"] = len(self.devices)
        return json.dumps(snapshot, indent=2)

    def _copilot_workspace_resolved(self) -> list[dict]:
        """Resolved connection dicts for every workspace device that has a host."""
        found: list[dict] = []
        seen = set()
        for n, _, _ in self.devices:
            if n in seen:
                continue
            seen.add(n)
            r = self._resolve_copilot_connection(n)
            if r.get("host"):
                found.append(dict(r))
        return found

    def invoke_ai_agent(self):
        """Triggered by the AI ✨ button — opens the Copilot interactive chat dialog."""
        if getattr(self, "_copilot_dlg", None) is not None:
            self._copilot_dlg.show()
            self._copilot_dlg.raise_()
            self._copilot_dlg.activateWindow()
            return

        from network_manager.gui.agent_dialog import ANCSAgentDialog

        # Ensure state attributes exist on MainWindow
        if not hasattr(self, "_copilot_history"):
            self._copilot_history = []
        if not hasattr(self, "_copilot_worker"):
            self._copilot_worker = None
        if not hasattr(self, "_copilot_chat_data"):
            self._copilot_chat_data = []

        dlg = ANCSAgentDialog(self)
        self._copilot_dlg = dlg
        dlg.show()


    def _set_send_busy(self, busy: bool):
        self._send_in_progress = busy
        try:
            self.btn_send.setEnabled(not busy)
            self.btn_send.setText("Sending\u2026" if busy else "Send")
            self.btn_send.setToolTip("" if not busy else "Sending configuration")
            if not busy:
                self._update_send_button_state()
            self._set_status_message("Sending configuration..." if busy else "Ready", 0 if busy else 2500)
        except Exception:
            pass

    def _on_connection_field_return(self):
        if self._send_in_progress:
            return
        if self.btn_send.isEnabled():
            self.send_now()

    def send_now(self):
        dlg = ActionConfirmDialog(self, "Send Configuration",
                                  "Are you sure you want to push this configuration to the device?\n\nThis will apply changes instantly.",
                                  "Send Config")
        if dlg.exec() != QDialog.Accepted:
            return
            
        content = self.preview.toPlainText().strip()
        ok, reason = self._validate_send_inputs()
        if not ok:
            QMessageBox.information(self, "Send", reason)
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
            if not host and self.current_device and self.current_device[2].get("gns3_node"):
                host = self.current_device[2].get("console_host", "")
            if not host:
                self._set_send_busy(False)
                QMessageBox.critical(self, "Error", "Enter host")
                return
            try:
                port_raw = self.ent_port.text().strip()
                if not port_raw and self.current_device and self.current_device[2].get("console_port"):
                    port_raw = str(self.current_device[2]["console_port"])
                port = int(port_raw or "23")
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
            if not host and self.current_device and self.current_device[2].get("gns3_node"):
                host = self.current_device[2].get("console_host", "")
            if not host:
                self._set_send_busy(False)
                QMessageBox.critical(self, "Error", "Enter host")
                return
            try:
                port_raw = self.ent_port.text().strip()
                if not port_raw and self.current_device and self.current_device[2].get("console_port"):
                    port_raw = str(self.current_device[2]["console_port"])
                port = int(port_raw or "22")
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
                self._run_on_main(lambda: self._set_status_message("Serial send completed", 3500))
            else:
                self._run_on_main(lambda: self._set_status_message("Serial send failed", 3500))
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
                self._run_on_main(lambda: self._set_status_message("Telnet send completed", 3500))
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
            else:
                self._run_on_main(lambda: self._set_status_message("Telnet send failed", 3500))
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
                self._run_on_main(lambda: self._set_status_message("SSH send completed", 3500))
            else:
                self._run_on_main(lambda: self._set_status_message("SSH send failed", 3500))
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
                font-size: 14px;
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
                font-size: 14px;
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
        filepath = self._get_export_path()
        if not filepath:
            return
        try:
            export_data = {"version": "1.0", "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"), "devices": [], "audit_logs": []}
            type_map = {"RouterModel": "router", "SwitchModel": "switch", "CoreSwitchModel": "core switch"}
            exported_names = []
            for name, model, meta in self.devices:
                type_key = type_map.get(model.__class__.__name__, "router")
                safe_meta = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, list, type(None)))}
                export_data["devices"].append({"name": name, "type_key": type_key, "metadata": safe_meta, "templates": dict(model.templates)})
                exported_names.append(name)
                
            if exported_names:
                try:
                    from network_manager.config import cur, db_lock
                    with db_lock:
                        placeholders = ",".join("?" * len(exported_names))
                        cur.execute(
                            f"SELECT device_name, action, details, config_snapshot, timestamp FROM logs "
                            f"WHERE device_name IN ({placeholders})",
                            exported_names
                        )
                        for r in cur.fetchall():
                            export_data["audit_logs"].append({
                                "device_name": r[0], "action": r[1],
                                "details": r[2], "config_snapshot": r[3], "timestamp": r[4]
                            })
                except Exception as e:
                    self.log(f"[export] Warning: Could not export logs: {e}")

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            QMessageBox.information(self, "Export Complete", f"Exported {len(self.devices)} device(s) to:\n{filepath}")
            self.log(f"[export] saved project to {filepath}")
            self._set_status_message(f"Exported {len(self.devices)} device(s)", 3500)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def import_project(self):
        filepath = self._get_import_path()
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

        replace_mode = False
        if self.devices:
            msg = QMessageBox(self)
            msg.setWindowTitle("Import Project")
            msg.setText(
                f"You already have {len(self.devices)} device(s) in the workspace.\n\n"
                f"The imported file contains {len(devices_data)} device(s).\n\n"
                "Choose how to proceed:"
            )
            btn_replace = msg.addButton("Replace All", QMessageBox.DestructiveRole)
            btn_merge   = msg.addButton("Merge (add new only)", QMessageBox.AcceptRole)
            btn_cancel  = msg.addButton("Cancel", QMessageBox.RejectRole)
            msg.setDefaultButton(btn_merge)
            msg.exec()

            clicked = msg.clickedButton()
            if clicked == btn_cancel:
                return
            replace_mode = (clicked == btn_replace)

        if replace_mode:
            self.devices.clear()
            self._clear_all_devices_from_db()
            self.refresh_device_list()

        added = 0
        skipped = 0
        imported_names = []
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
            imported_names.append(name)
            
        audit_logs = data.get("audit_logs", [])
        logs_restored = 0
        if audit_logs and imported_names:
            try:
                from network_manager.config import conn, cur, db_lock
                with db_lock:
                    for entry in audit_logs:
                        dname = entry.get("device_name")
                        if dname in imported_names:
                            cur.execute(
                                "INSERT INTO logs (device_name, action, details, config_snapshot, timestamp) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (dname, entry.get("action"), entry.get("details"),
                                 entry.get("config_snapshot"), entry.get("timestamp"))
                            )
                            logs_restored += 1
                    conn.commit()
            except Exception as e:
                self.log(f"[import] Warning: could not restore logs: {e}")

        self.refresh_device_list()
        mode_label = "Replaced" if replace_mode else "Imported"
        msg_str = f"{mode_label} {added} device(s)."
        if skipped:
            msg_str += f"\nSkipped {skipped} duplicate(s)."
        if logs_restored:
            msg_str += f"\nRestored {logs_restored} audit log(s)."
            
        QMessageBox.information(self, "Import Complete", msg_str)
        self.log(f"[import] {mode_label.lower()} {added} device(s) and {logs_restored} logs from {filepath}")
        self._set_status_message(f"{mode_label} {added} device(s)", 3500)

    # ── Cross-device context extraction ─────────────────────────────────

    def _build_project_context(self, exclude_name: str, network_id: str = "") -> dict:
        ip_pat = re.compile(r"ip address\s+((?:\d{1,3}\.){3}\d{1,3})", re.IGNORECASE)
        all_used_ips: set[str] = set()
        used_schemes: set[str] = set()
        for _dn, _mdl, _mt in self.devices:
            if _dn == exclude_name:
                continue
            for tmpl_text in _mdl.templates.values():
                for ip in ip_pat.findall(tmpl_text):
                    all_used_ips.add(ip)
                    parts = ip.split(".")
                    if len(parts) == 4:
                        used_schemes.add(f"{parts[0]}.{parts[1]}")
        all_used_ips.discard("0.0.0.0")

        ctx = {
            "vlans": [], "routing_entries": [], "dhcp_pools": [], "acl_rules": [],
            "static_routes": [], "isp_gateway": "", "rip_enabled": False,
            "domain": "", "enable_pw": "", "ip_scheme": "192.168",
            "vlan_source": "", "routing_source": "", "dhcp_source_device": "",
            "routing_device": "", "routing_device_type": "",
            "network_id": network_id,
            "all_used_ips": all_used_ips,
            "used_schemes": used_schemes,
            # Multi-protocol support
            "protocol_map": {},                  # {device_name: "rip"|"ospf"|"eigrp"|"none"}
            "redistribution_router": "",          # auto-detected redistribution router
            "redistribution_protocols": [],       # e.g. ["rip", "ospf"]
            "redistribution_needed": False,       # True if >1 protocol in the network
            "existing_redistribution_router": "", # loop safeguard
        }
        for dname, model, _meta in self.devices:
            if dname == exclude_name:
                continue
            if network_id and _meta.get("network_id", "default") != network_id:
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
            if not ctx["rip_enabled"] and ("guided_rip" in tmpls or "guided_routing_protocol" in tmpls):
                rp_text = tmpls.get("guided_routing_protocol", "") or tmpls.get("guided_rip", "")
                if re.search(r"router\s+rip", rp_text, re.IGNORECASE):
                    ctx["rip_enabled"] = True
            # ── Multi-protocol detection: per-device ──────────────────────
            if isinstance(model, RouterModel):
                detected_proto = "none"
                rp_text = tmpls.get("guided_routing_protocol", "") or tmpls.get("guided_rip", "")
                if rp_text:
                    if re.search(r"router\s+eigrp", rp_text, re.IGNORECASE):
                        detected_proto = "eigrp"
                    elif re.search(r"router\s+ospf", rp_text, re.IGNORECASE):
                        detected_proto = "ospf"
                    elif re.search(r"router\s+rip", rp_text, re.IGNORECASE):
                        detected_proto = "rip"
                ctx["protocol_map"][dname] = detected_proto
                # Check if this device already has redistribution configured
                if re.search(r"redistribute\s+", rp_text, re.IGNORECASE):
                    ctx["existing_redistribution_router"] = dname
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

        # ── Cross-segment protocol scan (redistribution needs global view) ──
        for dname, model, _meta in self.devices:
            if dname == exclude_name or dname in ctx["protocol_map"]:
                continue
            if not isinstance(model, RouterModel):
                continue
            tmpls = model.templates
            detected_proto = "none"
            rp_text = tmpls.get("guided_routing_protocol", "") or tmpls.get("guided_rip", "")
            if rp_text:
                if re.search(r"router\s+eigrp", rp_text, re.IGNORECASE):
                    detected_proto = "eigrp"
                elif re.search(r"router\s+ospf", rp_text, re.IGNORECASE):
                    detected_proto = "ospf"
                elif re.search(r"router\s+rip", rp_text, re.IGNORECASE):
                    detected_proto = "rip"
            ctx["protocol_map"][dname] = detected_proto
            if re.search(r"redistribute\s+", rp_text, re.IGNORECASE):
                ctx["existing_redistribution_router"] = dname

        # ── Post-loop: Redistribution auto-detection (subnet-based) ──────
        active_protos = {p for p in ctx["protocol_map"].values() if p != "none"}
        if len(active_protos) > 1:
            ctx["redistribution_needed"] = True
            if not ctx["existing_redistribution_router"]:
                redist_info = self._detect_redistribution_router(
                    ctx["protocol_map"], exclude_name
                )
                ctx["redistribution_router"] = redist_info.get("router", "")
                ctx["redistribution_protocols"] = redist_info.get("protocols", list(active_protos))
            else:
                ctx["redistribution_protocols"] = list(active_protos)

        return ctx

    def _detect_redistribution_router(self, protocol_map: dict,
                                       exclude_name: str = "") -> dict:
        """
        Detect the redistribution candidate using GNS3 cable topology.

        A router that connects to neighbors running different routing
        protocols is the natural redistribution point.  Prefer the device
        being configured (exclude_name) so the wizard can act on it.

        Returns {"router": "R3", "protocols": ["ospf", "rip"]} or empty.
        """
        # Build GNS3 physical adjacency: router_name -> {neighbor_names}
        adjacency: dict[str, set[str]] = {}
        router_has_default: dict[str, bool] = {}
        try:
            project_id = getattr(self, "gns3_project_id", "")
            raw_links = self.gns3.get_links(project_id) if project_id else []
            raw_nodes = self.gns3.get_nodes(project_id) if project_id else []
        except Exception:
            raw_links, raw_nodes = [], []

        nid_to_name: dict[str, str] = {}
        for dname, model, _meta in self.devices:
            nid = str(_meta.get("node_id", ""))
            if nid:
                nid_to_name[nid] = dname
            if isinstance(model, RouterModel):
                adjacency.setdefault(dname, set())
                sr_text = model.templates.get("guided_static_routes", "")
                router_has_default[dname] = bool(
                    re.search(r"ip\s+route\s+0\.0\.0\.0\s+0\.0\.0\.0", sr_text, re.IGNORECASE)
                )

        for link in raw_links:
            eps = link.get("nodes", [])
            if len(eps) < 2:
                continue
            a_name = nid_to_name.get(str(eps[0].get("node_id", "")), "")
            b_name = nid_to_name.get(str(eps[1].get("node_id", "")), "")
            if a_name in adjacency and b_name in adjacency:
                adjacency[a_name].add(b_name)
                adjacency[b_name].add(a_name)

        # Find redistribution candidate — prefer the device being configured
        candidates = [exclude_name] + [r for r in adjacency if r != exclude_name]
        for router in candidates:
            if router not in adjacency:
                continue
            neighbor_protos = set()
            for neighbor in adjacency[router]:
                p = protocol_map.get(neighbor, "none")
                if p != "none":
                    neighbor_protos.add(p)
            if len(neighbor_protos) >= 2:
                if router_has_default.get(router, False):
                    continue
                return {"router": router, "protocols": sorted(neighbor_protos)}

        return {"router": "", "protocols": []}

    # ── GNS3 link resolution ─────────────────────────────────────────────

    def _resolve_device_links(self, node_id: str, meta: dict) -> list:
        """
        Fetch GNS3 links for the current project and return the connections
        involving *node_id* as a list of dicts::

            [{"local_interface": "Fa0/0",
              "remote_device":   "CSW1",
              "remote_interface": "Fa1/0",
              "remote_role":     "core"}, ...]
        """
        if not self.gns3 or not node_id:
            return []
        project_id = meta.get("project_id") or getattr(self, "gns3_project_id", "")
        if not project_id:
            return []
        try:
            raw_links = self.gns3.get_links(project_id)
            raw_nodes = self.gns3.get_nodes(project_id)
        except Exception:
            return []

        gns3_nodes = {n.get("node_id"): n for n in raw_nodes if "node_id" in n}

        # Build port maps  {node_id: {(adapter, port): "FastEthernet0/0", ...}}
        needed_nids = {node_id}
        for link in raw_links:
            eps = link.get("nodes", [])
            if len(eps) < 2:
                continue
            nids = [eps[0].get("node_id", ""), eps[1].get("node_id", "")]
            if node_id in nids:
                needed_nids.update(nids)

        port_maps: dict[str, dict] = {}
        for nid in needed_nids:
            try:
                ports = self.gns3.get_node_ports(project_id, nid)
                mapping = {}
                for p in ports:
                    a, pt, nm = p.get("adapter_number"), p.get("port_number"), p.get("name", "")
                    if a is not None and pt is not None and nm:
                        mapping[(int(a), int(pt))] = nm
                port_maps[nid] = mapping
            except Exception:
                pass

        # Map node_id -> (device_name, device_role, known_interfaces) from ANCS devices list
        nid_info: dict[str, tuple[str, str, list[str]]] = {}
        for dname, dmodel, dmeta in self.devices:
            dnid = dmeta.get("node_id", "")
            if dnid:
                if isinstance(dmodel, RouterModel):
                    role = "router"
                elif isinstance(dmodel, CoreSwitchModel):
                    role = "core"
                else:
                    role = "access"
                nid_info[dnid] = (dname, role, dmeta.get("interfaces", []))

        def _expand_iface(short_name: str) -> str:
            low = short_name.lower().strip()
            if low.startswith("fa"): return "FastEthernet" + short_name[2:]
            if low.startswith("f") and len(low) > 1 and low[1].isdigit(): return "FastEthernet" + short_name[1:]
            if low.startswith("gi"): return "GigabitEthernet" + short_name[2:]
            if low.startswith("g") and len(low) > 1 and low[1].isdigit(): return "GigabitEthernet" + short_name[1:]
            if low.startswith("te"): return "TenGigabitEthernet" + short_name[2:]
            if low.startswith("t") and len(low) > 1 and low[1].isdigit(): return "TenGigabitEthernet" + short_name[1:]
            if low.startswith("et"): return "Ethernet" + short_name[2:]
            if low.startswith("e") and len(low) > 1 and low[1].isdigit(): return "Ethernet" + short_name[1:]
            if low.startswith("se"): return "Serial" + short_name[2:]
            if low.startswith("s") and len(low) > 1 and low[1].isdigit(): return "Serial" + short_name[1:]
            return short_name

        def _iface_name(nid: str, adapter: int, port: int, endpoint: dict) -> str:
            lbl = (endpoint.get("label") or {}).get("text", "").strip()
            pm = port_maps.get(nid, {})
            name = pm.get((adapter, port), "")
            if not name and lbl:
                name = _expand_iface(lbl)
            
            # Use known_interfaces to find an exact case-sensitive match
            _, _, known = nid_info.get(nid, ("", "", []))
            if name:
                for kn in known:
                    if kn.lower() == name.lower() or kn.lower() == lbl.lower() or kn.lower() == _expand_iface(lbl).lower():
                        return kn
            elif known:
                gen = f"{adapter}/{port}"
                for kn in known:
                    if kn.endswith(gen):
                        return kn

            return name or (lbl if lbl else f"e{adapter}/{port}")

        result = []
        for link in raw_links:
            eps = link.get("nodes", [])
            if len(eps) < 2:
                continue
            a, b = eps[0], eps[1]
            a_nid, b_nid = a.get("node_id", ""), b.get("node_id", "")
            if a_nid == node_id:
                local_ep, remote_ep, remote_nid = a, b, b_nid
            elif b_nid == node_id:
                local_ep, remote_ep, remote_nid = b, a, a_nid
            else:
                continue
            local_iface = _iface_name(
                node_id,
                int(local_ep.get("adapter_number", 0)),
                int(local_ep.get("port_number", 0)),
                local_ep)
            remote_iface = _iface_name(
                remote_nid,
                int(remote_ep.get("adapter_number", 0)),
                int(remote_ep.get("port_number", 0)),
                remote_ep)
            
            rname, rrole, _ = nid_info.get(remote_nid, (None, None, []))
            if rname is None:
                # Fallback to GNS3 native raw node if unconnected to ANCS logic
                g_node = gns3_nodes.get(remote_nid, {})
                rname = g_node.get("name", "unknown")
                rrole = g_node.get("node_type", "unknown")
            
            result.append({
                "local_interface":  local_iface,
                "remote_device":    rname,
                "remote_interface": remote_iface,
                "remote_role":      rrole,
            })
        return result

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
                "Continue with this switch?")
            if ret != QMessageBox.Yes:
                return
        
        net_id = meta.get("network_id", "default")
        project_context = self._build_project_context(exclude_name=name, network_id=net_id)
        connected_links = self._resolve_device_links(meta.get("node_id", ""), meta)

        # Ensure we have interface list — fetch from GNS3 if missing
        interfaces = meta.get("interfaces", [])
        if not interfaces and self.gns3 and meta.get("node_id"):
            project_id = meta.get("project_id") or getattr(self, "gns3_project_id", "")
            if project_id:
                try:
                    ports_data = self.gns3.get_node_ports(project_id, meta["node_id"])
                    interfaces = [p["name"] for p in ports_data if p.get("name")]
                    meta["interfaces"] = interfaces  # cache for next time
                except Exception:
                    pass

        from .wizards import GuidedSetupWizard
        win = GuidedSetupWizard(self, name, model, device_role=device_role,
                                 known_interfaces=interfaces,
                                 project_context=project_context,
                                 connected_links=connected_links)
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
        source_net = "default"
        for n, m, mt in self.devices:
            if n == configured_name:
                source_net = mt.get("network_id", "default")
                break
                
        if device_role == "access":
            targets = [(n, m, mt) for n, m, mt in self.devices
                       if isinstance(m, SwitchModel) and n != configured_name
                       and mt.get("network_id", "default") == source_net
                       and not any(k.startswith("guided_") for k in m.templates)]
            apply_what = "VLANs + trunk uplink"
        elif device_role == "core":
            targets = [(n, m, mt) for n, m, mt in self.devices
                       if isinstance(m, (SwitchModel, CoreSwitchModel)) and n != configured_name
                       and mt.get("network_id", "default") == source_net
                       and not any(k.startswith("guided_") for k in m.templates)]
            apply_what = "VLANs"
        elif device_role == "router":
            targets = [(n, m, mt) for n, m, mt in self.devices
                       if isinstance(m, RouterModel) and n != configured_name
                       and mt.get("network_id", "default") == source_net
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
        lbl.setStyleSheet("color: #C9D1D9; font-size: 15px; font-weight: bold;")
        layout.addWidget(lbl)
        hint = QLabel("Recommended: start with the router or core switch.")
        hint.setStyleSheet("color: #8B949E; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        listbox = QListWidget()
        listbox.setIconSize(QSize(16, 16))
        for name, model, meta in self.devices:
            if isinstance(model, RouterModel):
                role = "Router / Gateway"
                icon_name = "router.svg"
            elif isinstance(model, CoreSwitchModel):
                role = "Core Switch (Layer 3)"
                icon_name = "layer-3-switch.svg"
            else:
                role = "Access Switch (Layer 2)"
                icon_name = "workgroup-switch.svg"
            
            label_text = f"{name}  \u2014  {role}"
            net_id = meta.get("network_id")
            if net_id and net_id != "default":
                label_text += f" [{net_id}]"
                
            item = QListWidgetItem(label_text)
            icon = self._icon(icon_name)
            if not icon.isNull():
                item.setIcon(icon)
            listbox.addItem(item)
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

    # ── Project Setup / Fleet Backup / Topology ────────────────────────

    def run_project_sync(self):
        try:
            from network_manager.gui.sync_workflows import ProjectSyncDialog
            dlg = ProjectSyncDialog(self, self.devices)
            
            # Connect the dialog's log signal to our main log method
            def _log_relay(msg):
                self.log(f"[Sync] {msg}")
            dlg.signals.log.connect(_log_relay)
            
            dlg.exec()
            # If the user successfully pulled live config, result_chosen = 'pull'
            if dlg.result_chosen == 'pull':
                extracted_str = ", ".join(getattr(dlg, "discovered_hostnames", []))
                if extracted_str:
                    msg = f"Live configurations pulled and populated into devices:\n\n{extracted_str}\n\nYou can now use Guided Setup or Bulk Deploy effectively."
                else:
                    msg = "No configured devices were found (all returned blank factory states)."
                self.refresh_devices_tree()
                QMessageBox.information(self, "Project Setup Complete", msg)
            elif dlg.result_chosen == 'fresh':
                self.guided_setup()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open Project Setup: {e}")

    def open_topology(self):
        project_id = getattr(self, "gns3_project_id", None)
        if not project_id:
            QMessageBox.information(self, "Topology",
                                    "No GNS3 project loaded.\nConnect to GNS3 and import devices first.")
            return
        try:
            connector = GNS3Connector(server_url=self._last_gns3_url)
            from .topology_viewer import TopologyViewer
            ctx = self._build_project_context(exclude_name="")
            ctx["network_map"] = self._compute_network_segments()
            TopologyViewer(self, connector, project_id, self.devices, ctx)
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


        def _network(item):
            return item[2].get("network_id", "default")
            
        def _priority(item):
            _, model, __ = item
            if isinstance(model, RouterModel): return 0
            elif isinstance(model, CoreSwitchModel): return 1
            return 2

        ordered = sorted(self.devices, key=lambda i: (_network(i), _priority(i)))
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

        try:
            from network_manager.gui.parallel_deploy import ParallelDeployDialog
            dlg = ParallelDeployDialog(self, deploy_list)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Parallel Deploy Error", str(e))

    # ── Audit log (Natively integrated in Logs Page) ────────────────────

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
            project_id = proj.get('project_id') or proj.get('projectId')
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

    def _compute_network_segments(self) -> dict:
        """
        Router-centric BFS: each router anchors a site.
        BFS from each router through non-router nodes.
        """
        if getattr(self, "gns3", None) is None or not getattr(self, "gns3_project_id", None):
            return {}
            
        try:
            raw_nodes = self.gns3.get_nodes(self.gns3_project_id)
            raw_links = self.gns3.get_links(self.gns3_project_id)
        except Exception:
            return {}

        adjacency = {str(n.get("node_id", "")): set() for n in raw_nodes if n.get("node_id")}
        for link in raw_links:
            eps = link.get("nodes", [])
            if len(eps) >= 2:
                a, b = str(eps[0].get("node_id", "")), str(eps[1].get("node_id", ""))
                if a in adjacency and b in adjacency:
                    adjacency[a].add(b)
                    adjacency[b].add(a)

        router_nids = set()
        core_nids = set()
        for dname, model, meta in self.devices:
            nid = str(meta.get("node_id", ""))
            if nid:
                if isinstance(model, RouterModel):
                    router_nids.add(nid)
                elif isinstance(model, CoreSwitchModel):
                    core_nids.add(nid)

        anchors = list(sorted(router_nids))
        if not anchors:
            anchors = list(sorted(core_nids))

        node_to_net = {}
        for i, anchor in enumerate(anchors):
            net_id = f"net-{i}"
            queue = [anchor]
            visited = set([anchor])
            node_to_net[anchor] = net_id
            
            while queue:
                curr = queue.pop(0)
                for neighbor in adjacency.get(curr, []):
                    if neighbor not in visited:
                        if neighbor in router_nids:
                            continue
                        visited.add(neighbor)
                        node_to_net[neighbor] = net_id
                        queue.append(neighbor)
                        
        return node_to_net

    def _assign_network_ids(self):
        node_to_net = self._compute_network_segments()
        
        assigned = 0
        import string
        for dname, model, meta in self.devices:
            nid = str(meta.get("node_id", ""))
            if nid and nid in node_to_net:
                net_id = node_to_net[nid]
                idx = int(net_id.split("-")[1])
                letter = string.ascii_uppercase[idx % 26]
                if idx >= 26:
                    letter += str(idx // 26)
                meta["network_id"] = f"Net {letter}"
                assigned += 1
            elif "network_id" not in meta:
                meta["network_id"] = "default"

        if assigned > 0:
            self._run_on_main(self.refresh_device_list)


    def _apply_gns3_import(self, new_devices, proj_name):
        imported = 0
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        project_id = self.gns3_project_id if hasattr(self, 'gns3_project_id') else ""

        # ── WIPE STALE/OLD GHOST DEVICES FROM DATABASE AND MEMORY ──
        # Ensure ONLY live devices in the current GNS3 project session exist.
        live_node_ids = {d["node_id"] for d in new_devices}
        
        try:
            with db_lock:
                # Get all GNS3 devices from the database
                cur.execute("SELECT name, node_id, project_id FROM devices WHERE added_from_gns3 = 1")
                db_gns3_devices = cur.fetchall()
                
                # Identify ghost devices to delete
                to_delete = []
                for name, node_id, pid in db_gns3_devices:
                    if pid != project_id or node_id not in live_node_ids:
                        to_delete.append(name)
                        
                for name in to_delete:
                    # Clean up configurations first (foreign key reference)
                    cur.execute("DELETE FROM configs WHERE device_id = (SELECT id FROM devices WHERE name = ?)", (name,))
                    # Clean up device credentials
                    cur.execute("DELETE FROM credentials WHERE device_name = ?", (name,))
                    # Clean up the device itself
                    cur.execute("DELETE FROM devices WHERE name = ?", (name,))
                    self.log(f"[db] Wiped stale ghost device '{name}' from database.")
                conn.commit()
        except Exception as exc:
            self.log(f"[db] error cleaning stale ghost devices: {exc}")

        # Remove stale ghost devices from in-memory workspace list
        stale_indices = []
        for idx, (name, _, meta) in enumerate(self.devices):
            if meta.get("gns3_node"):
                if meta.get("project_id") != project_id or meta.get("node_id") not in live_node_ids:
                    stale_indices.append(idx)
                    
        # Delete indices in reverse order to preserve list positions
        for idx in sorted(stale_indices, reverse=True):
            self.log(f"[UI] Removed stale ghost device '{self.devices[idx][0]}' from active workspace.")
            del self.devices[idx]

        # Ingest active/live nodes
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
            self._assign_network_ids()
            self.refresh_device_list()
            self.log(f"Auto-imported {imported} GNS3 node(s) from '{proj_name}'")
            # Automatically open the Project Setup when new devices are discovered
            if not getattr(self, "_project_sync_triggered", False):
                self._project_sync_triggered = True
                self.run_project_sync()
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
            self.gns3_project_id = project.get('project_id') or project.get('projectId')
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
        self._shutdown_copilot_on_exit()
        event.accept()

    def _shutdown_copilot_on_exit(self):
        """Stop the Copilot dialog/worker before Qt tears down widgets."""
        dlg = getattr(self, "_copilot_dlg", None)
        if dlg is not None:
            try:
                dlg._closing_for_app = True
                if hasattr(dlg, "_chips_timer"):
                    dlg._chips_timer.stop()
                if hasattr(dlg, "_thinking_dots"):
                    dlg._thinking_dots.stop()
                if hasattr(dlg, "_disconnect_worker_signals"):
                    dlg._disconnect_worker_signals()
                dlg.close()
                dlg.deleteLater()
            except Exception:
                pass
            self._copilot_dlg = None

        worker = getattr(self, "_copilot_worker", None)
        if worker is None:
            return
        try:
            self._copilot_history = getattr(worker, "_messages", [])
            worker.stop()
            if worker.isRunning() and not worker.wait(5000):
                worker.terminate()
                worker.wait(1500)
        except Exception:
            pass
        self._copilot_worker = None

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
