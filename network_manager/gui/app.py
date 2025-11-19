"""
Main application GUI class
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
try:
    from PIL import Image  # type: ignore
except ImportError:
    Image = None
import threading
import time
import json
import os
import sys
import ipaddress
from typing import Optional

# Import from our modules
from ..config import DB_PATH, GNS3_DEFAULT_URL, conn, cur
from ..models import DeviceModel, RouterModel, SwitchModel, CoreSwitchModel
from ..network import Sender, GNS3Connector
from .dialogs import TextEditorPopup
from .wizards import VlanGuiWindow, StpGuiWindow, GuidedSetupWizard
from .calculators import SubnetCalculator

# Optional libs
try:
    import requests
except Exception:
    requests = None


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ANCS - Network Manager")
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(1180, screen_w - 80)
        height = min(720, screen_h - 80)
        self.geometry(f"{width}x{height}")
        self.minsize(900, 580)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # device types
        self.device_types = {"router": RouterModel, "switch": SwitchModel, "core switch": CoreSwitchModel}
        self.devices: list[tuple[str, DeviceModel, dict]] = []  # (name, model, meta)
        self.current_device: Optional[tuple[str, DeviceModel, dict]] = None

        # gns3 connector (try to init automatically)
        self.gns3: Optional[GNS3Connector] = None
        self.last_gns3_project = None
        self._icon_photo = None  # Keep reference to prevent garbage collection

        self._build_ui()

        # defaults workspace devices
        self.add_device_instance("router", "router1")
        self.add_device_instance("switch", "switch1")
        self.add_device_instance("core switch", "core-sw1")
        self.refresh_device_list()

        # try auto-connect to gns3 in background
        threading.Thread(target=self._auto_connect_gns3, daemon=True).start()

    def _build_ui(self):
        top = ctk.CTkFrame(self, height=70)
        top.pack(side="top", fill="x")
        
        # ANCS Logo (left side)
        logo_frame = ctk.CTkFrame(top, fg_color="transparent")
        logo_frame.pack(side="left", padx=8, pady=8)
        
        # Try to load logo image, fallback to text if not found
        self.logo_image = None
        if Image is not None:
            # Get the directory where the script/exe is located
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                base_path = os.path.dirname(sys.executable)
            else:
                # Running as script - try multiple methods
                try:
                    base_path = os.path.dirname(os.path.abspath(__file__))
                except:
                    # Fallback to current working directory if __file__ not available
                    base_path = os.getcwd()
            
            # Also check current working directory as fallback
            search_paths = [base_path, os.getcwd()]
            for extra in ["gui", os.path.join("network_manager","gui")]:
                search_paths.append(os.path.join(base_path, extra))
                search_paths.append(os.path.join(os.getcwd(), extra))
            
            logo_paths = ["ancs_logo.png", "logo.png", "ANCS_Logo.png"]
            for search_path in search_paths:
                for logo_name in logo_paths:
                    logo_path = os.path.join(search_path, logo_name)
                    if os.path.exists(logo_path):
                        try:
                            print(f"Loading logo from: {logo_path}")  # Debug output
                            img = Image.open(logo_path)
                            # Convert to RGBA if needed for better compatibility
                            if img.mode != 'RGBA':
                                img = img.convert('RGBA')
                            img = img.resize((50, 50), Image.Resampling.LANCZOS)
                            self.logo_image = ctk.CTkImage(light_image=img, dark_image=img, size=(50, 50))
                            ctk.CTkLabel(logo_frame, image=self.logo_image, text="").pack(side="left")
                            break
                        except Exception as e:
                            # Log error for debugging
                            print(f"Error loading logo {logo_path}: {e}")
                            pass
                if self.logo_image is not None:
                    break
        
        # If no logo image found, show text logo
        if self.logo_image is None:
            ctk.CTkLabel(logo_frame, text="ANCS", font=ctk.CTkFont(size=20, weight="bold"), text_color="#4A9EFF").pack(side="left", padx=4)
            ctk.CTkLabel(logo_frame, text="Auto Network\nConfiguration System", font=ctk.CTkFont(size=9), text_color="#bcd", justify="left").pack(side="left", padx=2)
        
        # Title and subtitle (center)
        title_frame = ctk.CTkFrame(top, fg_color="transparent")
        title_frame.pack(side="left", fill="x", expand=True, padx=12)
        ctk.CTkLabel(title_frame, text="network manager", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="customtk · sqlite · gns3(auto) · run(telnet/ssh/serial)", text_color="#bcd", font=ctk.CTkFont(size=11)).pack(anchor="w")

        self.nb = ctk.CTkTabview(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=12)
        self.nb.add("main"); self.nb.add("gns3 devices"); self.nb.add("output / logs"); self.nb.add("database")
        self.tab_main = self.nb.tab("main")
        self.tab_gns3 = self.nb.tab("gns3 devices")
        self.tab_logs = self.nb.tab("output / logs")
        self.tab_db = self.nb.tab("database")
    
        # left column
        left_container = ctk.CTkFrame(self.tab_main, width=300)
        left_container.pack(side="left", fill="y", padx=(8,4), pady=8)
        left_container.pack_propagate(False)
        left_scroll = ctk.CTkScrollableFrame(left_container, width=280)
        left_scroll.pack(fill="both", expand=True)
        left = left_scroll
        ctk.CTkLabel(left, text="devices", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="nw", padx=8, pady=(8,4))
        self.lb_devices = tk.Listbox(left, height=10, bd=0)
        self.lb_devices.pack(fill="x", padx=8)
        self.lb_devices.bind("<<ListboxSelect>>", lambda e: self.on_device_select())

        dbbtns = ctk.CTkFrame(left, fg_color="transparent")
        dbbtns.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(dbbtns, text="add", command=self.add_device_prompt).pack(side="left", expand=True, padx=4)
        ctk.CTkButton(dbbtns, text="remove", fg_color="#d9534f", command=self.remove_selected_device).pack(side="left", expand=True, padx=4)
        ctk.CTkButton(left, text="save selected to db", command=self.save_device_to_db).pack(fill="x", padx=8, pady=(6,4))
        ctk.CTkButton(left, text="view saved devices", command=self.view_saved_devices).pack(fill="x", padx=8)
        ctk.CTkButton(left, text="subnet calculator (quick)", command=self.subnet_calculator).pack(fill="x", padx=8, pady=(6,4))
        ctk.CTkButton(left, text="Subnet Calculator (GUI)", command=lambda: SubnetCalculator(self)).pack(fill="x", padx=8, pady=6)

        ctk.CTkLabel(left, text="templates", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="nw", padx=8, pady=(12,4))
        self.lb_templates = tk.Listbox(left, height=12, bd=0)
        self.lb_templates.pack(fill="both", expand=True, padx=8)
        self.lb_templates.bind("<<ListboxSelect>>", lambda e: self.on_template_select())

        tbtns = ctk.CTkFrame(left, fg_color="transparent")
        tbtns.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(tbtns, text="add template", command=self.add_template_dialog).pack(side="left", expand=True, padx=4)
        ctk.CTkButton(tbtns, text="edit template", command=self.edit_template_dialog).pack(side="left", expand=True, padx=4)
        ctk.CTkButton(left, text="guided setup (beginner)", fg_color="#1abc9c", command=self.guided_setup).pack(fill="x", padx=8, pady=(8,4))
        ctk.CTkButton(left, text="vlan popup wizard", command=self.vlan_popup).pack(fill="x", padx=8, pady=(6,4))
        ctk.CTkButton(left, text="vlan gui wizard", command=self.vlan_gui_wizard).pack(fill="x", padx=8)
        ctk.CTkButton(left, text="stp popup wizard", command=self.stp_popup).pack(fill="x", padx=8, pady=(6,4))
        ctk.CTkButton(left, text="stp gui wizard", command=self.stp_gui_wizard).pack(fill="x", padx=8)

        # center area
        center = ctk.CTkFrame(self.tab_main)
        center.pack(side="left", fill="both", expand=True, padx=6, pady=8)

        topc = ctk.CTkFrame(center)
        topc.pack(fill="x")
        ctk.CTkLabel(topc, text="preview / generated config", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        gframe = ctk.CTkFrame(topc, fg_color="transparent")
        gframe.pack(side="right")
        ctk.CTkButton(gframe, text="generate selected", command=self.generate_selected).pack(side="left", padx=6)
        ctk.CTkButton(gframe, text="generate full", command=self.generate_full).pack(side="left", padx=6)
        ctk.CTkButton(gframe, text="save config to db", fg_color="#6b2d9c", command=self.save_config_to_db).pack(side="left", padx=6)
        ctk.CTkButton(gframe, text="view saved configs", fg_color="#6b2d9c", command=self.view_saved_configs).pack(side="left", padx=6)

        preview_holder = ctk.CTkFrame(center)
        preview_holder.pack(fill="both", expand=True, padx=4, pady=4)
        self.preview = ctk.CTkTextbox(preview_holder, wrap="none")
        self.preview.pack(fill="both", expand=True, padx=6, pady=6)
        
        # Enable paste in preview window
        def paste_handler(event=None):
            try:
                clipboard_text = self.clipboard_get()
                self.preview.insert("insert", clipboard_text)
                return "break"
            except:
                pass
        
        self.preview.bind("<Control-v>", paste_handler)
        self.preview.bind("<Command-v>", paste_handler)  # macOS

        # right column
        right = ctk.CTkFrame(self.tab_main, width=320)
        right.pack(side="right", fill="y", padx=(4,8), pady=8)
        right.pack_propagate(False)
        ctk.CTkLabel(right, text="send / connect", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="nw", padx=8, pady=(8,6))
        self.send_method = ctk.CTkOptionMenu(right, values=["serial (console)", "telnet", "ssh"]) 
        self.send_method.set("serial (console)")
        self.send_method.pack(fill="x", padx=8, pady=(0,6))

        # serial
        ctk.CTkLabel(right, text="serial (console)").pack(anchor="w", padx=8, pady=(6,0))
        self.ent_serial_port = ctk.CTkEntry(right, placeholder_text="COM3 or /dev/ttyUSB0")
        self.ent_serial_port.pack(fill="x", padx=8)
        self.ent_serial_baud = ctk.CTkEntry(right, placeholder_text="9600")
        self.ent_serial_baud.pack(fill="x", padx=8, pady=(6,0))

        # network
        ctk.CTkLabel(right, text="network (telnet / ssh)").pack(anchor="w", padx=8, pady=(8,0))
        self.ent_host = ctk.CTkEntry(right, placeholder_text="host or ip")
        self.ent_host.pack(fill="x", padx=8)
        self.ent_port = ctk.CTkEntry(right, placeholder_text="port")
        self.ent_port.pack(fill="x", padx=8, pady=(6,0))
        self.ent_user = ctk.CTkEntry(right, placeholder_text="username")
        self.ent_user.pack(fill="x", padx=8, pady=(6,0))
        self.ent_pass = ctk.CTkEntry(right, placeholder_text="password", show="*")
        self.ent_pass.pack(fill="x", padx=8, pady=(6,0))
        self.ent_enable = ctk.CTkEntry(right, placeholder_text="enable password (optional)", show="*")
        self.ent_enable.pack(fill="x", padx=8, pady=(6,0))

        ctk.CTkButton(right, text="send now (background)", command=self.send_now).pack(fill="x", padx=8, pady=(12,8))

        # logs tab
        ctk.CTkLabel(self.tab_logs, text="output / logs", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="nw", padx=12, pady=(8,6))
        self.txt_logs = ctk.CTkTextbox(self.tab_logs)
        self.txt_logs.pack(fill="both", expand=True, padx=12, pady=(4,12))
        ctk.CTkButton(self.tab_logs, text="clear logs", command=lambda: self.txt_logs.delete("0.0","end")).pack(padx=12, pady=(0,12))

        # database tab (devices | configs)
        ctk.CTkLabel(self.tab_db, text="database (devices & configs)", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="nw", padx=12, pady=(8,6))
        db_frame = ctk.CTkFrame(self.tab_db)
        db_frame.pack(fill="both", expand=True, padx=12, pady=8)

        left_db = ctk.CTkFrame(db_frame, width=520)
        left_db.pack(side="left", fill="both", expand=True, padx=(0,6)); left_db.pack_propagate(False)
        self.tree_devices = ttk.Treeview(left_db, columns=("id","name","type","ip","port","conn","gns3","created"), show="headings")
        for h,w in [("id",50),("name",160),("type",120),("ip",110),("port",70),("conn",100),("gns3",60),("created",160)]:
            self.tree_devices.heading(h, text=h); self.tree_devices.column(h, width=w, anchor="center")
        self.tree_devices.pack(fill="both", expand=True)
        ctk.CTkButton(left_db, text="refresh devices", command=self.refresh_devices_tree).pack(pady=6)
        ctk.CTkButton(left_db, text="import selected into workspace", command=self.import_device_from_tree).pack(pady=(0,6))

        right_db = ctk.CTkFrame(db_frame)
        right_db.pack(side="right", fill="both", expand=True, padx=(6,0))
        self.tree_configs = ttk.Treeview(right_db, columns=("id","device_id","name","created"), show="headings")
        for h,w in [("id",60),("device_id",100),("name",200),("created",160)]:
            self.tree_configs.heading(h, text=h); self.tree_configs.column(h, width=w, anchor="center")
        self.tree_configs.pack(fill="both", expand=True)
        ctk.CTkButton(right_db, text="refresh configs", command=self.refresh_configs_tree).pack(pady=6)
        ctk.CTkButton(right_db, text="load selected into preview", command=self.load_config_into_preview).pack(pady=(0,6))

        # gns3 tab quick view
        gns3_header = ctk.CTkFrame(self.tab_gns3, fg_color="transparent")
        gns3_header.pack(fill="x", padx=12, pady=(8,6))
        ctk.CTkLabel(gns3_header, text="gns3 auto-import", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(gns3_header, text="🔄 Refresh", command=self.refresh_gns3_connection, width=100, fg_color="#2d9cdb").pack(side="right", padx=(6,0))
        
        self.lbl_gns3_status = ctk.CTkLabel(self.tab_gns3, text="attempting auto-connect to gns3...")
        self.lbl_gns3_status.pack(anchor="nw", padx=12, pady=(0,6))
        ctk.CTkButton(self.tab_gns3, text="manual import from gns3", command=self.gns3_list_projects).pack(padx=12, pady=(6,6))

        # menu quick action
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        gmenu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="gns3", menu=gmenu)
        gmenu.add_command(label="import from gns3", command=lambda: self.gns3_list_projects())

        # tab changed binding to refresh db tab when switched
        def on_tab_changed(event=None):
            selected = self.nb.get()
            if selected == "database":
                self.refresh_devices_tree()
                self.refresh_configs_tree()
        # bind the event - use configure callback as workaround for older customtkinter versions
        try:
            self.nb.bind("<<CTkTabviewChanged>>", on_tab_changed)
        except NotImplementedError:
            # Fallback: manually check tab on button clicks or use configure callback
            # We'll refresh when database tab buttons are clicked instead
            pass
        
        # Initial refresh of database tab
        self.refresh_devices_tree()
        self.refresh_configs_tree()

    # ------------------- device workspace functions -------------------
    def add_device_instance(self, type_key, name, metadata=None):
        # create device model in memory workspace
        cls = self.device_types.get(type_key)
        if not cls:
            return
        obj = cls(name)
        if metadata is None:
            metadata = {}
        self.devices.append((name, obj, metadata))

    def refresh_device_list(self):
        self.lb_devices.delete(0, "end")
        for n, obj, meta in self.devices:
            label = f"{n} ({obj.__class__.__name__})"
            if meta.get("gns3_node"):
                label += " [gns3]"
            self.lb_devices.insert("end", label)
        if self.devices:
            self.lb_devices.select_set(0)
            self.on_device_select()

    def add_device_prompt(self):
        dtype = simpledialog.askstring("add device", "device type: router / switch / core switch", parent=self)
        if not dtype: return
        dtype = dtype.strip().lower()
        if dtype not in self.device_types:
            messagebox.showerror("error", "unknown type"); return
        name = simpledialog.askstring("name", "device name (e.g. router2)", parent=self)
        if not name: return
        self.add_device_instance(dtype, name.strip())
        self.refresh_device_list()

    def remove_selected_device(self):
        sel = self.lb_devices.curselection()
        if not sel: return
        idx = sel[0]
        name,_,_ = self.devices[idx]
        if messagebox.askyesno("confirm", f"remove {name}?"):
            del self.devices[idx]
            self.refresh_device_list()

    def on_device_select(self):
        sel = self.lb_devices.curselection()
        if not sel: return
        idx = sel[0]
        name, model, meta = self.devices[idx]
        self.current_device = (name, model, meta)
        # templates
        self.lb_templates.delete(0, "end")
        for t in model.get_template_names():
            self.lb_templates.insert("end", t)
        # preview header
        try:
            self.preview.delete("0.0", "end")
            self.preview.insert("0.0", f"! device: {name}\n")
        except Exception:
            pass

    # ------------------- templates -------------------
    def add_template_dialog(self):
        if not self.current_device:
            messagebox.showinfo("info", "select device first"); return
        name = simpledialog.askstring("template name", "template name:", parent=self)
        if not name: return
        editor = TextEditorPopup(self, title=f"new template: {name}", initial="")
        self.wait_window(editor)
        if getattr(editor, "result", None) is not None:
            self.current_device[1].set_template(name, editor.result)
            self.on_device_select()

    def edit_template_dialog(self):
        sel = self.lb_templates.curselection()
        if not sel:
            messagebox.showinfo("info", "select template first"); return
        tname = self.lb_templates.get(sel[0])
        editor = TextEditorPopup(self, title=f"edit template: {tname}", initial=self.current_device[1].get_template(tname))
        self.wait_window(editor)
        if getattr(editor, "result", None) is not None:
            self.current_device[1].set_template(tname, editor.result)
            self.on_device_select()

    def on_template_select(self):
        sel = self.lb_templates.curselection()
        if not sel: return
        tname = self.lb_templates.get(sel[0])
        txt = self.current_device[1].get_template(tname).replace("{name}", self.current_device[0])
        self.preview.delete("0.0", "end")
        self.preview.insert("0.0", txt)

    # ------------------- VLAN wizards -------------------
    def vlan_popup(self):
        if not self.current_device:
            messagebox.showinfo("info", "select device first"); return
        count_s = simpledialog.askstring("vlan wizard", "enter number of vlans:", parent=self)
        if not count_s: return
        try:
            count = int(count_s)
        except:
            messagebox.showerror("error", "invalid number"); return
        out=[]; port_start=1
        for i in range(count):
            vid = simpledialog.askstring("vlan wizard", f"vlan #{i+1} id:", parent=self)
            if vid is None:
                return
            vname = simpledialog.askstring("vlan wizard", f"vlan #{i+1} name:", parent=self) or f"VLAN{vid}"
            ports_s = simpledialog.askstring("vlan wizard", f"vlan #{i+1} port count:", parent=self)
            if ports_s is None: return
            try: ports = int(ports_s)
            except:
                messagebox.showerror("error","invalid port count"); return
            port_end = port_start + ports -1
            out.append(f"vlan {vid}"); out.append(f" name {vname}")
            if ports>0:
                out.append(f"interface range GigabitEthernet0/{port_start} - {port_end}")
                out.append(" switchport mode access"); out.append(f" switchport access vlan {vid}")
            out.append(""); port_start = port_end + 1
        out.append("! vlan wizard complete")
        self.current_device[1].set_template("vlan_wizard_popup", "\n".join(out))
        self.on_device_select()

    def vlan_gui_wizard(self):
        if not self.current_device:
            messagebox.showinfo("info","select device first"); return
        win = VlanGuiWindow(self)
        self.wait_window(win)
        if getattr(win, "result", None):
            self.current_device[1].set_template("vlan_wizard_gui", win.result)
            self.on_device_select()
        
    # ------------------- STP wizards -------------------
    def stp_popup(self):
        if not self.current_device:
            messagebox.showinfo("info", "select device first"); return
        count_s = simpledialog.askstring("stp wizard", "enter number of STP VLANs:", parent=self)
        if not count_s: return
        try:
            count = int(count_s)
        except:
            messagebox.showerror("error", "invalid number"); return

        out = []
        for i in range(count):
            vlan_id = simpledialog.askstring("stp wizard", f"STP instance #{i+1} VLAN ID:", parent=self)
            if vlan_id is None: return

            mode = simpledialog.askstring("stp wizard", f"STP mode for VLAN {vlan_id} (pvst/rapid-pvst/mst):", parent=self) or "pvst"
            priority = simpledialog.askstring("stp wizard", f"Bridge priority for VLAN {vlan_id}:", parent=self) or "32768"

            portfast = messagebox.askyesno("stp wizard", "enable portfast?")
            bpduguard = messagebox.askyesno("stp wizard", "enable bpduguard?")
            uplinkfast = messagebox.askyesno("stp wizard", "enable uplinkfast?")
            backbonefast = messagebox.askyesno("stp wizard", "enable backbonefast?")

            out.append(f"spanning-tree mode {mode}")
            out.append(f"spanning-tree vlan {vlan_id} priority {priority}")

            if portfast:
                out.append("spanning-tree portfast default")
            if bpduguard:
                out.append("spanning-tree portfast bpduguard default")
            if uplinkfast:
                out.append("spanning-tree uplinkfast")
            if backbonefast:
                out.append("spanning-tree backbonefast")

            out.append("!")

        out.append("! STP wizard complete")
        self.current_device[1].set_template("stp_wizard_popup", "\n".join(out))
        self.on_device_select()


    def stp_gui_wizard(self):
        if not self.current_device:
            messagebox.showinfo("info","select device first"); return
        win = StpGuiWindow(self)
        self.wait_window(win)
        if getattr(win, "result", None):
            self.current_device[1].set_template("stp_wizard_gui", win.result)
            self.on_device_select()
    
    def guided_setup(self):
        if not self.devices:
            messagebox.showinfo("info", "add a device first")
            return
        choice = self._prompt_guided_device_choice()
        if not choice:
            return
        name, model, _ = choice
        if isinstance(model, RouterModel):
            device_role = "router"
        elif isinstance(model, CoreSwitchModel):
            device_role = "core"
        else:
            device_role = "access"

        if device_role == "access":
            msg = (
                f"{name} is a Layer 2 switch. It cannot run routing or DHCP services.\n\n"
                "The guided wizard will only configure VLANs, uplinks, and limited ACLs here. "
                "If you need routing/DHCP, choose your router or core switch instead.\n\n"
                "Continue with this switch?"
            )
            if not messagebox.askyesno("Layer 2 device", msg, parent=self):
                return
        win = GuidedSetupWizard(self, name, model, device_role=device_role)
        self.wait_window(win)
        self.on_device_select()
        try:
            self.generate_full()
        except Exception:
            pass
        messagebox.showinfo(
            "guided setup complete",
            "Guided templates were saved for this device.\nSelect any 'guided_*' template or keep the current preview to review.",
            parent=self,
        )

    def _prompt_guided_device_choice(self):
        dialog = tk.Toplevel(self)
        dialog.title("Pick the device to configure")
        dialog.geometry("420x360")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text="Which device should we configure first?", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(dialog, text="Tip: start with the router/core switch that handles routing, DHCP, and ACLs.", wraplength=380, justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        listbox = tk.Listbox(dialog, activestyle="none")
        listbox.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        device_labels = []
        for idx, (name, model, meta) in enumerate(self.devices):
            if isinstance(model, (RouterModel, CoreSwitchModel)):
                role = "Gateway (Routing + DHCP)"
            else:
                role = "Access (Layer 2)"
            device_labels.append((idx, role))
            listbox.insert("end", f"{name}  ·  {role}")
        listbox.select_set(0)

        choice = {"value": None}

        def confirm():
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("info", "select a device first", parent=dialog)
                return
            idx = sel[0]
            choice["value"] = self.devices[idx]
            dialog.destroy()

        def cancel():
            choice["value"] = None
            dialog.destroy()

        btns = tk.Frame(dialog)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(btns, text="Use selected", bg="#27ae60", fg="white", command=confirm).pack(side="left", padx=4)
        tk.Button(btns, text="Cancel", command=cancel).pack(side="right", padx=4)

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self.wait_window(dialog)
        return choice["value"]
  

    # ------------------- generate / export / db -------------------
    def generate_selected(self):
        sel = self.lb_templates.curselection()
        if not sel:
            messagebox.showinfo("info", "select template first"); return
        tname = self.lb_templates.get(sel[0])
        txt = self.current_device[1].get_template(tname).replace("{name}", self.current_device[0])
        self.preview.delete("0.0", "end")
        self.preview.insert("0.0", txt)

    def generate_full(self):
        txt = self.current_device[1].build_full_config().replace("{name}", self.current_device[0])
        self.preview.delete("0.0", "end")
        self.preview.insert("0.0", txt)

    def save_config_to_db(self):
        sel = self.lb_devices.curselection()
        if not sel:
            messagebox.showinfo("info", "select device first"); return
        idx = sel[0]
        name, _, _ = self.devices[idx]
        content = self.preview.get("0.0", "end").strip()
        if not content:
            messagebox.showinfo("info", "nothing to save"); return
        cfg_name = simpledialog.askstring("config name", "enter config name:", parent=self)
        if not cfg_name: return
        cur.execute("SELECT id FROM devices WHERE name=?", (name,))
        r = cur.fetchone()
        device_id = r[0] if r else None
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO configs (device_id, config_name, content, created_at) VALUES (?, ?, ?, ?)",
                    (device_id, cfg_name, content, ts))
        conn.commit()
        messagebox.showinfo("saved", f"config '{cfg_name}' saved")

    def view_saved_configs(self):
        win = tk.Toplevel(self)
        win.title("saved configs"); win.geometry("900x500")
        tree = ttk.Treeview(win, columns=("id","device","name","created"), show="headings")
        for h,w in [("id",80),("device",200),("name",300),("created",200)]:
            tree.heading(h, text=h); tree.column(h, width=w, anchor="center")
        tree.pack(fill="both", expand=True)
        cur.execute("SELECT c.id, d.name, c.config_name, c.created_at FROM configs c LEFT JOIN devices d ON c.device_id=d.id ORDER BY c.id DESC")
        for r in cur.fetchall():
            tree.insert("", "end", values=r)
        preview = ctk.CTkTextbox(win, height=120)
        preview.pack(fill="x", padx=6, pady=6)
        def on_select(e=None):
            sel = tree.selection()
            if not sel: return
            cfg_id = tree.item(sel[0])["values"][0]
            cur.execute("SELECT content FROM configs WHERE id=?", (cfg_id,))
            r = cur.fetchone()
            preview.delete("0.0","end")
            if r: preview.insert("0.0", r[0])
        tree.bind("<<TreeviewSelect>>", on_select)
        def load_into_preview():
            sel = tree.selection()
            if not sel: messagebox.showinfo("info","select one"); return
            cfg_id = tree.item(sel[0])["values"][0]
            cur.execute("SELECT d.name, c.content FROM configs c LEFT JOIN devices d ON c.device_id=d.id WHERE c.id=?", (cfg_id,))
            r = cur.fetchone()
            if r:
                devname, content = r
                for i,(n,_,_) in enumerate(self.devices):
                    if n == devname:
                        self.lb_devices.select_clear(0,"end"); self.lb_devices.select_set(i); self.on_device_select(); break
                self.preview.delete("0.0","end"); self.preview.insert("0.0", content)
                win.destroy()
        tk.Button(win, text="load selected into preview", command=load_into_preview).pack(pady=6)

    # ------------------- db device functions -------------------
    def save_device_to_db(self):
        sel = self.lb_devices.curselection()
        if not sel:
            messagebox.showinfo("info", "select device first"); return
        idx = sel[0]
        name, model, meta = self.devices[idx]
        ip = simpledialog.askstring("device ip", "enter device ip (optional):", parent=self) or ""
        port = simpledialog.askstring("device port", "enter device port (optional):", parent=self) or ""
        conn_type = simpledialog.askstring("connection type", "serial/telnet/ssh (optional):", parent=self) or ""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            cur.execute("INSERT OR REPLACE INTO devices (name,type,ip,port,connection_type,added_from_gns3,created_at) VALUES (?,?,?,?,?,?,?)",
                        (name, model.__class__.__name__, ip, port, conn_type, int(meta.get("gns3_node", False)), ts))
            conn.commit()
            messagebox.showinfo("saved", f"device '{name}' saved")
        except Exception as e:
            messagebox.showerror("error", f"db error: {e}")

    def refresh_devices_tree(self):
        """Refresh the devices treeview with current database data"""
        for i in self.tree_devices.get_children(): self.tree_devices.delete(i)
        cur.execute("SELECT id,name,type,ip,port,connection_type,added_from_gns3,created_at FROM devices ORDER BY id DESC")
        for r in cur.fetchall():
            self.tree_devices.insert("", "end", values=r)
    
    def _check_and_refresh_db_tab(self):
        """Helper method to refresh database tab if currently selected"""
        try:
            if self.nb.get() == "database":
                self.refresh_devices_tree()
                self.refresh_configs_tree()
        except:
            pass

    def refresh_configs_tree(self):
        for i in self.tree_configs.get_children(): self.tree_configs.delete(i)
        cur.execute("SELECT id, device_id, config_name, created_at FROM configs ORDER BY id DESC")
        for r in cur.fetchall():
            self.tree_configs.insert("", "end", values=r)

    def import_device_from_tree(self):
        sel = self.tree_devices.selection()
        if not sel:
            messagebox.showinfo("info","select device first"); return
        item = self.tree_devices.item(sel[0])["values"]
        name = item[1]; ip = item[3]; port = item[4]; conn_type = item[5]; gns3_flag = item[6]
        dtype = simpledialog.askstring("device type", "device type for workspace (router/switch/core switch):", initialvalue="router", parent=self)
        if not dtype: return
        dtype = dtype.strip().lower()
        if dtype not in self.device_types:
            messagebox.showerror("error","unknown type"); return
        meta = {"ip": ip, "port": port, "connection_type": conn_type, "gns3_node": bool(gns3_flag)}
        self.add_device_instance(dtype, name, metadata=meta)
        self.refresh_device_list()
        messagebox.showinfo("imported", f"{name} imported to workspace")

    def load_config_into_preview(self):
        sel = self.tree_configs.selection()
        if not sel:
            messagebox.showinfo("info","select config first"); return
        cfg_id = self.tree_configs.item(sel[0])["values"][0]
        cur.execute("SELECT content FROM configs WHERE id=?", (cfg_id,))
        r = cur.fetchone()
        if r:
            self.preview.delete("0.0","end"); self.preview.insert("0.0", r[0])
            

    # ------------------- logs only UI -------------------
    def log(self, msg):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.txt_logs.insert("0.0", f"[{ts}] {msg}\n")
            # echo small in preview
            self.preview.insert("0.0", f"[{ts}] {msg}\n")
        except Exception:
            pass

    # ------------------- send/run -------------------
    def send_now(self):
        content = self.preview.get("0.0","end").strip()
        if not content:
            messagebox.showinfo("info","nothing to send"); return
        method = self.send_method.get()
        if method.startswith("serial"):
            port = self.ent_serial_port.get().strip()
            try:
                baud = int(self.ent_serial_baud.get().strip() or "9600")
            except:
                messagebox.showerror("error","invalid baud"); return
            if not port:
                messagebox.showerror("error","enter serial port"); return
            threading.Thread(target=self._thread_serial, args=(port,baud,content), daemon=True).start()
        elif method == "telnet":
            host = self.ent_host.get().strip()
            if not host:
                messagebox.showerror("error","enter host"); return
            try:
                port = int(self.ent_port.get().strip() or "23")
            except:
                messagebox.showerror("error","invalid port"); return
            user = self.ent_user.get().strip(); pw = self.ent_pass.get().strip(); enable = self.ent_enable.get().strip()
            threading.Thread(target=self._thread_telnet, args=(host,port,user,pw,enable,content), daemon=True).start()
        elif method == "ssh":
            host = self.ent_host.get().strip()
            if not host:
                messagebox.showerror("error","enter host"); return
            try:
                port = int(self.ent_port.get().strip() or "22")
            except:
                messagebox.showerror("error","invalid port"); return
            user = self.ent_user.get().strip(); pw = self.ent_pass.get().strip(); enable = self.ent_enable.get().strip()
            threading.Thread(target=self._thread_ssh, args=(host,port,user,pw,enable,content), daemon=True).start()
        else:
            messagebox.showerror("error","unknown method")

    def _thread_serial(self, port, baud, content):
        self.log(f"starting serial to {port}@{baud}")
        ok = Sender.send_serial(self.log, port, baud, content)
        self.log(f"serial finished: {ok}")

    def _thread_telnet(self, host, port, user, pw, enable, content):
        self.log(f"starting telnet to {host}:{port}")
        ok = Sender.send_telnet(self.log, host, port, user, pw, enable, content)
        self.log(f"telnet finished: {ok}")

    def _thread_ssh(self, host, port, user, pw, enable, content):
        self.log(f"starting ssh to {host}:{port} as {user}")
        ok = Sender.send_ssh(self.log, host, port, user, pw, enable, content)
        self.log(f"ssh finished: {ok}")

    # ------------------- GNS3 integration -------------------
    def refresh_gns3_connection(self):
        """Refresh GNS3 connection and detect newly opened projects"""
        self.lbl_gns3_status.configure(text="refreshing gns3 connection...")
        threading.Thread(target=self._auto_connect_gns3, daemon=True).start()
    
    def _auto_connect_gns3(self):
        # try to auto-connect on startup and import nodes from open/most-recent project
        if requests is None:
            self.lbl_gns3_status.configure(text="requests not installed; gns3 auto-import disabled")
            return
        try:
            g = GNS3Connector(GNS3_DEFAULT_URL)
            projs = g.get_projects()
            if not projs:
                self.lbl_gns3_status.configure(text="no gns3 projects found on server")
                return
            # try to pick open project, else most recently modified (fallback)
            proj = None
            for p in projs:
                if p.get('is_open') or p.get('status') == 'opened':
                    proj = p; break
            if not proj:
                # attempt to choose most recently modified by 'name' timestamp-like or use first
                try:
                    projs_sorted = sorted(projs, key=lambda x: x.get('name',''), reverse=True)
                    proj = projs_sorted[0]
                except Exception:
                    proj = projs[0]
            
            # Check if project changed
            current_project_id = proj.get('project_id') or proj.get('projectId') or proj.get('id')
            if self.last_gns3_project:
                last_project_id = self.last_gns3_project.get('project_id') or self.last_gns3_project.get('projectId') or self.last_gns3_project.get('id')
                if current_project_id != last_project_id:
                    self.log(f"[gns3] detected project change: {self.last_gns3_project.get('name')} -> {proj.get('name')}")
            
            self.gns3 = g
            self.last_gns3_project = proj
            self.lbl_gns3_status.configure(text=f"auto-connected to gns3, project: {proj.get('name')}")
            # import nodes
            try:
                # FIX: Use .get() with fallback for project_id
                project_id = proj.get('project_id') or proj.get('projectId') or proj.get('id')
                if not project_id:
                    self.lbl_gns3_status.configure(text="gns3 project missing project_id")
                    return
                nodes = self.gns3.get_nodes(project_id)
                imported = 0
                for node in nodes:
                    name = node.get('name') or f"node-{str(node.get('node_id','') or node.get('id',''))[:6]}"
                    console_host = node.get('console_host') or node.get('console_host_override') or 'localhost'
                    # FIX: Remove console_type, use proper port fields
                    console_port = node.get('console') or node.get('console_port') or ''
                    node_id = node.get('node_id') or node.get('id')
                    # choose a workspace type guess
                    raw_node_type = node.get('node_type', '')
                    raw_platform = node.get('platform', '')
                    raw_category = node.get('category', '')
                    console_type = node.get('console_type', '')
                    properties = node.get('properties') or {}
                    image_name = properties.get('image') or properties.get('platform') or properties.get('hw_model') or ''
                    self.log(f"[gns3] node {name}: type={raw_node_type} platform={raw_platform} category={raw_category}")
                    self.log(f"[gns3] node {name}: console={console_type} image={image_name}")
                    node_type_field = (raw_node_type or '') + ' ' + (raw_platform or '')
                    desc = node_type_field.lower()
                    full_desc = " ".join([desc, str(console_type).lower(), str(image_name).lower(), name.lower()])
                    
                    # Check for Layer 3 switch indicators first
                    l3_switch_keywords = ['l3 switch', 'layer3', 'layer 3', 'esw', 'c3640', 'c3560', 'c3750', 'multilayer']
                    is_l3_switch = any(k in full_desc for k in l3_switch_keywords)
                    
                    router_keywords = [
                        'router', 'ios', 'csr', 'isr', 'iosv', 'firepower', 'asa', 'xrv', 'nxos',
                        'c2691', 'c2600', 'c7200', 'c3725', 'c3745', 'c3660', 'c3845', 'c1900', 'c2900',
                        'adventerprisek9', 'advipservices'
                    ]
                    
                    # Classify: L3 switch -> core switch, router keywords -> router, else -> switch
                    if is_l3_switch:
                        ntype = 'core switch'
                    elif any(k in full_desc for k in router_keywords):
                        ntype = 'router'
                    else:
                        ntype = 'switch'
                    base = name; dev_name = base; i = 1
                    while any(d[0]==dev_name for d in self.devices):
                        dev_name = f"{base}-{i}"; i+=1
                    meta = {"gns3_node": True, "project_id": project_id, "node_id": node_id, "console_host": console_host, "console_port": str(console_port)}
                    self.add_device_instance(ntype, dev_name, metadata=meta)
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        cur.execute("INSERT OR REPLACE INTO devices (name,type,ip,port,connection_type,added_from_gns3,project_id,node_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                    (dev_name, ntype, console_host, str(console_port), 'gns3-console', 1, project_id, node_id, ts))
                        conn.commit()
                        imported += 1
                    except Exception as e:
                        self.log(f"[db] error saving gns3 device: {e}")
                if imported>0:
                    self.refresh_device_list()
                    self.log(f"auto-imported {imported} gns3 nodes from project {proj.get('name')}")
            except Exception as e:
                self.log(f"[gns3] could not list nodes: {e}")
        except Exception as e:
            self.lbl_gns3_status.configure(text=f"gns3 auto-connect failed: {e}")

    def gns3_list_projects(self):
        if requests is None:
            messagebox.showerror("error","requests not installed"); return
        url = simpledialog.askstring("gns3 url", "enter gns3 server url (e.g. http://localhost:3080):", initialvalue=GNS3_DEFAULT_URL, parent=self)
        if not url: return
        self.gns3 = GNS3Connector(server_url=url)
        try:
            projs = self.gns3.get_projects()
            if not projs:
                messagebox.showinfo("gns3","no projects found on server"); return
            choices = [f"{p.get('name','<unnamed>')} ({p.get('project_id') or p.get('projectId')})" for p in projs]
            sel = simpledialog.askinteger("select project", "\n".join(f"{i+1}. {c}" for i,c in enumerate(choices)) + "\n\nenter number:", parent=self, minvalue=1, maxvalue=len(choices))
            if not sel: return
            project = projs[sel-1]
            self.last_gns3_project = project
            messagebox.showinfo("gns3", f"selected {project.get('name')}")
            self.gns3_list_nodes(project.get('project_id') or project.get('projectId'))
        except Exception as e:
            messagebox.showerror("gns3 error", str(e))

    def gns3_list_nodes(self, project_id=None):
        if self.gns3 is None:
            messagebox.showerror("error","gns3 connector not initialized"); return
        if project_id is None:
            project_id = getattr(self, "last_gns3_project", {}).get("project_id") or getattr(self, "last_gns3_project", {}).get("projectId")
            if not project_id:
                messagebox.showinfo("info","call list projects first"); return
        try:
            nodes = self.gns3.get_nodes(project_id)
        except Exception as e:
            messagebox.showerror("gns3 error", str(e)); return
        labels = []
        for i,n in enumerate(nodes):
            ch = f"{i+1}. {n.get('name')}  ({n.get('node_type')})  console:{n.get('console_host','localhost')}:{n.get('console') or n.get('console_port') or ''}"
            labels.append(ch)
        sel = simpledialog.askinteger("select node", "\n".join(labels) + "\n\nenter number to import:", parent=self, minvalue=1, maxvalue=len(labels))
        if not sel: return
        node = nodes[sel-1]
        console_host = node.get("console_host", "localhost")
        console_port = node.get("console") or node.get("console_port") or ""
        name = node.get("name") or f"node-{str(node.get('node_id',''))[:6]}"
        dtype = simpledialog.askstring("device type", "device type for imported node (router/switch/core switch):", initialvalue="router", parent=self)
        if not dtype: return
        dtype = dtype.strip().lower()
        if dtype not in self.device_types:
            messagebox.showerror("error","unknown type"); return
        meta = {"gns3_node": True, "project_id": project_id, "node_id": node.get("node_id") or node.get("id"), "console_host": console_host, "console_port": console_port}
        base = name; dev_name = base; i = 1
        while any(d[0]==dev_name for d in self.devices):
            dev_name = f"{base}-{i}"; i+=1
        self.add_device_instance(dtype, dev_name, metadata=meta)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            cur.execute("INSERT OR REPLACE INTO devices (name,type,ip,port,connection_type,added_from_gns3,project_id,node_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (dev_name, dtype, console_host, str(console_port), "gns3-console", 1, project_id, node.get("node_id") or node.get("id"), ts))
            conn.commit()
        except Exception as e:
            self.log(f"[db] error saving gns3 device: {e}")
        self.refresh_device_list()
        messagebox.showinfo("gns3", f"imported node as '{dev_name}' (saved to DB)")

    # ------------------- view saved devices (simple popup) -------------------
    def view_saved_devices(self):
        try:
            cur.execute("SELECT id, name, type, ip, port, connection_type, added_from_gns3, created_at FROM devices ORDER BY id DESC")
            rows = cur.fetchall()
        except Exception as e:
            messagebox.showerror("db error", str(e)); return
        if not rows:
            messagebox.showinfo("database", "no saved devices found."); return
        win = tk.Toplevel(self)
        win.title("saved devices")
        win.geometry("700x420")
        tree = ttk.Treeview(win, columns=("id","name","type","ip","port","conn","gns3","created"), show="headings")
        for h,w in [("id",60),("name",180),("type",120),("ip",120),("port",70),("conn",100),("gns3",60),("created",140)]:
            tree.heading(h, text=h); tree.column(h, width=w, anchor="center")
        tree.pack(fill="both", expand=True)
        for r in rows:
            tree.insert("", "end", values=r)
        def on_double(e=None):
            sel = tree.selection()
            if not sel: return
            item = tree.item(sel[0])["values"]
            name = item[1]; ip = item[3]; port = item[4]; conn_type = item[5]
            dtype = simpledialog.askstring("device type", "device type for workspace (router/switch/core switch):", initialvalue="router", parent=self)
            if not dtype: return
            dtype = dtype.strip().lower()
            if dtype not in self.device_types:
                messagebox.showerror("error","unknown type"); return
            meta = {"ip": ip, "port": port, "connection_type": conn_type}
            self.add_device_instance(dtype, name, metadata=meta)
            self.refresh_device_list()
            messagebox.showinfo("imported", f"{name} imported to workspace")
        tree.bind("<Double-1>", on_double)
        
        
    # ---------- quick subnet_calculator (method version) ----------
    def subnet_calculator(self):
        try:
            base_ip = simpledialog.askstring("subnet calculator", "enter base network (e.g. 192.168.10.0/24):", parent=self)
            if not base_ip:
                return

            network = ipaddress.ip_network(base_ip, strict=False)
            dept_count_s = simpledialog.askstring("subnet calculator", "how many departments?:", parent=self)
            if not dept_count_s:
                return
            dept_count = int(dept_count_s)

            dept_sizes = []
            for i in range(dept_count):
                h_s = simpledialog.askstring("subnet calculator", f"number of hosts in department #{i+1}:", parent=self)
                if not h_s:
                    return
                dept_sizes.append(int(h_s))

            # sort descending (largest first)
            dept_sizes.sort(reverse=True)

            results = []
            remaining = [network]

            for i, hosts in enumerate(dept_sizes):
                needed = hosts + 2
                bits = 0
                while (2 ** bits) < needed:
                    bits += 1
                subnet_prefix = 32 - bits

                alloc = None
                for idx, sn in enumerate(remaining):
                    if sn.prefixlen <= subnet_prefix:
                        subs = list(sn.subnets(new_prefix=subnet_prefix))
                        if subs:
                            alloc = subs[0]
                            # remove the original and extend with remainder
                            remaining.pop(idx)
                            remaining[idx:idx] = subs[1:]
                            break

                if not alloc:
                    messagebox.showerror("Error", f"No space for department needing {hosts} hosts")
                    continue

                hosts_list = list(alloc.hosts())
                broadcast = alloc.broadcast_address
                default_gateway = hosts_list[0] if hosts_list else "N/A"
                available_range = f"{hosts_list[1]} - {hosts_list[-1]}" if len(hosts_list) > 2 else "N/A"

                results.append({
                    "Department": f"Dept-{i+1}",
                    "Network": str(alloc.network_address),
                    "Mask": str(alloc.netmask),
                    "Broadcast": str(broadcast),
                    "Gateway": str(default_gateway),
                    "Range": available_range
                })

            # show results
            out = "Subnetting Result:\n\n"
            for r in results:
                out += f"{r['Department']}:\n"
                out += f" Network: {r['Network']}\n"
                out += f" Mask: {r['Mask']}\n"
                out += f" Broadcast: {r['Broadcast']}\n"
                out += f" Gateway: {r['Gateway']}\n"
                out += f" Range: {r['Range']}\n\n"

            messagebox.showinfo("subnetting results", out)

        except Exception as e:
            messagebox.showerror("error", f"subnet calculator failed:\n{e}")

