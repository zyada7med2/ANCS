"""
Workflows for Global Project State Sync and Global Configuration Backup.
"""
import sys
import threading
from typing import List, Tuple, Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QScrollArea, QWidget, QMessageBox, QProgressBar
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QColor

from ..network.puller import ConfigPuller
from ..config import conn, cur, db_lock

# Common UI Theme Constants
_BG = "#0D1117"
_PANEL = "#161B22"
_CARD = "#1F2630"
_ACCENT = "#58A6FF"
_GREEN = "#3fb950"
_TEXT = "#C9D1D9"
_MUTED = "#8B949E"
_BORDER = "#30363D"

_STYLE = f"""
    QDialog {{ background-color: {_BG}; color: {_TEXT}; font-family: 'Segoe UI'; }}
    QFrame[panel="true"] {{ background-color: {_PANEL}; border-radius: 8px; border: 1px solid {_BORDER}; }}
    QLabel {{ color: {_TEXT}; background: transparent; }}
    QLineEdit {{ background-color: {_CARD}; color: {_TEXT}; border: 1px solid {_BORDER}; border-radius: 4px; padding: 6px; }}
    QPushButton {{ background-color: #21262D; color: {_TEXT}; border: 1px solid {_BORDER}; border-radius: 6px; padding: 8px 16px; font-weight: bold; }}
    QPushButton:hover {{ background-color: #30363D; border-color: {_MUTED}; }}
    QPushButton[primary="true"] {{ background-color: #238636; border: 1px solid #2EA043; color: #FFFFFF; }}
    QPushButton[primary="true"]:hover {{ background-color: #2EA043; border-color: {_GREEN}; }}
    QProgressBar {{ border: 1px solid {_BORDER}; border-radius: 4px; background-color: {_CARD}; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background-color: {_ACCENT}; border-radius: 3px; }}
"""

class SyncWorkerSignals(QObject):
    progress = Signal(int, int)  # current, total
    log = Signal(str)
    finished = Signal(dict)

class BackupWorkerSignals(QObject):
    progress = Signal(int, int)
    finished = Signal()

def _run_threaded(target, *args):
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t

