"""
Smart Bulk Operations — topology detection, config suggestion, and parallel deploy.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import List, Dict, Tuple, Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel,
    QPushButton, QPlainTextEdit, QCheckBox, QScrollArea, QWidget,
    QMessageBox, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCharFormat, QColor

from ..models import RouterModel, SwitchModel, CoreSwitchModel  # noqa: F401
from ..network import Sender
from .utils import apply_responsive_geometry
from ..config import conn, cur, db_lock


def _config_hash(text: str) -> str:
    """Return a short SHA-256 hex digest of a config string."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _load_deployed_hash(device_name: str) -> str:
    """Fetch the last-deployed config hash from the database (empty string if none)."""
    try:
        with db_lock:
            cur.execute(
                "SELECT deployed_config_hash FROM devices WHERE name=?",
                (device_name,),
            )
            row = cur.fetchone()
            return (row[0] or "") if row else ""
    except Exception:
        return ""


def _save_deployed_hash(device_name: str, config_hash: str) -> None:
    """Persist a successfully-deployed config hash to the database."""
    try:
        with db_lock:
            cur.execute(
                "UPDATE devices SET deployed_config_hash=? WHERE name=?",
                (config_hash, device_name),
            )
            conn.commit()
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Theme constants (match main app)
# ─────────────────────────────────────────────────────────────────────────────
_BG     = "#0D1117"
_PANEL  = "#161B22"
_CARD   = "#1F2630"
_ACCENT = "#58A6FF"
_GREEN  = "#3fb950"
_RED    = "#f85149"
_YELLOW = "#d29922"
_TEXT   = "#C9D1D9"
_MUTED  = "#8B949E"
_BORDER = "#30363D"
_FONT   = "Inter"

