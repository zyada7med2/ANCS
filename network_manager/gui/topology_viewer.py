"""
Topology Viewer for ANCS — PySide6 version.
Draws the live GNS3 network topology using QPainter on a QWidget canvas.

Nodes are color-coded by device type:
  Router      — blue  (#388BFD)
  Core Switch — orange (#E3B341)
  Access Sw.  — grey  (#6E7681)
  Unknown     — muted grey

Devices configured via the Guided Wizard get a green border.
Nodes can be repositioned by dragging.
"""
import math
import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QScrollArea, QComboBox
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from .utils import apply_responsive_geometry

_T = {
    "bg":      "#0D1117", "card":   "#1F2630", "sidebar": "#161B22",
    "text":    "#C9D1D9", "muted":  "#6E7681", "border":  "#30363D",
    "router":  "#388BFD", "core":   "#E3B341", "access":  "#6E7681",
    "unknown": "#484F58", "configured_border": "#3FB950",
    "redist":  "#BF4B8A",  # Magenta/Purple for redistribution bridge
    "link":    "#444C56", "link_label": "#8B949E",
}
_NODE_W, _NODE_H = 120, 44

DARK = """
    QDialog { background-color: #0D1117; }
    QLabel { color: #C9D1D9; background: transparent; }
    QPushButton { background-color: #161B22; color: #C9D1D9; border: none; border-radius: 6px;
                  padding: 6px 14px; }
    QPushButton:hover { background-color: #1F2630; }
"""


