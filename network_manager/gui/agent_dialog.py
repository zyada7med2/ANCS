"""
ANCS Agent Dialog — QWebEngineView-based AI Copilot Interface
=============================================================
Drop-in replacement for invoke_ai_agent().
Renders the premium HTML UI (web/index.html) inside a QWebEngineView,
bridged to the Python CopilotWorker via QWebChannel (AgentBridge).

Zero changes to ai_agent.py or app.py.
"""

import json
import os
import re
import time
from datetime import datetime
from html import unescape

from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PySide6.QtCore import Qt, QTimer, QUrl, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel

try:
    import markdown
    def _render_md(text):
        return markdown.markdown(text, extensions=["fenced_code", "tables"])
except ImportError:
    def _render_md(text):
        return text.replace("\n", "<br>")

from network_manager.gui.agent_bridge import AgentBridge


# Path to the web assets
_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_INDEX_HTML = os.path.join(_WEB_DIR, "index.html")


class ANCSWebEnginePage(QWebEnginePage):
    """Custom QWebEnginePage to redirect JS console logs to Python stdout."""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        print(f"[JS Console] {message} (Line: {lineNumber}, Source: {sourceID})")


# ═══════════════════════════════════════════════════════════════════════
# MAIN DIALOG
# ═══════════════════════════════════════════════════════════════════════
class ANCSAgentDialog(QDialog):
    """Premium ANCS Agent dialog — drop-in replacement for invoke_ai_agent()."""

    def __init__(self, parent_app):
        super().__init__(
            parent_app,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowSystemMenuHint
        )
        self.app = parent_app
        self.setMinimumSize(900, 600)
        self.resize(1100, 780)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_pos = None
        self._is_maximized = False
        self._closing_for_app = False
        self._user_has_sent = False
        self._waiting_for_reply = False
        self._log_line_keys: set[str] = set()
        self._current_thoughts = []

        # Ensure chat data storage exists on parent app
        if not hasattr(self.app, "_copilot_chat_data"):
            self.app._copilot_chat_data = []

        # ── Build the WebChannel bridge ──────────────────────────────
        self._bridge = AgentBridge(self)

        # ── Build the QWebChannel ────────────────────────────────────
        self._channel = QWebChannel()
        self._channel.registerObject("bridge", self._bridge)

        # ── Build the QWebEngineView ─────────────────────────────────
        self._web = QWebEngineView()
        page = ANCSWebEnginePage(self._web)
        self._web.setPage(page)
        page.setWebChannel(self._channel)
        page.setBackgroundColor(QColor("#080C14"))

        # Enable required web engine settings
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)

        # Load the HTML UI
        self._web.load(QUrl.fromLocalFile(_INDEX_HTML))

        # ── Layout ───────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._web)

        # ── Device chips refresh timer ───────────────────────────────
        self._chips_timer = QTimer(self)
        self._chips_timer.setInterval(4000)
        self._chips_timer.timeout.connect(self._refresh_device_chips)
        self._chips_timer.start()

    # ──────────────────────────────────────────────────────────────────
    # JS READY CALLBACK
    # ──────────────────────────────────────────────────────────────────
    def _on_js_ready(self):
        """Called by AgentBridge when JS signals that QWebChannel is up."""
        self._restore_state()
        self._refresh_device_chips()
        self._replay_chat_history()

    def _render_thought_html(self, thoughts):
        """Build HTML string for the collapsible thinking process card."""
        if not thoughts:
            return ""
        
        unique_id = f"thought-{int(time.time() * 1000)}"
        steps_li = ""
        for thought in thoughts:
            steps_li += f"""
            <li class="thought-step">
                <span class="thought-step-icon thought-step-info">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                </span>
                <span class="thought-step-text">{unescape(thought)}</span>
            </li>
            """
        
        return f"""
        <div class="thought-container" id="{unique_id}" style="margin-top: 8px;">
            <div class="thought-header" onclick="toggleThought('{unique_id}')">
                <div class="thought-header-left">
                    <span class="thought-brain-icon">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"></path><path d="M12 6v6"></path><path d="M12 16h.01"></path></svg>
                    </span>
                    <span>Thinking Process</span>
                </div>
                <span class="thought-chevron">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                </span>
            </div>
            <div class="thought-content">
                <ul class="thought-steps">
                    {steps_li}
                </ul>
            </div>
        </div>
        """

    def _replay_chat_history(self):
        """Re-emit stored chat messages so they appear in the web UI."""
        for entry in (self.app._copilot_chat_data or []):
            kind = entry.get("type")
            text = entry.get("text", "")
            if kind == "user":
                self._bridge.addChatMessage.emit("user", text, "")
            elif kind == "ai":
                html = _render_md(text)
                thoughts = entry.get("thoughts", [])
                if thoughts:
                    html = self._render_thought_html(thoughts) + html
                self._bridge.addChatMessage.emit("agent", html, "")
            elif kind == "system":
                self._bridge.addChatMessage.emit("system", text, "")

    # ──────────────────────────────────────────────────────────────────
    # STATE MANAGEMENT
    # ──────────────────────────────────────────────────────────────────
    def _restore_state(self):
        """Load saved config and auto-connect if API key is present."""
        from network_manager.config import CONFIG_FILE

        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

        prov = cfg.get("agent_provider", "openrouter")
        model = cfg.get("agent_model", "openai/gpt-4o-mini")
        key = cfg.get("gemini_api_key", "") or cfg.get("openrouter_api_key", "")
        allow_raw = bool(cfg.get("agent_allow_raw_deploy", False))
        max_tokens = str(cfg.get("agent_max_tokens", "8192"))
        timeout = str(cfg.get("agent_timeout", "30"))

        # Push settings to JS
        settings_json = json.dumps({
            "provider": prov,
            "model": model,
            "apiKey": key,
            "allowRaw": allow_raw,
            "maxTokens": max_tokens,
            "timeout": timeout,
        })
        self._bridge.pushSettings.emit(settings_json)

        # Auto-connect if worker alive or key exists
        if self._is_worker_alive():
            self._connect_worker_signals()
            model_name = getattr(self.app._copilot_worker, "model_name", "Unknown")
            self._bridge.setConnectionStatus.emit("connected", model_name)
        elif key:
            QTimer.singleShot(400, self._launch_agent)

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

            # Prevent QThread crash from destroying running thread
            if self.app._copilot_worker.isRunning():
                if not hasattr(self.app, "_zombie_workers"):
                    self.app._zombie_workers = []
                self.app._zombie_workers.append(self.app._copilot_worker)

            self.app._copilot_worker = None

    def _launch_agent(self):
        """Create and start a CopilotWorker — same logic as old dialog."""
        from network_manager.ai_agent import CopilotWorker
        from network_manager.config import CONFIG_FILE, GNS3_DEFAULT_URL

        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

        api_key = cfg.get("gemini_api_key", "")
        provider = cfg.get("agent_provider", "openrouter")
        model_name = cfg.get("agent_model", "openai/gpt-4o-mini")
        allow_raw = bool(cfg.get("agent_allow_raw_deploy", False))

        if provider != "vertex" and not api_key:
            self._bridge.addChatMessage.emit(
                "system",
                "Please enter your API key in Settings (⚙) to connect.",
                ""
            )
            return

        if self._is_worker_alive():
            cw = self.app._copilot_worker
            if (getattr(cw, "api_key", "") == api_key
                    and getattr(cw, "provider", "") == provider
                    and getattr(cw, "model_name", "") == model_name):
                self._bridge.setConnectionStatus.emit("connected", model_name)
                return
            self._bridge.addChatMessage.emit("system", "Reconnecting with updated settings...", "")
            self.app._copilot_history = []
            self._stop_worker()
        elif self.app._copilot_worker is not None:
            self._bridge.addChatMessage.emit("system", "Reconnecting...", "")
            self._stop_worker()

        gns3_url = getattr(self.app, '_gns3_url', GNS3_DEFAULT_URL) or GNS3_DEFAULT_URL
        gns3_project_id = getattr(self.app, "gns3_project_id", None) or ""

        project_snapshot = self.app._build_copilot_snapshot()
        workspace_resolved = self.app._copilot_workspace_resolved()

        self._bridge.setConnectionStatus.emit("connecting", model_name)
        self._bridge.setThinking.emit(True, "Connecting to agent...")

        if not hasattr(self.app, '_copilot_history'):
            self.app._copilot_history = []

        self.app._copilot_worker = CopilotWorker(
            api_key=api_key,
            gns3_url=gns3_url,
            allow_raw_deploy=allow_raw,
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
        self._refresh_device_chips()

    def _reconnect_if_needed(self):
        """Reconnect the worker if settings changed. Called by bridge after saveSettings."""
        from network_manager.config import CONFIG_FILE
        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return

        if not self._is_worker_alive():
            self._launch_agent()
            return

        cw = self.app._copilot_worker
        api_key = cfg.get("gemini_api_key", "")
        provider = cfg.get("agent_provider", "openrouter")
        model_name = cfg.get("agent_model", "openai/gpt-4o-mini")

        if (getattr(cw, "api_key", "") != api_key
                or getattr(cw, "provider", "") != provider
                or getattr(cw, "model_name", "") != model_name):
            self._bridge.addChatMessage.emit("system", "Reconnecting with new settings...", "")
            self.app._copilot_history = []
            self._stop_worker()
            self._launch_agent()

    # ──────────────────────────────────────────────────────────────────
    # SIGNAL HANDLERS (CopilotWorker → Bridge → JS)
    # ──────────────────────────────────────────────────────────────────
    def _on_terminal_log(self, html_text):
        """Stream execution logs to JS and parse structured tool events."""
        # Stream all raw log outputs to JS bridge Console Stream
        self._bridge.appendExecutionLog.emit(html_text)

        clean = re.sub(r'<[^>]+>', '', html_text).strip()
        if not clean:
            return

        # Dedup [Thinking] lines
        if clean.startswith("[Thinking]") or "[Thinking]" in clean:
            key = re.sub(r"\s+", " ", clean).strip().lower()
            if key in self._log_line_keys:
                return
            self._log_line_keys.add(key)

        # Skip [User] echo
        if clean.startswith("[User]"):
            return

        # Don't flood chat before user has sent a message
        if not self._user_has_sent:
            return

        # Parse structured tool events and emit to JS
        self._parse_and_emit_tool_event(clean)

    def _parse_and_emit_tool_event(self, clean_text: str):
        """Parse structured tool log lines and emit them as JSON to the JS bridge."""
        clean_text = unescape(clean_text).replace("\xa0", " ")
        now = datetime.now().strftime("%I:%M:%S %p")

        call_match = re.search(r"\[Tool Call\]\s+([\w.]+)\((.*)\)", clean_text)
        result_match = re.search(r"\[Tool Result\]\s+([\w.]+)\s+(?:→|->|→)\s+(\d+)ms\s+\|\s+(.*)", clean_text)
        error_match = re.search(r"\[Tool Error\]\s+([\w.]+):\s+(.*)", clean_text)
        legacy_tool_match = re.search(r"\[Tool\]\s+([\w.]+)\((.*?)\)(?:\s*(?:→|->|→)\s*(.*))?", clean_text)
        thinking_match = re.search(r"\[Thinking\]\s*(.*)", clean_text)

        if call_match:
            tool_name = call_match.group(1)
            self._bridge.addToolLog.emit(json.dumps({
                "time": now, "type": "tool", "name": tool_name,
                "description": f"Calling {tool_name}...",
                "status": "running"
            }))
            self._bridge.setThinking.emit(True, f"Calling {tool_name}...")
            return

        if result_match:
            tool_name = result_match.group(1)
            duration = result_match.group(2)
            result = result_match.group(3) or ""
            self._bridge.addToolLog.emit(json.dumps({
                "time": now, "type": "tool", "name": tool_name,
                "description": f"{result[:100]}",
                "status": f"✓ {duration}ms"
            }))
            return

        if error_match:
            tool_name = error_match.group(1)
            error_text = error_match.group(2) or ""
            self._bridge.addToolLog.emit(json.dumps({
                "time": now, "type": "tool", "name": tool_name,
                "description": f"Error: {error_text[:100]}",
                "status": "error"
            }))
            return

        if legacy_tool_match:
            tool_name = legacy_tool_match.group(1)
            result_preview = legacy_tool_match.group(3) or ""
            status = "✓ completed" if result_preview else "running"
            self._bridge.addToolLog.emit(json.dumps({
                "time": now, "type": "tool", "name": tool_name,
                "description": result_preview[:100] or f"Executing {tool_name}...",
                "status": status
            }))
            self._bridge.setThinking.emit(True, f"Using {tool_name}...")
            return

        if thinking_match:
            thought = thinking_match.group(1).strip()
            self._current_thoughts.append(thought)
            self._bridge.setThinking.emit(True, thought or "Analyzing...")
            self._bridge.addToolLog.emit(json.dumps({
                "time": now, "type": "info", "name": "Thinking",
                "description": thought[:100] or "Analyzing request...",
                "status": "running"
            }))
            return

    def _on_chat_response(self, text):
        """Agent finished responding — push rendered markdown to JS."""
        html = _render_md(text)
        if self._current_thoughts:
            thought_html = self._render_thought_html(self._current_thoughts)
            html = thought_html + html

        ts = datetime.now().strftime("%I:%M %p")
        self._bridge.addChatMessage.emit("agent", html, ts)
        self._bridge.setThinking.emit(False, "")

        # Store for persistence
        self.app._copilot_chat_data.append({
            "type": "ai",
            "text": text,
            "thoughts": list(self._current_thoughts)
        })
        self._current_thoughts = []
        self._waiting_for_reply = False

    def _on_finished(self, summary, success):
        """Worker finished (disconnected or error)."""
        self._bridge.setThinking.emit(False, "")
        self._bridge.setConnectionStatus.emit("offline", "")
        if not success:
            self._bridge.addChatMessage.emit("system", f"Error: {summary}", "")
        self._current_thoughts = []
        self._waiting_for_reply = False

    def _on_ready(self):
        """Worker ready (connected successfully)."""
        model = "Unknown"
        if self._is_worker_alive():
            model = getattr(self.app._copilot_worker, "model_name", "Unknown")
        self._bridge.setConnectionStatus.emit("connected", model)
        self._bridge.setThinking.emit(False, "")

    # ──────────────────────────────────────────────────────────────────
    # DEVICE CHIPS
    # ──────────────────────────────────────────────────────────────────
    def _refresh_device_chips(self):
        """Build JSON from app.devices and push to JS."""
        if not hasattr(self.app, 'devices'):
            self._bridge.updateDevices.emit("[]")
            return

        dev_list = []
        total = len(self.app.devices)
        for i, (name, model, meta) in enumerate(self.app.devices[:20]):
            has_config = any(model.templates.values()) if hasattr(model, 'templates') else False
            status = "configured" if has_config else ("connected" if meta.get("console_host") else "pending")
            ip = meta.get("console_host", "N/A")
            platform = getattr(model, "platform", "Cisco IOS") if model else "Cisco IOS"

            # Auto-layout for topology — spread devices in a grid
            cols = max(3, int(total ** 0.5) + 1)
            row = i // cols
            col = i % cols
            x = 15 + (col * 70 // cols)
            y = 25 + (row * 50)

            dev_list.append({
                "id": name,
                "name": name,
                "status": status,
                "ip": str(ip),
                "platform": str(platform),
                "lastSeen": datetime.now().strftime("%I:%M:%S %p"),
                "x": min(x, 85),
                "y": min(y, 75),
            })

        self._bridge.updateDevices.emit(json.dumps(dev_list))

    # ──────────────────────────────────────────────────────────────────
    # WINDOW DRAG (frameless — handle from header mousedown events)
    # ──────────────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
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
        if event.position().y() < 60:
            self._toggle_maximize()

    def _toggle_maximize(self):
        if self._is_maximized:
            self.showNormal()
            self._is_maximized = False
        else:
            self.showMaximized()
            self._is_maximized = True

    # ──────────────────────────────────────────────────────────────────
    # CLOSE HANDLING
    # ──────────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        if self._closing_for_app:
            self._chips_timer.stop()
            event.accept()
            return
        event.ignore()
        self.hide()
