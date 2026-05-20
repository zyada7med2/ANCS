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
        parent=None
    )
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QMetaObject, Q_ARG
from PySide6.QtGui import QFont, QColor, QSyntaxHighlighter, QTextCharFormat
import re


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


# Thread-safe helper for use from the CopilotWorker thread
_pending_review = {"result": None}


def _show_dialog_on_main_thread(device_name: str, device_role: str, commands: list[str]):
    """Show the dialog on the main thread and store the result."""
    dialog = DeployReviewDialog(device_name, device_role, commands)
    dialog.exec()
    _pending_review["result"] = (dialog.approved, dialog.final_commands)


def request_deploy_approval(
    device_name: str,
    device_role: str,
    commands: list[str],
) -> tuple[bool, list[str]]:
    """Request user approval for a deployment via a modal dialog.

    This is thread-safe — can be called from the CopilotWorker thread.
    The dialog will be shown on the main (GUI) thread.

    Returns:
        (approved: bool, final_commands: list[str])
        If rejected, final_commands will be the original commands.
    """
    from PySide6.QtWidgets import QApplication

    _pending_review["result"] = None

    # Schedule dialog on main thread
    app = QApplication.instance()
    if app:
        QMetaObject.invokeMethod(
            app,
            lambda: _show_dialog_on_main_thread(device_name, device_role, commands),
            Qt.ConnectionType.BlockingQueuedConnection,
        )

    result = _pending_review.get("result")
    if result is None:
        return (False, commands)
    return result
