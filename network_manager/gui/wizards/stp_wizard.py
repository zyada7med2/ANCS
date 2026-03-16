"""
STP (Spanning Tree Protocol) configuration GUI wizard — PySide6 version
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt
from ..utils import apply_responsive_geometry

DARK = """
    QDialog { background-color: #0D1117; }
    QTableWidget { background-color: #161B22; color: #C9D1D9; border: 1px solid #30363D;
                   border-radius: 6px; gridline-color: #30363D; }
    QTableWidget::item:selected { background-color: #264F78; }
    QHeaderView::section { background-color: #1F2630; color: #8B949E; border: none; padding: 6px; }
    QPushButton { background-color: #374151; color: #9ca3af; border: none; border-radius: 6px;
                  padding: 6px 14px; }
    QPushButton:hover { background-color: #4b5563; color: white; }
    QPushButton#gen { background-color: #3b82f6; color: white; }
    QPushButton#gen:hover { background-color: #2563eb; }
"""


class StpGuiWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("STP GUI Wizard")
        self.setStyleSheet(DARK)
        apply_responsive_geometry(self, 750, 480)
        self.result = None

        layout = QVBoxLayout(self)
        cols = ["VLAN", "Mode", "Priority", "PortFast", "BPDUGuard", "UplinkFast", "BackboneFast"]
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btn_add = QPushButton("Add Row")
        btn_add.clicked.connect(self.add_row)
        btn_rm = QPushButton("Remove")
        btn_rm.clicked.connect(self.remove_sel)
        btn_gen = QPushButton("Generate")
        btn_gen.setObjectName("gen")
        btn_gen.clicked.connect(self.on_generate)
        btns.addWidget(btn_add)
        btns.addWidget(btn_rm)
        btns.addStretch()
        btns.addWidget(btn_gen)
        layout.addLayout(btns)

        self.add_row()

    def add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        defaults = ["", "pvst", "32768", "no", "no", "no", "no"]
        for c, val in enumerate(defaults):
            self.table.setItem(r, c, QTableWidgetItem(val))

    def remove_sel(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def on_generate(self):
        out = []
        try:
            for r in range(self.table.rowCount()):
                def _cell(c):
                    it = self.table.item(r, c)
                    return it.text().strip() if it else ""
                vlan = _cell(0)
                mode = _cell(1) or "pvst"
                priority = _cell(2) or "32768"
                portfast = _cell(3)
                bpduguard = _cell(4)
                uplinkfast = _cell(5)
                backbonefast = _cell(6)
                if not vlan:
                    QMessageBox.critical(self, "Error", "Enter VLAN ID")
                    return
                out.append(f"spanning-tree mode {mode}")
                out.append(f"spanning-tree vlan {vlan} priority {priority}")
                if portfast.lower() in ("yes", "true", "on"):
                    out.append("spanning-tree portfast default")
                if bpduguard.lower() in ("yes", "true", "on"):
                    out.append("spanning-tree portfast bpduguard default")
                if uplinkfast.lower() in ("yes", "true", "on"):
                    out.append("spanning-tree uplinkfast")
                if backbonefast.lower() in ("yes", "true", "on"):
                    out.append("spanning-tree backbonefast")
                out.append("")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Invalid input: {e}")
            return
        out.append("! stp gui wizard complete")
        self.result = "\n".join(out)
        self.accept()
