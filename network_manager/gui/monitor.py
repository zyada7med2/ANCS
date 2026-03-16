"""
Real-time device health monitor — PySide6 version.

Two-tab layout:
  Fleet Overview : health-score cards for all devices, polled in parallel
  Device Detail  : per-device deep diagnostics + ad-hoc terminal
"""
from __future__ import annotations

import threading
import asyncio
import queue
import re
import time
import base64
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QFrame, QListWidget, QPlainTextEdit, QLineEdit, QComboBox,
    QCheckBox, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont

from .utils import apply_responsive_geometry
from ..config import conn, cur, db_lock

try:
    import telnetlib3
except Exception:
    telnetlib3 = None


def _deobfuscate(pw: str) -> str:
    if not pw:
        return ""
    try:
        return base64.b64decode(pw.encode()).decode("utf-8")
    except Exception:
        return pw


def _load_device_creds(device_name: str, meta: dict) -> tuple:
    username = meta.get("username", "")
    password = meta.get("password", "")
    enable_pw = meta.get("enable_pw", "")
    if not (username and password):
        try:
            with db_lock:
                cur.execute("SELECT username, password, enable_password FROM credentials WHERE device_name=?", (device_name,))
                row = cur.fetchone()
            if row:
                if not username and row[0]: username = row[0]
                if not password and row[1]: password = _deobfuscate(row[1])
                if not enable_pw and row[2]: enable_pw = _deobfuscate(row[2])
        except Exception:
            pass
    return username, password, enable_pw


_C = {
    "bg": "#0D1117", "card": "#1F2630", "sidebar": "#161B22",
    "text": "#C9D1D9", "muted": "#8B949E", "success": "#3FB950",
    "danger": "#F85149", "warn": "#D29922", "border": "#30363D",
    "accent": "#58A6FF", "row_alt": "#192028",
}
_POLL_INTERVALS = {"10 s": 10000, "30 s": 30000, "60 s": 60000, "5 min": 300000}
_CMD_LABELS = {
    "show version": "Device Info", "show ip interface brief": "Network Interfaces",
    "show ip dhcp binding": "DHCP Leases", "show vlan-switch": "VLAN Membership",
    "show vlan brief": "VLAN Membership", "show ip route": "Routing Table",
    "show ip arp": "ARP Table", "show cdp neighbors": "CDP Neighbors",
    "show interfaces": "Interface Error Counters", "show spanning-tree": "Spanning Tree",
    "show spanning-tree summary": "Spanning Tree Summary",
}


def _is_invalid(raw: str) -> bool:
    return bool(re.search(r"(Invalid input|% Invalid|% Incomplete|% Ambiguous|% Unknown command)", raw, re.IGNORECASE))


def _parse_iface_states(raw: str) -> dict:
    result = {}
    pat = re.compile(r"^(\S+)\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)", re.IGNORECASE)
    for line in raw.splitlines():
        m = pat.match(line.strip())
        if m and m.group(1).lower() != "interface":
            result[m.group(1)] = "up" if m.group(2).lower() == "up" else "down"
    return result


def _parse_dhcp_ips(raw: str) -> set:
    ips = set()
    pat = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+\S")
    for line in raw.splitlines():
        m = pat.match(line)
        if m and "IP address" not in line:
            ips.add(m.group(1))
    return ips


def _parse_vlan_ids(raw: str) -> set:
    ids = set()
    pat = re.compile(r"^(\d+)\s+\S+\s+active", re.IGNORECASE)
    for line in raw.splitlines():
        m = pat.match(line.strip())
        if m:
            ids.add(m.group(1))
    return ids


def _count_iface_errors(raw: str) -> int:
    count = 0
    pat = re.compile(r"(\d+) input errors|(\d+) output errors|(\d+) CRC|(\d+) output drops", re.IGNORECASE)
    for line in raw.splitlines():
        m = pat.search(line)
        if m:
            val = next((int(g) for g in m.groups() if g is not None), 0)
            if val > 0:
                count += 1
    return count


