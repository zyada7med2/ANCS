"""
Interactive CLI terminal panel — PySide6 version.
Maintains a persistent Telnet session so the user can type raw CLI commands.
"""
import threading
import asyncio
import queue

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCharFormat, QColor
from .utils import apply_responsive_geometry
from ..network.sender import Sender

try:
    import telnetlib3
except Exception:
    telnetlib3 = None

DARK = """
    QDialog { background-color: #0D1117; }
    QLabel { color: #C9D1D9; background: transparent; }
    QPlainTextEdit { background-color: #161B22; color: #C9D1D9; border: none;
                     font-family: 'Courier New'; font-size: 11px; padding: 6px; }
    QLineEdit { background-color: #161B22; color: #C9D1D9; border: none;
                font-family: 'Courier New'; font-size: 11px; padding: 6px; }
    QPushButton { background-color: #161B22; color: #8B949E; border: none;
                  border-radius: 6px; padding: 6px 14px; }
    QPushButton:hover { background-color: #1F2630; color: white; }
    QPushButton#connect { background-color: #183a18; color: #3FB950; font-weight: bold; }
    QPushButton#disconnect { background-color: #3a1818; color: #F85149; }
    QPushButton#send { background-color: #58A6FF; color: white; font-weight: bold; }
"""

_COLORS = {
    "success": "#3FB950", "danger": "#F85149", "warn": "#D29922",
    "muted": "#8B949E", "accent": "#58A6FF",
}


