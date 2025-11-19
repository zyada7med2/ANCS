"""
Guided multi-step setup wizard to assist non-experts through configuration
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from dataclasses import dataclass
from typing import Callable, List, Dict, Any, Optional


@dataclass
class Step:
    title: str
    description: str
    build_ui: Callable[['GuidedSetupWizard', tk.Frame], None]
    validate: Callable[['GuidedSetupWizard'], bool]


class GuidedSetupWizard(tk.Toplevel):
    """
    High-level wizard that walks users through a recommended order:
    1. Welcome
    2. Identity & security
    3. VLAN grouping
    4. Gateway routing (SVIs)
    5. DHCP pools
    6. Access control
    7. Summary / save
    """

    def __init__(self, parent, device_name: str, device_model, device_role: str = "router"):
        super().__init__(parent)
        self.title("Guided Setup (Beginner Friendly)")
        self.geometry("900x560")
        self.resizable(False, False)
        self.parent = parent
        self.device_name = device_name
        self.device_model = device_model
        self.device_role = device_role  # "router", "core", or "access"
        self.routing_mode = "device"  # "device" means this device routes SVIs, "external" means router handles it

        # data buckets collected across steps
        self.identity_data: Dict[str, str] = {}
        self.vlans: List[Dict[str, str]] = []
        self.routing_entries: List[Dict[str, str]] = []
        self.dhcp_pools: List[Dict[str, str]] = []
        self.acl_rules: List[Dict[str, str]] = []
        self.uplinks: List[Dict[str, str]] = []
        self.summary_box: Optional[tk.Text] = None

        self.current_step = 0
        self.steps: List[Step] = []

        self._prompt_routing_mode()
        self._build_steps()
        self._build_layout()
        self._render_step()
    def _prompt_routing_mode(self):
        if self.device_role == "access":
            self.routing_mode = "external"
            return
        dialog = tk.Toplevel(self)
        dialog.title("Routing responsibility")
        dialog.geometry("420x220")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text="Who routes between VLANs for this network?", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(dialog, text="Pick the option that matches your design. You can change it later per device.", wraplength=380, justify="left").pack(anchor="w", padx=12)

        choice = tk.StringVar(value="device")
        tk.Radiobutton(dialog, text="This device handles inter-VLAN routing (SVIs here).", variable=choice, value="device", anchor="w", justify="left", wraplength=360).pack(fill="x", padx=20, pady=(8, 4))
        tk.Radiobutton(dialog, text="A separate router handles routing (this device stays Layer 2).", variable=choice, value="external", anchor="w", justify="left", wraplength=360).pack(fill="x", padx=20, pady=(0, 8))

        def confirm():
            self.routing_mode = choice.get()
            dialog.destroy()

        tk.Button(dialog, text="Continue", command=confirm).pack(pady=8)
        dialog.protocol("WM_DELETE_WINDOW", confirm)
        self.wait_window(dialog)

    # -------------------------- layout --------------------------
    def _build_layout(self):
        container = tk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        sidebar = tk.Frame(container, width=220)
        sidebar.pack(side="left", fill="y", padx=(0, 10))
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Guided Playbook", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 8))
        role_map = {
            "router": "Router / Gateway (routing + DHCP)",
            "core": "Core Switch (routing, no DHCP)",
            "access": "Access Switch (Layer 2)",
        }
        role = role_map.get(self.device_role, "Device")
        routing_note = "Routing here" if self.routing_mode == "device" else "Routing on separate router"
        tk.Label(sidebar, text=f"Device: {self.device_name}\nRole: {role}\nMode: {routing_note}", justify="left", fg="#7ab").pack(anchor="w", pady=(0, 10))

        self.listbox = tk.Listbox(sidebar, activestyle="none")
        self.listbox.pack(fill="both", expand=True)
        for step in self.steps:
            self.listbox.insert("end", step.title)

        self.listbox.select_set(0)

        self.content = tk.Frame(container, relief="groove", bd=1)
        self.content.pack(side="left", fill="both", expand=True)

        nav = tk.Frame(self)
        nav.pack(fill="x", padx=10, pady=(0, 10))

        self.lbl_status = tk.Label(nav, text="")
        self.lbl_status.pack(side="left")

        self.btn_back = tk.Button(nav, text="Back", command=self.prev_step, state="disabled")
        self.btn_back.pack(side="right", padx=5)

        self.btn_next = tk.Button(nav, text="Next", command=self.next_step)
        self.btn_next.pack(side="right", padx=5)

    def _build_steps(self):
        self.steps = [
            Step(
                "Welcome",
                "We’ll walk through the recommended order so your network works the first time.",
                GuidedSetupWizard._build_step_welcome,
                lambda self: True,
            ),
            Step(
                "Name & Lock",
                "Give the device a name and secure access before anything else.",
                GuidedSetupWizard._build_step_identity,
                GuidedSetupWizard._validate_identity,
            ),
        ]

        if self.device_role in ("core", "access"):
            self.steps.append(
                Step(
                    "Group Devices (VLANs)",
                    "Create VLANs so rooms or roles stay separated.",
                    GuidedSetupWizard._build_step_vlans,
                    GuidedSetupWizard._validate_vlans,
                )
            )

        if self.device_role == "router":
            self.steps.extend(
                [
                    Step(
                        "DHCP Pools",
                        "Hand out IPs to end devices automatically.",
                        GuidedSetupWizard._build_step_dhcp,
                        GuidedSetupWizard._validate_dhcp,
                    ),
                    Step(
                        "Access Rules",
                        "Control who can reach what. Start with simple allow/block rules.",
                        GuidedSetupWizard._build_step_acl,
                        GuidedSetupWizard._validate_acl,
                    ),
                ]
            )
        elif self.device_role == "core":
            self.steps.extend(
                [
                    Step(
                        "Gateway / Routing",
                        "Assign IP gateways (SVIs) so VLANs can talk when needed.",
                        GuidedSetupWizard._build_step_routing,
                        GuidedSetupWizard._validate_routing,
                    ),
                    Step(
                        "Access Rules",
                        "Control who can reach what. Start with simple allow/block rules.",
                        GuidedSetupWizard._build_step_acl,
                        GuidedSetupWizard._validate_acl,
                    ),
                ]
            )
        else:
            self.steps.extend(
                [
                    Step(
                        "Uplinks & Trunks",
                        "Tell the switch which ports connect to other switches/routers.",
                        GuidedSetupWizard._build_step_uplinks,
                        GuidedSetupWizard._validate_uplinks,
                    ),
                    Step(
                        "Access ACLs (Optional)",
                        "Lightweight filtering on this switch only (does not replace gateway ACLs).",
                        GuidedSetupWizard._build_step_acl_access,
                        GuidedSetupWizard._validate_acl,
                    ),
                ]
            )

        self.steps.append(
            Step(
                "Summary & Save",
                "Review everything and send back to the main window.",
                GuidedSetupWizard._build_step_summary,
                GuidedSetupWizard._validate_summary,
            )
        )

    # -------------------------- step render --------------------------
    def _render_step(self):
        for child in self.content.winfo_children():
            child.destroy()

        step = self.steps[self.current_step]
        self.listbox.select_clear(0, "end")
        self.listbox.select_set(self.current_step)

        tk.Label(self.content, text=step.title, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(self.content, text=step.description, wraplength=600, justify="left", fg="#566").pack(anchor="w", padx=12)

        body = tk.Frame(self.content)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        step.build_ui(self, body)
        self._update_nav()

    def _update_nav(self):
        self.btn_back.config(state="normal" if self.current_step > 0 else "disabled")
        if self.current_step == len(self.steps) - 1:
            self.btn_next.config(text="Finish")
        else:
            self.btn_next.config(text="Next")
        self.lbl_status.config(text=f"Step {self.current_step + 1} of {len(self.steps)}")

    # -------------------------- navigation --------------------------
    def next_step(self):
        if not self.steps[self.current_step].validate(self):
            return
        if self.current_step == len(self.steps) - 1:
            self._write_templates()
            self.destroy()
            return
        self.current_step += 1
        self._render_step()

    def prev_step(self):
        if self.current_step == 0:
            return
        self.current_step -= 1
        self._render_step()

    # -------------------------- specific step builders --------------------------
    def _build_step_welcome(self, body):
        tk.Label(body, text="What we’ll do:", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        if self.device_role == "router":
            text = (
                "1. Name the device and lock it down.\n"
                "2. Group ports into friendly names (VLANs).\n"
                "3. Give each group a gateway IP so traffic knows where to go.\n"
                "4. Turn on DHCP so laptops/phones get addresses.\n"
                "5. Add quick allow/block rules that protect the network edge.\n\n"
                "Everything you enter gets previewed in the main window so you stay in control."
            )
        elif self.device_role == "core":
            text = (
                "1. Name the core switch and secure logins.\n"
                "2. Group ports into VLANs for each room/team.\n"
                "3. Assign SVI gateway IPs so VLANs can talk here.\n"
                "4. Add quick ACLs to protect the campus core.\n\n"
                "Reminder: DHCP runs on your router or server—run the router wizard next to hand out addresses."
            )
        else:
            text = (
                "1. Name the switch and secure logins.\n"
                "2. Group edge ports into VLANs for each room/team.\n"
                "3. Mark uplink/trunk ports so VLAN tags reach the core.\n"
                "4. (Optional) Add simple ACLs to limit traffic on this switch only.\n\n"
                "Your gateway/router still handles routing, DHCP, and deep security—this step keeps the access layer tidy."
            )
        tk.Label(body, text=text, justify="left").pack(anchor="w")

    def _build_step_identity(self, body):
        form = tk.Frame(body)
        form.pack(anchor="w")

        self.entry_hostname = self._add_labeled_entry(form, "Hostname", self.identity_data.get("hostname", self.device_name))
        self.entry_domain = self._add_labeled_entry(form, "Domain (optional)", self.identity_data.get("domain", ""))
        self.entry_enable = self._add_labeled_entry(form, "Enable secret", self.identity_data.get("enable", ""))

    def _build_step_vlans(self, body):
        # Set tip and defaults based on device role
        if self.device_role == "access":  # Layer 2 IOU switch
            tip_text = "Tip: Use 'Ethernet0/0-3' or 'Et0/0-3' for IOU L2 switches. Multi-module: 'Et0/0-3,Et1/0-3'"
            default_ports = "Ethernet0/0-3"
        else:  # Layer 3 / Core switch
            # Match EtherSwitch ESW1 layout: Fa1/1-15 access ports
            tip_text = "Tip: Use 'FastEthernet1/1-15' or 'Fa1/1-15' for access ports on ESW modules."
            default_ports = "FastEthernet1/1-15"
        
        tk.Label(body, text=tip_text, fg="#555", font=("", 9, "italic")).pack(anchor="w", pady=(0, 5))
        self.vlan_tree = self._build_tree(body, ("ID", "Name", "Ports"), self.vlans, default_values=("10", "Staff", default_ports))

    def _build_step_routing(self, body):
        tip = "Tip: Match VLAN IDs from the previous step. IP mask uses slash or dotted format."
        tk.Label(body, text=tip, fg="#555").pack(anchor="w")
        if self.routing_mode == "device":
            self.route_tree = self._build_tree(body, ("VLAN", "IP", "Mask"), self.routing_entries, default_values=("10", "192.168.10.1", "255.255.255.0"))
        else:
            tk.Label(body, text="This device is not handling routing. Use your router wizard to configure subinterfaces/SVIs there.", wraplength=600, justify="left", fg="#888").pack(anchor="w", pady=10)

    def _build_step_dhcp(self, body):
        self.dhcp_tree = self._build_tree(
            body,
            ("Pool", "Network", "Mask", "Gateway", "DNS", "Start", "End"),
            self.dhcp_pools,
            default_values=("Staff", "192.168.10.0", "255.255.255.0", "192.168.10.1", "8.8.8.8", "192.168.10.50", "192.168.10.200"),
        )

    def _build_step_acl(self, body):
        self._build_acl_section(body, "Example rule: allow staff to servers, block guests to LAN.")

    def _build_step_acl_access(self, body):
        note = "These ACLs filter traffic only on this switch (per-port or VLAN). Gateway devices still enforce inter-VLAN/WAN rules."
        self._build_acl_section(body, note)

    def _build_step_uplinks(self, body):
        tip = "Tell us which ports connect to other switches/routers so we can configure trunks."
        tk.Label(body, text=tip, fg="#555").pack(anchor="w")
        
        # Set defaults based on device role
        if self.device_role == "access":  # Layer 2 IOU switch
            tip_text = "Tip: Use 'Ethernet3/3' or 'Et3/3' for single uplink ports."
            default_port = "Ethernet3/3"
        else:  # Layer 3 / Core switch
            # Match EtherSwitch ESW1 layout: Fa1/0 as typical uplink
            tip_text = "Tip: Use 'FastEthernet1/0' or 'Fa1/0' for uplink ports on ESW modules."
            default_port = "FastEthernet1/0"
        
        tk.Label(body, text=tip_text, fg="#555", font=("", 9, "italic")).pack(anchor="w", pady=(0, 5))
        self.uplink_tree = self._build_tree(
            body,
            ("Ports", "Mode", "Allowed VLANs"),
            self.uplinks,
            default_values=(default_port, "trunk", "all"),
        )

    def _build_step_summary(self, body):
        if self.summary_box is None:
            self.summary_box = tk.Text(body, wrap="word")
            self.summary_box.pack(fill="both", expand=True)
        self._refresh_summary()

    def _build_acl_section(self, body, tip_text):
        tk.Label(body, text=tip_text, fg="#555", wraplength=600, justify="left").pack(anchor="w")
        tk.Label(body, text="Using standard ACLs (source-only filtering). For advanced rules, edit manually after.", fg="#888", wraplength=600, justify="left").pack(anchor="w", pady=(0, 8))
        self.acl_tree = self._build_tree(
            body,
            ("ACL #", "Action", "Source", "Wildcard", "Remark"),
            self.acl_rules,
            default_values=("10", "permit", "192.168.10.0", "0.0.0.255", "Allow staff subnet"),
        )

    # -------------------------- helpers --------------------------
    def _add_labeled_entry(self, parent, label, value=""):
        frame = tk.Frame(parent)
        frame.pack(fill="x", pady=3)
        tk.Label(frame, text=label, width=18, anchor="w").pack(side="left")
        entry = tk.Entry(frame)
        entry.pack(side="left", fill="x", expand=True)
        if value:
            entry.insert(0, value)
        return entry

    def _build_tree(self, body, columns, backing_list, default_values=()):
        tree = ttk.Treeview(body, columns=columns, show="headings", height=8)
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=max(110, len(col) * 12), anchor="center")
        tree.pack(fill="both", expand=True, pady=(6, 4))

        btns = tk.Frame(body)
        btns.pack(fill="x")
        tk.Button(btns, text="Add row", command=lambda: tree.insert("", "end", values=default_values)).pack(side="left", padx=2)
        tk.Button(btns, text="Remove selected", command=lambda: [tree.delete(i) for i in tree.selection()]).pack(side="left", padx=2)

        for item in backing_list:
            tree.insert("", "end", values=tuple(item.get(col.lower(), item.get(col, "")) for col in columns))

        def double_click(event):
            region = tree.identify_region(event.x, event.y)
            if region != "cell":
                return
            column = tree.identify_column(event.x)
            item_id = tree.identify_row(event.y)
            if not item_id or not column:
                return
            col_index = int(column.replace("#", "")) - 1
            col_name = columns[col_index]
            current = tree.item(item_id)["values"][col_index]
            popup = simpledialog.askstring("Edit", f"{col_name} value:", initialvalue=current, parent=self)
            if popup is not None:
                values = list(tree.item(item_id)["values"])
                values[col_index] = popup
                tree.item(item_id, values=values)

        tree.bind("<Double-1>", double_click)
        return tree

    def _collect_tree(self, tree, columns):
        result = []
        for iid in tree.get_children():
            values = tree.item(iid)["values"]
            record = {}
            for idx, col in enumerate(columns):
                record[col.lower()] = values[idx]
            result.append(record)
        return result

    # -------------------------- validations per step --------------------------
    def _validate_identity(self):
        hostname = self.entry_hostname.get().strip()
        enable = self.entry_enable.get().strip()

        if not hostname:
            messagebox.showerror("Missing info", "Hostname is required.")
            return False
        if not enable:
            messagebox.showerror("Missing info", "Set an enable secret.")
            return False

        self.identity_data = {
            "hostname": hostname,
            "domain": self.entry_domain.get().strip(),
            "enable": enable,
        }
        return True

    def _validate_vlans(self):
        self.vlans = self._collect_tree(self.vlan_tree, ("id", "name", "ports"))
        if not self.vlans:
            messagebox.showerror("Add VLANs", "Add at least one VLAN.")
            return False
        for vlan in self.vlans:
            try:
                vid = int(vlan["id"])
                if vid < 1 or vid > 4094:
                    raise ValueError
            except Exception:
                messagebox.showerror("Invalid VLAN", f"VLAN ID '{vlan['id']}' is invalid.")
                return False
        return True

    def _validate_routing(self):
        if self.routing_mode == "device":
            self.routing_entries = self._collect_tree(self.route_tree, ("vlan", "ip", "mask"))
        else:
            self.routing_entries = []
        return True

    def _validate_dhcp(self):
        self.dhcp_pools = self._collect_tree(
            self.dhcp_tree, ("pool", "network", "mask", "gateway", "dns", "start", "end")
        )
        return True

    def _validate_acl(self):
        self.acl_rules = self._collect_tree(
            self.acl_tree,
            ("acl #", "action", "source", "wildcard", "remark"),
        )
        return True

    def _validate_uplinks(self):
        self.uplinks = self._collect_tree(
            self.uplink_tree,
            ("ports", "mode", "allowed vlans"),
        )
        if not self.uplinks:
            messagebox.showinfo("Info", "You can add uplinks later if needed.")
        return True

    def _validate_summary(self):
        self._refresh_summary()
        return True

    # -------------------------- summary & template writing --------------------------
    def _refresh_summary(self):
        if not self.summary_box:
            return
        self.summary_box.delete("1.0", "end")
        
        # Add instructions at the top
        self.summary_box.insert("end", "! ========================================\n")
        self.summary_box.insert("end", "! PASTE EACH BLOCK SEPARATELY!\n")
        self.summary_box.insert("end", "! Wait for device prompt before pasting the next block\n")
        self.summary_box.insert("end", "! ========================================\n\n")
        
        block_titles = [
            ("BLOCK 1: Identity & Security", self._render_identity_block()),
            ("BLOCK 2: VLANs & Port Assignment", self._render_vlan_block()),
            ("BLOCK 3: Uplinks & Trunks", self._render_uplink_block()),
            ("BLOCK 4: Routing & SVIs", self._render_routing_block()),
            ("BLOCK 5: DHCP Pools", self._render_dhcp_block()),
            ("BLOCK 6: Access Control Lists", self._render_acl_block()),
        ]
        
        inserted = False
        for title, block in block_titles:
            if block.strip():
                # Add prominent block separator
                self.summary_box.insert("end", "! " + "="*60 + "\n")
                self.summary_box.insert("end", f"! {title}\n")
                self.summary_box.insert("end", "! COPY THIS BLOCK --> PASTE IN DEVICE --> WAIT FOR PROMPT\n")
                self.summary_box.insert("end", "! " + "="*60 + "\n")
                self.summary_box.insert("end", block + "\n")
                self.summary_box.insert("end", "! " + "-"*60 + "\n")
                self.summary_box.insert("end", "! Block complete. Wait for device prompt before next block.\n")
                self.summary_box.insert("end", "! " + "-"*60 + "\n\n\n")
                inserted = True
        
        if not inserted:
            self.summary_box.insert(
                "end",
                "No configuration snippets were generated yet.\n"
                "Please make sure each step has at least one entry, then press Finish.",
            )
        else:
            # Add final instructions
            self.summary_box.insert("end", "! ========================================\n")
            self.summary_box.insert("end", "! ALL BLOCKS COMPLETE!\n")
            self.summary_box.insert("end", "! Now save your configuration:\n")
            self.summary_box.insert("end", "! ========================================\n")
            self.summary_box.insert("end", "write memory\n")
            self.summary_box.insert("end", "! (or use: copy running-config startup-config)\n")

    def _write_templates(self):
        self._cleanup_default_templates()
        templates = {
            "guided_identity": self._render_identity_block(),
            "guided_vlans": self._render_vlan_block(),
            "guided_uplinks": self._render_uplink_block(),
            "guided_routing": self._render_routing_block(),
            "guided_dhcp": self._render_dhcp_block(),
            "guided_acl": self._render_acl_block(),
        }
        for key, value in templates.items():
            if value.strip():
                self.device_model.set_template(key, value)

    def _cleanup_default_templates(self):
        # Clear any pre-existing templates (device models now start empty)
        # This ensures only wizard-generated configs are included
        pass

    # -------------------------- block render helpers --------------------------
    def _expand_ports_to_list(self, ports: str):
        """
        Expand user-friendly port ranges into a flat list of interfaces.

        Examples:
          'FastEthernet1/0-3' -> ['FastEthernet1/0', 'FastEthernet1/1', 'FastEthernet1/2', 'FastEthernet1/3']
          'Fa1/0-1,Fa1/5'     -> ['Fa1/0', 'Fa1/1', 'Fa1/5']
          'Ethernet0/0-3'     -> ['Ethernet0/0', 'Ethernet0/1', 'Ethernet0/2', 'Ethernet0/3']

        This avoids relying on IOS 'interface range x-y' syntax, which varies
        across platforms. We always configure ports one-by-one.
        """
        if not ports:
            return []
        result = []
        for part in str(ports).split(","):
            part = part.strip()
            if not part:
                continue
            # Find the last slash: prefix before it, numeric part after it
            slash_idx = part.rfind("/")
            if slash_idx == -1:
                # Not in module/port form, keep as-is
                result.append(part)
                continue
            prefix = part[: slash_idx + 1]
            tail = part[slash_idx + 1 :]
            if "-" in tail:
                start_s, end_s = tail.split("-", 1)
                try:
                    start = int(start_s)
                    end = int(end_s)
                except ValueError:
                    # Fallback: keep original text if parsing fails
                    result.append(part)
                    continue
                step = 1 if end >= start else -1
                for num in range(start, end + step, step):
                    result.append(f"{prefix}{num}")
            else:
                result.append(part)
        return result

    def _render_identity_block(self):
        if not self.identity_data:
            return ""
        lines = ["configure terminal"]
        lines.append(f"hostname {self.identity_data.get('hostname', self.device_name)}")
        if self.identity_data.get("domain"):
            lines.append(f"ip domain-name {self.identity_data.get('domain')}")
        lines.append(f"enable secret {self.identity_data.get('enable')}")
        lines.append("exit")
        return "\n".join(lines)

    def _render_vlan_block(self):
        if not self.vlans:
            return ""
        lines = []
        
        # Check if this is an old EtherSwitch device (NM-16ESW, old IOU L3)
        # Core switches (L3) use old vlan database syntax
        use_old_syntax = (self.device_role == "core")
        
        if use_old_syntax:
            # OLD SYNTAX: vlan database is EXEC mode command!
            lines.append("vlan database")
            for vlan in self.vlans:
                name = vlan.get("name") or f"VLAN{vlan.get('id')}"
                lines.append(f"vlan {vlan.get('id')} name {name}")
            lines.append("exit")
            lines.append("!")
            
            # Interface assignment needs config mode
            lines.append("configure terminal")
            for vlan in self.vlans:
                ports = vlan.get("ports", "")
                expanded = self._expand_ports_to_list(ports)
                for iface in expanded:
                    lines.append(f"interface {iface}")
                    lines.append("switchport mode access")
                    lines.append(f"switchport access vlan {vlan.get('id')}")
                    lines.append("no shutdown")
                    lines.append("exit")
            lines.append("exit")
        else:
            # MODERN SYNTAX: all in config mode
            lines.append("configure terminal")
            for vlan in self.vlans:
                name = vlan.get("name") or f"VLAN{vlan.get('id')}"
                lines.append(f"vlan {vlan.get('id')}")
                lines.append(f"name {name}")
            lines.append("exit")
            lines.append("!")
            
            # Interface assignment
            for vlan in self.vlans:
                ports = vlan.get("ports", "")
                expanded = self._expand_ports_to_list(ports)
                for iface in expanded:
                    lines.append(f"interface {iface}")
                    lines.append("switchport mode access")
                    lines.append(f"switchport access vlan {vlan.get('id')}")
                    lines.append("no shutdown")
                    lines.append("exit")
            lines.append("exit")
        
        return "\n".join(lines)

    def _render_uplink_block(self):
        if not self.uplinks:
            return ""
        lines = ["configure terminal"]
        
        for link in self.uplinks:
            ports = link.get("ports", "").strip()
            mode = (link.get("mode") or "trunk").lower()
            allowed = link.get("allowed vlans", "all")
            if not ports:
                continue
            lines.append(f"interface {ports}")
            if mode == "trunk":
                # Both L2 switches and old EtherSwitch (core) require trunk encapsulation
                if self.device_role in ("access", "core"):
                    lines.append("switchport trunk encapsulation dot1q")
                lines.append("switchport mode trunk")
                if allowed and allowed.lower() != "all":
                    lines.append(f"switchport trunk allowed vlan {allowed}")
            else:
                lines.append("switchport mode access")
                if allowed and allowed.lower() != "all":
                    lines.append(f"switchport access vlan {allowed}")
            lines.append("exit")
        
        lines.append("exit")
        return "\n".join(lines)

    def _render_routing_block(self):
        if self.routing_mode != "device":
            return "! Routing handled on separate router."
        if not self.routing_entries:
            return ""
        
        lines = ["configure terminal"]
        lines.append("ip routing")
        
        for entry in self.routing_entries:
            vlan = entry.get("vlan")
            ip = entry.get("ip")
            mask = entry.get("mask")
            if not vlan or not ip:
                continue
            lines.append(f"interface Vlan{vlan}")
            lines.append(f"ip address {ip} {mask}")
            lines.append("no shutdown")
            lines.append("exit")
        
        lines.append("exit")
        return "\n".join(lines)

    def _render_dhcp_block(self):
        if self.device_role == "access":
            return "! DHCP not configured on this device. Use your router/server."
        if not self.dhcp_pools:
            return ""
        
        lines = ["configure terminal"]
        
        for pool in self.dhcp_pools:
            if pool.get("start") and pool.get("end"):
                lines.append(f"ip dhcp excluded-address {pool['start']} {pool['end']}")
            lines.append(f"ip dhcp pool {pool.get('pool')}")
            lines.append(f"network {pool.get('network')} {pool.get('mask')}")
            if pool.get("gateway"):
                lines.append(f"default-router {pool.get('gateway')}")
            if pool.get("dns"):
                lines.append(f"dns-server {pool.get('dns')}")
            lines.append("exit")
        
        lines.append("exit")
        return "\n".join(lines)

    def _render_acl_block(self):
        if not self.acl_rules:
            if self.device_role == "access":
                return "! Note: Access-switch ACLs only filter local traffic."
            return ""
        
        lines = []
        if self.device_role == "access":
            lines.append("! Note: Access-switch ACLs only filter local traffic.")
        
        lines.append("configure terminal")
        
        for rule in self.acl_rules:
            acl_num = rule.get("acl #", "10")
            action = rule.get("action", "permit")
            src = rule.get("source", "any")
            src_wc = rule.get("wildcard", "")
            remark = rule.get("remark", "")
            if remark:
                lines.append(f"access-list {acl_num} remark {remark}")
            if src.lower() == "any":
                lines.append(f"access-list {acl_num} {action} any")
            else:
                lines.append(f"access-list {acl_num} {action} {src} {src_wc}")
        
        lines.append("exit")
        return "\n".join(lines)
    
    def _get_show_vlan_command(self):
        """Return the appropriate show vlan command based on device type"""
        if self.device_role == "core":
            return "show vlan-switch"  # Old EtherSwitch syntax
        else:
            return "show vlan brief"    # Modern syntax


