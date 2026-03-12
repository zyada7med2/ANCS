"""
Topology Viewer for ANCS — draws the live GNS3 network topology on a Canvas.

Nodes are color-coded by device type:
  Router      — blue  (#388BFD)
  Core Switch — orange (#E3B341)
  Access Sw.  — grey  (#6E7681)
  Unknown     — muted grey

Devices that have been configured via the Guided Wizard get a green border.
Nodes can be repositioned by dragging.
"""

import math
import tkinter as tk
from .utils import apply_responsive_geometry


# ── Colour palette ────────────────────────────────────────────────────────────
_T = {
    "bg":      "#0D1117",
    "card":    "#1F2630",
    "sidebar": "#161B22",
    "text":    "#C9D1D9",
    "muted":   "#6E7681",
    "border":  "#30363D",
    "router":  "#388BFD",
    "core":    "#E3B341",
    "access":  "#6E7681",
    "unknown": "#484F58",
    "configured_border": "#3FB950",  # green highlight for configured devices
    "link":    "#444C56",
    "link_label": "#8B949E",
}

_NODE_W  = 120
_NODE_H  = 44
_PADDING = 30


class TopologyViewer(tk.Toplevel):
    """
    Modal window that renders a GNS3 project topology.

    Parameters
    ----------
    parent       : the main App window
    connector    : GNS3Connector instance
    project_id   : GNS3 project UUID
    ancs_devices : list of (name, DeviceModel, meta) from app.self.devices
    """

    def __init__(self, parent, connector, project_id: str, ancs_devices: list):
        super().__init__(parent)
        self.title("Network Topology")
        self.resizable(True, True)
        apply_responsive_geometry(self, 900, 620, min_w=640, min_h=420)
        self.configure(bg=_T["bg"])

        self._connector    = connector
        self._project_id   = project_id
        self._ancs_devices = ancs_devices   # (name, model, meta) tuples
        self._parent       = parent

        # node_id → {x, y, name, role, configured}
        self._nodes: dict[str, dict] = {}
        # list of (node_id_a, node_id_b, label_a, label_b)
        self._links: list[tuple] = []

        # drag state
        self._drag_node: str | None = None
        self._drag_ox = 0
        self._drag_oy = 0

        self._build_ui()
        self._load_topology()

    # ── UI skeleton ───────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=_T["card"], pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="Network Topology",
            font=("TkDefaultFont", 13, "bold"), fg=_T["text"], bg=_T["card"],
        ).pack(side="left", padx=16)
        tk.Button(
            hdr, text="⟳  Refresh", command=self._load_topology,
            bg=_T["sidebar"], fg=_T["text"], relief="flat",
            font=("TkDefaultFont", 10), padx=10, pady=4,
        ).pack(side="right", padx=12)

        # Legend
        leg = tk.Frame(self, bg=_T["bg"])
        leg.pack(fill="x", padx=16, pady=(6, 0))
        for label, colour in [
            ("Router",        _T["router"]),
            ("Core Switch",   _T["core"]),
            ("Access Switch", _T["access"]),
            ("Configured ✓",  _T["configured_border"]),
        ]:
            dot = tk.Label(leg, text="●", fg=colour, bg=_T["bg"],
                           font=("TkDefaultFont", 12))
            dot.pack(side="left", padx=(0, 2))
            tk.Label(leg, text=label + "  ", fg=_T["muted"], bg=_T["bg"],
                     font=("TkDefaultFont", 9)).pack(side="left")

        # Canvas with scrollbars
        frm = tk.Frame(self, bg=_T["bg"])
        frm.pack(fill="both", expand=True, padx=8, pady=8)
        self._canvas = tk.Canvas(frm, bg=_T["bg"], highlightthickness=0)
        hbar = tk.Scrollbar(frm, orient="horizontal", command=self._canvas.xview)
        vbar = tk.Scrollbar(frm, orient="vertical",   command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        hbar.pack(side="bottom", fill="x")
        vbar.pack(side="right",  fill="y")
        self._canvas.pack(fill="both", expand=True)

        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

        # Status bar
        self._status_var = tk.StringVar(value="Loading topology…")
        tk.Label(self, textvariable=self._status_var, fg=_T["muted"], bg=_T["bg"],
                 font=("TkDefaultFont", 9), anchor="w").pack(fill="x", padx=16, pady=(0, 6))

    # ── Data loading ─────────────────────────────────────────────────────────

    def _load_topology(self):
        """Start topology load in a background thread to avoid blocking the UI."""
        self._status_var.set("Loading topology…")
        self._canvas.delete("all")
        import threading
        threading.Thread(target=self._fetch_topology, daemon=True).start()

    def _fetch_topology(self):
        """Background thread: fetch GNS3 data then hand off to main thread."""
        try:
            raw_nodes = self._connector.get_nodes(self._project_id)
            raw_links = self._connector.get_links(self._project_id)
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._status_var.set(f"Error: {e}"))
            return

        # Build a port-name lookup: node_id → {(adapter, port): real_iface_name}
        # This resolves interface names like "GigabitEthernet0/1" from raw numbers.
        port_map: dict[str, dict[tuple, str]] = {}
        for node in raw_nodes:
            nid = node.get("node_id", "")
            if not nid:
                continue
            try:
                ports = self._connector.get_node_ports(self._project_id, nid)
                mapping: dict[tuple, str] = {}
                for p in ports:
                    a  = p.get("adapter_number")
                    pt = p.get("port_number")
                    nm = p.get("name", "").strip()
                    if a is not None and pt is not None and nm:
                        mapping[(int(a), int(pt))] = nm
                if mapping:
                    port_map[nid] = mapping
            except Exception:
                pass  # if ports can't be fetched, fall back to label/generic name

        self.after(0, lambda n=raw_nodes, l=raw_links, pm=port_map:
                   self._apply_topology(n, l, pm))

    def _apply_topology(self, raw_nodes, raw_links, port_map: dict = None):
        """Main-thread callback: process and render topology data."""
        if port_map is None:
            port_map = {}

        # Build a map from node_id → ANCS name+model (if imported into ANCS)
        meta_map: dict[str, dict] = {}  # node_id → meta
        for aname, amodel, ameta in self._ancs_devices:
            nid = ameta.get("node_id")
            if nid:
                meta_map[nid] = {"name": aname, "model": amodel, "meta": ameta}

        # Classify and position nodes in a circle
        n = len(raw_nodes)
        cx = 420
        cy = 280
        radius = min(cx, cy) - 80 if n > 1 else 0

        self._nodes.clear()
        self._links.clear()

        for i, node in enumerate(raw_nodes):
            nid   = node.get("node_id", "")
            label = node.get("label", {}).get("text") or node.get("name", "?")
            node_type = node.get("node_type", "").lower()
            sym   = (node.get("symbol") or "").lower()

            # Determine role from GNS3 type / symbol hints or ANCS model
            role = "unknown"
            if nid in meta_map:
                from ..models.devices import RouterModel, CoreSwitchModel, SwitchModel
                mdl = meta_map[nid]["model"]
                if isinstance(mdl, RouterModel):
                    role = "router"
                elif isinstance(mdl, CoreSwitchModel):
                    role = "core"
                elif isinstance(mdl, SwitchModel):
                    role = "access"
            else:
                if "router" in sym or "router" in node_type:
                    role = "router"
                elif "multilayer" in sym or "layer3" in sym or "core" in sym:
                    role = "core"
                elif "switch" in sym or "switch" in node_type:
                    role = "access"

            # Configured = has any guided_* template
            configured = False
            if nid in meta_map:
                mdl = meta_map[nid]["model"]
                configured = any(k.startswith("guided_") for k in mdl.templates)

            # Position on circle
            angle = 2 * math.pi * i / max(n, 1)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)

            self._nodes[nid] = {
                "x": x, "y": y,
                "name": label, "role": role,
                "configured": configured,
            }

        # Parse links — resolve real interface names from port_map or label.text
        for link in raw_links:
            endpoints = link.get("nodes", [])
            if len(endpoints) < 2:
                continue
            a, b = endpoints[0], endpoints[1]
            nid_a = a.get("node_id", "")
            nid_b = b.get("node_id", "")
            lbl_a = _port_label(a, port_map.get(nid_a, {}))
            lbl_b = _port_label(b, port_map.get(nid_b, {}))
            self._links.append((nid_a, nid_b, lbl_a, lbl_b))

        self._draw()
        n_links = len(self._links)
        self._status_var.set(
            f"{len(self._nodes)} devices  ·  {n_links} link{'s' if n_links != 1 else ''}  "
            f"·  {sum(1 for nd in self._nodes.values() if nd['configured'])} configured"
        )

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self):
        c = self._canvas
        c.delete("all")

        # Draw links first (behind nodes)
        for nid_a, nid_b, lbl_a, lbl_b in self._links:
            na = self._nodes.get(nid_a)
            nb = self._nodes.get(nid_b)
            if not na or not nb:
                continue
            x1, y1 = na["x"], na["y"]
            x2, y2 = nb["x"], nb["y"]
            c.create_line(x1, y1, x2, y2, fill=_T["link"], width=2, tags="link")

            # Port label near the midpoint, offset slightly
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            if lbl_a or lbl_b:
                lbl_txt = f"{lbl_a}↔{lbl_b}" if (lbl_a and lbl_b) else (lbl_a or lbl_b)
                c.create_text(mx, my, text=lbl_txt, fill=_T["link_label"],
                              font=("TkFixedFont", 8), tags="link_label")

        # Draw nodes
        hw = _NODE_W // 2
        hh = _NODE_H // 2

        for nid, nd in self._nodes.items():
            x, y = nd["x"], nd["y"]
            role  = nd["role"]
            fill  = _T.get(role, _T["unknown"])
            outline_col = _T["configured_border"] if nd["configured"] else _T["border"]
            outline_w   = 3 if nd["configured"] else 1

            # Node rectangle
            c.create_rectangle(
                x - hw, y - hh, x + hw, y + hh,
                fill=fill, outline=outline_col, width=outline_w,
                tags=("node", f"node_{nid}"),
            )
            # Device name label
            short = nd["name"]
            if len(short) > 16:
                short = short[:14] + "…"
            c.create_text(
                x, y,
                text=short,
                fill="white",
                font=("TkDefaultFont", 9, "bold"),
                tags=("node_label", f"node_label_{nid}"),
            )
            # Role sub-label
            role_txt = {"router": "Router", "core": "Core SW", "access": "Access SW"}.get(role, "")
            if role_txt:
                c.create_text(
                    x, y + hh + 10,
                    text=role_txt,
                    fill=_T["muted"],
                    font=("TkDefaultFont", 8),
                    tags="role_label",
                )

        # Update scrollregion
        c.configure(scrollregion=c.bbox("all") or (0, 0, 840, 560))

    # ── Drag to reposition ────────────────────────────────────────────────────

    def _on_press(self, event):
        x = self._canvas.canvasx(event.x)
        y = self._canvas.canvasy(event.y)
        hw, hh = _NODE_W // 2, _NODE_H // 2
        for nid, nd in self._nodes.items():
            if abs(x - nd["x"]) <= hw and abs(y - nd["y"]) <= hh:
                self._drag_node = nid
                self._drag_ox   = x - nd["x"]
                self._drag_oy   = y - nd["y"]
                return
        self._drag_node = None

    def _on_drag(self, event):
        if not self._drag_node:
            return
        x = self._canvas.canvasx(event.x) - self._drag_ox
        y = self._canvas.canvasy(event.y) - self._drag_oy
        self._nodes[self._drag_node]["x"] = x
        self._nodes[self._drag_node]["y"] = y
        self._draw()

    def _on_release(self, event):
        self._drag_node = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _port_label(endpoint: dict, node_ports: dict = None) -> str:
    """
    Resolve the real interface name for a GNS3 link endpoint.

    Resolution order (most accurate → least accurate):
    1. endpoint["label"]["text"]  — GNS3 embeds the name in the link itself
    2. node_ports lookup          — fetched from /nodes/{id}/ports
    3. Generic fallback           — e.g. "e0/0" derived from adapter/port numbers
    """
    # 1. GNS3 embeds the label directly in the link endpoint
    label_text = (endpoint.get("label") or {}).get("text", "").strip()
    if label_text:
        return _shorten_iface(label_text)

    adapter = endpoint.get("adapter_number")
    port    = endpoint.get("port_number")

    # 2. Look up real name from the per-node port map
    if node_ports and adapter is not None and port is not None:
        real = node_ports.get((int(adapter), int(port)), "")
        if real:
            return _shorten_iface(real)

    # 3. Generic fallback
    if adapter is not None and port is not None:
        return f"e{adapter}/{port}"
    return ""


def _shorten_iface(name: str) -> str:
    """
    Abbreviate common Cisco interface names to keep topology labels compact.

    Examples:
        GigabitEthernet0/1  → Gi0/1
        FastEthernet0/0     → Fa0/0
        Ethernet0/1         → Et0/1
        Serial0/0/0         → Se0/0/0
    """
    _ABBREV = [
        ("GigabitEthernet", "Gi"),
        ("FastEthernet",    "Fa"),
        ("TenGigabitEthernet", "Te"),
        ("Ethernet",        "Et"),
        ("Serial",          "Se"),
        ("Loopback",        "Lo"),
        ("Tunnel",          "Tu"),
        ("Vlan",            "Vl"),
    ]
    for full, short in _ABBREV:
        if name.lower().startswith(full.lower()):
            return short + name[len(full):]
    return name
