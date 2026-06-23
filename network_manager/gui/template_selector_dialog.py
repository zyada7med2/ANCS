"""
template_selector_dialog.py — GNS3 Template Selector Dialog

Allows the user to select templates for GNS3 nodes interactively when they are not configured,
with an option to save the selections to gns3_template_mappings.json.

Usage:
    from network_manager.gui.template_selector_dialog import request_template_selection
    mappings = request_template_selection(
        roles=["router", "core", "switch"],
        available_templates=[{"name": "c7200", "template_id": "..."}, ...],
        current_mappings={"router": "", "core": "", "switch": ""}
    )
"""

import os
import json
import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame, QApplication
)
from PySide6.QtCore import Qt, Signal, Slot, QObject, QThread


class TemplateSelectorDialog(QDialog):
    """Modal dialog for choosing GNS3 templates for required network roles."""

    def __init__(self, roles: list[str], available_templates: list[dict], current_mappings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GNS3 Template Selection")
        self.setMinimumSize(500, 320)
        self.setModal(True)

        self._approved = False
        self._selected_mappings = {}
        self._remember = True

        self._roles = roles
        self._available_templates = available_templates
        self._current_mappings = current_mappings

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Header
        header = QLabel("🔧 <b>GNS3 Template Selection</b>")
        header.setStyleSheet("font-size: 16px; color: #58A6FF; padding: 5px;")
        layout.addWidget(header)

        info_label = QLabel(
            "The AI Copilot needs to spawn virtual nodes. Please assign a GNS3 template "
            "for each required device role below:"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #8b949e; padding: 0 5px;")
        layout.addWidget(info_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #30363d;")
        layout.addWidget(sep)

        # Grid of roles and combo boxes
        self._combos = {}
        template_names = [t.get("name", "") for t in available_templates if t.get("name")]
        template_names = sorted(list(set(template_names)))

        form_layout = QVBoxLayout()
        form_layout.setSpacing(12)

        for role in roles:
            row_layout = QHBoxLayout()
            
            # Role label
            role_title = role.upper()
            if role == "core":
                role_title = "CORE SWITCH"
            elif role == "switch":
                role_title = "ACCESS SWITCH"
            
            lbl = QLabel(f"<b>{role_title}:</b>")
            lbl.setStyleSheet("color: #c9d1d9; min-width: 120px;")
            row_layout.addWidget(lbl)

            # ComboBox
            combo = QComboBox()
            combo.addItems(template_names)
            combo.setStyleSheet("""
                QComboBox {
                    background-color: #0d1117;
                    color: #c9d1d9;
                    border: 1px solid #30363d;
                    border-radius: 6px;
                    padding: 6px;
                    min-height: 25px;
                }
                QComboBox QAbstractItemView {
                    background-color: #0d1117;
                    color: #c9d1d9;
                    selection-background-color: #21262d;
                }
            """)
            
            # Guess default selection
            default_val = current_mappings.get(role, "")
            if not default_val:
                default_val = self._guess_template_for_role(role, template_names)
            
            if default_val in template_names:
                combo.setCurrentText(default_val)
            elif template_names:
                combo.setCurrentIndex(0)

            row_layout.addWidget(combo, stretch=1)
            form_layout.addLayout(row_layout)
            self._combos[role] = combo

        layout.addLayout(form_layout)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #30363d;")
        layout.addWidget(sep2)

        # Remember mappings checkbox
        self._remember_cb = QCheckBox("Save these selections to GNS3 Template Mappings")
        self._remember_cb.setChecked(True)
        self._remember_cb.setStyleSheet("""
            QCheckBox {
                color: #8b949e;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        layout.addWidget(self._remember_cb)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("✖  Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                color: #f85149;
                border: 1px solid #f85149;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #3b1d23;
            }
        """)
        cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton("✔  Confirm")
        confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: white;
                border: 1px solid #2ea043;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_layout.addWidget(confirm_btn)

        layout.addLayout(btn_layout)

        self.setStyleSheet("QDialog { background-color: #161b22; }")

    def _guess_template_for_role(self, role: str, names: list[str]) -> str:
        """Heuristic guessing for GNS3 templates based on name string matches."""
        role_lower = role.lower()
        
        # Define keywords matching Component 2 logic
        router_kws = ("iosv", "c7200", "c3725", "router")
        core_kws = ("l3", "layer3", "layer 3", "ioul3", "multilayer", "esw")
        switch_kws = ("iosvl2", "switch", "ioul2", "l2", "esw", "layer 2", "layer2")

        for name in names:
            name_lower = name.lower()
            if role_lower == "router" and any(k in name_lower for k in router_kws):
                return name
            elif role_lower == "core" and any(k in name_lower for k in core_kws):
                return name
            elif role_lower in ("switch", "access") and any(k in name_lower for k in switch_kws):
                # Ensure if it's access switch, it doesn't accidentally grab a core switch template first
                if "l3" in name_lower or "layer3" in name_lower or "layer 3" in name_lower:
                    continue
                return name
        return ""

    def _on_confirm(self):
        self._approved = True
        self._selected_mappings = {role: combo.currentText() for role, combo in self._combos.items()}
        self._remember = self._remember_cb.isChecked()
        self.accept()

    def _on_cancel(self):
        self._approved = False
        self.reject()

    @property
    def approved(self) -> bool:
        return self._approved

    @property
    def selected_mappings(self) -> dict[str, str]:
        return self._selected_mappings

    @property
    def remember(self) -> bool:
        return self._remember


class _TemplateBridge(QObject):
    """
    Bridge enabling CopilotWorker thread to prompt TemplateSelectorDialog modal
    on the main GUI thread and safely block until the user selects options.
    """
    _trigger = Signal()

    def __init__(self):
        super().__init__()
        self._roles = []
        self._available_templates = []
        self._current_mappings = {}
        self._result = None
        self._done = threading.Event()
        self._trigger.connect(self._show_dialog, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _show_dialog(self):
        try:
            dialog = TemplateSelectorDialog(
                self._roles, self._available_templates, self._current_mappings
            )
            dialog.exec()
            if dialog.approved:
                self._result = {
                    "mappings": dialog.selected_mappings,
                    "remember": dialog.remember
                }
            else:
                self._result = None
        except Exception as e:
            print(f"Error showing template selector dialog: {e}")
            self._result = None
        finally:
            self._done.set()


# Singleton bridge instance
_bridge = None
_bridge_lock = threading.Lock()


def _get_bridge() -> _TemplateBridge:
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = _TemplateBridge()
            app = QApplication.instance()
            if app:
                _bridge.moveToThread(app.thread())
        return _bridge


def request_template_selection(
    roles: list[str],
    available_templates: list[dict],
    current_mappings: dict
) -> dict[str, str] | None:
    """
    Prompt the user to assign a GNS3 template for each role.
    Thread-safe — blocks the worker thread and runs dialog on the main GUI thread.

    Returns:
        Dictionary of {role: template_name} if confirmed, or None if cancelled.
    """
    app = QApplication.instance()
    if not app:
        # Fallback for non-GUI execution
        return None

    if QThread.currentThread() == app.thread():
        dialog = TemplateSelectorDialog(roles, available_templates, current_mappings)
        dialog.exec()
        if dialog.approved:
            if dialog.remember:
                _save_mappings(dialog.selected_mappings)
            return dialog.selected_mappings
        return None

    bridge = _get_bridge()
    bridge._roles = list(roles)
    bridge._available_templates = list(available_templates)
    bridge._current_mappings = dict(current_mappings)
    bridge._result = None
    bridge._done.clear()

    # Emit signal to trigger dialog on main thread
    bridge._trigger.emit()

    # Block worker thread for up to 5 minutes
    bridge._done.wait(timeout=300)

    if bridge._result:
        mappings = bridge._result["mappings"]
        remember = bridge._result["remember"]
        if remember:
            _save_mappings(mappings)
        return mappings
    return None


def _save_mappings(selected_mappings: dict):
    """Write selections back to gns3_template_mappings.json."""
    try:
        from network_manager.config import _BASE_DIR
        mapping_file = os.path.join(_BASE_DIR, "gns3_template_mappings.json")
        
        # Load existing mapping if present to merge
        mappings = {"router": "", "core": "", "switch": ""}
        if os.path.exists(mapping_file):
            try:
                with open(mapping_file, "r", encoding="utf-8") as f:
                    mappings.update(json.load(f))
            except Exception:
                pass
                
        mappings.update(selected_mappings)
        
        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump(mappings, f, indent=2)
            
        print(f"GNS3 template mappings saved successfully to {mapping_file}")
    except Exception as e:
        print(f"Failed to save GNS3 template mappings: {e}")
