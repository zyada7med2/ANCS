"""
Smart Bulk Operations — topology detection, config suggestion, and parallel deploy.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import List, Dict, Tuple, Any

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

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
            # flat / unknown — treat every device as access
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

        # Divide interfaces evenly across VLANs
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
    "router": "🔀",
    "core":   "🔶",
    "access": "🔷",
}


class BulkDeployPanel(ctk.CTkToplevel):
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

        self.title("Smart Bulk Deploy")
        self.resizable(True, True)
        # transient() must be set BEFORE geometry so the window manager can
        # position the dialog relative to the parent on multi-monitor setups.
        self.transient(parent)
        apply_responsive_geometry(self, 900, 680, min_w=700, min_h=500)
        self.configure(fg_color=_BG)
        self.grab_set()
        self._deploy_running = False
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        # Detect topology and build suggestions
        self.topology = TopologyDetector(devices).detect()
        self.plans    = ConfigSuggester(self.topology).suggest()

        # Per-plan override flag (after user customises via wizard)
        self._customised: Dict[int, bool] = {}

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        hdr = ctk.CTkFrame(self, fg_color=_PANEL, height=60)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="Smart Bulk Deploy",
            font=ctk.CTkFont(family=_FONT, size=18, weight="bold"),
            text_color=_TEXT,
        ).pack(side="left", padx=20, pady=14)

        pattern_label = _PATTERN_LABELS.get(self.topology["pattern"], self.topology["pattern"])
        ctk.CTkLabel(
            hdr,
            text=f"Detected: {pattern_label}  •  {len(self.plans)} device(s)",
            font=ctk.CTkFont(family=_FONT, size=12),
            text_color=_MUTED,
        ).pack(side="left", padx=8)

        # ── Body: two columns ──
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        # Left: device plan cards (scrollable)
        left = ctk.CTkScrollableFrame(body, fg_color=_PANEL, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            left,
            text="Configuration Plan",
            font=ctk.CTkFont(family=_FONT, size=14, weight="bold"),
            text_color=_MUTED,
        ).pack(anchor="w", padx=16, pady=(14, 8))

        if not self.plans:
            ctk.CTkLabel(
                left,
                text="No devices to configure.\nImport devices from GNS3 first.",
                text_color=_MUTED,
                font=ctk.CTkFont(family=_FONT, size=13),
            ).pack(padx=16, pady=32)
        else:
            for idx, plan in enumerate(self.plans):
                self._build_plan_card(left, idx, plan)

        # Right: log area + deploy button
        right = ctk.CTkFrame(body, fg_color=_PANEL, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right,
            text="Deploy Log",
            font=ctk.CTkFont(family=_FONT, size=14, weight="bold"),
            text_color=_MUTED,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

        self.log_box = ctk.CTkTextbox(
            right,
            fg_color=_CARD,
            text_color=_TEXT,
            font=ctk.CTkFont(family="Courier New", size=12),
            corner_radius=8,
            border_width=1,
            border_color=_BORDER,
            wrap="word",
            state="disabled",
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

        # Force re-deploy toggle
        force_row = ctk.CTkFrame(right, fg_color="transparent")
        force_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))
        self._force_redeploy_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            force_row,
            text="Force re-deploy (ignore 'already deployed' check)",
            variable=self._force_redeploy_var,
            font=ctk.CTkFont(family=_FONT, size=11),
            text_color=_MUTED,
            fg_color=_YELLOW,
            hover_color="#b07800",
        ).pack(side="left")

        # Deploy All button
        self.deploy_btn = ctk.CTkButton(
            right,
            text="Deploy All",
            command=self._deploy_all,
            fg_color=_ACCENT,
            hover_color="#388bfd",
            text_color="#fff",
            font=ctk.CTkFont(family=_FONT, size=14, weight="bold"),
            corner_radius=8,
            height=40,
        )
        self.deploy_btn.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 6))

        # Generate-only button (no send)
        ctk.CTkButton(
            right,
            text="Generate Configs Only",
            command=self._generate_only,
            fg_color="transparent",
            hover_color="#28313E",
            text_color=_ACCENT,
            font=ctk.CTkFont(family=_FONT, size=13),
            corner_radius=8,
            height=34,
            border_width=1,
            border_color=_ACCENT,
        ).grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 16))

    def _build_plan_card(self, parent, idx: int, plan: dict):
        name, model, meta = plan["device"]
        role   = plan["role"]
        icon   = _ROLE_ICONS.get(role, "🔲")

        # Determine initial deploy status by comparing stored vs current hash
        stored_hash = _load_deployed_hash(name)
        current_hash = _config_hash(model.build_full_config()) if model.templates else ""
        if not stored_hash:
            init_status, init_color = "● Not deployed", _ACCENT
            should_include = True
        elif current_hash == stored_hash:
            init_status, init_color = "✓ Deployed", _GREEN
            should_include = False   # unchanged — opt-out by default
        else:
            init_status, init_color = "↑ Modified", _YELLOW
            should_include = True

        plan["_stored_hash"] = stored_hash

        card = ctk.CTkFrame(parent, fg_color=_CARD, corner_radius=8)
        card.pack(fill="x", padx=12, pady=(0, 8))

        # Title row
        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            title_row,
            text=f"{icon}  {name}",
            font=ctk.CTkFont(family=_FONT, size=13, weight="bold"),
            text_color=_TEXT,
        ).pack(side="left")

        # Include-in-deploy checkbox (right side of title row)
        include_var = ctk.BooleanVar(value=should_include)
        plan["_include_var"] = include_var

        def _on_include_toggle(v=include_var, p=plan):
            """When the checkbox changes, re-tint the card border."""
            pass  # visual update handled by the deploy status label colour

        ctk.CTkCheckBox(
            title_row,
            text="Deploy",
            variable=include_var,
            command=_on_include_toggle,
            font=ctk.CTkFont(family=_FONT, size=11),
            text_color=_MUTED,
            fg_color=_ACCENT,
            hover_color="#388bfd",
            width=80,
        ).pack(side="right", padx=(0, 4))

        # Status badge
        status_var = tk.StringVar(value=init_status)
        status_lbl = ctk.CTkLabel(
            title_row,
            textvariable=status_var,
            font=ctk.CTkFont(family=_FONT, size=11),
            text_color=init_color,
        )
        status_lbl.pack(side="right", padx=(0, 8))
        plan["_status_var"] = status_var
        plan["_status_lbl"] = status_lbl

        # Summary bullets
        summary = self._plan_summary(plan)
        ctk.CTkLabel(
            card,
            text=summary,
            font=ctk.CTkFont(family=_FONT, size=11),
            text_color=_MUTED,
            justify="left",
            anchor="w",
            wraplength=340,
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # Customize button
        ctk.CTkButton(
            card,
            text="Customize in Wizard",
            command=lambda i=idx: self._customize(i),
            fg_color="transparent",
            hover_color="#28313E",
            text_color=_ACCENT,
            font=ctk.CTkFont(family=_FONT, size=12),
            corner_radius=6,
            height=28,
            border_width=1,
            border_color=_ACCENT,
        ).pack(anchor="e", padx=12, pady=(0, 10))

    def _plan_summary(self, plan: dict) -> str:
        bkts = plan["buckets"]
        role = plan["role"]
        lines = []

        if role == "router":
            iface = bkts.get("router_interface") or "FastEthernet0/0"
            n_sub = len(bkts.get("routing_entries", []))
            n_dhcp = len(bkts.get("dhcp_pools", []))
            lines.append(f"Interface: {iface}  •  {n_sub} subinterface(s)")
            lines.append(f"DHCP pools: {n_dhcp}  •  Default route to ISP")
        elif role == "core":
            n_v = len(bkts.get("vlans", []))
            lines.append(f"{n_v} VLANs  •  SVI routing (ip routing)")
        elif role == "access":
            n_v = len(bkts.get("vlans", []))
            up  = bkts.get("uplinks", [{}])
            lines.append(f"{n_v} VLANs  •  Trunk uplink: {up[0].get('ports','—') if up else '—'}")

        pw = bkts.get("identity_data", {}).get("enable", "—")
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
        # Pre-fill all buckets so the wizard opens with the suggestion loaded
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
        # Jump straight to Identity step (skip Welcome)
        win.current_step = 1
        win._render_step()
        self.wait_window(win)
        self._customised[idx] = True
        # Config may have changed after customisation — clear cached hash so it
        # compares fresh on next deploy and the card shows "Modified ↑"
        plan = self.plans[idx]
        plan["_stored_hash"] = ""
        self._set_plan_status(plan, "↑ Modified")
        self._set_plan_status_color(plan, _YELLOW)
        if plan.get("_include_var"):
            plan["_include_var"].set(True)

    def _generate_only(self):
        """Generate configs for all devices silently (no send)."""
        if not self.plans:
            return
        self._log_write("Generating configs for all devices...\n")
        for idx, plan in enumerate(self.plans):
            self._apply_plan_to_model(idx, plan)
            name = plan["device"][0]
            self._log_write(f"  [OK] {name} — config generated\n")
        self._log_write("\nDone. Use 'Send' in the main window for individual devices,\nor click 'Deploy All' to push all configs now.\n")
        messagebox.showinfo(
            "Configs Generated",
            "All configs have been generated.\nYou can review them in the main window by selecting each device.",
            parent=self,
        )

    def _deploy_all(self):
        """Generate all configs then push them in parallel via Telnet."""
        if not self.plans:
            messagebox.showwarning("No devices", "No devices in the plan.", parent=self)
            return

        gns3_only = [p for p in self.plans if p["device"][2].get("gns3_node")]
        if not gns3_only:
            messagebox.showwarning(
                "No GNS3 devices",
                "Bulk deploy requires GNS3 devices with console IP/port.\n"
                "Import devices from GNS3 first.",
                parent=self,
            )
            return

        force = self._force_redeploy_var.get()
        self.deploy_btn.configure(state="disabled", text="Deploying...")
        self._log_write("=== Bulk Deploy Started ===\n\n")
        if force:
            self._log_write("⚠  Force re-deploy enabled — skipping hash check\n\n")

        for idx, plan in enumerate(self.plans):
            self._apply_plan_to_model(idx, plan)

        threads = []
        self._deploy_running = True
        for idx, plan in enumerate(self.plans):
            name = plan["device"][0]
            meta = plan["device"][2]

            # Respect the per-device include checkbox
            if not plan.get("_include_var", ctk.BooleanVar(value=True)).get():
                self._log_write(f"[SKIP] {name} — excluded by checkbox\n")
                self._set_plan_status(plan, "skipped")
                continue

            if not meta.get("gns3_node"):
                self._log_write(f"[SKIP] {name} — not a GNS3 device\n")
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
            self.after(0, lambda: self.deploy_btn.configure(
                state="normal", text="Deploy All"
            ))
            self.after(0, lambda: self._log_write("\n=== Bulk Deploy Complete ===\n"))

        threading.Thread(target=_wait_all, daemon=True).start()

    def _send_one(self, idx: int, plan: dict, force: bool = False):
        name, model, meta = plan["device"]
        host   = meta.get("console_host", "localhost")
        port   = meta.get("console_port", "")
        config = model.build_full_config()

        if not config.strip():
            self._log_write(f"[{name}] No config to send — run Generate first.\n")
            self._set_plan_status(plan, "no config")
            return

        # ── Hash check: skip if unchanged since last successful deploy ──
        current_hash = _config_hash(config)
        stored_hash  = plan.get("_stored_hash", "")
        if stored_hash and current_hash == stored_hash and not force:
            self._log_write(
                f"[{name}] Config unchanged since last deploy — skipping. "
                f"Enable 'Force re-deploy' to push anyway.\n"
            )
            self._set_plan_status(plan, "✓ Up-to-date")
            self._set_plan_status_color(plan, _GREEN)
            return

        self._log_write(f"[{name}] Connecting to {host}:{port}...\n")
        self._set_plan_status(plan, "connecting…")
        self._set_plan_status_color(plan, _MUTED)

        try:
            port_int = int(port) if port else 23
        except (ValueError, TypeError):
            port_int = 23

        # Use credentials from identity_data if available (more reliable than raw meta)
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
            # Persist hash so future deploys detect "already deployed"
            _save_deployed_hash(name, current_hash)
            plan["_stored_hash"] = current_hash
            self._log_write(f"[{name}] Config sent successfully.\n")
            self._set_plan_status(plan, "✓ Deployed")
            self._set_plan_status_color(plan, _GREEN)
        except Exception as e:
            self._log_write(f"[{name}] ERROR: {e}\n")
            self._set_plan_status(plan, "✗ Failed")
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

        # Use the wizard in headless mode to reuse all renderers
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
        # Destroy the hidden window immediately
        wiz.destroy()

    def _on_close_request(self):
        """Guard window close while deploy threads are running."""
        from tkinter import messagebox as _mb
        if self._deploy_running:
            if not _mb.askokcancel(
                "Deploy in progress",
                "A bulk deploy is currently running.\n"
                "Closing now may leave devices partially configured.\n\n"
                "Close anyway?",
                parent=self,
            ):
                return
        self.grab_release()
        self.destroy()

    def _set_plan_status(self, plan: dict, text: str):
        """Thread-safe wrapper for updating a plan's status StringVar."""
        try:
            self.after(0, lambda v=plan["_status_var"], t=text: v.set(t))
        except Exception:
            pass

    def _set_plan_status_color(self, plan: dict, color: str):
        """Thread-safe wrapper for updating the status label text_color."""
        try:
            lbl = plan.get("_status_lbl")
            if lbl:
                self.after(0, lambda l=lbl, c=color: l.configure(text_color=c))
        except Exception:
            pass

    def _log_write(self, msg: str):
        """Thread-safe log write — updates local log_box AND main app Logs tab."""
        def _write():
            try:
                self.log_box.configure(state="normal")
                self.log_box.insert("end", msg)
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except Exception:
                pass
            # Mirror every non-blank line to the main application Logs tab
            stripped = msg.strip()
            if stripped:
                try:
                    self.parent_app.log(f"[BulkDeploy] {stripped}")
                except Exception:
                    pass
        try:
            self.after(0, _write)
        except Exception:
            pass