class ProjectSyncDialog(QDialog):
    """
    Dialog asking the user to Start Fresh (Local templates) or Pull Live Defaults.
    """
    def __init__(self, parent, devices):
        super().__init__(parent)
        self.devices = devices
        self.result_chosen = None # "fresh" or "pull"
        self.setWindowTitle("Project Configuration Setup")
        self.setMinimumWidth(500)
        self.setStyleSheet(_STYLE)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        lbl = QLabel("How would you like to build this project's configurations?")
        lbl.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(lbl)
        
        # Fresh
        f_card = QFrame()
        f_card.setProperty("panel", True)
        f_lay = QVBoxLayout(f_card)
        l1 = QLabel("Build New Network (Start Fresh)")
        l1.setStyleSheet("font-size: 14px; font-weight: bold;")
        l2 = QLabel("Start with blank templates. Recommended for designing brand new topologies \nwhere you want ANCS to automatically generate IPs and subnets.")
        l2.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        btn_fresh = QPushButton("Select: Start Fresh")
        btn_fresh.clicked.connect(self._select_fresh)
        f_lay.addWidget(l1)
        f_lay.addWidget(l2)
        f_lay.addWidget(btn_fresh, alignment=Qt.AlignRight)
        layout.addWidget(f_card)
        
        # Pull Existing
        p_card = QFrame()
        p_card.setProperty("panel", True)
        p_lay = QVBoxLayout(p_card)
        l3 = QLabel("Manage Existing Network (Pull Live Config)")
        l3.setStyleSheet("font-size: 14px; font-weight: bold;")
        l4 = QLabel("Connects to the GNS3 nodes and extracts their currently running configurations.\nGuided Setup will use these configurations directly instead of overwriting them.")
        l4.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        
        form_row = QHBoxLayout()
        form_row.addWidget(QLabel("Default Username (Optional):"))
        self.user_var = QLineEdit()
        form_row.addWidget(self.user_var)
        form_row.addWidget(QLabel("Password (Optional):"))
        self.pass_var = QLineEdit()
        self.pass_var.setEchoMode(QLineEdit.Password)
        form_row.addWidget(self.pass_var)
        p_lay.addWidget(l3)
        p_lay.addWidget(l4)
        p_lay.addLayout(form_row)
        
        btn_pull = QPushButton("Select: Pull Live Config")
        btn_pull.setProperty("primary", True)
        btn_pull.clicked.connect(self._select_pull)
        p_lay.addWidget(btn_pull, alignment=Qt.AlignRight)
        layout.addWidget(p_card)
        
        # Log / Progress area
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {_MUTED};")
        self.status_lbl.hide()
        layout.addWidget(self.status_lbl)
        
        self.pbar = QProgressBar()
        self.pbar.hide()
        layout.addWidget(self.pbar)

    def _select_fresh(self):
        self.result_chosen = "fresh"
        self.accept()

    def _select_pull(self):
        from PySide6.QtWidgets import QApplication
        
        # Filter for actual nodes
        nodes = [d for d in self.devices if d[2].get('console_host')]
        if not nodes:
            QMessageBox.warning(self, "No Devices", "No GNS3 devices with console ports found to pull from.")
            return
            
        self.status_lbl.setText("Connecting to background devices...")
        self.status_lbl.show()
        self.pbar.setMaximum(len(nodes))
        self.pbar.setValue(0)
        self.pbar.show()
        
        self.signals = SyncWorkerSignals()
        self.signals.progress.connect(self._update_progress)
        self.signals.log.connect(self.status_lbl.setText)
        self.signals.finished.connect(self._on_pull_finished)
        
        # Start puller thread
        user = self.user_var.text().strip()
        pw = self.pass_var.text().strip()
        _run_threaded(self._worker_pull, nodes, user, pw)

    def _update_progress(self, current, total):
        self.pbar.setValue(current)

    def _worker_pull(self, nodes, username, password):
        import concurrent.futures
        results = {}
        completed = 0
        total = len(nodes)
        
        # Parallel fetch logic
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_node = {}
            for node in nodes:
                name, model, meta = node
                host = meta.get('console_host', 'localhost')
                port = int(meta.get('console_port', 23))
                future = executor.submit(ConfigPuller.pull_sync, host, port, username, password, "")
                future_to_node[future] = name
                
            for future in concurrent.futures.as_completed(future_to_node):
                name = future_to_node[future]
                completed += 1
                try:
                    data = future.result()
                    results[name] = data
                    verdict = "[Blank]" if data.get("is_blank") else "[Configured]"
                    reason = data.get("reason", "")
                    self.signals.log.emit(f"{name}: {verdict} - {reason}")
                except Exception as e:
                    results[name] = {"error": str(e), "config": "", "is_blank": True}
                    self.signals.log.emit(f"Failed {name} ({str(e)})")
                self.signals.progress.emit(completed, total)
        
        self.signals.finished.emit(results)
        
    def _on_pull_finished(self, results):
        from ..network.parser import IOSParser
        self.result_chosen = "pull"
        self.discovered_hostnames = []
        
        # We store the results into the internal models
        for i, node in enumerate(self.devices):
            name, model, meta = node
            if name in results:
                info = results[name]
                if not info.get("error") and not info.get("is_blank"):
                    config_text = info["config"]
                    model.templates["live_pulled_config"] = config_text
                    
                    # Parse the live config into a structured state
                    try:
                        model.state = IOSParser.parse_config(config_text)
                    except Exception as pe:
                        print(f"DEBUG: Failed to parse {name}: {pe}")
                    
                    # Update the internal name if a distinct hostname was found
                    found_hostname = info.get("hostname", "")
                    if found_hostname and found_hostname.lower() not in ("router", "switch", name.lower()):
                        # We append it to our summary list
                        self.discovered_hostnames.append(found_hostname)
                        # Optionally rename the model representation
                        model.name = found_hostname
                        # Updating the immutable tuple in self.devices requires reassignment
                        self.devices[i] = (found_hostname, model, meta)
                    else:
                        self.discovered_hostnames.append(name)
                        
        # Allow the UI to close
        self.accept()