def _compute_health(data: dict, has_prev: bool = False) -> int:
    if not data or "_error" in data:
        return 0
    score = 50
    states = _parse_iface_states(data.get("show ip interface brief", ""))
    if states:
        up = sum(1 for s in states.values() if s == "up")
        score += int(30 * up / len(states))
    errs = _count_iface_errors(data.get("show interfaces", ""))
    score -= min(errs * 10, 30)
    if has_prev:
        score += 10
    return max(0, min(100, score))


def _health_color(score: int) -> str:
    if score >= 80: return _C["success"]
    elif score >= 50: return _C["warn"]
    return _C["danger"]


def _health_label(score: int) -> str:
    if score >= 80: return "Good"
    elif score >= 50: return "Warning"
    return "Critical"


def _detect_changes(new_data: dict, old_data: dict) -> list:
    alerts = []
    if not old_data or not new_data or "_error" in new_data:
        return alerts
    new_st = _parse_iface_states(new_data.get("show ip interface brief", ""))
    old_st = _parse_iface_states(old_data.get("show ip interface brief", ""))
    for iface, ns in new_st.items():
        os_ = old_st.get(iface)
        if os_ and os_ != ns:
            if ns == "down":
                alerts.append(("danger", f"  {iface} went DOWN since last poll"))
            else:
                alerts.append(("success", f"  {iface} came UP since last poll"))
    new_ips = _parse_dhcp_ips(new_data.get("show ip dhcp binding", ""))
    old_ips = _parse_dhcp_ips(old_data.get("show ip dhcp binding", ""))
    for ip in new_ips - old_ips:
        alerts.append(("accent", f"  New DHCP lease: {ip}"))
    for ip in old_ips - new_ips:
        alerts.append(("warn", f"  DHCP lease expired: {ip}"))
    vk = "show vlan brief"
    new_vl = _parse_vlan_ids(new_data.get(vk, new_data.get("show vlan-switch", "")))
    old_vl = _parse_vlan_ids(old_data.get(vk, old_data.get("show vlan-switch", "")))
    for v in old_vl - new_vl:
        alerts.append(("warn", f"  VLAN {v} disappeared"))
    for v in new_vl - old_vl:
        alerts.append(("accent", f"  VLAN {v} appeared"))
    return alerts


DARK = """
    QDialog { background-color: #0D1117; }
    QLabel { color: #C9D1D9; background: transparent; }
    QFrame { background: transparent; }
    QFrame[card="true"] { background-color: #1F2630; border-radius: 8px; border: 1px solid #30363D; }
    QListWidget { background-color: #161B22; color: #C9D1D9; border: 1px solid #30363D;
                  border-radius: 6px; padding: 4px; }
    QListWidget::item { padding: 6px; }
    QListWidget::item:selected { background-color: rgba(88,166,255,60); }
    QPlainTextEdit { background-color: #161B22; color: #C9D1D9; border: none;
                     font-family: 'Courier New'; font-size: 11px; }
    QLineEdit { background-color: #161B22; color: #C9D1D9; border: 1px solid #30363D;
                border-radius: 6px; padding: 6px; font-family: 'Courier New'; }
    QPushButton { background-color: #161B22; color: #8B949E; border: none;
                  border-radius: 6px; padding: 6px 14px; }
    QPushButton:hover { background-color: #1F2630; color: white; }
    QPushButton#accent { background-color: #58A6FF; color: white; font-weight: bold; }
    QPushButton#accent:hover { background-color: #4A90E8; }
    QComboBox { background-color: #161B22; color: #C9D1D9; border: 1px solid #30363D;
                border-radius: 6px; padding: 4px 8px; }
    QComboBox QAbstractItemView { background-color: #161B22; color: #C9D1D9; }
    QCheckBox { color: #C9D1D9; }
    QScrollArea { background: transparent; border: none; }
    QTableWidget { background-color: #161B22; color: #C9D1D9; border: none; gridline-color: #30363D; }
    QTableWidget::item:selected { background-color: #264F78; }
    QHeaderView::section { background-color: #1F2630; color: #8B949E; border: none; padding: 4px; }
"""