class _TopoCanvas(QWidget):
    """Custom widget that draws nodes and links using QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes: dict[str, dict] = {}
        self.links: list[tuple] = []
        self._drag_node = None
        self._drag_ox = 0
        self._drag_oy = 0
        self.setMinimumSize(840, 560)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(_T["bg"]))

        hw, hh = _NODE_W // 2, _NODE_H // 2

        for nid_a, nid_b, lbl_a, lbl_b in self.links:
            na, nb = self.nodes.get(nid_a), self.nodes.get(nid_b)
            if not na or not nb:
                continue
            p.setPen(QPen(QColor(_T["link"]), 2))
            p.drawLine(int(na["x"]), int(na["y"]), int(nb["x"]), int(nb["y"]))
            mx = (na["x"] + nb["x"]) / 2
            my = (na["y"] + nb["y"]) / 2
            if lbl_a or lbl_b:
                lbl = f"{lbl_a}\u2194{lbl_b}" if (lbl_a and lbl_b) else (lbl_a or lbl_b)
                p.setPen(QColor(_T["link_label"]))
                p.setFont(QFont("Consolas", 7))
                p.drawText(int(mx) - 40, int(my) - 6, 80, 14, Qt.AlignCenter, lbl)

        for nid, nd in self.nodes.items():
            x, y = int(nd["x"]), int(nd["y"])
            role = nd["role"]
            fill = QColor(_T.get(role, _T["unknown"]))
            outline = QColor(_T["configured_border"] if nd["configured"] else _T["border"])
            outline_width = 3 if nd["configured"] else 1
            
            if nd.get("is_redist"):
                outline = QColor(_T["redist"])
                outline_width = 4
                
            p.setBrush(QBrush(fill))
            p.setPen(QPen(outline, outline_width))
            p.drawRoundedRect(x - hw, y - hh, _NODE_W, _NODE_H, 6, 6)

            short = nd["name"]
            if len(short) > 16:
                short = short[:14] + "\u2026"
            p.setPen(QColor("white"))
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(x - hw, y - hh, _NODE_W, _NODE_H, Qt.AlignCenter, short)

            if nd.get("is_redist"):
                # Draw redistribution bridge sub-label outside the box
                p.setPen(QColor(_T["redist"]))
                p.setFont(QFont("Segoe UI", 8, QFont.Bold))
                bridge_txt = " \u2194 ".join(p.upper() for p in nd.get("redist_protos", []))
                p.drawText(x - hw - 20, y + hh + 2, _NODE_W + 40, 14, Qt.AlignCenter, f"[ {bridge_txt} ]")
                
                # Add a small icon inside the box
                p.setPen(QColor("white"))
                p.setFont(QFont("Segoe UI", 12))
                p.drawText(x - hw + 8, y - hh, 20, _NODE_H, Qt.AlignVCenter, "\u2b82")
            else:
                role_txt = {"router": "Router", "core": "Core SW", "access": "Access SW"}.get(role, "")
                if role_txt:
                    p.setPen(QColor(_T["muted"]))
                    p.setFont(QFont("Segoe UI", 7))
                    p.drawText(x - hw, y + hh + 2, _NODE_W, 14, Qt.AlignCenter, role_txt)
        p.end()

    def mousePressEvent(self, event):
        x, y = event.position().x(), event.position().y()
        hw, hh = _NODE_W // 2, _NODE_H // 2
        for nid, nd in self.nodes.items():
            if abs(x - nd["x"]) <= hw and abs(y - nd["y"]) <= hh:
                self._drag_node = nid
                self._drag_ox = x - nd["x"]
                self._drag_oy = y - nd["y"]
                return
        self._drag_node = None

    def mouseMoveEvent(self, event):
        if not self._drag_node:
            return
        x = event.position().x() - self._drag_ox
        y = event.position().y() - self._drag_oy
        self.nodes[self._drag_node]["x"] = x
        self.nodes[self._drag_node]["y"] = y
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag_node = None


class TopologyViewer(QDialog):
    _topology_ready = Signal(object, object, object)
    _topology_error = Signal(str)

    def __init__(self, parent, connector, project_id: str, ancs_devices: list, project_context: dict = None):
        super().__init__(parent)
        self.setWindowTitle("Network Topology")
        self.setStyleSheet(DARK)
        apply_responsive_geometry(self, 900, 620, min_w=640, min_h=420)

        self._connector = connector
        self._project_id = project_id
        self._ancs_devices = ancs_devices
        self._project_context = project_context or {}
        self._topology_ready.connect(self._apply_topology)
        self._topology_error.connect(lambda e: self._status.setText(f"Error: {e}"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        hdr = QHBoxLayout()
        lbl = QLabel("Network Topology")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        
        self._net_filter = QComboBox()
        self._net_filter.setStyleSheet("""
            QComboBox { background: #161B22; color: #C9D1D9; border: 1px solid #30363D; border-radius: 4px; padding: 4px; min-width: 120px; }
            QComboBox::drop-down { border: none; }
        """)
        self._net_filter.addItem("All Networks", "All")
        net_map = self._project_context.get("network_map", {})
        nets = sorted(set(net_map.values()))
        friendly_names = {}
        for _, _, meta in self._ancs_devices:
            if "network_id" in meta and meta.get("node_id") in net_map:
                friendly_names[net_map[meta.get("node_id")]] = meta["network_id"]
        for net in nets:
            self._net_filter.addItem(friendly_names.get(net, net), net)
        self._net_filter.currentIndexChanged.connect(lambda: self._apply_topology())
        hdr.addWidget(self._net_filter)

        btn_refresh = QPushButton("\u27F3  Refresh")
        btn_refresh.clicked.connect(self._load_topology)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        legend = QHBoxLayout()
        for label_text, colour in [("Router", _T["router"]), ("Core Switch", _T["core"]),
                                    ("Access Switch", _T["access"]), ("Configured \u2713", _T["configured_border"]),
                                    ("Bridge", _T["redist"])]:
            dot = QLabel("\u25CF")
            dot.setStyleSheet(f"color: {colour}; font-size: 12px;")
            legend.addWidget(dot)
            legend.addWidget(QLabel(label_text))
        legend.addStretch()
        layout.addLayout(legend)

        self._canvas = _TopoCanvas()
        layout.addWidget(self._canvas, 1)

        self._status = QLabel("Loading topology\u2026")
        self._status.setStyleSheet("color: #6E7681; font-size: 9px;")
        layout.addWidget(self._status)

        self._load_topology()
        self.show()

    def _load_topology(self):
        self._status.setText("Loading topology\u2026")
        self._canvas.nodes.clear()
        self._canvas.links.clear()
        self._canvas.update()
        threading.Thread(target=self._fetch_topology, daemon=True).start()

    def _fetch_topology(self):
        try:
            raw_nodes = self._connector.get_nodes(self._project_id)
            raw_links = self._connector.get_links(self._project_id)
        except Exception as exc:
            self._topology_error.emit(str(exc))
            return

        port_map = {}
        for node in raw_nodes:
            nid = node.get("node_id", "")
            if not nid:
                continue
            try:
                ports = self._connector.get_node_ports(self._project_id, nid)
                mapping = {}
                for p_data in ports:
                    a = p_data.get("adapter_number")
                    pt = p_data.get("port_number")
                    nm = p_data.get("name", "").strip()
                    if a is not None and pt is not None and nm:
                        mapping[(int(a), int(pt))] = nm
                if mapping:
                    port_map[nid] = mapping
            except Exception:
                pass

        self._topology_ready.emit(raw_nodes, raw_links, port_map)

    def _apply_topology(self, raw_nodes=None, raw_links=None, port_map=None):
        if raw_nodes is not None:
            self._last_raw_nodes = raw_nodes
            self._last_raw_links = raw_links
            self._last_port_map = port_map
        else:
            raw_nodes = getattr(self, "_last_raw_nodes", [])
            raw_links = getattr(self, "_last_raw_links", [])
            port_map = getattr(self, "_last_port_map", {})
            
        if port_map is None:
            port_map = {}
            
        net_map = self._project_context.get("network_map", {})
        filter_net = getattr(self, "_net_filter", None)
        if filter_net and filter_net.currentData() != "All":
            f_id = filter_net.currentData()
            raw_nodes = [n for n in raw_nodes if net_map.get(str(n.get("node_id", ""))) == f_id]
            allowed = set(str(n.get("node_id", "")) for n in raw_nodes)
            new_links = []
            for l in raw_links:
                eps = l.get("nodes", [])
                if len(eps) >= 2 and str(eps[0].get("node_id", "")) in allowed and str(eps[1].get("node_id", "")) in allowed:
                    new_links.append(l)
            raw_links = new_links

        meta_map = {}
        for aname, amodel, ameta in self._ancs_devices:
            nid = ameta.get("node_id")
            if nid:
                meta_map[nid] = {"name": aname, "model": amodel, "meta": ameta}

        n = len(raw_nodes)
        cx, cy = 420, 280
        radius = min(cx, cy) - 80 if n > 1 else 0

        nodes = {}
        links = []

        for i, node in enumerate(raw_nodes):
            nid = node.get("node_id", "")
            label = node.get("label", {}).get("text") or node.get("name", "?")
            node_type = node.get("node_type", "").lower()
            sym = (node.get("symbol") or "").lower()
            role = "unknown"
            if nid in meta_map:
                from ..models.devices import RouterModel, CoreSwitchModel, SwitchModel
                mdl = meta_map[nid]["model"]
                if isinstance(mdl, RouterModel): role = "router"
                elif isinstance(mdl, CoreSwitchModel): role = "core"
                elif isinstance(mdl, SwitchModel): role = "access"
            else:
                if "router" in sym or "router" in node_type: role = "router"
                elif "multilayer" in sym or "layer3" in sym or "core" in sym: role = "core"
                elif "switch" in sym or "switch" in node_type: role = "access"

            configured = False
            is_redist = False
            redist_protos = []
            
            if nid in meta_map:
                configured = any(k.startswith("guided_") for k in meta_map[nid]["model"].templates)
                d_name = meta_map[nid]["name"]
                
                # Check redistribution details from the project context
                if (d_name == self._project_context.get("redistribution_router") or 
                    d_name == self._project_context.get("existing_redistribution_router")):
                    is_redist = True
                    # Combine active protocols into a single list
                    redist_protos = self._project_context.get("redistribution_protocols", [])

            angle = 2 * math.pi * i / max(n, 1)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            nodes[nid] = {"x": x, "y": y, "name": label, "role": role, 
                          "configured": configured, "is_redist": is_redist, "redist_protos": redist_protos}

        for link in raw_links:
            endpoints = link.get("nodes", [])
            if len(endpoints) < 2:
                continue
            a, b = endpoints[0], endpoints[1]
            nid_a, nid_b = a.get("node_id", ""), b.get("node_id", "")
            lbl_a = _port_label(a, port_map.get(nid_a, {}))
            lbl_b = _port_label(b, port_map.get(nid_b, {}))
            links.append((nid_a, nid_b, lbl_a, lbl_b))

        self._canvas.nodes = nodes
        self._canvas.links = links
        self._canvas.update()
        n_links = len(links)
        self._status.setText(
            f"{len(nodes)} devices  \u00b7  {n_links} link{'s' if n_links != 1 else ''}  "
            f"\u00b7  {sum(1 for nd in nodes.values() if nd['configured'])} configured")


def _port_label(endpoint, node_ports=None):
    label_text = (endpoint.get("label") or {}).get("text", "").strip()
    if label_text:
        return _shorten_iface(label_text)
    adapter = endpoint.get("adapter_number")
    port = endpoint.get("port_number")
    if node_ports and adapter is not None and port is not None:
        real = node_ports.get((int(adapter), int(port)), "")
        if real:
            return _shorten_iface(real)
    if adapter is not None and port is not None:
        return f"e{adapter}/{port}"
    return ""


def _shorten_iface(name):
    for full, short in [("GigabitEthernet", "Gi"), ("FastEthernet", "Fa"),
                         ("TenGigabitEthernet", "Te"), ("Ethernet", "Et"),
                         ("Serial", "Se"), ("Loopback", "Lo"), ("Tunnel", "Tu"), ("Vlan", "Vl")]:
        if name.lower().startswith(full.lower()):
            return short + name[len(full):]
    return name
