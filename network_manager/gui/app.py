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
import base64
from typing import Optional


def _obfuscate(plaintext: str) -> str:
    """Base64-encode a password before storing. Not encryption — just prevents
    casual shoulder-surfing when the DB file is opened in a text editor."""
    if not plaintext:
        return ""
    return base64.b64encode(plaintext.encode("utf-8")).decode("ascii")


def _deobfuscate(stored: str) -> str:
    """Decode a base64-stored password. Falls back to returning as-is so
    legacy rows (plain text) still work."""
    if not stored:
        return ""
    try:
        return base64.b64decode(stored.encode("ascii")).decode("utf-8")
    except Exception:
        return stored  # legacy plain-text value


def _truncate(text: str, max_chars: int = 22) -> str:
    """Return text truncated with an ellipsis if it exceeds max_chars."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


class _Tooltip:
    """
    Lightweight hover tooltip for any tkinter widget.

    Usage:
        _Tooltip(widget, "Full text shown on hover")
    """

    def __init__(self, widget, text: str):
        self._widget = widget
        self._text   = text
        self._tip_win: Optional[tk.Toplevel] = None
        widget.bind("<Enter>",  self._show, add="+")
        widget.bind("<Leave>",  self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _show(self, event=None):
        if self._tip_win or not self._text:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip_win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self._text,
            background="#1F2630", foreground="#C9D1D9",
            font=("TkDefaultFont", 10),
            relief="solid", borderwidth=1,
            padx=6, pady=3,
        ).pack()

    def _hide(self, event=None):
        if self._tip_win:
            try:
                self._tip_win.destroy()
            except Exception:
                pass
            self._tip_win = None


# Import from our modules
from ..config import DB_PATH, GNS3_DEFAULT_URL, conn, cur, db_lock, _db_error
from ..models import DeviceModel, RouterModel, SwitchModel, CoreSwitchModel
from ..network import Sender, GNS3Connector
from .dialogs import TextEditorPopup
from .wizards import VlanGuiWindow, StpGuiWindow, GuidedSetupWizard
from .calculators import SubnetCalculator
from .topology_viewer import TopologyViewer
from .monitor import DeviceMonitor
from .terminal_panel import TerminalPanel
from .utils import apply_responsive_geometry

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
        self.minsize(650, 450)  # Smaller minimum - sidebar auto-hides when needed
        
        # Bind resize event for responsive sidebar
        self.bind("<Configure>", self._on_window_resize)

        ctk.set_appearance_mode("dark")
        # Custom color theme matching Figma design
        ctk.set_default_color_theme("blue")
        
        # Figma design colors - EXACT from design file
        self.colors = {
            "bg_main": "#0D1117",           # Desktop background (darkest)
            "bg_sidebar": "#1F2630",        # Sidebar panels
            "bg_card": "#1F2630",           # Cards/containers
            "bg_list": "#28313E",           # List items inner background
            "bg_preview": "#161B22",        # Preview code area (dark)
            "bg_input": "#2B323F",          # Input field background
            "bg_input_disabled": "#60656F", # Disabled input background
            "input_border": "#6B7280",      # Input border
            "input_border_disabled": "#777D81", # Disabled input border
            "accent": "#58A6FF",            # Primary blue (buttons, active)
            "accent_hover": "#4A90E8",      # Accent hover state
            "text_primary": "#C9D1D9",      # Primary text
            "text_white": "#FFFFFF",        # White text
            "text_secondary": "#9BA3AF",    # Secondary/muted text
            "text_title": "#F0F2F4",        # Bright title text
            "text_dark": "#15191E",         # Dark text on light bg
            "success_bg": "#ECFDF3",        # Success badge background
            "success_text": "#085D3A",      # Success text
            "danger": "#EF4444",            # Error/danger
            "highlight": "#E5F1FF",         # Selection highlight
        }

        # device types
        self.device_types = {"router": RouterModel, "switch": SwitchModel, "core switch": CoreSwitchModel}
        self.devices: list[tuple[str, DeviceModel, dict]] = []  # (name, model, meta)
        self.current_device: Optional[tuple[str, DeviceModel, dict]] = None

        # gns3 connector (try to init automatically)
        self.gns3: Optional[GNS3Connector] = None
        self.last_gns3_project = None
        self._icon_photo = None  # Keep reference to prevent garbage collection

        # Track whether any background operation is in progress (used by close guard)
        self._send_in_progress = False

        self._build_ui()

        # Warn if the database could not be opened
        if _db_error:
            self.after(200, lambda: messagebox.showwarning(
                "Database Error",
                f"Could not open the database:\n{_db_error}\n\n"
                "The app will run in read-only mode. Saving and logging will not work.",
                parent=self
            ))

        # Handle window close: warn when a send is in progress
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # try auto-connect to gns3 in background
        threading.Thread(target=self._auto_connect_gns3, daemon=True).start()

    def _build_ui(self):
        # Apply dark theme to all ttk.Treeview widgets globally — must run
        # once before any Treeview is instantiated so the style is inherited.
        _style = ttk.Style(self)
        try:
            _style.theme_use("default")
        except Exception:
            pass
        _style.configure(
            "Treeview",
            background="#161B22",
            foreground="#C9D1D9",
            fieldbackground="#161B22",
            rowheight=26,
            borderwidth=0,
            font=("TkDefaultFont", 10),
        )
        _style.map(
            "Treeview",
            background=[("selected", "#264F78")],
            foreground=[("selected", "#FFFFFF")],
        )
        _style.configure(
            "Treeview.Heading",
            background="#1F2630",
            foreground="#8B949E",
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
        )
        _style.map("Treeview.Heading", background=[("active", "#28313E")])

        # Configure main window background - Figma exact colors
        self.configure(fg_color="#0D1117")
        
        top = ctk.CTkFrame(self, height=70, fg_color="#0D1117")
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
                except Exception:
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
            ctk.CTkLabel(logo_frame, text="ANCS", font=ctk.CTkFont(family="Inter", size=20, weight="bold"), text_color="#58A6FF").pack(side="left", padx=4)
            ctk.CTkLabel(logo_frame, text="Auto Network\nConfiguration System", font=ctk.CTkFont(family="Inter", size=9), text_color="#9BA3AF", justify="left").pack(side="left", padx=2)
        
        # Navigation tabs in CENTER of header - like Figma photo 1
        nav_frame = ctk.CTkFrame(top, fg_color="transparent")
        nav_frame.pack(side="left", fill="x", expand=True)
        
        # Center the nav buttons using inner frame
        nav_inner = ctk.CTkFrame(nav_frame, fg_color="transparent")
        nav_inner.pack(expand=True)
        
        # Main tab with icon and underline - Figma Inter font
        self.main_tab_frame = ctk.CTkFrame(nav_inner, fg_color="transparent")
        self.main_tab_frame.pack(side="left", padx=12)
        self.btn_main_nav = ctk.CTkButton(self.main_tab_frame, text="🏠 Main", command=lambda: self._switch_tab("main"),
                                         fg_color="transparent", hover_color="#1F2630", width=90, height=32,
                                         font=ctk.CTkFont(family="Inter", size=16, weight="bold"), text_color="#C9D1D9")
        self.btn_main_nav.pack()
        self.main_underline = ctk.CTkFrame(self.main_tab_frame, height=3, fg_color="#58A6FF")
        self.main_underline.pack(fill="x", pady=(4,0))
        
        # Logs tab with icon and underline - Figma Inter font
        self.logs_tab_frame = ctk.CTkFrame(nav_inner, fg_color="transparent")
        self.logs_tab_frame.pack(side="left", padx=12)
        self.btn_logs_nav = ctk.CTkButton(self.logs_tab_frame, text="☰ Logs", command=lambda: self._switch_tab("logs"),
                                          fg_color="transparent", hover_color="#1F2630", width=90, height=32,
                                          font=ctk.CTkFont(family="Inter", size=16), text_color="#9BA3AF")
        self.btn_logs_nav.pack()
        self.logs_underline = ctk.CTkFrame(self.logs_tab_frame, height=3, fg_color="transparent")
        self.logs_underline.pack(fill="x", pady=(4,0))
        
        # Toggle button for right sidebar (appears when sidebar is hidden)
        self.btn_toggle_sidebar = ctk.CTkButton(nav_inner, text="☰ Panel", command=self._toggle_right_sidebar,
                                                fg_color="transparent", hover_color="#1F2630", width=80, height=32,
                                                font=ctk.CTkFont(family="Inter", size=14), text_color="#58A6FF",
                                                border_width=1, border_color="#58A6FF", corner_radius=6)
        # Initially hidden - will show when window is small
        
        # Create tabview for main and logs pages (our custom nav buttons at top are used instead)
        self.nb = ctk.CTkTabview(self, fg_color="#0D1117", 
                                segmented_button_fg_color="#0D1117",
                                segmented_button_selected_color="#0D1117",
                                segmented_button_unselected_color="#0D1117",
                                text_color="#0D1117")
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.nb.add("main")
        self.nb.add("logs")
        # Completely remove the built-in tab buttons - we use our own navigation
        self.nb._segmented_button.pack_forget()
        self.nb._segmented_button.configure(height=0, corner_radius=0)
        self.nb._segmented_button.grid_remove()
        self.tab_main = self.nb.tab("main")
        self.tab_logs = self.nb.tab("logs")
    
        # LEFT SIDEBAR - Figma panel with rounded corners (wider for long text)
        left_container = ctk.CTkFrame(self.tab_main, width=320, fg_color="#1F2630", corner_radius=8, border_width=0)
        left_container.pack(side="left", fill="y", padx=(16,0), pady=16)
        left_container.pack_propagate(False)
        left_scroll = ctk.CTkScrollableFrame(left_container, width=300, fg_color="transparent")
        left_scroll.pack(fill="both", expand=True, padx=0, pady=0)
        left = left_scroll
        
        # DEVICES SECTION - Figma Title/medium font
        ctk.CTkLabel(left, text="Devices", font=ctk.CTkFont(family="Inter", size=18, weight="bold"), text_color="#F0F2F4").pack(anchor="nw", padx=16, pady=(24,16))
        
        # Scrollable frame for device items - Figma inner background
        self.devices_list_frame = ctk.CTkFrame(left, fg_color="#28313E", corner_radius=8, border_width=0)
        self.devices_list_frame.pack(fill="x", padx=16, pady=(0,8))
        self.devices_scroll = ctk.CTkScrollableFrame(self.devices_list_frame, fg_color="transparent", height=160)
        self.devices_scroll.pack(fill="x", padx=8, pady=8)
        
        # Store device item widgets and selection state
        self.device_items = {}
        self.selected_device_name = None

        # Device buttons — Tier 3 (flat/muted utility)
        dbbtns = ctk.CTkFrame(left, fg_color="transparent")
        dbbtns.pack(fill="x", padx=16, pady=(8,24))
        ctk.CTkButton(dbbtns, text="+ Add", command=self.add_device_prompt,
                     fg_color="#374151", hover_color="#4b5563", text_color="#9ca3af",
                     font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=32,
                     border_width=0).pack(side="left", expand=True, padx=(0,8))
        ctk.CTkButton(dbbtns, text="Remove", command=self.remove_selected_device,
                     fg_color="#374151", hover_color="#4b5563", text_color="#9ca3af",
                     font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=32,
                     border_width=0).pack(side="left", expand=True, padx=(0,0))

        # TEMPLATES SECTION - Figma Title/medium font
        ctk.CTkLabel(left, text="Templates", font=ctk.CTkFont(family="Inter", size=18, weight="bold"), text_color="#F0F2F4").pack(anchor="nw", padx=16, pady=(0,16))
        
        # Scrollable frame for template items - Figma inner background
        self.templates_list_frame = ctk.CTkFrame(left, fg_color="#28313E", corner_radius=8, border_width=0)
        self.templates_list_frame.pack(fill="both", expand=True, padx=16, pady=(0,8))
        self.templates_scroll = ctk.CTkScrollableFrame(self.templates_list_frame, fg_color="transparent")
        self.templates_scroll.pack(fill="both", expand=True, padx=8, pady=8)
        
        # Store template item widgets and selection state
        self.template_items = {}
        self.selected_template_name = None

        # Template buttons — Tier 3 (flat/muted utility)
        tbtns = ctk.CTkFrame(left, fg_color="transparent")
        tbtns.pack(fill="x", padx=16, pady=(8,16))
        ctk.CTkButton(tbtns, text="+ Add", command=self.add_template_dialog,
                     fg_color="#374151", hover_color="#4b5563", text_color="#9ca3af",
                     font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=32,
                     border_width=0).pack(side="left", expand=True, padx=(0,8))
        ctk.CTkButton(tbtns, text="Edit", command=self.edit_template_dialog,
                     fg_color="#374151", hover_color="#4b5563", text_color="#9ca3af",
                     font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=32,
                     border_width=0).pack(side="left", expand=True, padx=(0,0))
        
        # Left sidebar — ordered by importance (most important first)
        # 1. Guided Setup — Tier 1 teal (start here)
        ctk.CTkButton(left, text="🧙 Guided Setup", command=self.guided_setup,
                     fg_color="#0d9488", hover_color="#0f766e", text_color="white",
                     font=ctk.CTkFont(family="Inter", size=14, weight="bold"), corner_radius=8, height=36,
                     border_width=0).pack(fill="x", padx=16, pady=(8,4))

        # 2. Deploy All — Tier 1 solid blue
        ctk.CTkButton(left, text="🚀 Deploy All (Ordered)", command=self.deploy_all_ordered,
                     fg_color="#58A6FF", hover_color="#4A90E8", text_color="white",
                     font=ctk.CTkFont(family="Inter", size=14, weight="bold"), corner_radius=8, height=36,
                     border_width=0).pack(fill="x", padx=16, pady=(0,4))

        # 3. Monitor Devices — Tier 2 outlined blue
        ctk.CTkButton(left, text="📊 Monitor Devices", command=self.open_monitor,
                     fg_color="transparent", hover_color="#28313E", text_color="#58A6FF",
                     font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=36,
                     border_width=1, border_color="#58A6FF").pack(fill="x", padx=16, pady=(0,8))

        # 4. Topology — Tier 3 flat/muted
        ctk.CTkButton(left, text="🗺 Topology", command=self.open_topology,
                     fg_color="#374151", hover_color="#4b5563", text_color="#9ca3af",
                     font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=36,
                     border_width=0).pack(fill="x", padx=16, pady=(0,4))

        # 5. Subnet Calculator — Tier 3 flat/muted
        ctk.CTkButton(left, text="🔢 Subnet Calculator", command=lambda: SubnetCalculator(self),
                     fg_color="#374151", hover_color="#4b5563", text_color="#9ca3af",
                     font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=36,
                     border_width=0).pack(fill="x", padx=16, pady=(0,4))

        # 6. Send History — Tier 3 flat/muted
        ctk.CTkButton(left, text="📋 Send History", command=self.open_audit_log,
                     fg_color="#374151", hover_color="#4b5563", text_color="#9ca3af",
                     font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=36,
                     border_width=0).pack(fill="x", padx=16, pady=(0,24))

        # 7. Rollback — Tier 3 (shown only when device has snapshots)
        self.btn_rollback = ctk.CTkButton(
            left, text="↩ Rollback Config", command=self.rollback_device,
            fg_color="#3d2020", hover_color="#4f2929", text_color="#f87171",
            font=ctk.CTkFont(family="Inter", size=13), corner_radius=8, height=36,
            border_width=0,
        )
        self.btn_rollback.pack(fill="x", padx=16, pady=(0,24))
        self.btn_rollback.pack_forget()  # hidden until a device with snapshots is selected

        # CENTER AREA - Preview card floating in the middle
        self.center_frame = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        self.center_frame.pack(side="left", fill="both", expand=True, padx=16, pady=16)
        center = self.center_frame

        # Preview header with title and Figma styled buttons
        topc = ctk.CTkFrame(center, fg_color="transparent")
        topc.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(topc, text="Preview", font=ctk.CTkFont(family="Inter", size=24, weight="bold"), text_color="#C9D1D9").pack(side="left")
        gframe = ctk.CTkFrame(topc, fg_color="transparent")
        gframe.pack(side="right")
        # Export/Import — Tier 2 outlined blue (lighter)
        ctk.CTkButton(gframe, text="📤 Export Project",
                     fg_color="transparent", hover_color="#28313E", text_color="#58A6FF",
                     command=self.export_project, width=140, height=40,
                     font=ctk.CTkFont(family="Inter", size=16), corner_radius=8,
                     border_width=1, border_color="#58A6FF").pack(side="left", padx=(0, 16))
        ctk.CTkButton(gframe, text="📥 Import Project",
                     fg_color="transparent", hover_color="#28313E", text_color="#58A6FF",
                     command=self.import_project, width=140, height=40,
                     font=ctk.CTkFont(family="Inter", size=16), corner_radius=8,
                     border_width=1, border_color="#58A6FF").pack(side="left")

        # Preview holder - Figma card with rounded corners
        preview_holder = ctk.CTkFrame(center, fg_color="#1F2630", corner_radius=8, border_width=0)
        preview_holder.pack(fill="both", expand=True)
        
        # Inner preview text area - Figma dark code background
        self.preview = ctk.CTkTextbox(preview_holder, wrap="none", 
                                     font=ctk.CTkFont(family="Consolas", size=14),
                                     fg_color="#161B22", text_color="#FFFFFF",
                                     corner_radius=8, border_width=0)
        self.preview.pack(fill="both", expand=True, padx=16, pady=(24, 16))
        
        # Bottom buttons frame
        bottom_btn_frame = ctk.CTkFrame(preview_holder, fg_color="transparent")
        bottom_btn_frame.pack(fill="x", padx=16, pady=(0, 24))
        
        # Generate button — Tier 1 solid blue (lighter)
        ctk.CTkButton(
            bottom_btn_frame,
            text="Generate",
            command=self.generate_full,
            fg_color="#58A6FF",
            hover_color="#4A90E8",
            text_color="white",
            width=120,
            height=48,
            font=ctk.CTkFont(family="Inter", size=18, weight="bold"),
            corner_radius=8,
            border_width=0
        ).pack(side="left")
        
        # Clear Preview button - Figma outlined red
        ctk.CTkButton(
            bottom_btn_frame, 
            text="Clear Preview", 
            command=self.clear_preview,
            fg_color="transparent",
            hover_color="#28313E",
            text_color="#EF4444",
            width=140,
            height=48,
            font=ctk.CTkFont(family="Inter", size=18, weight="bold"),
            corner_radius=8,
            border_width=1,
            border_color="#EF4444"
        ).pack(side="right")
        
        # Enable paste in preview window
        def paste_handler(event=None):
            try:
                clipboard_text = self.clipboard_get()
                self.preview.insert("insert", clipboard_text)
                return "break"
            except Exception:
                pass
        
        self.preview.bind("<Control-v>", paste_handler)
        self.preview.bind("<Command-v>", paste_handler)  # macOS

        # RIGHT SIDEBAR - Figma panel with rounded corners (responsive - can be hidden)
        self.right_sidebar = ctk.CTkFrame(self.tab_main, width=278, fg_color="#1F2630", corner_radius=8, border_width=0)
        self.right_sidebar.pack(side="right", fill="y", padx=(0,16), pady=16)
        self.right_sidebar.pack_propagate(False)
        self.right_sidebar_visible = True
        # Scrollable inner container so all fields remain accessible on small screens
        right = ctk.CTkScrollableFrame(self.right_sidebar, fg_color="transparent")
        right.pack(fill="both", expand=True)
        
        # GNS3 PROJECT SECTION
        ctk.CTkLabel(right, text="GNS3 Project", font=ctk.CTkFont(family="Inter", size=18, weight="bold"),
                    text_color="#FFFFFF").pack(anchor="nw", padx=16, pady=(24, 8))

        # Single row: project name on the left, status badge on the right
        config_row = ctk.CTkFrame(right, fg_color="transparent")
        config_row.pack(fill="x", padx=16, pady=(0, 16))

        self.lbl_gns3_project_name = ctk.CTkLabel(
            config_row,
            text="No project",
            font=ctk.CTkFont(family="Inter", size=13),
            text_color="#8B949E",
            anchor="w",
        )
        self.lbl_gns3_project_name.pack(side="left", fill="x", expand=True)

        self.lbl_gns3_status = ctk.CTkLabel(
            config_row, text="⏳ Connecting…",
            font=ctk.CTkFont(family="Inter", size=12),
            text_color="#9BA3AF",
            fg_color="#28313E",
            corner_radius=6,
            padx=10, pady=4,
        )
        self.lbl_gns3_status.pack(side="right")
        
        # GNS3 Import — Tier 1 solid blue (lighter); Refresh — Tier 3 flat/muted
        gns3_controls = ctk.CTkFrame(right, fg_color="transparent")
        gns3_controls.pack(fill="x", padx=16, pady=(0, 24))
        ctk.CTkButton(gns3_controls, text="Import", command=self.gns3_list_projects,
                     fg_color="#58A6FF", hover_color="#4A90E8", text_color="white",
                     width=100, height=32, font=ctk.CTkFont(family="Inter", size=14, weight="bold"), corner_radius=8,
                     border_width=0).pack(side="left", padx=(0, 16))
        ctk.CTkButton(gns3_controls, text="Refresh", command=self.refresh_gns3_connection,
                     fg_color="#374151", hover_color="#4b5563", text_color="#9ca3af",
                     width=100, height=32, font=ctk.CTkFont(family="Inter", size=14), corner_radius=8,
                     border_width=0).pack(side="left")
        
        # SEND / CONNECT SECTION - Figma Title/medium
        ctk.CTkLabel(right, text="Send / Connect", font=ctk.CTkFont(family="Inter", size=18, weight="bold"), 
                    text_color="#F0F2F4").pack(anchor="nw", padx=16, pady=(0,16))
        
        # Protocol dropdown - Figma styled
        self.send_method = ctk.CTkOptionMenu(right, values=["Telnet", "Serial", "SSH"],
                                            fg_color="#2B323F", button_color="#28313E",
                                            button_hover_color="#3C4A5D", text_color="#FFFFFF",
                                            font=ctk.CTkFont(family="Inter", size=14), corner_radius=8, height=40,
                                            dropdown_fg_color="#28313E", dropdown_hover_color="#3C4A5D",
                                            dropdown_text_color="#FFFFFF") 
        self.send_method.set("Telnet")
        self.send_method.pack(fill="x", padx=16, pady=(0,16))
        self.send_method.configure(command=self._on_protocol_changed)

        # Serial fields section - Figma Title/base
        self.lbl_serial_title = ctk.CTkLabel(right, text="Serial", font=ctk.CTkFont(family="Inter", size=16, weight="bold"), 
                                            text_color="#C9D1D9")
        self.lbl_serial_title.pack(anchor="w", padx=16, pady=(0,16))
        
        self.ent_serial_port = ctk.CTkEntry(right, placeholder_text="COM3 or /dev/ttyUSB0",
                                           font=ctk.CTkFont(family="Inter", size=14), height=44,
                                           fg_color="#60656F", border_color="#777D81", border_width=1,
                                           corner_radius=8, text_color="#FFFFFF", placeholder_text_color="#9BA3AF")
        self.ent_serial_port.pack(fill="x", padx=16, pady=(0,8))
        
        self.ent_serial_baud = ctk.CTkEntry(right, placeholder_text="9600",
                                           font=ctk.CTkFont(family="Inter", size=14), height=44,
                                           fg_color="#60656F", border_color="#777D81", border_width=1,
                                           corner_radius=8, text_color="#FFFFFF", placeholder_text_color="#9BA3AF")
        self.ent_serial_baud.pack(fill="x", padx=16, pady=(0,16))

        # Network fields section - Figma Title/base
        self.lbl_network_title = ctk.CTkLabel(right, text="Network", font=ctk.CTkFont(family="Inter", size=16, weight="bold"), 
                                             text_color="#C9D1D9")
        self.lbl_network_title.pack(anchor="w", padx=16, pady=(0,16))
        
        self.ent_host = ctk.CTkEntry(right, placeholder_text="Host or Ip",
                                    font=ctk.CTkFont(family="Inter", size=14), height=44,
                                    fg_color="#2B323F", border_color="#6B7280", border_width=1,
                                    corner_radius=8, text_color="#FFFFFF", placeholder_text_color="#9BA3AF")
        self.ent_host.pack(fill="x", padx=16, pady=(0,8))
        
        self.ent_port = ctk.CTkEntry(right, placeholder_text="Port",
                                     font=ctk.CTkFont(family="Inter", size=14), height=44,
                                     fg_color="#2B323F", border_color="#6B7280", border_width=1,
                                     corner_radius=8, text_color="#FFFFFF", placeholder_text_color="#9BA3AF")
        self.ent_port.pack(fill="x", padx=16, pady=(0,8))
        self.ent_user = ctk.CTkEntry(right, placeholder_text="Username",
                                    font=ctk.CTkFont(family="Inter", size=14), height=44,
                                    fg_color="#2B323F", border_color="#6B7280", border_width=1,
                                    corner_radius=8, text_color="#FFFFFF", placeholder_text_color="#9BA3AF")
        self.ent_user.pack(fill="x", padx=16, pady=(0,8))
        
        self.ent_pass = ctk.CTkEntry(right, placeholder_text="Password", show="*",
                                    font=ctk.CTkFont(family="Inter", size=14), height=44,
                                    fg_color="#2B323F", border_color="#6B7280", border_width=1,
                                    corner_radius=8, text_color="#FFFFFF", placeholder_text_color="#9BA3AF")
        self.ent_pass.pack(fill="x", padx=16, pady=(0,8))
        
        # Optional enable password - Figma styled with optional label
        enable_label = ctk.CTkLabel(right, text="Optional", font=ctk.CTkFont(family="Inter", size=12),
                                   text_color="#9BA3AF")
        enable_label.pack(anchor="w", padx=16, pady=(8,8))
        enable_frame = ctk.CTkFrame(right, fg_color="transparent")
        enable_frame.pack(fill="x", padx=16, pady=(0,8))
        self.enable_checkbox = ctk.CTkCheckBox(enable_frame, text="",
                                              font=ctk.CTkFont(size=11), width=24,
                                              fg_color="#58A6FF", hover_color="#4A90E8",
                                              border_color="#6B7280", corner_radius=4)
        self.enable_checkbox.pack(side="right", padx=(8,0))
        self.ent_enable = ctk.CTkEntry(enable_frame, placeholder_text="Enable Password",
                                      font=ctk.CTkFont(family="Inter", size=14), height=44,
                                      fg_color="#2B323F", border_color="#6B7280", border_width=1,
                                      corner_radius=8, text_color="#FFFFFF", placeholder_text_color="#9BA3AF")
        self.ent_enable.pack(side="left", fill="x", expand=True)

        # Send — Tier 1 solid blue (primary action, lighter)
        self.btn_send = ctk.CTkButton(right, text="Send", command=self.send_now,
                     fg_color="#58A6FF", hover_color="#4A90E8", text_color="white",
                     height=40, font=ctk.CTkFont(family="Inter", size=16, weight="bold"),
                     corner_radius=8, border_width=0)
        self.btn_send.pack(fill="x", padx=16, pady=(24,8))

        # Save Credentials — Tier 2 outlined blue (lighter)
        ctk.CTkButton(right, text="💾 Save Credentials", command=self.save_credentials,
                     fg_color="transparent", hover_color="#28313E", text_color="#58A6FF",
                     height=36, font=ctk.CTkFont(family="Inter", size=13), corner_radius=8,
                     border_width=1, border_color="#58A6FF").pack(fill="x", padx=16, pady=(0,8))

        # Open Terminal — Tier 2 outlined blue (lighter)
        ctk.CTkButton(right, text="💻 Open Terminal", command=self.open_terminal,
                     fg_color="transparent", hover_color="#28313E", text_color="#58A6FF",
                     height=36, font=ctk.CTkFont(family="Inter", size=13), corner_radius=8,
                     border_width=1, border_color="#58A6FF").pack(fill="x", padx=16, pady=(0,24))

        # Store references for conditional enabling
        self.serial_widgets = [self.lbl_serial_title, self.ent_serial_port, self.ent_serial_baud]
        self.network_widgets = [self.lbl_network_title, self.ent_host, self.ent_port, self.ent_user, self.ent_pass, self.ent_enable, self.enable_checkbox]
        
        # Initialize field states based on default protocol
        self._on_protocol_changed("Telnet")

        # LOGS TAB - device-filtered history + runtime output
        logs_card = ctk.CTkFrame(self.tab_logs, fg_color="#1F2630", corner_radius=8, border_width=0)
        logs_card.pack(fill="both", expand=True, padx=16, pady=16)

        # Top: device filter dropdown + refresh
        logs_top = ctk.CTkFrame(logs_card, fg_color="transparent")
        logs_top.pack(fill="x", padx=24, pady=(24,12))
        ctk.CTkLabel(logs_top, text="Logs", font=ctk.CTkFont(family="Inter", size=24, weight="bold"),
                    text_color="#C9D1D9").pack(side="left")
        self.logs_device_var = ctk.StringVar(value="All")
        self.logs_device_dropdown = ctk.CTkOptionMenu(
            logs_top, variable=self.logs_device_var, values=["All"],
            fg_color="#2B323F", button_color="#28313E", button_hover_color="#3C4A5D",
            text_color="#FFFFFF", font=ctk.CTkFont(family="Inter", size=14),
            corner_radius=8, height=36, width=200,
            command=lambda _: self._refresh_logs_history()
        )
        self.logs_device_dropdown.pack(side="left", padx=(24,8))
        ctk.CTkButton(logs_top, text="Refresh", command=self._refresh_logs_history,
                     fg_color="transparent", hover_color="#28313E", text_color="#58A6FF",
                     width=90, height=36, font=ctk.CTkFont(family="Inter", size=14),
                     corner_radius=8, border_width=1, border_color="#58A6FF").pack(side="left")

        # Log history table (from DB)
        logs_history_frame = ctk.CTkFrame(logs_card, fg_color="transparent")
        logs_history_frame.pack(fill="x", padx=24, pady=(0,8))
        ctk.CTkLabel(logs_history_frame, text="History (by device)", font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
                    text_color="#9ca3af").pack(anchor="w")
        self.logs_history_tree = None
        try:
            self._logs_history_container = ctk.CTkFrame(logs_history_frame, fg_color="#161B22", corner_radius=8)
            self._logs_history_container.pack(fill="x", pady=(4,0))
            self.logs_history_tree = ttk.Treeview(
                self._logs_history_container, columns=("id", "device", "action", "time"), show="headings",
                height=6
            )
            for h, w in [("id", 50), ("device", 140), ("action", 180), ("time", 150)]:
                self.logs_history_tree.heading(h, text=h)
                self.logs_history_tree.column(h, width=w, anchor="w")
            sb = ttk.Scrollbar(self._logs_history_container, orient="vertical", command=self.logs_history_tree.yview)
            self.logs_history_tree.configure(yscrollcommand=sb.set)
            self.logs_history_tree.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
        except Exception:
            pass

        # Runtime output section
        ctk.CTkLabel(logs_card, text="Live output", font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
                    text_color="#9ca3af").pack(anchor="nw", padx=24, pady=(16,8))
        self.txt_logs = ctk.CTkTextbox(logs_card, font=ctk.CTkFont(family="Consolas", size=14),
                                      fg_color="#161B22", text_color="#FFFFFF",
                                      corner_radius=8, border_width=0,
                                      state="disabled")
        self.txt_logs.pack(fill="both", expand=True, padx=24, pady=(0,16))
        clear_logs_frame = ctk.CTkFrame(logs_card, fg_color="transparent")
        clear_logs_frame.pack(fill="x", padx=24, pady=(0,24))
        def _clear_txt_logs():
            self.txt_logs.configure(state="normal")
            self.txt_logs.delete("0.0", "end")
            self.txt_logs.configure(state="disabled")

        clear_logs_btn = ctk.CTkButton(clear_logs_frame, text="Clear output",
                                      command=_clear_txt_logs,
                                      fg_color="transparent", hover_color="#28313E",
                                      text_color="#58A6FF", width=120, height=32,
                                      font=ctk.CTkFont(family="Inter", size=14), corner_radius=8,
                                      border_width=1, border_color="#58A6FF")
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
        except Exception:
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
            except Exception:
                messagebox.showerror("error", "invalid port count"); return
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
    
    # ──────────────────────────────────────────────────────────────────────────
    # Cross-device context extraction
    # ──────────────────────────────────────────────────────────────────────────
    def _build_project_context(self, exclude_name: str) -> dict:
        """
        Scan all guided_* templates from every device except `exclude_name`.
        Returns a rich context dict used by GuidedSetupWizard to pre-fill steps.
        """
        import re

        ctx = {
            "vlans":            [],
            "routing_entries":  [],
            "dhcp_pools":       [],
            "acl_rules":        [],
            "static_routes":    [],
            "isp_gateway":      "",
            "rip_enabled":      False,
            "domain":           "",
            "enable_pw":        "",
            "ip_scheme":        "192.168",
            "vlan_source":      "",
            "routing_source":   "",
            "dhcp_source_device": "",
            # Routing ownership — used to enforce mutual exclusion in the wizard
            "routing_device":       "",   # name of the device that already handles routing
            "routing_device_type":  "",   # "router" | "core"
        }

        for dname, model, _meta in self.devices:
            if dname == exclude_name:
                continue
            tmpls = model.templates

            # ── VLANs ──
            if not ctx["vlans"] and "guided_vlans" in tmpls:
                text = tmpls["guided_vlans"]
                for m in re.finditer(r"vlan\s+(\d+)\s*\nname\s+(\S+)", text, re.IGNORECASE):
                    ctx["vlans"].append({"id": m.group(1), "name": m.group(2)})
                if ctx["vlans"]:
                    ctx["vlan_source"] = dname

            # ── Routing / SVIs ──
            if not ctx["routing_entries"] and "guided_routing" in tmpls:
                text = tmpls["guided_routing"]
                # match: ip address 192.168.10.1 255.255.255.0  (under interface Vlan10 or .10)
                for m in re.finditer(
                    r"(?:interface\s+\S*?(\d+)[.\s].*?\n.*?)?ip\s+address\s+([\d.]+)\s+([\d.]+)",
                    text, re.IGNORECASE | re.DOTALL,
                ):
                    ip   = m.group(2)
                    mask = m.group(3)
                    if ip and mask:
                        # derive VLAN ID from IP third octet
                        parts = ip.split(".")
                        vid   = parts[2] if len(parts) == 4 else ""
                        ctx["routing_entries"].append({
                            "vlan": vid, "name": f"VLAN{vid}", "ip": ip, "mask": mask
                        })
                        # derive ip_scheme
                        if len(parts) >= 2:
                            ctx["ip_scheme"] = f"{parts[0]}.{parts[1]}"
                if ctx["routing_entries"]:
                    ctx["routing_source"] = dname
                    # Also extract VLAN names from guided_vlans of the same device
                    if "guided_vlans" in tmpls:
                        vtext = tmpls["guided_vlans"]
                        vlan_names: dict = {}
                        for m in re.finditer(r"vlan\s+(\d+)\s*\nname\s+(\S+)", vtext, re.IGNORECASE):
                            vlan_names[m.group(1)] = m.group(2)
                        for entry in ctx["routing_entries"]:
                            if entry["vlan"] in vlan_names:
                                entry["name"] = vlan_names[entry["vlan"]]

            # ── Routing ownership (mutual exclusion) ──
            # Track which device type already claims inter-VLAN routing so the
            # wizard can prevent a second device from also claiming it.
            if not ctx["routing_device"] and "guided_routing" in tmpls and tmpls["guided_routing"].strip():
                if isinstance(model, RouterModel):
                    ctx["routing_device"]      = dname
                    ctx["routing_device_type"] = "router"
                elif isinstance(model, CoreSwitchModel):
                    ctx["routing_device"]      = dname
                    ctx["routing_device_type"] = "core"

            # ── DHCP ──
            if not ctx["dhcp_pools"] and "guided_dhcp" in tmpls:
                text = tmpls["guided_dhcp"]
                pools = []
                for pool_block in re.split(r"ip dhcp pool\s+", text, flags=re.IGNORECASE):
                    if not pool_block.strip():
                        continue
                    pname = pool_block.split()[0] if pool_block.split() else ""
                    net_m = re.search(r"network\s+([\d.]+)\s+([\d.]+)", pool_block, re.IGNORECASE)
                    gw_m  = re.search(r"default-router\s+([\d.]+)", pool_block, re.IGNORECASE)
                    dns_m = re.search(r"dns-server\s+([\d.]+)", pool_block, re.IGNORECASE)
                    if net_m:
                        pools.append({
                            "pool":    pname,
                            "network": net_m.group(1),
                            "mask":    net_m.group(2),
                            "gateway": gw_m.group(1) if gw_m else "",
                            "dns":     dns_m.group(1) if dns_m else "8.8.8.8",
                        })
                if pools:
                    ctx["dhcp_pools"] = pools
                    ctx["dhcp_source_device"] = dname

            # ── Static routes / ISP gateway ──
            if not ctx["isp_gateway"] and "guided_static_routes" in tmpls:
                text = tmpls["guided_static_routes"]
                m = re.search(r"ip\s+route\s+0\.0\.0\.0\s+0\.0\.0\.0\s+([\d.]+)", text, re.IGNORECASE)
                if m:
                    ctx["isp_gateway"] = m.group(1)
                    ctx["static_routes"].append({
                        "network": "0.0.0.0", "mask": "0.0.0.0",
                        "next-hop": m.group(1), "description": "Default route to ISP"
                    })

            # ── RIP ──
            if not ctx["rip_enabled"] and "guided_rip" in tmpls:
                text = tmpls["guided_rip"]
                if re.search(r"router\s+rip", text, re.IGNORECASE):
                    ctx["rip_enabled"] = True

            # ── Identity hints (domain, enable password) ──
            if "guided_identity" in tmpls:
                text = tmpls["guided_identity"]
                if not ctx["domain"]:
                    dm = re.search(r"ip\s+domain[-\s]name\s+(\S+)", text, re.IGNORECASE)
                    if dm:
                        ctx["domain"] = dm.group(1)
                if not ctx["enable_pw"]:
                    em = re.search(r"enable\s+secret\s+(\S+)", text, re.IGNORECASE)
                    if em:
                        ctx["enable_pw"] = em.group(1)

        return ctx

    def open_topology(self):
        """Open the topology visualizer for the active GNS3 project."""
        project_id = getattr(self, "gns3_project_id", None)
        if not project_id:
            messagebox.showinfo(
                "Topology",
                "No GNS3 project loaded.\n\n"
                "Connect to GNS3 and import devices first.",
                parent=self,
            )
            return
        try:
            connector = GNS3Connector()
            TopologyViewer(self, connector, project_id, self.devices)
        except Exception as exc:
            messagebox.showerror("Topology Error", str(exc), parent=self)

    def rollback_device(self):
        """Restore the last wizard snapshot for the selected device."""
        if not self.current_device:
            messagebox.showinfo("Info", "Select a device first.")
            return
        name, model, meta = self.current_device
        if not model.has_snapshots():
            messagebox.showinfo("Info", "No rollback snapshot available for this device.")
            return
        if not messagebox.askyesno(
            "Rollback Config",
            f"Restore the previous configuration for '{name}'?\n\n"
            "This will undo the last Guided Setup run.",
            parent=self,
        ):
            return
        model.restore_snapshot()
        self._refresh_template_list()
        # Hide the button if no more snapshots remain
        if not model.has_snapshots():
            self.btn_rollback.pack_forget()
        messagebox.showinfo(
            "Rollback Complete",
            f"Previous configuration restored for '{name}'.\n"
            "Select a template and press Send to re-deploy.",
            parent=self,
        )

    def guided_setup(self):
        if not self.devices:
            messagebox.showinfo("info", "add a device first")
            return
        choice = self._prompt_guided_device_choice()
        if not choice:
            return
        name, model, meta = choice
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

        # Build cross-device context from already-configured devices
        project_context = self._build_project_context(exclude_name=name)

        win = GuidedSetupWizard(
            self, name, model,
            device_role=device_role,
            known_interfaces=meta.get("interfaces", []),
            project_context=project_context,
        )
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

        # ── Post-wizard: offer to apply to similar unconfigured devices ──
        self._offer_apply_to_similar(name, model, device_role, win)

    def _offer_apply_to_similar(self, configured_name: str, configured_model, device_role: str, win):
        """
        After the wizard closes, if other unconfigured devices of the same role
        exist, offer a one-click apply of consistent configs (VLANs+uplinks for
        switches; VLANs for core; identity hints for routers).
        """
        # Find unconfigured devices of a compatible type
        if device_role == "access":
            targets = [
                (n, m, mt) for n, m, mt in self.devices
                if isinstance(m, SwitchModel) and n != configured_name
                and not any(k.startswith("guided_") for k in m.templates)
            ]
            apply_what = "VLANs + trunk uplink"
        elif device_role == "core":
            targets = [
                (n, m, mt) for n, m, mt in self.devices
                if isinstance(m, (SwitchModel, CoreSwitchModel)) and n != configured_name
                and not any(k.startswith("guided_") for k in m.templates)
            ]
            apply_what = "VLANs"
        elif device_role == "router":
            targets = [
                (n, m, mt) for n, m, mt in self.devices
                if isinstance(m, RouterModel) and n != configured_name
                and not any(k.startswith("guided_") for k in m.templates)
            ]
            apply_what = "domain name and admin password"
        else:
            return

        if not targets:
            return

        names_str = ", ".join(n for n, _, _ in targets[:5])
        if len(targets) > 5:
            names_str += f" and {len(targets) - 5} more"

        answer = messagebox.askyesno(
            "Apply to similar devices",
            f"{len(targets)} other unconfigured device(s) found:\n  {names_str}\n\n"
            f"Apply the same {apply_what} to them now?",
            parent=self,
        )
        if not answer:
            return

        # Use headless wizard instances to write consistent templates
        for tname, tmodel, tmeta in targets:
            role = (
                "router" if isinstance(tmodel, RouterModel)
                else "core" if isinstance(tmodel, CoreSwitchModel)
                else "access"
            )
            headless = GuidedSetupWizard(
                self, tname, tmodel,
                device_role=role,
                known_interfaces=tmeta.get("interfaces", []),
                headless=True,
            )
            headless.vlans           = list(win.vlans)
            headless.identity_data   = {
                "hostname": tname,
                "domain":   win.identity_data.get("domain", ""),
                "enable":   win.identity_data.get("enable", "ChangeMe123!"),
            }
            if device_role in ("access", "core"):
                # Assign uplinks using this device's last known interface or default
                ifaces = tmeta.get("interfaces", [])
                uplink_port = ifaces[-1] if ifaces else ("Ethernet3/3" if role == "access" else "FastEthernet1/0")
                headless.uplinks = [{"ports": uplink_port, "mode": "trunk",
                                     "allowed vlans": ",".join(v["id"] for v in win.vlans) or "all"}]
            headless._write_templates()
            headless.destroy()

        messagebox.showinfo(
            "Done",
            f"Config applied to {len(targets)} device(s):\n  {names_str}",
            parent=self,
        )
        self.on_device_select()

    def _prompt_guided_device_choice(self):
        BG      = "#0D1117"
        SIDEBAR = "#161B22"
        CARD    = "#1F2630"
        TEXT    = "#C9D1D9"
        MUTED   = "#8B949E"
        ACCENT  = "#58A6FF"
        BORDER  = "#30363D"

        dialog = tk.Toplevel(self)
        dialog.title("Guided Setup — Select Device")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=BG)
        apply_responsive_geometry(dialog, 480, 420)

        tk.Label(dialog, text="Which device do you want to configure?",
                 font=("TkDefaultFont", 13, "bold"), fg=TEXT, bg=BG).pack(
            anchor="w", padx=18, pady=(18, 4))
        tk.Label(dialog,
                 text="Recommended: start with the router or core switch (handles routing, DHCP and ACLs).\n"
                      "Access switches can be configured afterwards.",
                 wraplength=440, justify="left", fg=MUTED, bg=BG,
                 font=("TkDefaultFont", 9)).pack(anchor="w", padx=18, pady=(0, 10))

        # Device cards (one per device)
        canvas_outer = tk.Frame(dialog, bg=BG)
        canvas_outer.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        listbox = tk.Listbox(
            canvas_outer,
            activestyle="none",
            bg=CARD, fg=TEXT,
            selectbackground=ACCENT, selectforeground="#fff",
            borderwidth=0, highlightthickness=1,
            highlightbackground=BORDER,
            font=("TkDefaultFont", 10),
        )
        listbox.pack(fill="both", expand=True)

        role_icons = {
            "router":  "🔀",
            "core":    "🔶",
            "access":  "🔷",
        }
        for name, model, meta in self.devices:
            if isinstance(model, RouterModel):
                role = "Router / Gateway  (Routing + DHCP + ACL)"
                icon = "🔀"
            elif isinstance(model, CoreSwitchModel):
                role = "Core Switch  (Layer 3 routing)"
                icon = "🔶"
            else:
                role = "Access Switch  (Layer 2 only)"
                icon = "🔷"
            listbox.insert("end", f"  {icon}  {name}  —  {role}")

        if listbox.size() > 0:
            listbox.select_set(0)

        choice = {"value": None}

        def confirm(_e=None):
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("Select device", "Please click a device first.", parent=dialog)
                return
            choice["value"] = self.devices[sel[0]]
            dialog.destroy()

        def cancel():
            choice["value"] = None
            dialog.destroy()

        listbox.bind("<Double-1>", confirm)

        btns = tk.Frame(dialog, bg=BG)
        btns.pack(fill="x", padx=18, pady=(0, 16))
        tk.Button(
            btns, text="Configure Selected  →",
            command=confirm,
            fg="#fff", bg=ACCENT,
            activebackground=ACCENT, activeforeground="#fff",
            font=("TkDefaultFont", 10, "bold"), padx=16, pady=6,
            relief="flat", cursor="hand2",
        ).pack(side="left")
        tk.Button(
            btns, text="Cancel",
            command=cancel,
            fg=MUTED, bg=CARD,
            activebackground=SIDEBAR, activeforeground=TEXT,
            padx=12, pady=6, relief="flat", cursor="hand2",
        ).pack(side="right")

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
        win.title("saved configs"); apply_responsive_geometry(win, 900, 500)
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
        except Exception:
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

    def _refresh_logs_history(self):
        """Refresh the Logs tab device dropdown and history table from DB."""
        if not hasattr(self, "logs_history_tree") or self.logs_history_tree is None:
            return
        if not hasattr(self, "logs_device_dropdown"):
            return
        try:
            # Get distinct devices that have logs
            cur.execute("""
                SELECT DISTINCT COALESCE(d.name, '(no device)') AS dev_name
                FROM logs l
                LEFT JOIN devices d ON l.device_id = d.id
                ORDER BY dev_name
            """)
            devices = ["All"] + [r[0] for r in cur.fetchall() if r[0]]
            devices = list(dict.fromkeys(devices))  # preserve order, remove dupes
            self.logs_device_dropdown.configure(values=devices)
            sel = self.logs_device_var.get()
            if sel not in devices:
                self.logs_device_var.set("All")
                sel = "All"

            # Populate history tree
            for i in self.logs_history_tree.get_children():
                self.logs_history_tree.delete(i)
            if sel == "All":
                cur.execute("""
                    SELECT l.id, COALESCE(d.name,'—'), l.action, l.created_at
                    FROM logs l
                    LEFT JOIN devices d ON l.device_id = d.id
                    ORDER BY l.id DESC
                    LIMIT 500
                """)
            else:
                cur.execute("""
                    SELECT l.id, COALESCE(d.name,'—'), l.action, l.created_at
                    FROM logs l
                    LEFT JOIN devices d ON l.device_id = d.id
                    WHERE COALESCE(d.name, '(no device)') = ?
                    ORDER BY l.id DESC
                    LIMIT 500
                """, (sel,))
            for row in cur.fetchall():
                self.logs_history_tree.insert("", "end", values=row)
        except Exception:
            pass

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
        """Clear the preview/config window (thread-safe)."""
        self.after(0, self._clear_preview_in_main)

    def _clear_preview_in_main(self):
        try:
            self.preview.delete("0.0", "end")
        except Exception:
            pass

    def log(self, msg: str):
        """Thread-safe log — always dispatches to the main thread via after().
        Writes only to the Logs tab; never contaminates the config Preview."""
        self.after(0, lambda m=msg: self._log_in_main(m))

    def _log_in_main(self, msg: str):
        """Actual widget write — must only be called on the main thread."""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.txt_logs.configure(state="normal")
            self.txt_logs.insert("0.0", f"[{ts}] {msg}\n")
            # Cap log to 500 lines to prevent unbounded memory growth
            try:
                last_line = int(self.txt_logs.index("end-1c").split(".")[0])
                if last_line > 500:
                    self.txt_logs.delete("501.0", "end")
            except Exception:
                pass
            self.txt_logs.configure(state="disabled")
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
        """Switch between Main and Logs tabs"""
        if tab == "main":
            self.nb.set("main")
            self.btn_main_nav.configure(text_color="#C9D1D9")
            self.btn_logs_nav.configure(text_color="#9BA3AF")
            self.main_underline.configure(fg_color="#58A6FF")
            self.logs_underline.configure(fg_color="transparent")
        else:
            self.nb.set("logs")
            self.btn_main_nav.configure(text_color="#9BA3AF")
            self.btn_logs_nav.configure(text_color="#C9D1D9")
            self.main_underline.configure(fg_color="transparent")
            self.logs_underline.configure(fg_color="#58A6FF")
            self._refresh_logs_history()
    
    def _on_closing(self):
        """Confirm before closing if a send operation is in progress."""
        if self._send_in_progress:
            if not messagebox.askokcancel(
                "Send in progress",
                "A configuration is currently being sent to a device.\n"
                "Closing now may leave the device in a partial state.\n\n"
                "Close anyway?",
                parent=self,
            ):
                return
        self.destroy()

    def _show_right_sidebar(self):
        """Re-pack the right sidebar then re-pack center to preserve correct order."""
        self.right_sidebar.pack(side="right", fill="y", padx=(0, 16), pady=16)
        # Re-pack center so the pack manager assigns space correctly after re-entry
        self.center_frame.pack_forget()
        self.center_frame.pack(side="left", fill="both", expand=True, padx=16, pady=16)
        self.right_sidebar_visible = True

    def _toggle_right_sidebar(self):
        """Toggle the right sidebar visibility."""
        if self.right_sidebar_visible:
            self.right_sidebar.pack_forget()
            self.right_sidebar_visible = False
            self.btn_toggle_sidebar.configure(text="☰ Panel", text_color="#58A6FF")
        else:
            self._show_right_sidebar()
            self.btn_toggle_sidebar.configure(text="✕ Panel", text_color="#9BA3AF")

    def _on_window_resize(self, event):
        """Handle window resize — show/hide sidebar toggle button."""
        if event.widget == self:
            width = event.width
            if width < 950:
                if not self.btn_toggle_sidebar.winfo_ismapped():
                    self.btn_toggle_sidebar.pack(side="right", padx=(20, 0))
                if self.right_sidebar_visible and width < 850:
                    self.right_sidebar.pack_forget()
                    self.right_sidebar_visible = False
            else:
                if self.btn_toggle_sidebar.winfo_ismapped():
                    self.btn_toggle_sidebar.pack_forget()
                if not self.right_sidebar_visible:
                    self._show_right_sidebar()

    # ------------------- custom list item helpers (Figma style) -------------------
    def _create_device_item(self, name: str, label: str, idx: int):
        """Create a device list item with checkbox - Figma style"""
        # Outer frame - Figma list item padding
        item_frame = ctk.CTkFrame(self.devices_scroll, fg_color="transparent", height=40, corner_radius=4)
        item_frame.pack(fill="x", pady=4, padx=0)
        item_frame.pack_propagate(False)
        
        # Left border indicator (shows when selected) - Figma accent
        border = ctk.CTkFrame(item_frame, width=3, fg_color="transparent", corner_radius=0)
        border.pack(side="left", fill="y")
        
        # Content frame
        content = ctk.CTkFrame(item_frame, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=(8, 0))
        
        # Label - truncate long names and show full name in tooltip on hover
        display_text = _truncate(label, max_chars=22)
        lbl = ctk.CTkLabel(content, text=display_text, font=ctk.CTkFont(family="Inter", size=12),
                           text_color="#C9D1D9", anchor="w")
        lbl.pack(side="left", fill="x", expand=True, padx=8)
        if display_text != label:
            _Tooltip(lbl, label)
        
        # Checkbox on right - Figma styled
        var = ctk.BooleanVar(value=False)
        checkbox = ctk.CTkCheckBox(content, text="", variable=var, width=24,
                                  fg_color="#58A6FF", hover_color="#4A90E8",
                                  border_color="#C9D1D9", corner_radius=2, border_width=1,
                                  command=lambda n=name, i=idx: self._on_device_item_click(n, i))
        checkbox.pack(side="right", padx=8)
        
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
            prev["frame"].configure(fg_color="transparent")
            prev["label"].configure(text_color="#C9D1D9")
            prev["var"].set(False)
        
        # Select new - Figma highlight color
        self.selected_device_name = name
        if name in self.device_items:
            item = self.device_items[name]
            item["border"].configure(fg_color="#58A6FF")
            item["frame"].configure(fg_color="#E5F1FF")
            item["label"].configure(text_color="#15191E")
            item["var"].set(True)
        
        # Trigger device selection logic
        if 0 <= idx < len(self.devices):
            dname, model, meta = self.devices[idx]
            self.current_device = (dname, model, meta)
            self._refresh_template_list()
            # Auto-fill connection details from GNS3 metadata
            if meta.get("gns3_node"):
                host = meta.get("console_host", "localhost")
                port = str(meta.get("console_port", ""))
                try:
                    self.ent_host.delete(0, "end")
                    self.ent_host.insert(0, host)
                    self.ent_port.delete(0, "end")
                    self.ent_port.insert(0, port)
                    self.send_method.set("Telnet")
                    self._on_protocol_changed("Telnet")
                except Exception:
                    pass
            # Load saved credentials (fills any previously-saved form values)
            self._load_credentials(dname)
            # Update preview header
            try:
                self.preview.delete("0.0", "end")
                self.preview.insert("0.0", f"! device: {dname}\n")
            except Exception:
                pass
            # Show/hide rollback button based on whether snapshots exist
            try:
                if model.has_snapshots():
                    self.btn_rollback.pack(fill="x", padx=16, pady=(0, 24))
                else:
                    self.btn_rollback.pack_forget()
            except Exception:
                pass
    
    def _create_template_item(self, name: str, idx: int):
        """Create a template list item with checkbox - Figma style"""
        # Outer frame - Figma list item padding
        item_frame = ctk.CTkFrame(self.templates_scroll, fg_color="transparent", height=40, corner_radius=4)
        item_frame.pack(fill="x", pady=4, padx=0)
        item_frame.pack_propagate(False)
        
        # Left border indicator (shows when selected) - Figma accent
        border = ctk.CTkFrame(item_frame, width=3, fg_color="transparent", corner_radius=0)
        border.pack(side="left", fill="y")
        
        # Content frame
        content = ctk.CTkFrame(item_frame, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=(8, 0))
        
        # Label - Figma Body/caption
        lbl = ctk.CTkLabel(content, text=name, font=ctk.CTkFont(family="Inter", size=12), 
                          text_color="#C9D1D9", anchor="w")
        lbl.pack(side="left", fill="x", expand=True, padx=8)
        
        # Checkbox on right - Figma styled
        var = ctk.BooleanVar(value=False)
        checkbox = ctk.CTkCheckBox(content, text="", variable=var, width=24,
                                  fg_color="#58A6FF", hover_color="#4A90E8",
                                  border_color="#C9D1D9", corner_radius=2, border_width=1,
                                  command=lambda n=name, i=idx: self._on_template_item_click(n, i))
        checkbox.pack(side="right", padx=8)
        
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
            prev["frame"].configure(fg_color="transparent")
            prev["label"].configure(text_color="#C9D1D9")
            prev["var"].set(False)
        
        # Select new - Figma highlight color
        self.selected_template_name = name
        if name in self.template_items:
            item = self.template_items[name]
            item["border"].configure(fg_color="#58A6FF")
            item["frame"].configure(fg_color="#E5F1FF")
            item["label"].configure(text_color="#15191E")
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
        """Enable/disable fields based on selected protocol"""
        protocol = value.lower()
        
        # Figma colors for field states
        disabled_color = "#60656F"  # Disabled input background
        disabled_border = "#777D81"  # Disabled border
        disabled_text_color = "#4b5563"  # Muted gray
        enabled_color = "#2B323F"  # Input background
        enabled_border = "#6B7280"  # Input border
        enabled_label_color = "#C9D1D9"  # Active label color
        
        if protocol == "telnet":
            # Enable only Network IP and Port
            self.ent_host.configure(state="normal", fg_color=enabled_color, border_color=enabled_border)
            self.ent_port.configure(state="normal", fg_color=enabled_color, border_color=enabled_border)
            self.lbl_network_title.configure(text_color=enabled_label_color)
            # Disable credential fields (devices should not require login)
            self.ent_user.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
            self.ent_pass.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
            self.ent_enable.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
            self.enable_checkbox.configure(state="disabled")
            # Disable Serial fields
            for widget in self.serial_widgets:
                if isinstance(widget, ctk.CTkEntry):
                    widget.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
                elif isinstance(widget, ctk.CTkLabel):
                    widget.configure(text_color=disabled_text_color)
        elif protocol == "serial":
            # Enable only Serial fields
            for widget in self.serial_widgets:
                if isinstance(widget, ctk.CTkEntry):
                    widget.configure(state="normal", fg_color=enabled_color, border_color=enabled_border)
                elif isinstance(widget, ctk.CTkLabel):
                    widget.configure(text_color=enabled_label_color)
            # Disable all Network fields
            self.ent_host.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
            self.ent_port.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
            self.ent_user.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
            self.ent_pass.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
            self.ent_enable.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
            self.enable_checkbox.configure(state="disabled")
            self.lbl_network_title.configure(text_color=disabled_text_color)
        elif protocol == "ssh":
            # Enable all Network fields
            self.ent_host.configure(state="normal", fg_color=enabled_color, border_color=enabled_border)
            self.ent_port.configure(state="normal", fg_color=enabled_color, border_color=enabled_border)
            self.ent_user.configure(state="normal", fg_color=enabled_color, border_color=enabled_border)
            self.ent_pass.configure(state="normal", fg_color=enabled_color, border_color=enabled_border)
            self.ent_enable.configure(state="normal", fg_color=enabled_color, border_color=enabled_border)
            self.enable_checkbox.configure(state="normal")
            self.lbl_network_title.configure(text_color=enabled_label_color)
            # Disable Serial fields
            for widget in self.serial_widgets:
                if isinstance(widget, ctk.CTkEntry):
                    widget.configure(state="disabled", fg_color=disabled_color, border_color=disabled_border)
                elif isinstance(widget, ctk.CTkLabel):
                    widget.configure(text_color=disabled_text_color)

    # ------------------- send/run -------------------
    def _set_send_busy(self, busy: bool):
        """Enable/disable the Send button and track in-progress state."""
        self._send_in_progress = busy
        try:
            self.btn_send.configure(
                state="disabled" if busy else "normal",
                text="Sending…" if busy else "Send",
            )
        except Exception:
            pass

    def send_now(self):
        content = self.preview.get("0.0", "end").strip()
        if not content:
            messagebox.showinfo("info", "nothing to send"); return

        # Pre-send validation check
        try:
            from .validators import ConfigValidator
            warnings = ConfigValidator.check_all(self.devices)
            if warnings:
                msg = "The following issues were detected:\n\n" + "\n".join(
                    f"• {w}" for w in warnings
                ) + "\n\nSend anyway?"
                if not messagebox.askokcancel("Config Warnings", msg, parent=self):
                    return
        except Exception:
            pass  # validator errors must never block sending

        method = self.send_method.get().lower()
        self._set_send_busy(True)

        if method == "serial":
            port = self.ent_serial_port.get().strip()
            try:
                baud = int(self.ent_serial_baud.get().strip() or "9600")
            except Exception:
                self._set_send_busy(False)
                messagebox.showerror("error", "invalid baud"); return
            if not port:
                self._set_send_busy(False)
                messagebox.showerror("error", "enter serial port"); return
            threading.Thread(target=self._thread_serial,
                             args=(port, baud, content), daemon=True).start()
        elif method == "telnet":
            host = self.ent_host.get().strip()
            if not host:
                self._set_send_busy(False)
                messagebox.showerror("error", "enter host"); return
            try:
                port = int(self.ent_port.get().strip() or "23")
            except Exception:
                self._set_send_busy(False)
                messagebox.showerror("error", "invalid port"); return
            # Read credentials from the form (same as SSH — device may require login)
            user   = self.ent_user.get().strip()
            pw     = self.ent_pass.get().strip()
            enable = self.ent_enable.get().strip() if self.enable_checkbox.get() else ""
            threading.Thread(target=self._thread_telnet,
                             args=(host, port, user, pw, enable, content), daemon=True).start()
        elif method == "ssh":
            host = self.ent_host.get().strip()
            if not host:
                self._set_send_busy(False)
                messagebox.showerror("error", "enter host"); return
            try:
                port = int(self.ent_port.get().strip() or "22")
            except Exception:
                self._set_send_busy(False)
                messagebox.showerror("error", "invalid port"); return
            user   = self.ent_user.get().strip()
            pw     = self.ent_pass.get().strip()
            enable = self.ent_enable.get().strip() if self.enable_checkbox.get() else ""
            threading.Thread(target=self._thread_ssh,
                             args=(host, port, user, pw, enable, content), daemon=True).start()
        else:
            self._set_send_busy(False)
            messagebox.showerror("error", "unknown method")

    def _thread_serial(self, port, baud, content):
        self.log(f"starting serial to {port}@{baud}")
        try:
            ok = Sender.send_serial(self.log, port, baud, content)
            self.log(f"serial finished: {ok}")
            if ok:
                self.clear_preview()
                device_name = self.current_device[0] if self.current_device else "unknown"
                self._write_audit_log(device_name, "serial", f"port={port} baud={baud}", config_content=content)
        finally:
            self.after(0, lambda: self._set_send_busy(False))

    def _thread_telnet(self, host, port, user, pw, enable, content):
        self.log(f"starting telnet to {host}:{port}")
        try:
            ok = Sender.send_telnet(self.log, host, port, user, pw, enable, content)
            self.log(f"telnet finished: {ok}")
            if ok:
                self.clear_preview()
                device_name = self.current_device[0] if self.current_device else "unknown"
                self._write_audit_log(device_name, "telnet", f"host={host} port={port}", config_content=content)
                cmds = ["show ip interface brief"]
                try:
                    if self.current_device:
                        from ..models.devices import CoreSwitchModel, SwitchModel
                        _, mdl, _ = self.current_device
                        if isinstance(mdl, (CoreSwitchModel, SwitchModel)):
                            cmds.append("show vlan-switch")
                except Exception:
                    pass
                self.log("[verify] running post-send verification...")
                results = Sender.verify_telnet(self.log, host, port, cmds,
                                               username=user, password=pw, enable_pw=enable)
                if results:
                    self.after(0, lambda r=results: self._show_verify_dialog(r))
        finally:
            self.after(0, lambda: self._set_send_busy(False))

    def _thread_ssh(self, host, port, user, pw, enable, content):
        self.log(f"starting ssh to {host}:{port} as {user}")
        try:
            ok = Sender.send_ssh(self.log, host, port, user, pw, enable, content)
            self.log(f"ssh finished: {ok}")
            if ok:
                self.clear_preview()
                device_name = self.current_device[0] if self.current_device else "unknown"
                self._write_audit_log(device_name, "ssh", f"host={host} port={port} user={user}", config_content=content)
        finally:
            self.after(0, lambda: self._set_send_busy(False))

    def _show_verify_dialog(self, results: dict):
        """Display a post-send verification window with color-coded interface status."""
        import tkinter as tk
        import re

        t = {
            "bg":      "#0D1117",
            "card":    "#1F2630",
            "sidebar": "#161B22",
            "text":    "#C9D1D9",
            "muted":   "#8B949E",
            "success": "#3FB950",
            "danger":  "#F85149",
            "warn":    "#D29922",
            "border":  "#30363D",
        }

        win = tk.Toplevel(self)
        win.title("Post-Send Verification")
        win.resizable(True, True)
        win.configure(bg=t["bg"])
        apply_responsive_geometry(win, 680, 520)

        # Title bar
        hdr = tk.Frame(win, bg=t["card"], pady=12)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="Config Verification Results",
            font=("TkDefaultFont", 14, "bold"), fg=t["text"], bg=t["card"],
        ).pack(side="left", padx=16)

        # Scrollable results area
        canvas = tk.Canvas(win, bg=t["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=16, pady=12)

        inner = tk.Frame(canvas, bg=t["bg"])
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_frame_configure)

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _render_interface_table(parent, raw: str):
            """Parse 'show ip interface brief' and render a color-coded table."""
            lines = [l for l in raw.splitlines() if l.strip()]
            # Find the header line
            header_idx = next(
                (i for i, l in enumerate(lines) if "Interface" in l and "Status" in l),
                None,
            )
            if header_idx is None:
                tk.Label(parent, text=raw[:800], fg=t["muted"], bg=t["bg"],
                         font=("Courier New", 10), justify="left", anchor="w",
                         wraplength=580).pack(anchor="w")
                return

            # Header row
            hf = tk.Frame(parent, bg=t["card"])
            hf.pack(fill="x", pady=(0, 2))
            for col, w in [("Interface", 22), ("IP Address", 18), ("Status", 12), ("Protocol", 12)]:
                tk.Label(hf, text=col, fg=t["muted"], bg=t["card"],
                         font=("TkDefaultFont", 10, "bold"), width=w, anchor="w").pack(side="left")

            iface_re = re.compile(
                r"^(\S+)\s+(\S+)\s+\S+\s+\S+\s+(\S+)\s+(\S+)", re.IGNORECASE
            )
            for line in lines[header_idx + 1:]:
                m = iface_re.match(line.strip())
                if not m:
                    continue
                iface, ip, status, protocol = m.group(1), m.group(2), m.group(3), m.group(4)
                is_up = protocol.lower() == "up"
                row_bg  = t["card"] if is_up else "#2a1a1a"
                dot_col = t["success"] if is_up else t["danger"]

                rf = tk.Frame(parent, bg=row_bg)
                rf.pack(fill="x", pady=1)
                tk.Label(rf, text="●", fg=dot_col, bg=row_bg,
                         font=("TkDefaultFont", 9)).pack(side="left", padx=(4, 0))
                for val, w in [(iface, 20), (ip, 18), (status, 12), (protocol, 12)]:
                    tk.Label(rf, text=val, fg=t["text"], bg=row_bg,
                             font=("Courier New", 10), width=w, anchor="w").pack(side="left")

        def _render_vlan_table(parent, raw: str):
            """Parse 'show vlan-switch' / 'show vlan brief' and render a simple table."""
            if re.search(r"(Invalid input|% Invalid|% Incomplete)", raw, re.IGNORECASE):
                tk.Label(parent, text="VLAN command not supported on this device.",
                         fg=t["muted"], bg=t["bg"], font=("TkDefaultFont", 10)).pack(anchor="w", padx=4, pady=4)
                return
            lines = [l for l in raw.splitlines() if l.strip()]
            header_idx = next(
                (i for i, l in enumerate(lines) if "VLAN" in l and "Name" in l),
                None,
            )
            if header_idx is None:
                tk.Label(parent, text=raw[:800], fg=t["muted"], bg=t["bg"],
                         font=("Courier New", 10), justify="left", anchor="w",
                         wraplength=580).pack(anchor="w")
                return

            hf = tk.Frame(parent, bg=t["card"])
            hf.pack(fill="x", pady=(0, 2))
            for col, w in [("VLAN", 8), ("Name", 28), ("Status", 12)]:
                tk.Label(hf, text=col, fg=t["muted"], bg=t["card"],
                         font=("TkDefaultFont", 10, "bold"), width=w, anchor="w").pack(side="left")

            vlan_re = re.compile(r"^(\d+)\s+(\S+)\s+(\S+)", re.IGNORECASE)
            for line in lines[header_idx + 1:]:
                m = vlan_re.match(line.strip())
                if not m:
                    continue
                vid, name, status = m.group(1), m.group(2), m.group(3)
                is_active = "active" in status.lower()
                row_bg  = t["card"] if is_active else "#2a1a1a"
                dot_col = t["success"] if is_active else t["warn"]

                rf = tk.Frame(parent, bg=row_bg)
                rf.pack(fill="x", pady=1)
                tk.Label(rf, text="●", fg=dot_col, bg=row_bg,
                         font=("TkDefaultFont", 9)).pack(side="left", padx=(4, 0))
                for val, w in [(vid, 6), (name, 26), (status, 12)]:
                    tk.Label(rf, text=val, fg=t["text"], bg=row_bg,
                             font=("Courier New", 10), width=w, anchor="w").pack(side="left")

        _cmd_labels = {
            "show ip interface brief": "Network Interfaces",
            "show vlan-switch":        "VLAN Membership",
            "show vlan brief":         "VLAN Membership",
        }

        for cmd, raw in results.items():
            label = _cmd_labels.get(cmd, cmd)
            sec = tk.Frame(inner, bg=t["sidebar"], pady=6)
            sec.pack(fill="x", pady=(8, 4))
            tk.Label(sec, text=f"  {label}", font=("TkDefaultFont", 11, "bold"),
                     fg=t["success"], bg=t["sidebar"]).pack(side="left", padx=12)

            if "interface brief" in cmd:
                _render_interface_table(inner, raw)
            elif "vlan" in cmd:
                _render_vlan_table(inner, raw)
            else:
                tk.Label(inner, text=raw[:1000], fg=t["text"], bg=t["bg"],
                         font=("Courier New", 10), justify="left", anchor="w",
                         wraplength=580).pack(anchor="w", padx=4)

        tk.Button(
            win, text="Close", command=win.destroy,
            bg="#238636", fg="white", relief="flat", padx=20, pady=6,
            font=("TkDefaultFont", 11),
        ).pack(pady=12)

    # ─────────────────────────────────────────────────────────────────────────
    # Credential Manager
    # ─────────────────────────────────────────────────────────────────────────

    def save_credentials(self):
        """Save current form values to the credentials table for the selected device."""
        if not self.selected_device_name:
            messagebox.showinfo("Save Credentials", "Select a device first.", parent=self)
            return
        try:
            host = self.ent_host.get().strip()
            port = self.ent_port.get().strip()
            username = self.ent_user.get().strip()
            password = _obfuscate(self.ent_pass.get().strip())
            enable = _obfuscate(self.ent_enable.get().strip())
            protocol = self.send_method.get().lower()
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with db_lock:
                cur.execute(
                    """INSERT INTO credentials
                       (device_name, host, port, username, password, enable_password, protocol, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(device_name) DO UPDATE SET
                       host=excluded.host, port=excluded.port,
                       username=excluded.username, password=excluded.password,
                       enable_password=excluded.enable_password,
                       protocol=excluded.protocol, updated_at=excluded.updated_at""",
                    (self.selected_device_name, host, port, username, password, enable, protocol, ts)
                )
                conn.commit()
            messagebox.showinfo(
                "Credentials Saved",
                f"Credentials for '{self.selected_device_name}' saved.\n"
                "They will be auto-loaded next time you select this device.",
                parent=self
            )
            self.log(f"[creds] saved credentials for {self.selected_device_name}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save credentials:\n{e}", parent=self)

    def _load_credentials(self, device_name: str):
        """Auto-fill connection form from saved credentials for device_name."""
        try:
            cur.execute(
                "SELECT host, port, username, password, enable_password, protocol "
                "FROM credentials WHERE device_name=?",
                (device_name,)
            )
            row = cur.fetchone()
            if not row:
                return
            host, port, username, password, enable, protocol = row
            if host:
                self.ent_host.configure(state="normal")
                self.ent_host.delete(0, "end")
                self.ent_host.insert(0, host)
            if port:
                self.ent_port.configure(state="normal")
                self.ent_port.delete(0, "end")
                self.ent_port.insert(0, port)
            if username:
                self.ent_user.configure(state="normal")
                self.ent_user.delete(0, "end")
                self.ent_user.insert(0, username)
            if password:
                self.ent_pass.configure(state="normal")
                self.ent_pass.delete(0, "end")
                self.ent_pass.insert(0, _deobfuscate(password))
            if enable:
                self.ent_enable.configure(state="normal")
                self.ent_enable.delete(0, "end")
                self.ent_enable.insert(0, _deobfuscate(enable))
            if protocol and protocol in ("telnet", "serial", "ssh"):
                display = protocol.capitalize() if protocol != "ssh" else "SSH"
                self.send_method.set(display)
                self._on_protocol_changed(display)
            else:
                self._on_protocol_changed(self.send_method.get())
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Export / Import Project
    # ─────────────────────────────────────────────────────────────────────────

    def export_project(self):
        """Export all workspace devices and templates to a .ancs JSON file."""
        if not self.devices:
            messagebox.showinfo("Export", "No devices to export.", parent=self)
            return
        filepath = filedialog.asksaveasfilename(
            title="Export ANCS Project",
            defaultextension=".ancs",
            filetypes=[("ANCS Project", "*.ancs"), ("JSON", "*.json"), ("All files", "*.*")],
            parent=self
        )
        if not filepath:
            return
        try:
            export_data = {
                "version": "1.0",
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "devices": []
            }
            # Map model class to type key
            type_map = {
                "RouterModel":     "router",
                "SwitchModel":     "switch",
                "CoreSwitchModel": "core switch",
            }
            for name, model, meta in self.devices:
                type_key = type_map.get(model.__class__.__name__, "router")
                # Exclude non-serialisable metadata values
                safe_meta = {
                    k: v for k, v in meta.items()
                    if isinstance(v, (str, int, float, bool, list, type(None)))
                }
                export_data["devices"].append({
                    "name":      name,
                    "type_key":  type_key,
                    "metadata":  safe_meta,
                    "templates": dict(model.templates),
                })
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            messagebox.showinfo(
                "Export Complete",
                f"Exported {len(self.devices)} device(s) to:\n{filepath}",
                parent=self
            )
            self.log(f"[export] saved project to {filepath}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e), parent=self)

    def import_project(self):
        """Import devices and templates from a previously exported .ancs file."""
        filepath = filedialog.askopenfilename(
            title="Import ANCS Project",
            filetypes=[("ANCS Project", "*.ancs"), ("JSON", "*.json"), ("All files", "*.*")],
            parent=self
        )
        if not filepath:
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Import Error", f"Could not read file:\n{e}", parent=self)
            return

        devices_data = data.get("devices", [])
        if not devices_data:
            messagebox.showinfo("Import", "No devices found in file.", parent=self)
            return

        if self.devices:
            if not messagebox.askyesno(
                "Import Project",
                f"This will add {len(devices_data)} device(s) to the current workspace.\n"
                "Devices with duplicate names will be skipped.\n\nContinue?",
                parent=self
            ):
                return

        added = 0
        skipped = 0
        for dev in devices_data:
            name     = dev.get("name", "unnamed")
            type_key = dev.get("type_key", "router").lower()
            meta     = dev.get("metadata", {})
            templates = dev.get("templates", {})

            if type_key not in self.device_types:
                type_key = "router"

            # Skip if name already exists
            if any(d[0] == name for d in self.devices):
                skipped += 1
                continue

            self.add_device_instance(type_key, name, metadata=meta)
            # Restore templates
            _, model, _ = self.devices[-1]
            for tname, ttext in templates.items():
                model.set_template(tname, ttext)
            added += 1

        self.refresh_device_list()
        messagebox.showinfo(
            "Import Complete",
            f"Imported {added} device(s)."
            + (f"\nSkipped {skipped} duplicate(s)." if skipped else ""),
            parent=self
        )
        self.log(f"[import] loaded {added} device(s) from {filepath}")

    # ─────────────────────────────────────────────────────────────────────────
    # Sequential Multi-Device Deploy
    # ─────────────────────────────────────────────────────────────────────────

    def deploy_all_ordered(self):
        """Deploy configs to all devices in dependency order: Router → Core → Access."""
        if not self.devices:
            messagebox.showinfo("Deploy All", "No devices in workspace.", parent=self)
            return

        # Sort by role priority
        def _priority(item):
            _, model, __ = item
            if isinstance(model, RouterModel):
                return 0
            elif isinstance(model, CoreSwitchModel):
                return 1
            return 2

        ordered = sorted(self.devices, key=_priority)

        # Build deploy list with connection info + credentials
        deploy_list = []
        for name, model, meta in ordered:
            config = model.build_full_config().strip()
            if not config or config.startswith("!"):
                # Check if there's any real content
                lines = [l for l in config.splitlines() if l.strip() and not l.strip().startswith("!")]
                if not lines:
                    deploy_list.append((name, model, meta, None, None, "", "", "", "no config"))
                    continue

            host     = meta.get("console_host") or meta.get("ip", "")
            port_raw = meta.get("console_port") or meta.get("port", "")
            username = meta.get("username", "")
            password = meta.get("password", "")
            enable_pw = meta.get("enable_pw", "")

            # Also check saved credentials table for connection info + auth
            try:
                with db_lock:
                    cur.execute(
                        "SELECT host, port, username, password, enable_password "
                        "FROM credentials WHERE device_name=?",
                        (name,)
                    )
                    row = cur.fetchone()
                if row:
                    if row[0] and not host:
                        host, port_raw = row[0], row[1]
                    if row[2] and not username:
                        username = row[2]
                    if row[3] and not password:
                        password = _deobfuscate(row[3])
                    if row[4] and not enable_pw:
                        enable_pw = _deobfuscate(row[4])
            except Exception:
                pass

            if not host:
                deploy_list.append((name, model, meta, None, None, "", "", "", "no host"))
                continue

            try:
                port = int(port_raw)
            except (ValueError, TypeError):
                deploy_list.append((name, model, meta, None, None, "", "", "", f"bad port: {port_raw}"))
                continue

            deploy_list.append((name, model, meta, host, port, username, password, enable_pw, "ready"))

        self._show_deploy_progress_window(deploy_list)

    def _show_deploy_progress_window(self, deploy_list: list):
        """Show a progress dialog and start sequential deployment."""
        t = {
            "bg":      "#0D1117",
            "card":    "#1F2630",
            "text":    "#C9D1D9",
            "muted":   "#8B949E",
            "success": "#3FB950",
            "danger":  "#F85149",
            "warn":    "#D29922",
            "accent":  "#58A6FF",
        }

        win = tk.Toplevel(self)
        win.title("Deploy All — Progress")
        win.resizable(True, True)
        win.configure(bg=t["bg"])
        win.transient(self)
        apply_responsive_geometry(win, 560, 460)

        tk.Label(
            win, text="Deploying configurations (Router → Core → Access)…",
            font=("TkDefaultFont", 12, "bold"), fg=t["text"], bg=t["bg"]
        ).pack(anchor="w", padx=16, pady=(16, 8))

        # Progress table
        table_frame = tk.Frame(win, bg=t["card"])
        table_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        canvas = tk.Canvas(table_frame, bg=t["card"], highlightthickness=0)
        vsb = tk.Scrollbar(table_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)

        inner = tk.Frame(canvas, bg=t["card"])
        cwin = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))

        # Header row
        hdr_f = tk.Frame(inner, bg=t["bg"])
        hdr_f.pack(fill="x", padx=4, pady=(4, 2))
        for col, w in [("Device", 22), ("Role", 14), ("Status", 20)]:
            tk.Label(
                hdr_f, text=col, fg=t["muted"], bg=t["bg"],
                font=("TkDefaultFont", 9, "bold"), width=w, anchor="w"
            ).pack(side="left")

        # Status labels per device
        status_labels = {}
        role_names = {0: "Router", 1: "Core SW", 2: "Access SW"}
        for name, model, meta, host, port, _u, _pw, _en, state in deploy_list:
            priority = 0 if isinstance(model, RouterModel) else (1 if isinstance(model, CoreSwitchModel) else 2)
            role_str = role_names.get(priority, "Unknown")

            rf = tk.Frame(inner, bg=t["card"])
            rf.pack(fill="x", padx=4, pady=1)
            tk.Label(rf, text=name, fg=t["text"], bg=t["card"],
                     font=("Courier New", 10), width=22, anchor="w").pack(side="left")
            tk.Label(rf, text=role_str, fg=t["muted"], bg=t["card"],
                     font=("TkDefaultFont", 9), width=14, anchor="w").pack(side="left")
            init_color = t["muted"] if state == "ready" else t["danger"]
            init_text  = "queued" if state == "ready" else state
            lbl = tk.Label(rf, text=init_text, fg=init_color, bg=t["card"],
                           font=("TkDefaultFont", 9), width=20, anchor="w")
            lbl.pack(side="left")
            status_labels[name] = lbl

        # Log area
        lbl_log = tk.Label(win, text="Log:", fg=t["muted"], bg=t["bg"],
                           font=("TkDefaultFont", 10))
        lbl_log.pack(anchor="w", padx=16)
        txt_log = tk.Text(
            win, height=6,
            bg=t["card"], fg=t["text"],
            font=("Courier New", 9), relief="flat", borderwidth=0,
            state="disabled"
        )
        txt_log.pack(fill="x", padx=16, pady=(0, 8))

        def _log(msg: str):
            """Thread-safe log for the deploy-progress window."""
            def _write():
                try:
                    txt_log.configure(state="normal")
                    txt_log.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
                    txt_log.see("end")
                    txt_log.configure(state="disabled")
                except Exception:
                    pass
            try:
                win.after(0, _write)
            except Exception:
                pass

        btn_close = tk.Button(
            win, text="Close", command=win.destroy,
            bg=t["card"], fg=t["muted"],
            relief="flat", padx=20, pady=6,
            font=("TkDefaultFont", 10)
        )
        btn_close.pack(pady=(0, 12))

        def _deploy_worker():
            for name, model, meta, host, port, username, password, enable_pw, state in deploy_list:
                if state != "ready":
                    _log(f"SKIP  {name}  ({state})")
                    self.log(f"[deploy-all] SKIP {name} ({state})")
                    continue

                lbl = status_labels.get(name)
                if lbl:
                    win.after(0, lambda l=lbl: l.configure(text="sending…", fg=t["warn"]))

                config = model.build_full_config()
                _log(f"SEND  {name}  →  {host}:{port}")
                self.log(f"[deploy-all] sending {name} → {host}:{port}")

                try:
                    ok = Sender.send_telnet(
                        _log, host, port, username, password, enable_pw, config
                    )
                    status = "✓ done" if ok else "✗ failed"
                    color  = t["success"] if ok else t["danger"]
                    if ok:
                        self._write_audit_log(name, "telnet", f"deploy-all host={host}:{port}", config_content=config)
                        self.log(f"[deploy-all] {name} ✓ done")
                    else:
                        self.log(f"[deploy-all] {name} ✗ failed")
                except Exception as exc:
                    status = f"error: {exc}"
                    color  = t["danger"]
                    ok     = False
                    self.log(f"[deploy-all] {name} ERROR: {exc}")

                _log(f"  → {status}")
                if lbl:
                    win.after(0, lambda l=lbl, s=status, c=color: l.configure(text=s, fg=c))

            _log("─── all done ───")
            self.log("[deploy-all] all devices complete")
            win.after(0, lambda: btn_close.configure(bg="#238636", fg="white"))

        threading.Thread(target=_deploy_worker, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # Monitor & Terminal launchers
    # ─────────────────────────────────────────────────────────────────────────

    def open_monitor(self):
        """Open the real-time device interface monitor."""
        if not self.devices:
            messagebox.showinfo("Monitor", "No devices in workspace.", parent=self)
            return
        DeviceMonitor(self, self.devices)

    def open_terminal(self):
        """Open an interactive CLI terminal for the currently selected device."""
        if not self.current_device:
            messagebox.showinfo("Terminal", "Select a device first.", parent=self)
            return
        name, model, meta = self.current_device
        host = meta.get("console_host") or meta.get("ip", "")
        port_raw = meta.get("console_port") or meta.get("port", "")

        # Fall back to form values if metadata is empty
        if not host:
            host = self.ent_host.get().strip()
        if not port_raw:
            port_raw = self.ent_port.get().strip()

        if not host:
            messagebox.showerror(
                "Terminal",
                "No host/IP set for this device.\n"
                "Fill in the Host field in the right panel or import from GNS3.",
                parent=self
            )
            return
        try:
            port = int(port_raw or "23")
        except ValueError:
            messagebox.showerror("Terminal", f"Invalid port: {port_raw}", parent=self)
            return

        # Load credentials (meta → saved credentials table)
        username  = meta.get("username", "")
        password  = meta.get("password", "")
        enable_pw = meta.get("enable_pw", "")
        if not (username and password):
            try:
                with db_lock:
                    cur.execute(
                        "SELECT username, password, enable_password "
                        "FROM credentials WHERE device_name=?",
                        (name,)
                    )
                    row = cur.fetchone()
                if row:
                    if not username and row[0]:
                        username = row[0]
                    if not password and row[1]:
                        password = _deobfuscate(row[1])
                    if not enable_pw and row[2]:
                        enable_pw = _deobfuscate(row[2])
            except Exception:
                pass

        TerminalPanel(self, name, host, port,
                      username=username, password=password, enable_pw=enable_pw)

    # ─────────────────────────────────────────────────────────────────────────
    # Audit Log helper
    # ─────────────────────────────────────────────────────────────────────────

    def _write_audit_log(self, device_name: str, protocol: str, details: str = "", config_content: str = ""):
        """Write a successful config-send event to the logs table.
        Safe to call from any thread — uses db_lock."""
        try:
            stored = details or ""
            if config_content:
                stored = (details + "\n\n--- CONFIG SENT ---\n" + config_content) if details else config_content
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with db_lock:
                cur.execute("SELECT id FROM devices WHERE name=?", (device_name,))
                row = cur.fetchone()
                device_id = row[0] if row else None
                cur.execute(
                    "INSERT INTO logs (action, device_id, details, severity, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (f"config_sent_{protocol}", device_id, stored, "info", ts)
                )
                conn.commit()
            # Auto-refresh the Logs tab history table if the user is looking at it
            self.after(0, self._refresh_logs_history)
        except Exception:
            pass  # audit log errors must never crash the app

    def open_audit_log(self):
        """Open a window showing the full config-send history from the logs table. Selecting a row shows the config that was sent."""
        t = {
            "bg":    "#0D1117", "card":  "#1F2630",
            "text":  "#C9D1D9", "muted": "#8B949E",
            "success": "#3FB950", "danger": "#F85149",
            "accent": "#58A6FF",
        }
        win = tk.Toplevel(self)
        win.title("Send History / Audit Log")
        win.resizable(True, True)
        win.configure(bg=t["bg"])
        apply_responsive_geometry(win, 800, 600)

        tk.Label(
            win, text="  Config Send History",
            font=("TkDefaultFont", 14, "bold"), fg=t["text"], bg=t["bg"]
        ).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(
            win,
            text="Select a row to see the config that was sent. New sends store the full config.",
            font=("TkDefaultFont", 9), fg=t["muted"], bg=t["bg"]
        ).pack(anchor="w", padx=16, pady=(0, 8))

        # Top: tree of send history
        tree_frame = tk.Frame(win, bg=t["bg"])
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        cols = ("id", "device", "action", "time")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=8)
        for h, w in [("id", 50), ("device", 180), ("action", 200), ("time", 160)]:
            tree.heading(h, text=h)
            tree.column(h, width=w, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Bottom: config preview when row selected
        tk.Label(win, text="  Config sent (select a row above)", font=("TkDefaultFont", 10, "bold"),
                fg=t["muted"], bg=t["bg"]).pack(anchor="w", padx=16, pady=(8, 4))
        config_frame = tk.Frame(win, bg=t["card"], relief="flat")
        config_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        config_text = tk.Text(config_frame, wrap="none", font=("Consolas", 10), bg="#161B22", fg=t["text"],
                             insertbackground=t["text"], relief="flat", padx=12, pady=8)
        config_sb = ttk.Scrollbar(config_frame, orient="vertical", command=config_text.yview)
        config_sb_x = ttk.Scrollbar(config_frame, orient="horizontal", command=config_text.xview)
        config_text.configure(yscrollcommand=config_sb.set, xscrollcommand=config_sb_x.set)
        config_text.pack(side="left", fill="both", expand=True)
        config_sb.pack(side="right", fill="y")
        config_sb_x.pack(side="bottom", fill="x")

        def _extract_config(details: str) -> str:
            if "--- CONFIG SENT ---" in details:
                return details.split("--- CONFIG SENT ---", 1)[1].strip()
            return details or "(no config stored for older entries)"

        def _on_select(_):
            sel = tree.selection()
            config_text.delete("1.0", "end")
            if not sel:
                config_text.insert("1.0", "Select a row to view the config that was sent.")
                return
            item = tree.item(sel[0])
            vals = item.get("values", ())
            if len(vals) < 1:
                return
            log_id = vals[0]
            try:
                cur.execute("SELECT details FROM logs WHERE id=?", (log_id,))
                row = cur.fetchone()
                if row:
                    config_text.insert("1.0", _extract_config(row[0] or ""))
                else:
                    config_text.insert("1.0", "(entry not found)")
            except Exception:
                config_text.insert("1.0", "(error loading)")

        tree.bind("<<TreeviewSelect>>", _on_select)

        def _refresh():
            for row in tree.get_children():
                tree.delete(row)
            config_text.delete("1.0", "end")
            config_text.insert("1.0", "Select a row to view the config that was sent.")
            try:
                cur.execute("""
                    SELECT l.id, COALESCE(d.name,'—'), l.action, l.created_at
                    FROM logs l
                    LEFT JOIN devices d ON l.device_id = d.id
                    WHERE l.action LIKE 'config_sent_%'
                    ORDER BY l.id DESC
                    LIMIT 200
                """)
                for row in cur.fetchall():
                    tree.insert("", "end", values=row)
            except Exception as e:
                tree.insert("", "end", values=("", "", f"Error: {e}", ""))

        _refresh()

        btn_f = tk.Frame(win, bg=t["bg"])
        btn_f.pack(fill="x", padx=16, pady=(0, 12))
        tk.Button(
            btn_f, text="Refresh", command=_refresh,
            bg=t["accent"], fg="white", relief="flat",
            font=("TkDefaultFont", 10), padx=16, pady=4, cursor="hand2"
        ).pack(side="left")
        tk.Button(
            btn_f, text="Close", command=win.destroy,
            bg=t["card"], fg=t["muted"], relief="flat",
            font=("TkDefaultFont", 10), padx=16, pady=4, cursor="hand2"
        ).pack(side="right")

    # ─────────────────────────────────────────────────────────────────────────
    # AI Config Assistant
    # ─────────────────────────────────────────────────────────────────────────

    def open_ai_assistant(self):
        """Open the AI Config Assistant window."""
        t = {
            "bg":      "#0D1117", "card":  "#1F2630",
            "sidebar": "#161B22", "text":  "#C9D1D9",
            "muted":   "#8B949E", "accent": "#58A6FF",
            "success": "#3FB950", "danger": "#F85149",
            "input_bg": "#161B22",
        }
        win = tk.Toplevel(self)
        win.title("AI Config Assistant")
        win.resizable(True, True)
        win.configure(bg=t["bg"])
        apply_responsive_geometry(win, 740, 580, min_w=560, min_h=420)

        # Header
        hdr = tk.Frame(win, bg=t["card"], pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="  🤖 AI Config Assistant",
            font=("TkDefaultFont", 14, "bold"), fg=t["text"], bg=t["card"]
        ).pack(side="left")
        tk.Label(
            hdr, text="Describe what you want — get IOS CLI config",
            font=("TkDefaultFont", 9), fg=t["muted"], bg=t["card"]
        ).pack(side="left", padx=10)

        # API Key row
        key_row = tk.Frame(win, bg=t["bg"])
        key_row.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(key_row, text="OpenAI API Key:", fg=t["muted"], bg=t["bg"],
                 font=("TkDefaultFont", 9)).pack(side="left")
        ent_key = tk.Entry(key_row, bg=t["sidebar"], fg=t["text"],
                           show="*", font=("Courier New", 10),
                           relief="flat", insertbackground=t["text"], width=40)
        ent_key.pack(side="left", padx=(8, 0))

        # Try to load saved key from dedicated api_keys table
        try:
            cur.execute("SELECT key_value FROM api_keys WHERE key_name='openai' ORDER BY id DESC LIMIT 1")
            r = cur.fetchone()
            if r and r[0]:
                ent_key.insert(0, r[0])
        except Exception:
            pass

        def _save_key():
            k = ent_key.get().strip()
            if k:
                try:
                    with db_lock:
                        cur.execute(
                            "INSERT INTO api_keys (key_name, key_value, updated_at) VALUES (?,?,?) "
                            "ON CONFLICT(key_name) DO UPDATE SET key_value=excluded.key_value, "
                            "updated_at=excluded.updated_at",
                            ("openai", k, time.strftime("%Y-%m-%d %H:%M:%S"))
                        )
                        conn.commit()
                except Exception:
                    pass

        tk.Button(key_row, text="Save", command=_save_key,
                  bg=t["accent"], fg="white", relief="flat",
                  font=("TkDefaultFont", 9), padx=8, pady=2,
                  cursor="hand2").pack(side="left", padx=8)

        # Prompt area
        tk.Label(win, text="Describe what you want:", fg=t["muted"], bg=t["bg"],
                 font=("TkDefaultFont", 10)).pack(anchor="w", padx=16, pady=(8, 2))
        ent_prompt = tk.Text(
            win, height=4, bg=t["sidebar"], fg=t["text"],
            font=("TkDefaultFont", 11), relief="flat", borderwidth=0,
            insertbackground=t["text"], wrap="word"
        )
        ent_prompt.pack(fill="x", padx=16, pady=(0, 4))

        # Example prompts
        examples = [
            "Block all traffic from VLAN 10 to VLAN 20 using an ACL",
            "Configure OSPF area 0 on all router interfaces",
            "Create a DHCP pool for 192.168.10.0/24 with gateway 192.168.10.1",
            "Set up SSH access with local authentication",
        ]
        ex_frame = tk.Frame(win, bg=t["bg"])
        ex_frame.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(ex_frame, text="Examples:", fg=t["muted"], bg=t["bg"],
                 font=("TkDefaultFont", 8)).pack(anchor="w")
        for ex in examples:
            tk.Button(
                ex_frame, text=f"  {ex}",
                command=lambda e=ex: (ent_prompt.delete("1.0", "end"), ent_prompt.insert("1.0", e)),
                bg=t["card"], fg=t["accent"], relief="flat",
                font=("TkDefaultFont", 8), cursor="hand2", anchor="w"
            ).pack(fill="x", pady=1)

        # Output area
        tk.Label(win, text="Generated Config:", fg=t["muted"], bg=t["bg"],
                 font=("TkDefaultFont", 10)).pack(anchor="w", padx=16, pady=(4, 2))
        txt_output = tk.Text(
            win, bg=t["input_bg"], fg=t["text"],
            font=("Courier New", 11), relief="flat", borderwidth=0,
            insertbackground=t["text"], wrap="word", state="disabled"
        )
        txt_output.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        def _set_output(text: str):
            txt_output.configure(state="normal")
            txt_output.delete("1.0", "end")
            txt_output.insert("1.0", text)
            txt_output.configure(state="disabled")

        def _generate():
            prompt = ent_prompt.get("1.0", "end").strip()
            if not prompt:
                return
            api_key = ent_key.get().strip()
            if not api_key:
                _set_output(
                    "! No API key provided.\n"
                    "! Enter your OpenAI API key in the field above and click Save.\n"
                    "! You can get a key at: https://platform.openai.com/api-keys\n\n"
                    "! Without an API key, here are some manual hints:\n"
                    "! - ACL: access-list 100 deny ip 192.168.10.0 0.0.0.255 192.168.20.0 0.0.0.255\n"
                    "! - DHCP: ip dhcp pool VLAN10\\n  network 192.168.10.0 255.255.255.0\n"
                    "! - OSPF: router ospf 1\\n  network 0.0.0.0 255.255.255.255 area 0\n"
                    "! - SSH: ip ssh version 2\\n  line vty 0 4\\n  transport input ssh"
                )
                return

            btn_gen.configure(text="Generating…", state="disabled")

            def _worker():
                try:
                    import urllib.request
                    import json as _json
                    system_msg = (
                        "You are a Cisco IOS network configuration expert. "
                        "When the user describes a network configuration task, "
                        "respond ONLY with the exact IOS CLI commands (no explanations, "
                        "no markdown, just the raw commands). "
                        "Use 'configure terminal' and 'end' to wrap the config block."
                    )
                    body = _json.dumps({
                        "model": "gpt-3.5-turbo",
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 512,
                        "temperature": 0.2,
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        "https://api.openai.com/v1/chat/completions",
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {api_key}",
                        },
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        result = _json.loads(resp.read().decode("utf-8"))
                    text = result["choices"][0]["message"]["content"].strip()
                    win.after(0, lambda: _set_output(text))
                    win.after(0, lambda: btn_gen.configure(
                        text="Generate", state="normal"
                    ))
                except Exception as exc:
                    err = f"! API error: {exc}\n! Check your API key and internet connection."
                    win.after(0, lambda: _set_output(err))
                    win.after(0, lambda: btn_gen.configure(
                        text="Generate", state="normal"
                    ))

            threading.Thread(target=_worker, daemon=True).start()

        def _insert_into_preview():
            content = txt_output.get("1.0", "end").strip()
            if not content or content.startswith("!"):
                lines = [l for l in content.splitlines() if not l.strip().startswith("!")]
                content = "\n".join(lines).strip()
            if content:
                self.preview.insert("end", "\n" + content + "\n")
                self.log("[ai] inserted AI-generated config into preview")

        btn_row = tk.Frame(win, bg=t["bg"])
        btn_row.pack(fill="x", padx=16, pady=(0, 12))
        btn_gen = tk.Button(
            btn_row, text="Generate",
            command=_generate,
            bg=t["accent"], fg="white", relief="flat",
            font=("TkDefaultFont", 11, "bold"), padx=20, pady=6, cursor="hand2"
        )
        btn_gen.pack(side="left")
        tk.Button(
            btn_row, text="Insert into Preview",
            command=_insert_into_preview,
            bg="#238636", fg="white", relief="flat",
            font=("TkDefaultFont", 10), padx=16, pady=6, cursor="hand2"
        ).pack(side="left", padx=8)
        tk.Button(
            btn_row, text="Close", command=win.destroy,
            bg=t["card"], fg=t["muted"], relief="flat",
            font=("TkDefaultFont", 10), padx=16, pady=6, cursor="hand2"
        ).pack(side="right")

    # ─────────────────────────────────────────────────────────────────────────

    # ------------------- GNS3 integration -------------------
    def refresh_gns3_connection(self):
        """Refresh GNS3 connection and detect newly opened projects"""
        self._set_gns3_status("⏳ Reconnecting…", connected=False)
        threading.Thread(target=self._auto_connect_gns3, daemon=True).start()
    
    def _set_gns3_status(self, text: str, connected: bool = False,
                         project_name: str = ""):
        """Thread-safe helper to update the GNS3 status badge and project name label."""
        def _update():
            try:
                if connected:
                    self.lbl_gns3_status.configure(
                        text=text, text_color="#085D3A", fg_color="#ECFDF3")
                else:
                    self.lbl_gns3_status.configure(
                        text=text, text_color="#9BA3AF", fg_color="#28313E")
            except Exception:
                pass
            try:
                if project_name:
                    self.lbl_gns3_project_name.configure(
                        text=project_name, text_color="#C9D1D9")
                elif not connected:
                    self.lbl_gns3_project_name.configure(
                        text="No project", text_color="#8B949E")
            except Exception:
                pass
        self.after(0, _update)

    def _auto_connect_gns3(self):
        """Background thread: connect to GNS3 and import nodes.
        All UI mutations go through self.after() — never touch widgets directly."""
        if requests is None:
            self._set_gns3_status("requests not installed; GNS3 disabled")
            return
        try:
            g = GNS3Connector(GNS3_DEFAULT_URL)
            projs = g.get_projects()
            if not projs:
                self._set_gns3_status("No GNS3 projects found on server")
                return

            proj = None
            for p in projs:
                if p.get('is_open') or p.get('status') == 'opened':
                    proj = p
                    break
            if not proj:
                try:
                    proj = sorted(projs, key=lambda x: x.get('name', ''), reverse=True)[0]
                except Exception:
                    proj = projs[0]

            current_project_id = proj.get('project_id') or proj.get('projectId') or proj.get('id')
            if self.last_gns3_project:
                last_id = (self.last_gns3_project.get('project_id')
                           or self.last_gns3_project.get('projectId')
                           or self.last_gns3_project.get('id'))
                if current_project_id != last_id:
                    self.log(f"[gns3] project change: {self.last_gns3_project.get('name')} → {proj.get('name')}")

            # Store state (non-UI — safe from background thread)
            self.gns3 = g
            self.last_gns3_project = proj

            project_id = proj.get('project_id') or proj.get('projectId') or proj.get('id')
            self.gns3_project_id = project_id

            if not project_id:
                self._set_gns3_status("GNS3 project missing project_id")
                return

            nodes = self.gns3.get_nodes(project_id)

            # ── classify nodes (pure data work, no UI) ─────────────────────
            _SKIP_TYPES = {"vpcs", "cloud", "nat", "ethernet_switch",
                           "ethernet_hub", "frame_relay_switch", "atm_switch"}
            l3_keywords   = ['l3 switch', 'layer3', 'layer 3', 'esw', 'c3640',
                             'c3560', 'c3750', 'multilayer']
            rtr_keywords  = ['router', 'ios', 'csr', 'isr', 'iosv', 'firepower',
                             'asa', 'xrv', 'nxos', 'c2691', 'c2600', 'c7200',
                             'c3725', 'c3745', 'c3660', 'c3845', 'c1900', 'c2900',
                             'adventerprisek9', 'advipservices']

            new_devices = []
            for node in nodes:
                raw_type = node.get('node_type', '')
                if raw_type.lower() in _SKIP_TYPES:
                    self.log(f"[gns3] skipping: {node.get('name')} ({raw_type})")
                    continue

                name         = node.get('name') or f"node-{str(node.get('node_id','') or node.get('id',''))[:6]}"
                console_host = node.get('console_host') or 'localhost'
                console_port = node.get('console') or node.get('console_port') or ''
                node_id      = node.get('node_id') or node.get('id')
                platform     = node.get('platform', '')
                console_type = node.get('console_type', '')
                image_name   = (node.get('properties') or {}).get('image', '')

                full_desc = " ".join([raw_type, platform, console_type,
                                      image_name, name]).lower()

                if any(k in full_desc for k in l3_keywords):
                    ntype = 'core switch'
                elif any(k in full_desc for k in rtr_keywords):
                    ntype = 'router'
                else:
                    ntype = 'switch'

                # Fetch interfaces (network call — still on background thread)
                interfaces = []
                try:
                    ports_data = self.gns3.get_node_ports(project_id, node_id)
                    interfaces = [p["name"] for p in ports_data if p.get("name")]
                except Exception:
                    pass

                new_devices.append({
                    "name": name, "ntype": ntype, "node_id": node_id,
                    "console_host": console_host, "console_port": str(console_port),
                    "project_id": project_id, "interfaces": interfaces,
                })

            # ── hand off to main thread for all UI + DB writes ──────────────
            proj_name = proj.get('name', '')
            self.after(0, lambda nd=new_devices, pn=proj_name:
                       self._apply_gns3_import(nd, pn))

        except Exception as exc:
            self._set_gns3_status(f"GNS3 auto-connect failed: {exc}")

    def _apply_gns3_import(self, new_devices: list, proj_name: str):
        """Main-thread callback: add GNS3 nodes to the workspace and update UI."""
        imported = 0
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        project_id = self.gns3_project_id if hasattr(self, 'gns3_project_id') else ""

        for d in new_devices:
            name      = d["name"]
            node_id   = d["node_id"]
            already   = any(
                x[2].get("node_id") == node_id
                and x[2].get("project_id") == project_id
                for x in self.devices
            )
            if already:
                continue

            dev_name = name
            i = 1
            while any(x[0] == dev_name for x in self.devices):
                dev_name = f"{name}-{i}"; i += 1

            meta = {
                "gns3_node": True, "project_id": project_id,
                "node_id": node_id, "console_host": d["console_host"],
                "console_port": d["console_port"], "interfaces": d["interfaces"],
            }
            self.add_device_instance(d["ntype"], dev_name, metadata=meta)

            try:
                with db_lock:
                    cur.execute(
                        "INSERT OR REPLACE INTO devices "
                        "(name,type,ip,port,connection_type,added_from_gns3,"
                        "project_id,node_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (dev_name, d["ntype"], d["console_host"],
                         d["console_port"], 'gns3-console', 1,
                         project_id, node_id, ts)
                    )
                    conn.commit()
                imported += 1
            except Exception as exc:
                self.log(f"[db] error saving GNS3 device: {exc}")

        if imported > 0:
            self.refresh_device_list()
            self.log(f"Auto-imported {imported} GNS3 node(s) from '{proj_name}'")

        self._set_gns3_status(
            "✓ Connected",
            connected=True,
            project_name=proj_name or "Unknown project",
        )

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
            proj_name = project.get('name', '')
            self._set_gns3_status("✓ Connected", connected=True,
                                  project_name=proj_name or "Unknown project")
            messagebox.showinfo("gns3", f"selected {proj_name}")
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
        _SKIP_TYPES = {"vpcs", "cloud", "nat", "ethernet_switch", "ethernet_hub",
                       "frame_relay_switch", "atm_switch"}
        nodes = [n for n in nodes if n.get('node_type', '').lower() not in _SKIP_TYPES]
        if not nodes:
            messagebox.showinfo("GNS3", "No configurable network devices found in this project.\n(PCs, clouds, and hubs are excluded.)")
            return
        labels = []
        for i,n in enumerate(nodes):
            ch = f"{i+1}. {n.get('name')}  ({n.get('node_type')})  console:{n.get('console_host','localhost')}:{n.get('console') or n.get('console_port') or ''}"
            labels.append(ch)
        sel = simpledialog.askinteger("select node", "\n".join(labels) + "\n\nenter number to import:", parent=self, minvalue=1, maxvalue=len(labels))
        if not sel: return
        node = nodes[sel-1]
        node_id = node.get("node_id") or node.get("id")
        
        # If already in workspace, skip
        already_in_workspace = any(
            d[2].get("node_id") == node_id and d[2].get("project_id") == project_id
            for d in self.devices
        )
        if already_in_workspace:
            messagebox.showinfo("Already in workspace", "This device is already in the workspace.")
            return
        # If in DB but not workspace, load from DB and add to workspace
        try:
            cur.execute("SELECT name, type, ip, port FROM devices WHERE node_id=? AND project_id=?", (node_id, project_id))
            existing = cur.fetchone()
            if existing:
                dev_name, dtype, console_host, console_port = existing
                dtype = (dtype or "router").strip().lower()
                # Map class names (RouterModel) to keys
                type_map = {"routermodel": "router", "switchmodel": "switch", "coreswitchmodel": "core switch"}
                dtype = type_map.get(dtype, dtype)
                if dtype not in self.device_types:
                    dtype = "router"
                meta = {"gns3_node": True, "project_id": project_id, "node_id": node_id, "console_host": console_host or "localhost", "console_port": str(console_port or "")}
                try:
                    ports_data = self.gns3.get_node_ports(project_id, node_id)
                    meta["interfaces"] = [p["name"] for p in ports_data if p.get("name")]
                except Exception:
                    meta["interfaces"] = []
                base = dev_name; name = base; i = 1
                while any(d[0] == name for d in self.devices):
                    name = f"{base}-{i}"; i += 1
                self.add_device_instance(dtype, name, metadata=meta)
                self.refresh_device_list()
                messagebox.showinfo("gns3", f"Added '{name}' to workspace (was in database)")
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
        try:
            ports_data = self.gns3.get_node_ports(project_id, node_id)
            meta["interfaces"] = [p["name"] for p in ports_data if p.get("name")]
        except Exception:
            meta["interfaces"] = []
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
        apply_responsive_geometry(win, 700, 420)
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

