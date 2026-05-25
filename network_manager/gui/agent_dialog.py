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

from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox, QWidget
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

class _EdgeGrip(QWidget):
    """Invisible widget placed on a window edge/corner to handle resize."""
    _CURSORS = {
        'left':         Qt.CursorShape.SizeHorCursor,
        'right':        Qt.CursorShape.SizeHorCursor,
        'top':          Qt.CursorShape.SizeVerCursor,
        'bottom':       Qt.CursorShape.SizeVerCursor,
        'top-left':     Qt.CursorShape.SizeFDiagCursor,
        'bottom-right': Qt.CursorShape.SizeFDiagCursor,
        'top-right':    Qt.CursorShape.SizeBDiagCursor,
        'bottom-left':  Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, parent: QDialog, edge: str, thickness: int = 6):
        super().__init__(parent)
        self._edge = edge
        self._thickness = thickness
        self._drag_start_pos = None
        self._drag_start_geo = None
        self.setMouseTracking(True)
        self.setCursor(self._CURSORS.get(edge, Qt.CursorShape.ArrowCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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
        if event.button() == Qt.MouseButton.LeftButton:
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

        # ── Invisible edge grips for frameless resize ──────────────────
        self._resize_grips = []
        for edge in ('left', 'right', 'top', 'bottom',
                     'top-left', 'top-right', 'bottom-left', 'bottom-right'):
            g = _EdgeGrip(self, edge, thickness=6)
            self._resize_grips.append(g)

        # ── Enable native Windows drop shadow for frameless dialog ────
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                margins = ctypes.c_int * 4
                ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, margins(1, 1, 1, 1))
            except Exception:
                pass

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
            self._refresh_device_chips() # Force immediate GNS3 topology and details refresh on tool completion
            return

        if error_match:
            tool_name = error_match.group(1)
            error_text = error_match.group(2) or ""
            self._bridge.addToolLog.emit(json.dumps({
                "time": now, "type": "tool", "name": tool_name,
                "description": f"Error: {error_text[:100]}",
                "status": "error"
            }))
            self._refresh_device_chips() # Force immediate refresh on tool error to show status update
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
        self._refresh_device_chips() # Force immediate GNS3 topology and details refresh on final chat response

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

        # ── Fetch GNS3 coordinates and links cached in the CopilotWorker ──
        gns3_nodes = []
        gns3_links = []
        w = getattr(self.app, "_copilot_worker", None)
        if w:
            gns3_nodes = getattr(w, "gns3_nodes_data", []) or []
            gns3_links = getattr(w, "gns3_links_data", []) or []

        # Map node positions if GNS3 data is available
        node_coords = {}
        if gns3_nodes:
            try:
                x_coords = [n.get("x", 0) for n in gns3_nodes]
                y_coords = [n.get("y", 0) for n in gns3_nodes]
                
                min_x, max_x = min(x_coords), max(x_coords)
                min_y, max_y = min(y_coords), max(y_coords)
                
                x_span = max_x - min_x if max_x != min_x else 1
                y_span = max_y - min_y if max_y != min_y else 1
                
                for n in gns3_nodes:
                    nid = n.get("node_id") or n.get("id")
                    name = n.get("name")
                    # Scale to 15% - 85% range for HTML container
                    px = 15 + ((n.get("x", 0) - min_x) / x_span) * 70
                    py = 15 + ((n.get("y", 0) - min_y) / y_span) * 70
                    
                    if nid:
                        node_coords[str(nid)] = (px, py)
                    if name:
                        node_coords[str(name).lower()] = (px, py)
            except Exception:
                pass

        dev_list = []
        total = len(self.app.devices)
        
        # Import models inside function to avoid circular imports
        from network_manager.models.devices import RouterModel, CoreSwitchModel, SwitchModel

        for i, (name, model, meta) in enumerate(self.app.devices[:20]):
            has_config = any(model.templates.values()) if hasattr(model, 'templates') else False
            status = "configured" if has_config else ("connected" if meta.get("console_host") else "pending")
            ip = meta.get("console_host", "N/A")
            platform = getattr(model, "platform", "Cisco IOS") if model else "Cisco IOS"

            # Determine device type
            dev_type = "router"
            if isinstance(model, CoreSwitchModel):
                dev_type = "switch"
            elif isinstance(model, SwitchModel):
                dev_type = "switch"
            elif isinstance(model, RouterModel):
                dev_type = "router"
            else:
                lower_name = name.lower()
                if "switch" in lower_name or "esw" in lower_name or "sw" in lower_name:
                    dev_type = "switch"
                else:
                    dev_type = "router"

            # Fallback auto-layout spread in a grid
            cols = max(3, int(total ** 0.5) + 1)
            row = i // cols
            col = i % cols
            fallback_x = 15 + (col * 70 // cols)
            fallback_y = 25 + (row * 50)

            # Try GNS3 resolved coordinates, fall back to grid
            nid = meta.get("node_id")
            x, y = fallback_x, fallback_y
            if nid and str(nid) in node_coords:
                x, y = node_coords[str(nid)]
            elif name and str(name).lower() in node_coords:
                x, y = node_coords[str(name).lower()]

            # Get operational IP and active roles from model state
            op_ip = "—"
            roles = []
            
            if model and hasattr(model, 'state') and model.state:
                # Try to get WAN/uplink interface IP
                wan = model.state.get("wan", {})
                if wan and wan.get("ip"):
                    op_ip = f"{wan.get('ip')}"
                
                # Check for routing protocols, DHCP, static routes
                routing = model.state.get("routing", {})
                if routing and routing.get("protocol") != "none" and routing.get("protocol"):
                    roles.append(routing.get("protocol").upper())
                
                dhcp = model.state.get("dhcp_pools", [])
                if dhcp:
                    roles.append("DHCP")
                    
                static_routes = model.state.get("static_routes", [])
                if static_routes:
                    roles.append("STATIC")
                    
                vlans = model.state.get("vlans", [])
                if vlans:
                    roles.append("VLANS")
            
            if not roles:
                if dev_type == "router":
                    roles.append("ROUTER")
                else:
                    roles.append("SWITCH")

            dev_list.append({
                "id": name,
                "name": name,
                "status": status,
                "ip": str(ip),
                "op_ip": op_ip,
                "roles": roles,
                "platform": str(platform),
                "type": dev_type,
                "lastSeen": datetime.now().strftime("%I:%M:%S %p"),
                "x": min(x, 90),
                "y": min(y, 90),
            })

        self._bridge.updateDevices.emit(json.dumps(dev_list))

        # ── Dynamically build connections list from GNS3 link data ──
        connections_list = []
        if gns3_nodes and gns3_links:
            # Map node_id -> device workspace name
            id_to_name = {}
            for aname, amodel, ameta in self.app.devices:
                nid = ameta.get("node_id")
                if nid:
                    id_to_name[str(nid)] = aname

            # Fallback mapping from raw GNS3 nodes
            for n in gns3_nodes:
                nid = n.get("node_id") or n.get("id")
                nname = n.get("name")
                if nid and nname and str(nid) not in id_to_name:
                    id_to_name[str(nid)] = nname

            for link in gns3_links:
                eps = link.get("nodes", [])
                if len(eps) >= 2:
                    nid_a = eps[0].get("node_id")
                    nid_b = eps[1].get("node_id")
                    name_a = id_to_name.get(str(nid_a))
                    name_b = id_to_name.get(str(nid_b))
                    if name_a and name_b:
                        # Extract port names
                        port_a = ""
                        port_b = ""
                        
                        label_obj_a = eps[0].get("label") or {}
                        label_text_a = label_obj_a.get("text", "").strip()
                        if label_text_a:
                            port_a = label_text_a
                        else:
                            adapter_a = eps[0].get("adapter_number")
                            port_num_a = eps[0].get("port_number")
                            if adapter_a is not None and port_num_a is not None:
                                port_a = f"Et{adapter_a}/{port_num_a}"

                        label_obj_b = eps[1].get("label") or {}
                        label_text_b = label_obj_b.get("text", "").strip()
                        if label_text_b:
                            port_b = label_text_b
                        else:
                            adapter_b = eps[1].get("adapter_number")
                            port_num_b = eps[1].get("port_number")
                            if adapter_b is not None and port_num_b is not None:
                                port_b = f"Et{adapter_b}/{port_num_b}"

                        # Shorten interface names
                        def shorten_iface(nm):
                            for full, short in [("GigabitEthernet", "Gi"), ("FastEthernet", "Fa"),
                                                 ("TenGigabitEthernet", "Te"), ("Ethernet", "Et"),
                                                 ("Serial", "Se"), ("Loopback", "Lo"), ("Tunnel", "Tu"), ("Vlan", "Vl")]:
                                if str(nm).lower().startswith(full.lower()):
                                    return short + str(nm)[len(full):]
                            return str(nm)

                        port_a = shorten_iface(port_a)
                        port_b = shorten_iface(port_b)

                        connections_list.append({
                            "from": name_a,
                            "to": name_b,
                            "port_from": port_a,
                            "port_to": port_b
                        })

        # Emit live link connections to the JS side
        self._bridge.updateConnections.emit(json.dumps(connections_list))

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for grip in getattr(self, '_resize_grips', []):
            if self._is_maximized:
                grip.hide()
            else:
                grip.reposition()
                grip.show()

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
