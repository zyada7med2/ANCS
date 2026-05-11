import asyncio
import threading
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QComboBox, QProgressBar, QTextEdit, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt, QTimer, Signal

from ..network.physical import PhysicalDiscovery

class PhysicalDiscoveryDialog(QDialog):
    """Dialog for initiating a Physical Network Discovery."""
    
    discovery_complete = Signal(list) # Emits the list of discovered device dictionaries

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Physical Network Discovery")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        
        self.found_devices = []
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # Method selection
        self.method_combo = QComboBox()
        self.method_combo.addItems(["CDP Seed Crawl (Recommended)", "IP Subnet Sweep"])
        self.method_combo.currentIndexChanged.connect(self._on_method_change)
        
        main_layout.addWidget(QLabel("Discovery Method:"))
        main_layout.addWidget(self.method_combo)

        # Input Group
        input_group = QGroupBox("Target Information")
        input_form = QFormLayout()
        
        self.lbl_target = QLabel("Seed Device IP:")
        self.edit_target = QLineEdit()
        self.edit_target.setPlaceholderText("e.g. 192.168.1.1")
        input_form.addRow(self.lbl_target, self.edit_target)
        
        self.edit_user = QLineEdit()
        self.edit_user.setPlaceholderText("Common Username")
        input_form.addRow("Username:", self.edit_user)

        self.edit_pass = QLineEdit()
        self.edit_pass.setEchoMode(QLineEdit.Password)
        self.edit_pass.setPlaceholderText("Common Password")
        input_form.addRow("Password:", self.edit_pass)

        self.edit_en = QLineEdit()
        self.edit_en.setEchoMode(QLineEdit.Password)
        self.edit_en.setPlaceholderText("Enable Password (Optional)")
        input_form.addRow("Enable Password:", self.edit_en)

        input_group.setLayout(input_form)
        main_layout.addWidget(input_group)

        # Log Output
        self.log_out = QTextEdit()
        self.log_out.setReadOnly(True)
        self.log_out.setStyleSheet("background-color: #121A2F; color: #58A6FF; font-family: Consolas;")
        main_layout.addWidget(self.log_out)
        
        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0) # Indeterminate spinning
        self.progress.hide()
        main_layout.addWidget(self.progress)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_run = QPushButton("Start Discovery")
        self.btn_run.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        self.btn_run.clicked.connect(self._run_discovery)
        
        btn_close = QPushButton("Cancel")
        btn_close.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        btn_layout.addWidget(self.btn_run)
        main_layout.addLayout(btn_layout)

    def _on_method_change(self):
        method = self.method_combo.currentText()
        if "Subnet" in method:
            self.lbl_target.setText("Subnet CIDR:")
            self.edit_target.setPlaceholderText("e.g. 10.0.0.0/24")
        else:
            self.lbl_target.setText("Seed Device IP:")
            self.edit_target.setPlaceholderText("e.g. 192.168.1.1")

    def _safe_log(self, msg: str):
        # We need a cross-thread safe way to log, so we use QMetaObject.invokeMethod, 
        # or just hope the minimal thread boundary here allows safe append. 
        # Using a signal or just appending since QTextEdit append is generally thread safe in PySide6.
        # But to be perfectly safe, we can use QTimer
        QTimer.singleShot(0, lambda: self.log_out.append(msg))

    def _run_discovery(self):
        target = self.edit_target.text().strip()
        if not target:
            self._safe_log("[!] Error: Target IP/Subnet is required.")
            return

        self.btn_run.setEnabled(False)
        self.progress.show()
        self.log_out.clear()

        method = self.method_combo.currentText()
        user = self.edit_user.text().strip()
        psw = self.edit_pass.text()
        en = self.edit_en.text()

        def background_task():
            try:
                if "Subnet" in method:
                    # Run subnet sweep in its own isolated asyncio loop
                    self._safe_log(f"Starting Subnet Sweep on {target}...")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    live_endpoints = loop.run_until_complete(
                        PhysicalDiscovery.scan_subnet(target, self._safe_log)
                    )
                    loop.close()
                    
                    if not live_endpoints:
                        self._safe_log("No responsive endpoints found.")
                        return

                    self._safe_log("Attempting to identify discovered endpoints...")
                    for ep in live_endpoints:
                        dev = PhysicalDiscovery.identify_device(
                            ep['ip'], ep['protocol'], ep['port'], user, psw, en, self._safe_log
                        )
                        if dev:
                            self.found_devices.append(dev)

                else:
                    # CDP Seed Crawl
                    self._safe_log(f"Starting CDP Crawl from {target}...")
                    seed_dev = PhysicalDiscovery.identify_device(
                        target, "telnet", 23, user, psw, en, self._safe_log
                    )
                    if not seed_dev:
                        seed_dev = {"name": f"Core-{target}", "ip": target, "port": 23, "protocol": "telnet", "type": "core switch"}
                        self._safe_log(f"Couldn't identify seed perfectly, assuming {seed_dev['name']}")
                    
                    self.found_devices.append(seed_dev)
                    
                    neighbors = PhysicalDiscovery.crawl_cdp(
                        target, 23, "telnet", user, psw, en, self._safe_log
                    )
                    self.found_devices.extend(neighbors)

            except Exception as e:
                self._safe_log(f"[!] Core Discovery Error: {str(e)}")
            finally:
                QTimer.singleShot(0, self._on_finish)

        threading.Thread(target=background_task, daemon=True).start()

    def _on_finish(self):
        self.progress.hide()
        self.btn_run.setEnabled(True)
        if self.found_devices:
            self._safe_log(f"\n--- SUCCESS ---\nDiscovered {len(self.found_devices)} devices.")
            self.btn_run.setText("Import Devices")
            self.btn_run.clicked.disconnect()
            self.btn_run.clicked.connect(self._accept_results)
        else:
            self._safe_log("\nDiscovery finished. No devices found.")

    def _accept_results(self):
        self.discovery_complete.emit(self.found_devices)
        self.accept()
