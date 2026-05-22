"""
ANCS Agent Dialog — Premium AI Copilot Interface
=================================================
Drop-in replacement for invoke_ai_agent().
All backend integration flows through parent_app (MainWindow).
Zero changes to ai_agent.py.
"""

import json
import os
import re
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextBrowser, QMessageBox, QTabWidget, QWidget, QScrollArea, QFrame,
    QComboBox, QStackedWidget, QSizePolicy, QSpacerItem,
    QFileDialog, QTextEdit, QApplication, QGraphicsDropShadowEffect,
)
from PySide6.QtCore import (
    Qt, QTimer, Signal, QSize, QPropertyAnimation, QEasingCurve,
    QPoint, QRect, Property, QRectF, QEvent,
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QLinearGradient,
    QCursor, QPainterPath, QIcon, QMouseEvent, QPixmap,
)

try:
    import markdown
    def _render_md(text):
        return markdown.markdown(text, extensions=["fenced_code", "tables"])
except ImportError:
    def _render_md(text):
        return text.replace("\n", "<br>")

# ═══════════════════════════════════════════════════════════════════════
# COLOR PALETTE
# ═══════════════════════════════════════════════════════════════════════
class _C:
    bg_deepest    = "#0D1117"
    bg_card       = "#161B22"
    bg_elevated   = "#1C2128"
    bg_input      = "#0D1117"
    border        = "#30363D"
    border_subtle = "#21262D"
    text_pri      = "#E6EDF3"
    text_sec      = "#C9D1D9"
    text_muted    = "#8B949E"
    accent        = "#3B82F6"
    accent_hover  = "#2563EB"
    purple        = "#A371F7"
    green         = "#3FB950"
    amber         = "#D29922"
    red           = "#F85149"
    white         = "#FFFFFF"
    user_bg       = "#1A2332"
    user_border   = "#1E3A5F"


# ═══════════════════════════════════════════════════════════════════════
# ICON FACTORY — QPainter-drawn vector icons (no emoji, no SVG deps)
# ═══════════════════════════════════════════════════════════════════════
def _make_icon(draw_fn, size=20, color="#C9D1D9") -> QIcon:
    """Create a QIcon by painting with the given draw function."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    draw_fn(p, size)
    p.end()
    return QIcon(pixmap)


def _draw_gear(p: QPainter, s: int):
    c = s / 2
    p.drawEllipse(QRectF(c - 4, c - 4, 8, 8))
    for i in range(6):
        import math
        a = math.radians(i * 60)
        x1 = c + 5.5 * math.cos(a)
        y1 = c + 5.5 * math.sin(a)
        x2 = c + 8 * math.cos(a)
        y2 = c + 8 * math.sin(a)
        p.drawLine(QPoint(int(x1), int(y1)), QPoint(int(x2), int(y2)))


def _draw_minimize(p: QPainter, s: int):
    y = s // 2
    p.drawLine(4, y, s - 4, y)


def _draw_maximize(p: QPainter, s: int):
    p.drawRect(4, 4, s - 8, s - 8)


def _draw_close(p: QPainter, s: int):
    p.drawLine(5, 5, s - 5, s - 5)
    p.drawLine(s - 5, 5, 5, s - 5)


def _draw_send(p: QPainter, s: int):
    path = QPainterPath()
    path.moveTo(4, s / 2)
    path.lineTo(s - 4, s / 2)
    path.moveTo(s - 8, s / 2 - 4)
    path.lineTo(s - 4, s / 2)
    path.lineTo(s - 8, s / 2 + 4)
    p.drawPath(path)


def _draw_search(p: QPainter, s: int):
    p.drawEllipse(QRectF(3, 3, 10, 10))
    p.drawLine(11, 11, s - 4, s - 4)


def _draw_clear(p: QPainter, s: int):
    p.drawLine(6, 4, 6, s - 6)
    p.drawLine(s - 6, 4, s - 6, s - 6)
    p.drawLine(6, s - 6, s - 6, s - 6)
    p.drawLine(4, 7, s - 4, 7)
    p.drawLine(8, 2, 8, 5)
    p.drawLine(s - 8, 2, s - 8, 5)


def _draw_export(p: QPainter, s: int):
    c = s // 2
    p.drawLine(c, 4, c, s - 7)
    p.drawLine(c - 4, s - 11, c, s - 7)
    p.drawLine(c + 4, s - 11, c, s - 7)
    p.drawLine(4, s - 4, s - 4, s - 4)


def _draw_terminal(p: QPainter, s: int):
    p.drawLine(4, 6, 8, s // 2)
    p.drawLine(8, s // 2, 4, s - 6)
    p.drawLine(10, s - 6, s - 4, s - 6)


def _draw_back(p: QPainter, s: int):
    c = s // 2
    p.drawLine(s - 5, c, 5, c)
    p.drawLine(5, c, 9, c - 4)
    p.drawLine(5, c, 9, c + 4)


def _draw_expand(p: QPainter, s: int):
    c = s // 2
    p.drawLine(5, c - 2, c, c + 3)
    p.drawLine(c, c + 3, s - 5, c - 2)


def _draw_collapse(p: QPainter, s: int):
    c = s // 2
    p.drawLine(5, c + 2, c, c - 3)
    p.drawLine(c, c - 3, s - 5, c + 2)


def _draw_check(p: QPainter, s: int):
    pen = p.pen()
    pen.setColor(QColor(_C.green))
    pen.setWidthF(2.0)
    p.setPen(pen)
    p.drawLine(4, s // 2, s // 2 - 1, s - 5)
    p.drawLine(s // 2 - 1, s - 5, s - 4, 5)


def _draw_spinner(p: QPainter, s: int):
    pen = p.pen()
    pen.setColor(QColor(_C.accent))
    pen.setWidthF(2.0)
    p.setPen(pen)
    p.drawArc(QRectF(4, 4, s - 8, s - 8), 30 * 16, 270 * 16)


def _draw_error(p: QPainter, s: int):
    pen = p.pen()
    pen.setColor(QColor(_C.red))
    pen.setWidthF(2.0)
    p.setPen(pen)
    c = s // 2
    p.drawLine(c, 4, c, s // 2 + 1)
    p.drawPoint(c, s - 5)


def _draw_attach(p: QPainter, s: int):
    path = QPainterPath()
    path.moveTo(s - 6, 8)
    path.lineTo(s - 6, s / 2 + 2)
    path.cubicTo(s - 6, s - 3, 4, s - 3, 4, s / 2 + 2)
    path.lineTo(4, 7)
    path.cubicTo(4, 3, s - 6, 3, s - 6, 7)
    p.drawPath(path)


def _draw_dot(p: QPainter, s: int, color: str = "#3FB950"):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    c = s / 2
    p.drawEllipse(QRectF(c - 3, c - 3, 6, 6))


# Pre-built icons
class Icons:
    @staticmethod
    def gear():     return _make_icon(_draw_gear, 18)
    @staticmethod
    def minimize(): return _make_icon(_draw_minimize, 18)
    @staticmethod
    def maximize(): return _make_icon(_draw_maximize, 18)
    @staticmethod
    def close():    return _make_icon(_draw_close, 18, _C.text_sec)
    @staticmethod
    def send():     return _make_icon(_draw_send, 20, _C.white)
    @staticmethod
    def search():   return _make_icon(_draw_search, 16, _C.text_muted)
    @staticmethod
    def clear():    return _make_icon(_draw_clear, 16)
    @staticmethod
    def export():   return _make_icon(_draw_export, 16)
    @staticmethod
    def terminal(): return _make_icon(_draw_terminal, 16, _C.purple)
    @staticmethod
    def back():     return _make_icon(_draw_back, 18)
    @staticmethod
    def expand():   return _make_icon(_draw_expand, 14, _C.text_muted)
    @staticmethod
    def collapse(): return _make_icon(_draw_collapse, 14, _C.text_muted)
    @staticmethod
    def check():    return _make_icon(_draw_check, 16)
    @staticmethod
    def spinner():  return _make_icon(_draw_spinner, 16)
    @staticmethod
    def error():    return _make_icon(_draw_error, 16)
    @staticmethod
    def attach():   return _make_icon(_draw_attach, 18, _C.text_sec)


# ═══════════════════════════════════════════════════════════════════════
# STYLED BUTTON FACTORY
# ═══════════════════════════════════════════════════════════════════════
def _icon_btn(icon: QIcon, size=32, tooltip="", style="ghost") -> QPushButton:
    btn = QPushButton()
    btn.setIcon(icon)
    btn.setIconSize(QSize(size - 10, size - 10))
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.PointingHandCursor)
    if tooltip:
        btn.setToolTip(tooltip)
    if style == "ghost":
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: {size // 2}px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.06);
            }}
            QPushButton:pressed {{
                background: rgba(255, 255, 255, 0.1);
            }}
        """)
    elif style == "close":
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: {size // 2}px;
            }}
            QPushButton:hover {{
                background: {_C.red};
            }}
            QPushButton:pressed {{
                background: #da3633;
            }}
        """)
    return btn


# ═══════════════════════════════════════════════════════════════════════
# STATUS DOT (painted, not text)
# ═══════════════════════════════════════════════════════════════════════
class StatusDot(QWidget):
    def __init__(self, color="#8B949E", size=10, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)

    def set_color(self, color: str):
        self._color = color
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        s = min(self.width(), self.height())
        p.drawEllipse(QRectF(1, 1, s - 2, s - 2))


# ═══════════════════════════════════════════════════════════════════════
# TOGGLE SWITCH (animated)
# ═══════════════════════════════════════════════════════════════════════
class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._offset = 22.0 if checked else 2.0
        self.setFixedSize(48, 26)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, v):
        self._checked = v
        self._offset = 22.0 if v else 2.0
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QColor(_C.accent) if self._checked else QColor("#374151")
        p.setBrush(track)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, 48, 26, 13, 13)
        p.setBrush(QColor(_C.white))
        p.drawEllipse(int(self._offset), 2, 22, 22)

    def mousePressEvent(self, _e):
        self._checked = not self._checked
        anim = QPropertyAnimation(self, b"offset", self)
        anim.setDuration(150)
        anim.setStartValue(self._offset)
        anim.setEndValue(22.0 if self._checked else 2.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self.toggled.emit(self._checked)

    def _get_offset(self):
        return self._offset

    def _set_offset(self, v):
        self._offset = v
        self.update()

    offset = Property(float, _get_offset, _set_offset)


# ═══════════════════════════════════════════════════════════════════════
# THINKING DOTS
# ═══════════════════════════════════════════════════════════════════════
class ThinkingDots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 24)
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._phase = 0
        self._timer.start(350)
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase = (self._phase + 1) % 3
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i in range(3):
            active = i == self._phase
            sz = 10 if active else 7
            alpha = 255 if active else 80
            p.setBrush(QColor(59, 130, 246, alpha))
            x = 4 + i * 18
            y = 12 - sz // 2
            p.drawEllipse(x, y, sz, sz)


# ═══════════════════════════════════════════════════════════════════════
# DEVICE CHIP
# ═══════════════════════════════════════════════════════════════════════
class DeviceChip(QFrame):
    def __init__(self, name: str, status: str = "connected", parent=None):
        super().__init__(parent)
        colors = {"configured": _C.green, "connected": _C.green,
                  "pending": _C.amber, "error": _C.red, "offline": _C.text_muted}
        dot_color = colors.get(status, _C.text_muted)
        self.setStyleSheet(f"""
            DeviceChip {{
                background: {_C.bg_elevated};
                border: 1px solid {_C.border};
                border-radius: 12px;
                padding: 3px 10px;
            }}
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)
        dot = StatusDot(dot_color, 8)
        lay.addWidget(dot)
        lbl = QLabel(name)
        lbl.setStyleSheet(f"color: {_C.text_sec}; font-size: 11px; font-weight: 500;")
        lay.addWidget(lbl)