class DeviceMonitor(QDialog):

    def __init__(self, parent, devices: list, gns3=None, project_id=None):
        super().__init__(parent)
        self.setWindowTitle("Device Monitor")
        self.setStyleSheet(DARK)
        apply_responsive_geometry(self, 1080, 700, min_w=800, min_h=500)

        self.devices = [d for d in devices if d[2].get("console_host") or d[2].get("ip")]
        self._selected_idx = 0
        self._result_queue: queue.Queue = queue.Queue()
        self._closed = False
        self._last_results: dict[str, dict] = {}
        self._current_tab = "fleet"
        self._active_polls: set[str] = set()
        self._auto_timer = None

        self._build_ui()

        if not self.devices:
            self._detail_output.setPlainText("No devices with connection info found.\nImport GNS3 devices first.")
        else:
            QTimer.singleShot(400, self._poll_fleet)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._process_queue)
        self._poll_timer.start(200)

        self.show()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(16, 8, 16, 8)
        lbl_title = QLabel("Device Monitor")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        hdr.addWidget(lbl_title)

        self.btn_fleet = QPushButton("Fleet Overview")
        self.btn_fleet.setObjectName("accent")
        self.btn_fleet.clicked.connect(lambda: self._switch_tab("fleet"))
        hdr.addWidget(self.btn_fleet)

        self.btn_detail = QPushButton("Device Detail")
        self.btn_detail.clicked.connect(lambda: self._switch_tab("detail"))
        hdr.addWidget(self.btn_detail)

        hdr.addStretch()

        self.auto_check = QCheckBox("Auto-poll")
        self.auto_check.stateChanged.connect(self._toggle_auto)
        hdr.addWidget(self.auto_check)

        self.interval_combo = QComboBox()
        self.interval_combo.addItems(list(_POLL_INTERVALS.keys()))
        self.interval_combo.setCurrentText("30 s")
        hdr.addWidget(self.interval_combo)

        self.lbl_status = QLabel("ready")
        self.lbl_status.setStyleSheet(f"color: {_C['muted']};")
        hdr.addWidget(self.lbl_status)
        layout.addLayout(hdr)

        # Body — stacked
        from PySide6.QtWidgets import QStackedWidget
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        # Fleet tab
        fleet_page = QWidget()
        fleet_layout = QVBoxLayout(fleet_page)
        fleet_layout.setContentsMargins(16, 8, 16, 8)

        ft = QHBoxLayout()
        ft.addWidget(QLabel("All Devices"))
        ft.addStretch()
        btn_poll_all = QPushButton("Poll All")
        btn_poll_all.setObjectName("accent")
        btn_poll_all.clicked.connect(self._poll_fleet)
        ft.addWidget(btn_poll_all)
        fleet_layout.addLayout(ft)

        self.fleet_scroll = QScrollArea()
        self.fleet_scroll.setWidgetResizable(True)
        self.fleet_container = QWidget()
        self.fleet_grid = QGridLayout(self.fleet_container)
        self.fleet_grid.setSpacing(12)
        self.fleet_scroll.setWidget(self.fleet_container)
        fleet_layout.addWidget(self.fleet_scroll, 1)

        self._stack.addWidget(fleet_page)

        # Detail tab
        detail_page = QWidget()
        detail_layout = QHBoxLayout(detail_page)
        detail_layout.setContentsMargins(8, 8, 8, 8)

        # Sidebar
        sidebar = QVBoxLayout()
        self.device_listbox = QListWidget()
        self.device_listbox.setFixedWidth(200)
        for name, model, meta in self.devices:
            self.device_listbox.addItem(name)
        self.device_listbox.currentRowChanged.connect(self._on_device_select)
        sidebar.addWidget(self.device_listbox, 1)

        btn_poll = QPushButton("Poll Selected")
        btn_poll.setObjectName("accent")
        btn_poll.clicked.connect(self._poll_selected)
        sidebar.addWidget(btn_poll)

        detail_layout.addLayout(sidebar)

        # Detail content
        detail_right = QVBoxLayout()
        self.lbl_device_header = QLabel("Select a device")
        self.lbl_device_header.setStyleSheet("font-size: 16px; font-weight: bold;")
        detail_right.addWidget(self.lbl_device_header)

        self._detail_scroll = QScrollArea()
        self._detail_scroll.setWidgetResizable(True)
        self._detail_container = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_container)
        self._detail_layout.setAlignment(Qt.AlignTop)
        self._detail_scroll.setWidget(self._detail_container)
        detail_right.addWidget(self._detail_scroll, 1)

        # Ad-hoc command
        adhoc = QHBoxLayout()
        self.ent_adhoc = QLineEdit()
        self.ent_adhoc.setPlaceholderText("Run ad-hoc command...")
        self.ent_adhoc.returnPressed.connect(self._run_adhoc_cmd)
        adhoc.addWidget(self.ent_adhoc, 1)
        btn_adhoc = QPushButton("Run")
        btn_adhoc.setObjectName("accent")
        btn_adhoc.clicked.connect(self._run_adhoc_cmd)
        adhoc.addWidget(btn_adhoc)
        detail_right.addLayout(adhoc)

        self._detail_output = QPlainTextEdit()
        self._detail_output.setReadOnly(True)
        self._detail_output.setMaximumHeight(150)
        detail_right.addWidget(self._detail_output)

        detail_layout.addLayout(detail_right, 1)
        self._stack.addWidget(detail_page)

        self._build_fleet_cards()
        self._switch_tab("fleet")

    def _switch_tab(self, tab):
        self._current_tab = tab
        if tab == "fleet":
            self._stack.setCurrentIndex(0)
            self.btn_fleet.setObjectName("accent")
            self.btn_fleet.setStyleSheet("background-color: #58A6FF; color: white; font-weight: bold; border: none; border-radius: 6px; padding: 6px 14px;")
            self.btn_detail.setStyleSheet("background-color: #161B22; color: #8B949E; border: none; border-radius: 6px; padding: 6px 14px;")
        else:
            self._stack.setCurrentIndex(1)
            self.btn_detail.setObjectName("accent")
            self.btn_detail.setStyleSheet("background-color: #58A6FF; color: white; font-weight: bold; border: none; border-radius: 6px; padding: 6px 14px;")
            self.btn_fleet.setStyleSheet("background-color: #161B22; color: #8B949E; border: none; border-radius: 6px; padding: 6px 14px;")

    def _build_fleet_cards(self):
        self._fleet_cards = {}
        while self.fleet_grid.count():
            item = self.fleet_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, (name, model, meta) in enumerate(self.devices):
            try:
                from ..models.devices import RouterModel, CoreSwitchModel
                if isinstance(model, RouterModel): role = "router"
                elif isinstance(model, CoreSwitchModel): role = "core"
                else: role = "access"
            except Exception:
                role = "access"

            card = QFrame()
            card.setProperty("card", True)
            card.setFixedHeight(120)
            card.setMinimumWidth(240)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)

            top = QHBoxLayout()
            role_colors = {"router": _C["accent"], "core": _C["warn"], "access": _C["muted"]}
            role_lbl = QLabel({"router": "Router", "core": "Core SW", "access": "Access SW"}.get(role, ""))
            role_lbl.setStyleSheet(f"color: {role_colors.get(role, _C['muted'])}; font-size: 10px;")
            top.addWidget(role_lbl)
            top.addStretch()
            score_lbl = QLabel("--")
            score_lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 20px; font-weight: bold;")
            top.addWidget(score_lbl)
            card_layout.addLayout(top)

            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
            card_layout.addWidget(name_lbl)

            info_lbl = QLabel("Not polled yet")
            info_lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 10px;")
            card_layout.addWidget(info_lbl)

            status_lbl = QLabel("")
            status_lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 9px;")
            card_layout.addWidget(status_lbl)

            row, col = divmod(i, 3)
            self.fleet_grid.addWidget(card, row, col)
            self._fleet_cards[name] = {"score": score_lbl, "info": info_lbl, "status": status_lbl, "card": card}

    def _update_fleet_card(self, name, data, ts):
        w = self._fleet_cards.get(name)
        if not w:
            return
        err = data.get("_error", "")
        if err:
            w["score"].setText("!")
            w["score"].setStyleSheet(f"color: {_C['danger']}; font-size: 20px; font-weight: bold;")
            w["info"].setText(f"Error: {err[:40]}")
            w["status"].setText(ts)
            return
        score = _compute_health(data, name in self._last_results)
        color = _health_color(score)
        w["score"].setText(str(score))
        w["score"].setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
        states = _parse_iface_states(data.get("show ip interface brief", ""))
        up = sum(1 for s in states.values() if s == "up")
        w["info"].setText(f"{_health_label(score)}  |  {up}/{len(states)} interfaces up")
        w["status"].setText(f"Last: {ts}")

    def _on_device_select(self, row):
        if row < 0 or row >= len(self.devices):
            return
        self._selected_idx = row
        name = self.devices[row][0]
        self.lbl_device_header.setText(f"  {name}")
        if name in self._last_results:
            self._render_device_detail(name, self._last_results[name])

    def _poll_fleet(self):
        self.lbl_status.setText(f"polling {len(self.devices)} device(s)\u2026")
        self.lbl_status.setStyleSheet(f"color: {_C['warn']};")
        for name, model, meta in self.devices:
            self._start_poll(name, model, meta, source="fleet")

    def _poll_selected(self):
        if not self.devices:
            return
        row = self.device_listbox.currentRow()
        idx = row if row >= 0 else self._selected_idx
        if idx >= len(self.devices):
            return
        name, model, meta = self.devices[idx]
        self.lbl_status.setText(f"polling {name}\u2026")
        self.lbl_status.setStyleSheet(f"color: {_C['warn']};")
        self._start_poll(name, model, meta, source="detail")

    def _start_poll(self, name, model, meta, source="detail"):
        if name in self._active_polls:
            return
        host = meta.get("console_host") or meta.get("ip", "")
        port_raw = meta.get("console_port") or meta.get("port", "")
        if not host:
            self._result_queue.put((source, name, {"_error": "No host configured"}))
            return
        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            self._result_queue.put((source, name, {"_error": f"Invalid port '{port_raw}'"}))
            return
        username, password, enable_pw = _load_device_creds(name, meta)
        cmds = self._commands_for(model)
        self._active_polls.add(name)
        threading.Thread(target=self._run_poll,
                         args=(name, host, port, cmds, source, username, password, enable_pw),
                         daemon=True).start()

    def _commands_for(self, model):
        try:
            from ..models.devices import RouterModel, CoreSwitchModel
            is_router = isinstance(model, RouterModel)
            is_core = isinstance(model, CoreSwitchModel)
        except Exception:
            is_router = is_core = False
        cmds = ["show version", "show ip interface brief", "show interfaces"]
        if is_router:
            cmds += ["show ip route", "show ip arp", "show cdp neighbors", "show ip dhcp binding"]
        elif is_core:
            cmds += ["show vlan-switch", "show vlan brief", "show cdp neighbors", "show spanning-tree summary", "show ip arp"]
        else:
            cmds += ["show vlan-switch", "show vlan brief", "show cdp neighbors", "show spanning-tree"]
        return cmds

    def _run_poll(self, name, host, port, cmds, source, username="", password="", enable_pw=""):
        if telnetlib3 is None:
            data = {"_error": "telnetlib3 not installed"}
        else:
            try:
                data = asyncio.run(self._poll_async(host, port, cmds, username, password, enable_pw))
            except Exception as exc:
                data = {"_error": str(exc)}
        self._active_polls.discard(name)
        self._result_queue.put((source, name, data))

    async def _poll_async(self, host, port, cmds, username="", password="", enable_pw=""):
        reader, writer = await asyncio.wait_for(telnetlib3.open_connection(host, port), timeout=12)

        async def _read_prompt(timeout=5.0):
            buf = ""
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=0.5)
                    if chunk:
                        buf += chunk
                        if buf.rstrip() and buf.rstrip()[-1] in (">", "#"):
                            break
                except asyncio.TimeoutError:
                    break
            return buf

        results = {}
        try:
            await asyncio.sleep(0.6)
            await _read_prompt(3.0)
            writer.write("terminal length 0\r\n")
            await asyncio.sleep(0.3)
            await _read_prompt(3.0)
            for cmd in cmds:
                writer.write(cmd + "\r\n")
                await asyncio.sleep(0.3)
                t = 10.0 if "interfaces" in cmd else 5.0
                results[cmd] = await _read_prompt(t)
            writer.close()
        except Exception as exc:
            try:
                writer.close()
            except Exception:
                pass
            results["_error"] = str(exc)
        return results

    def _process_queue(self):
        if self._closed:
            return
        while not self._result_queue.empty():
            source, name, data = self._result_queue.get()
            ts = time.strftime("%H:%M:%S")
            if source == "adhoc":
                self._detail_output.setPlainText(data.get("_adhoc_raw", "") or data.get("_error", ""))
                continue
            err = data.get("_error", "")
            old_data = self._last_results.get(name)
            if not err:
                self._last_results[name] = data
            self._update_fleet_card(name, data, ts)
            is_selected = self._selected_idx < len(self.devices) and self.devices[self._selected_idx][0] == name
            if source == "detail" or (self._current_tab == "detail" and is_selected):
                if err:
                    self.lbl_status.setText(f"error {ts}")
                    self.lbl_status.setStyleSheet(f"color: {_C['danger']};")
                    self._clear_detail()
                    self._add_detail_text(f"Error connecting to '{name}':\n{err}", _C["danger"])
                else:
                    self.lbl_status.setText(f"updated {ts}")
                    self.lbl_status.setStyleSheet(f"color: {_C['success']};")
                    alerts = _detect_changes(data, old_data) if old_data else []
                    self._clear_detail()
                    for level, msg in alerts:
                        self._add_detail_text(msg, _C.get(level, _C["muted"]))
                    self._render_device_detail(name, data)
        if not self._active_polls and self.devices:
            done = sum(1 for n, _, __ in self.devices if n in self._last_results)
            self.lbl_status.setText(f"last poll: {time.strftime('%H:%M:%S')}  ({done}/{len(self.devices)} devices)")
            self.lbl_status.setStyleSheet(f"color: {_C['success']};")

    def _clear_detail(self):
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_detail_text(self, text, color=None):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        if color:
            lbl.setStyleSheet(f"color: {color};")
        self._detail_layout.addWidget(lbl)

    def _add_detail_section(self, title):
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {_C['accent']}; font-size: 14px; font-weight: bold; padding-top: 8px;")
        self._detail_layout.addWidget(lbl)

    def _render_device_detail(self, name, data):
        score = _compute_health(data, name in self._last_results)
        color = _health_color(score)
        self._add_detail_text(f"Health Score: {score}  ({_health_label(score)})", color)

        for cmd, raw in data.items():
            if cmd.startswith("_"):
                continue
            label = _CMD_LABELS.get(cmd, cmd)
            if _is_invalid(raw):
                continue
            self._add_detail_section(label)
            txt = QPlainTextEdit()
            txt.setPlainText(raw.strip())
            txt.setReadOnly(True)
            txt.setMaximumHeight(180)
            self._detail_layout.addWidget(txt)

    def _run_adhoc_cmd(self):
        cmd = self.ent_adhoc.text().strip()
        if not cmd or not self.devices:
            return
        idx = self._selected_idx
        if idx >= len(self.devices):
            return
        name, model, meta = self.devices[idx]
        host = meta.get("console_host") or meta.get("ip", "")
        port_raw = meta.get("console_port") or meta.get("port", "")
        if not host:
            self._detail_output.setPlainText("No host configured")
            return
        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            self._detail_output.setPlainText(f"Invalid port: {port_raw}")
            return
        self._detail_output.setPlainText(f"Running '{cmd}'...")
        username, password, enable_pw = _load_device_creds(name, meta)

        def worker():
            if telnetlib3 is None:
                self._result_queue.put(("adhoc", name, {"_error": "telnetlib3 not installed"}))
                return
            try:
                result = asyncio.run(self._poll_async(host, port, [cmd], username, password, enable_pw))
                self._result_queue.put(("adhoc", name, {"_adhoc_raw": result.get(cmd, "")}))
            except Exception as exc:
                self._result_queue.put(("adhoc", name, {"_error": str(exc)}))
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_auto(self):
        if self.auto_check.isChecked():
            interval = _POLL_INTERVALS.get(self.interval_combo.currentText(), 30000)
            self._auto_timer = QTimer(self)
            self._auto_timer.timeout.connect(self._poll_fleet)
            self._auto_timer.start(interval)
        else:
            if self._auto_timer:
                self._auto_timer.stop()
                self._auto_timer = None

    def closeEvent(self, event):
        self._closed = True
        if self._poll_timer:
            self._poll_timer.stop()
        if self._auto_timer:
            self._auto_timer.stop()
        event.accept()
