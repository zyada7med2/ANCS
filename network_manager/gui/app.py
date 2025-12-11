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
        # Custom color theme matching Figma design
        ctk.set_default_color_theme("blue")
        
        # Figma design colors
        self.colors = {
            "bg_main": "#13151b",      # Main background (very dark blue-grey)
            "bg_sidebar": "#1a1f2e",   # Secondary background (sidebar/panels)
            "bg_card": "#222736",      # Cards/containers
            "bg_input": "#2b3040",     # Input field background
            "accent": "#4ade80",       # Primary accent (green for checkboxes/active)
            "accent_hover": "#22c55e", # Accent hover state
            "btn_primary": "#3b82f6",  # Primary button (blue)
            "btn_primary_hover": "#2563eb",  # Primary button hover
            "text_primary": "#ffffff",
            "text_secondary": "#9ca3af",
            "success": "#4ade80",
            "danger": "#ef4444",
            "border": "#374151",
        }

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
        # Configure main window background - Figma dark theme
        self.configure(fg_color="#13151b")
        
        top = ctk.CTkFrame(self, height=70, fg_color="#13151b")
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
        
        # If no logo image found, show text logo - Figma styled
        if self.logo_image is None:
            ctk.CTkLabel(logo_frame, text="ANCS", font=ctk.CTkFont(size=20, weight="bold"), text_color="#4ade80").pack(side="left", padx=4)
            ctk.CTkLabel(logo_frame, text="Auto Network\nConfiguration System", font=ctk.CTkFont(size=9), text_color="#9ca3af", justify="left").pack(side="left", padx=2)
        
        # Navigation tabs in CENTER of header - like Figma photo 1
        nav_frame = ctk.CTkFrame(top, fg_color="transparent")
        nav_frame.pack(side="left", fill="x", expand=True)
        
        # Center the nav buttons using inner frame
        nav_inner = ctk.CTkFrame(nav_frame, fg_color="transparent")
        nav_inner.pack(expand=True)
        
        # Main tab with icon and underline
        self.main_tab_frame = ctk.CTkFrame(nav_inner, fg_color="transparent")
        self.main_tab_frame.pack(side="left", padx=12)
        self.btn_main_nav = ctk.CTkButton(self.main_tab_frame, text="🏠 Main", command=lambda: self._switch_tab("main"),
                                         fg_color="transparent", hover_color="#222736", width=90, height=32,
                                         font=ctk.CTkFont(size=13, weight="bold"), text_color="#4ade80")
        self.btn_main_nav.pack()
        self.main_underline = ctk.CTkFrame(self.main_tab_frame, height=3, fg_color="#4ade80")
        self.main_underline.pack(fill="x", pady=(4,0))
        
        # Logs tab with icon and underline
        self.logs_tab_frame = ctk.CTkFrame(nav_inner, fg_color="transparent")
        self.logs_tab_frame.pack(side="left", padx=12)
        self.btn_logs_nav = ctk.CTkButton(self.logs_tab_frame, text="☰ Logs", command=lambda: self._switch_tab("logs"),
                                          fg_color="transparent", hover_color="#222736", width=90, height=32,
                                          font=ctk.CTkFont(size=13), text_color="#9ca3af")
        self.btn_logs_nav.pack()
        self.logs_underline = ctk.CTkFrame(self.logs_tab_frame, height=3, fg_color="transparent")
        self.logs_underline.pack(fill="x", pady=(4,0))
        
        # Create tabview - Figma dark theme
        self.nb = ctk.CTkTabview(self, fg_color="#13151b", segmented_button_fg_color="#13151b",
                                segmented_button_selected_color="#13151b", 
                                segmented_button_unselected_color="#13151b")
        self.nb.pack(fill="both", expand=True, padx=12, pady=8)
        # Only add main and logs tabs - database tab code kept but hidden
        self.nb.add("main")
        self.nb.add("output / logs")
        # Hide the default tab buttons (we're using custom navigation)
        self.nb._segmented_button.pack_forget()
        # Database tab: keep code but don't show tab (commented out for future use)
        # self.nb.add("database")
        self.tab_main = self.nb.tab("main")
        self.tab_logs = self.nb.tab("output / logs")
        # Keep database tab reference for future use (code remains intact)
        # self.tab_db = self.nb.tab("database")
    
        # left column - Figma styled
        left_container = ctk.CTkFrame(self.tab_main, width=280, fg_color="#1a1f2e", corner_radius=8)
        left_container.pack(side="left", fill="y", padx=(8,4), pady=8)
        left_container.pack_propagate(False)
        left_scroll = ctk.CTkScrollableFrame(left_container, width=260, fg_color="transparent")
        left_scroll.pack(fill="both", expand=True, padx=4, pady=4)
        left = left_scroll
        
        # ═══════════════════════════════════════════════════════════════
        # DEVICES SECTION - Custom list with checkboxes like Figma photo 1
        # ═══════════════════════════════════════════════════════════════
        ctk.CTkLabel(left, text="Devices", font=ctk.CTkFont(size=14, weight="bold"), text_color="#ffffff").pack(anchor="nw", padx=8, pady=(8,4))
        
        # Custom devices list container
        self.devices_list_frame = ctk.CTkFrame(left, fg_color="#222736", corner_radius=8)
        self.devices_list_frame.pack(fill="x", padx=8, pady=(0,4))
        
        # Scrollable frame for device items
        self.devices_scroll = ctk.CTkScrollableFrame(self.devices_list_frame, fg_color="transparent", height=180)
        self.devices_scroll.pack(fill="x", padx=2, pady=2)
        
        # Store device item widgets and selection state
        self.device_items = {}  # {name: {"frame": frame, "checkbox": checkbox, "selected": bool}}
        self.selected_device_name = None

        # Device buttons - OUTLINED style like Figma
        dbbtns = ctk.CTkFrame(left, fg_color="transparent")
        dbbtns.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(dbbtns, text="+ Add", command=self.add_device_prompt,
                     fg_color="transparent", hover_color="#222736", 
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     font=ctk.CTkFont(size=11), corner_radius=8, height=30).pack(side="left", expand=True, padx=(0,4))
        ctk.CTkButton(dbbtns, text="🗑 Remove", command=self.remove_selected_device,
                     fg_color="transparent", hover_color="#222736",
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     font=ctk.CTkFont(size=11), corner_radius=8, height=30).pack(side="left", expand=True, padx=(4,0))

        # ═══════════════════════════════════════════════════════════════
        # TEMPLATES SECTION - Custom list with checkboxes like Figma photo 1
        # ═══════════════════════════════════════════════════════════════
        ctk.CTkLabel(left, text="Templates", font=ctk.CTkFont(size=14, weight="bold"), text_color="#ffffff").pack(anchor="nw", padx=8, pady=(12,4))
        
        # Custom templates list container
        self.templates_list_frame = ctk.CTkFrame(left, fg_color="#222736", corner_radius=8)
        self.templates_list_frame.pack(fill="both", expand=True, padx=8, pady=(0,4))
        
        # Scrollable frame for template items
        self.templates_scroll = ctk.CTkScrollableFrame(self.templates_list_frame, fg_color="transparent")
        self.templates_scroll.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Store template item widgets and selection state
        self.template_items = {}  # {name: {"frame": frame, "checkbox": checkbox, "selected": bool}}
        self.selected_template_name = None

        # Template buttons - OUTLINED style like Figma
        tbtns = ctk.CTkFrame(left, fg_color="transparent")
        tbtns.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(tbtns, text="+ Add", command=self.add_template_dialog,
                     fg_color="transparent", hover_color="#222736",
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     font=ctk.CTkFont(size=11), corner_radius=8, height=30).pack(side="left", expand=True, padx=(0,4))
        ctk.CTkButton(tbtns, text="✏ Edit", command=self.edit_template_dialog,
                     fg_color="transparent", hover_color="#222736",
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     font=ctk.CTkFont(size=11), corner_radius=8, height=30).pack(side="left", expand=True, padx=(4,0))
        
        # Guided Setup Wizard button - Figma styled (solid green accent)
        ctk.CTkButton(left, text="🧙 Guided Setup (Beginner)", command=self.guided_setup,
                     fg_color="#4ade80", hover_color="#22c55e", text_color="#13151b",
                     font=ctk.CTkFont(size=11, weight="bold"), corner_radius=8, height=34).pack(fill="x", padx=8, pady=(12,4))
        
        # Subnet Calculator GUI button - Figma styled (outlined green)
        ctk.CTkButton(left, text="🔢 Subnet Calculator (GUI)", command=lambda: SubnetCalculator(self),
                     fg_color="transparent", hover_color="#222736",
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     font=ctk.CTkFont(size=11), corner_radius=8, height=32).pack(fill="x", padx=8, pady=(4,8))

        # center area - Figma styled
        center = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        center.pack(side="left", fill="both", expand=True, padx=6, pady=8)

        # Preview header with title and OUTLINED buttons on top right
        topc = ctk.CTkFrame(center, fg_color="transparent")
        topc.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(topc, text="Preview", font=ctk.CTkFont(size=16, weight="bold"), text_color="#ffffff").pack(side="left")
        gframe = ctk.CTkFrame(topc, fg_color="transparent")
        gframe.pack(side="right")
        ctk.CTkButton(gframe, text="Save config to db", 
                     fg_color="transparent", hover_color="#222736",
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     command=self.save_config_to_db, width=130, height=32,
                     font=ctk.CTkFont(size=11), corner_radius=8).pack(side="left", padx=(0, 8))
        ctk.CTkButton(gframe, text="View saved configs", 
                     fg_color="transparent", hover_color="#222736",
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     command=self.view_saved_configs, width=140, height=32,
                     font=ctk.CTkFont(size=11), corner_radius=8).pack(side="left")

        # Preview holder - dark card like Figma
        preview_holder = ctk.CTkFrame(center, fg_color="#222736", corner_radius=10)
        preview_holder.pack(fill="both", expand=True, padx=0, pady=0)
        
        # Inner preview area - darker
        self.preview = ctk.CTkTextbox(preview_holder, wrap="none", 
                                     font=ctk.CTkFont(family="Consolas", size=11),
                                     fg_color="#2b3040", text_color="#ffffff",
                                     corner_radius=8, border_width=1, border_color="#374151")
        self.preview.pack(fill="both", expand=True, padx=12, pady=(12, 8))
        
        # Bottom buttons frame
        bottom_btn_frame = ctk.CTkFrame(preview_holder, fg_color="transparent")
        bottom_btn_frame.pack(fill="x", padx=12, pady=(0, 12))
        
        # Generate button - SOLID filled blue like Figma
        ctk.CTkButton(
            bottom_btn_frame, 
            text="Generate", 
            command=self.generate_full,
            fg_color="#3b82f6",
            hover_color="#2563eb",
            text_color="#ffffff",
            width=110,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=8
        ).pack(side="left")
        
        # Clear Preview button - OUTLINED red like Figma
        ctk.CTkButton(
            bottom_btn_frame, 
            text="Clear Preview", 
            command=self.clear_preview,
            fg_color="transparent",
            hover_color="#222736",
            border_width=1,
            border_color="#ef4444",
            text_color="#ef4444",
            width=120,
            height=32,
            font=ctk.CTkFont(size=11),
            corner_radius=8
        ).pack(side="right")
        
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

        # right column - Figma styled card
        right = ctk.CTkFrame(self.tab_main, width=300, fg_color="#1a1f2e", corner_radius=10)
        right.pack(side="right", fill="y", padx=(4,8), pady=8)
        right.pack_propagate(False)
        
        # CONFIG STATUS SECTION - Like Figma design
        ctk.CTkLabel(right, text="Config Status", font=ctk.CTkFont(size=14, weight="bold"), 
                    text_color="#ffffff").pack(anchor="nw", padx=12, pady=(12,8))
        
        # Config name row with Connected badge
        config_row = ctk.CTkFrame(right, fg_color="transparent")
        config_row.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(config_row, text="config name", font=ctk.CTkFont(size=11), 
                    text_color="#9ca3af").pack(side="left")
        
        # Connected badge - green pill like Figma
        self.lbl_gns3_status = ctk.CTkLabel(config_row, text="● Connected", 
                                           font=ctk.CTkFont(size=11),
                                           text_color="#4ade80",
                                           fg_color="transparent")
        self.lbl_gns3_status.pack(side="right")
        
        # Import and Refresh buttons - OUTLINED like Figma
        gns3_controls = ctk.CTkFrame(right, fg_color="transparent")
        gns3_controls.pack(fill="x", padx=12, pady=(0, 16))
        ctk.CTkButton(gns3_controls, text="⬆ Import", command=self.gns3_list_projects,
                     fg_color="transparent", hover_color="#222736",
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     width=100, height=32, font=ctk.CTkFont(size=11), corner_radius=8).pack(side="left", padx=(0, 8))
        ctk.CTkButton(gns3_controls, text="↻ Refresh", command=self.refresh_gns3_connection, 
                     fg_color="transparent", hover_color="#222736",
                     border_width=1, border_color="#4ade80", text_color="#4ade80",
                     width=100, height=32, font=ctk.CTkFont(size=11), corner_radius=8).pack(side="left")
        
        # SEND / CONNECT SECTION
        ctk.CTkLabel(right, text="Send / Connect", font=ctk.CTkFont(size=14, weight="bold"), 
                    text_color="#ffffff").pack(anchor="nw", padx=12, pady=(0,8))
        
        # Protocol dropdown - SOLID filled blue like Figma
        self.send_method = ctk.CTkOptionMenu(right, values=["Telnet", "Serial", "SSH"],
                                            fg_color="#3b82f6", button_color="#2563eb",
                                            button_hover_color="#1d4ed8", text_color="#ffffff",
                                            font=ctk.CTkFont(size=11), corner_radius=8, height=36) 
        self.send_method.set("Telnet")
        self.send_method.pack(fill="x", padx=12, pady=(0,12))
        self.send_method.configure(command=self._on_protocol_changed)

        # Serial fields section
        self.lbl_serial_title = ctk.CTkLabel(right, text="Serial", font=ctk.CTkFont(size=12, weight="bold"), 
                                            text_color="#ffffff")
        self.lbl_serial_title.pack(anchor="w", padx=12, pady=(0,6))
        
        self.ent_serial_port = ctk.CTkEntry(right, placeholder_text="COM3 or /dev/ttyUSB0",
                                           font=ctk.CTkFont(size=11), height=36,
                                           fg_color="#2b3040", border_color="#374151",
                                           corner_radius=8, text_color="#ffffff")
        self.ent_serial_port.pack(fill="x", padx=12, pady=(0,6))
        
        self.ent_serial_baud = ctk.CTkEntry(right, placeholder_text="9600",
                                           font=ctk.CTkFont(size=11), height=36,
                                           fg_color="#2b3040", border_color="#374151",
                                           corner_radius=8, text_color="#ffffff")
        self.ent_serial_baud.pack(fill="x", padx=12, pady=(0,12))

        # Network fields section
        self.lbl_network_title = ctk.CTkLabel(right, text="Network", font=ctk.CTkFont(size=12, weight="bold"), 
                                             text_color="#ffffff")
        self.lbl_network_title.pack(anchor="w", padx=12, pady=(0,6))
        
        self.ent_host = ctk.CTkEntry(right, placeholder_text="Host or Ip",
                                    font=ctk.CTkFont(size=11), height=36,
                                    fg_color="#2b3040", border_color="#374151",
                                    corner_radius=8, text_color="#ffffff")
        self.ent_host.pack(fill="x", padx=12, pady=(0,6))
        
        self.ent_port = ctk.CTkEntry(right, placeholder_text="Port",
                                     font=ctk.CTkFont(size=11), height=36,
                                     fg_color="#2b3040", border_color="#374151",
                                     corner_radius=8, text_color="#ffffff")
        self.ent_port.pack(fill="x", padx=12, pady=(0,6))
        self.ent_user = ctk.CTkEntry(right, placeholder_text="Username",
                                    font=ctk.CTkFont(size=11), height=36,
                                    fg_color="#2b3040", border_color="#374151",
                                    corner_radius=8, text_color="#ffffff")
        self.ent_user.pack(fill="x", padx=12, pady=(0,6))
        
        self.ent_pass = ctk.CTkEntry(right, placeholder_text="Password", show="*",
                                    font=ctk.CTkFont(size=11), height=36,
                                    fg_color="#2b3040", border_color="#374151",
                                    corner_radius=8, text_color="#ffffff")
        self.ent_pass.pack(fill="x", padx=12, pady=(0,6))
        
        # Optional enable password - Figma styled
        ctk.CTkLabel(right, text="Optional", font=ctk.CTkFont(size=10), 
                    text_color="#9ca3af").pack(anchor="w", padx=12, pady=(4,2))
        enable_frame = ctk.CTkFrame(right, fg_color="transparent")
        enable_frame.pack(fill="x", padx=12, pady=(0,0))
        self.enable_checkbox = ctk.CTkCheckBox(enable_frame, text="",
                                              font=ctk.CTkFont(size=11), width=20,
                                              fg_color="#4ade80", hover_color="#22c55e",
                                              border_color="#374151")
        self.enable_checkbox.pack(side="right", padx=(4,0))
        self.ent_enable = ctk.CTkEntry(enable_frame, placeholder_text="Enable Password", show="*",
                                      font=ctk.CTkFont(size=11), height=36,
                                      fg_color="#2b3040", border_color="#374151",
                                      corner_radius=8, text_color="#ffffff")
        self.ent_enable.pack(side="left", fill="x", expand=True)

        # Send button - Solid filled blue like Figma
        ctk.CTkButton(right, text="Send", command=self.send_now, 
                     fg_color="#3b82f6", hover_color="#2563eb", text_color="#ffffff",
                     height=40, font=ctk.CTkFont(size=12, weight="bold"),
                     corner_radius=8).pack(fill="x", padx=12, pady=(16,12))
        
        # Store references for conditional enabling
        self.serial_widgets = [self.lbl_serial_title, self.ent_serial_port, self.ent_serial_baud]
        self.network_widgets = [self.lbl_network_title, self.ent_host, self.ent_port, self.ent_user, self.ent_pass, self.ent_enable, self.enable_checkbox]
        
        # Initialize field states based on default protocol
        self._on_protocol_changed("Telnet")

        # logs tab - Figma styled
        logs_card = ctk.CTkFrame(self.tab_logs, fg_color="#222736", corner_radius=10)
        logs_card.pack(fill="both", expand=True, padx=12, pady=12)
        
        ctk.CTkLabel(logs_card, text="Output", font=ctk.CTkFont(size=16, weight="bold"),
                    text_color="#ffffff").pack(anchor="nw", padx=16, pady=(12,8))
        
        self.txt_logs = ctk.CTkTextbox(logs_card, font=ctk.CTkFont(family="Consolas", size=11),
                                      fg_color="#2b3040", text_color="#ffffff",
                                      corner_radius=8, border_width=1, border_color="#374151")
        self.txt_logs.pack(fill="both", expand=True, padx=12, pady=(0,12))
        # Clear Logs button in bottom right corner - OUTLINED red like Figma
        clear_logs_frame = ctk.CTkFrame(logs_card, fg_color="transparent")
        clear_logs_frame.pack(fill="x", padx=12, pady=(0,12))
        clear_logs_btn = ctk.CTkButton(clear_logs_frame, text="Clear Logs", 
                                      command=lambda: self.txt_logs.delete("0.0","end"),
                                      fg_color="transparent", hover_color="#222736",
                                      border_width=1, border_color="#ef4444",
                                      text_color="#ef4444", width=110, height=32,
                                      font=ctk.CTkFont(size=11), corner_radius=8)
        clear_logs_btn.pack(side="right")

        # Database tab: professional multi-entity browser
        # NOTE: Database tab UI code is kept but commented out since tab is hidden from users
        # All database methods remain functional for future use
        # To re-enable: uncomment the tab creation line (around line 179) and uncomment this section
        
        # Initialize database treeviews as None to prevent errors in methods
        self.tree_devices = None
        self.tree_configs = None
        self.tree_users = None
        self.tree_tasks = None
        self.tree_logs = None
        self.tree_ai_models = None
        self.tree_training = None
        self.db_tabview = None
        
        # Database tab UI code commented out - tab hidden from users
        # To re-enable: uncomment the tab creation line (around line 175) and change False to True below
        # All database tab UI code is preserved below but disabled
        if False:  # Database tab UI disabled - set to True and uncomment tab_db creation to enable
            pass  # Placeholder - actual code preserved in comments below
            """
            Database tab UI code (preserved for future use):
            
            ctk.CTkLabel(
                self.tab_db,
                text="database browser",
                font=ctk.CTkFont(size=14, weight="bold")
            ).pack(anchor="nw", padx=12, pady=(8, 2))

            db_top = ctk.CTkFrame(self.tab_db, fg_color="transparent")
            db_top.pack(fill="x", padx=12, pady=(0, 6))
            ctk.CTkLabel(
                db_top,
                text=f"SQLite file: {DB_PATH}",
                font=ctk.CTkFont(size=11),
                text_color="#bcd",
            ).pack(side="left")

            # Inner tabview for each logical entity in the database
            self.db_tabview = ctk.CTkTabview(self.tab_db)
            self.db_tabview.pack(fill="both", expand=True, padx=12, pady=8)

            tab_devices = self.db_tabview.add("devices")
            tab_configs = self.db_tabview.add("configs")
            tab_users = self.db_tabview.add("users")
            tab_tasks = self.db_tabview.add("tasks")
            tab_logs = self.db_tabview.add("logs")
            tab_ai = self.db_tabview.add("ai models")
            tab_training = self.db_tabview.add("training data")

            # ----- devices tab -----
            devices_frame = ctk.CTkFrame(tab_devices)
            devices_frame.pack(fill="both", expand=True, padx=4, pady=4)

            self.tree_devices = ttk.Treeview(
                devices_frame,
                columns=("id", "name", "type", "ip", "port", "conn", "gns3", "status", "last_seen", "created"),
                show="headings",
            )
            for h, w in [
                ("id", 50),
                ("name", 160),
                ("type", 100),
                ("ip", 110),
                ("port", 70),
                ("conn", 90),
                ("gns3", 60),
                ("status", 90),
                ("last_seen", 130),
                ("created", 150),
            ]:
                self.tree_devices.heading(h, text=h)
                self.tree_devices.column(h, width=w, anchor="center")
            self.tree_devices.pack(fill="both", expand=True)

            dev_btns = ctk.CTkFrame(tab_devices, fg_color="transparent")
            dev_btns.pack(fill="x", padx=4, pady=(0, 6))
            ctk.CTkButton(dev_btns, text="refresh devices", command=self.refresh_devices_tree).pack(side="left", padx=4)
            ctk.CTkButton(
                dev_btns,
                text="import selected into workspace",
                command=self.import_device_from_tree,
            ).pack(side="left", padx=4)

            # ----- configs (legacy generated configs) -----
            configs_frame = ctk.CTkFrame(tab_configs)
            configs_frame.pack(fill="both", expand=True, padx=4, pady=4)

            self.tree_configs = ttk.Treeview(
                configs_frame,
                columns=("id", "device_id", "name", "created"),
                show="headings",
            )
            for h, w in [("id", 60), ("device_id", 100), ("name", 220), ("created", 160)]:
                self.tree_configs.heading(h, text=h)
                self.tree_configs.column(h, width=w, anchor="center")
            self.tree_configs.pack(fill="both", expand=True)

            cfg_btns = ctk.CTkFrame(tab_configs, fg_color="transparent")
            cfg_btns.pack(fill="x", padx=4, pady=(0, 6))
            ctk.CTkButton(cfg_btns, text="refresh configs", command=self.refresh_configs_tree).pack(side="left", padx=4)
            ctk.CTkButton(
                cfg_btns,
                text="load selected into preview",
                command=self.load_config_into_preview,
            ).pack(side="left", padx=4)

            # ----- users -----
            users_frame = ctk.CTkFrame(tab_users)
            users_frame.pack(fill="both", expand=True, padx=4, pady=4)

            self.tree_users = ttk.Treeview(
                users_frame,
                columns=("id", "username", "email", "role", "created"),
                show="headings",
            )
            for h, w in [
                ("id", 60),
                ("username", 140),
                ("email", 200),
                ("role", 90),
                ("created", 160),
            ]:
                self.tree_users.heading(h, text=h)
                self.tree_users.column(h, width=w, anchor="center")
            self.tree_users.pack(fill="both", expand=True)

            ctk.CTkButton(
                tab_users,
                text="refresh users",
                command=self.refresh_users_tree,
            ).pack(padx=4, pady=(0, 6), anchor="w")

            # ----- tasks -----
            tasks_frame = ctk.CTkFrame(tab_tasks)
            tasks_frame.pack(fill="both", expand=True, padx=4, pady=4)

            self.tree_tasks = ttk.Treeview(
                tasks_frame,
                columns=("id", "device_id", "task_type", "status", "executed_by", "created"),
                show="headings",
            )
            for h, w in [
                ("id", 60),
                ("device_id", 90),
                ("task_type", 150),
                ("status", 90),
                ("executed_by", 100),
                ("created", 160),
            ]:
                self.tree_tasks.heading(h, text=h)
                self.tree_tasks.column(h, width=w, anchor="center")
            self.tree_tasks.pack(fill="both", expand=True)

            ctk.CTkButton(
                tab_tasks,
                text="refresh tasks",
                command=self.refresh_tasks_tree,
            ).pack(padx=4, pady=(0, 6), anchor="w")

            # ----- logs -----
            logs_frame = ctk.CTkFrame(tab_logs)
            logs_frame.pack(fill="both", expand=True, padx=4, pady=4)

            self.tree_logs = ttk.Treeview(
                logs_frame,
                columns=("id", "user_id", "device_id", "action", "severity", "created"),
                show="headings",
            )
            for h, w in [
                ("id", 50),
                ("user_id", 70),
                ("device_id", 80),
                ("action", 220),
                ("severity", 90),
                ("created", 160),
            ]:
                self.tree_logs.heading(h, text=h)
                self.tree_logs.column(h, width=w, anchor="center")
            self.tree_logs.pack(fill="both", expand=True)

            ctk.CTkButton(
                tab_logs,
                text="refresh logs",
                command=self.refresh_logs_tree,
            ).pack(padx=4, pady=(0, 6), anchor="w")

            # ----- ai models -----
            ai_frame = ctk.CTkFrame(tab_ai)
            ai_frame.pack(fill="both", expand=True, padx=4, pady=4)

            self.tree_ai_models = ttk.Treeview(
                ai_frame,
                columns=("id", "model_name", "model_type", "accuracy", "version", "trained_at"),
                show="headings",
            )
            for h, w in [
                ("id", 50),
                ("model_name", 180),
                ("model_type", 140),
                ("accuracy", 90),
                ("version", 90),
                ("trained_at", 160),
            ]:
                self.tree_ai_models.heading(h, text=h)
                self.tree_ai_models.column(h, width=w, anchor="center")
            self.tree_ai_models.pack(fill="both", expand=True)

            ctk.CTkButton(
                tab_ai,
                text="refresh models",
                command=self.refresh_ai_models_tree,
            ).pack(padx=4, pady=(0, 6), anchor="w")

            # ----- training data -----
            training_frame = ctk.CTkFrame(tab_training)
            training_frame.pack(fill="both", expand=True, padx=4, pady=4)

            self.tree_training = ttk.Treeview(
                training_frame,
                columns=("id", "device_id", "label", "created"),
                show="headings",
            )
            for h, w in [
                ("id", 60),
                ("device_id", 90),
                ("label", 220),
                ("created", 160),
            ]:
                self.tree_training.heading(h, text=h)
                self.tree_training.column(h, width=w, anchor="center")
            self.tree_training.pack(fill="both", expand=True)

            ctk.CTkButton(
                tab_training,
                text="refresh training data",
                command=self.refresh_training_tree,
            ).pack(padx=4, pady=(0, 6), anchor="w")
            """
        
        # GNS3 tab removed - functionality moved to top right of main page
        # GNS3 controls are now in the center area above preview section

        # menu quick action
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        gmenu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="gns3", menu=gmenu)
        gmenu.add_command(label="import from gns3", command=lambda: self.gns3_list_projects())

        # Tab change handler removed - database tab is hidden from users
        # Database code remains intact for future use

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
        """Refresh the device list with Figma-style items"""
        # Clear existing items
        for name, item in self.device_items.items():
            item["frame"].destroy()
        self.device_items.clear()
        self.selected_device_name = None
        
        # Add new items
        for idx, (n, obj, meta) in enumerate(self.devices):
            label = f"{n} ({obj.__class__.__name__})"
            if meta.get("gns3_node"):
                label += " [gns3]"
            self._create_device_item(n, label, idx)
        
        # Select first item
        if self.devices:
            first_name = self.devices[0][0]
            self._on_device_item_click(first_name, 0)

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
        """Remove the selected device"""
        if not self.selected_device_name:
            messagebox.showinfo("info", "select device first")
            return
        # Find index
        idx = None
        for i, (n, _, _) in enumerate(self.devices):
            if n == self.selected_device_name:
                idx = i
                break
        if idx is None:
            return
        name = self.devices[idx][0]
        if messagebox.askyesno("confirm", f"remove {name}?"):
            del self.devices[idx]
            self.refresh_device_list()

    def on_device_select(self):
        """Legacy method - now handled by _on_device_item_click"""
        # This method is kept for compatibility but the main logic is in _on_device_item_click
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
        """Edit the selected template"""
        if not self.selected_template_name:
            messagebox.showinfo("info", "select template first")
            return
        if not self.current_device:
            messagebox.showinfo("info", "select device first")
            return
        tname = self.selected_template_name
        editor = TextEditorPopup(self, title=f"edit template: {tname}", initial=self.current_device[1].get_template(tname))
        self.wait_window(editor)
        if getattr(editor, "result", None) is not None:
            self.current_device[1].set_template(tname, editor.result)
            self._refresh_template_list()

    def on_template_select(self):
        """Legacy method - now handled by _on_template_item_click"""
        # This method is kept for compatibility but the main logic is in _on_template_item_click
        pass

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
        tk.Button(btns, text="Use selected", bg="#4ade80", fg="#13151b", command=confirm).pack(side="left", padx=4)
        tk.Button(btns, text="Cancel", command=cancel).pack(side="right", padx=4)

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self.wait_window(dialog)
        return choice["value"]
  

    # ------------------- generate / export / db -------------------
    def generate_selected(self):
        """Generate config for selected template"""
        if not self.selected_template_name:
            messagebox.showinfo("info", "select template first")
            return
        if not self.current_device:
            messagebox.showinfo("info", "select device first")
            return
        tname = self.selected_template_name
        txt = self.current_device[1].get_template(tname).replace("{name}", self.current_device[0])
        self.preview.delete("0.0", "end")
        self.preview.insert("0.0", txt)

    def generate_full(self):
        if not self.current_device:
            messagebox.showinfo("info", "select device first"); return
        txt = self.current_device[1].build_full_config().replace("{name}", self.current_device[0])
        self.preview.delete("0.0", "end")
        self.preview.insert("0.0", txt)

    def save_config_to_db(self):
        if not self.selected_device_name:
            messagebox.showinfo("info", "select device first"); return
        # Find device by name
        idx = None
        for i, (n, _, _) in enumerate(self.devices):
            if n == self.selected_device_name:
                idx = i
                break
        if idx is None:
            return
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
                        self._on_device_item_click(n, i)
                        break
                self.preview.delete("0.0","end"); self.preview.insert("0.0", content)
                win.destroy()
        tk.Button(win, text="load selected into preview", command=load_into_preview).pack(pady=6)

    # ------------------- db device functions -------------------
    def save_device_to_db(self):
        if not self.selected_device_name:
            messagebox.showinfo("info", "select device first"); return
        # Find device by name
        idx = None
        for i, (n, _, _) in enumerate(self.devices):
            if n == self.selected_device_name:
                idx = i
                break
        if idx is None:
            return
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
        if self.tree_devices is None:
            return  # Database tab UI not initialized
        for i in self.tree_devices.get_children(): self.tree_devices.delete(i)
        # include status/last_seen if present; fallback handled by SELECT
        try:
            cur.execute("""
                SELECT id,
                       name,
                       type,
                       ip,
                       port,
                       connection_type,
                       added_from_gns3,
                       COALESCE(status, 'unknown'),
                       COALESCE(last_seen, ''),
                       created_at
                FROM devices
                ORDER BY id DESC
            """)
        except Exception:
            # fallback to legacy schema if new columns are missing
            cur.execute("SELECT id,name,type,ip,port,connection_type,added_from_gns3,'' as status,'' as last_seen,created_at FROM devices ORDER BY id DESC")
        for r in cur.fetchall():
            self.tree_devices.insert("", "end", values=r)
    
    def _check_and_refresh_db_tab(self):
        """Helper method to refresh database tab if currently selected"""
        try:
            if self.nb.get() == "database":
                self.refresh_devices_tree()
                self.refresh_configs_tree()
                self.refresh_users_tree()
                self.refresh_tasks_tree()
                self.refresh_logs_tree()
                self.refresh_ai_models_tree()
                self.refresh_training_tree()
        except:
            pass

    def refresh_configs_tree(self):
        if self.tree_configs is None:
            return  # Database tab UI not initialized
        for i in self.tree_configs.get_children(): self.tree_configs.delete(i)
        cur.execute("SELECT id, device_id, config_name, created_at FROM configs ORDER BY id DESC")
        for r in cur.fetchall():
            self.tree_configs.insert("", "end", values=r)

    def refresh_users_tree(self):
        if self.tree_users is None:
            return  # Database tab UI not initialized
        for i in self.tree_users.get_children():
            self.tree_users.delete(i)
        try:
            cur.execute("SELECT id, username, email, role, created_at FROM users ORDER BY id DESC")
            rows = cur.fetchall()
        except Exception:
            rows = []
        for r in rows:
            self.tree_users.insert("", "end", values=r)

    def refresh_tasks_tree(self):
        if self.tree_tasks is None:
            return  # Database tab UI not initialized
        for i in self.tree_tasks.get_children():
            self.tree_tasks.delete(i)
        try:
            cur.execute("""
                SELECT id, device_id, task_type, status, executed_by, created_at
                FROM tasks
                ORDER BY id DESC
            """)
            rows = cur.fetchall()
        except Exception:
            rows = []
        for r in rows:
            self.tree_tasks.insert("", "end", values=r)

    def refresh_logs_tree(self):
        if self.tree_logs is None:
            return  # Database tab UI not initialized
        for i in self.tree_logs.get_children():
            self.tree_logs.delete(i)
        try:
            cur.execute("""
                SELECT id, user_id, device_id, action, severity, created_at
                FROM logs
                ORDER BY id DESC
            """)
            rows = cur.fetchall()
        except Exception:
            rows = []
        for r in rows:
            self.tree_logs.insert("", "end", values=r)

    def refresh_ai_models_tree(self):
        if self.tree_ai_models is None:
            return  # Database tab UI not initialized
        for i in self.tree_ai_models.get_children():
            self.tree_ai_models.delete(i)
        try:
            cur.execute("""
                SELECT id, model_name, model_type, accuracy, version, trained_at
                FROM ai_models
                ORDER BY id DESC
            """)
            rows = cur.fetchall()
        except Exception:
            rows = []
        for r in rows:
            self.tree_ai_models.insert("", "end", values=r)

    def refresh_training_tree(self):
        if self.tree_training is None:
            return  # Database tab UI not initialized
        for i in self.tree_training.get_children():
            self.tree_training.delete(i)
        try:
            cur.execute("""
                SELECT id, device_id, label, created_at
                FROM training_data
                ORDER BY id DESC
            """)
            rows = cur.fetchall()
        except Exception:
            rows = []
        for r in rows:
            self.tree_training.insert("", "end", values=r)

    def import_device_from_tree(self):
        if self.tree_devices is None:
            messagebox.showinfo("info", "Database tab not available"); return
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
        if self.tree_configs is None:
            messagebox.showinfo("info", "Database tab not available"); return
        sel = self.tree_configs.selection()
        if not sel:
            messagebox.showinfo("info","select config first"); return
        cfg_id = self.tree_configs.item(sel[0])["values"][0]
        cur.execute("SELECT content FROM configs WHERE id=?", (cfg_id,))
        r = cur.fetchone()
        if r:
            self.preview.delete("0.0","end"); self.preview.insert("0.0", r[0])
            

    # ------------------- logs only UI -------------------
    def clear_preview(self):
        """Clear the preview/config window"""
        try:
            self.preview.delete("0.0", "end")
            self.log("Preview cleared")
        except Exception:
            pass

    def log(self, msg):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.txt_logs.insert("0.0", f"[{ts}] {msg}\n")
            # echo small in preview
            self.preview.insert("0.0", f"[{ts}] {msg}\n")
        except Exception:
            pass

    # ------------------- config status helpers -------------------
    def _import_config(self):
        """Import config from file"""
        filename = filedialog.askopenfilename(
            title="Import Config",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'r') as f:
                    content = f.read()
                self.preview.delete("0.0", "end")
                self.preview.insert("0.0", content)
                self.log(f"Config imported from {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import config: {e}")
    
    def _refresh_config_status(self):
        """Refresh config status indicator"""
        # Config name is now in GNS3 section - this method kept for compatibility
        self.log("Config status refreshed")

    # ------------------- tab switching -------------------
    def _switch_tab(self, tab: str):
        """Switch between Main and Logs tabs with Figma-style underline animation"""
        if tab == "main":
            self.nb.set("main")
            self.btn_main_nav.configure(text_color="#4ade80")
            self.btn_logs_nav.configure(text_color="#9ca3af")
            self.main_underline.configure(fg_color="#4ade80")
            self.logs_underline.configure(fg_color="transparent")
        else:
            self.nb.set("output / logs")
            self.btn_main_nav.configure(text_color="#9ca3af")
            self.btn_logs_nav.configure(text_color="#4ade80")
            self.main_underline.configure(fg_color="transparent")
            self.logs_underline.configure(fg_color="#4ade80")

    # ------------------- custom list item helpers (Figma style) -------------------
    def _create_device_item(self, name: str, label: str, idx: int):
        """Create a device list item with checkbox - Figma style"""
        # Outer frame with left border for selection
        item_frame = ctk.CTkFrame(self.devices_scroll, fg_color="transparent", height=40)
        item_frame.pack(fill="x", pady=1)
        item_frame.pack_propagate(False)
        
        # Left border indicator (shows when selected)
        border = ctk.CTkFrame(item_frame, width=3, fg_color="transparent", corner_radius=0)
        border.pack(side="left", fill="y")
        
        # Content frame
        content = ctk.CTkFrame(item_frame, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=(4, 0))
        
        # Label
        lbl = ctk.CTkLabel(content, text=label, font=ctk.CTkFont(size=11), 
                          text_color="#ffffff", anchor="w")
        lbl.pack(side="left", fill="x", expand=True, padx=4)
        
        # Checkbox on right
        var = ctk.BooleanVar(value=False)
        checkbox = ctk.CTkCheckBox(content, text="", variable=var, width=20,
                                  fg_color="#4ade80", hover_color="#22c55e",
                                  border_color="#374151", corner_radius=4,
                                  command=lambda n=name, i=idx: self._on_device_item_click(n, i))
        checkbox.pack(side="right", padx=4)
        
        # Store reference
        self.device_items[name] = {
            "frame": item_frame, "border": border, "label": lbl, 
            "checkbox": checkbox, "var": var, "idx": idx
        }
        
        # Click binding on entire frame
        for widget in [item_frame, content, lbl]:
            widget.bind("<Button-1>", lambda e, n=name, i=idx: self._on_device_item_click(n, i))
    
    def _on_device_item_click(self, name: str, idx: int):
        """Handle device item selection"""
        # Deselect previous
        if self.selected_device_name and self.selected_device_name in self.device_items:
            prev = self.device_items[self.selected_device_name]
            prev["border"].configure(fg_color="transparent")
            prev["var"].set(False)
        
        # Select new
        self.selected_device_name = name
        if name in self.device_items:
            item = self.device_items[name]
            item["border"].configure(fg_color="#4ade80")
            item["var"].set(True)
        
        # Trigger device selection logic
        if 0 <= idx < len(self.devices):
            dname, model, meta = self.devices[idx]
            self.current_device = (dname, model, meta)
            self._refresh_template_list()
            # Update preview header
            try:
                self.preview.delete("0.0", "end")
                self.preview.insert("0.0", f"! device: {dname}\n")
            except Exception:
                pass
    
    def _create_template_item(self, name: str, idx: int):
        """Create a template list item with checkbox - Figma style"""
        # Outer frame with left border for selection
        item_frame = ctk.CTkFrame(self.templates_scroll, fg_color="transparent", height=40)
        item_frame.pack(fill="x", pady=1)
        item_frame.pack_propagate(False)
        
        # Left border indicator (shows when selected)
        border = ctk.CTkFrame(item_frame, width=3, fg_color="transparent", corner_radius=0)
        border.pack(side="left", fill="y")
        
        # Content frame
        content = ctk.CTkFrame(item_frame, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=(4, 0))
        
        # Label
        lbl = ctk.CTkLabel(content, text=name, font=ctk.CTkFont(size=11), 
                          text_color="#ffffff", anchor="w")
        lbl.pack(side="left", fill="x", expand=True, padx=4)
        
        # Checkbox on right
        var = ctk.BooleanVar(value=False)
        checkbox = ctk.CTkCheckBox(content, text="", variable=var, width=20,
                                  fg_color="#4ade80", hover_color="#22c55e",
                                  border_color="#374151", corner_radius=4,
                                  command=lambda n=name, i=idx: self._on_template_item_click(n, i))
        checkbox.pack(side="right", padx=4)
        
        # Store reference
        self.template_items[name] = {
            "frame": item_frame, "border": border, "label": lbl, 
            "checkbox": checkbox, "var": var, "idx": idx
        }
        
        # Click binding on entire frame
        for widget in [item_frame, content, lbl]:
            widget.bind("<Button-1>", lambda e, n=name, i=idx: self._on_template_item_click(n, i))
    
    def _on_template_item_click(self, name: str, idx: int):
        """Handle template item selection"""
        # Deselect previous
        if self.selected_template_name and self.selected_template_name in self.template_items:
            prev = self.template_items[self.selected_template_name]
            prev["border"].configure(fg_color="transparent")
            prev["var"].set(False)
        
        # Select new
        self.selected_template_name = name
        if name in self.template_items:
            item = self.template_items[name]
            item["border"].configure(fg_color="#4ade80")
            item["var"].set(True)
        
        # Show template content in preview
        if self.current_device:
            txt = self.current_device[1].get_template(name).replace("{name}", self.current_device[0])
            self.preview.delete("0.0", "end")
            self.preview.insert("0.0", txt)
    
    def _refresh_template_list(self):
        """Refresh the template list for current device"""
        # Clear existing items
        for name, item in self.template_items.items():
            item["frame"].destroy()
        self.template_items.clear()
        self.selected_template_name = None
        
        # Add new items
        if self.current_device:
            for idx, tname in enumerate(self.current_device[1].get_template_names()):
                self._create_template_item(tname, idx)

    # ------------------- conditional field enabling -------------------
    def _on_protocol_changed(self, value):
        """Enable/disable fields based on selected protocol - Figma colors"""
        protocol = value.lower()
        
        # Figma design colors for disabled fields
        disabled_color = "#222736"  # Same as card background
        disabled_text_color = "#4b5563"  # Muted gray
        enabled_color = "#2b3040"  # Dark input background
        enabled_label_color = "#ffffff"
        
        if protocol == "telnet":
            # Enable only Network IP and Port
            self.ent_host.configure(state="normal", fg_color=enabled_color)
            self.ent_port.configure(state="normal", fg_color=enabled_color)
            self.lbl_network_title.configure(text_color=enabled_label_color)
            # Disable other Network fields
            self.ent_user.configure(state="disabled", fg_color=disabled_color)
            self.ent_pass.configure(state="disabled", fg_color=disabled_color)
            self.ent_enable.configure(state="disabled", fg_color=disabled_color)
            self.enable_checkbox.configure(state="disabled")
            # Disable Serial fields
            for widget in self.serial_widgets:
                if isinstance(widget, ctk.CTkEntry):
                    widget.configure(state="disabled", fg_color=disabled_color)
                elif isinstance(widget, ctk.CTkLabel):
                    widget.configure(text_color=disabled_text_color)
        elif protocol == "serial":
            # Enable only Serial fields
            for widget in self.serial_widgets:
                if isinstance(widget, ctk.CTkEntry):
                    widget.configure(state="normal", fg_color=enabled_color)
                elif isinstance(widget, ctk.CTkLabel):
                    widget.configure(text_color=enabled_label_color)
            # Disable all Network fields
            self.ent_host.configure(state="disabled", fg_color=disabled_color)
            self.ent_port.configure(state="disabled", fg_color=disabled_color)
            self.ent_user.configure(state="disabled", fg_color=disabled_color)
            self.ent_pass.configure(state="disabled", fg_color=disabled_color)
            self.ent_enable.configure(state="disabled", fg_color=disabled_color)
            self.enable_checkbox.configure(state="disabled")
            self.lbl_network_title.configure(text_color=disabled_text_color)
        elif protocol == "ssh":
            # Enable all Network fields
            self.ent_host.configure(state="normal", fg_color=enabled_color)
            self.ent_port.configure(state="normal", fg_color=enabled_color)
            self.ent_user.configure(state="normal", fg_color=enabled_color)
            self.ent_pass.configure(state="normal", fg_color=enabled_color)
            self.ent_enable.configure(state="normal", fg_color=enabled_color)
            self.enable_checkbox.configure(state="normal")
            self.lbl_network_title.configure(text_color=enabled_label_color)
            # Disable Serial fields
            for widget in self.serial_widgets:
                if isinstance(widget, ctk.CTkEntry):
                    widget.configure(state="disabled", fg_color=disabled_color)
                elif isinstance(widget, ctk.CTkLabel):
                    widget.configure(text_color=disabled_text_color)

    # ------------------- send/run -------------------
    def send_now(self):
        content = self.preview.get("0.0","end").strip()
        if not content:
            messagebox.showinfo("info","nothing to send"); return
        method = self.send_method.get().lower()
        if method == "serial":
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
            # Telnet doesn't use username/password in this implementation
            user = ""; pw = ""; enable = ""
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
        if ok:
            self.clear_preview()

    def _thread_telnet(self, host, port, user, pw, enable, content):
        self.log(f"starting telnet to {host}:{port}")
        ok = Sender.send_telnet(self.log, host, port, user, pw, enable, content)
        self.log(f"telnet finished: {ok}")
        if ok:
            self.clear_preview()

    def _thread_ssh(self, host, port, user, pw, enable, content):
        self.log(f"starting ssh to {host}:{port} as {user}")
        ok = Sender.send_ssh(self.log, host, port, user, pw, enable, content)
        self.log(f"ssh finished: {ok}")
        if ok:
            self.clear_preview()

    # ------------------- GNS3 integration -------------------
    def refresh_gns3_connection(self):
        """Refresh GNS3 connection and detect newly opened projects"""
        if hasattr(self, 'lbl_gns3_status'):
            self.lbl_gns3_status.configure(text="refreshing gns3 connection...")
        threading.Thread(target=self._auto_connect_gns3, daemon=True).start()
    
    def _auto_connect_gns3(self):
        # try to auto-connect on startup and import nodes from open/most-recent project
        if requests is None:
            if hasattr(self, 'lbl_gns3_status'):
                self.lbl_gns3_status.configure(text="requests not installed; gns3 auto-import disabled")
            return
        try:
            g = GNS3Connector(GNS3_DEFAULT_URL)
            projs = g.get_projects()
            if not projs:
                if hasattr(self, 'lbl_gns3_status'):
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
            # Update GNS3 status label (now in main page top right)
            if hasattr(self, 'lbl_gns3_status'):
                self.lbl_gns3_status.configure(text=f"auto-connected to gns3, project: {proj.get('name')}")
            # import nodes
            try:
                # FIX: Use .get() with fallback for project_id
                project_id = proj.get('project_id') or proj.get('projectId') or proj.get('id')
                if not project_id:
                    if hasattr(self, 'lbl_gns3_status'):
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
                    # Check if device already exists in database by node_id
                    try:
                        cur.execute("SELECT name FROM devices WHERE node_id=? AND project_id=?", (node_id, project_id))
                        existing = cur.fetchone()
                        if existing:
                            # Device already exists, skip import
                            continue
                    except Exception:
                        pass  # If check fails, proceed with import
                    
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
            if hasattr(self, 'lbl_gns3_status'):
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
        node_id = node.get("node_id") or node.get("id")
        
        # Check if device already exists in database
        try:
            cur.execute("SELECT name FROM devices WHERE node_id=? AND project_id=?", (node_id, project_id))
            existing = cur.fetchone()
            if existing:
                messagebox.showinfo("Already Imported", f"This device '{existing[0]}' has already been imported from GNS3.", parent=self)
                return
        except Exception:
            pass
        
        console_host = node.get("console_host", "localhost")
        console_port = node.get("console") or node.get("console_port") or ""
        name = node.get("name") or f"node-{str(node_id or '')[:6]}"
        dtype = simpledialog.askstring("device type", "device type for imported node (router/switch/core switch):", initialvalue="router", parent=self)
        if not dtype: return
        dtype = dtype.strip().lower()
        if dtype not in self.device_types:
            messagebox.showerror("error","unknown type"); return
        meta = {"gns3_node": True, "project_id": project_id, "node_id": node_id, "console_host": console_host, "console_port": console_port}
        base = name; dev_name = base; i = 1
        while any(d[0]==dev_name for d in self.devices):
            dev_name = f"{base}-{i}"; i+=1
        self.add_device_instance(dtype, dev_name, metadata=meta)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            cur.execute("INSERT OR REPLACE INTO devices (name,type,ip,port,connection_type,added_from_gns3,project_id,node_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (dev_name, dtype, console_host, str(console_port), "gns3-console", 1, project_id, node_id, ts))
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