# ═══════════════════════════════════════════════════════════════════════
# TOOL EXECUTION CARD
# ═══════════════════════════════════════════════════════════════════════
class ToolCard(QFrame):
    def __init__(self, tool_name: str, args_preview: str = "", parent=None):
        super().__init__(parent)
        self.tool_name = tool_name
        self._expanded = False
        self._result_text = ""

        self.setStyleSheet(f"""
            ToolCard {{
                background: {_C.bg_deepest};
                border: 1px solid {_C.border_subtle};
                border-radius: 8px;
            }}
        """)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(12, 8, 12, 8)
        self._main_layout.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(8)

        icon_lbl = QPushButton()
        icon_lbl.setIcon(Icons.terminal())
        icon_lbl.setIconSize(QSize(14, 14))
        icon_lbl.setFixedSize(20, 20)
        icon_lbl.setStyleSheet("border: none; background: transparent;")
        icon_lbl.setEnabled(False)
        header.addWidget(icon_lbl)

        display = tool_name
        if args_preview:
            short = args_preview[:40] + ("..." if len(args_preview) > 40 else "")
            display = f"{tool_name}({short})"
        self._name_lbl = QLabel(display)
        self._name_lbl.setStyleSheet(f"color: {_C.text_sec}; font-size: 12px; font-family: 'Cascadia Code', 'Consolas', monospace;")
        header.addWidget(self._name_lbl, 1)

        self._status_icon = QPushButton()
        self._status_icon.setIcon(Icons.spinner())
        self._status_icon.setIconSize(QSize(14, 14))
        self._status_icon.setFixedSize(18, 18)
        self._status_icon.setStyleSheet("border: none; background: transparent;")
        self._status_icon.setEnabled(False)
        header.addWidget(self._status_icon)

        self._status_lbl = QLabel("Running")
        self._status_lbl.setStyleSheet(f"color: {_C.accent}; font-size: 11px;")
        header.addWidget(self._status_lbl)

        self._expand_btn = _icon_btn(Icons.expand(), 22)
        self._expand_btn.clicked.connect(self._toggle_expand)
        header.addWidget(self._expand_btn)

        self._main_layout.addLayout(header)

        self._result_browser = QTextBrowser()
        self._result_browser.setMaximumHeight(180)
        self._result_browser.setVisible(False)
        self._result_browser.setStyleSheet(f"""
            QTextBrowser {{
                background: {_C.bg_card};
                border: 1px solid {_C.border_subtle};
                border-radius: 6px;
                color: {_C.text_sec};
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 11px;
                padding: 8px;
                margin-top: 6px;
            }}
        """)
        self._main_layout.addWidget(self._result_browser)

    def set_completed(self, duration_ms: str = "", result: str = ""):
        self._status_icon.setIcon(Icons.check())
        label = "Completed"
        if duration_ms:
            label += f"  {duration_ms}ms"
        self._status_lbl.setText(label)
        self._status_lbl.setStyleSheet(f"color: {_C.green}; font-size: 11px;")
        if result:
            self._result_text = result
            self._result_browser.setPlainText(result)

    def set_error(self, error_text: str = ""):
        self._status_icon.setIcon(Icons.error())
        self._status_lbl.setText("Error")
        self._status_lbl.setStyleSheet(f"color: {_C.red}; font-size: 11px;")
        if error_text:
            self._result_text = error_text
            self._result_browser.setPlainText(error_text)

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._result_browser.setVisible(self._expanded and bool(self._result_text))
        self._expand_btn.setIcon(Icons.collapse() if self._expanded else Icons.expand())


