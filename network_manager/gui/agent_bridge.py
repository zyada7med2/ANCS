"""
AgentBridge — QWebChannel bridge between Python backend and HTML frontend.
Registered as 'bridge' on the QWebChannel so JavaScript can access it via
window.bridge.
"""

import json
import os
import re
import time
from datetime import datetime
from html import unescape

from PySide6.QtCore import QObject, Signal, Slot, QTimer


class AgentBridge(QObject):
    """Bidirectional bridge: Python signals → JS, JS calls → Python slots."""

    # ── Python → JS Signals ──────────────────────────────────────────
    addChatMessage = Signal(str, str, str)        # sender, content_html, timestamp
    setThinking = Signal(bool, str)               # active, label
    setConnectionStatus = Signal(str, str)        # status, model_name
    addToolLog = Signal(str)                      # JSON: {time, type, name, description, status}
    appendExecutionLog = Signal(str)              # raw HTML line
    updateDevices = Signal(str)                   # JSON array of device objects
    updateConnections = Signal(str)               # JSON array of GNS3 link objects
    pushSettings = Signal(str)                    # JSON settings object
    fileAttached = Signal(str, str)               # filename, absolute_path
    clearAttachment = Signal()                    # clear current attachment pill

    def __init__(self, dialog):
        super().__init__(dialog)
        self._dialog = dialog  # ANCSAgentDialog reference
        self._js_ready = False

    @property
    def app(self):
        return self._dialog.app

    # ── JS → Python Slots ────────────────────────────────────────────

    @Slot(str, str)
    def sendMessage(self, text, mode):
        """User pressed Send in the HTML UI."""
        text = text.strip()
        if not text:
            return

        # Set user sent flag
        self._dialog._user_has_sent = True

        # Store in chat data for persistence
        if not hasattr(self.app, '_copilot_chat_data'):
            self.app._copilot_chat_data = []
        self.app._copilot_chat_data.append({"type": "user", "text": text})

        self.setThinking.emit(True, "Processing...")

        # Extract attachment path if any
        attachment_path = getattr(self._dialog, '_active_attachment', None)
        if attachment_path:
            self._dialog._active_attachment = None
            self.clearAttachment.emit()

        # Queue message to the CopilotWorker
        worker = getattr(self.app, '_copilot_worker', None)
        if worker and worker.isRunning():
            worker.queue_message(text, attachment_path)
        else:
            # Not connected — try auto-connect first
            self._dialog._launch_agent()
            # Wait a moment then queue
            QTimer.singleShot(1500, lambda: self._delayed_send(text, attachment_path))

    def _delayed_send(self, text, attachment_path=None):
        worker = getattr(self.app, '_copilot_worker', None)
        if worker and worker.isRunning():
            worker.queue_message(text, attachment_path)
        else:
            self.addChatMessage.emit(
                "system",
                "Could not connect to agent. Please check your API key in Settings.",
                ""
            )
            self.setThinking.emit(False, "")

    @Slot(str)
    def saveSettings(self, json_settings):
        """User saved settings from the HTML modal."""
        try:
            settings = json.loads(json_settings)
        except (json.JSONDecodeError, TypeError):
            return

        from network_manager.config import CONFIG_FILE

        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

        provider_map = {
            "openrouter": "openrouter",
            "gemini": "gemini",
            "vertex": "vertex",
            "hapuppy": "hapuppy",
            "nvidia": "nvidia",
        }
        prov = settings.get("provider", "openrouter")
        cfg["agent_provider"] = provider_map.get(prov, prov)
        cfg["agent_model"] = settings.get("model", "openai/gpt-4o-mini")
        cfg["gemini_api_key"] = settings.get("apiKey", "")
        cfg["agent_allow_raw_deploy"] = bool(settings.get("allowRaw", False))
        cfg["agent_max_tokens"] = settings.get("maxTokens", "8192")
        cfg["agent_timeout"] = settings.get("timeout", "30")

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

        # Reconnect if worker exists with changed settings
        self._dialog._reconnect_if_needed()

    @Slot()
    def connectAgent(self):
        """User pressed Connect."""
        self._dialog._launch_agent()

    @Slot()
    def disconnectAgent(self):
        """User pressed Disconnect."""
        self._dialog._stop_worker()
        self.setConnectionStatus.emit("offline", "")

    @Slot()
    def clearChat(self):
        """User pressed New Session / Clear."""
        if hasattr(self.app, '_copilot_chat_data'):
            self.app._copilot_chat_data.clear()
        if hasattr(self.app, '_copilot_history'):
            self.app._copilot_history = []

    @Slot()
    def exportLogs(self):
        """User pressed Export logs."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self._dialog, "Export Logs", "ancs_agent_logs.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return
        # Export chat data
        try:
            with open(path, "w", encoding="utf-8") as f:
                for entry in (self.app._copilot_chat_data or []):
                    kind = entry.get("type", "")
                    text = entry.get("text", "")
                    f.write(f"[{kind.upper()}] {text}\n\n")
        except Exception:
            pass

    @Slot()
    def jsReady(self):
        """Called by JS when QWebChannel init completes."""
        self._js_ready = True
        self._dialog._on_js_ready()

    @Slot(int, int)
    def moveWindow(self, dx, dy):
        """Window drag move by delta coordinates."""
        if self._dialog.isMaximized():
            return
        self._dialog.move(self._dialog.x() + dx, self._dialog.y() + dy)

    @Slot()
    def minimizeWindow(self):
        self._dialog.showMinimized()

    @Slot()
    def maximizeWindow(self):
        self._dialog._toggle_maximize()

    @Slot()
    def closeWindow(self):
        self._dialog.hide()

    @Slot()
    def stopAgent(self):
        """Forcefully stops the current worker thread and restarts a clean one."""
        self._dialog._stop_worker()
        self._dialog._launch_agent()
        self.setThinking.emit(False, "")
        self.addChatMessage.emit("system", "Process stopped by user.", "")

    @Slot()
    def selectFile(self):
        """Launch native file picker to attach a PDF or Image."""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self._dialog, "Attach File to Copilot", "",
            "Supported Files (*.pdf *.png *.jpg *.jpeg *.webp);;PDF Files (*.pdf);;Images (*.png *.jpg *.jpeg *.webp);;All Files (*)"
        )
        if not file_path:
            return

        # Store the active attachment path on the dialog
        self._dialog._active_attachment = file_path

        # Extract filename for display in Web UI
        import os
        filename = os.path.basename(file_path)

        # Send signal to JS to show the attachment pill in the input box
        self.fileAttached.emit(filename, file_path)

    @Slot()
    def removeAttachment(self):
        """Remove the active file attachment."""
        if hasattr(self._dialog, '_active_attachment'):
            self._dialog._active_attachment = None
        self.clearAttachment.emit()