class TerminalPanel(QDialog):
    def __init__(self, parent, host: str, port: int, device_name: str = "",
                 username: str = "", password: str = "", enable_pw: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Terminal \u2014 {device_name}")
        self.setStyleSheet(DARK)
        apply_responsive_geometry(self, 740, 500, min_w=540, min_h=360)

        self.device_name = device_name
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.enable_pw = enable_pw

        self._running = False
        self._loop = None
        self._async_queue = None
        self._resp_queue = queue.Queue()
        self._poll_timer = None
        self._thread = None
        self._cmd_history: list[str] = []
        self._history_idx: int = -1

        self._build_ui()

        if telnetlib3 is None:
            self._append("[error] telnetlib3 is not installed\n", "danger")
            self.btn_connect.setEnabled(False)
        else:
            QTimer.singleShot(300, self._connect)

        self.show()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 8, 8, 8)
        lbl_name = QLabel(f"  {self.device_name}")
        lbl_name.setStyleSheet("font-size: 13px; font-weight: bold;")
        hdr.addWidget(lbl_name)

        self.lbl_status = QLabel("\u2b24 disconnected")
        self.lbl_status.setStyleSheet(f"color: {_COLORS['danger']};")
        hdr.addWidget(self.lbl_status)

        lbl_addr = QLabel(f"{self.host}:{self.port}")
        lbl_addr.setStyleSheet("color: #8B949E; font-size: 9px;")
        hdr.addStretch()
        hdr.addWidget(lbl_addr)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_output)
        hdr.addWidget(btn_clear)

        btn_disc = QPushButton("Disconnect")
        btn_disc.setObjectName("disconnect")
        btn_disc.clicked.connect(self._disconnect)
        hdr.addWidget(btn_disc)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setObjectName("connect")
        self.btn_connect.clicked.connect(self._connect)
        hdr.addWidget(self.btn_connect)

        layout.addLayout(hdr)

        self.txt_out = QPlainTextEdit()
        self.txt_out.setReadOnly(True)
        layout.addWidget(self.txt_out, 1)

        inp = QHBoxLayout()
        inp.setContentsMargins(8, 8, 8, 8)
        lbl_prompt = QLabel(">")
        lbl_prompt.setStyleSheet("color: #3FB950; font-family: 'Courier New'; font-size: 14px; font-weight: bold;")
        inp.addWidget(lbl_prompt)

        self.ent_cmd = QLineEdit()
        self.ent_cmd.returnPressed.connect(self._send_command)
        inp.addWidget(self.ent_cmd, 1)

        btn_send = QPushButton("Send")
        btn_send.setObjectName("send")
        btn_send.clicked.connect(self._send_command)
        inp.addWidget(btn_send)
        layout.addLayout(inp)

        self._append(f"Terminal ready \u2014 {self.device_name}  ({self.host}:{self.port})\nConnecting...\n\n", "muted")

    def keyPressEvent(self, event):
        if self.ent_cmd.hasFocus():
            if event.key() == Qt.Key_Up:
                self._history_up()
                return
            elif event.key() == Qt.Key_Down:
                self._history_down()
                return
        super().keyPressEvent(event)

    def _connect(self):
        if self._running:
            return
        self._running = True
        self.lbl_status.setText("\u2b24 connecting...")
        self.lbl_status.setStyleSheet(f"color: {_COLORS['warn']};")
        self.btn_connect.setEnabled(False)
        self._append(f"Connecting to {self.host}:{self.port}...\n", "muted")
        self._thread = threading.Thread(target=self._telnet_loop, daemon=True)
        self._thread.start()
        self._schedule_poll()

    def _disconnect(self):
        self._running = False
        if self._loop and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        self.lbl_status.setText("\u2b24 disconnected")
        self.lbl_status.setStyleSheet(f"color: {_COLORS['danger']};")
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("Reconnect")
        self._append("\nDisconnected.\n", "warn")

    def _telnet_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_session())
        except (RuntimeError, asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as exc:
            self._resp_queue.put(("error", str(exc)))
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
        self._running = False
        QTimer.singleShot(0, lambda: self._update_status_disconnected())

    def _update_status_disconnected(self):
        try:
            self.lbl_status.setText("\u2b24 disconnected")
            self.lbl_status.setStyleSheet(f"color: {_COLORS['danger']};")
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("Reconnect")
        except Exception:
            pass

    async def _async_session(self):
        self._async_queue = asyncio.Queue()
        try:
            reader, writer = await asyncio.wait_for(
                telnetlib3.open_connection(self.host, self.port), timeout=10)
        except Exception as exc:
            self._resp_queue.put(("error", f"Connection failed: {exc}"))
            return
        self._resp_queue.put(("connected", None))

        async def read_burst(max_wait=1.5):
            buf = ""
            deadline = asyncio.get_event_loop().time() + max_wait
            while asyncio.get_event_loop().time() < deadline:
                remaining = max(0.05, deadline - asyncio.get_event_loop().time())
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=min(remaining, 0.3))
                    if chunk:
                        buf += chunk
                    else:
                        break
                except asyncio.TimeoutError:
                    break
            return buf

        await asyncio.sleep(0.5)
        banner = await read_burst(2.0)

        async def read_avail(timeout_sec=1.5):
            return await read_burst(timeout_sec)

        banner = await Sender._telnet_wake_gns3_console(
            writer, read_avail, lambda m: self._resp_queue.put(("output", f"{m}\n")), banner
        )
        if banner.strip():
            self._resp_queue.put(("output", banner))
        writer.write("terminal length 0\r\n")
        await asyncio.sleep(0.3)
        await read_burst(1.0)

        while self._running:
            try:
                cmd = await asyncio.wait_for(self._async_queue.get(), timeout=0.5)
                writer.write(cmd + "\r\n")
                await asyncio.sleep(0.2)
                output = await read_burst(3.0)
                self._resp_queue.put(("output", output))
            except asyncio.TimeoutError:
                try:
                    chunk = await asyncio.wait_for(reader.read(512), timeout=0.05)
                    if chunk:
                        self._resp_queue.put(("output", chunk))
                except asyncio.TimeoutError:
                    pass

        try:
            writer.write("exit\r\n")
            await asyncio.sleep(0.2)
            writer.close()
        except Exception:
            pass

    def _send_command(self):
        cmd = self.ent_cmd.text().strip()
        if not cmd:
            return
        if not self._running or self._loop is None or self._loop.is_closed():
            self._append("[not connected]\n", "danger")
            return
        if not self._cmd_history or self._cmd_history[-1] != cmd:
            self._cmd_history.append(cmd)
        self._history_idx = len(self._cmd_history)
        try:
            self._loop.call_soon_threadsafe(self._async_queue.put_nowait, cmd)
        except Exception:
            pass
        self.ent_cmd.clear()
        self._append(f"\n> {cmd}\n", "accent")

    def _history_up(self):
        if not self._cmd_history:
            return
        self._history_idx = max(0, self._history_idx - 1)
        self.ent_cmd.setText(self._cmd_history[self._history_idx])

    def _history_down(self):
        if not self._cmd_history:
            return
        self._history_idx = min(len(self._cmd_history), self._history_idx + 1)
        if self._history_idx < len(self._cmd_history):
            self.ent_cmd.setText(self._cmd_history[self._history_idx])
        else:
            self.ent_cmd.clear()

    def _schedule_poll(self):
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_responses)
        self._poll_timer.start(100)

    def _poll_responses(self):
        try:
            while not self._resp_queue.empty():
                kind, data = self._resp_queue.get_nowait()
                if kind == "connected":
                    self.lbl_status.setText("\u2b24 connected")
                    self.lbl_status.setStyleSheet(f"color: {_COLORS['success']};")
                    self.btn_connect.setEnabled(False)
                    self._append("Connected.\n\n", "success")
                elif kind == "output":
                    self._append(data)
                elif kind == "error":
                    self._append(f"\n[error] {data}\n", "danger")
        except Exception:
            pass
        if not self._running and self._resp_queue.empty() and self._poll_timer:
            self._poll_timer.stop()

    def _append(self, text, tag=None):
        if tag and tag in _COLORS:
            fmt = self.txt_out.currentCharFormat()
            fmt.setForeground(QColor(_COLORS[tag]))
            self.txt_out.setCurrentCharFormat(fmt)
            self.txt_out.appendPlainText(text.rstrip("\n"))
            fmt.setForeground(QColor("#C9D1D9"))
            self.txt_out.setCurrentCharFormat(fmt)
        else:
            self.txt_out.appendPlainText(text.rstrip("\n"))

    def _clear_output(self):
        self.txt_out.clear()

    def closeEvent(self, event):
        self._running = False
        if self._poll_timer:
            self._poll_timer.stop()
        if self._loop and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        event.accept()
