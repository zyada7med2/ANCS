"""
Real-time device health monitor — Network Operations Dashboard.

Two-tab layout
--------------
Fleet Overview : health-score cards for all devices, polled in parallel
Device Detail  : per-device deep diagnostics + change alerts + ad-hoc terminal

Commands per role
-----------------
Router      : show version | show ip interface brief | show interfaces
              | show ip route | show ip arp | show cdp neighbors
              | show ip dhcp binding
Core Switch : show version | show ip interface brief | show interfaces
              | show vlan brief | show vlan-switch | show cdp neighbors
              | show spanning-tree summary | show ip arp
Access Sw.  : show version | show ip interface brief | show interfaces
              | show vlan brief | show vlan-switch | show cdp neighbors
              | show spanning-tree
"""
from __future__ import annotations

import tkinter as tk
import threading
import asyncio
import queue
import re
import time
from typing import Optional

import base64

from .utils import apply_responsive_geometry
from ..config import conn, cur, db_lock

try:
    import telnetlib3
except Exception:
    telnetlib3 = None


def _deobfuscate(pw: str) -> str:
    """Decode a base64-stored password; falls back to plain text."""
    if not pw:
        return ""
    try:
        return base64.b64decode(pw.encode()).decode("utf-8")
    except Exception:
        return pw


def _load_device_creds(device_name: str, meta: dict) -> tuple:
    """Return (username, password, enable_pw) for a device.

    Priority: meta dict → credentials database table.
    """
    username  = meta.get("username", "")
    password  = meta.get("password", "")
    enable_pw = meta.get("enable_pw", "")

    if not (username and password):
        try:
            with db_lock:
                cur.execute(
                    "SELECT username, password, enable_password "
                    "FROM credentials WHERE device_name=?",
                    (device_name,),
                )
                row = cur.fetchone()
            if row:
                if not username and row[0]:
                    username = row[0]
                if not password and row[1]:
                    password = _deobfuscate(row[1])
                if not enable_pw and row[2]:
                    enable_pw = _deobfuscate(row[2])
        except Exception:
            pass

    return username, password, enable_pw


# ── Palette ───────────────────────────────────────────────────────────────────
_C = {
    "bg":      "#0D1117",
    "card":    "#1F2630",
    "sidebar": "#161B22",
    "text":    "#C9D1D9",
    "muted":   "#8B949E",
    "success": "#3FB950",
    "danger":  "#F85149",
    "warn":    "#D29922",
    "border":  "#30363D",
    "accent":  "#58A6FF",
    "row_alt": "#192028",
    "alert_danger":  "#2a1010",
    "alert_success": "#0f2a14",
    "alert_warn":    "#2a1f0a",
    "alert_accent":  "#0d1f3c",
}

_ROLE_ICONS = {"router": "R", "core": "C", "access": "S"}

_POLL_INTERVALS = {
    "10 s":  10_000,
    "30 s":  30_000,
    "60 s":  60_000,
    "5 min": 300_000,
}

_CMD_LABELS = {
    "show version":               "Device Info",
    "show ip interface brief":    "Network Interfaces",
    "show ip dhcp binding":       "DHCP Leases",
    "show vlan-switch":           "VLAN Membership",
    "show vlan brief":            "VLAN Membership",
    "show ip route":              "Routing Table",
    "show ip arp":                "ARP Table",
    "show cdp neighbors":         "CDP Neighbors",
    "show interfaces":            "Interface Error Counters",
    "show spanning-tree":         "Spanning Tree",
    "show spanning-tree summary": "Spanning Tree Summary",
}


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _is_invalid(raw: str) -> bool:
    return bool(re.search(
        r"(Invalid input|% Invalid|% Incomplete|% Ambiguous|% Unknown command)",
        raw, re.IGNORECASE
    ))


def _parse_iface_states(raw: str) -> dict:
    """Return {iface_name: 'up'/'down'} from show ip interface brief."""
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
    """Count interface blocks with any non-zero error counter."""
    count = 0
    pat = re.compile(
        r"(\d+) input errors|(\d+) output errors|(\d+) CRC|(\d+) output drops",
        re.IGNORECASE
    )
    for line in raw.splitlines():
        m = pat.search(line)
        if m:
            val = next((int(g) for g in m.groups() if g is not None), 0)
            if val > 0:
                count += 1
    return count


def _compute_health(data: dict, has_prev: bool = False) -> int:
    """Return a 0–100 health score."""
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
    if score >= 80:
        return _C["success"]
    elif score >= 50:
        return _C["warn"]
    return _C["danger"]


def _health_label(score: int) -> str:
    if score >= 80:
        return "Good"
    elif score >= 50:
        return "Warning"
    return "Critical"


def _detect_changes(new_data: dict, old_data: dict) -> list:
    """Return list of (level_key, message) tuples for notable state changes."""
    alerts = []
    if not old_data or not new_data or "_error" in new_data:
        return alerts

    new_st = _parse_iface_states(new_data.get("show ip interface brief", ""))
    old_st = _parse_iface_states(old_data.get("show ip interface brief", ""))
    for iface, ns in new_st.items():
        os_ = old_st.get(iface)
        if os_ and os_ != ns:
            if ns == "down":
                alerts.append(("danger",  f"  {iface} went DOWN since last poll"))
            else:
                alerts.append(("success", f"  {iface} came UP since last poll"))

    new_ips = _parse_dhcp_ips(new_data.get("show ip dhcp binding", ""))
    old_ips = _parse_dhcp_ips(old_data.get("show ip dhcp binding", ""))
    for ip in new_ips - old_ips:
        alerts.append(("accent", f"  New DHCP lease: {ip}"))
    for ip in old_ips - new_ips:
        alerts.append(("warn",   f"  DHCP lease expired: {ip}"))

    vlan_key = "show vlan brief"
    new_vl = _parse_vlan_ids(
        new_data.get(vlan_key, new_data.get("show vlan-switch", ""))
    )
    old_vl = _parse_vlan_ids(
        old_data.get(vlan_key, old_data.get("show vlan-switch", ""))
    )
    for v in old_vl - new_vl:
        alerts.append(("warn",   f"  VLAN {v} disappeared"))
    for v in new_vl - old_vl:
        alerts.append(("accent", f"  VLAN {v} appeared"))

    return alerts


# ── Main class ────────────────────────────────────────────────────────────────

