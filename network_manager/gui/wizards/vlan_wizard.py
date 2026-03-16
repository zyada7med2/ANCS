"""
VLAN configuration GUI wizard — PySide6 version
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox,
    QInputDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
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


class VlanGuiWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("VLAN GUI Wizard")
        self.setStyleSheet(DARK)
        apply_responsive_geometry(self, 700, 460)
        self.result = None

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["VLAN", "Name", "Ports"])
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
        for c in range(3):
            self.table.setItem(r, c, QTableWidgetItem(""))

    def remove_sel(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def on_generate(self):
        out = []
        port_start = 1
        try:
            for r in range(self.table.rowCount()):
                v = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
                name = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
                pc = (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()
                if not v:
                    QMessageBox.critical(self, "Error", "Enter VLAN ID")
                    return
                vid = int(v)
                pname = name if name else f"VLAN{vid}"
                pcnt = int(pc) if pc else 0
                port_end = port_start + pcnt - 1
                out.append(f"vlan {vid}")
                out.append(f" name {pname}")
                if pcnt > 0:
                    out.append(f"interface range GigabitEthernet0/{port_start} - {port_end}")
                    out.append(" switchport mode access")
                    out.append(f" switchport access vlan {vid}")
                out.append("")
                port_start = port_end + 1
        except Exception:
            QMessageBox.critical(self, "Error", "Invalid numbers")
            return
        out.append("! vlan gui wizard complete")
        self.result = "\n".join(out)
        self.accept()
