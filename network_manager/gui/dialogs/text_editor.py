"""
Text editor popup dialog — PySide6 version
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
)
from PySide6.QtCore import Qt
from ..utils import apply_responsive_geometry

DARK_STYLE = """
    QDialog { background-color: #0D1117; }
    QPlainTextEdit {
        background-color: #161B22;
        color: #C9D1D9;
        border: 1px solid #30363D;
        border-radius: 6px;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 12px;
        padding: 6px;
    }
    QPushButton {
        background-color: #374151;
        color: #9ca3af;
        border: none;
        border-radius: 6px;
        padding: 6px 16px;
        font-size: 13px;
    }
    QPushButton:hover { background-color: #4b5563; color: white; }
    QPushButton#save { background-color: #3b82f6; color: white; }
    QPushButton#save:hover { background-color: #2563eb; }
"""


class TextEditorPopup(QDialog):
    def __init__(self, parent, title="edit", initial=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(DARK_STYLE)
        apply_responsive_geometry(self, 760, 480)
        self.result = None

        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setPlainText(initial)
        layout.addWidget(self.text, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.on_cancel)
        btns.addWidget(btn_cancel)
        btn_save = QPushButton("Save")
        btn_save.setObjectName("save")
        btn_save.clicked.connect(self.on_save)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

    def on_save(self):
        self.result = self.text.toPlainText().rstrip()
        self.accept()

    def on_cancel(self):
        self.result = None
        self.reject()
