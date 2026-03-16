"""
Subnet calculator GUI for network planning — PySide6 version
"""
import ipaddress
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QWidget, QScrollArea, QFrame, QAbstractItemView,
)
from PySide6.QtCore import Qt
from ..utils import apply_responsive_geometry

DARK = """
    QDialog { background-color: #13151b; }
    QLabel { color: #9ca3af; background: transparent; }
    QTabWidget::pane { background-color: #1a1f2e; border: 1px solid #30363D; border-radius: 6px; }
    QTabBar::tab { background: #1a1f2e; color: #9ca3af; padding: 8px 16px; border: none; }
    QTabBar::tab:selected { color: white; border-bottom: 2px solid #3b82f6; }
    QLineEdit { background-color: #374151; color: white; border: 1px solid #4b5563;
                border-radius: 6px; padding: 6px 12px; }
    QPushButton { background-color: #374151; color: #9ca3af; border: none; border-radius: 6px;
                  padding: 6px 14px; }
    QPushButton:hover { background-color: #4b5563; color: white; }
    QPushButton#accent { background-color: #3b82f6; color: white; }
    QPushButton#accent:hover { background-color: #2563eb; }
    QTableWidget { background-color: #161B22; color: #C9D1D9; border: 1px solid #30363D;
                   gridline-color: #30363D; }
    QTableWidget::item:selected { background-color: #264F78; }
    QHeaderView::section { background-color: #1F2630; color: #8B949E; border: none; padding: 6px; }
    QScrollArea { background: transparent; border: none; }
"""


class SubnetCalculator(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Subnet Calculator")
        self.setStyleSheet(DARK)
        apply_responsive_geometry(self, 900, 600)
        self.dept_entries = []

        layout = QVBoxLayout(self)
        lbl = QLabel("Subnet Calculator")
        lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #9ca3af;")
        layout.addWidget(lbl, alignment=Qt.AlignCenter)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Network Info tab
        info_page = QWidget()
        info_layout = QVBoxLayout(info_page)
        info_layout.setContentsMargins(20, 20, 20, 20)
        info_layout.setSpacing(12)

        info_layout.addWidget(QLabel("Network (e.g. 192.168.10.0/24):"))
        self.entry_net = QLineEdit()
        self.entry_net.setPlaceholderText("192.168.10.0/24")
        info_layout.addWidget(self.entry_net)

        info_layout.addWidget(QLabel("Number of Departments:"))
        self.entry_dept = QLineEdit()
        self.entry_dept.setPlaceholderText("e.g. 4")
        info_layout.addWidget(self.entry_dept)

        btn_next = QPushButton("Next \u279C")
        btn_next.setObjectName("accent")
        btn_next.clicked.connect(self.create_dept_tab)
        info_layout.addWidget(btn_next, alignment=Qt.AlignRight)
        info_layout.addStretch()
        self.tabs.addTab(info_page, "Network Info")

        # Departments tab
        dept_page = QWidget()
        dept_outer = QVBoxLayout(dept_page)
        self.dept_scroll = QScrollArea()
        self.dept_scroll.setWidgetResizable(True)
        self.dept_container = QWidget()
        self.dept_layout = QVBoxLayout(self.dept_container)
        self.dept_scroll.setWidget(self.dept_container)
        dept_outer.addWidget(self.dept_scroll, 1)
        btn_gen = QPushButton("Generate Subnets")
        btn_gen.setObjectName("accent")
        btn_gen.clicked.connect(self.calculate_subnets)
        dept_outer.addWidget(btn_gen, alignment=Qt.AlignCenter)
        self.tabs.addTab(dept_page, "Departments")

        # Results tab
        result_page = QWidget()
        self.result_layout = QVBoxLayout(result_page)
        self.tabs.addTab(result_page, "Results")

        self.show()

    def create_dept_tab(self):
        while self.dept_layout.count():
            item = self.dept_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.dept_entries.clear()

        try:
            dept_count = int(self.entry_dept.text().strip())
            if dept_count <= 0:
                raise ValueError
        except Exception:
            QMessageBox.critical(self, "Error", "Invalid department count")
            return

        lbl = QLabel("Enter Department Info")
        lbl.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.dept_layout.addWidget(lbl)

        for i in range(dept_count):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"Dept {i+1} Name:"))
            name_entry = QLineEdit()
            name_entry.setFixedWidth(180)
            row.addWidget(name_entry)
            row.addWidget(QLabel("Hosts:"))
            hosts_entry = QLineEdit()
            hosts_entry.setFixedWidth(100)
            row.addWidget(hosts_entry)
            row.addStretch()
            wrapper = QWidget()
            wrapper.setLayout(row)
            self.dept_layout.addWidget(wrapper)
            self.dept_entries.append((name_entry, hosts_entry))

        self.dept_layout.addStretch()
        self.tabs.setCurrentIndex(1)

    def calculate_subnets(self):
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            network = ipaddress.ip_network(self.entry_net.text().strip(), strict=False)
        except Exception:
            QMessageBox.critical(self, "Error", "Invalid network address")
            return

        dept_data = []
        for name_entry, hosts_entry in self.dept_entries:
            dept = name_entry.text().strip() or "Unnamed"
            try:
                hosts = int(hosts_entry.text().strip())
            except Exception:
                QMessageBox.critical(self, "Error", f"Invalid host count for {dept}")
                return
            dept_data.append((dept, hosts))

        dept_data.sort(key=lambda x: x[1], reverse=True)
        remaining = [network]

        columns = ["Department", "Network", "Mask", "Gateway", "Broadcast", "Usable Range"]
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        for dept, hosts in dept_data:
            needed = hosts + 2
            bits = 0
            while 2 ** bits < needed:
                bits += 1
            new_prefix = 32 - bits
            alloc = None
            for sn in remaining:
                if sn.prefixlen <= new_prefix:
                    subs = list(sn.subnets(new_prefix=new_prefix))
                    if subs:
                        alloc = subs[0]
                        remaining.remove(sn)
                        remaining.extend(subs[1:])
                        break
            if not alloc:
                QMessageBox.critical(self, "Error", f"No space for {dept}")
                continue
            hosts_list = list(alloc.hosts())
            gw = str(hosts_list[0]) if hosts_list else "-"
            usable = f"{hosts_list[1]} - {hosts_list[-1]}" if len(hosts_list) > 2 else "-"
            r = table.rowCount()
            table.insertRow(r)
            for c, val in enumerate([dept, str(alloc.network_address), str(alloc.netmask),
                                     gw, str(alloc.broadcast_address), usable]):
                table.setItem(r, c, QTableWidgetItem(val))

        self.result_layout.addWidget(table)
        self.tabs.setCurrentIndex(2)
        QMessageBox.information(self, "Done", "Subnet calculation complete")