# ═══════════════════════════════════════════════════════════════════════
# MESSAGE WIDGETS
# ═══════════════════════════════════════════════════════════════════════
_MD_CSS = f"""
    body {{ color: {_C.text_sec}; font-family: 'Segoe UI', sans-serif; font-size: 13px; line-height: 1.6; }}
    h1,h2,h3 {{ color: {_C.purple}; margin: 10px 0 4px; }}
    strong,b {{ color: #58a6ff; }}
    code {{ background: {_C.bg_deepest}; color: #79c0ff; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
    pre {{ background: {_C.bg_deepest}; border: 1px solid {_C.border_subtle}; padding: 12px; border-radius: 8px; overflow-x: auto; }}
    pre code {{ background: none; padding: 0; }}
    ul,ol {{ padding-left: 18px; }}
    li {{ margin-bottom: 3px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
    th,td {{ border: 1px solid {_C.border}; padding: 6px 12px; text-align: left; }}
    th {{ background: {_C.bg_card}; color: {_C.purple}; }}
    p {{ margin: 4px 0; }}
    a {{ color: {_C.accent}; }}
"""


class UserBubble(QFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(60, 2, 8, 2)

        outer.addStretch()

        bubble = QFrame()
        bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        bubble.setStyleSheet(f"""
            QFrame {{
                background: {_C.user_bg};
                border: 1px solid {_C.user_border};
                border-radius: 12px;
                padding: 8px 14px;
            }}
        """)
        blay = QVBoxLayout(bubble)
        blay.setContentsMargins(0, 0, 0, 0)
        blay.setSpacing(2)

        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setTextFormat(Qt.PlainText)
        msg.setMaximumWidth(500)
        msg.setStyleSheet(f"color: {_C.text_pri}; font-size: 13px; border: none; background: none;")
        blay.addWidget(msg)

        ts = QLabel(datetime.now().strftime("%I:%M %p"))
        ts.setAlignment(Qt.AlignRight)
        ts.setStyleSheet(f"color: {_C.text_muted}; font-size: 9px; border: none; background: none;")
        blay.addWidget(ts)

        outer.addWidget(bubble)


class AIBubble(QFrame):
    def __init__(self, html_content: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 80, 6)
        lay.setSpacing(4)

        sender = QLabel("ANCS")
        sender.setStyleSheet(f"color: {_C.accent}; font-weight: bold; font-size: 13px;")
        lay.addWidget(sender)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(f"<style>{_MD_CSS}</style>{html_content}")
        browser.setStyleSheet(f"""
            QTextBrowser {{
                background: transparent;
                border: none;
                color: {_C.text_sec};
                font-size: 13px;
            }}
        """)
        browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        doc = browser.document()
        doc.setTextWidth(650)
        h = max(40, int(doc.size().height()) + 12)
        browser.setFixedHeight(min(h, 800))
        lay.addWidget(browser)

        ts = QLabel(datetime.now().strftime("%I:%M %p"))
        ts.setStyleSheet(f"color: {_C.text_muted}; font-size: 10px;")
        lay.addWidget(ts)

        self.tool_container = QVBoxLayout()
        self.tool_container.setSpacing(4)
        lay.addLayout(self.tool_container)


class SystemMsg(QFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 8)
        line_l = QFrame()
        line_l.setFixedHeight(1)
        line_l.setStyleSheet(f"background: {_C.border_subtle};")
        lay.addWidget(line_l, 1)
        lbl = QLabel(f"  {text}  ")
        lbl.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px;")
        lay.addWidget(lbl)
        line_r = QFrame()
        line_r.setFixedHeight(1)
        line_r.setStyleSheet(f"background: {_C.border_subtle};")
        lay.addWidget(line_r, 1)


# ═══════════════════════════════════════════════════════════════════════
# SCROLLBAR STYLESHEET
# ═══════════════════════════════════════════════════════════════════════
_SCROLLBAR = f"""
    QScrollBar:vertical {{
        background: transparent; width: 6px; margin: 4px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: {_C.border}; border-radius: 3px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {_C.text_muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


# ═══════════════════════════════════════════════════════════════════════
# MAIN DIALOG
# ═══════════════════════════════════════════════════════════════════════
class ANCSAgentDialog(QDialog):
    """Premium ANCS Agent dialog — drop-in replacement for invoke_ai_agent()."""

    def __init__(self, parent_app):
        super().__init__(parent_app, Qt.FramelessWindowHint | Qt.WindowSystemMenuHint)
        self.app = parent_app
        self.setMinimumSize(900, 600)
        self.resize(1060, 760)
        self._drag_pos = None
        self._is_maximized = False

        self._tool_cards: dict[str, ToolCard] = {}
        self._pending_tool_cards: list[ToolCard] = []
        self._waiting_for_reply = False

        if not hasattr(self.app, "_copilot_chat_data"):
            self.app._copilot_chat_data = []

        self._build_ui()
        self._restore_state()

    # ──────────────────────────────────────────────────────────────────
    # UI CONSTRUCTION
    # ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setStyleSheet(f"""
            ANCSAgentDialog {{
                background: {_C.bg_deepest};
                border: 1px solid {_C.border};
                border-radius: 10px;
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
            QFrame {{
                border: none;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_sub_header())

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_C.border_subtle};")
        root.addWidget(sep)

        self._main_stack = QStackedWidget()
        root.addWidget(self._main_stack, 1)

        self._main_stack.addWidget(self._build_chat_logs_page())
        self._main_stack.addWidget(self._build_settings_page())

    # ── TITLE BAR ─────────────────────────────────────────────────────
    def _build_title_bar(self):
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"""
            QWidget {{
                background: {_C.bg_card};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
        """)
        self._title_bar_widget = bar

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 8, 0)
        lay.setSpacing(12)

        title = QLabel("ANCS Agent")
        title.setStyleSheet(f"color: {_C.text_pri}; font-size: 15px; font-weight: bold; letter-spacing: 0.5px;")
        lay.addWidget(title)

        self._status_dot = StatusDot(_C.text_muted, 9)
        lay.addWidget(self._status_dot)

        self._status_label = QLabel("Offline")
        self._status_label.setStyleSheet(f"color: {_C.text_muted}; font-size: 12px;")
        lay.addWidget(self._status_label)

        lay.addStretch()

        btn_settings = _icon_btn(Icons.gear(), 34, "Settings")
        btn_settings.clicked.connect(self._toggle_settings)
        lay.addWidget(btn_settings)

        lay.addSpacing(8)

        btn_min = _icon_btn(Icons.minimize(), 32, "Minimize")
        btn_min.clicked.connect(self.showMinimized)
        lay.addWidget(btn_min)

        btn_max = _icon_btn(Icons.maximize(), 32, "Maximize")
        btn_max.clicked.connect(self._toggle_maximize)
        lay.addWidget(btn_max)

        btn_close = _icon_btn(Icons.close(), 32, "Close", style="close")
        btn_close.clicked.connect(self.hide)
        lay.addWidget(btn_close)

        return bar

    # ── SUB-HEADER ────────────────────────────────────────────────────
    def _build_sub_header(self):
        w = QWidget()
        w.setFixedHeight(34)
        w.setStyleSheet(f"background: {_C.bg_deepest};")

        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(10)

        self._model_badge = QLabel("Not connected")
        self._model_badge.setStyleSheet(f"""
            QLabel {{
                background: {_C.bg_elevated};
                border: 1px solid {_C.border};
                border-radius: 10px;
                padding: 3px 12px;
                color: {_C.text_sec};
                font-size: 11px;
                font-weight: 500;
            }}
        """)
        lay.addWidget(self._model_badge)

        self._device_count_lbl = QLabel("")
        self._device_count_lbl.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px;")
        lay.addWidget(self._device_count_lbl)

        lay.addStretch()
        return w

    # ── CHAT + LOGS PAGE ──────────────────────────────────────────────
    def _build_chat_logs_page(self):
        page = QWidget()
        page.setStyleSheet(f"background: {_C.bg_deepest};")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: {_C.bg_deepest};
            }}
            QTabBar::tab {{
                background: transparent;
                color: {_C.text_muted};
                padding: 10px 28px;
                font-size: 13px;
                font-weight: 500;
                border: none;
                border-bottom: 2px solid transparent;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                color: {_C.text_pri};
                border-bottom: 2px solid {_C.accent};
            }}
            QTabBar::tab:hover {{
                color: {_C.text_sec};
                background: rgba(255, 255, 255, 0.03);
            }}
        """)
        self._tabs.addTab(self._build_chat_tab(), "Chat")
        self._tabs.addTab(self._build_logs_tab(), "Execution Logs")
        lay.addWidget(self._tabs, 1)

        lay.addWidget(self._build_input_bar())

        return page

    # ── CHAT TAB ──────────────────────────────────────────────────────
    def _build_chat_tab(self):
        w = QWidget()
        w.setStyleSheet(f"background: {_C.bg_deepest};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 8, 12, 0)
        lay.setSpacing(6)

        # Device chips row
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)

        chips_dot = StatusDot(_C.accent, 8)
        chips_row.addWidget(chips_dot)

        self._chips_count = QLabel("0 Devices")
        self._chips_count.setStyleSheet(f"color: {_C.text_sec}; font-size: 11px; font-weight: bold;")
        chips_row.addWidget(self._chips_count)

        self._chips_container = QHBoxLayout()
        self._chips_container.setSpacing(6)
        chips_row.addLayout(self._chips_container)

        chips_row.addStretch()
        lay.addLayout(chips_row)

        # Chat scroll area
        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chat_scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {_C.bg_card};
                border: 1px solid {_C.border_subtle};
                border-radius: 10px;
            }}
            {_SCROLLBAR}
        """)

        self._chat_content = QWidget()
        self._chat_content.setStyleSheet(f"background: {_C.bg_card}; border-radius: 10px;")
        self._chat_layout = QVBoxLayout(self._chat_content)
        self._chat_layout.setAlignment(Qt.AlignTop)
        self._chat_layout.setContentsMargins(14, 14, 14, 14)
        self._chat_layout.setSpacing(4)
        self._chat_scroll.setWidget(self._chat_content)

        lay.addWidget(self._chat_scroll, 1)

        # Thinking row
        self._thinking_row = QWidget()
        self._thinking_row.setVisible(False)
        tlay = QHBoxLayout(self._thinking_row)
        tlay.setContentsMargins(8, 4, 8, 4)
        self._thinking_text = QLabel("")
        self._thinking_text.setStyleSheet(f"color: {_C.text_muted}; font-size: 12px;")
        tlay.addWidget(self._thinking_text)
        self._thinking_dots = ThinkingDots()
        self._thinking_dots.hide()
        tlay.addWidget(self._thinking_dots)
        tlay.addStretch()
        lay.addWidget(self._thinking_row)

        return w

    # ── LOGS TAB ──────────────────────────────────────────────────────
    def _build_logs_tab(self):
        w = QWidget()
        w.setStyleSheet(f"background: {_C.bg_deepest};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.addStretch()

        self._logs_search = QLineEdit()
        self._logs_search.setPlaceholderText("Search logs...")
        self._logs_search.setFixedWidth(220)
        self._logs_search.setFixedHeight(32)
        self._logs_search.setStyleSheet(f"""
            QLineEdit {{
                background: {_C.bg_card};
                border: 1px solid {_C.border};
                border-radius: 6px;
                color: {_C.text_sec};
                padding: 0 10px 0 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {_C.accent}; }}
        """)
        self._logs_search.textChanged.connect(self._filter_logs)
        toolbar.addWidget(self._logs_search)

        btn_style = f"""
            QPushButton {{
                background: {_C.bg_elevated};
                border: 1px solid {_C.border};
                border-radius: 6px;
                color: {_C.text_sec};
                padding: 0 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {_C.text_muted}; color: {_C.text_pri}; }}
        """

        btn_clear = QPushButton("  Clear")
        btn_clear.setIcon(Icons.clear())
        btn_clear.setFixedHeight(32)
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setStyleSheet(btn_style)
        btn_clear.clicked.connect(self._clear_logs)
        toolbar.addWidget(btn_clear)

        btn_export = QPushButton("  Export")
        btn_export.setIcon(Icons.export())
        btn_export.setFixedHeight(32)
        btn_export.setCursor(Qt.PointingHandCursor)
        btn_export.setStyleSheet(btn_style)
        btn_export.clicked.connect(self._export_logs)
        toolbar.addWidget(btn_export)

        lay.addLayout(toolbar)

        self._logs_browser = QTextBrowser()
        self._logs_browser.setOpenExternalLinks(False)
        self._logs_browser.setStyleSheet(f"""
            QTextBrowser {{
                background: {_C.bg_card};
                border: 1px solid {_C.border_subtle};
                border-radius: 10px;
                color: {_C.text_sec};
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 12px;
                padding: 12px;
            }}
            {_SCROLLBAR}
        """)
        self._logs_browser.setHtml(
            f"<span style='color:{_C.text_muted}'>Tool execution logs will stream here...</span>"
        )
        self._logs_raw_entries: list[str] = []
        lay.addWidget(self._logs_browser, 1)

        return w

    # ── INPUT BAR ─────────────────────────────────────────────────────
    def _build_input_bar(self):
        bar = QWidget()
        bar.setStyleSheet(f"background: {_C.bg_deepest}; border-top: 1px solid {_C.border_subtle};")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        self._chat_input = QTextEdit()
        self._chat_input.setPlaceholderText("Ask ANCS anything...")
        self._chat_input.setMinimumHeight(44)
        self._chat_input.setMaximumHeight(150)
        self._chat_input.setAcceptRichText(False)
        self._chat_input.setStyleSheet(f"""
            QTextEdit {{
                background: {_C.bg_card};
                border: 1px solid {_C.border};
                border-radius: 10px;
                color: {_C.text_pri};
                padding: 10px 14px;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                selection-background-color: {_C.accent};
            }}
            QTextEdit:focus {{ border-color: {_C.accent}; }}
            {_SCROLLBAR}
        """)
        self._chat_input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chat_input.setEnabled(False)
        self._chat_input.installEventFilter(self)
        self._chat_input.textChanged.connect(self._auto_resize_input)
        outer.addWidget(self._chat_input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_attach = _icon_btn(Icons.attach(), 34, "Attach file")
        self._btn_attach.setStyleSheet(f"""
            QPushButton {{
                background: {_C.bg_elevated};
                border: 1px solid {_C.border};
                border-radius: 8px;
            }}
            QPushButton:hover {{ border-color: {_C.text_muted}; }}
        """)
        self._btn_attach.clicked.connect(self._attach_file)
        btn_row.addWidget(self._btn_attach)

        btn_row.addStretch()

        hint = QLabel("Shift + Enter for new line")
        hint.setStyleSheet(f"color: {_C.text_muted}; font-size: 10px;")
        btn_row.addWidget(hint)

        btn_row.addSpacing(4)

        self._btn_send = QPushButton("  Send")
        self._btn_send.setIcon(Icons.send())
        self._btn_send.setIconSize(QSize(16, 16))
        self._btn_send.setFixedHeight(36)
        self._btn_send.setCursor(Qt.PointingHandCursor)
        self._btn_send.setStyleSheet(f"""
            QPushButton {{
                background: {_C.accent};
                border: none;
                border-radius: 8px;
                color: {_C.white};
                font-size: 13px;
                font-weight: bold;
                padding: 0 20px;
            }}
            QPushButton:hover {{ background: {_C.accent_hover}; }}
            QPushButton:disabled {{ background: {_C.border}; color: {_C.text_muted}; }}
        """)
        self._btn_send.clicked.connect(self._send_message)
        self._btn_send.setEnabled(False)
        btn_row.addWidget(self._btn_send)

        outer.addLayout(btn_row)
        return bar

    # ── SETTINGS PAGE ─────────────────────────────────────────────────
    def _build_settings_page(self):
        page = QWidget()
        page.setStyleSheet(f"background: {_C.bg_deepest};")
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(0, 0, 0, 0)
        page_lay.setSpacing(0)

        content = QWidget()
        content_lay = QHBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"background: {_C.bg_card};")

        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(12, 20, 12, 16)
        sb_lay.setSpacing(4)

        sb_title = QLabel("Settings")
        sb_title.setStyleSheet(f"color: {_C.text_pri}; font-size: 16px; font-weight: bold; padding-bottom: 12px;")
        sb_lay.addWidget(sb_title)

        self._settings_nav_buttons = []
        nav_items = ["General", "Model & Provider", "Connections", "Workspace", "Advanced"]
        for label in nav_items:
            btn = QPushButton(f"  {label}")
            btn.setFixedHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none; border-radius: 8px;
                    color: {_C.text_sec}; font-size: 12px; text-align: left; padding-left: 12px;
                }}
                QPushButton:hover {{ background: {_C.bg_elevated}; color: {_C.text_pri}; }}
            """)
            self._settings_nav_buttons.append(btn)
            sb_lay.addWidget(btn)

        sb_lay.addStretch()

        btn_back = QPushButton("  Back to Chat")
        btn_back.setIcon(Icons.back())
        btn_back.setFixedHeight(36)
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {_C.border}; border-radius: 8px;
                color: {_C.text_sec}; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {_C.accent}; color: {_C.text_pri}; }}
        """)
        btn_back.clicked.connect(lambda: self._main_stack.setCurrentIndex(0))
        sb_lay.addWidget(btn_back)

        content_lay.addWidget(sidebar)

        vsep = QFrame()
        vsep.setFixedWidth(1)
        vsep.setStyleSheet(f"background: {_C.border_subtle};")
        content_lay.addWidget(vsep)

        self._settings_stack = QStackedWidget()
        self._settings_stack.addWidget(self._build_general_settings())
        for _ in range(4):
            ph = QWidget()
            pl = QVBoxLayout(ph)
            pl.setContentsMargins(24, 24, 24, 24)
            pl.addWidget(QLabel("Coming soon..."))
            pl.addStretch()
            self._settings_stack.addWidget(ph)

        content_lay.addWidget(self._settings_stack, 1)

        for i, btn in enumerate(self._settings_nav_buttons):
            btn.clicked.connect(lambda _=False, idx=i: self._select_settings_tab(idx))

        self._select_settings_tab(0)
        page_lay.addWidget(content, 1)

        # Bottom bar
        bottom = QWidget()
        bottom.setFixedHeight(56)
        bottom.setStyleSheet(f"background: {_C.bg_card}; border-top: 1px solid {_C.border_subtle};")
        b_lay = QHBoxLayout(bottom)
        b_lay.setContentsMargins(16, 0, 16, 0)
        b_lay.addStretch()

        btn_test = QPushButton("Test Connection")
        btn_test.setFixedHeight(36)
        btn_test.setCursor(Qt.PointingHandCursor)
        btn_test.setStyleSheet(f"""
            QPushButton {{
                background: {_C.bg_elevated}; border: 1px solid {_C.border}; border-radius: 8px;
                color: {_C.text_sec}; padding: 0 18px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {_C.text_muted}; color: {_C.text_pri}; }}
        """)
        btn_test.clicked.connect(self._test_connection)
        b_lay.addWidget(btn_test)

        btn_save = QPushButton("Save Changes")
        btn_save.setFixedHeight(36)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {_C.accent}; border: none; border-radius: 8px;
                color: {_C.white}; padding: 0 22px; font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {_C.accent_hover}; }}
        """)
        btn_save.clicked.connect(self._save_settings)
        b_lay.addWidget(btn_save)

        page_lay.addWidget(bottom)
        return page

    def _build_general_settings(self):
        w = QWidget()
        w.setStyleSheet(f"background: {_C.bg_deepest};")
        main_h = QHBoxLayout(w)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # LEFT — General
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(24, 20, 24, 20)
        ll.setSpacing(14)

        ll.addWidget(self._section_title("General"))
        ll.addWidget(self._field_label("Theme"))
        self._theme_combo = self._styled_combo(["Dark", "Light", "System"])
        ll.addWidget(self._theme_combo)

        ll.addWidget(self._field_label("Language"))
        self._lang_combo = self._styled_combo(["English", "Arabic", "French", "Spanish"])
        ll.addWidget(self._lang_combo)

        toggles = [
            ("Start on system startup", "auto_start", False),
            ("Minimize to tray", "minimize_tray", True),
            ("Notifications on completion", "notifications", True),
            ("Auto connect last workspace", "auto_connect", False),
        ]
        self._setting_toggles = {}
        for label, key, default in toggles:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {_C.text_sec}; font-size: 12px;")
            row.addWidget(lbl)
            row.addStretch()
            toggle = ToggleSwitch(checked=default)
            self._setting_toggles[key] = toggle
            row.addWidget(toggle)
            ll.addLayout(row)

        ll.addStretch()

        vsep = QFrame()
        vsep.setFixedWidth(1)
        vsep.setStyleSheet(f"background: {_C.border_subtle};")

        # RIGHT — Model & Provider
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(24, 20, 24, 20)
        rl.setSpacing(10)

        rl.addWidget(self._section_title("Model & Provider"))
        rl.addWidget(self._field_label("Provider"))
        self._provider_combo = self._styled_combo([
            "OpenRouter (Free Models)", "Gemini (API Key)",
            "Vertex AI (Cloud Credits)", "Hapuppy (Cheap Models)",
        ])
        rl.addWidget(self._provider_combo)

        rl.addWidget(self._field_label("Model"))
        self._model_combo = self._styled_combo([
            "gemini-2.5-flash", "gemini-3.5-flash", "gpt-4o-mini", "deepseek-v3",
            "openai/gpt-4o-mini", "openai/gpt-oss-120b:free",
            "mistralai/mistral-nemo:free", "meta-llama/llama-3.1-8b-instruct:free",
            "google/gemma-2-27b-it:free", "gemini-3-flash-preview", "gemini-3-flash",
        ], editable=True)
        rl.addWidget(self._model_combo)

        rl.addWidget(self._field_label("API Key"))
        key_row = QHBoxLayout()
        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.Password)
        self._api_key_input.setPlaceholderText("Enter API key (not needed for Vertex AI)")
        self._api_key_input.setFixedHeight(36)
        self._style_lineedit(self._api_key_input)
        key_row.addWidget(self._api_key_input, 1)
        rl.addLayout(key_row)

        self._api_status = QLabel("")
        self._api_status.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px;")
        rl.addWidget(self._api_status)

        rl.addWidget(self._field_label("Max tokens"))
        self._max_tokens_input = QLineEdit("8192")
        self._max_tokens_input.setFixedHeight(36)
        self._style_lineedit(self._max_tokens_input)
        rl.addWidget(self._max_tokens_input)

        rl.addWidget(self._field_label("Request timeout (seconds)"))
        self._timeout_input = QLineEdit("30")
        self._timeout_input.setFixedHeight(36)
        self._style_lineedit(self._timeout_input)
        rl.addWidget(self._timeout_input)

        raw_row = QHBoxLayout()
        raw_lbl = QLabel("Allow raw config deploy")
        raw_lbl.setStyleSheet(f"color: {_C.text_sec}; font-size: 12px;")
        raw_row.addWidget(raw_lbl)
        raw_row.addStretch()
        self._raw_deploy_toggle = ToggleSwitch(checked=False)
        raw_row.addWidget(self._raw_deploy_toggle)
        rl.addLayout(raw_row)

        rl.addStretch()

        main_h.addWidget(left, 1)
        main_h.addWidget(vsep)
        main_h.addWidget(right, 1)
        return w

    # ── Settings helpers ──────────────────────────────────────────────
    def _section_title(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_C.text_pri}; font-size: 17px; font-weight: bold;")
        return lbl

    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px; margin-top: 4px;")
        return lbl

    def _styled_combo(self, items, editable=False):
        c = QComboBox()
        c.addItems(items)
        c.setEditable(editable)
        c.setFixedHeight(36)
        c.setStyleSheet(f"""
            QComboBox {{
                background: {_C.bg_card}; border: 1px solid {_C.border}; border-radius: 8px;
                color: {_C.text_pri}; padding: 0 12px; font-size: 12px;
            }}
            QComboBox:focus {{ border-color: {_C.accent}; }}
            QComboBox::drop-down {{ border: none; width: 28px; }}
            QComboBox::down-arrow {{ image: url(noimg); }}
            QComboBox QAbstractItemView {{
                background: {_C.bg_card}; border: 1px solid {_C.border}; color: {_C.text_pri};
                selection-background-color: {_C.bg_elevated};
            }}
        """)
        return c

    def _style_lineedit(self, inp):
        inp.setStyleSheet(f"""
            QLineEdit {{
                background: {_C.bg_card}; border: 1px solid {_C.border}; border-radius: 8px;
                color: {_C.text_pri}; padding: 0 12px; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {_C.accent}; }}
        """)

    def _select_settings_tab(self, idx):
        self._settings_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._settings_nav_buttons):
            if i == idx:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {_C.accent}; border: none; border-radius: 8px;
                        color: {_C.white}; font-size: 12px; text-align: left;
                        padding-left: 12px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; border: none; border-radius: 8px;
                        color: {_C.text_sec}; font-size: 12px; text-align: left; padding-left: 12px;
                    }}
                    QPushButton:hover {{ background: {_C.bg_elevated}; color: {_C.text_pri}; }}
                """)

    # ──────────────────────────────────────────────────────────────────
    # STATE MANAGEMENT
    # ──────────────────────────────────────────────────────────────────
    def _restore_state(self):
        from network_manager.config import CONFIG_FILE
        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

        prov = cfg.get("agent_provider", "openrouter")
        idx_map = {"openrouter": 0, "gemini": 1, "vertex": 2, "hapuppy": 3}
        self._provider_combo.setCurrentIndex(idx_map.get(prov, 0))
        self._model_combo.setCurrentText(cfg.get("agent_model", "openai/gpt-4o-mini"))
        key = cfg.get("gemini_api_key", "") or cfg.get("openrouter_api_key", "")
        self._api_key_input.setText(key)
        self._raw_deploy_toggle.setChecked(bool(cfg.get("agent_allow_raw_deploy", False)))
        self._max_tokens_input.setText(str(cfg.get("agent_max_tokens", "8192")))
        self._timeout_input.setText(str(cfg.get("agent_timeout", "30")))

        for tkey, toggle in self._setting_toggles.items():
            toggle.setChecked(bool(cfg.get(f"setting_{tkey}", toggle.isChecked())))

        self._refresh_device_chips()

        if self._is_worker_alive():
            self._connect_worker_signals()
            self._set_status("connected")
            self._chat_input.setEnabled(True)
            self._btn_send.setEnabled(True)
            model = getattr(self.app._copilot_worker, "model_name", "Unknown")
            self._model_badge.setText(model)
        elif key:
            QTimer.singleShot(400, self._launch_agent)

        for entry in self.app._copilot_chat_data:
            kind = entry.get("type")
            if kind == "user":
                self._chat_layout.addWidget(UserBubble(entry["text"]))
            elif kind == "ai":
                html = _render_md(entry["text"])
                self._chat_layout.addWidget(AIBubble(html))
            elif kind == "system":
                self._chat_layout.addWidget(SystemMsg(entry["text"]))

    def _update_device_count(self):
        n = len(self.app.devices) if hasattr(self.app, 'devices') else 0
        self._device_count_lbl.setText(f"  {n} device{'s' if n != 1 else ''} connected")
        if hasattr(self, '_chips_count'):
            self._chips_count.setText(f"{n} Devices")

    def _refresh_device_chips(self):
        while self._chips_container.count():
            item = self._chips_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not hasattr(self.app, 'devices'):
            self._update_device_count()
            return

        for name, model, meta in self.app.devices[:8]:
            has_config = any(model.templates.values()) if hasattr(model, 'templates') else False
            status = "configured" if has_config else ("connected" if meta.get("console_host") else "pending")
            chip = DeviceChip(name, status)
            self._chips_container.addWidget(chip)

        self._update_device_count()

    # ──────────────────────────────────────────────────────────────────
    # WORKER LIFECYCLE
    # ──────────────────────────────────────────────────────────────────
    def _is_worker_alive(self):
        w = getattr(self.app, "_copilot_worker", None)
        return w is not None and w.isRunning() and getattr(w, "_running", False)

    def _connect_worker_signals(self):
        w = self.app._copilot_worker
        if not w:
            return
        try:
            w.terminal_log_signal.connect(self._on_terminal_log, Qt.QueuedConnection)
            w.chat_response_signal.connect(self._on_chat_response, Qt.QueuedConnection)
            w.finished_signal.connect(self._on_finished, Qt.QueuedConnection)
            w.ready_signal.connect(self._on_ready, Qt.QueuedConnection)
        except Exception:
            pass

    def _disconnect_worker_signals(self):
        w = self.app._copilot_worker
        if not w:
            return
        try:
            w.terminal_log_signal.disconnect(self._on_terminal_log)
            w.chat_response_signal.disconnect(self._on_chat_response)
            w.finished_signal.disconnect(self._on_finished)
            w.ready_signal.disconnect(self._on_ready)
        except Exception:
            pass

    def _stop_worker(self):
        if self.app._copilot_worker is not None:
            self.app._copilot_history = getattr(self.app._copilot_worker, "_messages", [])
            self._disconnect_worker_signals()
            self.app._copilot_worker.stop()
            if self.app._copilot_worker.isRunning():
                self.app._copilot_worker.wait(5000)
            self.app._copilot_worker = None

    def _launch_agent(self):
        from network_manager.ai_agent import CopilotWorker
        from network_manager.config import CONFIG_FILE, GNS3_DEFAULT_URL

        api_key = self._api_key_input.text().strip()
        idx = self._provider_combo.currentIndex()
        provider_map = {0: "openrouter", 1: "gemini", 2: "vertex", 3: "hapuppy"}
        provider = provider_map.get(idx, "openrouter")

        if provider != "vertex" and not api_key:
            self._main_stack.setCurrentIndex(1)
            QMessageBox.warning(self, "Missing Key", "Please enter your API key in Settings.")
            return

        model_name = self._model_combo.currentText().strip()

        if self._is_worker_alive():
            cw = self.app._copilot_worker
            if (getattr(cw, "api_key", "") == api_key
                    and getattr(cw, "provider", "") == provider
                    and getattr(cw, "model_name", "") == model_name):
                self._set_status("connected")
                return
            self._add_system_message("Reconnecting with updated settings...")
            self.app._copilot_history = []
            self._stop_worker()
        elif self.app._copilot_worker is not None:
            self._add_system_message("Reconnecting...")
            self._stop_worker()

        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

        cfg["gemini_api_key"] = api_key
        cfg["agent_provider"] = provider
        cfg["agent_model"] = model_name
        cfg["agent_allow_raw_deploy"] = self._raw_deploy_toggle.isChecked()

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

        gns3_url = getattr(self.app, '_gns3_url', GNS3_DEFAULT_URL) or GNS3_DEFAULT_URL
        gns3_project_id = getattr(self.app, "gns3_project_id", None) or ""

        project_snapshot = self.app._build_copilot_snapshot()
        workspace_resolved = self.app._copilot_workspace_resolved()

        self._start_thinking("Connecting to agent...")

        if not hasattr(self.app, '_copilot_history'):
            self.app._copilot_history = []

        self.app._copilot_worker = CopilotWorker(
            api_key=api_key,
            gns3_url=gns3_url,
            allow_raw_deploy=self._raw_deploy_toggle.isChecked(),
            workspace_resolved=workspace_resolved,
            gns3_project_id=str(gns3_project_id) if gns3_project_id else "",
            project_snapshot=project_snapshot,
            audit_fn=self.app._write_audit_log,
            provider=provider,
            model_name=model_name,
            initial_messages=self.app._copilot_history,
        )
        self._connect_worker_signals()
        self.app._copilot_worker.start()

        self._set_status("connecting")
        self._model_badge.setText(model_name)
        self._refresh_device_chips()

    # ──────────────────────────────────────────────────────────────────
    # SIGNAL HANDLERS
    # ──────────────────────────────────────────────────────────────────
    def _on_terminal_log(self, html_text):
        # Always append to logs tab
        self._logs_raw_entries.append(html_text)
        self._logs_browser.append(html_text)
        sb = self._logs_browser.verticalScrollBar()
        sb.setValue(sb.maximum())

        # Skip empty
        clean = re.sub(r'<[^>]+>', '', html_text).strip()
        if not clean:
            return

        # Skip [User] echo
        if clean.startswith("[User]"):
            return

        # Only show live bubble AFTER user has sent a message
        if not getattr(self, '_user_has_sent', False):
            return

        # Ensure live activity bubble exists
        if not hasattr(self, '_live_bubble') or self._live_bubble is None:
            self._create_live_bubble()

        # Pipe the raw HTML directly into the live bubble browser
        self._live_browser.append(html_text)
        self._live_browser.verticalScrollBar().setValue(
            self._live_browser.verticalScrollBar().maximum()
        )

        # Update status line from clean text
        short = clean[:80]
        if hasattr(self, '_live_status_lbl'):
            self._live_status_lbl.setText(short)

        # Auto-expand on first content
        if hasattr(self, '_live_detail') and not self._live_detail.isVisible():
            self._live_detail.setVisible(True)
            if hasattr(self, '_live_expand_btn'):
                self._live_expand_btn.setIcon(Icons.collapse())

        # Force immediate repaint so updates appear live
        self._live_browser.repaint()
        self._live_bubble.repaint()
        QApplication.processEvents()

        self._scroll_chat_bottom()

    def _create_live_bubble(self):
        """Create a collapsible live-activity bubble in the chat area."""
        self._live_bubble = QFrame()
        self._live_bubble.setStyleSheet(f"""
            QFrame#liveBubble {{
                background: {_C.bg_deepest};
                border: 1px solid {_C.border};
                border-radius: 10px;
            }}
        """)
        self._live_bubble.setObjectName("liveBubble")
        outer = QVBoxLayout(self._live_bubble)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(4)

        # Header: animated dots + "Working" + status + expand btn
        header = QHBoxLayout()
        header.setSpacing(8)

        self._live_dots = ThinkingDots()
        self._live_dots.start()
        header.addWidget(self._live_dots)

        title = QLabel("Working")
        title.setStyleSheet(f"color: {_C.purple}; font-weight: bold; font-size: 12px;")
        header.addWidget(title)

        self._live_status_lbl = QLabel("")
        self._live_status_lbl.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px;")
        self._live_status_lbl.setMaximumWidth(600)
        header.addWidget(self._live_status_lbl, 1)

        self._live_expand_btn = _icon_btn(Icons.expand(), 22)
        self._live_expand_btn.clicked.connect(self._toggle_live_detail)
        header.addWidget(self._live_expand_btn)

        outer.addLayout(header)

        # Detail: scrollable text browser showing raw HTML
        self._live_detail = QWidget()
        self._live_detail.setVisible(False)
        d_lay = QVBoxLayout(self._live_detail)
        d_lay.setContentsMargins(0, 4, 0, 0)

        self._live_browser = QTextBrowser()
        self._live_browser.setOpenExternalLinks(False)
        self._live_browser.setMinimumHeight(60)
        self._live_browser.setMaximumHeight(250)
        self._live_browser.setStyleSheet(f"""
            QTextBrowser {{
                background: {_C.bg_card};
                border: 1px solid {_C.border_subtle};
                border-radius: 8px;
                color: {_C.text_sec};
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 11px;
                padding: 8px;
            }}
            {_SCROLLBAR}
        """)
        d_lay.addWidget(self._live_browser)
        outer.addWidget(self._live_detail)

        self._chat_layout.addWidget(self._live_bubble)
        self._scroll_chat_bottom()

    def _toggle_live_detail(self):
        if hasattr(self, '_live_detail'):
            vis = not self._live_detail.isVisible()
            self._live_detail.setVisible(vis)
            self._live_expand_btn.setIcon(Icons.collapse() if vis else Icons.expand())

    def _finalize_live_bubble(self):
        """Freeze the live bubble when agent responds — keep it visible."""
        if hasattr(self, '_live_bubble') and self._live_bubble:
            if hasattr(self, '_live_dots'):
                self._live_dots.stop()
            if hasattr(self, '_live_status_lbl'):
                self._live_status_lbl.setText("✓ Completed")
            # Keep expanded so user can see what happened — don't collapse
        self._live_bubble = None

    def _on_chat_response(self, text):
        self._stop_thinking()
        self._finalize_live_bubble()
        self._add_ai_message(text)
        self._tabs.setCurrentIndex(0)
        self._chat_input.setEnabled(True)
        self._btn_send.setEnabled(True)
        self._chat_input.setFocus()
        self._waiting_for_reply = False
        self._tool_cards.clear()
        self._pending_tool_cards.clear()

    def _on_finished(self, summary, success):
        self._stop_thinking()
        self._set_status("disconnected")
        if not success:
            self._add_ai_message(f"**Error:** {summary}")
        self._chat_input.setEnabled(False)
        self._btn_send.setEnabled(False)
        self._waiting_for_reply = False

    def _on_ready(self):
        self._set_status("connected")
        self._chat_input.setEnabled(True)
        self._btn_send.setEnabled(True)
        self._chat_input.setFocus()
        self._stop_thinking()

    # ──────────────────────────────────────────────────────────────────
    # CHAT
    # ──────────────────────────────────────────────────────────────────
    def _send_message(self):
        msg = self._chat_input.toPlainText().strip()
        if not msg or self._waiting_for_reply:
            return
        self._user_has_sent = True
        self._add_user_message(msg)
        self._chat_input.clear()
        self._chat_input.setFixedHeight(44)
        self._waiting_for_reply = True
        self._chat_input.setEnabled(False)
        self._btn_send.setEnabled(False)
        self._start_thinking("Processing...")
        if self.app._copilot_worker:
            self.app._copilot_worker.queue_message(msg)

    def _add_user_message(self, text):
        self._chat_layout.addWidget(UserBubble(text))
        self.app._copilot_chat_data.append({"type": "user", "text": text})
        self._scroll_chat_bottom()

    def _add_ai_message(self, text):
        html = _render_md(text)
        self._chat_layout.addWidget(AIBubble(html))
        self.app._copilot_chat_data.append({"type": "ai", "text": text})
        self._scroll_chat_bottom()

    def _add_system_message(self, text):
        self._chat_layout.addWidget(SystemMsg(text))
        self.app._copilot_chat_data.append({"type": "system", "text": text})
        self._scroll_chat_bottom()

    def _scroll_chat_bottom(self):
        QTimer.singleShot(50, lambda: self._chat_scroll.verticalScrollBar().setValue(
            self._chat_scroll.verticalScrollBar().maximum()
        ))

    def _start_thinking(self, text=""):
        self._thinking_row.setVisible(True)
        self._thinking_text.setText(text)
        self._thinking_dots.start()

    def _stop_thinking(self):
        self._thinking_dots.stop()
        self._thinking_row.setVisible(False)
        self._thinking_text.setText("")

    # ──────────────────────────────────────────────────────────────────
    # STATUS
    # ──────────────────────────────────────────────────────────────────
    def _set_status(self, state):
        colors = {
            "connected":    (_C.green,      "Connected"),
            "connecting":   (_C.amber,      "Connecting..."),
            "disconnected": (_C.red,        "Disconnected"),
            "offline":      (_C.text_muted, "Offline"),
        }
        color, label = colors.get(state, (_C.text_muted, "Offline"))
        self._status_dot.set_color(color)
        self._status_label.setText(label)
        self._status_label.setStyleSheet(f"color: {color}; font-size: 12px;")

    # ──────────────────────────────────────────────────────────────────
    # LOGS
    # ──────────────────────────────────────────────────────────────────
    def _filter_logs(self, query):
        if not query:
            self._logs_browser.setHtml("".join(self._logs_raw_entries))
            return
        filtered = [e for e in self._logs_raw_entries
                     if query.lower() in re.sub(r'<[^>]+>', '', e).lower()]
        self._logs_browser.setHtml("".join(filtered))

    def _clear_logs(self):
        self._logs_raw_entries.clear()
        self._logs_browser.setHtml(f"<span style='color:{_C.text_muted}'>Logs cleared.</span>")

    def _export_logs(self):
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(self, "Export Logs", f"ancs_logs_{ts}", "Text (*.txt);;HTML (*.html)")
        if not path:
            return
        try:
            content = "\n".join(re.sub(r'<[^>]+>', '', e) for e in self._logs_raw_entries)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            QMessageBox.information(self, "Export", f"Logs exported to:\n{path}")
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"Export failed: {ex}")

    # ──────────────────────────────────────────────────────────────────
    # SETTINGS
    # ──────────────────────────────────────────────────────────────────
    def _toggle_settings(self):
        self._main_stack.setCurrentIndex(1 if self._main_stack.currentIndex() == 0 else 0)

    def _save_settings(self):
        from network_manager.config import CONFIG_FILE
        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

        idx = self._provider_combo.currentIndex()
        provider_map = {0: "openrouter", 1: "gemini", 2: "vertex", 3: "hapuppy"}
        cfg["agent_provider"] = provider_map.get(idx, "openrouter")
        cfg["agent_model"] = self._model_combo.currentText().strip()
        cfg["gemini_api_key"] = self._api_key_input.text().strip()
        cfg["agent_allow_raw_deploy"] = self._raw_deploy_toggle.isChecked()
        cfg["agent_max_tokens"] = self._max_tokens_input.text().strip()
        cfg["agent_timeout"] = self._timeout_input.text().strip()
        for tkey, toggle in self._setting_toggles.items():
            cfg[f"setting_{tkey}"] = toggle.isChecked()

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            QMessageBox.information(self, "Settings", "Settings saved successfully!")
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"Failed to save: {ex}")

    def _test_connection(self):
        api_key = self._api_key_input.text().strip()
        idx = self._provider_combo.currentIndex()
        if idx == 2:
            self._api_status.setText("Vertex AI uses Application Default Credentials")
            self._api_status.setStyleSheet(f"color: {_C.amber}; font-size: 11px;")
            return
        if not api_key:
            self._api_status.setText("No API key provided")
            self._api_status.setStyleSheet(f"color: {_C.red}; font-size: 11px;")
            return
        if len(api_key) > 10:
            self._api_status.setText("API key format looks valid")
            self._api_status.setStyleSheet(f"color: {_C.green}; font-size: 11px;")
        else:
            self._api_status.setText("API key appears invalid (too short)")
            self._api_status.setStyleSheet(f"color: {_C.red}; font-size: 11px;")

    # ──────────────────────────────────────────────────────────────────
    # WINDOW DRAG (frameless)
    # ──────────────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() < 48:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.position().y() < 48:
            self._toggle_maximize()

    def _toggle_maximize(self):
        if self._is_maximized:
            self.showNormal()
            self._is_maximized = False
        else:
            self.showMaximized()
            self._is_maximized = True

    def _auto_resize_input(self):
        doc = self._chat_input.document()
        doc_height = int(doc.size().height()) + 20
        new_h = max(44, min(doc_height, 150))
        self._chat_input.setFixedHeight(new_h)

    def _attach_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach File", "",
            "All Files (*);;Text (*.txt *.log *.csv);;Config (*.cfg *.conf *.json *.yaml)"
        )
        if path:
            current = self._chat_input.toPlainText()
            prefix = current + "\n" if current.strip() else ""
            self._chat_input.setPlainText(f"{prefix}[Attached: {path}]")
            cursor = self._chat_input.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._chat_input.setTextCursor(cursor)
            self._chat_input.setFocus()

    def eventFilter(self, obj, event):
        if obj == self._chat_input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    return False  # Let Shift+Enter insert newline
                self._send_message()
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
