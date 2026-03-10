"""
VLAN configuration GUI wizard
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from ..utils import apply_responsive_geometry


class VlanGuiWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("vlan gui wizard")
        self.transient(parent)
        self.grab_set()
        apply_responsive_geometry(self, 700, 460)
        self.result = None
        frame = tk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        cols = ("vlan", "name", "ports")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=200, anchor="center")
        self.tree.pack(fill="both", expand=True)
        # Make cells editable on double-click
        self.tree.bind("<Double-1>", self.on_double_click)
        btns = tk.Frame(self)
        btns.pack(fill="x", pady=6)
        tk.Button(btns, text="add row", bg="#374151", fg="#9ca3af", command=self.add_row).pack(side="left", padx=6)
        tk.Button(btns, text="remove", bg="#374151", fg="#9ca3af", command=self.remove_sel).pack(side="left", padx=6)
        tk.Button(btns, text="generate", bg="#3b82f6", fg="white", command=self.on_generate).pack(side="right", padx=6)
        self.add_row()
    
    def on_double_click(self, event):
        """Make treeview cells editable on double-click - uses popup dialog"""
        region = self.tree.identify_region(event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)  # Fixed: only takes x coordinate
            item = self.tree.identify_row(event.y)
            if item and column:
                try:
                    col_index = int(column.replace("#", "")) - 1
                    if col_index >= 0:
                        self.edit_cell_popup(item, col_index)
                except Exception:
                    pass
    
    def edit_cell_popup(self, item, column):
        """Edit cell using a popup dialog"""
        cols = ("vlan", "name", "ports")
        col_name = cols[column] if column < len(cols) else f"Column {column+1}"
        values = self.tree.item(item)["values"]
        current_value = str(values[column]) if column < len(values) and values[column] else ""
        
        new_value = simpledialog.askstring("Edit Cell", f"Enter new value for {col_name}:", 
                                           initialvalue=current_value, parent=self)
        if new_value is not None:  # User didn't cancel
            values = list(self.tree.item(item)["values"])
            while len(values) <= column:
                values.append("")
            values[column] = new_value
            self.tree.item(item, values=values)
    
    def add_row(self):
        self.tree.insert("", "end", values=("", "", ""))
    
    def remove_sel(self):
        for s in self.tree.selection():
            self.tree.delete(s)
    
    def on_generate(self):
        items = self.tree.get_children()
        out = []
        port_start = 1
        try:
            for it in items:
                v, name, pc = self.tree.item(it)["values"]
                if not v:
                    messagebox.showerror("error", "enter vlan id")
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
        except:
            messagebox.showerror("error", "invalid numbers")
            return
        out.append("! vlan gui wizard complete")
        self.result = "\n".join(out)
        self.destroy()

