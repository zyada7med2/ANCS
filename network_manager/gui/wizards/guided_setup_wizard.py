"""
Guided multi-step setup wizard — smart forms edition.

Every step asks the minimum questions needed; all other config values
(DHCP pools, routing entries, ACL rules) are auto-derived so the user
never has to edit raw tables or type IOS syntax manually.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import Callable, List, Dict, Optional

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

# Preset catalogue: key → (display_name, short_description)
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
    build_ui: Callable[["GuidedSetupWizard", tk.Frame], None]
    validate: Callable[["GuidedSetupWizard"], bool]


# ══════════════════════════════════════════════════════════════════════════════
class GuidedSetupWizard(tk.Toplevel):
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
    ):
        super().__init__(parent)

        self.headless = headless

        if headless:
            # Invisible window used purely to call _write_templates()
            self.withdraw()
        else:
            self.title("Guided Setup — Smart Wizard")
            self.geometry("960x620")
            self.resizable(True, True)
            self.minsize(800, 520)
            self.configure(bg=self.THEME["bg"])
            self._setup_ttk_theme()

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
        self.router_interface: str          = ""  # resolved from known_interfaces or dropdown
        self.static_routes: List[Dict]      = []
        self.rip_networks:  List[Dict]      = []
        self.enable_rip:    bool            = False
        self.summary_box:   Optional[tk.Text] = None

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

    # ════════════════════════ routing mode dialog ══════════════════════════════
    def _prompt_routing_mode(self):
        if self.device_role == "access":
            self.routing_mode = "external"
            return

        t = self.THEME
        dlg = tk.Toplevel(self)
        dlg.title("Network setup")
        dlg.geometry("500x320")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=t["bg"])

        tk.Label(
            dlg, text="How is your network set up?",
            font=("Segoe UI", 13, "bold"), fg=t["text"], bg=t["bg"],
        ).pack(anchor="w", padx=18, pady=(18, 4))
        tk.Label(
            dlg, text="Choose the option that matches your topology.",
            fg=t["muted"], bg=t["bg"],
        ).pack(anchor="w", padx=18)

        choice = tk.StringVar(value="device")

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

        for val, title, sub in opts:
            f = tk.Frame(dlg, bg=t["bg"])
            f.pack(fill="x", padx=18, pady=(12, 0))
            tk.Radiobutton(
                f, text=title, variable=choice, value=val,
                anchor="w", fg=t["text"], bg=t["bg"],
                selectcolor=t["card"], activebackground=t["bg"],
                activeforeground=t["text"], font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w")
            tk.Label(f, text=f"    {sub}", fg=t["muted"], bg=t["bg"],
                     font=("Segoe UI", 9)).pack(anchor="w")

        def confirm():
            self.routing_mode = choice.get()
            dlg.destroy()

        tk.Button(
            dlg, text="Continue →", command=confirm,
            fg="#fff", bg=t["accent"], activebackground=t["accent"],
            activeforeground="#fff", font=("Segoe UI", 10, "bold"),
            padx=18, pady=6, relief="flat", cursor="hand2",
        ).pack(pady=20)
        dlg.protocol("WM_DELETE_WINDOW", confirm)
        self.wait_window(dlg)

    # ════════════════════════ ttk theme ═══════════════════════════════════════
    def _setup_ttk_theme(self):
        try:
            style = ttk.Style(self)
            style.theme_use("clam")
            t = self.THEME
            style.configure(
                "Treeview", background=t["card"], foreground=t["text"],
                fieldbackground=t["card"],
            )
            style.configure("Treeview.Heading", background=t["sidebar"], foreground=t["text"])
            style.map("Treeview",
                      background=[("selected", t["accent"])],
                      foreground=[("selected", "#fff")])
            # Progress bar
            style.configure("Wizard.Horizontal.TProgressbar",
                             troughcolor=t["sidebar"], background=t["accent"], thickness=4)
        except Exception:
            pass

    # ════════════════════════ help popup ══════════════════════════════════════
    def _show_help(self, term: str):
        text = HELP_TEXT.get(term, f"No help available for '{term}'.")
        t = self.THEME
        win = tk.Toplevel(self)
        win.title(f"Help: {term}")
        win.geometry("460x210")
        win.resizable(True, True)
        win.transient(self)
        win.configure(bg=t["bg"])
        frm = tk.Frame(win, padx=16, pady=16, bg=t["bg"])
        frm.pack(fill="both", expand=True)
        tk.Label(frm, text=term, font=("Segoe UI", 12, "bold"),
                 fg=t["accent"], bg=t["bg"]).pack(anchor="w")
        tk.Label(frm, text=text, wraplength=420, justify="left",
                 fg=t["text"], bg=t["bg"], font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 0))
        tk.Button(frm, text="Got it", command=win.destroy,
                  fg="#fff", bg=t["accent"], relief="flat",
                  padx=12, pady=4).pack(pady=(14, 0))

    # ════════════════════════ suggestion banner ═══════════════════════════════
    def _show_suggestion_banner(self, parent: tk.Widget,
                                message: str,
                                on_accept=None) -> tk.Frame:
        """
        Renders a dismissable coloured suggestion strip at the top of `parent`.

        If `on_accept` is provided a [Use] button appears; it calls on_accept()
        then destroys the banner.  A [✕] button always dismisses without action.
        """
        t = self.THEME
        strip = tk.Frame(parent, bg="#1a3a5c", padx=10, pady=6)
        strip.pack(fill="x", pady=(0, 8))

        tk.Label(
            strip,
            text="💡  " + message,
            fg="#90c8f8", bg="#1a3a5c",
            font=("Segoe UI", 9), justify="left", wraplength=580,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        def dismiss():
            strip.destroy()

        if on_accept:
            tk.Button(
                strip, text="Use", command=lambda: (on_accept(), dismiss()),
                fg="#fff", bg=t["accent"], activebackground=t["accent"],
                activeforeground="#fff", font=("Segoe UI", 9, "bold"),
                padx=8, pady=2, relief="flat", cursor="hand2",
            ).pack(side="right", padx=(6, 2))

        tk.Button(
            strip, text="✕", command=dismiss,
            fg=t["muted"], bg="#1a3a5c", activebackground="#1a3a5c",
            activeforeground=t["text"], font=("Segoe UI", 9),
            padx=4, pady=2, relief="flat", cursor="hand2",
        ).pack(side="right")

        return strip

    # ════════════════════════ preset helpers ══════════════════════════════════
    def _auto_dhcp_from_routing(self, dns: str = "8.8.8.8") -> List[Dict]:
        """Derive one DHCP pool per routing entry. All fields auto-calculated."""
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
        """Derive routing entries from self.vlans using an IP scheme."""
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
        """
        Populate ALL data buckets from the named preset.
        Hostname always reflects the actual device name from GNS3.
        """
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
                     "ports": "Ethernet0/0-2" if self.device_role == "access" else "FastEthernet1/1-5"},
                    {"id": "20", "name": "Guest",
                     "ports": "Ethernet1/0-1" if self.device_role == "access" else "FastEthernet1/6-10"},
                ]
            if self.device_role == "router":
                self.router_interface = self.known_interfaces[0] if self.known_interfaces else "FastEthernet0/0"
                self.routing_entries = [
                    {"vlan": "10", "name": "Staff", "ip": "192.168.10.1", "mask": "255.255.255.0"},
                    {"vlan": "20", "name": "Guest", "ip": "192.168.20.1", "mask": "255.255.255.0"},
                ]
                self.dhcp_pools   = self._auto_dhcp_from_routing()
                self.static_routes = [{"network": "0.0.0.0", "mask": "0.0.0.0",
                                        "next-hop": "10.0.0.1", "description": "Default route to ISP"}]
                self.acl_rules = [
                    {"acl #": "101", "action": "permit", "source": "192.168.10.0",
                     "wildcard": "0.0.0.255", "remark": "Allow Staff"},
                    {"acl #": "101", "action": "deny",   "source": "192.168.20.0",
                     "wildcard": "0.0.0.255", "remark": "Block Guest from reaching Staff"},
                    {"acl #": "101", "action": "permit", "source": "any",
                     "wildcard": "",           "remark": "Permit all other"},
                ]
            elif self.device_role == "core" and self.routing_mode == "device":
                self.routing_entries = self._auto_routing_from_vlans()
                self.acl_rules = [
                    {"acl #": "10", "action": "permit", "source": "192.168.10.0",
                     "wildcard": "0.0.0.255", "remark": "Allow Staff"},
                ]
            if self.device_role == "access":
                self.uplinks = [{"ports": a_uplink, "mode": "trunk", "allowed vlans": "all"}]

        elif key == "school_lab":
            self.identity_data = {"hostname": dn, "domain": "school.edu", "enable": "EduPass456!"}
            if self.device_role in ("core", "access"):
                self.vlans = [
                    {"id": "10", "name": "Students",
                     "ports": "Ethernet0/0-2" if self.device_role == "access" else "FastEthernet1/1-5"},
                    {"id": "20", "name": "Teachers",
                     "ports": "Ethernet1/0-1" if self.device_role == "access" else "FastEthernet1/6-8"},
                    {"id": "30", "name": "Servers",
                     "ports": "Ethernet2/0"   if self.device_role == "access" else "FastEthernet1/9-10"},
                ]
            if self.device_role == "router":
                self.router_interface = self.known_interfaces[0] if self.known_interfaces else "FastEthernet0/0"
                self.routing_entries = [
                    {"vlan": "10", "name": "Students", "ip": "192.168.10.1", "mask": "255.255.255.0"},
                    {"vlan": "20", "name": "Teachers", "ip": "192.168.20.1", "mask": "255.255.255.0"},
                    {"vlan": "30", "name": "Servers",  "ip": "192.168.30.1", "mask": "255.255.255.0"},
                ]
                self.dhcp_pools   = self._auto_dhcp_from_routing()
                self.static_routes = [{"network": "0.0.0.0", "mask": "0.0.0.0",
                                        "next-hop": "10.0.0.1", "description": "Default route to ISP"}]
                self.acl_rules = [
                    {"acl #": "101", "action": "permit", "source": "192.168.20.0",
                     "wildcard": "0.0.0.255", "remark": "Allow Teachers full access"},
                    {"acl #": "101", "action": "deny",   "source": "192.168.10.0",
                     "wildcard": "0.0.0.255", "remark": "Block Students from Servers"},
                    {"acl #": "101", "action": "permit", "source": "any",
                     "wildcard": "",           "remark": "Permit all other"},
                ]
            elif self.device_role == "core" and self.routing_mode == "device":
                self.routing_entries = self._auto_routing_from_vlans()
                self.acl_rules = [
                    {"acl #": "10", "action": "permit", "source": "192.168.20.0",
                     "wildcard": "0.0.0.255", "remark": "Allow Teachers"},
                ]
            if self.device_role == "access":
                self.uplinks = [{"ports": a_uplink, "mode": "trunk", "allowed vlans": "all"}]

        else:  # minimal
            self.identity_data = {"hostname": dn, "domain": "", "enable": "ChangeMe123!"}
            if self.device_role in ("core", "access"):
                self.vlans = [{"id": "10", "name": "Default", "ports": a_ports}]
            if self.device_role == "router":
                self.router_interface = self.known_interfaces[0] if self.known_interfaces else "FastEthernet0/0"
                self.routing_entries  = [{"vlan": "10", "name": "Default",
                                           "ip": "192.168.10.1", "mask": "255.255.255.0"}]
                self.dhcp_pools = self._auto_dhcp_from_routing()
            elif self.device_role == "core" and self.routing_mode == "device":
                self.routing_entries = self._auto_routing_from_vlans()
            if self.device_role == "access":
                self.uplinks = [{"ports": a_uplink, "mode": "trunk", "allowed vlans": "all"}]

    def _quick_generate(self, key: str):
        """One-click: apply preset → write templates → close wizard."""
        self._apply_preset(key)
        if not self.identity_data.get("hostname"):
            self.identity_data["hostname"] = self.device_name
        if not self.identity_data.get("enable"):
            self.identity_data["enable"] = "ChangeMe123!"
        self._write_templates()
        self.destroy()

    def _apply_preset_and_next(self, key: str):
        """Apply preset and advance to step 2 so the user can review each step."""
        self._apply_preset(key)
        self.current_step = 1  # skip Welcome, go straight to Name & Lock
        self._render_step()

    # ════════════════════════ layout ══════════════════════════════════════════
    def _build_layout(self):
        t = self.THEME
        outer = tk.Frame(self, bg=t["bg"])
        outer.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        # ── sidebar ──
        sidebar = tk.Frame(outer, width=210, bg=t["sidebar"])
        sidebar.pack(side="left", fill="y", padx=(0, 10))
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Guided Setup",
                 font=("Segoe UI", 13, "bold"), fg=t["text"], bg=t["sidebar"]
                 ).pack(anchor="w", padx=12, pady=(14, 4))

        role_labels = {
            "router": "Router / Gateway",
            "core":   "Core Switch (L3)",
            "access": "Access Switch (L2)",
        }
        routing_note = "routes here" if self.routing_mode == "device" else "routing external"
        tk.Label(
            sidebar,
            text=f"{self.device_name}\n{role_labels.get(self.device_role,'')}\n{routing_note}",
            justify="left", fg=t["accent"], bg=t["sidebar"], font=("Segoe UI", 9),
        ).pack(anchor="w", padx=12, pady=(0, 10))

        self.listbox = tk.Listbox(
            sidebar, activestyle="none",
            bg=t["bg"], fg=t["text"],
            selectbackground=t["accent"], selectforeground="#fff",
            borderwidth=0, highlightthickness=0, font=("Segoe UI", 9),
        )
        self.listbox.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        for step in self.steps:
            self.listbox.insert("end", f"  {step.title}")
        self.listbox.select_set(0)

        # ── content ──
        self.content = tk.Frame(outer, bg=t["card"], relief="flat", bd=0)
        self.content.pack(side="left", fill="both", expand=True)

        # ── nav bar ──
        nav = tk.Frame(self, bg=t["bg"])
        nav.pack(fill="x", padx=10, pady=(4, 10))

        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(
            nav, variable=self.progress_var, maximum=1.0,
            mode="determinate", length=260,
            style="Wizard.Horizontal.TProgressbar",
        ).pack(side="left", padx=(0, 10))

        self.lbl_status = tk.Label(nav, text="", fg=t["muted"], bg=t["bg"], font=("Segoe UI", 9))
        self.lbl_status.pack(side="left")

        self.btn_back = tk.Button(
            nav, text="◀  Back", command=self.prev_step, state="disabled",
            fg=t["text"], bg=t["sidebar"],
            activebackground=t["card"], activeforeground=t["text"],
            padx=12, pady=5, relief="flat", cursor="hand2",
        )
        self.btn_back.pack(side="right", padx=(6, 0))

        self.btn_next = tk.Button(
            nav, text="Next  ▶", command=self.next_step,
            fg="#fff", bg=t["accent"],
            activebackground=t["accent"], activeforeground="#fff",
            font=("Segoe UI", 10, "bold"), padx=18, pady=5,
            relief="flat", cursor="hand2",
        )
        self.btn_next.pack(side="right")

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

        else:  # access
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
        t = self.THEME
        for child in self.content.winfo_children():
            child.destroy()

        step = self.steps[self.current_step]
        self.listbox.select_clear(0, "end")
        self.listbox.select_set(self.current_step)

        # Header
        hdr = tk.Frame(self.content, bg=t["card"], padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=step.title, font=("Segoe UI", 16, "bold"),
                 fg=t["text"], bg=t["card"]).pack(anchor="w")
        tk.Label(hdr, text=step.description, wraplength=700, justify="left",
                 fg=t["muted"], bg=t["card"]).pack(anchor="w", pady=(2, 0))
        tk.Frame(self.content, height=1, bg=t["border"]).pack(fill="x", padx=16, pady=(0, 6))

        body = tk.Frame(self.content, bg=t["card"])
        body.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        step.build_ui(self, body)
        self._update_nav()

    def _update_nav(self):
        n = len(self.steps)
        self.btn_back.config(state="normal" if self.current_step > 0 else "disabled")
        if self.current_step == n - 1:
            self.btn_next.config(text="Finish ✓")
        else:
            self.btn_next.config(text="Next  ▶")
        self.lbl_status.config(text=f"Step {self.current_step + 1} of {n}")
        self.progress_var.set((self.current_step + 1) / n)

    def next_step(self):
        if not self.steps[self.current_step].validate(self):
            return
        if self.current_step == len(self.steps) - 1:
            self._write_templates()
            self.destroy()
            return
        self.current_step += 1
        self._render_step()

    def prev_step(self):
        if self.current_step == 0:
            return
        self.current_step -= 1
        self._render_step()

    # ════════════════════════ UI building helpers ══════════════════════════════
    def _help_link(self, parent: tk.Widget, term: str) -> tk.Label:
        t = self.THEME
        lbl = tk.Label(parent, text=f"?  What is {term}?",
                       font=("Segoe UI", 9, "underline"),
                       fg=t["accent"], cursor="hand2", bg=t["card"])
        lbl.bind("<Button-1>", lambda _e: self._show_help(term))
        return lbl

    def _entry(self, parent: tk.Widget,
               textvariable=None, value: str = "", width: int = 20) -> tk.Entry:
        t = self.THEME
        e = tk.Entry(
            parent, textvariable=textvariable, width=width,
            bg=t["sidebar"], fg=t["text"], insertbackground=t["text"],
            relief="flat", highlightthickness=1,
            highlightcolor=t["accent"], highlightbackground=t["border"],
        )
        if value and textvariable is None:
            e.insert(0, value)
        return e

    def _lbl(self, parent: tk.Widget, text: str,
             muted: bool = False, bold: bool = False) -> tk.Label:
        t = self.THEME
        font = ("Segoe UI", 10, "bold") if bold else ("Segoe UI", 10)
        fg   = t["muted"] if muted else t["text"]
        return tk.Label(parent, text=text, fg=fg, bg=t["card"],
                        font=font, justify="left")

    def _section_hdr(self, parent: tk.Widget, cols: list) -> tk.Frame:
        """Render a column header bar. cols = list of (label, width) tuples."""
        t = self.THEME
        hdr = tk.Frame(parent, bg=t["border"])
        hdr.pack(fill="x", pady=(0, 2))
        for label, w in cols:
            tk.Label(hdr, text=label, width=w, anchor="w",
                     fg=t["muted"], bg=t["border"],
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=5, pady=3)
        return hdr

    def _card(self, parent: tk.Widget, padx: int = 10, pady: int = 8) -> tk.Frame:
        t = self.THEME
        f = tk.Frame(parent, bg=t["sidebar"], padx=padx, pady=pady)
        f.pack(fill="x", pady=4)
        return f

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Welcome
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_welcome(self, body):
        t = self.THEME

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

        self._lbl(body, blurb, muted=True).pack(anchor="w", pady=(0, 12))

        # ── Cross-device context summary banner ──
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
            self._show_suggestion_banner(
                body,
                f"Already configured in this project — {src}: {summary}. "
                "Smart suggestions will appear as you proceed.",
            )

        self._lbl(body, "One-click presets:", bold=True).pack(anchor="w", pady=(0, 6))

        for key, (name, desc) in PRESET_CATALOGUE.items():
            card = tk.Frame(body, bg=t["sidebar"], padx=14, pady=10, relief="flat")
            card.pack(fill="x", pady=4)

            left = tk.Frame(card, bg=t["sidebar"])
            left.pack(side="left", fill="both", expand=True)
            tk.Label(left, text=name, font=("Segoe UI", 11, "bold"),
                     fg=t["text"], bg=t["sidebar"]).pack(anchor="w")
            tk.Label(left, text=desc, font=("Segoe UI", 9),
                     fg=t["muted"], bg=t["sidebar"]).pack(anchor="w")

            right = tk.Frame(card, bg=t["sidebar"])
            right.pack(side="right")
            tk.Button(
                right, text="⚡  Generate Now",
                command=lambda k=key: self._quick_generate(k),
                fg="#fff", bg=t["accent"],
                activebackground=t["accent"], activeforeground="#fff",
                font=("Segoe UI", 9, "bold"), padx=12, pady=5,
                relief="flat", cursor="hand2",
            ).pack(side="left", padx=(0, 8))
            tk.Button(
                right, text="Customize →",
                command=lambda k=key: self._apply_preset_and_next(k),
                fg=t["text"], bg=t["card"],
                activebackground=t["border"], activeforeground=t["text"],
                font=("Segoe UI", 9), padx=12, pady=5,
                relief="flat", cursor="hand2",
            ).pack(side="left")

        self._lbl(body, "\nOr click  Next ▶  to start from scratch.", muted=True).pack(anchor="w", pady=(10, 0))

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Name & Lock
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_identity(self, body):
        t = self.THEME
        ctx = self.project_context

        # Pre-fill domain from context if not yet set
        current_domain = self.identity_data.get("domain", "") or ctx.get("domain", "")
        self._hn_var  = tk.StringVar(value=self.identity_data.get("hostname", self.device_name))
        self._dom_var = tk.StringVar(value=current_domain)
        self._pw_var  = tk.StringVar(value=self.identity_data.get("enable",   ""))

        # Password suggestion banner
        ctx_pw = ctx.get("enable_pw", "")
        if ctx_pw and not self._pw_var.get():
            def _use_pw():
                self._pw_var.set(ctx_pw)
            src = ctx.get("routing_source") or ctx.get("vlan_source") or "another device"
            self._show_suggestion_banner(
                body,
                f"Other devices use enable password from {src} — use the same for consistency?",
                on_accept=_use_pw,
            )

        def row(label, var, help_term=None, show_pw=False):
            f = tk.Frame(body, bg=t["card"])
            f.pack(fill="x", pady=6)
            tk.Label(f, text=label, width=34, anchor="w",
                     fg=t["text"], bg=t["card"]).pack(side="left")
            e = self._entry(f, textvariable=var, width=30)
            if show_pw:
                e.config(show="*")
            e.pack(side="left")
            if help_term:
                self._help_link(f, help_term).pack(side="left", padx=10)

        row("Device hostname  *", self._hn_var)
        row("Domain name  (optional)", self._dom_var)
        row("Admin (enable) password  *", self._pw_var, "Enable secret", show_pw=True)
        self._lbl(body, "\n* Required", muted=True).pack(anchor="w")

    def _validate_identity(self) -> bool:
        hn = self._hn_var.get().strip()
        pw = self._pw_var.get().strip()
        if not hn:
            messagebox.showerror("Required", "Enter a device name.", parent=self)
            return False
        if not pw:
            messagebox.showerror("Required", "Enter an admin password.", parent=self)
            return False
        self.identity_data = {
            "hostname": hn,
            "domain":   self._dom_var.get().strip(),
            "enable":   pw,
        }
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: VLANs  (core / access)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_vlans(self, body):
        t   = self.THEME
        ctx = self.project_context

        # ── Auto-fill VLANs from context if none set yet ──
        if ctx.get("vlans") and not self.vlans:
            def _use_ctx_vlans():
                self.vlans = [
                    {"id": v["id"], "name": v["name"], "ports": ""}
                    for v in ctx["vlans"]
                ]
                self.vlan_count_var.set(len(self.vlans))
                # trigger rebuild happens via trace
            src = ctx.get("vlan_source") or ctx.get("routing_source") or "another device"
            vnames = ", ".join(f"{v['name']} {v['id']}" for v in ctx["vlans"][:3])
            self._show_suggestion_banner(
                body,
                f"Found {len(ctx['vlans'])} VLANs from {src} ({vnames}). "
                "Port assignments will be auto-set for this device.",
                on_accept=_use_ctx_vlans,
            )
            # Silently pre-load so the user just has to hit Next
            self.vlans = [
                {"id": v["id"], "name": v["name"], "ports": ""}
                for v in ctx["vlans"]
            ]

        top = tk.Frame(body, bg=t["card"])
        top.pack(fill="x", pady=(0, 10))
        self._help_link(top, "VLAN").pack(side="left")

        cnt_f = tk.Frame(body, bg=t["card"])
        cnt_f.pack(anchor="w", pady=(0, 10))
        self._lbl(cnt_f, "How many VLANs do you need?").pack(side="left")
        self.vlan_count_var = tk.IntVar(value=max(2, len(self.vlans)))
        tk.Spinbox(
            cnt_f, from_=1, to=12, textvariable=self.vlan_count_var,
            width=4, bg=t["sidebar"], fg=t["text"],
            buttonbackground=t["sidebar"], relief="flat",
        ).pack(side="left", padx=8)
        self._lbl(cnt_f, "(ports are auto-assigned — just set the names)", muted=True).pack(side="left")

        # ── Column headers: extra "Assign Ports" column only for access/core ──
        has_picker = bool(self.known_interfaces) and self.device_role in ("access", "core")
        cols = [("VLAN ID", 9), ("Name", 22)]
        if has_picker:
            cols.append(("Assign Ports (optional)", 34))
        else:
            cols.append(("Ports  (e.g. Et0/0-3)", 30))
        self._section_hdr(body, cols)

        rows_frame = tk.Frame(body, bg=t["card"])
        rows_frame.pack(fill="both", expand=True)
        self.vlan_rows_frame  = rows_frame
        self.vlan_row_entries = []

        def _open_port_picker(ports_var: tk.StringVar, btn: tk.Button, row_idx: int):
            """Pop a small floating window with one checkbox per interface."""
            popup = tk.Toplevel(self)
            popup.title("Select ports")
            popup.configure(bg=t["sidebar"])
            popup.resizable(False, False)
            popup.transient(self)
            popup.grab_set()

            tk.Label(popup, text="Tick the ports for this VLAN:",
                     fg=t["muted"], bg=t["sidebar"],
                     font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(10, 4))

            # Determine which ports are already assigned to OTHER VLANs
            already_used: set = set()
            for j, (_, _, pv) in enumerate(self.vlan_row_entries):
                if j != row_idx:
                    for p in pv.get().replace(",", " ").split():
                        already_used.add(p.strip())

            # Current selection for THIS row
            current = set(ports_var.get().replace(",", " ").split())

            check_vars: dict = {}
            for iface in self.known_interfaces:
                var = tk.BooleanVar(value=(iface in current))
                row = tk.Frame(popup, bg=t["sidebar"])
                row.pack(fill="x", padx=12, pady=1)
                state = "normal"
                label_extra = ""
                if iface in already_used and iface not in current:
                    state   = "disabled"
                    label_extra = "  (used)"
                tk.Checkbutton(
                    row, variable=var,
                    bg=t["sidebar"], activebackground=t["sidebar"],
                    selectcolor=t["card"], state=state,
                ).pack(side="left")
                tk.Label(
                    row,
                    text=iface + label_extra,
                    fg=t["muted"] if state == "disabled" else t["text"],
                    bg=t["sidebar"], font=("Segoe UI", 9),
                ).pack(side="left")
                check_vars[iface] = var

            def _apply():
                selected = [iface for iface, v in check_vars.items() if v.get()]
                ports_var.set(",".join(selected) if selected else "auto")
                btn.config(text=_btn_label(ports_var.get()))
                popup.destroy()

            tk.Button(
                popup, text="Apply",
                command=_apply,
                fg="#fff", bg=t["accent"],
                activebackground=t["accent"], activeforeground="#fff",
                font=("Segoe UI", 9, "bold"), padx=14, pady=4,
                relief="flat", cursor="hand2",
            ).pack(pady=(8, 10))

        def _btn_label(val: str) -> str:
            if not val or val == "auto":
                return "Auto-assign  ▾"
            parts = val.split(",")
            if len(parts) <= 2:
                return f"{val}  ▾"
            return f"{parts[0]}, +{len(parts)-1} more  ▾"

        def rebuild(*_):
            for w in self.vlan_rows_frame.winfo_children():
                w.destroy()
            self.vlan_row_entries.clear()
            try:
                count = int(self.vlan_count_var.get())
            except Exception:
                count = 2
            for i in range(count):
                ex    = self.vlans[i] if i < len(self.vlans) else {}
                vid   = ex.get("id",    str((i + 1) * 10))
                vname = ex.get("name",  f"VLAN{vid}")
                vport = ex.get("ports", self._auto_ports(i))

                bg = t["row_alt"] if i % 2 else t["card"]
                rf = tk.Frame(self.vlan_rows_frame, bg=bg)
                rf.pack(fill="x", pady=1)

                id_v    = tk.StringVar(value=vid)
                name_v  = tk.StringVar(value=vname)
                ports_v = tk.StringVar(value=vport)

                self._entry(rf, textvariable=id_v,   width=9).pack(side="left", padx=5, pady=3)
                self._entry(rf, textvariable=name_v, width=22).pack(side="left", padx=5)

                if has_picker:
                    # Dropdown-style button that opens port picker
                    btn = tk.Button(
                        rf,
                        text=_btn_label(vport),
                        fg=t["text"], bg=t["sidebar"],
                        activebackground=t["card"], activeforeground=t["text"],
                        font=("Segoe UI", 9), width=30,
                        relief="flat", cursor="hand2", anchor="w",
                    )
                    btn.config(command=lambda pv=ports_v, b=btn, idx=i: _open_port_picker(pv, b, idx))
                    btn.pack(side="left", padx=5)
                else:
                    self._entry(rf, textvariable=ports_v, width=30).pack(side="left", padx=5)

                self.vlan_row_entries.append((id_v, name_v, ports_v))

        self.vlan_count_var.trace_add("write", rebuild)
        rebuild()

        if has_picker:
            self._lbl(body, "Tip: Click each row's port button to pick specific ports, or leave as 'Auto-assign'.",
                      muted=True).pack(anchor="w", pady=(6, 0))

    def _auto_ports(self, idx: int) -> str:
        if self.known_interfaces:
            total = len(self.known_interfaces)
            try:
                n_vlans = int(self.vlan_count_var.get())
            except Exception:
                n_vlans = 2
            n_vlans = max(1, n_vlans)
            per_vlan = max(1, total // n_vlans)
            start_i = idx * per_vlan
            end_i   = min(start_i + per_vlan - 1, total - 1)
            first = self.known_interfaces[start_i]
            last  = self.known_interfaces[end_i]
            if first == last:
                return first
            # Compact range notation: Ethernet0/0-3
            prefix = first.rsplit("/", 1)[0]
            return f"{prefix}/{first.rsplit('/', 1)[1]}-{last.rsplit('/', 1)[1]}"
        # Fallback when no GNS3 interface data is available
        if self.device_role == "access":
            return f"Ethernet{idx}/0-3"
        start = idx * 4 + 1
        return f"FastEthernet1/{start}-{start + 3}"

    def _validate_vlans(self) -> bool:
        self.vlans = []
        for id_v, name_v, ports_v in self.vlan_row_entries:
            vid   = id_v.get().strip()
            vname = name_v.get().strip()
            vport = ports_v.get().strip()
            if not vid:
                continue
            try:
                n = int(vid)
                if not (1 <= n <= 4094):
                    raise ValueError
            except Exception:
                messagebox.showerror("Invalid VLAN ID",
                                     f"VLAN ID must be 1–4094. Got: {vid!r}", parent=self)
                return False
            self.vlans.append({"id": vid, "name": vname or f"VLAN{vid}", "ports": vport})
        if not self.vlans:
            messagebox.showerror("Required", "Add at least one VLAN.", parent=self)
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Gateways / SVIs  (core switch)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_routing(self, body):
        t   = self.THEME
        ctx = self.project_context

        if self.routing_mode != "device":
            self._lbl(body,
                      "Routing is handled on a separate device — nothing to configure here.",
                      muted=True).pack(anchor="w", pady=20)
            return

        top = tk.Frame(body, bg=t["card"])
        top.pack(fill="x", pady=(0, 10))
        self._help_link(top, "SVI").pack(side="left")

        # ── Context banner for SVI/routing ──
        if ctx.get("routing_entries") and not self.routing_entries:
            src = ctx.get("routing_source") or "another device"
            def _use_ctx_svi():
                self.routing_entries = list(ctx["routing_entries"])
            self._show_suggestion_banner(
                body,
                f"Matched {src} subinterface IPs — SVIs will mirror the router's gateway addresses.",
                on_accept=_use_ctx_svi,
            )
            self.routing_entries = list(ctx["routing_entries"])

        self._lbl(body, "IP addressing scheme", bold=True).pack(anchor="w", pady=(0, 4))
        scheme_f = tk.Frame(body, bg=t["card"])
        scheme_f.pack(anchor="w", pady=(0, 12))
        self._lbl(scheme_f, "First two octets:").pack(side="left")
        default_scheme = ctx.get("ip_scheme", "192.168")
        self.ip_scheme_var = tk.StringVar(value=default_scheme)
        self._entry(scheme_f, textvariable=self.ip_scheme_var, width=12).pack(side="left", padx=8)
        self._lbl(scheme_f, ".VLANID.1   (e.g. VLAN 10 → 192.168.10.1 / 24)", muted=True).pack(side="left")

        self._lbl(body, "Auto-generated gateways — edit any IP if needed:", muted=True).pack(anchor="w", pady=(4, 2))
        self._section_hdr(body, [("VLAN ID", 10), ("Name", 18), ("Gateway IP", 18), ("Subnet Mask", 16)])

        rows_frame = tk.Frame(body, bg=t["card"])
        rows_frame.pack(fill="x")
        self.routing_rows_frame  = rows_frame
        self.routing_row_entries = []

        def rebuild(*_):
            for w in self.routing_rows_frame.winfo_children():
                w.destroy()
            self.routing_row_entries.clear()
            scheme = self.ip_scheme_var.get().strip()
            for i, vlan in enumerate(self.vlans):
                vid   = vlan.get("id", "10")
                vname = vlan.get("name", f"VLAN{vid}")
                ex_ip = next((r.get("ip","") for r in self.routing_entries
                              if str(r.get("vlan","")) == str(vid)), "")
                auto_ip = ex_ip or f"{scheme}.{vid}.1"
                bg = t["row_alt"] if i % 2 else t["card"]
                rf = tk.Frame(self.routing_rows_frame, bg=bg)
                rf.pack(fill="x", pady=1)
                ip_v   = tk.StringVar(value=auto_ip)
                mask_v = tk.StringVar(value="255.255.255.0")
                tk.Label(rf, text=vid,   width=10, anchor="w",
                         fg=t["text"],  bg=bg).pack(side="left", padx=5, pady=3)
                tk.Label(rf, text=vname, width=18, anchor="w",
                         fg=t["muted"], bg=bg).pack(side="left", padx=5)
                self._entry(rf, textvariable=ip_v,   width=18).pack(side="left", padx=5)
                self._entry(rf, textvariable=mask_v, width=16).pack(side="left", padx=5)
                self.routing_row_entries.append((vid, vname, ip_v, mask_v))

        self.ip_scheme_var.trace_add("write", lambda *_: body.after_idle(rebuild))
        rebuild()

    def _validate_routing(self) -> bool:
        if self.routing_mode != "device":
            self.routing_entries = []
            return True
        self.routing_entries = [
            {"vlan": vid, "name": vname, "ip": ip_v.get().strip(), "mask": mask_v.get().strip()}
            for vid, vname, ip_v, mask_v in self.routing_row_entries
            if ip_v.get().strip()
        ]
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Router subinterfaces  (router)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_router_subinterfaces(self, body):
        t   = self.THEME
        ctx = self.project_context

        top = tk.Frame(body, bg=t["card"])
        top.pack(fill="x", pady=(0, 10))
        self._help_link(top, "Subinterface").pack(side="left")

        # ── Context banner for subinterfaces ──
        if ctx.get("routing_entries") and not self.routing_entries:
            src = ctx.get("routing_source") or "another device"
            def _use_ctx_routing():
                self.routing_entries = list(ctx["routing_entries"])
                self.vlans = [{"id": r["vlan"], "name": r["name"], "ports": ""} for r in self.routing_entries]
            self._show_suggestion_banner(
                body,
                f"Matched SVIs from {src} — subinterface IPs are consistent with the rest of the network.",
                on_accept=_use_ctx_routing,
            )
            # Silently pre-load
            self.routing_entries = list(ctx["routing_entries"])
            self.vlans = [{"id": r["vlan"], "name": r["name"], "ports": ""} for r in self.routing_entries]
        elif ctx.get("vlans") and not self.routing_entries:
            src = ctx.get("vlan_source") or "another device"
            self._show_suggestion_banner(
                body,
                f"Found VLAN database from {src} — generating matching subinterface IPs.",
            )
            if not self.vlans:
                self.vlans = [{"id": v["id"], "name": v["name"], "ports": ""} for v in ctx["vlans"]]

        # ── physical interface ──
        iface_f = tk.Frame(body, bg=t["card"])
        iface_f.pack(fill="x", pady=(0, 8))
        tk.Label(iface_f, text="Interface connected to the switch:",
                 width=36, anchor="w", fg=t["text"], bg=t["card"]).pack(side="left")
        _fallback_ifaces = [
            "FastEthernet0/0",
            "GigabitEthernet1/0", "GigabitEthernet2/0", "GigabitEthernet3/0",
            "GigabitEthernet4/0", "GigabitEthernet5/0",
            "Serial6/0",          "Serial6/1",
            "Serial6/2",          "Serial6/3",
        ]
        ifaces = self.known_interfaces if self.known_interfaces else _fallback_ifaces
        default_iface = (
            self.router_interface
            or (self.known_interfaces[0] if self.known_interfaces else "FastEthernet0/0")
        )
        self.router_interface_var = tk.StringVar(value=default_iface)
        ttk.Combobox(
            iface_f, textvariable=self.router_interface_var,
            values=ifaces, state="readonly", width=26,
        ).pack(side="left", padx=6)

        # ── VLAN count (routers have no prior VLAN step) ──
        source_vlans = self.vlans  # may be empty for a router

        cnt_row = None
        if not source_vlans:
            cnt_row = tk.Frame(body, bg=t["card"])
            cnt_row.pack(anchor="w", fill="x", pady=(0, 8))
            self._lbl(cnt_row, "How many VLANs to route?").pack(side="left")
            self.sub_count_var = tk.IntVar(value=max(2, len(self.routing_entries)))
            tk.Spinbox(
                cnt_row, from_=1, to=12, textvariable=self.sub_count_var,
                width=4, bg=t["sidebar"], fg=t["text"], relief="flat",
            ).pack(side="left", padx=8)
        else:
            self.sub_count_var = None

        # ── IP scheme — derive from context if available ──
        scheme_f = tk.Frame(body, bg=t["card"])
        scheme_f.pack(fill="x", pady=(0, 10))
        tk.Label(scheme_f, text="IP scheme (first two octets):",
                 width=36, anchor="w", fg=t["text"], bg=t["card"]).pack(side="left")
        default_scheme = ctx.get("ip_scheme", "192.168")
        self.ip_scheme_var = tk.StringVar(value=default_scheme)
        self._entry(scheme_f, textvariable=self.ip_scheme_var, width=12).pack(side="left", padx=6)
        self._lbl(scheme_f, ".VLANID.1/24", muted=True).pack(side="left")

        self._lbl(body, "Subinterface gateways — edit any IP if needed:", muted=True).pack(anchor="w", pady=(4, 2))
        self._section_hdr(body, [("VLAN ID", 10), ("Name", 18), ("Gateway IP", 18), ("Mask", 16)])

        rows_frame = tk.Frame(body, bg=t["card"])
        rows_frame.pack(fill="x")
        self.routing_rows_frame  = rows_frame
        self.routing_row_entries = []

        def get_vlans():
            if source_vlans:
                return source_vlans
            try:
                count = int(self.sub_count_var.get())
            except Exception:
                count = 2
            return [{"id": str((i+1)*10), "name": f"VLAN{(i+1)*10}"} for i in range(count)]

        def rebuild(*_):
            for w in self.routing_rows_frame.winfo_children():
                w.destroy()
            self.routing_row_entries.clear()
            scheme = self.ip_scheme_var.get().strip()
            for i, vlan in enumerate(get_vlans()):
                vid   = vlan.get("id",   "10")
                vname = vlan.get("name", f"VLAN{vid}")
                ex_ip = next((r.get("ip","") for r in self.routing_entries
                              if str(r.get("vlan","")) == str(vid)), "")
                auto_ip = ex_ip or f"{scheme}.{vid}.1"
                bg = t["row_alt"] if i % 2 else t["card"]
                rf = tk.Frame(self.routing_rows_frame, bg=bg)
                rf.pack(fill="x", pady=1)
                id_v   = tk.StringVar(value=vid)
                name_v = tk.StringVar(value=vname)
                ip_v   = tk.StringVar(value=auto_ip)
                mask_v = tk.StringVar(value="255.255.255.0")
                self._entry(rf, textvariable=id_v,   width=10).pack(side="left", padx=5, pady=3)
                self._entry(rf, textvariable=name_v, width=18).pack(side="left", padx=5)
                self._entry(rf, textvariable=ip_v,   width=18).pack(side="left", padx=5)
                self._entry(rf, textvariable=mask_v, width=16).pack(side="left", padx=5)
                self.routing_row_entries.append((id_v, name_v, ip_v, mask_v))

        if self.sub_count_var:
            self.sub_count_var.trace_add("write", rebuild)
        self.ip_scheme_var.trace_add("write", lambda *_: body.after_idle(rebuild))
        rebuild()

    def _validate_router_subinterfaces(self) -> bool:
        self.router_interface = self.router_interface_var.get()
        self.routing_entries = []
        for id_v, name_v, ip_v, mask_v in self.routing_row_entries:
            vid  = id_v.get().strip()
            ip   = ip_v.get().strip()
            if vid and ip:
                self.routing_entries.append({
                    "vlan": vid,
                    "name": name_v.get().strip(),
                    "ip":   ip,
                    "mask": mask_v.get().strip() or "255.255.255.0",
                })
        if not self.routing_entries:
            messagebox.showerror("Required",
                                 "Add at least one VLAN / gateway row.", parent=self)
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: DHCP  (router)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_dhcp(self, body):
        t   = self.THEME
        ctx = self.project_context
        self._help_link(body, "DHCP pool").pack(anchor="w", pady=(0, 8))

        # ── Context banners for DHCP ──
        if ctx.get("dhcp_pools"):
            src = ctx.get("dhcp_source_device") or "another device"
            self._show_suggestion_banner(
                body,
                f"DHCP is already configured on {src}. "
                "All pools are unchecked below — enable only if this device should also serve DHCP.",
            )
        elif ctx.get("routing_entries"):
            src = ctx.get("routing_source") or "another device"
            self._show_suggestion_banner(
                body,
                f"Pool addresses match the {src} SVIs — gateway IPs are consistent with the network.",
            )

        self._lbl(
            body,
            "Tick the VLANs that should hand out IP addresses automatically.\n"
            "Network, gateway and range are all derived from your routing settings.",
            muted=True,
        ).pack(anchor="w", pady=(0, 10))

        # DNS
        dns_f = tk.Frame(body, bg=t["card"])
        dns_f.pack(anchor="w", fill="x", pady=(0, 12))
        self._lbl(dns_f, "DNS server:").pack(side="left")
        self.dhcp_dns_var = tk.StringVar(value="8.8.8.8")
        self._entry(dns_f, textvariable=self.dhcp_dns_var, width=16).pack(side="left", padx=8)
        self._lbl(dns_f, "(8.8.8.8 = Google, change if you have a local DNS)", muted=True).pack(side="left")

        if not self.routing_entries:
            self._lbl(body,
                      "No routing entries found.\n"
                      "Go back and complete the Subinterfaces step first.",
                      muted=True).pack(anchor="w", pady=10)
            return

        self._lbl(body, "Enable DHCP for:", bold=True).pack(anchor="w", pady=(0, 6))
        self.dhcp_check_vars = []

        for i, entry in enumerate(self.routing_entries):
            vid   = entry.get("vlan", "?")
            vname = entry.get("name", f"VLAN{vid}")
            gw    = entry.get("ip", "")
            p     = gw.split(".")
            if len(p) == 4:
                net   = f"{p[0]}.{p[1]}.{p[2]}.0"
                rng   = f"{p[0]}.{p[1]}.{p[2]}.50 – .200"
            else:
                net = rng = "n/a"

            bg = t["row_alt"] if i % 2 else t["sidebar"]
            rf = tk.Frame(body, bg=bg, padx=10, pady=8)
            rf.pack(fill="x", pady=2)

            # Default unchecked if another device already handles DHCP
            default_checked = not bool(ctx.get("dhcp_pools"))
            var = tk.BooleanVar(value=default_checked)
            tk.Checkbutton(
                rf, variable=var, bg=bg,
                activebackground=bg, selectcolor=t["card"],
            ).pack(side="left")
            tk.Label(rf, text=f"VLAN {vid}  ({vname})",
                     font=("Segoe UI", 10, "bold"),
                     fg=t["text"], bg=bg).pack(side="left", padx=(4, 14))
            tk.Label(rf,
                     text=f"network {net}  ·  gateway {gw}  ·  pool {rng}",
                     fg=t["muted"], bg=bg, font=("Segoe UI", 9)).pack(side="left")
            self.dhcp_check_vars.append((var, entry))

    def _validate_dhcp(self) -> bool:
        dns = getattr(self, "dhcp_dns_var", None)
        dns = dns.get().strip() if dns else "8.8.8.8"
        self.dhcp_pools = []
        for var, entry in self.dhcp_check_vars:
            if not var.get():
                continue
            gw   = entry.get("ip",   "")
            mask = entry.get("mask", "255.255.255.0")
            vid  = entry.get("vlan", "")
            name = entry.get("name", f"VLAN{vid}")
            p    = gw.split(".")
            if len(p) != 4:
                continue
            prefix = f"{p[0]}.{p[1]}.{p[2]}"
            self.dhcp_pools.append({
                "pool":    name,
                "network": f"{prefix}.0",
                "mask":    mask,
                "gateway": gw,
                "dns":     dns,
                "start":   f"{prefix}.50",
                "end":     f"{prefix}.200",
            })
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Static Routes  (router)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_static_routes(self, body):
        t   = self.THEME
        ctx = self.project_context

        # ── Context banner for static routes ──
        if ctx.get("isp_gateway"):
            src = ctx.get("routing_source") or "another device"
            self._show_suggestion_banner(
                body,
                f"Using the same ISP gateway as {src} ({ctx['isp_gateway']}).",
            )

        # For core switch: suggest default route toward the router's IP
        if self.device_role == "core" and ctx.get("routing_entries") and not ctx.get("isp_gateway"):
            router_ip = ctx["routing_entries"][0].get("ip", "")
            if router_ip:
                src = ctx.get("routing_source") or "the router"
                self._show_suggestion_banner(
                    body,
                    f"Suggested default route through {src} ({router_ip}).",
                )

        self._lbl(
            body,
            "A default route sends internet-bound traffic to your ISP or upstream router.\n"
            "This is required for devices to reach the internet.",
            muted=True,
        ).pack(anchor="w", pady=(0, 12))

        # Default route card
        def_card = self._card(body)
        self.default_route_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            def_card,
            text="Add a default route to the internet / upstream router",
            variable=self.default_route_var,
            font=("Segoe UI", 10, "bold"),
            fg=t["text"], bg=t["sidebar"],
            selectcolor=t["card"], activebackground=t["sidebar"],
            activeforeground=t["text"],
        ).pack(anchor="w")

        isp_f = tk.Frame(def_card, bg=t["sidebar"])
        isp_f.pack(anchor="w", pady=(6, 0))
        tk.Label(isp_f, text="ISP / upstream gateway IP:",
                 width=28, anchor="w", fg=t["text"], bg=t["sidebar"]).pack(side="left")
        # Pre-fill from context or existing data
        existing_isp = self.static_routes[0].get("next-hop", "") if self.static_routes else ""
        if not existing_isp:
            if ctx.get("isp_gateway"):
                existing_isp = ctx["isp_gateway"]
            elif self.device_role == "core" and ctx.get("routing_entries"):
                existing_isp = ctx["routing_entries"][0].get("ip", "10.0.0.1")
            else:
                existing_isp = "10.0.0.1"
        self.isp_gw_var = tk.StringVar(value=existing_isp)
        self._entry(isp_f, textvariable=self.isp_gw_var, width=18).pack(side="left", padx=6)

        # Extra routes
        self._lbl(body, "Additional static routes:", bold=True).pack(anchor="w", pady=(14, 4))
        self.extra_routes_var = tk.BooleanVar(value=len(self.static_routes) > 1)
        tk.Checkbutton(
            body, text="I need more static routes (advanced)",
            variable=self.extra_routes_var,
            fg=t["text"], bg=t["card"],
            selectcolor=t["sidebar"], activebackground=t["card"],
        ).pack(anchor="w")

        extra_frame = tk.Frame(body, bg=t["card"])
        extra_frame.pack(fill="x", pady=(4, 0))
        self.extra_route_rows = []

        def toggle_extra(*_):
            for w in extra_frame.winfo_children():
                w.destroy()
            self.extra_route_rows.clear()
            if not self.extra_routes_var.get():
                return
            self._section_hdr(extra_frame,
                               [("Network", 16), ("Mask", 14), ("Next-Hop", 16), ("Note", 20)])
            existing = self.static_routes[1:] if len(self.static_routes) > 1 else [{}]
            for ex in existing:
                self._add_route_row(extra_frame, ex)

            tk.Button(
                extra_frame, text="+ Add route",
                command=lambda: self._add_route_row(extra_frame, {}),
                fg=t["accent"], bg=t["card"], relief="flat", cursor="hand2",
            ).pack(anchor="w", pady=4)

        def _add_route_row(frame, ex):
            rf = tk.Frame(frame, bg=t["card"])
            rf.pack(fill="x", pady=2)
            net_v  = tk.StringVar(value=ex.get("network",     ""))
            mask_v = tk.StringVar(value=ex.get("mask",        "255.255.255.0"))
            nh_v   = tk.StringVar(value=ex.get("next-hop",    ""))
            desc_v = tk.StringVar(value=ex.get("description", ""))
            self._entry(rf, textvariable=net_v,  width=16).pack(side="left", padx=4)
            self._entry(rf, textvariable=mask_v, width=14).pack(side="left", padx=4)
            self._entry(rf, textvariable=nh_v,   width=16).pack(side="left", padx=4)
            self._entry(rf, textvariable=desc_v, width=20).pack(side="left", padx=4)
            self.extra_route_rows.append((net_v, mask_v, nh_v, desc_v))

        self._add_route_row = _add_route_row
        self.extra_routes_var.trace_add("write", toggle_extra)
        toggle_extra()

    def _validate_static_routes(self) -> bool:
        self.static_routes = []
        if getattr(self, "default_route_var", None) and self.default_route_var.get():
            isp = getattr(self, "isp_gw_var", None)
            isp = isp.get().strip() if isp else "10.0.0.1"
            if isp:
                self.static_routes.append({
                    "network": "0.0.0.0", "mask": "0.0.0.0",
                    "next-hop": isp, "description": "Default route to ISP",
                })
        for net_v, mask_v, nh_v, desc_v in self.extra_route_rows:
            net = net_v.get().strip()
            nh  = nh_v.get().strip()
            if net and nh:
                self.static_routes.append({
                    "network":     net,
                    "mask":        mask_v.get().strip() or "255.255.255.0",
                    "next-hop":    nh,
                    "description": desc_v.get().strip(),
                })
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: RIPv2  (router)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_rip(self, body):
        t   = self.THEME
        ctx = self.project_context

        # ── Context banner for RIP ──
        if ctx.get("rip_enabled") and not self.enable_rip:
            src = ctx.get("routing_source") or "another device"
            self._show_suggestion_banner(
                body,
                f"RIP is already enabled on {src} — enabling here keeps your routing protocol consistent.",
            )
            self.enable_rip = True

        self._lbl(
            body,
            "RIPv2 shares routes automatically with neighbouring routers.\n"
            "Enable this only when you have multiple routers that need to discover "
            "each other's networks automatically.",
            muted=True,
        ).pack(anchor="w", pady=(0, 12))

        card = self._card(body)
        self.enable_rip_var = tk.BooleanVar(value=self.enable_rip)
        tk.Checkbutton(
            card,
            text="Enable RIPv2 and advertise all connected networks",
            variable=self.enable_rip_var,
            font=("Segoe UI", 10, "bold"),
            fg=t["text"], bg=t["sidebar"],
            selectcolor=t["card"], activebackground=t["sidebar"],
            activeforeground=t["text"],
        ).pack(anchor="w")
        self._lbl(card,
                  "  All networks from the Subinterfaces step will be advertised automatically.",
                  muted=True).pack(anchor="w", pady=(4, 0))

    def _validate_rip(self) -> bool:
        rip_var = getattr(self, "enable_rip_var", None)
        self.enable_rip    = rip_var.get() if rip_var else False
        self.rip_networks  = []  # auto-derived from routing_entries in renderer
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Uplinks  (access switch)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_uplinks(self, body):
        t   = self.THEME
        ctx = self.project_context

        top = tk.Frame(body, bg=t["card"])
        top.pack(fill="x", pady=(0, 8))
        self._help_link(top, "Trunk").pack(side="left")

        # ── Context banner for uplinks ──
        ctx_vlan_ids = ",".join(v["id"] for v in ctx["vlans"]) if ctx.get("vlans") else ""
        if ctx_vlan_ids:
            src = ctx.get("vlan_source") or ctx.get("routing_source") or "another device"
            self._show_suggestion_banner(
                body,
                f"Trunk will carry VLANs {ctx_vlan_ids} (matched from {src}).",
            )

        self._lbl(
            body,
            "The uplink port connects this switch to the router or core switch.\n"
            "It carries all VLAN traffic in trunk mode.",
            muted=True,
        ).pack(anchor="w", pady=(0, 12))

        default_port = "Ethernet3/3" if self.device_role == "access" else "FastEthernet1/0"
        ex0 = self.uplinks[0] if self.uplinks else {}

        # Primary uplink
        primary = self._card(body)
        tk.Label(primary, text="Primary uplink port:", width=24, anchor="w",
                 fg=t["text"], bg=t["sidebar"]).pack(side="left")
        self.uplink_port_var = tk.StringVar(value=ex0.get("ports", default_port))
        self._entry(primary, textvariable=self.uplink_port_var, width=22).pack(side="left", padx=6)

        allowed_f = tk.Frame(body, bg=t["card"])
        allowed_f.pack(fill="x", pady=(0, 10))
        tk.Label(allowed_f, text="Allowed VLANs on this trunk:", width=30, anchor="w",
                 fg=t["text"], bg=t["card"]).pack(side="left")
        # Use context VLANs if available, otherwise fall back to existing or "all"
        default_allowed = ex0.get("allowed vlans") or ctx_vlan_ids or "all"
        self.uplink_vlans_var = tk.StringVar(value=default_allowed)
        self._entry(allowed_f, textvariable=self.uplink_vlans_var, width=22).pack(side="left", padx=6)
        self._lbl(allowed_f, "(e.g. 10,20  or  all)", muted=True).pack(side="left")

        # Optional second uplink
        self._lbl(body, "Second uplink port (optional):", bold=True).pack(anchor="w", pady=(8, 4))
        ex1 = self.uplinks[1] if len(self.uplinks) > 1 else {}
        sec_f = tk.Frame(body, bg=t["card"])
        sec_f.pack(anchor="w", fill="x")
        tk.Label(sec_f, text="Port:", width=8, anchor="w",
                 fg=t["text"], bg=t["card"]).pack(side="left")
        self.uplink2_port_var = tk.StringVar(value=ex1.get("ports", ""))
        self._entry(sec_f, textvariable=self.uplink2_port_var, width=22).pack(side="left", padx=6)
        self._lbl(sec_f, "(leave blank if not needed)", muted=True).pack(side="left")

    def _validate_uplinks(self) -> bool:
        self.uplinks = []
        port = getattr(self, "uplink_port_var", None)
        port = port.get().strip() if port else ""
        if port:
            allowed = getattr(self, "uplink_vlans_var", None)
            allowed = allowed.get().strip() if allowed else "all"
            self.uplinks.append({"ports": port, "mode": "trunk", "allowed vlans": allowed})
        port2 = getattr(self, "uplink2_port_var", None)
        port2 = port2.get().strip() if port2 else ""
        if port2:
            self.uplinks.append({"ports": port2, "mode": "trunk",
                                  "allowed vlans": allowed if self.uplinks else "all"})
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Access Rules  (router / core)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_acl(self, body):
        self._help_link(body, "ACL").pack(anchor="w", pady=(0, 8))
        ctx = self.project_context
        if ctx.get("routing_entries") or ctx.get("vlans"):
            src = ctx.get("routing_source") or ctx.get("vlan_source") or "another device"
            self._show_suggestion_banner(
                body,
                f"ACL rules are generated from the network's VLAN subnets (matched from {src}).",
            )
        self._build_acl_scenarios(body, context="gateway")

    def _build_step_acl_access(self, body):
        t = self.THEME
        self._lbl(
            body,
            "Optional — lightweight per-switch filtering.\n"
            "Gateway ACLs on your router or core switch are more effective for "
            "inter-VLAN rules.",
            muted=True,
        ).pack(anchor="w", pady=(0, 8))
        self._build_acl_scenarios(body, context="access")

    def _build_acl_scenarios(self, body, context: str):
        t = self.THEME

        # Build subnet map from routing entries
        subnets = []
        for e in self.routing_entries:
            vid  = e.get("vlan", "")
            name = e.get("name", f"VLAN{vid}")
            gw   = e.get("ip",   "")
            p    = gw.split(".")
            if len(p) == 4:
                subnets.append({
                    "vlan":     vid,
                    "name":     name,
                    "network":  f"{p[0]}.{p[1]}.{p[2]}.0",
                    "wildcard": "0.0.0.255",
                })

        self.acl_scenario_vars = []

        if not subnets:
            msg = (
                "No VLAN/routing data found — complete the routing step first.\n"
                "You can skip this step and add ACLs manually later."
                if context == "gateway"
                else "No ACL scenarios available for a pure L2 switch. Skip this step."
            )
            self._lbl(body, msg, muted=True).pack(anchor="w", pady=10)
            return

        self._lbl(body, "Tick the rules you want to apply:", bold=True).pack(anchor="w", pady=(0, 8))

        scenarios = []
        if context == "gateway" and len(subnets) >= 2:
            # Generate pairwise block scenarios
            for src in subnets:
                for dst in subnets:
                    if src["vlan"] == dst["vlan"]:
                        continue
                    # Default-check if source looks like an untrusted VLAN
                    trusted_keywords = ("staff", "admin", "teacher", "server", "mgmt")
                    untrusted_keywords = ("guest", "student", "visitor", "untrusted", "iot")
                    default_on = any(k in src["name"].lower() for k in untrusted_keywords)
                    scenarios.append((
                        f"Block  {src['name']} (VLAN {src['vlan']})  from accessing  "
                        f"{dst['name']} (VLAN {dst['vlan']})",
                        default_on, src, dst,
                    ))

        if context == "access":
            scenarios.append(("Permit all traffic from local VLANs (pass-through)", False, None, None))

        if not scenarios:
            self._lbl(body, "No scenarios available for this topology.", muted=True).pack(anchor="w")
            return

        for i, (label, default, src, dst) in enumerate(scenarios):
            bg = t["row_alt"] if i % 2 else t["sidebar"]
            rf = tk.Frame(body, bg=bg, padx=10, pady=6)
            rf.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=default)
            tk.Checkbutton(
                rf, text=label, variable=var,
                fg=t["text"], bg=bg,
                selectcolor=t["card"], activebackground=bg,
                activeforeground=t["text"],
                wraplength=620, justify="left",
                anchor="w",
            ).pack(anchor="w")
            self.acl_scenario_vars.append((var, src, dst))

        self._lbl(body,
                  "\nNo applicable rule? Skip this step — ACLs can be added manually later.",
                  muted=True).pack(anchor="w", pady=(8, 0))

    def _validate_acl(self) -> bool:
        self.acl_rules = []
        acl_num = 101
        for var, src, dst in self.acl_scenario_vars:
            if not var.get() or not src:
                continue
            self.acl_rules.append({
                "acl #":    str(acl_num),
                "action":   "deny",
                "source":   src["network"],
                "wildcard": src["wildcard"],
                "remark":   f"Block {src['name']} from {dst['name']}" if dst else src["name"],
            })
        if self.acl_rules:
            # Always end with permit-all so we don't black-hole everything
            self.acl_rules.append({
                "acl #":    str(acl_num),
                "action":   "permit",
                "source":   "any",
                "wildcard": "",
                "remark":   "Permit all other traffic",
            })
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP: Summary & Save
    # ══════════════════════════════════════════════════════════════════════════
    def _build_step_summary(self, body):
        t = self.THEME

        top_bar = tk.Frame(body, bg=t["card"])
        top_bar.pack(fill="x", pady=(0, 6))
        self._lbl(top_bar, "Generated configuration blocks (paste each one separately):").pack(side="left")
        tk.Button(
            top_bar, text="Copy All",
            command=self._copy_summary,
            fg="#fff", bg=t["accent"],
            activebackground=t["accent"], activeforeground="#fff",
            relief="flat", padx=10, pady=3, cursor="hand2",
        ).pack(side="right")

        frm = tk.Frame(body, bg=t["card"])
        frm.pack(fill="both", expand=True)
        self.summary_box = tk.Text(
            frm, wrap="word",
            bg=t["sidebar"], fg=t["text"],
            insertbackground=t["text"],
            relief="flat", font=("Consolas", 9),
        )
        sb = ttk.Scrollbar(frm, command=self.summary_box.yview)
        self.summary_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.summary_box.pack(fill="both", expand=True)
        self._refresh_summary()

    def _copy_summary(self):
        if self.summary_box:
            text = self.summary_box.get("1.0", "end").strip()
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Copied", "Configuration copied to clipboard.", parent=self)

    def _validate_summary(self) -> bool:
        self._refresh_summary()
        return True

    # ════════════════════════ summary content ═════════════════════════════════
    def _refresh_summary(self):
        if not self.summary_box:
            return
        self.summary_box.delete("1.0", "end")

        self.summary_box.insert("end",
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
            ("BLOCK 5 — Static Routes",             self._render_static_routes_block()),
            ("BLOCK 6 — RIPv2",                     self._render_rip_block()),
            ("BLOCK 7 — DHCP Pools",                self._render_dhcp_block()),
            ("BLOCK 8 — Access Control Lists",      self._render_acl_block()),
        ]

        inserted = False
        for title, block in blocks:
            if not block.strip():
                continue
            self.summary_box.insert("end", f"! {'='*52}\n! {title}\n! {'='*52}\n")
            self.summary_box.insert("end", block.strip() + "\n\n")
            self.summary_box.insert("end", f"! {'─'*52}\n! Block done — wait for prompt.\n\n\n")
            inserted = True

        if not inserted:
            self.summary_box.insert("end",
                "Nothing generated yet — go back and complete the earlier steps.\n")
        else:
            self.summary_box.insert("end",
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
            "guided_static_routes": self._render_static_routes_block(),
            "guided_rip":           self._render_rip_block(),
            "guided_dhcp":          self._render_dhcp_block(),
            "guided_acl":           self._render_acl_block(),
        }
        for key, value in templates.items():
            if value.strip():
                self.device_model.set_template(key, value)

    def _cleanup_default_templates(self):
        """Remove any previous guided_* templates so old data never bleeds in."""
        for key in list(self.device_model.templates.keys()):
            if key.startswith("guided_"):
                del self.device_model.templates[key]

    # ════════════════════════ port range helper ════════════════════════════════
    def _expand_ports_to_list(self, ports: str) -> List[str]:
        """
        Expand 'Fa1/0-3, Fa1/5' → ['Fa1/0','Fa1/1','Fa1/2','Fa1/3','Fa1/5']
        Handles multi-segment ranges separated by commas.
        """
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
            tail   = part[slash + 1:]
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

    # ════════════════════════ block renderers ══════════════════════════════════
    def _render_identity_block(self) -> str:
        if not self.identity_data:
            return ""
        lines = ["configure terminal",
                 f"hostname {self.identity_data.get('hostname', self.device_name)}"]
        if self.identity_data.get("domain"):
            lines.append(f"ip domain-name {self.identity_data['domain']}")
        lines += [f"enable secret {self.identity_data.get('enable')}", "exit"]
        return "\n".join(lines)

    def _render_vlan_block(self) -> str:
        if self.device_role == "router" or not self.vlans:
            return ""
        lines = []
        old_syntax = (self.device_role == "core")
        if old_syntax:
            lines.append("vlan database")
            for v in self.vlans:
                name = v.get("name") or f"VLAN{v.get('id')}"
                lines.append(f"vlan {v.get('id')} name {name}")
            lines += ["exit", "!", "configure terminal"]
            for v in self.vlans:
                for iface in self._expand_ports_to_list(v.get("ports", "")):
                    lines += [f"interface {iface}", "switchport mode access",
                              f"switchport access vlan {v.get('id')}", "no shutdown", "exit"]
            lines.append("exit")
        else:
            lines.append("configure terminal")
            for v in self.vlans:
                name = v.get("name") or f"VLAN{v.get('id')}"
                lines += [f"vlan {v.get('id')}", f"name {name}", "exit"]
            lines.append("!")
            for v in self.vlans:
                for iface in self._expand_ports_to_list(v.get("ports", "")):
                    lines += [f"interface {iface}", "switchport mode access",
                              f"switchport access vlan {v.get('id')}", "no shutdown", "exit"]
            lines.append("exit")
        return "\n".join(lines)

    def _render_uplink_block(self) -> str:
        if not self.uplinks:
            return ""
        lines = ["configure terminal"]
        for link in self.uplinks:
            ports   = link.get("ports", "").strip()
            mode    = (link.get("mode") or "trunk").lower()
            allowed = link.get("allowed vlans", "all")
            if not ports:
                continue
            lines.append(f"interface {ports}")
            if mode == "trunk":
                if self.device_role in ("access", "core"):
                    lines.append("switchport trunk encapsulation dot1q")
                lines.append("switchport mode trunk")
                if allowed and allowed.lower() != "all":
                    lines.append(f"switchport trunk allowed vlan {allowed}")
            else:
                lines.append("switchport mode access")
                if allowed and allowed.lower() != "all":
                    lines.append(f"switchport access vlan {allowed}")
            lines.append("exit")
        lines.append("exit")
        return "\n".join(lines)

    def _render_routing_block(self) -> str:
        if self.routing_mode != "device" or not self.routing_entries:
            return ""
        if self.device_role == "router":
            return self._render_router_on_stick_block()
        # Core switch SVIs
        lines = ["configure terminal", "ip routing"]
        for e in self.routing_entries:
            vlan = e.get("vlan")
            ip   = e.get("ip")
            mask = e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface Vlan{vlan}", f"ip address {ip} {mask}",
                          "no shutdown", "exit"]
        lines.append("exit")
        return "\n".join(lines)

    def _render_router_on_stick_block(self) -> str:
        if not self.router_interface or not self.routing_entries:
            return ""
        lines = ["configure terminal",
                 f"interface {self.router_interface}", "no shutdown", "exit"]
        for e in self.routing_entries:
            vlan = e.get("vlan")
            ip   = e.get("ip")
            mask = e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface {self.router_interface}.{vlan}",
                          f"encapsulation dot1Q {vlan}",
                          f"ip address {ip} {mask}", "exit"]
        lines.append("exit")
        return "\n".join(lines)

    def _render_static_routes_block(self) -> str:
        if not self.static_routes:
            return ""
        lines = ["configure terminal"]
        for r in self.static_routes:
            net  = r.get("network")
            mask = r.get("mask")
            nh   = r.get("next-hop")
            desc = r.get("description", "")
            if not (net and nh):
                continue
            if desc:
                lines.append(f"! {desc}")
            lines.append(f"ip route {net} {mask} {nh}")
        lines.append("exit")
        return "\n".join(lines)

    def _render_rip_block(self) -> str:
        if not self.enable_rip:
            return ""
        lines = ["configure terminal", "router rip", "version 2", "no auto-summary"]
        seen = set()
        for e in self.routing_entries:
            ip = e.get("ip", "")
            p  = ip.split(".")
            if len(p) == 4:
                net = f"{p[0]}.{p[1]}.{p[2]}.0"
                if net not in seen:
                    seen.add(net)
                    lines.append(f"network {net}")
        lines += ["exit", "exit"]
        return "\n".join(lines)

    def _render_dhcp_block(self) -> str:
        if self.device_role == "access" or not self.dhcp_pools:
            return ""
        lines = ["configure terminal"]
        for pool in self.dhcp_pools:
            gw    = pool.get("gateway", "")
            start = pool.get("start",   "")
            end   = pool.get("end",     "")

            # Exclude: gateway → (start - 1)
            if gw and start:
                p = start.split(".")
                try:
                    s_last = int(p[3])
                    g_p    = gw.split(".")
                    pfx    = f"{g_p[0]}.{g_p[1]}.{g_p[2]}"
                    if s_last > 1:
                        lines.append(f"ip dhcp excluded-address {gw} {pfx}.{s_last - 1}")
                    else:
                        lines.append(f"ip dhcp excluded-address {gw}")
                except (IndexError, ValueError):
                    pass

            # Exclude: (end + 1) → 254
            if end:
                p = end.split(".")
                try:
                    e_last = int(p[3])
                    pfx    = f"{p[0]}.{p[1]}.{p[2]}"
                    if e_last < 254:
                        lines.append(f"ip dhcp excluded-address {pfx}.{e_last + 1} {pfx}.254")
                except (IndexError, ValueError):
                    pass

            lines.append(f"ip dhcp pool {pool.get('pool')}")
            lines.append(f"network {pool.get('network')} {pool.get('mask')}")
            if gw:
                lines.append(f"default-router {gw}")
            if pool.get("dns"):
                lines.append(f"dns-server {pool['dns']}")
            lines.append("exit")
        lines.append("exit")
        return "\n".join(lines)

    def _render_acl_block(self) -> str:
        if not self.acl_rules:
            return ""
        lines = ["configure terminal"]
        for rule in self.acl_rules:
            num    = rule.get("acl #", "101")
            action = rule.get("action", "permit")
            src    = rule.get("source", "any")
            wc     = rule.get("wildcard", "")
            remark = rule.get("remark",   "")
            if remark:
                lines.append(f"access-list {num} remark {remark}")
            if src.lower() == "any":
                lines.append(f"access-list {num} {action} any")
            else:
                lines.append(f"access-list {num} {action} {src} {wc}")
        lines.append("exit")
        return "\n".join(lines)

    # kept for any remaining callers
    def _get_show_vlan_command(self) -> str:
        return "show vlan-switch" if self.device_role == "core" else "show vlan brief"
