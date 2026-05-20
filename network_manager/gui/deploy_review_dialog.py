"""
deploy_review_dialog.py — Human-in-the-Loop (HITL) Deploy Review Dialog

Shows a diff-like view of configuration commands that the AI agent wants to deploy,
allowing the user to review, edit, and approve/reject before any changes are applied.

Usage from ai_agent.py:
    from network_manager.gui.deploy_review_dialog import request_deploy_approval
    approved, final_commands = request_deploy_approval(
        device_name="R1",
        device_role="router",
        commands=["router ospf 1", "network 10.0.0.0 0.0.0.255 area 0", ...],
    )
"""

import re
import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFrame, QApplication,
)
from PySide6.QtCore import Qt, Signal, Slot, QObject, QThread
from PySide6.QtGui import QFont, QColor, QSyntaxHighlighter, QTextCharFormat


class IOSSyntaxHighlighter(QSyntaxHighlighter):
    """Simple syntax highlighter for IOS config commands."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []

        # "no ..." commands — red (deletions)
        fmt_delete = QTextCharFormat()
        fmt_delete.setForeground(QColor("#f85149"))
        fmt_delete.setFontWeight(QFont.Weight.Bold)
        self._rules.append((re.compile(r'^no\s+.*', re.IGNORECASE), fmt_delete))

        # Config mode markers — dim
        fmt_dim = QTextCharFormat()
        fmt_dim.setForeground(QColor("#8b949e"))
        self._rules.append((re.compile(r'^(configure terminal|end|exit|!)$', re.IGNORECASE), fmt_dim))

        # Interface/router sections — yellow
        fmt_section = QTextCharFormat()
        fmt_section.setForeground(QColor("#d29922"))
        fmt_section.setFontWeight(QFont.Weight.Bold)
        self._rules.append((re.compile(r'^(interface|router|ip dhcp|vlan)\s+.*', re.IGNORECASE), fmt_section))

        # Comments — green
        fmt_comment = QTextCharFormat()
        fmt_comment.setForeground(QColor("#3fb950"))
        self._rules.append((re.compile(r'^!.*'), fmt_comment))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            if pattern.match(text.strip()):
                self.setFormat(0, len(text), fmt)
                break


class DeployReviewDialog(QDialog):
    """Modal dialog for reviewing and approving configuration deployments."""

    def __init__(self, device_name: str, device_role: str, commands: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Review Deployment — {device_name}")
        self.setMinimumSize(700, 500)
        self.setModal(True)

        self._approved = False
        self._final_commands = commands

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel(f"⚠️ <b>Deploy to {device_name}</b> ({device_role})")
        header.setStyleSheet("font-size: 16px; color: #d29922; padding: 8px;")
        layout.addWidget(header)

        info_label = QLabel(
            "Review the commands below before deploying. You can edit them directly. "
            "Click <b>Approve & Deploy</b> to proceed or <b>Reject</b> to cancel."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #8b949e; padding: 0 8px;")
        layout.addWidget(info_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #30363d;")
        layout.addWidget(sep)

        # Command count
        count_label = QLabel(f"📝 {len(commands)} commands")
        count_label.setStyleSheet("color: #58A6FF; font-weight: bold; padding: 0 8px;")
        layout.addWidget(count_label)

        # Command editor (editable!)
        self._editor = QPlainTextEdit()
        self._editor.setPlainText("\n".join(commands))
        self._editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 12px;
                font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
                font-size: 13px;
                selection-background-color: #264f78;
            }
        """)
        # Apply syntax highlighting
        self._highlighter = IOSSyntaxHighlighter(self._editor.document())
        layout.addWidget(self._editor, stretch=1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        reject_btn = QPushButton("✖  Reject")
        reject_btn.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                color: #f85149;
                border: 1px solid #f85149;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #3b1d23;
            }
        """)
        reject_btn.clicked.connect(self._on_reject)
        btn_layout.addWidget(reject_btn)

        approve_btn = QPushButton("✔  Approve && Deploy")
        approve_btn.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: white;
                border: 1px solid #2ea043;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
        """)
        approve_btn.clicked.connect(self._on_approve)
        btn_layout.addWidget(approve_btn)

        layout.addLayout(btn_layout)

        # Dialog style
        self.setStyleSheet("""
            QDialog {
                background-color: #161b22;
            }
        """)

    def _on_approve(self):
        self._approved = True
        # Get potentially edited commands
        text = self._editor.toPlainText()
        self._final_commands = [c.strip() for c in text.split("\n") if c.strip()]
        self.accept()

    def _on_reject(self):
        self._approved = False
        self.reject()

    @property
    def approved(self) -> bool:
        return self._approved

    @property
    def final_commands(self) -> list[str]:
        return self._final_commands


