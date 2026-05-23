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
from html import unescape
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
    bg_deepest    = "#0B1018"
    bg_card       = "#131A24"
    bg_elevated   = "#1A2332"
    bg_input      = "#0D1117"
    bg_chat       = "#0F1720"
    border        = "#1E2D3D"
    border_subtle = "#182430"
    text_pri      = "#E8EDF3"
    text_sec      = "#B8C4D0"
    text_muted    = "#6B7B8D"
    accent        = "#3B82F6"
    accent_hover  = "#2563EB"
    accent_glow   = "rgba(59, 130, 246, 0.15)"
    purple        = "#A78BFA"
    purple_dim    = "rgba(167, 139, 250, 0.12)"
    green         = "#34D399"
    amber         = "#FBBF24"
    red           = "#F87171"
    white         = "#FFFFFF"
    user_bg       = "#122038"
    user_bg2      = "#18294A"
    user_border   = "#1E3A5F"


# ═══════════════════════════════════════════════════════════════════════
# ICON FACTORY — QPainter-drawn vector icons (no emoji, no SVG deps)
# ═══════════════════════════════════════════════════════════════════════
def _make_icon(draw_fn, size=20, color="#C9D1D9") -> QIcon:
    """Create a QIcon by painting with the given draw function."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
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
    p.setPen(Qt.PenStyle.NoPen)
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
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self._pulse = False
        self._pulse_phase = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self.setFixedSize(size + 8, size + 8)  # Extra room for glow ring

    def set_color(self, color: str):
        self._color = color
        self._pulse = (color == _C.green)
        if self._pulse and not self._pulse_timer.isActive():
            self._pulse_phase = 0.0
            self._pulse_timer.start(50)
        elif not self._pulse:
            self._pulse_timer.stop()
        self.update()

    def _tick_pulse(self):
        import math
        self._pulse_phase += 0.12
        if self._pulse_phase > 2 * math.pi:
            self._pulse_phase -= 2 * math.pi
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        # Glow ring when pulsing
        if self._pulse:
            import math
            alpha = int(40 + 30 * math.sin(self._pulse_phase))
            glow_r = 4 + 2 * (0.5 + 0.5 * math.sin(self._pulse_phase))
            glow_color = QColor(self._color)
            glow_color.setAlpha(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow_color)
            p.drawEllipse(QRectF(cx - glow_r - 1, cy - glow_r - 1, glow_r * 2 + 2, glow_r * 2 + 2))
        # Main dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color))
        dot_r = 3.5
        p.drawEllipse(QRectF(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2))


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
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, v):
        self._checked = v
        self._offset = 22.0 if v else 2.0
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(_C.accent) if self._checked else QColor("#374151")
        p.setBrush(track)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 48, 26, 13, 13)
        # Thumb with subtle shadow effect
        thumb_x = int(self._offset)
        shadow_col = QColor(0, 0, 0, 40)
        p.setBrush(shadow_col)
        p.drawEllipse(thumb_x + 1, 3, 22, 22)
        p.setBrush(QColor(_C.white))
        p.drawEllipse(thumb_x, 2, 22, 22)

    def mousePressEvent(self, _e):
        self._checked = not self._checked
        anim = QPropertyAnimation(self, b"offset", self)
        anim.setDuration(150)
        anim.setStartValue(self._offset)
        anim.setEndValue(22.0 if self._checked else 2.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
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
_TOOL_DISPLAY_NAMES = {
    "run_cli_on_device": "Terminal tool",
    "run_command_on_device": "Terminal tool",
    "verify_device": "Verification terminal",
    "snapshot_network_state": "Network snapshot",
    "get_network_overview": "Network overview",
    "list_all_devices": "Device inventory",
    "get_topology_links": "Topology mapper",
    "generate_device_config": "Config generator",
    "generate_and_deploy_device_config": "Generate and deploy",
    "deploy_to_device": "Deploy config",
    "trace_connectivity": "Connectivity trace",
    "audit_network": "Security audit",
    "validate_configs": "Config validator",
    "cleanup_device": "Cleanup tool",
    "bulk_deploy": "Bulk deploy",
    "calculate_subnet": "Subnet calculator",
    "get_agent_guidelines": "Guidelines tool",
}


def _friendly_tool_name(tool_name: str) -> str:
    return _TOOL_DISPLAY_NAMES.get(tool_name, tool_name.replace("_", " "))


class ToolCard(QFrame):
    def __init__(self, tool_name: str, args_preview: str = "", parent=None):
        super().__init__(parent)
        self.tool_name = tool_name
        self._expanded = False
        self._result_text = ""
        self._state = "running"

        self.setStyleSheet(f"""
            ToolCard {{
                background: rgba(11, 16, 24, 0.8);
                border: 1px solid {_C.border};
                border-left: 2px solid {_C.purple};
                border-radius: 0 8px 8px 0;
            }}
        """)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(14, 10, 14, 10)
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

        display = _friendly_tool_name(tool_name)
        if args_preview:
            short = args_preview[:52] + ("..." if len(args_preview) > 52 else "")
            display = f"{display}  {short}"
        self._name_lbl = QLabel(display)
        self._name_lbl.setStyleSheet(f"color: {_C.purple}; font-size: 12px; font-weight: 600; font-family: 'Cascadia Code', 'Consolas', monospace;")
        header.addWidget(self._name_lbl, 1)

        self._status_icon = QPushButton()
        self._status_icon.setIcon(Icons.spinner())
        self._status_icon.setIconSize(QSize(14, 14))
        self._status_icon.setFixedSize(18, 18)
        self._status_icon.setStyleSheet("border: none; background: transparent;")
        self._status_icon.setEnabled(False)
        header.addWidget(self._status_icon)

        self._status_lbl = QLabel("Running")
        self._status_lbl.setStyleSheet(f"color: {_C.accent}; font-size: 11px; font-weight: 500;")
        header.addWidget(self._status_lbl)

        self._expand_btn = _icon_btn(Icons.expand(), 22)
        self._expand_btn.clicked.connect(self._toggle_expand)
        header.addWidget(self._expand_btn)

        self._main_layout.addLayout(header)

        self._result_browser = QTextBrowser()
        self._result_browser.setMaximumHeight(200)
        self._result_browser.setVisible(False)
        self._result_browser.setStyleSheet(f"""
            QTextBrowser {{
                background: #0A0F18;
                border: 1px solid {_C.border};
                border-radius: 8px;
                color: {_C.text_sec};
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 11px;
                padding: 10px 12px;
                margin-top: 8px;
            }}
        """)
        self._main_layout.addWidget(self._result_browser)

    def set_completed(self, duration_ms: str = "", result: str = ""):
        self._state = "completed"
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
        self._state = "error"
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


class ActivityNote(QFrame):
    def __init__(self, text: str, kind: str = "status", parent=None):
        super().__init__(parent)
        colors = {
            "thinking": (_C.purple, "Analyzing"),
            "action": (_C.accent, "Using tool"),
            "status": (_C.text_muted, "Status"),
        }
        color, label = colors.get(kind, colors["status"])
        self.setStyleSheet(f"""
            ActivityNote {{
                background: rgba(19, 26, 36, 0.58);
                border: 1px solid {_C.border_subtle};
                border-radius: 8px;
            }}
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        lay.addWidget(StatusDot(color, 7))
        lbl = QLabel(f"{label}: {text}")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setStyleSheet(f"color: {_C.text_sec}; font-size: 12px; line-height: 1.35;")
        lay.addWidget(lbl, 1)