DARK_STYLE = f"""
QDialog {{
    background-color: {_BG};
}}
QFrame {{
    background-color: transparent;
}}
QFrame[panel="true"] {{
    background-color: {_PANEL};
    border-radius: 10px;
}}
QFrame[card="true"] {{
    background-color: {_CARD};
    border-radius: 8px;
}}
QLabel {{
    color: {_TEXT};
    background: transparent;
}}
QPushButton {{
    background-color: {_ACCENT};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: bold;
}}
QPushButton:hover {{
    background-color: #388bfd;
}}
QPushButton:disabled {{
    background-color: #30363D;
    color: {_MUTED};
}}
QPushButton[outline="true"] {{
    background-color: transparent;
    color: {_ACCENT};
    border: 1px solid {_ACCENT};
}}
QPushButton[outline="true"]:hover {{
    background-color: #28313E;
}}
QPlainTextEdit {{
    background-color: {_CARD};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 8px;
    font-family: "Courier New";
    font-size: 12px;
}}
QCheckBox {{
    color: {_MUTED};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {_BORDER};
    background-color: {_CARD};
}}
QCheckBox::indicator:checked {{
    background-color: {_ACCENT};
    border-color: {_ACCENT};
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# 1. TopologyDetector
# ─────────────────────────────────────────────────────────────────────────────

class TopologyDetector:
    """
    Reads the devices list and classifies it into a topology dict.

    Returns:
        {
            "routers":  [(name, model, meta), ...],
            "cores":    [(name, model, meta), ...],
            "switches": [(name, model, meta), ...],
            "pattern":  "router-core-access" | "router-only" |
                        "core-access" | "flat" | "empty",
        }
    """

    def __init__(self, devices: List[Tuple[str, Any, dict]]):
        self.devices = devices

    def detect(self) -> dict:
        routers, cores, switches = [], [], []
        for entry in self.devices:
            name, model, meta = entry
            if isinstance(model, RouterModel):
                routers.append(entry)
            elif isinstance(model, CoreSwitchModel):
                cores.append(entry)
            else:
                switches.append(entry)

        has_router  = len(routers) > 0
        has_core    = len(cores) > 0
        has_access  = len(switches) > 0

        if not self.devices:
            pattern = "empty"
        elif has_router and has_core and has_access:
            pattern = "router-core-access"
        elif has_router and not has_core and has_access:
            pattern = "router-access"
        elif not has_router and has_core and has_access:
            pattern = "core-access"
        elif has_router and not has_core and not has_access:
            pattern = "router-only"
        else:
            pattern = "flat"

        return {
            "routers":  routers,
            "cores":    cores,
            "switches": switches,
            "pattern":  pattern,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. ConfigSuggester
# ─────────────────────────────────────────────────────────────────────────────

_VLAN_PLAN = [
    {"id": "10", "name": "Management"},
    {"id": "20", "name": "Users"},
    {"id": "30", "name": "Servers"},
]

_SUBNET_BASE = "192.168.{vlan_idx}.0"
_GW_BASE     = "192.168.{vlan_idx}.1"
_MASK        = "255.255.255.0"
_DNS         = "8.8.8.8"


class ConfigSuggester:
    """
    Produces per-device config bucket dicts (same structures the wizard uses)
    based on the detected topology.

    Each entry in the returned list:
        {
            "device":   (name, model, meta),
            "role":     "router" | "core" | "access",
            "buckets":  { identity_data, vlans, routing_entries,
                          dhcp_pools, uplinks, static_routes,
                          router_interface, enable_rip }
        }
    """

    def __init__(self, topology: dict):
        self.topology = topology

    # ── public API ────────────────────────────────────────────────────────────

    def suggest(self) -> List[dict]:
        pattern  = self.topology["pattern"]
        routers  = self.topology["routers"]
        cores    = self.topology["cores"]
        switches = self.topology["switches"]

        plans = []

        if pattern == "router-core-access":
            plans += [self._plan_router(d)  for d in routers]
            plans += [self._plan_core(d)    for d in cores]
            plans += [self._plan_access(d, idx) for idx, d in enumerate(switches)]

        elif pattern == "router-access":
            plans += [self._plan_router(d) for d in routers]
            plans += [self._plan_access(d, idx) for idx, d in enumerate(switches)]

        elif pattern == "core-access":
            plans += [self._plan_core(d)   for d in cores]
            plans += [self._plan_access(d, idx) for idx, d in enumerate(switches)]

        elif pattern == "router-only":
            plans += [self._plan_router(d) for d in routers]

        else:
            all_devs = routers + cores + switches
            for idx, d in enumerate(all_devs):
                plans.append(self._plan_access(d, idx))

        return plans

    # ── per-role helpers ─────────────────────────────────────────────────────

    def _iface0(self, meta: dict) -> str:
        ifaces = meta.get("interfaces", [])
        return ifaces[0] if ifaces else "FastEthernet0/0"

    def _plan_router(self, device: tuple) -> dict:
        name, model, meta = device
        iface = self._iface0(meta)

        routing = []
        for i, v in enumerate(_VLAN_PLAN, start=1):
            routing.append({
                "vlan":  v["id"],
                "name":  v["name"],
                "ip":    f"192.168.{i}0.1",
                "mask":  _MASK,
            })

        dhcp = []
        for entry in routing:
            prefix = entry["ip"].rsplit(".", 1)[0]
            dhcp.append({
                "pool":    entry["name"],
                "network": f"{prefix}.0",
                "mask":    _MASK,
                "gateway": entry["ip"],
                "dns":     _DNS,
                "start":   f"{prefix}.50",
                "end":     f"{prefix}.200",
            })

        return {
            "device": device,
            "role":   "router",
            "buckets": {
                "identity_data":   {"hostname": name, "domain": "", "enable": "ChangeMe123!"},
                "vlans":           [],
                "routing_entries": routing,
                "dhcp_pools":      dhcp,
                "uplinks":         [],
                "static_routes":   [{"network": "0.0.0.0", "mask": "0.0.0.0",
                                     "next-hop": "10.0.0.1", "description": "Default route to ISP"}],
                "acl_rules":       [],
                "router_interface": iface,
                "enable_rip":      False,
                "rip_networks":    [],
            },
        }

    def _plan_core(self, device: tuple) -> dict:
        name, model, meta = device

        vlans = []
        routing = []
        for i, v in enumerate(_VLAN_PLAN, start=1):
            vlans.append({"id": v["id"], "name": v["name"], "ports": ""})
            routing.append({
                "vlan":  v["id"],
                "name":  v["name"],
                "ip":    f"192.168.{i}0.1",
                "mask":  _MASK,
            })

        return {
            "device": device,
            "role":   "core",
            "buckets": {
                "identity_data":   {"hostname": name, "domain": "", "enable": "ChangeMe123!"},
                "vlans":           vlans,
                "routing_entries": routing,
                "dhcp_pools":      [],
                "uplinks":         [],
                "static_routes":   [],
                "acl_rules":       [],
                "router_interface": "",
                "enable_rip":      False,
                "rip_networks":    [],
            },
        }

    def _plan_access(self, device: tuple, switch_index: int) -> dict:
        name, model, meta = device
        ifaces = meta.get("interfaces", [])

        n_vlans = len(_VLAN_PLAN)
        per_v   = max(1, len(ifaces) // n_vlans) if ifaces else 4

        vlans = []
        for i, v in enumerate(_VLAN_PLAN):
            if ifaces:
                start_i = i * per_v
                end_i   = min(start_i + per_v - 1, len(ifaces) - 1)
                first = ifaces[start_i]
                last  = ifaces[end_i]
                if first == last:
                    ports = first
                else:
                    prefix = first.rsplit("/", 1)[0]
                    ports = f"{prefix}/{first.rsplit('/',1)[1]}-{last.rsplit('/',1)[1]}"
            else:
                ports = f"Ethernet{i}/0-3"
            vlans.append({"id": v["id"], "name": v["name"], "ports": ports})

        uplink_port = ifaces[-1] if ifaces else "Ethernet3/3"
        uplinks = [{"ports": uplink_port, "mode": "trunk", "allowed vlans": "all"}]

        return {
            "device": device,
            "role":   "access",
            "buckets": {
                "identity_data":   {"hostname": name, "domain": "", "enable": "ChangeMe123!"},
                "vlans":           vlans,
                "routing_entries": [],
                "dhcp_pools":      [],
                "uplinks":         uplinks,
                "static_routes":   [],
                "acl_rules":       [],
                "router_interface": "",
                "enable_rip":      False,
                "rip_networks":    [],
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. BulkDeployPanel
# ─────────────────────────────────────────────────────────────────────────────

_PATTERN_LABELS = {
    "router-core-access": "Router + Core Switch + Access Switches",
    "router-access":      "Router + Access Switches (no core)",
    "core-access":        "Core Switch + Access Switches (no router)",
    "router-only":        "Router only",
    "flat":               "Mixed / flat topology",
    "empty":              "No devices imported",
}

_ROLE_ICONS = {
    "router": "\U0001F500",
    "core":   "\U0001F536",
    "access": "\U0001F537",
}


class BulkDeployPanel(QDialog):
    """
    Main window for smart bulk operations.

    Shows:
      - Topology detection summary
      - Per-device suggestion cards with Customize button
      - Deploy All button with live per-device progress log
    """

    def __init__(self, parent, devices: List[Tuple[str, Any, dict]]):
        super().__init__(parent)
        self.parent_app = parent
        self.devices    = devices

        self.setWindowTitle("Smart Bulk Deploy")
        self.setMinimumSize(700, 500)
        self.resize(900, 680)
        self.setStyleSheet(DARK_STYLE)
        self.setWindowModality(Qt.ApplicationModal)
        self._deploy_running = False

        self.topology = TopologyDetector(devices).detect()
        self.plans    = ConfigSuggester(self.topology).suggest()

        self._customised: Dict[int, bool] = {}

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Header ──
        hdr = QFrame()
        hdr.setProperty("panel", True)
        hdr.setFixedHeight(60)
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(20, 0, 20, 0)

        title_lbl = QLabel("Smart Bulk Deploy")
        title_lbl.setFont(QFont(_FONT, 18, QFont.Bold))
        hdr_lay.addWidget(title_lbl)

        pattern_label = _PATTERN_LABELS.get(self.topology["pattern"], self.topology["pattern"])
        info_lbl = QLabel(f"Detected: {pattern_label}  \u2022  {len(self.plans)} device(s)")
        info_lbl.setFont(QFont(_FONT, 12))
        info_lbl.setStyleSheet(f"color: {_MUTED};")
        hdr_lay.addWidget(info_lbl)
        hdr_lay.addStretch()

        root_layout.addWidget(hdr)

        # ── Body: two columns ──
        body = QFrame()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(16, 12, 16, 12)
        body_lay.setSpacing(8)

        # Left: device plan cards (scrollable)
        left_panel = QFrame()
        left_panel.setProperty("panel", True)
        left_vbox = QVBoxLayout(left_panel)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(0)

        plan_title = QLabel("  Configuration Plan")
        plan_title.setFont(QFont(_FONT, 14, QFont.Bold))
        plan_title.setStyleSheet(f"color: {_MUTED}; padding: 14px 16px 8px 16px;")
        left_vbox.addWidget(plan_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self._cards_layout = QVBoxLayout(scroll_content)
        self._cards_layout.setContentsMargins(12, 0, 12, 12)
        self._cards_layout.setSpacing(8)

        if not self.plans:
            empty_lbl = QLabel("No devices to configure.\nImport devices from GNS3 first.")
            empty_lbl.setStyleSheet(f"color: {_MUTED};")
            empty_lbl.setFont(QFont(_FONT, 13))
            empty_lbl.setAlignment(Qt.AlignCenter)
            self._cards_layout.addWidget(empty_lbl)
        else:
            for idx, plan in enumerate(self.plans):
                self._build_plan_card(idx, plan)

        self._cards_layout.addStretch()
        scroll.setWidget(scroll_content)
        left_vbox.addWidget(scroll)

        body_lay.addWidget(left_panel, stretch=3)

        # Right: log area + deploy button
        right_panel = QFrame()
        right_panel.setProperty("panel", True)
        right_vbox = QVBoxLayout(right_panel)
        right_vbox.setContentsMargins(12, 14, 12, 16)
        right_vbox.setSpacing(6)

        log_title = QLabel("Deploy Log")
        log_title.setFont(QFont(_FONT, 14, QFont.Bold))
        log_title.setStyleSheet(f"color: {_MUTED};")
        right_vbox.addWidget(log_title)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        right_vbox.addWidget(self.log_box, stretch=1)

        # Force re-deploy toggle
        self._force_checkbox = QCheckBox("Force re-deploy (ignore 'already deployed' check)")
        self._force_checkbox.setFont(QFont(_FONT, 11))
        right_vbox.addWidget(self._force_checkbox)

        # Deploy All button
        self.deploy_btn = QPushButton("Deploy All")
        self.deploy_btn.setFont(QFont(_FONT, 14, QFont.Bold))
        self.deploy_btn.setFixedHeight(40)
        self.deploy_btn.clicked.connect(self._deploy_all)
        right_vbox.addWidget(self.deploy_btn)

        # Generate-only button
        gen_btn = QPushButton("Generate Configs Only")
        gen_btn.setProperty("outline", True)
        gen_btn.setFont(QFont(_FONT, 13))
        gen_btn.setFixedHeight(34)
        gen_btn.clicked.connect(self._generate_only)
        right_vbox.addWidget(gen_btn)

        body_lay.addWidget(right_panel, stretch=2)
        root_layout.addWidget(body, stretch=1)

    def _build_plan_card(self, idx: int, plan: dict):
        name, model, meta = plan["device"]
        role   = plan["role"]
        icon   = _ROLE_ICONS.get(role, "\u25A1")

        stored_hash = _load_deployed_hash(name)
        current_hash = _config_hash(model.build_full_config()) if model.templates else ""
        if not stored_hash:
            init_status, init_color = "\u25CF Not deployed", _ACCENT
            should_include = True
        elif current_hash == stored_hash:
            init_status, init_color = "\u2713 Deployed", _GREEN
            should_include = False
        else:
            init_status, init_color = "\u2191 Modified", _YELLOW
            should_include = True

        plan["_stored_hash"] = stored_hash

        card = QFrame()
        card.setProperty("card", True)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        card_lay.setSpacing(4)

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel(f"{icon}  {name}")
        title_lbl.setFont(QFont(_FONT, 13, QFont.Bold))
        title_row.addWidget(title_lbl)

        title_row.addStretch()

        # Status badge
        status_lbl = QLabel(init_status)
        status_lbl.setFont(QFont(_FONT, 11))
        status_lbl.setStyleSheet(f"color: {init_color};")
        title_row.addWidget(status_lbl)
        plan["_status_lbl"] = status_lbl

        # Include checkbox
        include_cb = QCheckBox("Deploy")
        include_cb.setFont(QFont(_FONT, 11))
        include_cb.setChecked(should_include)
        title_row.addWidget(include_cb)
        plan["_include_cb"] = include_cb

        card_lay.addLayout(title_row)

        # Summary
        summary = self._plan_summary(plan)
        sum_lbl = QLabel(summary)
        sum_lbl.setFont(QFont(_FONT, 11))
        sum_lbl.setStyleSheet(f"color: {_MUTED};")
        sum_lbl.setWordWrap(True)
        card_lay.addWidget(sum_lbl)

        # Customize button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cust_btn = QPushButton("Customize in Wizard")
        cust_btn.setProperty("outline", True)
        cust_btn.setFont(QFont(_FONT, 12))
        cust_btn.setFixedHeight(28)
        cust_btn.clicked.connect(lambda checked=False, i=idx: self._customize(i))
        btn_row.addWidget(cust_btn)
        card_lay.addLayout(btn_row)

        self._cards_layout.addWidget(card)

    def _plan_summary(self, plan: dict) -> str:
        bkts = plan["buckets"]
        role = plan["role"]
        lines = []

        if role == "router":
            iface = bkts.get("router_interface") or "FastEthernet0/0"
            n_sub = len(bkts.get("routing_entries", []))
            n_dhcp = len(bkts.get("dhcp_pools", []))
            lines.append(f"Interface: {iface}  \u2022  {n_sub} subinterface(s)")
            lines.append(f"DHCP pools: {n_dhcp}  \u2022  Default route to ISP")
        elif role == "core":
            n_v = len(bkts.get("vlans", []))
            lines.append(f"{n_v} VLANs  \u2022  SVI routing (ip routing)")
        elif role == "access":
            n_v = len(bkts.get("vlans", []))
            up  = bkts.get("uplinks", [{}])
            lines.append(f"{n_v} VLANs  \u2022  Trunk uplink: {up[0].get('ports','\u2014') if up else '\u2014'}")

        pw = bkts.get("identity_data", {}).get("enable", "\u2014")
        lines.append(f"Enable password: {pw}")
        return "\n".join(lines)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _customize(self, idx: int):
        """Open the existing GuidedSetupWizard pre-filled with this plan's buckets."""
        from .wizards.guided_setup_wizard import GuidedSetupWizard

        plan = self.plans[idx]
        name, model, meta = plan["device"]
        role  = plan["role"]
        bkts  = plan["buckets"]

        if isinstance(model, RouterModel):
            device_role = "router"
        elif isinstance(model, CoreSwitchModel):
            device_role = "core"
        else:
            device_role = "access"

        win = GuidedSetupWizard(
            self, name, model,
            device_role=device_role,
            known_interfaces=meta.get("interfaces", []),
        )
        win.identity_data    = dict(bkts["identity_data"])
        win.vlans            = list(bkts["vlans"])
        win.routing_entries  = list(bkts["routing_entries"])
        win.dhcp_pools       = list(bkts["dhcp_pools"])
        win.uplinks          = list(bkts["uplinks"])
        win.static_routes    = list(bkts["static_routes"])
        win.acl_rules        = list(bkts["acl_rules"])
        win.router_interface = bkts["router_interface"]
        win.enable_rip       = bkts["enable_rip"]
        win.rip_networks     = list(bkts["rip_networks"])
        win.current_step = 1
        win._render_step()
        win.exec()
        self._customised[idx] = True
        plan["_stored_hash"] = ""
        self._set_plan_status(plan, "\u2191 Modified")
        self._set_plan_status_color(plan, _YELLOW)
        cb = plan.get("_include_cb")
        if cb:
            cb.setChecked(True)

    def _generate_only(self):
        """Generate configs for all devices silently (no send)."""
        if not self.plans:
            return
        self._log_write("Generating configs for all devices...\n")
        for idx, plan in enumerate(self.plans):
            self._apply_plan_to_model(idx, plan)
            name = plan["device"][0]
            self._log_write(f"  [OK] {name} \u2014 config generated\n")
        self._log_write("\nDone. Use 'Send' in the main window for individual devices,\nor click 'Deploy All' to push all configs now.\n")
        QMessageBox.information(
            self,
            "Configs Generated",
            "All configs have been generated.\nYou can review them in the main window by selecting each device.",
        )

    def _deploy_all(self):
        """Generate all configs then push them in parallel via Telnet."""
        if not self.plans:
            QMessageBox.warning(self, "No devices", "No devices in the plan.")
            return

        gns3_only = [p for p in self.plans if p["device"][2].get("gns3_node")]
        if not gns3_only:
            QMessageBox.warning(
                self,
                "No GNS3 devices",
                "Bulk deploy requires GNS3 devices with console IP/port.\n"
                "Import devices from GNS3 first.",
            )
            return

        force = self._force_checkbox.isChecked()
        self.deploy_btn.setEnabled(False)
        self.deploy_btn.setText("Deploying...")
        self._log_write("=== Bulk Deploy Started ===\n\n")
        if force:
            self._log_write("\u26A0  Force re-deploy enabled \u2014 skipping hash check\n\n")

        for idx, plan in enumerate(self.plans):
            self._apply_plan_to_model(idx, plan)

        threads = []
        self._deploy_running = True
        for idx, plan in enumerate(self.plans):
            name = plan["device"][0]
            meta = plan["device"][2]

            cb = plan.get("_include_cb")
            if cb and not cb.isChecked():
                self._log_write(f"[SKIP] {name} \u2014 excluded by checkbox\n")
                self._set_plan_status(plan, "skipped")
                continue

            if not meta.get("gns3_node"):
                self._log_write(f"[SKIP] {name} \u2014 not a GNS3 device\n")
                self._set_plan_status(plan, "skipped")
                continue

            t = threading.Thread(
                target=self._send_one,
                args=(idx, plan, force),
                daemon=True,
            )
            threads.append(t)
            t.start()

        def _wait_all():
            for t in threads:
                t.join()
            self._deploy_running = False
            QTimer.singleShot(0, lambda: self.deploy_btn.setEnabled(True))
            QTimer.singleShot(0, lambda: self.deploy_btn.setText("Deploy All"))
            QTimer.singleShot(0, lambda: self._log_write("\n=== Bulk Deploy Complete ===\n"))

        threading.Thread(target=_wait_all, daemon=True).start()

    def _send_one(self, idx: int, plan: dict, force: bool = False):
        name, model, meta = plan["device"]
        host   = meta.get("console_host", "localhost")
        port   = meta.get("console_port", "")
        config = model.build_full_config()

        if not config.strip():
            self._log_write(f"[{name}] No config to send \u2014 run Generate first.\n")
            self._set_plan_status(plan, "no config")
            return

        current_hash = _config_hash(config)
        stored_hash  = plan.get("_stored_hash", "")
        if stored_hash and current_hash == stored_hash and not force:
            self._log_write(
                f"[{name}] Config unchanged since last deploy \u2014 skipping. "
                f"Enable 'Force re-deploy' to push anyway.\n"
            )
            self._set_plan_status(plan, "\u2713 Up-to-date")
            self._set_plan_status_color(plan, _GREEN)
            return

        self._log_write(f"[{name}] Connecting to {host}:{port}...\n")
        self._set_plan_status(plan, "connecting\u2026")
        self._set_plan_status_color(plan, _MUTED)

        try:
            port_int = int(port) if port else 23
        except (ValueError, TypeError):
            port_int = 23

        identity = plan.get("buckets", {}).get("identity_data", {})
        username = identity.get("username") or meta.get("username", "")
        password = identity.get("password") or meta.get("password", "")
        enable_pw = identity.get("enable") or meta.get("enable_pw", "")

        try:
            Sender.send_telnet(
                log_fn=lambda msg: self._log_write(f"  [{name}] {msg}\n"),
                host=host,
                port=port_int,
                username=username,
                password=password,
                enable_pw=enable_pw,
                text=config,
            )
            _save_deployed_hash(name, current_hash)
            plan["_stored_hash"] = current_hash
            self._log_write(f"[{name}] Config sent successfully.\n")
            self._set_plan_status(plan, "\u2713 Deployed")
            self._set_plan_status_color(plan, _GREEN)
        except Exception as e:
            self._log_write(f"[{name}] ERROR: {e}\n")
            self._set_plan_status(plan, "\u2717 Failed")
            self._set_plan_status_color(plan, _RED)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _apply_plan_to_model(self, idx: int, plan: dict):
        """Write wizard templates onto the device model using the plan's buckets."""
        from .wizards.guided_setup_wizard import GuidedSetupWizard

        name, model, meta = plan["device"]
        bkts  = plan["buckets"]
        role  = plan["role"]

        if isinstance(model, RouterModel):
            device_role = "router"
        elif isinstance(model, CoreSwitchModel):
            device_role = "core"
        else:
            device_role = "access"

        wiz = GuidedSetupWizard(
            self, name, model,
            device_role=device_role,
            known_interfaces=meta.get("interfaces", []),
            headless=True,
        )
        wiz.identity_data    = dict(bkts["identity_data"])
        wiz.vlans            = list(bkts["vlans"])
        wiz.routing_entries  = list(bkts["routing_entries"])
        wiz.dhcp_pools       = list(bkts["dhcp_pools"])
        wiz.uplinks          = list(bkts["uplinks"])
        wiz.static_routes    = list(bkts["static_routes"])
        wiz.acl_rules        = list(bkts["acl_rules"])
        wiz.router_interface = bkts["router_interface"]
        wiz.enable_rip       = bkts["enable_rip"]
        wiz.rip_networks     = list(bkts["rip_networks"])
        wiz._write_templates()
        wiz.close()

    def closeEvent(self, event):
        """Guard window close while deploy threads are running."""
        if self._deploy_running:
            reply = QMessageBox.question(
                self,
                "Deploy in progress",
                "A bulk deploy is currently running.\n"
                "Closing now may leave devices partially configured.\n\n"
                "Close anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()

    def _set_plan_status(self, plan: dict, text: str):
        """Thread-safe wrapper for updating a plan's status label."""
        try:
            lbl = plan.get("_status_lbl")
            if lbl:
                QTimer.singleShot(0, lambda: lbl.setText(text))
        except Exception:
            pass

    def _set_plan_status_color(self, plan: dict, color: str):
        """Thread-safe wrapper for updating the status label color."""
        try:
            lbl = plan.get("_status_lbl")
            if lbl:
                QTimer.singleShot(0, lambda: lbl.setStyleSheet(f"color: {color};"))
        except Exception:
            pass

    def _log_write(self, msg: str):
        """Thread-safe log write — updates local log_box AND main app Logs tab."""
        def _write():
            try:
                self.log_box.appendPlainText(msg.rstrip("\n"))
            except Exception:
                pass
            stripped = msg.strip()
            if stripped:
                try:
                    self.parent_app.log(f"[BulkDeploy] {stripped}")
                except Exception:
                    pass
        try:
            QTimer.singleShot(0, _write)
        except Exception:
            pass
