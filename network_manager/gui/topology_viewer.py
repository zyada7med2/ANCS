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
    QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from .utils import apply_responsive_geometry

_T = {
    "bg":      "#0D1117", "card":   "#1F2630", "sidebar": "#161B22",
    "text":    "#C9D1D9", "muted":  "#6E7681", "border":  "#30363D",
    "router":  "#388BFD", "core":   "#E3B341", "access":  "#6E7681",
    "unknown": "#484F58", "configured_border": "#3FB950",
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
            p.setBrush(QBrush(fill))
            p.setPen(QPen(outline, 3 if nd["configured"] else 1))
            p.drawRoundedRect(x - hw, y - hh, _NODE_W, _NODE_H, 6, 6)

            short = nd["name"]
            if len(short) > 16:
                short = short[:14] + "\u2026"
            p.setPen(QColor("white"))
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(x - hw, y - hh, _NODE_W, _NODE_H, Qt.AlignCenter, short)

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

    def __init__(self, parent, connector, project_id: str, ancs_devices: list):
        super().__init__(parent)
        self.setWindowTitle("Network Topology")
        self.setStyleSheet(DARK)
        apply_responsive_geometry(self, 900, 620, min_w=640, min_h=420)

        self._connector = connector
        self._project_id = project_id
        self._ancs_devices = ancs_devices
        self._topology_ready.connect(self._apply_topology)
        self._topology_error.connect(lambda e: self._status.setText(f"Error: {e}"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        hdr = QHBoxLayout()
        lbl = QLabel("Network Topology")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        btn_refresh = QPushButton("\u27F3  Refresh")
        btn_refresh.clicked.connect(self._load_topology)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        legend = QHBoxLayout()
        for label_text, colour in [("Router", _T["router"]), ("Core Switch", _T["core"]),
                                    ("Access Switch", _T["access"]), ("Configured \u2713", _T["configured_border"])]:
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

    def _apply_topology(self, raw_nodes, raw_links, port_map=None):
        if port_map is None:
            port_map = {}
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
            if nid in meta_map:
                configured = any(k.startswith("guided_") for k in meta_map[nid]["model"].templates)

            angle = 2 * math.pi * i / max(n, 1)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            nodes[nid] = {"x": x, "y": y, "name": label, "role": role, "configured": configured}

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