# ═══════════════════════════════════════════════════════════════════════
# MESSAGE WIDGETS
# ═══════════════════════════════════════════════════════════════════════
_MD_CSS = f"""
    body {{ color: {_C.text_sec}; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 13.5px; line-height: 1.7; }}
    h1 {{ color: {_C.text_pri}; font-size: 18px; font-weight: 700; margin: 14px 0 6px; border-bottom: 1px solid {_C.border}; padding-bottom: 6px; }}
    h2 {{ color: {_C.purple}; font-size: 15px; font-weight: 600; margin: 12px 0 4px; }}
    h3 {{ color: {_C.accent}; font-size: 14px; font-weight: 600; margin: 10px 0 4px; }}
    strong,b {{ color: #93C5FD; }}
    em {{ color: {_C.text_sec}; font-style: italic; }}
    code {{ background: rgba(59, 130, 246, 0.08); color: #93C5FD; padding: 2px 7px; border-radius: 5px; font-size: 12px; font-family: 'Cascadia Code', 'Consolas', monospace; }}
    pre {{ background: #0A0F18; border: 1px solid {_C.border}; padding: 14px 16px; border-radius: 10px; overflow-x: auto; margin: 8px 0; }}
    pre code {{ background: none; padding: 0; color: #A5D6FF; }}
    ul,ol {{ padding-left: 20px; }}
    li {{ margin-bottom: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; border-radius: 8px; overflow: hidden; }}
    th {{ background: {_C.bg_elevated}; color: {_C.purple}; padding: 8px 14px; text-align: left; border-bottom: 2px solid {_C.border}; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
    td {{ border-bottom: 1px solid {_C.border}; padding: 7px 14px; text-align: left; }}
    p {{ margin: 5px 0; }}
    a {{ color: {_C.accent}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    blockquote {{ border-left: 3px solid {_C.purple}; margin: 8px 0; padding: 4px 14px; color: {_C.text_muted}; background: {_C.purple_dim}; border-radius: 0 6px 6px 0; }}
    hr {{ border: none; height: 1px; background: {_C.border}; margin: 12px 0; }}
"""


