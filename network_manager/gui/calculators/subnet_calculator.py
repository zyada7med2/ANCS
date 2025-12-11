"""
Subnet calculator GUI for network planning
"""
import customtkinter as ctk
from tkinter import ttk, messagebox
import ipaddress


class SubnetCalculator(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Subnet Calculator")
        self.geometry("900x600")
        self.configure(fg_color="#13151b")

        ctk.CTkLabel(self, text="Subnet Calculator", font=("Segoe UI", 20, "bold"), text_color="#4ade80").pack(pady=10)

        # tab view
        self.tabs = ctk.CTkTabview(self, width=850, height=500, fg_color="#222736")
        self.tabs.pack(pady=10, expand=True)

        # tabs
        self.tab_info = self.tabs.add("Network Info")
        self.tab_dept = self.tabs.add("Departments")
        self.tab_result = self.tabs.add("Results")

        # --- network info tab ---
        ctk.CTkLabel(self.tab_info, text="Network (e.g. 192.168.10.0/24):", font=("Segoe UI", 14), text_color="#ffffff").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        self.entry_net = ctk.CTkEntry(self.tab_info, width=220, fg_color="#2b3040", border_color="#374151", text_color="#ffffff", corner_radius=8)
        self.entry_net.grid(row=0, column=1, padx=10)

        ctk.CTkLabel(self.tab_info, text="Number of Departments:", font=("Segoe UI", 14), text_color="#ffffff").grid(row=1, column=0, sticky="w", padx=10, pady=8)
        self.entry_dept = ctk.CTkEntry(self.tab_info, width=220, fg_color="#2b3040", border_color="#374151", text_color="#ffffff", corner_radius=8)
        self.entry_dept.grid(row=1, column=1, padx=10)

        ctk.CTkButton(self.tab_info, text="Next ➜", fg_color="#3b82f6", hover_color="#2563eb", text_color="#ffffff", corner_radius=8, command=self.create_dept_tab).grid(row=2, column=1, pady=20, sticky="e")

        # --- departments tab ---
        self.dept_frame = ctk.CTkScrollableFrame(self.tab_dept, fg_color="#222736", width=780, height=350)
        self.dept_frame.pack(pady=15)

        self.generate_btn = ctk.CTkButton(self.tab_dept, text="Generate Subnets", fg_color="#4ade80", hover_color="#22c55e", text_color="#13151b", corner_radius=8, command=self.calculate_subnets)
        self.generate_btn.pack(pady=10)

        # --- results tab ---
        self.result_frame = ctk.CTkFrame(self.tab_result, fg_color="#222736")
        self.result_frame.pack(fill="both", expand=True, pady=10, padx=10)

        self.dept_entries = []

    def create_dept_tab(self):
        """create department entry fields"""
        for widget in self.dept_frame.winfo_children():
            widget.destroy()
        self.dept_entries.clear()

        try:
            self.dept_count = int(self.entry_dept.get())
            if self.dept_count <= 0:
                raise ValueError
        except:
            messagebox.showerror("Error", "Invalid department count")
            return

        ctk.CTkLabel(self.dept_frame, text="Enter Department Info", font=("Segoe UI", 18, "bold"), text_color="#4ade80").pack(pady=10)

        for i in range(self.dept_count):
            row = ctk.CTkFrame(self.dept_frame, fg_color="transparent")
            row.pack(fill="x", pady=5)
            ctk.CTkLabel(row, text=f"Dept {i+1} Name:", width=100, text_color="#ffffff").pack(side="left", padx=6)
            name_entry = ctk.CTkEntry(row, width=180, fg_color="#2b3040", border_color="#374151", text_color="#ffffff", corner_radius=8)
            name_entry.pack(side="left", padx=6)
            ctk.CTkLabel(row, text="Hosts:", width=70, text_color="#ffffff").pack(side="left", padx=6)
            hosts_entry = ctk.CTkEntry(row, width=100, fg_color="#2b3040", border_color="#374151", text_color="#ffffff", corner_radius=8)
            hosts_entry.pack(side="left", padx=6)
            self.dept_entries.append((name_entry, hosts_entry))

        self.tabs.set("Departments")

    def calculate_subnets(self):
        """generate subnet info and show in results tab"""
        for widget in self.result_frame.winfo_children():
            widget.destroy()

        # validate network
        try:
            network = ipaddress.ip_network(self.entry_net.get(), strict=False)
        except:
            messagebox.showerror("Error", "Invalid network address")
            return

        dept_data = []
        for name_entry, hosts_entry in self.dept_entries:
            dept = name_entry.get().strip() or "Unnamed"
            try:
                hosts = int(hosts_entry.get())
            except:
                messagebox.showerror("Error", f"Invalid host count for {dept}")
                return
            dept_data.append((dept, hosts))

        dept_data.sort(key=lambda x: x[1], reverse=True)
        remaining = [network]

        columns = ("Department", "Network", "Mask", "Gateway", "Broadcast", "Usable Range")
        tree_res = ttk.Treeview(self.result_frame, columns=columns, show="headings", height=14)
        for c in columns:
            tree_res.heading(c, text=c)
            tree_res.column(c, width=130, anchor="center")
        tree_res.pack(fill="both", expand=True, padx=8, pady=8)

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
                messagebox.showerror("Error", f"No space for {dept}")
                continue

            hosts_list = list(alloc.hosts())
            gw = hosts_list[0] if hosts_list else "-"
            usable = f"{hosts_list[1]} - {hosts_list[-1]}" if len(hosts_list) > 2 else "-"

            tree_res.insert("", "end", values=(
                dept,
                str(alloc.network_address),
                str(alloc.netmask),
                str(gw),
                str(alloc.broadcast_address),
                usable
            ))

        self.tabs.set("Results")
        messagebox.showinfo("Done", "Subnet calculation complete ✅")

