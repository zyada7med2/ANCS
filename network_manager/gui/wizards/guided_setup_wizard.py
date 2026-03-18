"""
Guided multi-step setup wizard — smart forms edition.

Every step asks the minimum questions needed; all other config values
(DHCP pools, routing entries, ACL rules) are auto-derived so the user
never has to edit raw tables or type IOS syntax manually.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Dict, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QProgressBar, QFrame, QScrollArea, QComboBox, QCheckBox, QSpinBox,
    QRadioButton, QButtonGroup, QMessageBox, QApplication,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ..utils import apply_responsive_geometry

if TYPE_CHECKING:
    pass

# ──────────────────────────── help text ───────────────────────────────────────
HELP_TEXT: Dict[str, str] = {
    "VLAN": (
        "A VLAN is like a separate virtual network inside your switch. "
        "Devices in one VLAN cannot talk to another unless you explicitly allow it.\n"
        "Example: Staff VLAN 10, Guest VLAN 20."
    ),
    "Gateway": (
        "The gateway IP is the address of this device that other devices use to "
        "reach other networks or the internet. Usually the first usable IP in the "
        "subnet (e.g. 192.168.10.1 for VLAN 10)."
    ),
    "Enable secret": (
        "A hashed password required to enter privileged (enable) mode and change "
        "device settings. Choose something strong and memorable."
    ),
    "Trunk": (
        "A trunk port carries traffic for multiple VLANs between switches or "
        "between a switch and a router. Use it for uplink ports."
    ),
    "SVI": (
        "Switch Virtual Interface — an IP address assigned directly to a VLAN on a "
        "Layer 3 switch. Acts as the default gateway for devices in that VLAN."
    ),
    "Subinterface": (
        "A logical division of a physical interface. Routers use subinterfaces to "
        "route traffic for multiple VLANs over a single cable (router-on-a-stick)."
    ),
    "ACL": (
        "Access Control List — a set of rules that allow or deny traffic based on "
        "source IP, destination IP, or other criteria."
    ),
    "Wildcard": (
        "The inverse of a subnet mask. For 255.255.255.0 (/24) the wildcard is "
        "0.0.0.255. Used in ACLs to match a range of IP addresses."
    ),
    "DHCP pool": (
        "A range of IP addresses the device hands out automatically to connected "
        "devices (laptops, phones, etc.) so they don't need static IPs."
    ),
    "Next-hop": (
        "The IP address of the next router on the path to a destination network. "
        "Traffic is forwarded there when no more-specific route exists."
    ),
}

# Preset catalogue: key -> (display_name, short_description)
PRESET_CATALOGUE = {
    "small_office": (
        "Small Office",
        "Staff + Guest VLANs · DHCP for both · default internet route · basic ACL",
    ),
    "school_lab": (
        "School / Lab",
        "Students + Teachers + Servers VLANs · DHCP · ACL protecting servers",
    ),
    "minimal": (
        "Minimal",
        "Single default VLAN · basic identity only",
    ),
}


# ──────────────────────────── Step dataclass ──────────────────────────────────
@dataclass
class Step:
    title: str
    description: str
    build_ui: Callable[["GuidedSetupWizard", QWidget], None]
    validate: Callable[["GuidedSetupWizard"], bool]


# ══════════════════════════════════════════════════════════════════════════════
class GuidedSetupWizard(QDialog):
    """
    Smart guided wizard — asks minimal questions and derives complete IOS
    configurations from the answers. No row-by-row table editing required.

    Device roles:
        "router"  – router-on-a-stick (subinterfaces, DHCP, static routes, RIP, ACL)
        "core"    – Layer 3 switch (VLANs, SVIs, ACL)
        "access"  – Layer 2 switch (VLANs, uplink trunk, optional ACL)
    """

    THEME = {
        "bg":       "#0D1117",
        "sidebar":  "#161B22",
        "card":     "#1F2630",
        "input":    "#0F1723",
        "text":     "#C9D1D9",
        "muted":    "#8B949E",
        "accent":   "#58A6FF",
        "success":  "#3FB950",
        "border":   "#30363D",
        "row_alt":  "#1A2030",
    }

    def __init__(
        self,
        parent,
        device_name: str,
        device_model,
        device_role: str = "router",
        known_interfaces: list = None,
        headless: bool = False,
        project_context: dict = None,
        connected_links: list = None,
    ):
        super().__init__(parent)

        # Accept non-Qt parent (e.g. from bulk_deploy which uses Tkinter)
        if parent is not None:
            try:
                from PySide6.QtWidgets import QWidget
                if not isinstance(parent, QWidget):
                    parent = None
            except Exception:
                parent = None
        if parent is not None:
            self.setParent(parent)

        self.headless = headless

        if headless:
            self.hide()
        else:
            self.setWindowTitle("Guided Setup — Smart Wizard")
            self.setMinimumSize(1080, 700)
            apply_responsive_geometry(self, 1240, 820, min_w=1080, min_h=700)
            self._apply_dark_theme()

        self.parent            = parent
        self.device_name       = device_name
        self.device_model      = device_model
        self.device_role       = device_role   # "router" | "core" | "access"
        self.routing_mode      = "device"      # "device" | "external"
        self.known_interfaces: list = known_interfaces or []
        self.project_context:  dict = project_context or {}

        # ── data buckets (populated step-by-step or by preset) ──
        self.identity_data: Dict[str, str]  = {}
        self.vlans:         List[Dict]      = []
        self.routing_entries: List[Dict]    = []
        self.dhcp_pools:    List[Dict]      = []
        self.acl_rules:     List[Dict]      = []
        self.uplinks:       List[Dict]      = []
        self.router_interface: str          = ""
        self.wan_interface: str              = ""
        self.wan_ip: str                    = ""
        self.wan_mask: str                  = "255.255.255.252"
        self.static_routes: List[Dict]      = []
        self.rip_networks:  List[Dict]      = []
        self.enable_rip:    bool            = False
        self.summary_box:   Optional[QTextEdit] = None
        self.connected_links: List[Dict] = connected_links or []

        # ── per-step UI state (reset on each render) ──
        self.vlan_row_entries:    List = []
        self.routing_row_entries: List = []
        self.dhcp_check_vars:     List = []
        self.acl_scenario_vars:   List = []
        self.extra_route_rows:    List = []

        self.current_step = 0
        self.steps: List[Step] = []

        if not headless:
            self._prompt_routing_mode()
            self._build_steps()
            self._build_layout()
        self._render_step()

    def _find_link_to(self, *roles: str) -> Optional[Dict]:
        """Return the first connected_links entry whose remote_role is one of *roles*."""
        for link in self.connected_links:
            if link.get("remote_role") in roles:
                return link
        return None

    def _show_suggestion_banner(self, parent, text: str) -> QLabel:
        """Create a themed suggestion banner with a green left-border."""
        t = self.THEME
        lbl = QLabel(f"\U0001f517 {text}", parent)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"background-color: {t['card']}; color: #3FB950; "
            f"border-left: 3px solid #3FB950; "
            f"padding: 6px 10px; border-radius: 4px; font-size: 11px;"
        )
        return lbl

    def _apply_dark_theme(self):
        t = self.THEME
        self.setStyleSheet(f"""
            QDialog {{ background-color: {t['bg']}; }}
            QDialog, QWidget, QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget, QComboBox, QCheckBox, QSpinBox, QRadioButton {{
                font-family: "Segoe UI";
            }}
            QWidget {{ color: {t['text']}; }}
            QLabel {{ color: {t['text']}; }}
            QPushButton {{ background-color: {t['accent']}; color: white; border: none; border-radius: 8px; padding: 8px 16px; }}
            QPushButton:hover {{ background-color: #79b8ff; }}
            QPushButton:disabled {{ background-color: {t['border']}; color: {t['muted']}; }}
            QLineEdit {{
                background-color: {t['input']};
                color: {t['text']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 8px 10px;
                min-height: 18px;
                selection-background-color: #1f6feb;
            }}
            QLineEdit:focus {{
                border: 1px solid {t['accent']};
                background-color: #111c2c;
            }}
            QTextEdit {{ background-color: {t['sidebar']}; color: {t['text']}; border: 1px solid {t['border']}; font-family: Consolas; }}
            QListWidget {{ background-color: {t['bg']}; color: {t['text']}; border: none; outline: 0; }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 6px; margin: 2px 0; }}
            QListWidget::item:selected {{ background-color: {t['accent']}; color: white; }}
            QProgressBar {{ background: {t['sidebar']}; border: 1px solid {t['border']}; border-radius: 5px; height: 10px; text-align: left; }}
            QProgressBar::chunk {{ background: {t['accent']}; }}
            QScrollArea {{ background: transparent; border: none; }}
            QComboBox {{ background-color: {t['input']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 6px; }}
            QComboBox:focus {{ border: 1px solid {t['accent']}; }}
            QCheckBox {{ color: {t['text']}; }}
            QSpinBox {{ background-color: {t['input']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 4px; }}
            QRadioButton {{ color: {t['text']}; }}
        """)

    # ════════════════════════ routing mode dialog ══════════════════════════════
    def _prompt_routing_mode(self):
        if self.device_role == "access":
            self.routing_mode = "external"
            return

        t = self.THEME

        # ── Check for routing ownership conflict ──────────────────────────────
        ctx = self.project_context
        routing_owner      = ctx.get("routing_device", "")
        routing_owner_type = ctx.get("routing_device_type", "")

        routing_locked = False
        lock_reason    = ""
        if routing_owner:
            if self.device_role == "router" and routing_owner_type == "core":
                routing_locked = True
                lock_reason = (
                    f"Core switch \"{routing_owner}\" is already configured as the "
                    f"routing device for this project.\n\n"
                    f"This router will be set to 'external routing' mode — only "
                    f"identity and basic settings will be configured here."
                )
            elif self.device_role == "core" and routing_owner_type == "router":
                routing_locked = True
                lock_reason = (
                    f"Router \"{routing_owner}\" is already configured as the "
                    f"routing device for this project.\n\n"
                    f"This core switch will be set to Layer-2-only mode — VLANs and "
                    f"port assignments only; no SVI gateways."
                )

        if routing_locked:
            self.routing_mode = "external"
            QMessageBox.information(self, "Routing already assigned", lock_reason)
            return

        if self.headless:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Network setup")
        dlg.setFixedSize(500, 320)
        dlg.setStyleSheet(f"background-color: {t['bg']}; color: {t['text']};")
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 18)

        hdr = QLabel("How is your network set up?")
        hdr.setStyleSheet(f"font-weight: bold; font-size: 13px;")
        layout.addWidget(hdr)
        layout.addWidget(QLabel("Choose the option that matches your topology."))

        if self.device_role == "router":
            opts = [
                ("device",   "This router routes traffic between VLANs",
                             "Subinterfaces, DHCP and ACLs will be configured here."),
                ("external", "A separate device handles routing",
                             "Only identity and basic settings will be configured."),
            ]
        else:
            opts = [
                ("device",   "This core switch handles routing (Layer 3)",
                             "SVI gateways will be created for each VLAN."),
                ("external", "A separate router does the routing (Layer 2 only)",
                             "Only VLANs and port assignments will be configured."),
            ]

        radios = []
        for val, title, sub in opts:
            rb = QRadioButton(title)
            rb.setProperty("value", val)
            if val == "device":
                rb.setChecked(True)
            radios.append(rb)
            layout.addWidget(rb)
            layout.addWidget(QLabel(f"    {sub}"))

        def confirm():
            for rb in radios:
                if rb.isChecked():
                    self.routing_mode = rb.property("value")
                    break
            dlg.accept()

        btn = QPushButton("Continue")
        btn.clicked.connect(confirm)
        layout.addWidget(btn)
        dlg.exec()

    # ════════════════════════ help popup ══════════════════════════════════════
    def _show_help(self, term: str):
        text = HELP_TEXT.get(term, f"No help available for '{term}'.")
        QMessageBox.information(self, f"Help: {term}", text)

    # ════════════════════════ suggestion banner ═══════════════════════════════
    def _show_suggestion_banner(self, parent: QWidget, message: str, on_accept=None) -> QFrame:
        t = self.THEME
        strip = QFrame(parent)
        strip.setObjectName("suggestionBanner")
        strip.setStyleSheet("QFrame#suggestionBanner { background-color: #1a3a5c; border-radius: 8px; padding: 6px; }")
        strip_layout = QHBoxLayout(strip)

        lbl = QLabel("Tip: " + message)
        lbl.setStyleSheet(f"color: #90c8f8;")
        lbl.setWordWrap(True)
        strip_layout.addWidget(lbl, 1)

        def dismiss():
            strip.deleteLater()

        if on_accept:
            use_btn = QPushButton("Use")
            use_btn.clicked.connect(lambda: (on_accept(), dismiss()))
            strip_layout.addWidget(use_btn)
        close_btn = QPushButton("X")
        close_btn.setStyleSheet(f"background: transparent; color: {t['muted']};")
        close_btn.clicked.connect(dismiss)
        strip_layout.addWidget(close_btn)
        return strip

    # ════════════════════════ preset helpers ══════════════════════════════════
    def _auto_dhcp_from_routing(self, dns: str = "8.8.8.8") -> List[Dict]:
        pools = []
        for e in self.routing_entries:
            gw   = e.get("ip", "")
            mask = e.get("mask", "255.255.255.0")
            vid  = e.get("vlan", "")
            name = e.get("name", f"VLAN{vid}")
            if not gw:
                continue
            p = gw.split(".")
            if len(p) != 4:
                continue
            prefix = f"{p[0]}.{p[1]}.{p[2]}"
            pools.append({
                "pool":    name,
                "network": f"{prefix}.0",
                "mask":    mask,
                "gateway": gw,
                "dns":     dns,
                "start":   f"{prefix}.50",
                "end":     f"{prefix}.200",
            })
        return pools

    def _auto_routing_from_vlans(self, scheme: str = "192.168") -> List[Dict]:
        return [
            {
                "vlan": v.get("id", "10"),
                "name": v.get("name", f"VLAN{v.get('id','10')}"),
                "ip":   f"{scheme}.{v.get('id','10')}.1",
                "mask": "255.255.255.0",
            }
            for v in self.vlans
        ]

    def _apply_preset(self, key: str):
        dn = self.device_name

        if self.device_role == "access":
            a_ports  = "Ethernet0/0-3"
            a_uplink = "Ethernet3/3"
        else:
            a_ports  = "FastEthernet1/1-10"
            a_uplink = "FastEthernet1/0"

        if key == "small_office":
            self.identity_data = {"hostname": dn, "domain": "office.local", "enable": "Secret123!"}
            if self.device_role in ("core", "access"):
                self.vlans = [
                    {"id": "10", "name": "Staff",
                     "ports": "Ethernet0/0-2" if self.device_role == "access" else ""},
                    {"id": "20", "name": "Guest",
                     "ports": "Ethernet1/0-1" if self.device_role == "access" else ""},
                ]
            if self.device_role == "router":
                _link = self._find_link_to("core", "access")
                self.router_interface = _link["local_interface"] if _link else (
                    self.known_interfaces[0] if self.known_interfaces else "FastEthernet0/0")
                # WAN interface — pick the second known interface or use a default
                wan_candidates = [i for i in self.known_interfaces if i != self.router_interface]
                self.wan_interface = wan_candidates[0] if wan_candidates else "FastEthernet0/1"
                self.wan_ip = "10.0.0.2"
                self.wan_mask = "255.255.255.252"
                self.routing_entries = [
                    {"vlan": "10", "name": "Staff", "ip": "192.168.10.1", "mask": "255.255.255.0"},
                    {"vlan": "20", "name": "Guest", "ip": "192.168.20.1", "mask": "255.255.255.0"},
                ]
                self.dhcp_pools   = self._auto_dhcp_from_routing()
                self.static_routes = [{"network": "0.0.0.0", "mask": "0.0.0.0",
                                        "next-hop": "10.0.0.1", "description": "Default route to ISP"}]
                self.acl_rules = [
                    {"acl #": "101", "action": "deny",   "source": "192.168.20.0",
                     "wildcard": "0.0.0.255", "destination": "192.168.10.0",
                     "destination_wildcard": "0.0.0.255",
                     "remark": "Block Guest from reaching Staff"},
                    {"acl #": "101", "action": "permit", "source": "any",
                     "wildcard": "",           "remark": "Permit all other"},
                ]
            elif self.device_role == "core" and self.routing_mode == "device":
                self.routing_entries = self._auto_routing_from_vlans()
                self.acl_rules = [
                    {"acl #": "10", "action": "permit", "source": "192.168.10.0",
                     "wildcard": "0.0.0.255", "remark": "Allow Staff"},
                ]
            if self.device_role == "core":
                # Core switch needs trunk uplinks to router and access switches
                trunk_ports = []
                for link in (self.connected_links or []):
                    trunk_ports.append(link["local_interface"])
                if not trunk_ports:
                    trunk_ports = ["FastEthernet1/0", "FastEthernet1/1"]
                self.uplinks = [{"ports": ", ".join(trunk_ports), "mode": "trunk", "allowed vlans": "all"}]
            if self.device_role == "access":
                _link = self._find_link_to("core", "router")
                a_uplink_port = _link["local_interface"] if _link else a_uplink
                self.uplinks = [{"ports": a_uplink_port, "mode": "trunk", "allowed vlans": "all"}]

        elif key == "school_lab":
            self.identity_data = {"hostname": dn, "domain": "school.edu", "enable": "EduPass456!"}
            if self.device_role in ("core", "access"):
                self.vlans = [
                    {"id": "10", "name": "Students",
                     "ports": "Ethernet0/0-2" if self.device_role == "access" else ""},
                    {"id": "20", "name": "Teachers",
                     "ports": "Ethernet1/0-1" if self.device_role == "access" else ""},
                    {"id": "30", "name": "Servers",
                     "ports": "Ethernet2/0"   if self.device_role == "access" else ""},
                ]
            if self.device_role == "router":
                _link = self._find_link_to("core", "access")
                self.router_interface = _link["local_interface"] if _link else (
                    self.known_interfaces[0] if self.known_interfaces else "FastEthernet0/0")
                wan_candidates = [i for i in self.known_interfaces if i != self.router_interface]
                self.wan_interface = wan_candidates[0] if wan_candidates else "FastEthernet0/1"
                self.wan_ip = "10.0.0.2"
                self.wan_mask = "255.255.255.252"
                self.routing_entries = [
                    {"vlan": "10", "name": "Students", "ip": "192.168.10.1", "mask": "255.255.255.0"},
                    {"vlan": "20", "name": "Teachers", "ip": "192.168.20.1", "mask": "255.255.255.0"},
                    {"vlan": "30", "name": "Servers",  "ip": "192.168.30.1", "mask": "255.255.255.0"},
                ]
                self.dhcp_pools   = self._auto_dhcp_from_routing()
                self.static_routes = [{"network": "0.0.0.0", "mask": "0.0.0.0",
                                        "next-hop": "10.0.0.1", "description": "Default route to ISP"}]
                self.acl_rules = [
                    {"acl #": "101", "action": "deny",   "source": "192.168.10.0",
                     "wildcard": "0.0.0.255", "destination": "192.168.30.0",
                     "destination_wildcard": "0.0.0.255",
                     "remark": "Block Students from Servers"},
                    {"acl #": "101", "action": "permit", "source": "any",
                     "wildcard": "",           "remark": "Permit all other"},
                ]
            elif self.device_role == "core" and self.routing_mode == "device":
                self.routing_entries = self._auto_routing_from_vlans()
                self.acl_rules = [
                    {"acl #": "10", "action": "permit", "source": "192.168.20.0",
                     "wildcard": "0.0.0.255", "remark": "Allow Teachers"},
                ]
            if self.device_role == "core":
                trunk_ports = []
                for link in (self.connected_links or []):
                    trunk_ports.append(link["local_interface"])
                if not trunk_ports:
                    trunk_ports = ["FastEthernet1/0", "FastEthernet1/1"]
                self.uplinks = [{"ports": ", ".join(trunk_ports), "mode": "trunk", "allowed vlans": "all"}]
            if self.device_role == "access":
                _link = self._find_link_to("core", "router")
                a_uplink_port = _link["local_interface"] if _link else a_uplink
                self.uplinks = [{"ports": a_uplink_port, "mode": "trunk", "allowed vlans": "all"}]

        else:  # minimal
            self.identity_data = {"hostname": dn, "domain": "", "enable": "ChangeMe123!"}
            if self.device_role in ("core", "access"):
                self.vlans = [{"id": "10", "name": "Default",
                               "ports": a_ports if self.device_role == "access" else ""}]
            if self.device_role == "router":
                _link = self._find_link_to("core", "access")
                self.router_interface = _link["local_interface"] if _link else (
                    self.known_interfaces[0] if self.known_interfaces else "FastEthernet0/0")
                wan_candidates = [i for i in self.known_interfaces if i != self.router_interface]
                self.wan_interface = wan_candidates[0] if wan_candidates else "FastEthernet0/1"
                self.wan_ip = "10.0.0.2"
                self.wan_mask = "255.255.255.252"
                self.routing_entries  = [{"vlan": "10", "name": "Default",
                                           "ip": "192.168.10.1", "mask": "255.255.255.0"}]
                self.dhcp_pools = self._auto_dhcp_from_routing()
            elif self.device_role == "core" and self.routing_mode == "device":
                self.routing_entries = self._auto_routing_from_vlans()
            if self.device_role == "core":
                trunk_ports = []
                for link in (self.connected_links or []):
                    trunk_ports.append(link["local_interface"])
                if not trunk_ports:
                    trunk_ports = ["FastEthernet1/0", "FastEthernet1/1"]
                self.uplinks = [{"ports": ", ".join(trunk_ports), "mode": "trunk", "allowed vlans": "all"}]
            if self.device_role == "access":
                _link = self._find_link_to("core", "router")
                a_uplink_port = _link["local_interface"] if _link else a_uplink
                self.uplinks = [{"ports": a_uplink_port, "mode": "trunk", "allowed vlans": "all"}]

    def _quick_generate(self, key: str):
        self._apply_preset(key)
        if not self.identity_data.get("hostname"):
            self.identity_data["hostname"] = self.device_name
        if not self.identity_data.get("enable"):
            self.identity_data["enable"] = "ChangeMe123!"
        self._write_templates()
        self.accept()

    def _apply_preset_and_next(self, key: str):
        self._apply_preset(key)
        self.current_step = 1
        self._render_step()

    def destroy(self):
        """Compatibility: close the dialog."""
        self.close()

    # ════════════════════════ layout ══════════════════════════════════════════
    def _build_layout(self):
        t = self.THEME
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(12)

        shell = QFrame()
        shell.setObjectName("wizardShell")
        shell.setStyleSheet(
            f"QFrame#wizardShell {{ background-color: #0F1520; border: 1px solid {t['border']}; border-radius: 14px; }}"
        )
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(12, 12, 12, 12)
        shell_layout.setSpacing(12)

        # ── sidebar ──
        sidebar = QFrame()
        sidebar.setMinimumWidth(250)
        sidebar.setMaximumWidth(290)
        sidebar.setObjectName("wizardSidebar")
        sidebar.setStyleSheet(
            f"QFrame#wizardSidebar {{ background-color: {t['sidebar']}; border: 1px solid {t['border']}; border-radius: 10px; }}"
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 14, 14, 12)
        sidebar_layout.setSpacing(10)

        sidebar_layout.addWidget(QLabel("Guided Setup"))
        role_labels = {"router": "Router / Gateway", "core": "Core Switch (L3)", "access": "Access Switch (L2)"}
        routing_note = "routes here" if self.routing_mode == "device" else "routing external"
        info = QLabel(f"{self.device_name}\n{role_labels.get(self.device_role,'')}\n{routing_note}")
        info.setStyleSheet(f"color: {t['accent']}; font-size: 10pt;")
        sidebar_layout.addWidget(info)

        self.listbox = QListWidget()
        self.listbox.setStyleSheet(f"background: {t['bg']}; color: {t['text']}; border: none;")
        for step in self.steps:
            self.listbox.addItem(f"  {step.title}")
        self.listbox.setCurrentRow(0)
        sidebar_layout.addWidget(self.listbox, 1)

        shell_layout.addWidget(sidebar)

        # ── right side: content + nav ──
        right = QFrame()
        right.setObjectName("wizardRightPane")
        right.setStyleSheet(
            f"QFrame#wizardRightPane {{ background-color: {t['card']}; border: 1px solid {t['border']}; border-radius: 10px; }}"
        )
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(12)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {t['card']};")
        self.stack_pages = []
        for step in self.steps:
            page = QWidget()
            page.setStyleSheet(f"background-color: {t['card']};")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            self.stack_pages.append(page)
            self.stack.addWidget(page)
        right_layout.addWidget(self.stack, 1)

        # ── nav bar ──
        nav = QWidget()
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(0, 2, 0, 0)
        nav_layout.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(280)
        nav_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {t['muted']}; font-size: 10pt;")
        nav_layout.addWidget(self.lbl_status)

        nav_layout.addStretch()
        self.btn_back = QPushButton("Back")
        self.btn_back.setProperty("secondary", True)
        self.btn_back.setStyleSheet(f"background-color: {t['sidebar']}; color: {t['text']}; border: 1px solid {t['border']};")
        self.btn_back.clicked.connect(self.prev_step)
        self.btn_back.setEnabled(False)
        nav_layout.addWidget(self.btn_back)

        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self.next_step)
        nav_layout.addWidget(self.btn_next)

        right_layout.addWidget(nav)
        shell_layout.addWidget(right, 1)
        main_layout.addWidget(shell, 1)

    # ════════════════════════ step list ════════════════════════════════════════
    def _build_steps(self):
        self.steps = [
            Step("Welcome",     "One-click presets or customise every step — your choice.",
                 GuidedSetupWizard._build_step_welcome, lambda self: True),
            Step("Name & Lock", "Device name and admin password.",
                 GuidedSetupWizard._build_step_identity, GuidedSetupWizard._validate_identity),
        ]

        if self.device_role in ("core", "access"):
            self.steps.append(Step(
                "VLANs",
                "How many VLANs? Ports are assigned automatically.",
                GuidedSetupWizard._build_step_vlans,
                GuidedSetupWizard._validate_vlans,
            ))

        if self.device_role == "router":
            if self.routing_mode == "device":
                self.steps += [
                    Step("Subinterfaces",
                         "Choose the interface and IP scheme — gateways auto-fill.",
                         GuidedSetupWizard._build_step_router_subinterfaces,
                         GuidedSetupWizard._validate_router_subinterfaces),
                    Step("Default Route",
                         "One checkbox to add internet access.",
                         GuidedSetupWizard._build_step_static_routes,
                         GuidedSetupWizard._validate_static_routes),
                    Step("RIPv2",
                         "Enable automatic route sharing with neighbouring routers.",
                         GuidedSetupWizard._build_step_rip,
                         GuidedSetupWizard._validate_rip),
                    Step("DHCP",
                         "Auto-IP for each network — just tick which VLANs need it.",
                         GuidedSetupWizard._build_step_dhcp,
                         GuidedSetupWizard._validate_dhcp),
                ]
            self.steps.append(Step(
                "Access Rules",
                "Scenario checkboxes — no ACL syntax needed.",
                GuidedSetupWizard._build_step_acl,
                GuidedSetupWizard._validate_acl,
            ))

        elif self.device_role == "core":
            if self.routing_mode == "device":
                self.steps.append(Step(
                    "Gateways",
                    "Enter an IP scheme — SVI gateways auto-fill for each VLAN.",
                    GuidedSetupWizard._build_step_routing,
                    GuidedSetupWizard._validate_routing,
                ))
            self.steps.append(Step(
                "Access Rules",
                "Scenario checkboxes — no ACL syntax needed.",
                GuidedSetupWizard._build_step_acl,
                GuidedSetupWizard._validate_acl,
            ))

        else:
            self.steps += [
                Step("Uplink",
                     "Which port connects to the upstream device?",
                     GuidedSetupWizard._build_step_uplinks,
                     GuidedSetupWizard._validate_uplinks),
                Step("Access Rules (optional)",
                     "Lightweight per-switch filtering.",
                     GuidedSetupWizard._build_step_acl_access,
                     GuidedSetupWizard._validate_acl),
            ]

        self.steps.append(Step(
            "Summary & Save",
            "Review the complete configuration and save it.",
            GuidedSetupWizard._build_step_summary,
            GuidedSetupWizard._validate_summary,
        ))

    # ════════════════════════ step render / navigation ═════════════════════════
    def _render_step(self):
        if not hasattr(self, "stack"):
            return
        t = self.THEME
        step = self.steps[self.current_step]
        self.listbox.setCurrentRow(self.current_step)
        self.stack.setCurrentIndex(self.current_step)

        page = self.stack_pages[self.current_step]
        # Clear and rebuild page content
        old_layout = page.layout()

        def _clear_layout(layout):
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
                elif child.layout():
                    _clear_layout(child.layout())

        if old_layout:
            _clear_layout(old_layout)

        layout = old_layout if old_layout else QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        hdr = QLabel(step.title)
        hdr.setStyleSheet(f"font-size: 16pt; font-weight: bold; color: {t['text']};")
        layout.addWidget(hdr)
        desc = QLabel(step.description)
        desc.setStyleSheet(f"color: {t['muted']};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {t['border']};")
        layout.addWidget(sep)

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.NoFrame)
        body.setStyleSheet("background: transparent; border: none;")
        body_widget = QWidget()
        body_outer_layout = QVBoxLayout(body_widget)
        body_outer_layout.setContentsMargins(0, 8, 0, 8)

        # Keep a wide, readable column so content doesn't collapse into a narrow strip.
        content_row = QWidget()
        row_layout = QHBoxLayout(content_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addStretch()

        content_col = QWidget()
        content_col.setMinimumWidth(700)
        content_col.setMaximumWidth(980)
        col_layout = QVBoxLayout(content_col)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(10)
        step.build_ui(self, content_col)

        row_layout.addWidget(content_col, 1)
        row_layout.addStretch()
        body_outer_layout.addWidget(content_row)
        body_outer_layout.addStretch()
        body.setWidget(body_widget)
        layout.addWidget(body, 1)

        self._update_nav()

    def _update_nav(self):
        n = len(self.steps)
        self.btn_back.setEnabled(self.current_step > 0)
        if self.current_step == n - 1:
            self.btn_next.setText("Finish")
        else:
            self.btn_next.setText("Next")
        self.lbl_status.setText(f"Step {self.current_step + 1} of {n}")
        self.progress_bar.setValue(int((self.current_step + 1) / n * 100))

    def next_step(self):
        if not self.steps[self.current_step].validate(self):
            return
        if self.current_step == len(self.steps) - 1:
            self._write_templates()
            self.accept()
            return
        self.current_step += 1
        self._render_step()

    def prev_step(self):
        if self.current_step == 0:
            return
        self.current_step -= 1
        self._render_step()

    # ════════════════════════ UI building helpers ══════════════════════════════
    def _help_link(self, parent: QWidget, term: str) -> QLabel:
        t = self.THEME
        lbl = QLabel(f"?  What is {term}?")
        lbl.setStyleSheet(f"color: {t['accent']}; text-decoration: underline;")
        lbl.setCursor(Qt.PointingHandCursor)
        lbl.mousePressEvent = lambda e: self._show_help(term)
        return lbl

    def _entry(self, parent: QWidget, value: str = "", width: int = 20) -> QLineEdit:
        e = QLineEdit()
        e.setText(value)
        e.setMinimumWidth(width * 8)
        e.setMinimumHeight(34)
        e.setClearButtonEnabled(True)
        return e

    def _lbl(self, parent: QWidget, text: str, muted: bool = False, bold: bool = False) -> QLabel:
        t = self.THEME
        lbl = QLabel(text)
        color = t["muted"] if muted else t["text"]
        style = f"color: {color};"
        if bold:
            style += " font-weight: bold;"
        lbl.setStyleSheet(style)
        return lbl

    def _section_hdr(self, parent: QWidget, cols: list) -> QFrame:
        t = self.THEME
        hdr = QFrame()
        hdr.setObjectName("sectionHeader")
        hdr.setStyleSheet(f"QFrame#sectionHeader {{ background-color: {t['border']}; border-radius: 6px; }}")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(8, 4, 8, 4)
        hdr_layout.setSpacing(8)
        for label, w in cols:
            l = QLabel(label)
            l.setStyleSheet(f"color: {t['muted']}; font-weight: bold;")
            l.setMinimumWidth(w * 8)
            hdr_layout.addWidget(l)
        return hdr

    def _row_box(self, parent: QWidget, alt: bool = False, padding: int = 6) -> QFrame:
        t = self.THEME
        f = QFrame(parent)
        f.setObjectName("rowBox")
        bg = t['row_alt'] if alt else t['card']
        f.setStyleSheet(
            f"QFrame#rowBox {{ background-color: {bg}; border: 1px solid {t['border']}; border-radius: 8px; padding: {padding}px; }}"
        )
        return f

    def _card(self, parent: QWidget, padx: int = 10, pady: int = 8) -> QFrame:
        t = self.THEME
        f = QFrame()
        f.setObjectName("wizardCard")
        f.setStyleSheet(
            f"QFrame#wizardCard {{ background-color: {t['sidebar']}; border: 1px solid {t['border']}; "
            f"border-radius: 10px; padding: {pady}px {padx}px; }}"
        )
        return f

    def _form_row(self, label: str, widget: QWidget, help_term: str | None = None) -> QWidget:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {self.THEME['text']}; font-weight: 600;")
        lbl.setMinimumWidth(210)
        rl.addWidget(lbl)
        rl.addWidget(widget, 1)
        if help_term:
            rl.addWidget(self._help_link(row, help_term))
        return row

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Welcome
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_welcome(self, body):
        t = self.THEME
        layout = body.layout() or QVBoxLayout(body)
        layout.setSpacing(10)

        if self.device_role == "router":
            blurb = (
                "This wizard configures subinterfaces, DHCP, a default internet route "
                "and access rules — everything the router needs to run your network.\n\n"
                "Pick a preset for a one-click complete config, or click Next to "
                "customise each step yourself."
            )
        elif self.device_role == "core":
            blurb = (
                "This wizard creates VLANs, assigns ports and sets up SVI gateways.\n"
                "Enter an IP scheme once and all gateways are auto-filled.\n\n"
                "Note: DHCP is handled by the router — run the router wizard separately."
            )
        else:
            blurb = (
                "This wizard groups ports into VLANs and configures the uplink trunk.\n"
                "Ports are auto-assigned — just confirm the VLAN names and uplink port."
            )

        layout.addWidget(self._lbl(body, blurb, muted=True))

        ctx = self.project_context
        if ctx.get("vlans") or ctx.get("routing_entries") or ctx.get("rip_enabled"):
            parts = []
            src = ctx.get("routing_source") or ctx.get("vlan_source") or "another device"
            if ctx.get("vlans"):
                vnames = ", ".join(f"{v['name']} {v['id']}" for v in ctx["vlans"][:3])
                extra  = f" +{len(ctx['vlans'])-3} more" if len(ctx["vlans"]) > 3 else ""
                parts.append(f"{len(ctx['vlans'])} VLANs ({vnames}{extra})")
            if ctx.get("dhcp_pools"):
                parts.append("DHCP")
            if ctx.get("rip_enabled"):
                parts.append("RIP")
            if ctx.get("routing_entries"):
                parts.append(f"{len(ctx['routing_entries'])} SVI/subinterfaces")
            summary = ", ".join(parts)
            layout.addWidget(self._show_suggestion_banner(
                body,
                f"Already configured in this project — {src}: {summary}. "
                "Smart suggestions will appear as you proceed.",
            ))

        layout.addWidget(self._lbl(body, "One-click presets:", bold=True))

        for key, (name, desc) in PRESET_CATALOGUE.items():
            card = QFrame()
            card.setObjectName("presetCard")
            card.setStyleSheet(
                f"QFrame#presetCard {{ background-color: {t['sidebar']}; border: 1px solid {t['border']}; "
                "border-radius: 10px; }}"
            )
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(10)
            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(4)
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-weight: 700; font-size: 11pt;")
            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet(f"color: {t['muted']};")
            left_layout.addWidget(name_lbl)
            left_layout.addWidget(desc_lbl)
            card_layout.addWidget(left, 1)
            gen_btn = QPushButton("Generate Now")
            gen_btn.clicked.connect(lambda checked, k=key: self._quick_generate(k))
            card_layout.addWidget(gen_btn)
            cust_btn = QPushButton("Customize")
            cust_btn.setStyleSheet(f"background-color: {t['card']}; color: {t['text']}; border: 1px solid {t['border']};")
            cust_btn.clicked.connect(lambda checked, k=key: self._apply_preset_and_next(k))
            card_layout.addWidget(cust_btn)
            layout.addWidget(card)

        layout.addWidget(self._lbl(body, "\nOr click Next to start from scratch.", muted=True))

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Name & Lock
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_identity(self, body):
        ctx = self.project_context
        layout = body.layout() or QVBoxLayout(body)
        layout.setSpacing(12)

        current_domain = self.identity_data.get("domain", "") or ctx.get("domain", "")
        self._hn_edit  = self._entry(body, self.identity_data.get("hostname", self.device_name), 30)
        self._hn_edit.setPlaceholderText("e.g. R1-Core or Branch-Router")
        self._dom_edit = self._entry(body, current_domain, 30)
        self._dom_edit.setPlaceholderText("e.g. company.local")
        self._pw_edit  = self._entry(body, self.identity_data.get("enable", ""), 30)
        self._pw_edit.setEchoMode(QLineEdit.Password)
        self._pw_edit.setPlaceholderText("Strong admin password")

        ctx_pw = ctx.get("enable_pw", "")
        if ctx_pw and not self._pw_edit.text():
            def _use_pw():
                self._pw_edit.setText(ctx_pw)
            src = ctx.get("routing_source") or ctx.get("vlan_source") or "another device"
            layout.addWidget(self._show_suggestion_banner(
                body,
                f"Other devices use enable password from {src} — use the same for consistency?",
                on_accept=_use_pw,
            ))

        card = self._card(body, padx=12, pady=10)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(10)
        cl.addWidget(self._form_row("Device hostname  *", self._hn_edit))
        cl.addWidget(self._form_row("Domain name  (optional)", self._dom_edit))
        cl.addWidget(self._form_row("Admin (enable) password  *", self._pw_edit, "Enable secret"))
        layout.addWidget(card)
        layout.addWidget(self._lbl(body, "\n* Required", muted=True))

    def _validate_identity(self) -> bool:
        hn = self._hn_edit.text().strip()
        pw = self._pw_edit.text().strip()
        if not hn:
            QMessageBox.critical(self, "Required", "Enter a device name.")
            return False
        if not pw:
            QMessageBox.critical(self, "Required", "Enter an admin password.")
            return False
        self.identity_data = {
            "hostname": hn,
            "domain":   self._dom_edit.text().strip(),
            "enable":   pw,
        }
        return True

    def _build_step_vlans(self, body):
        t = self.THEME
        ctx = self.project_context
        layout = body.layout() or QVBoxLayout(body)
        layout.setSpacing(10)
        if ctx.get("vlans") and not self.vlans:
            def _use_ctx_vlans():
                self.vlans = [{"id": v["id"], "name": v["name"], "ports": ""} for v in ctx["vlans"]]
                self.vlan_count_spin.setValue(len(self.vlans))
            src = ctx.get("vlan_source") or ctx.get("routing_source") or "another device"
            vnames = ", ".join(f"{v['name']} {v['id']}" for v in ctx["vlans"][:3])
            layout.addWidget(self._show_suggestion_banner(body,
                f"Found {len(ctx['vlans'])} VLANs from {src} ({vnames}). Port assignments will be auto-set.",
                on_accept=_use_ctx_vlans))
            self.vlans = [{"id": v["id"], "name": v["name"], "ports": ""} for v in ctx["vlans"]]
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self._help_link(body, "VLAN"))
        layout.addWidget(top)
        cnt_f = QWidget()
        cnt_layout = QHBoxLayout(cnt_f)
        cnt_layout.setContentsMargins(0, 0, 0, 0)
        cnt_layout.setSpacing(10)
        cnt_layout.addWidget(self._lbl(body, "How many VLANs do you need?"))
        self.vlan_count_spin = QSpinBox()
        self.vlan_count_spin.setRange(1, 12)
        self.vlan_count_spin.setValue(max(2, len(self.vlans)))
        cnt_layout.addWidget(self.vlan_count_spin)
        cnt_layout.addWidget(self._lbl(body, "(ports are auto-assigned)", muted=True))
        layout.addWidget(cnt_f)
        has_picker = bool(self.known_interfaces) and self.device_role in ("access", "core")
        cols = [("VLAN ID", 9), ("Name", 22)]
        cols.append(("Assign Ports (optional)", 34) if has_picker else ("Ports (e.g. Et0/0-3)", 30))
        layout.addWidget(self._section_hdr(body, cols))
        self.vlan_rows_widget = QWidget()
        self.vlan_rows_layout = QVBoxLayout(self.vlan_rows_widget)
        layout.addWidget(self.vlan_rows_widget, 1)

        def _btn_label(val: str) -> str:
            if not val or val == "auto":
                return "Auto-assign"
            parts = val.split(",")
            return f"{parts[0]}, +{len(parts)-1} more" if len(parts) > 2 else f"{val}"

        def _open_port_picker(ports_edit, btn, row_idx):
            popup = QDialog(self)
            popup.setWindowTitle("Select ports")
            popup.setStyleSheet(f"background-color: {t['sidebar']};")
            popup.setFixedSize(320, 280)
            pl = QVBoxLayout(popup)
            pl.addWidget(QLabel("Tick the ports for this VLAN:"))
            already_used = set()
            for j, (_, _, pe) in enumerate(self.vlan_row_entries):
                if j != row_idx:
                    for p in pe.text().replace(",", " ").split():
                        already_used.add(p.strip())
            current = set(pe.text().replace(",", " ").split()) if row_idx < len(self.vlan_row_entries) else set()
            check_vars = {}
            for iface in self.known_interfaces:
                cb = QCheckBox(iface)
                cb.setChecked(iface in current)
                if iface in already_used and iface not in current:
                    cb.setEnabled(False)
                    cb.setText(iface + "  (used)")
                check_vars[iface] = cb
                pl.addWidget(cb)

            def _apply():
                selected = [iface for iface, v in check_vars.items() if v.isChecked()]
                ports_edit.setText(",".join(selected) if selected else "auto")
                btn.setText(_btn_label(ports_edit.text()))
                popup.accept()
            apply_btn = QPushButton("Apply")
            apply_btn.clicked.connect(_apply)
            pl.addWidget(apply_btn)
            popup.exec()

        def rebuild():
            while self.vlan_rows_layout.count():
                child = self.vlan_rows_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.vlan_row_entries.clear()
            for i in range(self.vlan_count_spin.value()):
                ex = self.vlans[i] if i < len(self.vlans) else {}
                vid = ex.get("id", str((i + 1) * 10))
                vname = ex.get("name", f"VLAN{vid}")
                vport = ex.get("ports", self._auto_ports(i))
                rf = self._row_box(self.vlan_rows_widget, alt=bool(i % 2), padding=6)
                rfl = QHBoxLayout(rf)
                rfl.setContentsMargins(8, 6, 8, 6)
                rfl.setSpacing(8)
                id_edit = self._entry(rf, vid, 9)
                name_edit = self._entry(rf, vname, 22)
                ports_edit = self._entry(rf, vport, 30)
                rfl.addWidget(id_edit)
                rfl.addWidget(name_edit)
                if has_picker:
                    btn = QPushButton(_btn_label(vport))
                    btn.setStyleSheet(f"background-color: {t['sidebar']}; color: {t['text']};")
                    btn.clicked.connect(lambda c, pe=ports_edit, b=btn, idx=i: _open_port_picker(pe, b, idx))
                    rfl.addWidget(btn)
                else:
                    rfl.addWidget(ports_edit)
                self.vlan_row_entries.append((id_edit, name_edit, ports_edit))
                self.vlan_rows_layout.addWidget(rf)
        self.vlan_count_spin.valueChanged.connect(rebuild)
        rebuild()

    def _auto_ports(self, idx: int) -> str:
        if self.known_interfaces:
            total = len(self.known_interfaces)
            n_vlans = max(1, self.vlan_count_spin.value())
            per_vlan = max(1, total // n_vlans)
            start_i = idx * per_vlan
            end_i = min(start_i + per_vlan - 1, total - 1)
            first, last = self.known_interfaces[start_i], self.known_interfaces[end_i]
            if first == last:
                return first
            return f"{first.rsplit('/', 1)[0]}/{first.rsplit('/', 1)[1]}-{last.rsplit('/', 1)[1]}"
        return f"Ethernet{idx}/0-3" if self.device_role == "access" else f"FastEthernet1/{idx*4+1}-{idx*4+4}"

    def _validate_vlans(self) -> bool:
        self.vlans = []
        seen_ids = set()
        for id_edit, name_edit, ports_edit in self.vlan_row_entries:
            vid, vname, vport = id_edit.text().strip(), name_edit.text().strip(), ports_edit.text().strip()
            if not vid:
                continue
            try:
                if not (1 <= int(vid) <= 4094):
                    raise ValueError
            except Exception:
                QMessageBox.critical(self, "Invalid VLAN ID", f"VLAN ID must be 1–4094. Got: {vid!r}")
                return False
            if vid in seen_ids:
                QMessageBox.critical(self, "Duplicate VLAN ID", f"VLAN ID {vid} appears more than once.")
                return False
            seen_ids.add(vid)
            self.vlans.append({"id": vid, "name": vname or f"VLAN{vid}", "ports": vport})
        if not self.vlans:
            QMessageBox.critical(self, "Required", "Add at least one VLAN.")
            return False
        return True

    def _build_step_routing(self, body):
        t = self.THEME
        ctx = self.project_context
        layout = body.layout() or QVBoxLayout(body)
        layout.setSpacing(10)
        if self.routing_mode != "device":
            layout.addWidget(self._lbl(body, "Routing is handled on a separate device — nothing to configure here.", muted=True))
            return
        layout.addWidget(self._help_link(body, "SVI"))
        if ctx.get("routing_entries") and not self.routing_entries:
            def _use_ctx_svi():
                self.routing_entries = list(ctx["routing_entries"])
            layout.addWidget(self._show_suggestion_banner(body,
                f"Matched subinterface IPs — SVIs will mirror the router's gateway addresses.",
                on_accept=_use_ctx_svi))
            self.routing_entries = list(ctx["routing_entries"])
        layout.addWidget(self._lbl(body, "IP addressing scheme", bold=True))
        scheme_f = QWidget()
        sfl = QHBoxLayout(scheme_f)
        sfl.setContentsMargins(0, 0, 0, 0)
        sfl.setSpacing(10)
        sfl.addWidget(self._lbl(body, "First two octets:"))
        self.ip_scheme_var = self._entry(body, ctx.get("ip_scheme", "192.168"), 12)
        sfl.addWidget(self.ip_scheme_var)
        sfl.addWidget(self._lbl(body, ".VLANID.1   (e.g. VLAN 10 -> 192.168.10.1 / 24)", muted=True))
        layout.addWidget(scheme_f)
        layout.addWidget(self._lbl(body, "Auto-generated gateways:", muted=True))
        layout.addWidget(self._section_hdr(body, [("VLAN ID", 10), ("Name", 18), ("Gateway IP", 18), ("Subnet Mask", 16)]))
        self.routing_rows_widget = QWidget()
        self.routing_rows_layout = QVBoxLayout(self.routing_rows_widget)
        layout.addWidget(self.routing_rows_widget)

        def rebuild():
            while self.routing_rows_layout.count():
                c = self.routing_rows_layout.takeAt(0)
                if c.widget():
                    c.widget().deleteLater()
            self.routing_row_entries.clear()
            scheme = self.ip_scheme_var.text().strip()
            for i, vlan in enumerate(self.vlans):
                vid, vname = vlan.get("id", "10"), vlan.get("name", f"VLAN{vlan.get('id','10')}")
                ex_ip = next((r.get("ip", "") for r in self.routing_entries if str(r.get("vlan", "")) == str(vid)), "")
                auto_ip = ex_ip or f"{scheme}.{vid}.1"
                rf = self._row_box(self.routing_rows_widget, alt=bool(i % 2), padding=6)
                rfl = QHBoxLayout(rf)
                rfl.setContentsMargins(8, 6, 8, 6)
                rfl.setSpacing(10)
                rfl.addWidget(QLabel(vid))
                rfl.addWidget(QLabel(vname))
                ip_v = self._entry(rf, auto_ip, 18)
                mask_v = self._entry(rf, "255.255.255.0", 16)
                rfl.addWidget(ip_v)
                rfl.addWidget(mask_v)
                self.routing_row_entries.append((vid, vname, ip_v, mask_v))
                self.routing_rows_layout.addWidget(rf)
        self.ip_scheme_var.textChanged.connect(rebuild)
        rebuild()

    def _validate_routing(self) -> bool:
        import ipaddress as _ip
        if self.routing_mode != "device":
            self.routing_entries = []
            return True
        self.routing_entries = []
        for vid, vname, ip_v, mask_v in self.routing_row_entries:
            ip_str, mask_str = ip_v.text().strip(), mask_v.text().strip()
            if not ip_str:
                continue
            try:
                _ip.ip_address(ip_str)
            except ValueError:
                QMessageBox.critical(self, "Invalid IP", f"VLAN {vid}: '{ip_str}' is not a valid IP address.")
                return False
            if mask_str:
                try:
                    _ip.ip_address(mask_str)
                except ValueError:
                    QMessageBox.critical(self, "Invalid Mask", f"VLAN {vid}: '{mask_str}' is not a valid subnet mask.")
                    return False
            self.routing_entries.append({"vlan": vid, "name": vname, "ip": ip_str, "mask": mask_str or "255.255.255.0"})
        return True

    def _build_step_router_subinterfaces(self, body):
        t = self.THEME
        ctx = self.project_context
        layout = body.layout() or QVBoxLayout(body)
        layout.setSpacing(10)
        layout.addWidget(self._help_link(body, "Subinterface"))
        if ctx.get("routing_entries") and not self.routing_entries:
            self.routing_entries = list(ctx["routing_entries"])
            self.vlans = [{"id": r["vlan"], "name": r["name"], "ports": ""} for r in self.routing_entries]
        elif ctx.get("vlans") and not self.routing_entries and not self.vlans:
            self.vlans = [{"id": v["id"], "name": v["name"], "ports": ""} for v in ctx["vlans"]]
        iface_f = QWidget()
        ifl = QHBoxLayout(iface_f)
        ifl.setContentsMargins(0, 0, 0, 0)
        ifl.setSpacing(10)
        ifl.addWidget(QLabel("Interface connected to the switch:"))
        _fallback = ["FastEthernet0/0", "GigabitEthernet1/0", "GigabitEthernet2/0", "Serial6/0"]
        ifaces = self.known_interfaces if self.known_interfaces else _fallback
        # Auto-detect the connected interface from GNS3 cables
        _link = self._find_link_to("core", "access")
        if _link:
            default = _link["local_interface"]
        else:
            default = self.router_interface or (ifaces[0] if ifaces else "FastEthernet0/0")
        self.router_interface_combo = QComboBox()
        self.router_interface_combo.addItems(ifaces)
        self.router_interface_combo.setCurrentText(default)
        self.router_interface_combo.setEditable(True)
        ifl.addWidget(self.router_interface_combo)
        layout.addWidget(iface_f)
        if _link:
            layout.addWidget(self._show_suggestion_banner(
                body,
                f"Detected cable: {_link['local_interface']} ↔ {_link['remote_device']} ({_link['remote_interface']}). "
                "Auto-selected as the trunk interface.",
            ))
        source_vlans = self.vlans
        if not source_vlans:
            cnt_row = QWidget()
            cntl = QHBoxLayout(cnt_row)
            cntl.setContentsMargins(0, 0, 0, 0)
            cntl.setSpacing(10)
            cntl.addWidget(self._lbl(body, "How many VLANs to route?"))
            self.sub_count_spin = QSpinBox()
            self.sub_count_spin.setRange(1, 12)
            self.sub_count_spin.setValue(max(2, len(self.routing_entries)))
            cntl.addWidget(self.sub_count_spin)
            layout.addWidget(cnt_row)
        scheme_f = QWidget()
        sfl = QHBoxLayout(scheme_f)
        sfl.setContentsMargins(0, 0, 0, 0)
        sfl.setSpacing(10)
        sfl.addWidget(QLabel("IP scheme (first two octets):"))
        self.ip_scheme_var = self._entry(body, ctx.get("ip_scheme", "192.168"), 12)
        sfl.addWidget(self.ip_scheme_var)
        layout.addWidget(scheme_f)
        layout.addWidget(self._section_hdr(body, [("VLAN ID", 10), ("Name", 18), ("Gateway IP", 18), ("Mask", 16)]))
        self.routing_rows_widget = QWidget()
        self.routing_rows_layout = QVBoxLayout(self.routing_rows_widget)
        layout.addWidget(self.routing_rows_widget)

        def get_vlans():
            if source_vlans:
                return source_vlans
            return [{"id": str((i+1)*10), "name": f"VLAN{(i+1)*10}"} for i in range(self.sub_count_spin.value())]

        def rebuild():
            while self.routing_rows_layout.count():
                c = self.routing_rows_layout.takeAt(0)
                if c.widget():
                    c.widget().deleteLater()
            self.routing_row_entries.clear()
            scheme = self.ip_scheme_var.text().strip()
            for i, vlan in enumerate(get_vlans()):
                vid = vlan.get("id", "10")
                vname = vlan.get("name", f"VLAN{vid}")
                ex_ip = next((r.get("ip", "") for r in self.routing_entries if str(r.get("vlan", "")) == str(vid)), "")
                auto_ip = ex_ip or f"{scheme}.{vid}.1"
                rf = self._row_box(self.routing_rows_widget, alt=bool(i % 2), padding=6)
                rfl = QHBoxLayout(rf)
                rfl.setContentsMargins(8, 6, 8, 6)
                rfl.setSpacing(8)
                id_v = self._entry(rf, vid, 10)
                name_v = self._entry(rf, vname, 18)
                ip_v = self._entry(rf, auto_ip, 18)
                mask_v = self._entry(rf, "255.255.255.0", 16)
                rfl.addWidget(id_v)
                rfl.addWidget(name_v)
                rfl.addWidget(ip_v)
                rfl.addWidget(mask_v)
                self.routing_row_entries.append((id_v, name_v, ip_v, mask_v))
                self.routing_rows_layout.addWidget(rf)
        if not source_vlans:
            self.sub_count_spin.valueChanged.connect(rebuild)
        self.ip_scheme_var.textChanged.connect(rebuild)
        rebuild()

    def _validate_router_subinterfaces(self) -> bool:
        self.router_interface = self.router_interface_combo.currentText()
        self.routing_entries = []
        for id_v, name_v, ip_v, mask_v in self.routing_row_entries:
            vid, ip = id_v.text().strip(), ip_v.text().strip()
            if vid and ip:
                self.routing_entries.append({"vlan": vid, "name": name_v.text().strip(), "ip": ip, "mask": mask_v.text().strip() or "255.255.255.0"})
        if not self.routing_entries:
            QMessageBox.critical(self, "Required", "Add at least one VLAN / gateway row.")
            return False
        return True

    def _build_step_dhcp(self, body):
        t = self.THEME
        ctx = self.project_context
        layout = body.layout() or QVBoxLayout(body)
        layout.addWidget(self._help_link(body, "DHCP pool"))
        layout.addWidget(self._lbl(body, "Tick the VLANs that should hand out IP addresses automatically.", muted=True))
        dns_f = QWidget()
        dnl = QHBoxLayout(dns_f)
        dnl.addWidget(self._lbl(body, "DNS server:"))
        self.dhcp_dns_var = self._entry(body, "8.8.8.8", 16)
        dnl.addWidget(self.dhcp_dns_var)
        layout.addWidget(dns_f)
        if not self.routing_entries:
            layout.addWidget(self._lbl(body, "No routing entries. Go back and complete Subinterfaces first.", muted=True))
            return
        layout.addWidget(self._lbl(body, "Enable DHCP for:", bold=True))
        self.dhcp_check_vars = []
        default_checked = not bool(ctx.get("dhcp_pools"))
        for i, entry in enumerate(self.routing_entries):
            vid, vname = entry.get("vlan", "?"), entry.get("name", f"VLAN{entry.get('vlan','?')}")
            gw = entry.get("ip", "")
            p = gw.split(".")
            net = rng = "n/a"
            if len(p) == 4:
                net = f"{p[0]}.{p[1]}.{p[2]}.0"
                rng = f"{p[0]}.{p[1]}.{p[2]}.50 – .200"
            rf = self._row_box(body, alt=bool(i % 2), padding=8)
            rfl = QHBoxLayout(rf)
            cb = QCheckBox()
            cb.setChecked(default_checked)
            rfl.addWidget(cb)
            rfl.addWidget(QLabel(f"VLAN {vid}  ({vname})"))
            rfl.addWidget(QLabel(f"network {net}  ·  gateway {gw}  ·  pool {rng}"))
            self.dhcp_check_vars.append((cb, entry))
            layout.addWidget(rf)

    def _validate_dhcp(self) -> bool:
        dns = getattr(self, "dhcp_dns_var", None)
        dns = dns.text().strip() if dns else "8.8.8.8"
        self.dhcp_pools = []
        for cb, entry in self.dhcp_check_vars:
            if not cb.isChecked():
                continue
            gw, mask, vid, name = entry.get("ip", ""), entry.get("mask", "255.255.255.0"), entry.get("vlan", ""), entry.get("name", f"VLAN{entry.get('vlan','')}")
            p = gw.split(".")
            if len(p) != 4:
                continue
            prefix = f"{p[0]}.{p[1]}.{p[2]}"
            self.dhcp_pools.append({"pool": name, "network": f"{prefix}.0", "mask": mask, "gateway": gw, "dns": dns, "start": f"{prefix}.50", "end": f"{prefix}.200"})
        return True

    def _build_step_static_routes(self, body):
        t = self.THEME
        ctx = self.project_context
        layout = body.layout() or QVBoxLayout(body)

        # ── WAN Interface card ────────────────────────────────────────────
        layout.addWidget(self._lbl(body, "Configure the interface that connects to the ISP / internet.", muted=True))
        wan_card = self._card(body)
        wan_card_layout = QVBoxLayout(wan_card)
        wan_card_layout.addWidget(self._lbl(body, "WAN / Internet Interface", bold=True))

        # Interface selector
        wan_iface_f = QWidget()
        wil = QHBoxLayout(wan_iface_f)
        wil.setContentsMargins(0, 0, 0, 0)
        wil.addWidget(QLabel("WAN interface:"))
        _fallback_wan = ["FastEthernet0/1", "GigabitEthernet1/0", "GigabitEthernet0/1"]
        wan_ifaces = [i for i in self.known_interfaces if i != self.router_interface] if self.known_interfaces else _fallback_wan
        if not wan_ifaces:
            wan_ifaces = _fallback_wan
        default_wan = self.wan_interface or (wan_ifaces[0] if wan_ifaces else "FastEthernet0/1")
        self.wan_iface_combo = QComboBox()
        self.wan_iface_combo.addItems(wan_ifaces)
        self.wan_iface_combo.setCurrentText(default_wan)
        self.wan_iface_combo.setEditable(True)
        wil.addWidget(self.wan_iface_combo)
        wan_card_layout.addWidget(wan_iface_f)

        # IP / Mask row
        wan_ip_f = QWidget()
        wipl = QHBoxLayout(wan_ip_f)
        wipl.setContentsMargins(0, 0, 0, 0)
        wipl.addWidget(QLabel("IP address:"))
        self.wan_ip_var = self._entry(body, self.wan_ip or "10.0.0.2", 16)
        wipl.addWidget(self.wan_ip_var)
        wipl.addWidget(QLabel("Mask:"))
        self.wan_mask_var = self._entry(body, self.wan_mask or "255.255.255.252", 16)
        wipl.addWidget(self.wan_mask_var)
        wan_card_layout.addWidget(wan_ip_f)
        layout.addWidget(wan_card)

        # ── Default Route card ────────────────────────────────────────────
        def_card = self._card(body)
        def_card_layout = QVBoxLayout(def_card)
        self.default_route_cb = QCheckBox("Add a default route to the internet / upstream router")
        self.default_route_cb.setChecked(True)
        def_card_layout.addWidget(self.default_route_cb)
        isp_f = QWidget()
        ispl = QHBoxLayout(isp_f)
        ispl.addWidget(QLabel("ISP / upstream gateway IP:"))
        existing = self.static_routes[0].get("next-hop", "") if self.static_routes else ""
        if not existing and ctx.get("isp_gateway"):
            existing = ctx["isp_gateway"]
        elif not existing and self.device_role == "core" and ctx.get("routing_entries"):
            existing = ctx["routing_entries"][0].get("ip", "10.0.0.1")
        if not existing:
            existing = "10.0.0.1"
        self.isp_gw_var = self._entry(body, existing, 18)
        ispl.addWidget(self.isp_gw_var)
        def_card_layout.addWidget(isp_f)
        layout.addWidget(def_card)

        # ── Extra routes ─────────────────────────────────────────────────
        layout.addWidget(self._lbl(body, "Additional static routes:", bold=True))
        self.extra_routes_cb = QCheckBox("I need more static routes (advanced)")
        self.extra_routes_cb.setChecked(len(self.static_routes) > 1)
        layout.addWidget(self.extra_routes_cb)
        self.extra_routes_widget = QWidget()
        self.extra_routes_layout = QVBoxLayout(self.extra_routes_widget)
        layout.addWidget(self.extra_routes_widget)

        def _add_route_row(ex):
            rf = QWidget()
            rfl = QHBoxLayout(rf)
            net_v = self._entry(rf, ex.get("network", ""), 16)
            mask_v = self._entry(rf, ex.get("mask", "255.255.255.0"), 14)
            nh_v = self._entry(rf, ex.get("next-hop", ""), 16)
            desc_v = self._entry(rf, ex.get("description", ""), 20)
            rfl.addWidget(net_v)
            rfl.addWidget(mask_v)
            rfl.addWidget(nh_v)
            rfl.addWidget(desc_v)
            self.extra_route_rows.append((net_v, mask_v, nh_v, desc_v))
            idx = self.extra_routes_layout.count() - 1 if self.extra_routes_layout.count() > 0 else 0
            self.extra_routes_layout.insertWidget(idx, rf)

        def toggle_extra():
            while self.extra_routes_layout.count():
                c = self.extra_routes_layout.takeAt(0)
                if c.widget():
                    c.widget().deleteLater()
            self.extra_route_rows.clear()
            if not self.extra_routes_cb.isChecked():
                return
            self.extra_routes_layout.addWidget(self._section_hdr(body, [("Network", 16), ("Mask", 14), ("Next-Hop", 16), ("Note", 20)]))
            for ex in (self.static_routes[1:] if len(self.static_routes) > 1 else [{}]):
                _add_route_row(ex)
            add_btn = QPushButton("+ Add route")
            add_btn.setStyleSheet(f"color: {t['accent']}; background: transparent;")
            add_btn.clicked.connect(lambda: _add_route_row({}))
            self.extra_routes_layout.addWidget(add_btn)
        self._add_route_row = _add_route_row
        self.extra_routes_cb.toggled.connect(toggle_extra)
        toggle_extra()

    def _validate_static_routes(self) -> bool:
        # Save WAN interface fields
        wan_combo = getattr(self, "wan_iface_combo", None)
        if wan_combo:
            self.wan_interface = wan_combo.currentText().strip()
        wan_ip = getattr(self, "wan_ip_var", None)
        if wan_ip:
            self.wan_ip = wan_ip.text().strip()
        wan_mask = getattr(self, "wan_mask_var", None)
        if wan_mask:
            self.wan_mask = wan_mask.text().strip()

        # Save static routes
        self.static_routes = []
        if getattr(self, "default_route_cb", None) and self.default_route_cb.isChecked():
            isp = getattr(self, "isp_gw_var", None)
            isp = isp.text().strip() if isp else "10.0.0.1"
            if isp:
                self.static_routes.append({"network": "0.0.0.0", "mask": "0.0.0.0", "next-hop": isp, "description": "Default route to ISP"})
        for net_v, mask_v, nh_v, desc_v in self.extra_route_rows:
            net, nh = net_v.text().strip(), nh_v.text().strip()
            if net and nh:
                self.static_routes.append({"network": net, "mask": mask_v.text().strip() or "255.255.255.0", "next-hop": nh, "description": desc_v.text().strip()})
        return True

    def _render_wan_block(self) -> str:
        if not self.wan_interface or not self.wan_ip:
            return ""
        lines = [
            "configure terminal",
            f"interface {self.wan_interface}",
            f" ip address {self.wan_ip} {self.wan_mask or '255.255.255.252'}",
            " no shutdown",
            "exit",
            "!",
            "end",
        ]
        return "\n".join(lines)

    def _build_step_rip(self, body):
        layout = body.layout() or QVBoxLayout(body)
        layout.addWidget(self._lbl(body, "RIPv2 shares routes automatically with neighbouring routers.", muted=True))
        card = self._card(body)
        card_layout = QVBoxLayout(card)
        self.enable_rip_cb = QCheckBox("Enable RIPv2 and advertise all connected networks")
        self.enable_rip_cb.setChecked(self.enable_rip)
        card_layout.addWidget(self.enable_rip_cb)
        layout.addWidget(card)

    def _validate_rip(self) -> bool:
        self.enable_rip = getattr(self, "enable_rip_cb", None)
        self.enable_rip = self.enable_rip.isChecked() if self.enable_rip else False
        self.rip_networks = []
        return True

    def _build_step_uplinks(self, body):
        t = self.THEME
        ctx = self.project_context
        layout = body.layout() or QVBoxLayout(body)
        layout.addWidget(self._help_link(body, "Trunk"))
        layout.addWidget(self._lbl(body, "The uplink port connects this switch to the router or core switch.", muted=True))
        ex0 = self.uplinks[0] if self.uplinks else {}
        ctx_vlan_ids = ",".join(v["id"] for v in ctx["vlans"]) if ctx.get("vlans") else ""
        # Auto-detect the uplink from GNS3 cables
        _link = self._find_link_to("core", "router")
        if _link:
            default_port = _link["local_interface"]
        else:
            default_port = "Ethernet3/3" if self.device_role == "access" else "FastEthernet1/0"
        primary = self._card(body)
        pl = QVBoxLayout(primary)
        pl.addWidget(QLabel("Uplink to core switch or router (trunk port):"))
        self.uplink_port_var = self._entry(body, ex0.get("ports", default_port), 22)
        pl.addWidget(self.uplink_port_var)
        if _link:
            pl.addWidget(self._show_suggestion_banner(
                body,
                f"Detected cable: {_link['local_interface']} \u2194 {_link['remote_device']} ({_link['remote_interface']}). "
                "Auto-filled as the uplink port.",
            ))
        layout.addWidget(primary)
        allowed_f = QWidget()
        afl = QHBoxLayout(allowed_f)
        afl.addWidget(QLabel("Allowed VLANs on this trunk:"))
        self.uplink_vlans_var = self._entry(body, ex0.get("allowed vlans") or ctx_vlan_ids or "all", 22)
        afl.addWidget(self.uplink_vlans_var)
        layout.addWidget(allowed_f)
        ex1 = self.uplinks[1] if len(self.uplinks) > 1 else {}
        sec_f = QWidget()
        sfl = QHBoxLayout(sec_f)
        sfl.addWidget(QLabel("Second uplink port (optional):"))
        self.uplink2_port_var = self._entry(body, ex1.get("ports", ""), 28)
        sfl.addWidget(self.uplink2_port_var)
        layout.addWidget(sec_f)

    def _validate_uplinks(self) -> bool:
        self.uplinks = []
        port = getattr(self, "uplink_port_var", None)
        port = port.text().strip() if port else ""
        allowed = getattr(self, "uplink_vlans_var", None)
        allowed = (allowed.text().strip() if allowed else "") or "all"
        if port:
            self.uplinks.append({"ports": port, "mode": "trunk", "allowed vlans": allowed})
        port2 = getattr(self, "uplink2_port_var", None)
        port2 = (port2.text().strip() if port2 else "")
        if port2:
            self.uplinks.append({"ports": port2, "mode": "trunk", "allowed vlans": allowed, "_downlink": self.device_role == "core"})
        return True

    def _build_step_acl(self, body):
        layout = body.layout() or QVBoxLayout(body)
        layout.addWidget(self._help_link(body, "ACL"))
        self._build_acl_scenarios(body, "gateway")

    def _build_step_acl_access(self, body):
        layout = body.layout() or QVBoxLayout(body)
        layout.addWidget(self._lbl(body, "Optional — lightweight per-switch filtering.", muted=True))
        self._build_acl_scenarios(body, "access")

    def _build_acl_scenarios(self, body, context: str):
        t = self.THEME
        layout = body.layout() or QVBoxLayout(body)
        subnets = []
        for e in self.routing_entries:
            vid, name, gw = e.get("vlan", ""), e.get("name", f"VLAN{e.get('vlan','')}"), e.get("ip", "")
            p = gw.split(".")
            if len(p) == 4:
                subnets.append({"vlan": vid, "name": name, "network": f"{p[0]}.{p[1]}.{p[2]}.0", "wildcard": "0.0.0.255"})
        self.acl_scenario_vars = []
        if not subnets:
            layout.addWidget(self._lbl(body, "No VLAN/routing data found — complete the routing step first." if context == "gateway" else "No ACL scenarios for pure L2 switch.", muted=True))
            return
        layout.addWidget(self._lbl(body, "Tick the rules you want to apply:", bold=True))
        scenarios = []
        if context == "gateway" and len(subnets) >= 2:
            for src in subnets:
                for dst in subnets:
                    if src["vlan"] == dst["vlan"]:
                        continue
                    untrusted = ("guest", "student", "visitor", "untrusted", "iot")
                    default_on = any(k in src["name"].lower() for k in untrusted)
                    scenarios.append((f"Block  {src['name']} (VLAN {src['vlan']})  from accessing  {dst['name']} (VLAN {dst['vlan']})", default_on, src, dst))
        if context == "access":
            scenarios.append(("Permit all traffic from local VLANs (pass-through)", False, None, None))
        for i, (label, default, src, dst) in enumerate(scenarios):
            rf = self._row_box(body, alt=bool(i % 2), padding=6)
            rfl = QVBoxLayout(rf)
            cb = QCheckBox(label)
            cb.setChecked(default)
            rfl.addWidget(cb)
            self.acl_scenario_vars.append((cb, src, dst))
            layout.addWidget(rf)
        layout.addWidget(self._lbl(body, "\nNo applicable rule? Skip this step — ACLs can be added manually later.", muted=True))

    def _validate_acl(self) -> bool:
        self.acl_rules = []
        acl_num = getattr(self, "_preset_acl_num", 101)
        for cb, src, dst in self.acl_scenario_vars:
            if not cb.isChecked() or not src:
                continue
            entry = {"acl #": str(acl_num), "action": "deny", "source": src["network"], "wildcard": src["wildcard"], "remark": f"Block {src['name']} from {dst['name']}" if dst else src["name"]}
            if dst and dst.get("network"):
                entry["destination"] = dst["network"]
                entry["destination_wildcard"] = dst.get("wildcard", "")
            self.acl_rules.append(entry)
        if self.acl_rules:
            self.acl_rules.append({"acl #": str(acl_num), "action": "permit", "source": "any", "wildcard": "", "remark": "Permit all other traffic"})
        return True

    def _build_step_summary(self, body):
        t = self.THEME
        layout = body.layout() or QVBoxLayout(body)
        top_bar = QWidget()
        tbl = QHBoxLayout(top_bar)
        tbl.addWidget(self._lbl(body, "Generated configuration blocks (paste each one separately):"))
        copy_btn = QPushButton("Copy All")
        copy_btn.clicked.connect(self._copy_summary)
        tbl.addWidget(copy_btn)
        layout.addWidget(top_bar)
        self.summary_box = QTextEdit()
        self.summary_box.setReadOnly(True)
        layout.addWidget(self.summary_box, 1)
        self._refresh_summary()

    def _copy_summary(self):
        if self.summary_box:
            text = self.summary_box.toPlainText().strip()
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Copied", "Configuration copied to clipboard.")

    def _validate_summary(self) -> bool:
        self._refresh_summary()
        return True

    # ════════════════════════ summary content ═════════════════════════════════
    def _refresh_summary(self):
        if not self.summary_box:
            return
        self.summary_box.clear()
        self.summary_box.insertPlainText(
            "! =====================================================\n"
            "! PASTE EACH BLOCK SEPARATELY\n"
            "! Wait for the device prompt before the next block.\n"
            "! =====================================================\n\n"
        )
        blocks = [
            ("BLOCK 1 — Identity & Security",     self._render_identity_block()),
            ("BLOCK 2 — VLANs & Port Assignment",  self._render_vlan_block()),
            ("BLOCK 3 — Uplinks & Trunks",          self._render_uplink_block()),
            ("BLOCK 4 — Routing / Subinterfaces",   self._render_routing_block()),
            ("BLOCK 5 — WAN Interface",             self._render_wan_block()),
            ("BLOCK 6 — Static Routes",             self._render_static_routes_block()),
            ("BLOCK 7 — RIPv2",                     self._render_rip_block()),
            ("BLOCK 8 — DHCP Pools",                self._render_dhcp_block()),
            ("BLOCK 9 — Access Control Lists",      self._render_acl_block()),
        ]
        inserted = False
        for title, block in blocks:
            if not block.strip():
                continue
            self.summary_box.insertPlainText(f"! {'='*52}\n! {title}\n! {'='*52}\n")
            self.summary_box.insertPlainText(block.strip() + "\n\n")
            self.summary_box.insertPlainText(f"! {'─'*52}\n! Block done — wait for prompt.\n\n\n")
            inserted = True
        if not inserted:
            self.summary_box.insertPlainText("Nothing generated yet — go back and complete the earlier steps.\n")
        else:
            self.summary_box.insertPlainText(
                "! =====================================================\n"
                "! ALL DONE — save configuration with:\n"
                "!   write memory\n"
                "! =====================================================\n"
                "write memory\n"
            )

    # ════════════════════════ template writing ═════════════════════════════════
    def _write_templates(self):
        self._cleanup_default_templates()
        templates = {
            "guided_identity":      self._render_identity_block(),
            "guided_vlans":         self._render_vlan_block(),
            "guided_uplinks":       self._render_uplink_block(),
            "guided_routing":       self._render_routing_block(),
            "guided_wan":           self._render_wan_block(),
            "guided_static_routes": self._render_static_routes_block(),
            "guided_rip":           self._render_rip_block(),
            "guided_dhcp":          self._render_dhcp_block(),
            "guided_acl":           self._render_acl_block(),
            "guided_save":          "write memory",
        }
        for key, value in templates.items():
            if value.strip():
                self.device_model.set_template(key, value)

    def _cleanup_default_templates(self):
        self.device_model.snapshot_templates()
        for key in list(self.device_model.templates.keys()):
            if key.startswith("guided_"):
                del self.device_model.templates[key]

    def _expand_ports_to_list(self, ports: str) -> List[str]:
        if not ports:
            return []
        result = []
        for part in str(ports).split(","):
            part = part.strip()
            if not part:
                continue
            slash = part.rfind("/")
            if slash == -1:
                result.append(part)
                continue
            prefix = part[: slash + 1]
            tail = part[slash + 1:]
            if "-" in tail:
                a, b = tail.split("-", 1)
                try:
                    start, end = int(a), int(b)
                except ValueError:
                    result.append(part)
                    continue
                step = 1 if end >= start else -1
                for n in range(start, end + step, step):
                    result.append(f"{prefix}{n}")
            else:
                result.append(part)
        return result

    def _render_identity_block(self) -> str:
        if not self.identity_data:
            return ""
        hostname = self.identity_data.get("hostname", self.device_name)
        domain = self.identity_data.get("domain", "")
        lines = ["configure terminal", f"hostname {hostname}", "no ip domain-lookup"]
        if domain:
            lines.append(f"ip domain-name {domain}")
        lines += [
            "!", "! ---------------------------------------------------------------",
            "! SECURITY NOTE: Passwords, enable secrets, and login authentication",
            "! have been intentionally left out. Please set up 'enable secret',",
            "! 'username', and 'line con/vty login' manually.",
            "! ---------------------------------------------------------------", "!",
            "line vty 0 4", " transport input telnet ssh", " logging synchronous",
            "exit", "!", "end",
        ]
        return "\n".join(lines)

    def _render_vlan_block(self) -> str:
        if self.device_role == "router" or not self.vlans:
            return ""
        lines = []
        if self.device_role == "core":
            lines.append("vlan database")
            for v in self.vlans:
                lines.append(f"vlan {v.get('id')} name {v.get('name') or 'VLAN' + str(v.get('id', ''))}")
            lines += ["exit", "!", "configure terminal"]
            for v in self.vlans:
                for iface in self._expand_ports_to_list(v.get("ports", "")):
                    if iface:
                        lines += [f"interface {iface}", " switchport mode access", f" switchport access vlan {v.get('id')}", " no shutdown", "exit"]
            lines += ["!", "end"]
        else:
            lines.append("configure terminal")
            for v in self.vlans:
                lines += [f"vlan {v.get('id')}", f" name {v.get('name') or 'VLAN' + str(v.get('id', ''))}", "exit"]
            lines.append("!")
            for v in self.vlans:
                for iface in self._expand_ports_to_list(v.get("ports", "")):
                    if iface:
                        lines += [f"interface {iface}", " switchport mode access", f" switchport access vlan {v.get('id')}", " no shutdown", "exit"]
            lines += ["!", "end"]
        return "\n".join(lines)

    def _render_uplink_block(self) -> str:
        if not self.uplinks:
            return ""
        lines = ["configure terminal"]
        for link in self.uplinks:
            ports = link.get("ports", "").strip()
            mode = (link.get("mode") or "trunk").lower()
            allowed = link.get("allowed vlans", "all")
            if not ports:
                continue
            for port in [p.strip() for p in ports.split(",") if p.strip()]:
                lines.append(f"interface {port}")
                if mode == "trunk":
                    lines.append(" switchport trunk encapsulation dot1q")
                    lines.append(" switchport mode trunk")
                    lines.append(f" switchport trunk allowed vlan {allowed}" if allowed.lower() != "all" else " switchport trunk allowed vlan all")
                else:
                    lines.append(" switchport mode access")
                    if allowed.lower() != "all":
                        lines.append(f" switchport access vlan {allowed}")
                lines += [" no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_routing_block(self) -> str:
        if self.routing_mode != "device" or not self.routing_entries:
            return ""
        if self.device_role == "router":
            return self._render_router_on_stick_block()
        lines = ["configure terminal", "ip routing"]
        for e in self.routing_entries:
            vlan, ip, mask = e.get("vlan"), e.get("ip"), e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface Vlan{vlan}", f" ip address {ip} {mask}", " no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_router_on_stick_block(self) -> str:
        if not self.router_interface or not self.routing_entries:
            return ""
        lines = ["configure terminal", f"interface {self.router_interface}", " no shutdown", "exit"]
        for e in self.routing_entries:
            vlan, ip, mask = e.get("vlan"), e.get("ip"), e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface {self.router_interface}.{vlan}", f" encapsulation dot1Q {vlan}", f" ip address {ip} {mask}", " no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_static_routes_block(self) -> str:
        if not self.static_routes:
            return ""
        lines = ["configure terminal"]
        for r in self.static_routes:
            net, mask, nh, desc = r.get("network"), r.get("mask"), r.get("next-hop"), r.get("description", "")
            if net and nh:
                if desc:
                    lines.append(f"! {desc}")
                lines.append(f"ip route {net} {mask} {nh}")
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_rip_block(self) -> str:
        if not self.enable_rip:
            return ""
        lines = ["configure terminal", "router rip", " version 2", " no auto-summary"]
        seen = set()
        for e in self.routing_entries:
            ip = e.get("ip", "")
            try:
                import ipaddress as _ip
                addr = _ip.ip_address(ip)
                first_octet = int(str(addr).split(".")[0])
                classful_net = f"{str(addr).split('.')[0]}.0.0.0" if first_octet <= 127 else (
                    f"{str(addr).split('.')[0]}.{str(addr).split('.')[1]}.0.0" if first_octet <= 191 else
                    f"{str(addr).split('.')[0]}.{str(addr).split('.')[1]}.{str(addr).split('.')[2]}.0")
                if classful_net not in seen:
                    seen.add(classful_net)
                    lines.append(f" network {classful_net}")
            except Exception:
                pass
        lines += ["exit", "!", "end"]
        return "\n".join(lines)

    def _render_dhcp_block(self) -> str:
        if self.device_role == "access" or not self.dhcp_pools:
            return ""
        lines = ["configure terminal"]
        for pool in self.dhcp_pools:
            gw, start, end = pool.get("gateway", ""), pool.get("start", ""), pool.get("end", "")
            if gw and start:
                p = start.split(".")
                try:
                    s_last = int(p[3])
                    pfx = ".".join(gw.split(".")[:3])
                    lines.append(f"ip dhcp excluded-address {gw} {pfx}.{s_last - 1}" if s_last > 1 else f"ip dhcp excluded-address {gw}")
                except (IndexError, ValueError):
                    pass
            elif gw:
                lines.append(f"ip dhcp excluded-address {gw}")
            if end:
                p = end.split(".")
                try:
                    e_last = int(p[3])
                    pfx = ".".join(p[:3])
                    if e_last < 254:
                        lines.append(f"ip dhcp excluded-address {pfx}.{e_last + 1} {pfx}.254")
                except (IndexError, ValueError):
                    pass
            pool_name = (pool.get("pool") or pool.get("name") or "POOL").replace(" ", "_").replace("/", "-")
            lines.append(f"ip dhcp pool {pool_name}")
            lines.append(f" network {pool.get('network')} {pool.get('mask', '255.255.255.0')}")
            if gw:
                lines.append(f" default-router {gw}")
            if pool.get("dns"):
                lines.append(f" dns-server {pool['dns']}")
            lines.append(" lease 0 2")
            lines.append("exit")
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_acl_block(self) -> str:
        if not self.acl_rules:
            return ""
        acl_num = self.acl_rules[0].get("acl #", "101")
        is_extended = int(acl_num) >= 100
        lines = ["configure terminal"]
        for rule in self.acl_rules:
            num, action, src, wc = rule.get("acl #", "101"), rule.get("action", "permit"), rule.get("source", "any"), rule.get("wildcard", "")
            dst, dst_wc, remark = rule.get("destination", ""), rule.get("destination_wildcard", ""), rule.get("remark", "")
            if remark:
                lines.append(f"access-list {num} remark {remark}")
            if is_extended:
                lines.append(f"access-list {num} {action} ip any any" if src.lower() == "any" else
                    f"access-list {num} {action} ip {src} {wc} {dst} {dst_wc}" if dst and dst.lower() != "any" else
                    f"access-list {num} {action} ip {src} {wc} any")
            else:
                lines.append(f"access-list {num} {action} any" if src.lower() == "any" else f"access-list {num} {action} {src} {wc}")
        lines.append("!")
        if is_extended:
            applied_ifaces = set()
            for rule in self.acl_rules:
                src_net = rule.get("source", "")
                if not src_net or src_net.lower() == "any":
                    continue
                for e in self.routing_entries:
                    e_ip = e.get("ip", "")
                    e_net = ".".join(e_ip.split(".")[:3]) + ".0" if e_ip else ""
                    src_prefix = ".".join(src_net.split(".")[:3]) + ".0" if src_net else ""
                    if e_net and src_prefix and e_net == src_prefix:
                        vlan = e.get("vlan")
                        if vlan:
                            iface = f"{self.router_interface}.{vlan}" if self.device_role == "router" and self.router_interface else f"Vlan{vlan}"
                            if iface not in applied_ifaces:
                                applied_ifaces.add(iface)
                                lines += [f"interface {iface}", f" ip access-group {acl_num} in", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _get_show_vlan_command(self) -> str:
        return "show vlan-switch" if self.device_role == "core" else "show vlan brief"