class UserBubble(QFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(100, 4, 12, 4)

        outer.addStretch()

        bubble = QFrame()
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        bubble.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_C.user_bg}, stop:1 {_C.user_bg2});
                border: 1px solid rgba(30, 58, 95, 0.6);
                border-radius: 16px;
                border-bottom-right-radius: 4px;
                padding: 12px 18px;
            }}
        """)
        blay = QVBoxLayout(bubble)
        blay.setContentsMargins(0, 0, 0, 0)
        blay.setSpacing(4)

        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setTextFormat(Qt.TextFormat.PlainText)
        msg.setMaximumWidth(520)
        msg.setStyleSheet(f"color: {_C.text_pri}; font-size: 13.5px; border: none; background: none; line-height: 1.5;")
        blay.addWidget(msg)

        ts = QLabel(datetime.now().strftime("%I:%M %p"))
        ts.setAlignment(Qt.AlignmentFlag.AlignRight)
        ts.setStyleSheet(f"color: rgba(107, 123, 141, 0.7); font-size: 9px; border: none; background: none;")
        blay.addWidget(ts)

        outer.addWidget(bubble)


class AIBubble(QFrame):
    def __init__(self, html_content: str, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(1120)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(f"""
            AIBubble {{
                background: rgba(19, 26, 36, 0.5);
                border-left: 2px solid {_C.accent};
                border-radius: 0 10px 10px 0;
                margin: 2px 0;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 42, 12)
        lay.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        sender = QLabel("✦ ANCS Agent")
        sender.setStyleSheet(f"color: {_C.accent}; font-weight: 700; font-size: 12px; letter-spacing: 0.5px; border: none; background: none;")
        header.addWidget(sender)
        header.addStretch()
        ts = QLabel(datetime.now().strftime("%I:%M %p"))
        ts.setStyleSheet(f"color: rgba(107, 123, 141, 0.6); font-size: 9px; border: none; background: none;")
        header.addWidget(ts)
        lay.addLayout(header)

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
        browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        doc = browser.document()
        doc.setTextWidth(900)
        h = max(44, int(doc.size().height()) + 18)
        browser.setFixedHeight(min(h, 1800))
        lay.addWidget(browser)

        self.tool_container = QVBoxLayout()
        self.tool_container.setSpacing(6)
        lay.addLayout(self.tool_container)


class SystemMsg(QFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        line_l = QFrame()
        line_l.setFixedHeight(1)
        line_l.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 transparent, stop:1 {_C.border});")
        lay.addWidget(line_l, 1)
        lbl = QLabel(f"  {text}  ")
        lbl.setStyleSheet(f"""
            color: {_C.text_muted}; font-size: 10px; font-weight: 500;
            letter-spacing: 0.5px; background: transparent; border: none;
        """)
        lay.addWidget(lbl)
        line_r = QFrame()
        line_r.setFixedHeight(1)
        line_r.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {_C.border}, stop:1 transparent);")
        lay.addWidget(line_r, 1)