class DeviceMonitor(tk.Toplevel):

    def __init__(self, parent, devices: list):
        super().__init__(parent)
        self.title("Device Monitor")
        self.resizable(True, True)
        apply_responsive_geometry(self, 1080, 700, min_w=800, min_h=500)
        self.configure(bg=_C["bg"])

        self.devices = [
            d for d in devices
            if d[2].get("console_host") or d[2].get("ip")
        ]
        self._selected_idx = 0
        self._poll_timer: Optional[str] = None
        self._result_queue: queue.Queue = queue.Queue()
        self._closed = False

        # State
        self._last_results: dict[str, dict] = {}
        self._fleet_card_widgets: dict[str, dict] = {}
        self._current_tab = "fleet"
        self._adhoc_history: list[str] = []
        self._adhoc_expanded = False
        self._active_polls: set[str] = set()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self.devices:
            self._show_placeholder("No devices with connection info found.\nImport GNS3 devices first.")
        else:
            self.after(400, self._poll_fleet)

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self, bg=_C["card"], pady=8)
        hdr.pack(fill="x")

        tk.Label(
            hdr, text="  Device Monitor",
            font=("TkDefaultFont", 13, "bold"), fg=_C["text"], bg=_C["card"]
        ).pack(side="left")

        # Status (right side, pack right-to-left)
        self.lbl_status = tk.Label(
            hdr, text="ready", fg=_C["muted"], bg=_C["card"],
            font=("TkDefaultFont", 10)
        )
        self.lbl_status.pack(side="right", padx=16)

        # Auto-poll interval
        self._interval_var = tk.StringVar(value="30 s")
        interval_menu = tk.OptionMenu(hdr, self._interval_var, *_POLL_INTERVALS.keys())
        interval_menu.configure(
            bg=_C["sidebar"], fg=_C["text"], relief="flat",
            highlightthickness=0, activebackground=_C["card"],
            activeforeground=_C["text"], font=("TkDefaultFont", 10),
        )
        interval_menu["menu"].configure(
            bg=_C["sidebar"], fg=_C["text"],
            activebackground=_C["accent"], activeforeground="white",
        )
        interval_menu.pack(side="right", padx=(0, 4))

        # Auto-poll checkbox
        self.auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            hdr, text="Auto-poll",
            variable=self.auto_var,
            fg=_C["text"], bg=_C["card"],
            selectcolor=_C["sidebar"],
            activebackground=_C["card"], activeforeground=_C["text"],
            font=("TkDefaultFont", 10),
            command=self._toggle_auto,
        ).pack(side="right", padx=(0, 2))

        # Tab switcher
        tab_bar = tk.Frame(hdr, bg=_C["card"])
        tab_bar.pack(side="right", padx=(0, 16))

        self.btn_tab_fleet = tk.Button(
            tab_bar, text="Fleet Overview",
            command=lambda: self._switch_tab("fleet"),
            bg=_C["accent"], fg="white", relief="flat",
            font=("TkDefaultFont", 10, "bold"), padx=12, pady=4,
            cursor="hand2",
        )
        self.btn_tab_fleet.pack(side="left", padx=(0, 2))

        self.btn_tab_detail = tk.Button(
            tab_bar, text="Device Detail",
            command=lambda: self._switch_tab("detail"),
            bg=_C["sidebar"], fg=_C["muted"], relief="flat",
            font=("TkDefaultFont", 10), padx=12, pady=4,
            cursor="hand2",
        )
        self.btn_tab_detail.pack(side="left")

        # ── Body ──
        self.body = tk.Frame(self, bg=_C["bg"])
        self.body.pack(fill="both", expand=True, padx=8, pady=6)

        self._build_fleet_tab()
        self._build_detail_tab()
        self._switch_tab("fleet")

    # ── Fleet tab ─────────────────────────────────────────────────────────────

    def _build_fleet_tab(self):
        self.fleet_frame = tk.Frame(self.body, bg=_C["bg"])

        ft = tk.Frame(self.fleet_frame, bg=_C["bg"])
        ft.pack(fill="x", pady=(0, 8))

        tk.Label(
            ft, text="All Devices",
            font=("TkDefaultFont", 12, "bold"), fg=_C["text"], bg=_C["bg"]
        ).pack(side="left")

        tk.Button(
            ft, text="  Poll All",
            command=self._poll_fleet,
            bg=_C["accent"], fg="white", relief="flat",
            font=("TkDefaultFont", 10, "bold"), padx=10, pady=4,
            cursor="hand2",
        ).pack(side="right")

        cf = tk.Frame(self.fleet_frame, bg=_C["bg"])
        cf.pack(fill="both", expand=True)

        self.fleet_canvas = tk.Canvas(cf, bg=_C["bg"], highlightthickness=0)
        vsb = tk.Scrollbar(cf, orient="vertical", command=self.fleet_canvas.yview)
        self.fleet_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.fleet_canvas.pack(fill="both", expand=True)

        self.fleet_inner = tk.Frame(self.fleet_canvas, bg=_C["bg"])
        self._fleet_cwin = self.fleet_canvas.create_window(
            (0, 0), window=self.fleet_inner, anchor="nw"
        )
        self.fleet_inner.bind(
            "<Configure>",
            lambda e: self.fleet_canvas.configure(
                scrollregion=self.fleet_canvas.bbox("all")
            )
        )
        self.fleet_canvas.bind(
            "<Configure>",
            lambda e: (
                self.fleet_canvas.itemconfig(self._fleet_cwin, width=e.width),
                self._layout_fleet_cards(),
            )
        )

        self._build_fleet_cards()

    def _build_fleet_cards(self):
        for w in self.fleet_inner.winfo_children():
            w.destroy()
        self._fleet_card_widgets.clear()

        for name, model, meta in self.devices:
            try:
                from ..models.devices import RouterModel, CoreSwitchModel
                if isinstance(model, RouterModel):
                    role = "router"
                elif isinstance(model, CoreSwitchModel):
                    role = "core"
                else:
                    role = "access"
            except Exception:
                role = "access"

            icon = _ROLE_ICONS.get(role, "?")
            self._fleet_card_widgets[name] = self._create_fleet_card(name, icon, role)

        self._layout_fleet_cards()

    def _create_fleet_card(self, name: str, icon: str, role: str) -> dict:
        role_accent = {"router": _C["accent"], "core": _C["warn"], "access": _C["muted"]}
        accent = role_accent.get(role, _C["border"])

        card = tk.Frame(self.fleet_inner, bg=_C["card"], cursor="hand2")

        left_bar = tk.Frame(card, bg=accent, width=4)
        left_bar.pack(side="left", fill="y")

        inner = tk.Frame(card, bg=_C["card"], padx=14, pady=12)
        inner.pack(fill="both", expand=True)

        # Title row
        tr = tk.Frame(inner, bg=_C["card"])
        tr.pack(fill="x")

        role_label = {"router": "Router", "core": "Core SW", "access": "Access SW"}.get(role, "")
        tk.Label(
            tr,
            text=f"[{icon}] {name[:16]}",
            font=("TkDefaultFont", 11, "bold"), fg=_C["text"], bg=_C["card"], anchor="w",
        ).pack(side="left")

        lbl_reach = tk.Label(
            tr, text="Pending",
            font=("TkDefaultFont", 9), fg=_C["muted"], bg=_C["sidebar"],
            padx=8, pady=2,
        )
        lbl_reach.pack(side="right")

        # Role sub-label
        tk.Label(
            inner, text=role_label,
            font=("TkDefaultFont", 8), fg=_C["muted"], bg=_C["card"], anchor="w"
        ).pack(anchor="w", pady=(0, 6))

        # Score row
        sr = tk.Frame(inner, bg=_C["card"])
        sr.pack(fill="x")

        lbl_score_val = tk.Label(
            sr, text="—",
            font=("TkDefaultFont", 26, "bold"), fg=_C["muted"], bg=_C["card"]
        )
        lbl_score_val.pack(side="left")

        score_info = tk.Frame(sr, bg=_C["card"])
        score_info.pack(side="left", padx=(6, 0), anchor="s")
        lbl_score_label = tk.Label(
            score_info, text="",
            font=("TkDefaultFont", 10, "bold"), fg=_C["muted"], bg=_C["card"]
        )
        lbl_score_label.pack(anchor="w")
        tk.Label(
            score_info, text="Health Score",
            font=("TkDefaultFont", 7), fg=_C["muted"], bg=_C["card"]
        ).pack(anchor="w")

        # Stats row
        stats = tk.Frame(inner, bg=_C["card"])
        stats.pack(fill="x", pady=(8, 0))

        def _mini(parent, label, color=_C["muted"]):
            f = tk.Frame(parent, bg=_C["card"])
            f.pack(side="left", padx=(0, 14))
            v = tk.Label(f, text="—", font=("TkDefaultFont", 13, "bold"), fg=color, bg=_C["card"])
            v.pack()
            tk.Label(f, text=label, font=("TkDefaultFont", 7), fg=_C["muted"], bg=_C["card"]).pack()
            return v

        lbl_up   = _mini(stats, "Ifaces Up",   _C["success"])
        lbl_down = _mini(stats, "Ifaces Down", _C["danger"])
        lbl_vlan = _mini(stats, "VLANs",       _C["accent"])

        lbl_ts = tk.Label(
            inner, text="Not polled yet",
            font=("TkDefaultFont", 8), fg=_C["muted"], bg=_C["card"]
        )
        lbl_ts.pack(anchor="w", pady=(8, 0))

        # Click → switch to detail
        def _on_click(n=name):
            self._switch_tab("detail")
            for i, (dn, _, __) in enumerate(self.devices):
                if dn == n:
                    self.device_listbox.selection_clear(0, "end")
                    self.device_listbox.selection_set(i)
                    self._selected_idx = i
                    self.lbl_device_header.configure(text=f"  {n}", fg=_C["text"])
                    break
            self._poll_selected()

        for w in [card, inner, tr, sr, stats]:
            w.bind("<Button-1>", lambda e, n=name: _on_click(n))

        return {
            "card": card,
            "lbl_reach":       lbl_reach,
            "lbl_score_val":   lbl_score_val,
            "lbl_score_label": lbl_score_label,
            "lbl_up":          lbl_up,
            "lbl_down":        lbl_down,
            "lbl_vlan":        lbl_vlan,
            "lbl_ts":          lbl_ts,
        }

    def _layout_fleet_cards(self):
        try:
            canvas_w = self.fleet_canvas.winfo_width()
        except Exception:
            canvas_w = 1060

        card_min = 230
        cols = max(1, (canvas_w - 16) // (card_min + 12))

        for w in self._fleet_card_widgets.values():
            w["card"].grid_forget()

        for i, name in enumerate(self._fleet_card_widgets):
            row, col = divmod(i, cols)
            self._fleet_card_widgets[name]["card"].grid(
                row=row, column=col, padx=6, pady=6, sticky="nsew"
            )

        for c in range(cols):
            self.fleet_inner.columnconfigure(c, weight=1, minsize=card_min)

    # ── Detail tab ────────────────────────────────────────────────────────────

    def _build_detail_tab(self):
        self.detail_frame = tk.Frame(self.body, bg=_C["bg"])

        # Left sidebar
        left = tk.Frame(self.detail_frame, bg=_C["sidebar"], width=200)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)

        tk.Label(
            left, text="  Devices",
            font=("TkDefaultFont", 11, "bold"), fg=_C["text"], bg=_C["sidebar"]
        ).pack(anchor="w", pady=(12, 6))

        self.device_listbox = tk.Listbox(
            left, bg=_C["card"], fg=_C["text"],
            selectbackground=_C["accent"], selectforeground="white",
            borderwidth=0, highlightthickness=0,
            font=("TkDefaultFont", 10), activestyle="none",
        )
        self.device_listbox.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        for name, _, __ in self.devices:
            self.device_listbox.insert("end", f"  {name}")

        if self.devices:
            self.device_listbox.selection_set(0)

        tk.Button(
            left, text="Poll Now",
            command=self._poll_selected,
            bg=_C["accent"], fg="white", relief="flat",
            font=("TkDefaultFont", 10, "bold"), padx=8, pady=6, cursor="hand2",
        ).pack(fill="x", padx=6, pady=(0, 8))

        self.device_listbox.bind("<<ListboxSelect>>", self._on_device_select)

        # Right pane
        right = tk.Frame(self.detail_frame, bg=_C["bg"])
        right.pack(side="left", fill="both", expand=True)

        self.lbl_device_header = tk.Label(
            right, text="Select a device and click Poll Now",
            font=("TkDefaultFont", 12, "bold"), fg=_C["muted"], bg=_C["bg"]
        )
        self.lbl_device_header.pack(anchor="w", pady=(0, 4))

        # Alert zone
        self.alert_zone = tk.Frame(right, bg=_C["bg"])
        self.alert_zone.pack(fill="x")

        # Scrollable results
        outer = tk.Frame(right, bg=_C["bg"])
        outer.pack(fill="both", expand=True)

        self.results_canvas = tk.Canvas(outer, bg=_C["bg"], highlightthickness=0)
        vsb = tk.Scrollbar(outer, orient="vertical", command=self.results_canvas.yview)
        self.results_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.results_canvas.pack(side="left", fill="both", expand=True)

        self.results_inner = tk.Frame(self.results_canvas, bg=_C["bg"])
        self._cwin = self.results_canvas.create_window(
            (0, 0), window=self.results_inner, anchor="nw"
        )
        self.results_inner.bind(
            "<Configure>",
            lambda e: self.results_canvas.configure(
                scrollregion=self.results_canvas.bbox("all")
            )
        )
        self.results_canvas.bind(
            "<Configure>",
            lambda e: self.results_canvas.itemconfig(self._cwin, width=e.width)
        )

        # Ad-hoc terminal
        self._build_adhoc_terminal(right)

        self._show_placeholder("Select a device and click Poll Now.")

    def _build_adhoc_terminal(self, parent):
        # Toggle bar
        self.adhoc_header = tk.Frame(parent, bg=_C["sidebar"], cursor="hand2")
        self.adhoc_header.pack(fill="x", pady=(4, 0))

        self.adhoc_toggle_lbl = tk.Label(
            self.adhoc_header,
            text="  Terminal  (ad-hoc show commands)",
            font=("TkDefaultFont", 10, "bold"), fg=_C["muted"], bg=_C["sidebar"],
            padx=12, pady=6, cursor="hand2",
        )
        self.adhoc_toggle_lbl.pack(side="left")

        self.adhoc_header.bind("<Button-1>", lambda e: self._toggle_adhoc())
        self.adhoc_toggle_lbl.bind("<Button-1>", lambda e: self._toggle_adhoc())

        # Collapsible body (hidden initially)
        self.adhoc_body = tk.Frame(parent, bg=_C["card"])

        # Input row
        ir = tk.Frame(self.adhoc_body, bg=_C["card"])
        ir.pack(fill="x", padx=8, pady=(8, 4))

        tk.Label(ir, text="show", fg=_C["muted"], bg=_C["card"],
                 font=("Courier New", 11)).pack(side="left")

        self._adhoc_var = tk.StringVar()
        self.adhoc_entry = tk.Entry(
            ir, textvariable=self._adhoc_var,
            bg=_C["sidebar"], fg=_C["text"], insertbackground=_C["text"],
            font=("Courier New", 11), relief="flat", bd=4,
        )
        self.adhoc_entry.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self.adhoc_entry.bind("<Return>", lambda e: self._run_adhoc_cmd())

        tk.Button(
            ir, text="Run",
            command=self._run_adhoc_cmd,
            bg=_C["accent"], fg="white", relief="flat",
            font=("TkDefaultFont", 10, "bold"), padx=12, pady=4, cursor="hand2",
        ).pack(side="left")

        self._adhoc_hist_var = tk.StringVar(value="History")
        self.adhoc_hist_menu = tk.OptionMenu(ir, self._adhoc_hist_var, "—")
        self.adhoc_hist_menu.configure(
            bg=_C["sidebar"], fg=_C["muted"], relief="flat",
            highlightthickness=0, font=("TkDefaultFont", 9),
            activebackground=_C["card"], activeforeground=_C["text"],
        )
        self.adhoc_hist_menu.pack(side="left", padx=(4, 0))

        # Output
        self.adhoc_output = tk.Text(
            self.adhoc_body,
            bg=_C["sidebar"], fg=_C["text"],
            font=("Courier New", 10), relief="flat",
            height=8, state="disabled",
            insertbackground=_C["text"],
        )
        self.adhoc_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _toggle_adhoc(self):
        self._adhoc_expanded = not self._adhoc_expanded
        if self._adhoc_expanded:
            self.adhoc_body.pack(fill="x", pady=(0, 4))
            self.adhoc_toggle_lbl.configure(text="  Terminal  (ad-hoc show commands)  ▼")
        else:
            self.adhoc_body.pack_forget()
            self.adhoc_toggle_lbl.configure(text="  Terminal  (ad-hoc show commands)  ▶")

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _switch_tab(self, tab: str):
        self._current_tab = tab
        if tab == "fleet":
            self.detail_frame.pack_forget()
            self.fleet_frame.pack(fill="both", expand=True)
            self.btn_tab_fleet.configure(
                bg=_C["accent"], fg="white", font=("TkDefaultFont", 10, "bold"))
            self.btn_tab_detail.configure(
                bg=_C["sidebar"], fg=_C["muted"], font=("TkDefaultFont", 10))
        else:
            self.fleet_frame.pack_forget()
            self.detail_frame.pack(fill="both", expand=True)
            self.btn_tab_detail.configure(
                bg=_C["accent"], fg="white", font=("TkDefaultFont", 10, "bold"))
            self.btn_tab_fleet.configure(
                bg=_C["sidebar"], fg=_C["muted"], font=("TkDefaultFont", 10))

    # ── Device selection ──────────────────────────────────────────────────────

    def _on_device_select(self, _event=None):
        sel = self.device_listbox.curselection()
        if sel:
            self._selected_idx = sel[0]
            name = self.devices[sel[0]][0]
            self.lbl_device_header.configure(text=f"  {name}", fg=_C["text"])
            if name in self._last_results:
                self._clear_results()
                self._render_device_detail(name, self._last_results[name])

    # ── Fleet polling ─────────────────────────────────────────────────────────

    def _poll_fleet(self):
        if not self.devices:
            return
        self.lbl_status.configure(
            text=f"polling {len(self.devices)} device(s)…", fg=_C["warn"]
        )
        for name, model, meta in self.devices:
            self._start_poll(name, model, meta, source="fleet")

    def _start_poll(self, name: str, model, meta: dict, source: str = "detail"):
        if name in self._active_polls:
            return

        host     = meta.get("console_host") or meta.get("ip", "")
        port_raw = meta.get("console_port") or meta.get("port", "")

        if not host:
            self._result_queue.put((source, name, {"_error": "No host configured"}))
            self.after(0, self._process_queue)
            return

        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            self._result_queue.put(
                (source, name, {"_error": f"Invalid port '{port_raw}'"})
            )
            self.after(0, self._process_queue)
            return

        username, password, enable_pw = _load_device_creds(name, meta)
        cmds = self._commands_for(model)
        self._active_polls.add(name)
        threading.Thread(
            target=self._run_poll,
            args=(name, host, port, cmds, source, username, password, enable_pw),
            daemon=True,
        ).start()

    def _commands_for(self, model) -> list:
        try:
            from ..models.devices import RouterModel, CoreSwitchModel
            is_router = isinstance(model, RouterModel)
            is_core   = isinstance(model, CoreSwitchModel)
        except Exception:
            is_router = is_core = False

        cmds = ["show version", "show ip interface brief", "show interfaces"]

        if is_router:
            cmds += [
                "show ip route", "show ip arp",
                "show cdp neighbors", "show ip dhcp binding",
            ]
        elif is_core:
            cmds += [
                "show vlan-switch", "show vlan brief",
                "show cdp neighbors",
                "show spanning-tree summary",
                "show ip arp",
            ]
        else:
            cmds += [
                "show vlan-switch", "show vlan brief",
                "show cdp neighbors",
                "show spanning-tree",
            ]
        return cmds

    # ── Poll engine ───────────────────────────────────────────────────────────

    def _poll_selected(self):
        if not self.devices:
            return
        sel = self.device_listbox.curselection()
        idx = sel[0] if sel else self._selected_idx
        if idx >= len(self.devices):
            return
        name, model, meta = self.devices[idx]
        self.lbl_status.configure(text=f"polling {name}…", fg=_C["warn"])
        self.lbl_device_header.configure(text=f"  {name}", fg=_C["text"])
        self._start_poll(name, model, meta, source="detail")

    def _run_poll(
        self, name: str, host: str, port: int, cmds: list, source: str,
        username: str = "", password: str = "", enable_pw: str = "",
    ):
        if telnetlib3 is None:
            data = {"_error": "telnetlib3 not installed"}
        else:
            try:
                data = asyncio.run(
                    self._poll_async(host, port, cmds, username, password, enable_pw)
                )
            except Exception as exc:
                data = {"_error": str(exc)}
        self._active_polls.discard(name)
        self._result_queue.put((source, name, data))
        self.after(0, self._process_queue)

    async def _poll_async(
        self, host: str, port: int, cmds: list,
        username: str = "", password: str = "", enable_pw: str = "",
    ) -> dict:
        reader, writer = await asyncio.wait_for(
            telnetlib3.open_connection(host, port), timeout=12
        )

        async def _read_until_prompt(timeout: float = 5.0) -> str:
            """Read until a CLI prompt (> or #) or timeout."""
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
            # Drain GNS3 banner and reach prompt (no auth — devices use no login)
            await asyncio.sleep(0.6)
            await _read_until_prompt(3.0)

            writer.write("terminal length 0\r\n")
            await asyncio.sleep(0.3)
            await _read_until_prompt(3.0)

            for cmd in cmds:
                writer.write(cmd + "\r\n")
                await asyncio.sleep(0.3)
                t = 10.0 if "interfaces" in cmd else 5.0
                results[cmd] = await _read_until_prompt(t)

            writer.close()
        except Exception as exc:
            try:
                writer.close()
            except Exception:
                pass
            results["_error"] = str(exc)

        return results

    # ── Result processing ─────────────────────────────────────────────────────

    def _process_queue(self):
        if getattr(self, "_closed", False):
            return

        while not self._result_queue.empty():
            source, name, data = self._result_queue.get()
            ts = time.strftime("%H:%M:%S")

            if source == "adhoc":
                self._show_adhoc_result(
                    data.get("_adhoc_raw", ""),
                    data.get("_error", ""),
                )
                continue

            err = data.get("_error", "")
            old_data = self._last_results.get(name)

            if not err:
                self._last_results[name] = data

            # Always update the fleet card
            self._update_fleet_card(name, data, ts)

            # Update detail tab if this device is selected there
            is_selected_device = self.devices[self._selected_idx][0] == name
            if source == "detail" or (self._current_tab == "detail" and is_selected_device):
                self._clear_results()
                if err:
                    self.lbl_status.configure(text=f"error {ts}", fg=_C["danger"])
                    self._show_error(f"Could not connect to '{name}':\n{err}")
                else:
                    self.lbl_status.configure(text=f"updated {ts}", fg=_C["success"])
                    alerts = _detect_changes(data, old_data) if old_data else []
                    self._render_alerts(alerts)
                    self._render_device_detail(name, data)

        # Update global status when all polls finish
        if not self._active_polls and self.devices:
            done = sum(1 for n, _, __ in self.devices if n in self._last_results)
            total = len(self.devices)
            self.lbl_status.configure(
                text=f"last poll: {time.strftime('%H:%M:%S')}  ({done}/{total} devices)",
                fg=_C["success"],
            )

    def _update_fleet_card(self, name: str, data: dict, ts: str):
        widgets = self._fleet_card_widgets.get(name)
        if not widgets:
            return
        err = data.get("_error", "")
        try:
            if err:
                widgets["lbl_reach"].configure(
                    text="Offline", fg=_C["danger"], bg="#2a0a0a")
                widgets["lbl_score_val"].configure(text="0", fg=_C["danger"])
                widgets["lbl_score_label"].configure(text="Offline", fg=_C["danger"])
                widgets["lbl_up"].configure(text="—", fg=_C["muted"])
                widgets["lbl_down"].configure(text="—", fg=_C["muted"])
                widgets["lbl_vlan"].configure(text="—", fg=_C["muted"])
            else:
                has_prev = name in self._last_results
                score = _compute_health(data, has_prev)
                col   = _health_color(score)
                label = _health_label(score)

                states = _parse_iface_states(data.get("show ip interface brief", ""))
                up   = sum(1 for s in states.values() if s == "up")
                down = len(states) - up

                vlan_raw = data.get("show vlan brief", data.get("show vlan-switch", ""))
                vlans = len(_parse_vlan_ids(vlan_raw))

                widgets["lbl_reach"].configure(
                    text="Online", fg="#085D3A", bg="#ECFDF3")
                widgets["lbl_score_val"].configure(text=str(score), fg=col)
                widgets["lbl_score_label"].configure(text=label, fg=col)
                widgets["lbl_up"].configure(text=str(up), fg=_C["success"])
                widgets["lbl_down"].configure(
                    text=str(down), fg=_C["danger"] if down else _C["muted"])
                widgets["lbl_vlan"].configure(
                    text=str(vlans) if vlans else "—")

            widgets["lbl_ts"].configure(text=f"Polled {ts}")
        except Exception:
            pass

    # ── Renderers ─────────────────────────────────────────────────────────────

    def _render_alerts(self, alerts: list):
        for w in self.alert_zone.winfo_children():
            w.destroy()

        level_style = {
            "danger":  (_C["alert_danger"],  _C["danger"]),
            "success": (_C["alert_success"], _C["success"]),
            "warn":    (_C["alert_warn"],    _C["warn"]),
            "accent":  (_C["alert_accent"],  _C["accent"]),
        }
        for level, msg in alerts:
            bg, fg = level_style.get(level, (_C["card"], _C["text"]))
            row = tk.Frame(self.alert_zone, bg=bg)
            row.pack(fill="x", pady=1)
            tk.Label(
                row, text=msg, fg=fg, bg=bg,
                font=("TkDefaultFont", 10), padx=12, pady=6, anchor="w",
            ).pack(side="left", fill="x", expand=True)
            tk.Button(
                row, text="Dismiss",
                command=row.destroy,
                fg=fg, bg=bg, relief="flat",
                font=("TkDefaultFont", 9), padx=8, cursor="hand2",
            ).pack(side="right")

    def _render_device_detail(self, name: str, data: dict):
        self._render_health_summary(name, data)

        # Resolve best VLAN command
        vlan_sw  = data.get("show vlan-switch", "")
        vlan_br  = data.get("show vlan brief",  "")
        vlan_raw = vlan_cmd = ""
        if vlan_sw and not _is_invalid(vlan_sw):
            vlan_raw, vlan_cmd = vlan_sw, "show vlan-switch"
        elif vlan_br and not _is_invalid(vlan_br):
            vlan_raw, vlan_cmd = vlan_br, "show vlan brief"

        render_plan = [
            ("show version",            data.get("show version", "")),
            ("show ip interface brief", data.get("show ip interface brief", "")),
            ("show interfaces",         data.get("show interfaces", "")),
        ]
        if vlan_raw:
            render_plan.append((vlan_cmd, vlan_raw))
        for cmd in [
            "show ip route", "show ip arp", "show cdp neighbors",
            "show ip dhcp binding",
            "show spanning-tree summary", "show spanning-tree",
        ]:
            if cmd in data:
                render_plan.append((cmd, data[cmd]))

        dispatch = {
            "show version":               self._render_version_info,
            "show ip interface brief":    self._render_interface_table,
            "show interfaces":            self._render_interface_errors,
            "show ip route":              self._render_route_table,
            "show ip arp":                self._render_arp_table,
            "show cdp neighbors":         self._render_cdp_table,
            "show ip dhcp binding":       self._render_dhcp_table,
            "show vlan-switch":           self._render_vlan_table,
            "show vlan brief":            self._render_vlan_table,
            "show spanning-tree summary": self._render_stp_table,
            "show spanning-tree":         self._render_stp_table,
        }
        for cmd, raw in render_plan:
            if not raw or (_is_invalid(raw) and "version" not in cmd):
                continue
            renderer = dispatch.get(cmd)
            if renderer:
                self._render_section_header(_CMD_LABELS.get(cmd, cmd))
                renderer(raw)

    def _render_health_summary(self, device_name: str, data: dict):
        has_prev  = device_name in self._last_results
        score     = _compute_health(data, has_prev)
        score_col = _health_color(score)
        score_lbl = _health_label(score)

        states   = _parse_iface_states(data.get("show ip interface brief", ""))
        up_count = sum(1 for s in states.values() if s == "up")
        dn_count = len(states) - up_count

        vlan_raw = data.get("show vlan brief", data.get("show vlan-switch", ""))
        vlan_cnt = len(_parse_vlan_ids(vlan_raw))

        dhcp_raw = data.get("show ip dhcp binding", "")
        dhcp_cnt = len(_parse_dhcp_ips(dhcp_raw)) if dhcp_raw and not _is_invalid(dhcp_raw) else 0

        err_cnt  = _count_iface_errors(data.get("show interfaces", ""))

        ver_raw  = data.get("show version", "")
        ios_ver = uptime = hardware = ""
        if ver_raw:
            vm = re.search(r"Version\s+([\d\.\(\)A-Za-z]+)", ver_raw)
            if vm:
                ios_ver = vm.group(1)
            um = re.search(r"uptime is (.+)", ver_raw, re.IGNORECASE)
            if um:
                uptime = um.group(1).strip().rstrip(".")
            hm = re.search(r"[Cc]isco\s+([\w\-]+[^\n,]*)", ver_raw)
            if hm:
                hardware = hm.group(1).strip()[:40]

        card = tk.Frame(self.results_inner, bg=_C["card"], pady=12)
        card.pack(fill="x", padx=4, pady=(4, 8))

        top = tk.Frame(card, bg=_C["card"])
        top.pack(fill="x", padx=16)
        tk.Label(
            top, text=device_name,
            font=("TkDefaultFont", 13, "bold"), fg=_C["text"], bg=_C["card"]
        ).pack(side="left")
        for extra in [f"  {hardware}" if hardware else None,
                      f"  IOS {ios_ver}" if ios_ver else None,
                      f"  uptime: {uptime}" if uptime else None]:
            if extra:
                tk.Label(
                    top, text=extra,
                    font=("TkDefaultFont", 10), fg=_C["muted"], bg=_C["card"]
                ).pack(side="left")

        row = tk.Frame(card, bg=_C["card"])
        row.pack(fill="x", padx=16, pady=(10, 4))

        # Health score block
        sf = tk.Frame(row, bg=_C["sidebar"], padx=14, pady=8)
        sf.pack(side="left", padx=(0, 12))
        tk.Label(sf, text=str(score), font=("TkDefaultFont", 26, "bold"),
                 fg=score_col, bg=_C["sidebar"]).pack()
        tk.Label(sf, text=score_lbl, font=("TkDefaultFont", 9, "bold"),
                 fg=score_col, bg=_C["sidebar"]).pack()
        tk.Label(sf, text="Health Score", font=("TkDefaultFont", 7),
                 fg=_C["muted"], bg=_C["sidebar"]).pack()

        def _badge(label, value, color):
            f = tk.Frame(row, bg=_C["sidebar"], padx=12, pady=8)
            f.pack(side="left", padx=(0, 8))
            tk.Label(f, text=str(value), font=("TkDefaultFont", 20, "bold"),
                     fg=color, bg=_C["sidebar"]).pack()
            tk.Label(f, text=label, font=("TkDefaultFont", 7),
                     fg=_C["muted"], bg=_C["sidebar"]).pack()

        if up_count or dn_count:
            _badge("Ifaces Up",   up_count, _C["success"] if up_count else _C["muted"])
            _badge("Ifaces Down", dn_count, _C["danger"]  if dn_count else _C["muted"])
        if vlan_cnt:
            _badge("Active VLANs", vlan_cnt, _C["accent"])
        if dhcp_cnt:
            _badge("DHCP Leases",  dhcp_cnt, _C["warn"])
        if err_cnt:
            _badge("Iface Errors", err_cnt, _C["danger"])

    def _render_section_header(self, label: str):
        hf = tk.Frame(self.results_inner, bg=_C["sidebar"], pady=7)
        hf.pack(fill="x", pady=(8, 2))
        tk.Label(
            hf, text=f"  {label}",
            font=("TkDefaultFont", 11, "bold"), fg=_C["text"], bg=_C["sidebar"]
        ).pack(side="left", padx=8)

    def _render_version_info(self, raw: str):
        if _is_invalid(raw):
            return
        hardware = ios_ver = uptime = ""
        vm = re.search(r"Version\s+([\d\.\(\)A-Za-z]+)", raw)
        if vm:
            ios_ver = vm.group(1)
        um = re.search(r"uptime is (.+)", raw, re.IGNORECASE)
        if um:
            uptime = um.group(1).strip().rstrip(".")
        hm = re.search(r"[Cc]isco\s+([\w\-]+[^\n,]*)", raw)
        if hm:
            hardware = hm.group(1).strip()[:40]

        cols = [c for c in [
            ("Hardware",    hardware),
            ("IOS Version", ios_ver),
            ("Uptime",      uptime),
        ] if c[1]]
        if not cols:
            return

        row = tk.Frame(self.results_inner, bg=_C["card"], pady=10)
        row.pack(fill="x", padx=4, pady=2)
        for label, value in cols:
            cell = tk.Frame(row, bg=_C["card"])
            cell.pack(side="left", padx=16)
            tk.Label(cell, text=label, font=("TkDefaultFont", 8),
                     fg=_C["muted"], bg=_C["card"]).pack(anchor="w")
            tk.Label(cell, text=value, font=("TkDefaultFont", 10, "bold"),
                     fg=_C["text"], bg=_C["card"]).pack(anchor="w")

    def _render_interface_table(self, raw: str):
        lines = [l for l in raw.splitlines() if l.strip()]
        hi = next((i for i, l in enumerate(lines)
                   if "Interface" in l and "Status" in l), None)
        if hi is None:
            return

        hf = tk.Frame(self.results_inner, bg=_C["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("", 2), ("Interface", 24), ("IP Address", 18),
                       ("Status", 12), ("Protocol", 10)]:
            tk.Label(hf, text=col, fg=_C["muted"], bg=_C["sidebar"],
                     font=("TkDefaultFont", 9, "bold"), width=w,
                     anchor="w").pack(side="left")

        pat = re.compile(r"^(\S+)\s+(\S+)\s+\S+\s+\S+\s+(\S+)\s+(\S+)", re.IGNORECASE)
        alt = False
        for line in lines[hi + 1:]:
            m = pat.match(line.strip())
            if not m:
                continue
            iface, ip, status, proto = m.groups()
            is_up = proto.lower() == "up"
            bg = (_C["row_alt"] if alt else _C["card"]) if is_up else "#2a1a1a"
            alt = not alt
            rf = tk.Frame(self.results_inner, bg=bg)
            rf.pack(fill="x", pady=1, padx=4)
            dot = _C["success"] if is_up else _C["danger"]
            tk.Label(rf, text="●", fg=dot, bg=bg,
                     font=("TkDefaultFont", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(iface, 22), (ip, 18), (status, 12), (proto, 10)]:
                tk.Label(rf, text=val, fg=_C["text"], bg=bg,
                         font=("Courier New", 10), width=w, anchor="w").pack(side="left")

    def _render_interface_errors(self, raw: str):
        """Show per-interface error counters; flag non-zero values in red."""
        if _is_invalid(raw) or not raw.strip():
            return

        blocks = re.split(r"\n(?=\S+\s+is\s+(?:up|down|administratively))", raw)
        error_ifaces = []

        for block in blocks:
            hm = re.match(r"^(\S+)\s+is\s+(\S+)", block)
            if not hm:
                continue
            iface = hm.group(1)
            state = hm.group(2).lower()

            metrics = {}
            for pattern, key in [
                (r"(\d+) input errors",  "In Errors"),
                (r"(\d+) CRC",           "CRC"),
                (r"(\d+) output errors", "Out Errors"),
                (r"(\d+) output drops",  "Out Drops"),
                (r"(\d+) input drops",   "In Drops"),
            ]:
                m2 = re.search(pattern, block, re.IGNORECASE)
                if m2 and int(m2.group(1)) > 0:
                    metrics[key] = m2.group(1)

            rate_in  = re.search(r"5 minute input rate (\d+) bits",  block, re.IGNORECASE)
            rate_out = re.search(r"5 minute output rate (\d+) bits", block, re.IGNORECASE)

            if metrics:
                error_ifaces.append({
                    "name": iface, "state": state, "metrics": metrics,
                    "rate_in":  rate_in.group(1)  if rate_in  else "",
                    "rate_out": rate_out.group(1) if rate_out else "",
                })

        if not error_ifaces:
            row = tk.Frame(self.results_inner, bg=_C["card"])
            row.pack(fill="x", padx=4, pady=4)
            tk.Label(
                row, text="  No interface errors detected.",
                fg=_C["success"], bg=_C["card"],
                font=("TkDefaultFont", 10), pady=8,
            ).pack(anchor="w")
            return

        for ei in error_ifaces:
            is_up = ei["state"] == "up"
            bg = _C["card"] if is_up else "#2a1a1a"
            row = tk.Frame(self.results_inner, bg=bg, pady=6)
            row.pack(fill="x", padx=4, pady=2)

            dot = _C["success"] if is_up else _C["danger"]
            tk.Label(row, text="●", fg=dot, bg=bg,
                     font=("TkDefaultFont", 9)).pack(side="left", padx=(6, 0))
            tk.Label(row, text=ei["name"], fg=_C["text"], bg=bg,
                     font=("Courier New", 10, "bold"), width=22,
                     anchor="w").pack(side="left", padx=(4, 12))

            for key, val in ei["metrics"].items():
                cell = tk.Frame(row, bg=bg)
                cell.pack(side="left", padx=(0, 12))
                tk.Label(cell, text=val, fg=_C["danger"], bg=bg,
                         font=("TkDefaultFont", 12, "bold")).pack()
                tk.Label(cell, text=key, fg=_C["muted"], bg=bg,
                         font=("TkDefaultFont", 7)).pack()

            if ei["rate_in"] or ei["rate_out"]:
                rates = tk.Frame(row, bg=bg)
                rates.pack(side="right", padx=12)
                if ei["rate_in"]:
                    tk.Label(rates, text=f"In: {ei['rate_in']} b/s",
                             fg=_C["muted"], bg=bg, font=("TkDefaultFont", 8)).pack(anchor="e")
                if ei["rate_out"]:
                    tk.Label(rates, text=f"Out: {ei['rate_out']} b/s",
                             fg=_C["muted"], bg=bg, font=("TkDefaultFont", 8)).pack(anchor="e")

    def _render_vlan_table(self, raw: str):
        if _is_invalid(raw):
            return
        lines = [l for l in raw.splitlines() if l.strip()]
        hi = next((i for i, l in enumerate(lines)
                   if "VLAN" in l and "Name" in l), None)
        if hi is None:
            return

        hf = tk.Frame(self.results_inner, bg=_C["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("", 2), ("VLAN", 8), ("Name", 22), ("Status", 10), ("Ports", 28)]:
            tk.Label(hf, text=col, fg=_C["muted"], bg=_C["sidebar"],
                     font=("TkDefaultFont", 9, "bold"), width=w,
                     anchor="w").pack(side="left")

        pat = re.compile(r"^(\d+)\s+(\S+)\s+(\S+)(.*)", re.IGNORECASE)
        alt = found = 0
        for line in lines[hi + 1:]:
            m = pat.match(line.strip())
            if not m:
                continue
            vid, vname, status, ports = m.groups()
            is_active = "active" in status.lower()
            bg = (_C["row_alt"] if alt % 2 else _C["card"]) if is_active else "#2a1a1a"
            alt += 1
            rf = tk.Frame(self.results_inner, bg=bg)
            rf.pack(fill="x", pady=1, padx=4)
            dot = _C["success"] if is_active else _C["warn"]
            tk.Label(rf, text="●", fg=dot, bg=bg,
                     font=("TkDefaultFont", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(vid, 6), (vname, 20), (status, 10), (ports.strip()[:26], 26)]:
                tk.Label(rf, text=val, fg=_C["text"], bg=bg,
                         font=("Courier New", 10), width=w,
                         anchor="w").pack(side="left")
            found += 1

        if found == 0:
            tk.Label(self.results_inner, text="No VLANs found.",
                     fg=_C["muted"], bg=_C["bg"],
                     font=("TkDefaultFont", 10)).pack(anchor="w", padx=8, pady=4)

    def _render_dhcp_table(self, raw: str):
        if _is_invalid(raw):
            return
        lines = [l for l in raw.splitlines() if l.strip()]
        hi = next((i for i, l in enumerate(lines)
                   if "IP address" in l or "IP Address" in l), None)

        pat = re.compile(
            r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+(\S+)\s+"
            r"(\w{3}\s+\d+\s+\d{4}[^\s]*\s+\d+:\d+\s*\w*)",
            re.IGNORECASE
        )
        simple = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+(\S+)")
        rows = []
        for line in lines[(hi + 1 if hi is not None else 0):]:
            m = pat.match(line)
            if m:
                rows.append((m.group(1), m.group(2), m.group(3).strip()))
                continue
            ms = simple.match(line)
            if ms and ms.group(1) not in ("0.0.0.0",):
                rows.append((ms.group(1), ms.group(2), "—"))

        if not rows:
            tk.Label(self.results_inner, text="No active DHCP leases.",
                     fg=_C["muted"], bg=_C["bg"],
                     font=("TkDefaultFont", 10), pady=6).pack(anchor="w", padx=8)
            return

        hf = tk.Frame(self.results_inner, bg=_C["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("", 2), ("IP Address", 18), ("MAC / Client ID", 26),
                       ("Lease Expires", 24)]:
            tk.Label(hf, text=col, fg=_C["muted"], bg=_C["sidebar"],
                     font=("TkDefaultFont", 9, "bold"), width=w,
                     anchor="w").pack(side="left")

        alt = False
        for ip, client, expires in rows:
            bg = _C["row_alt"] if alt else _C["card"]
            alt = not alt
            rf = tk.Frame(self.results_inner, bg=bg)
            rf.pack(fill="x", pady=1, padx=4)
            tk.Label(rf, text="●", fg=_C["success"], bg=bg,
                     font=("TkDefaultFont", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(ip, 16), (client, 24), (expires, 22)]:
                tk.Label(rf, text=val, fg=_C["text"], bg=bg,
                         font=("Courier New", 10), width=w,
                         anchor="w").pack(side="left")

    def _render_route_table(self, raw: str):
        """Parse and render 'show ip route' with color-coded route types."""
        if _is_invalid(raw) or not raw.strip():
            return

        hf = tk.Frame(self.results_inner, bg=_C["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("", 2), ("Code", 6), ("Network / Prefix", 22),
                       ("Via / Next-Hop", 18), ("Interface", 16)]:
            tk.Label(hf, text=col, fg=_C["muted"], bg=_C["sidebar"],
                     font=("TkDefaultFont", 9, "bold"), width=w,
                     anchor="w").pack(side="left")

        code_colors = {
            "C": _C["success"],   # connected
            "L": _C["success"],   # local
            "S": _C["accent"],    # static
            "R": _C["warn"],      # RIP
            "O": "#DA77F2",       # OSPF
            "B": "#FF8C00",       # BGP
            "D": "#00CED1",       # EIGRP
        }

        # Match route lines: code(s), prefix, optional via, optional interface
        route_pat = re.compile(
            r"^([A-Za-z*\s]{1,6})\s+([\d\.\/]+)"
            r"(?:.*?\bvia\b\s+([\d\.]+))?",
            re.IGNORECASE
        )
        iface_pat = re.compile(
            r"(GigabitEthernet|FastEthernet|Ethernet|Serial|Loopback|Tunnel)\S+",
            re.IGNORECASE
        )

        alt = found = 0
        for line in raw.splitlines():
            line_s = line.strip()
            # Skip legend, blank, and gateway-of-last-resort lines
            if not line_s or re.match(r"^[A-Za-z*]+ -", line_s):
                continue
            if line_s.startswith("Gateway"):
                continue

            m = route_pat.match(line_s)
            if not m:
                continue

            code   = m.group(1).strip()
            prefix = m.group(2).strip()
            via    = m.group(3) or "—"

            # Try to extract interface name from the full line
            im = iface_pat.search(line)
            iface = im.group(0)[:16] if im else "—"

            code_key = code.lstrip("*").strip()[0:1].upper()
            fg = code_colors.get(code_key, _C["text"])
            bg = _C["row_alt"] if alt % 2 else _C["card"]
            alt += 1

            rf = tk.Frame(self.results_inner, bg=bg)
            rf.pack(fill="x", pady=1, padx=4)
            tk.Label(rf, text="●", fg=fg, bg=bg,
                     font=("TkDefaultFont", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(code[:5], 5), (prefix, 20), (via, 16), (iface, 14)]:
                tk.Label(rf, text=val, fg=_C["text"], bg=bg,
                         font=("Courier New", 10), width=w,
                         anchor="w").pack(side="left")
            found += 1

        if found == 0:
            tk.Label(self.results_inner, text="No routes found.",
                     fg=_C["muted"], bg=_C["bg"],
                     font=("TkDefaultFont", 10), pady=6).pack(anchor="w", padx=8)

    def _render_arp_table(self, raw: str):
        if _is_invalid(raw) or not raw.strip():
            return
        lines = [l for l in raw.splitlines() if l.strip()]
        hi = next((i for i, l in enumerate(lines)
                   if "Protocol" in l and "Address" in l), None)
        if hi is None:
            return

        hf = tk.Frame(self.results_inner, bg=_C["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("", 2), ("IP Address", 18), ("Age", 8),
                       ("MAC Address", 18), ("Interface", 18)]:
            tk.Label(hf, text=col, fg=_C["muted"], bg=_C["sidebar"],
                     font=("TkDefaultFont", 9, "bold"), width=w,
                     anchor="w").pack(side="left")

        pat = re.compile(
            r"^(?:Internet|ARPA)\s+([\d\.]+)\s+(\S+)\s+"
            r"([0-9a-fA-F\.\:]{5,}|Incomplete)\s+\S+\s+(\S+)",
            re.IGNORECASE
        )
        alt = found = 0
        for line in lines[hi + 1:]:
            m = pat.match(line.strip())
            if not m:
                continue
            ip, age, mac, iface = m.groups()
            bg = _C["row_alt"] if alt % 2 else _C["card"]
            alt += 1
            rf = tk.Frame(self.results_inner, bg=bg)
            rf.pack(fill="x", pady=1, padx=4)
            tk.Label(rf, text="●", fg=_C["success"], bg=bg,
                     font=("TkDefaultFont", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(ip, 16), (age, 6), (mac, 16), (iface[:16], 16)]:
                tk.Label(rf, text=val, fg=_C["text"], bg=bg,
                         font=("Courier New", 10), width=w,
                         anchor="w").pack(side="left")
            found += 1

        if found == 0:
            tk.Label(self.results_inner, text="No ARP entries.",
                     fg=_C["muted"], bg=_C["bg"],
                     font=("TkDefaultFont", 10), pady=6).pack(anchor="w", padx=8)

    def _render_cdp_table(self, raw: str):
        if _is_invalid(raw) or not raw.strip():
            return
        lines = [l for l in raw.splitlines() if l.strip()]
        hi = next((i for i, l in enumerate(lines) if "Device ID" in l), None)

        if hi is None:
            tk.Label(
                self.results_inner,
                text="CDP not enabled or no neighbors found.",
                fg=_C["muted"], bg=_C["bg"],
                font=("TkDefaultFont", 10), pady=6,
            ).pack(anchor="w", padx=8)
            return

        hf = tk.Frame(self.results_inner, bg=_C["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("", 2), ("Neighbor", 20), ("Local Intf", 14),
                       ("Platform", 14), ("Remote Intf", 14)]:
            tk.Label(hf, text=col, fg=_C["muted"], bg=_C["sidebar"],
                     font=("TkDefaultFont", 9, "bold"), width=w,
                     anchor="w").pack(side="left")

        # CDP format: Device_ID  Local_Intf  Holdtime  Capability  Platform  Port_ID
        pat = re.compile(
            r"^(\S+)\s+"
            r"((?:Gig|Fas|Eth|Ten|Se|Lo)\S+)\s+"
            r"\d+\s+"
            r"([\w\s]+?)\s+"
            r"(\S+)\s+"
            r"((?:Gig|Fas|Eth|Ten|Se|Lo)\S+)",
            re.IGNORECASE
        )
        alt = found = 0
        for line in lines[hi + 1:]:
            m = pat.match(line.strip())
            if not m:
                continue
            neighbor, local_if, _cap, platform, remote_if = m.groups()
            bg = _C["row_alt"] if alt % 2 else _C["card"]
            alt += 1
            rf = tk.Frame(self.results_inner, bg=bg)
            rf.pack(fill="x", pady=1, padx=4)
            tk.Label(rf, text="●", fg=_C["accent"], bg=bg,
                     font=("TkDefaultFont", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(neighbor[:18], 18), (local_if[:12], 12),
                           (platform[:12], 12), (remote_if[:12], 12)]:
                tk.Label(rf, text=val, fg=_C["text"], bg=bg,
                         font=("Courier New", 10), width=w,
                         anchor="w").pack(side="left")
            found += 1

        if found == 0:
            tk.Label(self.results_inner, text="No CDP neighbors found.",
                     fg=_C["muted"], bg=_C["bg"],
                     font=("TkDefaultFont", 10), pady=6).pack(anchor="w", padx=8)

    def _render_stp_table(self, raw: str):
        if _is_invalid(raw) or not raw.strip():
            return

        card = tk.Frame(self.results_inner, bg=_C["card"], pady=8)
        card.pack(fill="x", padx=4, pady=2)

        mode_m = re.search(r"Switch is in (\S+) mode", raw, re.IGNORECASE)
        if mode_m:
            tk.Label(card, text=f"  Mode: {mode_m.group(1)}",
                     fg=_C["text"], bg=_C["card"],
                     font=("TkDefaultFont", 10)).pack(anchor="w")

        root_m = re.search(r"Root bridge for:\s*(.+)", raw, re.IGNORECASE)
        if root_m:
            tk.Label(card, text=f"  Root for: {root_m.group(1).strip()}",
                     fg=_C["success"], bg=_C["card"],
                     font=("TkDefaultFont", 10)).pack(anchor="w")

        lines = [l for l in raw.splitlines() if l.strip()]
        hi = next((i for i, l in enumerate(lines)
                   if "Blocking" in l and "Forwarding" in l), None)

        if hi is not None:
            hf = tk.Frame(self.results_inner, bg=_C["sidebar"])
            hf.pack(fill="x", pady=(4, 2), padx=4)
            for col, w in [("VLAN", 14), ("Blocking", 10), ("Listening", 10),
                           ("Learning", 10), ("Forwarding", 12), ("Active", 8)]:
                tk.Label(hf, text=col, fg=_C["muted"], bg=_C["sidebar"],
                         font=("TkDefaultFont", 9, "bold"), width=w,
                         anchor="w").pack(side="left")

            row_pat = re.compile(r"^(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)")
            alt = 0
            for line in lines[hi + 1:]:
                if "----" in line or not line.strip():
                    continue
                m = row_pat.match(line.strip())
                if not m:
                    continue
                bg = _C["row_alt"] if alt % 2 else _C["card"]
                alt += 1
                rf = tk.Frame(self.results_inner, bg=bg)
                rf.pack(fill="x", pady=1, padx=4)
                for val, w in zip(m.groups(), [12, 8, 8, 8, 10, 6]):
                    tk.Label(rf, text=val, fg=_C["text"], bg=bg,
                             font=("Courier New", 10), width=w,
                             anchor="w").pack(side="left")

        if not mode_m and not root_m and hi is None:
            tk.Label(card, text=raw[:400], fg=_C["muted"], bg=_C["card"],
                     font=("Courier New", 9), justify="left",
                     wraplength=560, padx=12).pack(anchor="w")

    # ── Ad-hoc terminal ───────────────────────────────────────────────────────

    def _run_adhoc_cmd(self):
        suffix = self._adhoc_var.get().strip()
        if not suffix:
            return

        cmd = suffix if suffix.lower().startswith("show") else f"show {suffix}"

        if not cmd.lower().startswith("show"):
            self._show_adhoc_result("", "Only 'show' commands are permitted.")
            return

        if not self.devices:
            return
        sel = self.device_listbox.curselection()
        idx = sel[0] if sel else self._selected_idx
        if idx >= len(self.devices):
            return
        name, _model, meta = self.devices[idx]

        host     = meta.get("console_host") or meta.get("ip", "")
        port_raw = meta.get("console_port") or meta.get("port", "")
        if not host:
            self._show_adhoc_result("", f"No host configured for '{name}'.")
            return
        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            self._show_adhoc_result("", f"Invalid port '{port_raw}'.")
            return

        # Update history list
        if cmd not in self._adhoc_history:
            self._adhoc_history.insert(0, cmd)
            self._adhoc_history = self._adhoc_history[:10]
            menu = self.adhoc_hist_menu["menu"]
            menu.delete(0, "end")
            for h in self._adhoc_history:
                menu.add_command(
                    label=h,
                    command=lambda v=h: (
                        self._adhoc_var.set(v[5:] if v.startswith("show ") else v),
                        self._adhoc_hist_var.set("History"),
                    ),
                )

        username, password, enable_pw = _load_device_creds(name, meta)

        self._show_adhoc_result("Running…", "")
        threading.Thread(
            target=self._run_adhoc_poll,
            args=(name, host, port, cmd, username, password, enable_pw),
            daemon=True,
        ).start()

    def _run_adhoc_poll(
        self, name: str, host: str, port: int, cmd: str,
        username: str = "", password: str = "", enable_pw: str = "",
    ):
        if telnetlib3 is None:
            result = {"_adhoc_raw": "", "_error": "telnetlib3 not installed"}
        else:
            try:
                data = asyncio.run(
                    self._poll_async(host, port, [cmd], username, password, enable_pw)
                )
                result = {
                    "_adhoc_raw": data.get(cmd, ""),
                    "_error": data.get("_error", ""),
                }
            except Exception as exc:
                result = {"_adhoc_raw": "", "_error": str(exc)}

        self._result_queue.put(("adhoc", name, result))
        self.after(0, self._process_queue)

    def _show_adhoc_result(self, output: str, error: str):
        try:
            self.adhoc_output.configure(state="normal")
            self.adhoc_output.delete("1.0", "end")
            if error:
                self.adhoc_output.insert("end", f"ERROR: {error}\n")
            else:
                self.adhoc_output.insert("end", output)
            self.adhoc_output.configure(state="disabled")
        except Exception:
            pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _show_placeholder(self, msg: str):
        self._clear_results()
        tk.Label(
            self.results_inner, text=msg,
            fg=_C["muted"], bg=_C["bg"],
            font=("TkDefaultFont", 11), justify="center",
        ).pack(expand=True, pady=40)

    def _show_error(self, msg: str):
        tk.Label(
            self.results_inner, text=msg,
            fg=_C["danger"], bg=_C["bg"],
            font=("TkDefaultFont", 10), wraplength=580, justify="left",
        ).pack(anchor="w", padx=8, pady=8)

    def _clear_results(self):
        try:
            for w in self.alert_zone.winfo_children():
                w.destroy()
        except Exception:
            pass
        try:
            for w in self.results_inner.winfo_children():
                w.destroy()
        except Exception:
            pass

    # ── Auto-poll ─────────────────────────────────────────────────────────────

    def _toggle_auto(self):
        if self._poll_timer:
            try:
                self.after_cancel(self._poll_timer)
            except Exception:
                pass
            self._poll_timer = None
        if self.auto_var.get():
            self._auto_poll_tick()

    def _auto_poll_tick(self):
        if not self.auto_var.get() or self._closed:
            return
        if self._current_tab == "fleet":
            self._poll_fleet()
        else:
            self._poll_selected()
        ms = _POLL_INTERVALS.get(self._interval_var.get(), 30_000)
        self._poll_timer = self.after(ms, self._auto_poll_tick)

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._closed = True
        if self._poll_timer:
            try:
                self.after_cancel(self._poll_timer)
            except Exception:
                pass
        self.destroy()
