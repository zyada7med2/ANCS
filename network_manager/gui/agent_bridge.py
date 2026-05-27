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
        # Handle special command modes from JS
        if mode == "replay_history":
            self._dialog._replay_chat_history()
            return
        elif mode == "new_session":
            self._dialog._current_conversation_id = None
            self.clearChat()
            return

        text = text.strip()
        if not text:
            return

        # Set user sent flag
        self._dialog._user_has_sent = True
        self._dialog._current_mode = mode

        # Resolve Current Conversation ID
        conv_id = getattr(self._dialog, '_current_conversation_id', None)
        from network_manager.config import conn, db_lock
        if not conv_id:
            conv_id = f"chat_{int(time.time())}"
            self._dialog._current_conversation_id = conv_id
            title = text[:40] + ("..." if len(text) > 40 else "")
            try:
                with db_lock:
                    cur = conn.cursor()
                    cur.execute("INSERT INTO chat_conversations (conversation_id, title) VALUES (?, ?)", (conv_id, title))
                    conn.commit()
                    cur.close()
            except Exception as e:
                print(f"Error creating conversation: {e}")

        # Save User Message to DB
        try:
            with db_lock:
                cur = conn.cursor()
                cur.execute("INSERT INTO chat_messages (conversation_id, sender, text, thoughts) VALUES (?, ?, ?, ?)",
                            (conv_id, "user", text, json.dumps([])))
                conn.commit()
                cur.close()
        except Exception as e:
            print(f"Error saving user message: {e}")

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

        # `@` Mentions Resolution & Context Prepending
        augmented_text = text
        mentions = re.findall(r'@(\w+)', text)
        if mentions:
            context_blocks = []
            for dev_name in mentions:
                dev_info = self._get_device_info_for_mention(dev_name)
                if dev_info:
                    context_blocks.append(dev_info)
            if context_blocks:
                augmented_text = "\n\n".join(context_blocks) + "\n\nUser Message:\n" + text

        # Queue message to the CopilotWorker
        worker = getattr(self.app, '_copilot_worker', None)
        if worker and worker.isRunning():
            worker.queue_message(augmented_text, attachment_path)
        else:
            # Not connected — try auto-connect first
            self._dialog._launch_agent()
            # Wait a moment then queue
            QTimer.singleShot(1500, lambda: self._delayed_send(augmented_text, attachment_path))

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

    def _get_device_info_for_mention(self, dev_name):
        if not hasattr(self.app, 'devices'):
            return None
        matched_dev = None
        for name, model, meta in self.app.devices:
            if name.lower() == dev_name.lower():
                matched_dev = (name, model, meta)
                break
        if not matched_dev:
            return None
        name, model, meta = matched_dev
        config_content = "No saved configuration found in database."
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                cur = conn.cursor()
                cur.execute(
                    "SELECT content FROM configs WHERE device_id = (SELECT id FROM devices WHERE name = ?)",
                    (name,)
                )
                row = cur.fetchone()
                if row:
                    config_content = row[0]
                cur.close()
        except Exception:
            pass
        platform = getattr(model, "platform", "Cisco IOS") if model else "Cisco IOS"
        return f"""<mentioned-device name="{name}">
Platform: {platform}
Connection: {meta.get("console_host", "N/A")}:{meta.get("console_port", "N/A")}
Saved Configuration:
```
{config_content}
```
</mentioned-device>"""

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
        QTimer.singleShot(0, self._do_export_logs)

    def _do_export_logs(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self._dialog, "Export Logs", "ancs_agent_logs.txt",
            "Text Files (*.txt);;All Files (*)",
            options=QFileDialog.DontUseNativeDialog
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
        QTimer.singleShot(0, self._do_select_file)

    def _do_select_file(self):
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self._dialog, "Attach File to Copilot", "",
            "Supported Files (*.pdf *.png *.jpg *.jpeg *.webp);;PDF Files (*.pdf);;Images (*.png *.jpg *.jpeg *.webp);;All Files (*)",
            options=QFileDialog.DontUseNativeDialog
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

    @Slot()
    def exportPDF(self):
        """Generates a premium PDF of the chat history using native print-to-PDF."""
        QTimer.singleShot(0, self._do_export_pdf)

    def _do_export_pdf(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self._dialog, "Export Chat PDF", "ancs_chat_export.pdf",
            "PDF Files (*.pdf);;All Files (*)",
            options=QFileDialog.DontUseNativeDialog
        )
        if not path:
            return

        def handle_pdf_result(data):
            if not data.isEmpty():
                try:
                    with open(path, "wb") as f:
                        f.write(data.data())
                except Exception:
                    pass

        # Request QWebEngineView to print to PDF asynchronously
        web_view = getattr(self._dialog, '_web', None)
        if web_view:
            web_view.page().printToPdf(handle_pdf_result)

    @Slot(result=str)
    def getPastConversations(self):
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                cur = conn.cursor()
                cur.execute("SELECT conversation_id, title, created_at FROM chat_conversations ORDER BY created_at DESC")
                rows = cur.fetchall()
                cur.close()
            return json.dumps([{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows])
        except Exception as e:
            return json.dumps([])

    @Slot(str)
    def deleteConversation(self, conversation_id):
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                cur = conn.cursor()
                cur.execute("DELETE FROM chat_conversations WHERE conversation_id = ?", (conversation_id,))
                conn.commit()
                cur.close()
            if getattr(self._dialog, '_current_conversation_id', None) == conversation_id:
                self._dialog._current_conversation_id = None
                self.clearChat()
        except Exception as e:
            print(f"Error deleting conversation: {e}")

    @Slot(str)
    def loadConversation(self, conversation_id):
        try:
            from network_manager.config import conn, db_lock
            from network_manager.ai_agent import SYSTEM_PROMPT
            with db_lock:
                cur = conn.cursor()
                cur.execute("SELECT sender, text, thoughts FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,))
                rows = cur.fetchall()
                cur.close()

            chat_data = []
            history = []
            history.append({"role": "system", "content": SYSTEM_PROMPT})

            for sender, text, thoughts_json in rows:
                thoughts = []
                if thoughts_json:
                    try:
                        thoughts = json.loads(thoughts_json)
                    except Exception:
                        pass
                chat_data.append({
                    "type": "user" if sender == "user" else "ai" if sender == "agent" else "system",
                    "text": text,
                    "thoughts": thoughts
                })
                if sender == "user":
                    history.append({"role": "user", "content": text})
                elif sender == "agent":
                    history.append({"role": "assistant", "content": text})

            self._dialog._current_conversation_id = conversation_id
            self.app._copilot_chat_data = chat_data
            self.app._copilot_history = history

            # Restart the worker
            self._dialog._stop_worker()
            self._dialog._launch_agent()

            # Tell QWebEngine to render replayed logs
            self._dialog._web.page().runJavaScript("clearAndReplayChat();")
        except Exception as e:
            print(f"Error loading conversation: {e}")

    @Slot(result=str)
    def getDevicesList(self):
        if not hasattr(self.app, 'devices'):
            return json.dumps([])
        
        dev_list = []
        for name, model, meta in self.app.devices:
            # Determine type
            lower_name = name.lower()
            if "switch" in lower_name or "esw" in lower_name or "sw" in lower_name:
                dev_type = "switch"
            else:
                dev_type = "router"
            dev_list.append({"name": name, "type": dev_type})
        return json.dumps(dev_list)

