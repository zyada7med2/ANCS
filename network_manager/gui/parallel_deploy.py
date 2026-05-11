import time
import threading
import concurrent.futures
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, 
    QTableWidgetItem, QCheckBox, QLabel, QWidget, QMessageBox, QHeaderView
)
from PySide6.QtCore import Qt, QTimer

from network_manager.network.sender import Sender
from network_manager.config import cur, db_lock, conn

class ParallelDeployDialog(QDialog):
    """
    Dialog for parallel deployment of configurations.
    Allows user to select devices and deploy concurrently.
    """
    def __init__(self, parent_app, deploy_list):
        super().__init__(parent_app)
        self.parent_app = parent_app
        self.deploy_list = deploy_list
        self._cancel_flag = False
        self._active = False
        
        self.setWindowTitle("Parallel Bulk Deploy")
        self.resize(900, 600)
        if hasattr(parent_app, "_dialog_style"):
            self.setStyleSheet(parent_app._dialog_style())

        self._build_ui()
        self._populate_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        lbl = QLabel("Select devices to deploy configurations concurrently.")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #C9D1D9;")
        layout.addWidget(lbl)

        # Controls
        ctrl_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_deselect_all.clicked.connect(self._deselect_all)
        
        ctrl_layout.addWidget(self.btn_select_all)
        ctrl_layout.addWidget(self.btn_deselect_all)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Device", "Status", "Details"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        if hasattr(self.parent_app, "_style_table_widget"):
            self.parent_app._style_table_widget(self.table)
        layout.addWidget(self.table)

        # Action Buttons
        action_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start Deployment")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                color: #FFFFFF;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #2EA043; }
            QPushButton:disabled { background-color: #1A401A; color: #888888; }
        """)
        self.btn_start.clicked.connect(self._start_deploy)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #DA3633;
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                color: #FFFFFF;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #F85149; }
            QPushButton:disabled { background-color: #552020; color: #888888; }
        """)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_deploy)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)

        action_layout.addStretch()
        action_layout.addWidget(self.btn_stop)
        action_layout.addWidget(self.btn_start)
        action_layout.addWidget(self.btn_close)
        layout.addLayout(action_layout)

    def _populate_table(self):
        self.table.setRowCount(len(self.deploy_list))
        for i, item in enumerate(self.deploy_list):
            name, model, meta, host, port, user, pw, enable, status = item
            
            # Checkbox widget
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb = QCheckBox()
            # Only enable if status is "ready"
            if status != "ready":
                cb.setEnabled(False)
                cb.setChecked(False)
            else:
                cb.setChecked(True)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 0, cb_widget)

            # Labels
            self.table.setItem(i, 1, QTableWidgetItem(name))
            self.table.setItem(i, 2, QTableWidgetItem(status))
            if status == "ready":
                self.table.setItem(i, 3, QTableWidgetItem(f"target={host}:{port}"))
            else:
                self.table.setItem(i, 3, QTableWidgetItem(status))

    def _select_all(self):
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 0)
            if w:
                cb = w.layout().itemAt(0).widget()
                if cb.isEnabled():
                    cb.setChecked(True)

    def _deselect_all(self):
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 0)
            if w:
                cb = w.layout().itemAt(0).widget()
                if cb.isEnabled():
                    cb.setChecked(False)

    def _start_deploy(self):
        self._cancel_flag = False
        self._active = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_close.setEnabled(False)
        self.btn_select_all.setEnabled(False)
        self.btn_deselect_all.setEnabled(False)

        # Collect checked devices
        jobs = []
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 0)
            if w:
                cb = w.layout().itemAt(0).widget()
                if cb.isChecked() and cb.isEnabled():
                    jobs.append((row, self.deploy_list[row]))
                    cb.setEnabled(False) # lock it

        if not jobs:
            self._finish_deploy()
            return

        def run_all():
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(jobs))) as executor:
                futures = []
                for idx, (row, item) in enumerate(jobs):
                    if self._cancel_flag:
                        break
                    # We pass 'idx' so the worker can do a staggered delay
                    futures.append(executor.submit(self._worker, idx, row, item))

                for f in concurrent.futures.as_completed(futures):
                    pass
            self.parent_app._run_on_main(self._finish_deploy)

        threading.Thread(target=run_all, daemon=True).start()

    def _worker(self, index, row, item):
        if self._cancel_flag:
            self.parent_app._run_on_main(lambda r=row: self.table.setItem(r, 2, QTableWidgetItem("Cancelled")))
            return

        name, model, meta, host, port, user, pw, enable, status = item
        config = model.build_full_config().strip()

        # Staggered start delay (e.g. 1.5 seconds per index)
        # This keeps hierarchy processing somewhat preserved while running concurrently
        delay = index * 1.5
        if delay > 0:
            self.parent_app._run_on_main(lambda r=row: self.table.setItem(r, 2, QTableWidgetItem(f"Waiting ({delay}s)...")))
            
            # Smart delay loop so it can be interrupted if stopped
            slept = 0.0
            while slept < delay:
                if self._cancel_flag:
                    self.parent_app._run_on_main(lambda r=row: self.table.setItem(r, 2, QTableWidgetItem("Cancelled")))
                    return
                time.sleep(0.5)
                slept += 0.5

        if self._cancel_flag:
            self.parent_app._run_on_main(lambda r=row: self.table.setItem(r, 2, QTableWidgetItem("Cancelled")))
            return

        self.parent_app._run_on_main(lambda r=row: self.table.setItem(r, 2, QTableWidgetItem("Deploying...")))
        
        try:
            # Get vendor-correct session config from the device model
            from network_manager.vendors import get_profile
            _vendor_id = getattr(model, "vendor_id", "cisco_ios")
            _sc = get_profile(_vendor_id).session_config()
            ok = Sender.send_telnet(self.parent_app.log, host, port, user, pw, enable, config, session_config=_sc)
            result = "Success" if ok else "Failed"
            detail = f"target={host}:{port}" if ok else "Send failed; check Logs tab"
            if ok:
                self.parent_app._write_audit_log(name, "parallel-deploy", f"host={host}:{port}", config_content=config)
        except Exception as e:
            result = f"Error"
            detail = str(e)

        self.parent_app._run_on_main(lambda r=row, s=result: self.table.setItem(r, 2, QTableWidgetItem(s)))
        self.parent_app._run_on_main(lambda r=row, d=detail: self.table.setItem(r, 3, QTableWidgetItem(d)))

    def _stop_deploy(self):
        self._cancel_flag = True
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Stopping...")

    def _finish_deploy(self):
        self._active = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Stop")
        self.btn_close.setEnabled(True)
        self.btn_select_all.setEnabled(True)
        self.btn_deselect_all.setEnabled(True)
        
        # Unlock checkboxes that didn't run, or all checkboxes if they want to run again? 
        # Usually it's better to leave them locked if success, but we'll uncheck everything.
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 0)
            if w:
                cb = w.layout().itemAt(0).widget()
                status_item = self.table.item(row, 2)
                if status_item and status_item.text() == "Success":
                    cb.setChecked(False)
                # Re-enable all if the status hasn't fundamentally broken
                if status_item and status_item.text() not in ("Waiting", "Deploying..."):
                    cb.setEnabled(True)

    def closeEvent(self, event):
        if self._active:
            QMessageBox.warning(self, "Warning", "Please stop the deployment before closing.")
            event.ignore()
        else:
            event.accept()