# ═══════════════════════════════════════════════════════════════════
# Thread-safe bridge for invoking the dialog from the CopilotWorker
# ═══════════════════════════════════════════════════════════════════

class _ReviewBridge(QObject):
    """
    Bridge object that enables the CopilotWorker thread to show a modal
    dialog on the main (GUI) thread and block until the user responds.

    How it works:
    1. CopilotWorker calls request_deploy_approval() from its thread
    2. The bridge emits _trigger signal (parameterless to avoid PySide6 type issues)
    3. Signal is delivered via QueuedConnection to the main thread's event loop
    4. _show_dialog() runs on the main thread, shows the modal, stores result
    5. threading.Event unblocks the worker thread
    """
    _trigger = Signal()

    def __init__(self):
        super().__init__()
        self._device_name = ""
        self._device_role = ""
        self._commands = []
        self._result = None
        self._done = threading.Event()
        # Connect signal → slot. QueuedConnection delivers to receiver's thread.
        self._trigger.connect(self._show_dialog, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _show_dialog(self):
        """Runs on the main thread — safe to create and exec a QDialog."""
        try:
            dialog = DeployReviewDialog(
                self._device_name, self._device_role, self._commands
            )
            dialog.exec()
            self._result = (dialog.approved, dialog.final_commands)
        except Exception as e:
            self._result = None
        finally:
            self._done.set()


# Singleton bridge, lazily initialized
_bridge = None
_bridge_lock = threading.Lock()


def _get_bridge() -> _ReviewBridge:
    """Get or create the singleton bridge, moved to the main thread."""
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = _ReviewBridge()
            # Move bridge to the main thread so its slot runs there
            app = QApplication.instance()
            if app:
                _bridge.moveToThread(app.thread())
        return _bridge


def request_deploy_approval(
    device_name: str,
    device_role: str,
    commands: list[str],
) -> tuple[bool, list[str]]:
    """Request user approval for a deployment via a modal dialog.

    Thread-safe — designed to be called from the CopilotWorker thread.
    The dialog runs on the main GUI thread; the worker blocks until
    the user clicks Approve or Reject.

    Returns:
        (approved: bool, final_commands: list[str])
        If dialog fails, returns (False, original_commands).
    """
    app = QApplication.instance()
    if not app:
        raise RuntimeError("No QApplication instance — cannot show HITL dialog")

    # If already on main thread (shouldn't happen, but handle it), show directly
    if QThread.currentThread() == app.thread():
        dialog = DeployReviewDialog(device_name, device_role, commands)
        dialog.exec()
        return (dialog.approved, dialog.final_commands)

    # Cross-thread: use the bridge
    bridge = _get_bridge()
    bridge._device_name = device_name
    bridge._device_role = device_role
    bridge._commands = list(commands)  # copy to be safe
    bridge._result = None
    bridge._done.clear()

    # Emit signal — delivered to main thread via QueuedConnection
    bridge._trigger.emit()

    # Block worker thread until the dialog closes (5 min timeout)
    bridge._done.wait(timeout=300)

    if bridge._result is None:
        return (False, commands)
    return bridge._result
