"""
Text editor popup dialog
"""
import tkinter as tk
from ..utils import apply_responsive_geometry


class TextEditorPopup(tk.Toplevel):
    def __init__(self, parent, title="edit", initial=""):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        apply_responsive_geometry(self, 760, 480)
        self.result = None
        self.text = tk.Text(self, wrap="none", font=("Courier", 11))
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", initial)
        btnf = tk.Frame(self)
        btnf.pack(fill="x")
        tk.Button(btnf, text="save", bg="#3b82f6", fg="white", command=self.on_save).pack(side="right", padx=6, pady=6)
        tk.Button(btnf, text="cancel", bg="#374151", fg="#9ca3af", command=self.on_cancel).pack(side="right", padx=6, pady=6)
    
    def on_save(self):
        self.result = self.text.get("1.0", "end").rstrip()
        self.destroy()
    
    def on_cancel(self):
        self.result = None
        self.destroy()