# ═══════════════════════════════════════════════════════════════════════
# SCROLLBAR STYLESHEET
# ═══════════════════════════════════════════════════════════════════════
_SCROLLBAR = f"""
    QScrollBar:vertical {{
        background: transparent; width: 7px; margin: 4px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(88, 140, 210, 80); border-radius: 3px; min-height: 36px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(88, 166, 255, 150);
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
        super().__init__(parent_app, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowSystemMenuHint)
        self.app = parent_app
        self.setMinimumSize(900, 600)
        self.resize(1060, 760)
        self._drag_pos = None
        self._is_maximized = False

        self._tool_cards: dict[str, list[ToolCard]] = {}
        self._pending_tool_cards: list[ToolCard] = []
        self._tool_section = None
        self._tool_list = None
        self._tool_status_lbl = None
        self._tool_header = None
        self._logs_tool_cards: dict[str, list[ToolCard]] = {}
        self._logs_tool_section = None
        self._logs_tool_list = None
        self._logs_tool_status_lbl = None
        self._logs_tool_empty = None
        self._waiting_for_reply = False
        self._activity_note_keys: set[tuple[str, str]] = set()
        self._log_line_keys: set[str] = set()
        self._closing_for_app = False
        self._chips_timer = QTimer(self)
        self._attached_files: list[str] = []
        self._attach_count_btn = None

        if not hasattr(self.app, "_copilot_chat_data"):
            self.app._copilot_chat_data = []

        self._build_ui()
        self._restore_state()

        self._chips_timer.setInterval(4000)
        self._chips_timer.timeout.connect(self._refresh_device_chips)
        self._chips_timer.start()

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
        sep.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 transparent, stop:0.2 {_C.border_subtle}, "
            f"stop:0.8 {_C.border_subtle}, stop:1 transparent);"
        )
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
        title.setStyleSheet(f"color: {_C.text_pri}; font-size: 16px; font-weight: 800; letter-spacing: 1px;")
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
            QTabBar {{
                background: {_C.bg_card};
                border-bottom: 1px solid {_C.border};
            }}
            QTabBar::tab {{
                background: transparent;
                color: {_C.text_muted};
                padding: 12px 32px;
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-bottom: 2px solid transparent;
                margin-right: 0px;
                letter-spacing: 0.3px;
            }}
            QTabBar::tab:selected {{
                color: {_C.text_pri};
                border-bottom: 2px solid {_C.accent};
                background: rgba(59, 130, 246, 0.05);
            }}
            QTabBar::tab:hover:!selected {{
                color: {_C.text_sec};
                border-bottom: 2px solid rgba(59, 130, 246, 0.3);
                background: rgba(255, 255, 255, 0.02);
            }}
        """)
        self._tabs.addTab(self._build_chat_tab(), "💬  Chat")
        self._tabs.addTab(self._build_logs_tab(), "📋  Execution Logs")
        lay.addWidget(self._tabs, 1)

        lay.addWidget(self._build_input_bar())

        return page

    # ── CHAT TAB ──────────────────────────────────────────────────────
    def _build_chat_tab(self):
        w = QWidget()
        w.setStyleSheet(f"background: {_C.bg_deepest};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Device chips bar
        chips_bar = QWidget()
        chips_bar.setFixedHeight(38)
        chips_bar.setStyleSheet(f"""
            QWidget {{
                background: {_C.bg_card};
                border-bottom: 1px solid {_C.border};
            }}
        """)
        chips_row = QHBoxLayout(chips_bar)
        chips_row.setContentsMargins(16, 0, 16, 0)
        chips_row.setSpacing(8)

        chips_dot = StatusDot(_C.accent, 7)
        chips_row.addWidget(chips_dot)

        self._chips_count = QLabel("0 Devices")
        self._chips_count.setStyleSheet(f"color: {_C.text_sec}; font-size: 11px; font-weight: 600; letter-spacing: 0.3px;")
        chips_row.addWidget(self._chips_count)

        self._chips_container = QHBoxLayout()
        self._chips_container.setSpacing(6)
        chips_row.addLayout(self._chips_container)

        chips_row.addStretch()

        self._btn_topology = QPushButton("View Topology")
        self._btn_topology.setFixedHeight(26)
        self._btn_topology.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_topology.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {_C.border};
                border-radius: 13px;
                color: {_C.text_muted};
                padding: 0 14px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {_C.accent};
                color: {_C.accent};
                background: {_C.accent_glow};
            }}
        """)
        self._btn_topology.clicked.connect(self._open_topology)
        chips_row.addWidget(self._btn_topology)

        lay.addWidget(chips_bar)

        # Chat scroll area
        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chat_scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {_C.bg_chat};
                border: none;
            }}
            {_SCROLLBAR}
        """)

        self._chat_content = QWidget()
        self._chat_content.setStyleSheet(f"background: {_C.bg_chat};")
        self._chat_layout = QVBoxLayout(self._chat_content)
        self._chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._chat_layout.setContentsMargins(16, 16, 16, 16)
        self._chat_layout.setSpacing(6)
        self._chat_scroll.setWidget(self._chat_content)

        lay.addWidget(self._chat_scroll, 1)

        # Thinking row
        self._thinking_row = QWidget()
        self._thinking_row.setVisible(False)
        self._thinking_row.setStyleSheet(f"""
            QWidget {{
                background: {_C.bg_card};
                border-top: 1px solid {_C.border};
            }}
        """)
        tlay = QHBoxLayout(self._thinking_row)
        tlay.setContentsMargins(16, 6, 16, 6)
        self._thinking_text = QLabel("")
        self._thinking_text.setStyleSheet(f"color: {_C.accent}; font-size: 12px; font-weight: 500;")
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
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Toolbar bar
        toolbar_widget = QWidget()
        toolbar_widget.setFixedHeight(48)
        toolbar_widget.setStyleSheet(f"""
            QWidget {{
                background: {_C.bg_card};
                border-bottom: 1px solid {_C.border};
            }}
        """)
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(16, 0, 16, 0)
        toolbar.setSpacing(10)

        logs_title = QLabel("Execution Logs")
        logs_title.setStyleSheet(f"color: {_C.text_muted}; font-size: 12px; font-weight: 600; letter-spacing: 0.5px;")
        toolbar.addWidget(logs_title)

        toolbar.addStretch()

        self._logs_search = QLineEdit()
        self._logs_search.setPlaceholderText("🔍  Filter logs...")
        self._logs_search.setFixedWidth(240)
        self._logs_search.setFixedHeight(30)
        self._logs_search.setStyleSheet(f"""
            QLineEdit {{
                background: {_C.bg_deepest};
                border: 1px solid {_C.border};
                border-radius: 15px;
                color: {_C.text_sec};
                padding: 0 14px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid rgba(59, 130, 246, 0.6);
                background: rgba(11, 16, 24, 0.9);
            }}
        """)
        self._logs_search.textChanged.connect(self._filter_logs)
        toolbar.addWidget(self._logs_search)

        _log_btn_style = f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {_C.border};
                border-radius: 15px;
                color: {_C.text_muted};
                padding: 0 16px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {_C.accent};
                color: {_C.text_sec};
                background: {_C.accent_glow};
            }}
        """

        btn_clear = QPushButton("  Clear")
        btn_clear.setIcon(Icons.clear())
        btn_clear.setFixedHeight(30)
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet(_log_btn_style)
        btn_clear.clicked.connect(self._clear_logs)
        toolbar.addWidget(btn_clear)

        btn_export = QPushButton("  Export")
        btn_export.setIcon(Icons.export())
        btn_export.setFixedHeight(30)
        btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export.setStyleSheet(_log_btn_style)
        btn_export.clicked.connect(self._export_logs)
        toolbar.addWidget(btn_export)

        lay.addWidget(toolbar_widget)

        # Logs content area
        logs_container = QWidget()
        logs_container.setStyleSheet(f"background: {_C.bg_deepest};")
        logs_lay = QVBoxLayout(logs_container)
        logs_lay.setContentsMargins(16, 12, 16, 12)
        logs_lay.setSpacing(10)

        self._logs_tool_section = QFrame()
        self._logs_tool_section.setObjectName("logsToolSection")
        self._logs_tool_section.setStyleSheet(f"""
            QFrame#logsToolSection {{
                background: rgba(11, 16, 24, 0.55);
                border: 1px solid {_C.border_subtle};
                border-radius: 10px;
            }}
        """)
        logs_tool_outer = QVBoxLayout(self._logs_tool_section)
        logs_tool_outer.setContentsMargins(12, 10, 12, 10)
        logs_tool_outer.setSpacing(8)

        logs_tool_header = QHBoxLayout()
        logs_tool_header.setSpacing(8)
        logs_tool_title = QLabel("Tool calls")
        logs_tool_title.setStyleSheet(f"color: {_C.accent}; font-size: 12px; font-weight: 700;")
        logs_tool_header.addWidget(logs_tool_title)
        logs_tool_header.addStretch()
        self._logs_tool_status_lbl = QLabel("Idle")
        self._logs_tool_status_lbl.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px;")
        logs_tool_header.addWidget(self._logs_tool_status_lbl)
        logs_tool_outer.addLayout(logs_tool_header)

        self._logs_tool_list = QVBoxLayout()
        self._logs_tool_list.setSpacing(6)
        self._logs_tool_empty = QLabel("No tool calls yet.")
        self._logs_tool_empty.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px;")
        self._logs_tool_list.addWidget(self._logs_tool_empty)
        logs_tool_outer.addLayout(self._logs_tool_list)

        logs_lay.addWidget(self._logs_tool_section)

        self._logs_browser = QTextBrowser()
        self._logs_browser.setOpenExternalLinks(False)
        self._logs_browser.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._logs_browser.setStyleSheet(f"""
            QTextBrowser {{
                background: #0D141E;
                border: 1px solid {_C.border_subtle};
                border-radius: 12px;
                color: {_C.text_sec};
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 11.5px;
                padding: 18px;
                line-height: 1.55;
            }}
            {_SCROLLBAR}
        """)
        self._logs_browser.setHtml(
            f"<div style='text-align: center; padding: 40px 0;'>"
            f"<span style='color: {_C.text_muted}; font-size: 13px;'>📋 Tool execution logs will stream here...</span>"
            f"</div>"
        )
        self._logs_raw_entries: list[str] = []
        logs_lay.addWidget(self._logs_browser, 1)

        lay.addWidget(logs_container, 1)

        return w

    # ── INPUT BAR ─────────────────────────────────────────────────────
    def _build_input_bar(self):
        bar = QWidget()
        bar.setStyleSheet(f"""
            QWidget {{
                background: {_C.bg_card};
                border-top: 1px solid {_C.border};
            }}
        """)
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(8)

        self._chat_input = QTextEdit()
        self._chat_input.setPlaceholderText("Ask ANCS anything...")
        self._chat_input.setMinimumHeight(44)
        self._chat_input.setMaximumHeight(150)
        self._chat_input.setAcceptRichText(False)
        self._chat_input.setStyleSheet(f"""
            QTextEdit {{
                background: {_C.bg_card};
                border: 1.5px solid {_C.border};
                border-radius: 12px;
                color: {_C.text_pri};
                padding: 10px 16px;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                selection-background-color: {_C.accent};
            }}
            QTextEdit:focus {{
                border: 1.5px solid rgba(59, 130, 246, 200);
                background: rgba(22, 27, 34, 250);
            }}
            {_SCROLLBAR}
        """)
        self._chat_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chat_input.setEnabled(False)
        self._chat_input.installEventFilter(self)
        self._chat_input.textChanged.connect(self._auto_resize_input)
        outer.addWidget(self._chat_input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._attach_count_btn = QPushButton("📎  0")
        self._attach_count_btn.setFixedSize(42, 30)
        self._attach_count_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach_count_btn.setToolTip("Attach file")
        self._attach_count_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {_C.border};
                border-radius: 15px;
                color: {_C.text_muted};
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {_C.accent};
                color: {_C.text_sec};
                background: {_C.accent_glow};
            }}
        """)
        self._attach_count_btn.clicked.connect(self._attach_file)
        btn_row.addWidget(self._attach_count_btn)

        btn_row.addStretch()

        hint = QLabel("Shift + Enter for new line")
        hint.setStyleSheet(f"color: {_C.text_muted}; font-size: 10px;")
        btn_row.addWidget(hint)

        btn_row.addSpacing(4)

        self._btn_send = QPushButton("  Send")
        self._btn_send.setIcon(Icons.send())
        self._btn_send.setIconSize(QSize(16, 16))
        self._btn_send.setFixedHeight(36)
        self._btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_send.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #3B82F6);
                border: 1px solid rgba(59, 130, 246, 100);
                border-radius: 10px;
                color: {_C.white};
                font-size: 13px;
                font-weight: bold;
                padding: 0 22px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #4F8EF7);
                border: 1px solid rgba(96, 165, 250, 160);
            }}
            QPushButton:disabled {{ background: {_C.border}; color: {_C.text_muted}; border: none; }}
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
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
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
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
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
        btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
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
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
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
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

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
            w.terminal_log_signal.connect(self._on_terminal_log, Qt.ConnectionType.QueuedConnection)
            w.chat_response_signal.connect(self._on_chat_response, Qt.ConnectionType.QueuedConnection)
            w.finished_signal.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)
            w.ready_signal.connect(self._on_ready, Qt.ConnectionType.QueuedConnection)
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
        # Skip empty
        clean = re.sub(r'<[^>]+>', '', html_text).strip()
        if not clean:
            return

        if clean.startswith("[Thinking]") or "[Thinking]" in clean:
            key = re.sub(r"\s+", " ", clean).strip().lower()
            if key in self._log_line_keys:
                return
            self._log_line_keys.add(key)

        # Always append to logs tab after deduping repeated model thought parts.
        self._logs_raw_entries.append(html_text)
        self._logs_browser.append(html_text)
        sb = self._logs_browser.verticalScrollBar()
        sb.setValue(sb.maximum())

        # Skip [User] echo
        if clean.startswith("[User]"):
            return

        # Startup/session-pool messages belong in Execution Logs only. The chat
        # activity panel starts after the user asks the agent to do something.
        if not getattr(self, '_user_has_sent', False):
            return

        handled_activity = self._handle_tool_log(clean)

        # Tool calls and agent phases now render as structured cards in chat.
        # Keep the full raw stream in Execution Logs, but avoid duplicating it
        # as an unreadable live log blob in the conversation.
        if handled_activity:
            return

        # Unstructured device output stays in the Execution Logs tab. Showing it
        # inline made the chat feel like a raw terminal instead of an agent.
        return

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
        self._live_bubble = None  # type: ignore[assignment]

    def _on_chat_response(self, text):
        self._stop_thinking()
        self._finalize_live_bubble()
        self._add_ai_message(text)
        self._tabs.setCurrentIndex(0)
        self._chat_input.setEnabled(True)
        self._btn_send.setEnabled(True)
        self._chat_input.setFocus()
        self._waiting_for_reply = False
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
        if self._is_worker_alive():
            model = getattr(self.app._copilot_worker, "model_name", "Unknown")
            self._model_badge.setText(model)
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
        self._clear_tool_section()
        self._clear_logs_tool_section()
        self._add_user_message(msg)
        self._chat_input.clear()
        self._chat_input.setFixedHeight(44)
        self._attached_files.clear()
        if self._attach_count_btn is not None:
            self._attach_count_btn.setText("0")
        self._waiting_for_reply = True
        self._chat_input.setEnabled(False)
        self._btn_send.setEnabled(False)
        self._start_thinking("Processing...")
        self._ensure_live_bubble()
        self._update_live_status("Thinking...")
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

    def _ensure_tool_section(self):
        if self._tool_section is not None:
            return

        self._tool_section = QFrame()
        self._tool_section.setObjectName("toolSection")
        self._tool_section.setStyleSheet(f"""
            QFrame#toolSection {{
                background: rgba(11, 16, 24, 0.34);
                border: 1px solid {_C.border_subtle};
                border-radius: 10px;
            }}
        """)
        outer = QVBoxLayout(self._tool_section)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._tool_header = QLabel("Agent activity")
        self._tool_header.setStyleSheet(f"color: {_C.accent}; font-size: 12px; font-weight: 700;")
        header.addWidget(self._tool_header)
        header.addStretch()
        self._tool_status_lbl = QLabel("Working...")
        self._tool_status_lbl.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px;")
        header.addWidget(self._tool_status_lbl)
        outer.addLayout(header)

        self._tool_list = QVBoxLayout()
        self._tool_list.setSpacing(6)
        outer.addLayout(self._tool_list)

        self._chat_layout.addWidget(self._tool_section)
        self._scroll_chat_bottom()

    def _clear_logs_tool_section(self):
        if self._logs_tool_list is None:
            return
        while self._logs_tool_list.count():
            item = self._logs_tool_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._logs_tool_cards.clear()
        self._logs_tool_empty = QLabel("No tool calls yet.")
        self._logs_tool_empty.setStyleSheet(f"color: {_C.text_muted}; font-size: 11px;")
        self._logs_tool_list.addWidget(self._logs_tool_empty)
        if self._logs_tool_status_lbl is not None:
            self._logs_tool_status_lbl.setText("Idle")

    def _find_logs_tool_card(self, tool_name: str):
        cards = self._logs_tool_cards.get(tool_name) or []
        for card in cards:
            if getattr(card, "_state", "running") == "running":
                return card
        return cards[-1] if cards else None

    def _set_logs_tool_status(self, tool_name: str):
        if self._logs_tool_status_lbl is None:
            return
        label = "Working..."
        low = tool_name.lower()
        if "run_cli" in low or "command" in low:
            label = "Using terminal..."
        elif "snapshot" in low or "overview" in low:
            label = "Inspecting network..."
        elif "generate" in low:
            label = "Generating config..."
        elif "subnet" in low:
            label = "Calculating subnet..."
        elif "deploy" in low or "send" in low:
            label = "Applying configurations..."
        self._logs_tool_status_lbl.setText(label)

    def _ensure_live_bubble(self):
        if getattr(self, "_live_bubble", None) is None:
            self._create_live_bubble()

    def _update_live_status(self, text: str):
        if hasattr(self, "_live_status_lbl") and self._live_status_lbl is not None:
            self._live_status_lbl.setText(text[:120])

    def _append_live_detail(self, text: str):
        if hasattr(self, "_live_browser") and self._live_browser is not None:
            safe = text.replace("<", "&lt;").replace(">", "&gt;")
            self._live_browser.append(safe)

    def _add_activity_note(self, text: str, kind: str = "status"):
        self._ensure_tool_section()
        if self._tool_list is None:
            return
        text = " ".join((text or "").split())
        if not text:
            return
        if len(text) > 260:
            text = text[:257].rstrip() + "..."
        key = (kind, text.lower())
        if key in self._activity_note_keys:
            return
        self._activity_note_keys.add(key)
        self._tool_list.addWidget(ActivityNote(text, kind))
        self._scroll_chat_bottom()

    def _clear_tool_section(self):
        if self._tool_section is None:
            return
        self._chat_layout.removeWidget(self._tool_section)
        self._tool_section.deleteLater()
        self._tool_section = None
        self._tool_list = None
        self._tool_status_lbl = None
        self._tool_header = None
        self._tool_cards.clear()
        self._activity_note_keys.clear()

    def _handle_tool_log(self, clean_text: str) -> bool:
        clean_text = unescape(clean_text).replace("\xa0", " ")
        call_match = re.search(r"\[Tool Call\]\s+([\w.]+)\((.*)\)", clean_text)
        result_match = re.search(r"\[Tool Result\]\s+([\w.]+)\s+(?:→|->|â†’)\s+(\d+)ms\s+\|\s+(.*)", clean_text)
        error_match = re.search(r"\[Tool Error\]\s+([\w.]+):\s+(.*)", clean_text)
        legacy_tool_match = re.search(r"\[Tool\]\s+([\w.]+)\((.*?)\)(?:\s*(?:â†’|->|Ã¢â€ â€™)\s*(.*))?", clean_text)
        action_match = re.search(r"\[Agent Action\]\s*(.*)", clean_text)
        thinking_match = re.search(r"\[Thinking\]\s*(.*)", clean_text)
        copilot_match = re.search(r"\[Copilot\]\s*(.*)", clean_text)

        if action_match:
            action_text = action_match.group(1).strip()
            self._add_activity_note(action_text, "action")
            if self._tool_status_lbl is not None:
                self._tool_status_lbl.setText(action_text[:120])
            if self._logs_tool_status_lbl is not None:
                self._logs_tool_status_lbl.setText(action_text[:120])
            self._ensure_live_bubble()
            self._update_live_status(action_text or "Working...")
            self._append_live_detail(clean_text)
            return True

        if call_match:
            tool_name = call_match.group(1)
            args_preview = call_match.group(2) or ""
            self._ensure_tool_section()
            if self._tool_list is not None:
                card = ToolCard(tool_name, args_preview)
                self._tool_cards.setdefault(tool_name, []).append(card)
                self._tool_list.addWidget(card)
            if self._logs_tool_list is not None:
                if self._logs_tool_empty is not None:
                    self._logs_tool_empty.deleteLater()
                    self._logs_tool_empty = None
                logs_card = ToolCard(tool_name, args_preview)
                self._logs_tool_cards.setdefault(tool_name, []).append(logs_card)
                self._logs_tool_list.addWidget(logs_card)
            self._set_tool_status(tool_name)
            self._set_logs_tool_status(tool_name)
            self._ensure_live_bubble()
            self._update_live_status(f"Calling {tool_name}...")
            self._append_live_detail(clean_text)
            self._scroll_chat_bottom()
            return True

        if legacy_tool_match:
            tool_name = legacy_tool_match.group(1)
            args_preview = legacy_tool_match.group(2) or ""
            result_preview = legacy_tool_match.group(3) or ""
            self._ensure_tool_section()
            card = self._find_tool_card(tool_name)
            if card is None and self._tool_list is not None:
                card = ToolCard(tool_name, args_preview)
                self._tool_cards.setdefault(tool_name, []).append(card)
                self._tool_list.addWidget(card)
            logs_card = self._find_logs_tool_card(tool_name)
            if logs_card is None and self._logs_tool_list is not None:
                if self._logs_tool_empty is not None:
                    self._logs_tool_empty.deleteLater()
                    self._logs_tool_empty = None
                logs_card = ToolCard(tool_name, args_preview)
                self._logs_tool_cards.setdefault(tool_name, []).append(logs_card)
                self._logs_tool_list.addWidget(logs_card)
            if card and result_preview:
                card.set_completed("", result_preview)
            elif card and "complete" in clean_text.lower():
                card.set_completed("", clean_text)
            if logs_card and result_preview:
                logs_card.set_completed("", result_preview)
            elif logs_card and "complete" in clean_text.lower():
                logs_card.set_completed("", clean_text)
            self._set_tool_status(tool_name)
            self._set_logs_tool_status(tool_name)
            self._ensure_live_bubble()
            self._update_live_status(f"Completed {tool_name}")
            self._append_live_detail(clean_text)
            self._scroll_chat_bottom()
            return True

        if result_match:
            tool_name = result_match.group(1)
            duration_ms = result_match.group(2)
            result_preview = result_match.group(3) or ""
            card = self._find_tool_card(tool_name)
            if card:
                card.set_completed(duration_ms, result_preview)
            logs_card = self._find_logs_tool_card(tool_name)
            if logs_card:
                logs_card.set_completed(duration_ms, result_preview)
            if self._tool_status_lbl is not None:
                self._tool_status_lbl.setText("Completed")
            if self._logs_tool_status_lbl is not None:
                self._logs_tool_status_lbl.setText("Completed")
            self._ensure_live_bubble()
            self._update_live_status(f"Completed {tool_name}")
            self._append_live_detail(clean_text)
            self._scroll_chat_bottom()
            return True

        if error_match:
            tool_name = error_match.group(1)
            error_text = error_match.group(2) or ""
            card = self._find_tool_card(tool_name)
            if card:
                card.set_error(error_text)
            logs_card = self._find_logs_tool_card(tool_name)
            if logs_card:
                logs_card.set_error(error_text)
            if self._tool_status_lbl is not None:
                self._tool_status_lbl.setText("Error")
            if self._logs_tool_status_lbl is not None:
                self._logs_tool_status_lbl.setText("Error")
            self._ensure_live_bubble()
            self._update_live_status(f"Error in {tool_name}")
            self._append_live_detail(clean_text)
            self._scroll_chat_bottom()
            return True

        if thinking_match:
            thought = thinking_match.group(1).strip()
            self._add_activity_note(thought or "Analyzing request...", "thinking")
            if self._tool_status_lbl is not None:
                self._tool_status_lbl.setText("Analyzing request...")
            self._start_thinking("Analyzing...")
            if self._logs_tool_status_lbl is not None:
                self._logs_tool_status_lbl.setText("Analyzing...")
            self._ensure_live_bubble()
            self._update_live_status("Analyzing...")
            self._append_live_detail(clean_text)
            self._scroll_chat_bottom()
            return True

        if copilot_match:
            status = copilot_match.group(1).strip()
            if status:
                self._add_activity_note(status, "status")
                if self._tool_status_lbl is not None:
                    self._tool_status_lbl.setText(status[:120])
                self._start_thinking(status[:80])
                if self._logs_tool_status_lbl is not None:
                    self._logs_tool_status_lbl.setText(status[:120])
                self._ensure_live_bubble()
                self._update_live_status(status)
                self._append_live_detail(clean_text)
                self._scroll_chat_bottom()
                return True

        return False

    def _find_tool_card(self, tool_name: str):
        cards = self._tool_cards.get(tool_name) or []
        for card in cards:
            if getattr(card, "_state", "running") == "running":
                return card
        return cards[-1] if cards else None

    def _set_tool_status(self, tool_name: str):
        if self._tool_status_lbl is None:
            return
        label = "Working..."
        low = tool_name.lower()
        if "run_cli" in low or "command" in low:
            label = "Using terminal..."
        elif "snapshot" in low or "overview" in low:
            label = "Inspecting network..."
        elif "generate" in low:
            label = "Generating config..."
        elif "subnet" in low:
            label = "Calculating subnet..."
        elif "deploy" in low or "send" in low:
            label = "Applying configurations..."
        self._tool_status_lbl.setText(label)

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

    def _open_topology(self):
        if hasattr(self.app, "open_topology"):
            self.app.open_topology()

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
        self._log_line_keys.clear()
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
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 48:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
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
            self._attached_files.append(path)
            if self._attach_count_btn is not None:
                self._attach_count_btn.setText(str(len(self._attached_files)))
            current = self._chat_input.toPlainText()
            prefix = current + "\n" if current.strip() else ""
            self._chat_input.setPlainText(f"{prefix}[Attached: {path}]")
            cursor = self._chat_input.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._chat_input.setTextCursor(cursor)
            self._chat_input.setFocus()

    def eventFilter(self, obj, event):
        if obj == self._chat_input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False  # Let Shift+Enter insert newline
                self._send_message()
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        if self._closing_for_app:
            self._chips_timer.stop()
            event.accept()
            return
        event.ignore()
        self.hide()
