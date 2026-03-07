"""
Real-time device health monitor.

Connects to a device via Telnet, runs a role-appropriate set of show commands,
and presents the results as a user-friendly health dashboard — not raw CLI output.

Commands per role
-----------------
Router      : show version | show ip interface brief | show ip dhcp binding
Core Switch : show version | show ip interface brief | show vlan-switch | show vlan brief
Access Sw   : show version | show vlan-switch | show vlan brief

VLAN note: both 'show vlan-switch' (old IOU/ESW images) and 'show vlan brief'
(modern images) are run. Whichever returns a valid table is displayed; the other
is silently discarded.
"""
import tkinter as tk
import threading
import asyncio
import queue
import re
import time

try:
    import telnetlib3
except Exception:
    telnetlib3 = None

# ── Human-readable labels for each show command ────────────────────────────────
_CMD_LABELS = {
    "show version":           "Device Info",
    "show ip interface brief": "Network Interfaces",
    "show vlan-switch":        "VLAN Membership",
    "show vlan brief":         "VLAN Membership",
    "show ip dhcp binding":    "Active DHCP Leases",
}


def _is_invalid(raw: str) -> bool:
    """Return True if the device rejected the command (old IOS 'Invalid input')."""
    return bool(re.search(r"(Invalid input|% Invalid|% Incomplete|% Ambiguous)", raw, re.IGNORECASE))


class DeviceMonitor(tk.Toplevel):
    COLORS = {
        "bg":      "#0D1117",
        "card":    "#1F2630",
        "sidebar": "#161B22",
        "text":    "#C9D1D9",
        "muted":   "#8B949E",
        "success": "#3FB950",
        "danger":  "#F85149",
        "warn":    "#D29922",
        "border":  "#30363D",
        "accent":  "#58A6FF",
    }

    def __init__(self, parent, devices: list):
        super().__init__(parent)
        self.title("Device Monitor")
        self.geometry("900x580")
        self.minsize(680, 420)
        self.resizable(True, True)
        self.configure(bg=self.COLORS["bg"])

        self.devices = [
            d for d in devices
            if d[2].get("console_host") or d[2].get("ip")
        ]
        self._selected_idx = 0
        self._poll_timer = None
        self._result_queue = queue.Queue()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self.devices:
            self._show_placeholder("No devices with connection info found.\nImport GNS3 devices first.")

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        t = self.COLORS

        hdr = tk.Frame(self, bg=t["card"], pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="  Device Monitor",
            font=("Segoe UI", 14, "bold"), fg=t["text"], bg=t["card"]
        ).pack(side="left")

        self.lbl_status = tk.Label(
            hdr, text="idle", fg=t["muted"], bg=t["card"], font=("Segoe UI", 10)
        )
        self.lbl_status.pack(side="right", padx=16)

        self.auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            hdr, text="Auto-poll every 30s",
            variable=self.auto_var,
            fg=t["text"], bg=t["card"],
            selectcolor=t["sidebar"],
            activebackground=t["card"],
            activeforeground=t["text"],
            font=("Segoe UI", 10),
            command=self._toggle_auto
        ).pack(side="right", padx=(0, 12))

        body = tk.Frame(self, bg=t["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=8)

        # Left: device list
        left = tk.Frame(body, bg=t["sidebar"], width=200)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)

        tk.Label(
            left, text="  Devices",
            font=("Segoe UI", 11, "bold"), fg=t["text"], bg=t["sidebar"]
        ).pack(anchor="w", pady=(12, 6))

        self.device_listbox = tk.Listbox(
            left, bg=t["card"], fg=t["text"],
            selectbackground=t["accent"], selectforeground="#ffffff",
            borderwidth=0, highlightthickness=0,
            font=("Segoe UI", 10), activestyle="none",
        )
        self.device_listbox.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        for name, _, __ in self.devices:
            self.device_listbox.insert("end", f"  {name}")

        if self.devices:
            self.device_listbox.selection_set(0)

        tk.Button(
            left, text="Poll Now",
            command=self._poll_selected,
            bg=t["accent"], fg="white", relief="flat",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2", padx=8, pady=6,
        ).pack(fill="x", padx=6, pady=(0, 8))

        self.device_listbox.bind("<<ListboxSelect>>", self._on_device_select)

        # Right: results
        right = tk.Frame(body, bg=t["bg"])
        right.pack(side="left", fill="both", expand=True)

        self.lbl_device_header = tk.Label(
            right, text="Select a device and click Poll Now",
            font=("Segoe UI", 12, "bold"), fg=t["muted"], bg=t["bg"]
        )
        self.lbl_device_header.pack(anchor="w", pady=(0, 6))

        outer = tk.Frame(right, bg=t["bg"])
        outer.pack(fill="both", expand=True)

        self.results_canvas = tk.Canvas(outer, bg=t["bg"], highlightthickness=0)
        vsb = tk.Scrollbar(outer, orient="vertical", command=self.results_canvas.yview)
        self.results_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.results_canvas.pack(side="left", fill="both", expand=True)

        self.results_inner = tk.Frame(self.results_canvas, bg=t["bg"])
        self._cwin = self.results_canvas.create_window((0, 0), window=self.results_inner, anchor="nw")

        self.results_inner.bind(
            "<Configure>",
            lambda e: self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all"))
        )
        self.results_canvas.bind(
            "<Configure>",
            lambda e: self.results_canvas.itemconfig(self._cwin, width=e.width)
        )

        self._show_placeholder("Select a device and click Poll Now.")

    # ── Device selection ───────────────────────────────────────────────────────

    def _on_device_select(self, _event=None):
        sel = self.device_listbox.curselection()
        if sel:
            self._selected_idx = sel[0]
            name = self.devices[sel[0]][0]
            self.lbl_device_header.configure(text=f"  {name}", fg=self.COLORS["text"])

    # ── Polling ────────────────────────────────────────────────────────────────

    def _poll_selected(self):
        if not self.devices:
            return

        sel = self.device_listbox.curselection()
        idx = sel[0] if sel else self._selected_idx
        if idx >= len(self.devices):
            return

        name, model, meta = self.devices[idx]
        host = meta.get("console_host") or meta.get("ip", "")
        port_raw = meta.get("console_port") or meta.get("port", "")

        if not host:
            self._clear_results()
            self._show_error(f"No host configured for '{name}'.")
            return

        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            self._clear_results()
            self._show_error(f"Invalid port '{port_raw}' for '{name}'.")
            return

        self.lbl_status.configure(text=f"polling {name}...", fg=self.COLORS["warn"])
        self.lbl_device_header.configure(text=f"  {name}", fg=self.COLORS["text"])

        # Build command list based on device role
        try:
            from ..models.devices import CoreSwitchModel, SwitchModel, RouterModel
            is_router = isinstance(model, RouterModel)
            is_switch = isinstance(model, (CoreSwitchModel, SwitchModel))
        except Exception:
            is_router = False
            is_switch = False

        cmds = ["show version", "show ip interface brief"]

        if is_router:
            cmds.append("show ip dhcp binding")
        elif is_switch:
            # Run both; the renderer will discard whichever is invalid for this image
            cmds.append("show vlan-switch")
            cmds.append("show vlan brief")
        else:
            # Unknown role — try both VLAN commands
            cmds.append("show vlan-switch")
            cmds.append("show vlan brief")

        threading.Thread(
            target=self._run_poll,
            args=(name, host, port, cmds),
            daemon=True
        ).start()

    def _run_poll(self, name: str, host: str, port: int, cmds: list):
        if telnetlib3 is None:
            self._result_queue.put(("error", name, "telnetlib3 not installed"))
            self.after(0, self._process_queue)
            return
        try:
            results = asyncio.run(self._poll_async(host, port, cmds))
            self._result_queue.put(("ok", name, results))
        except Exception as exc:
            self._result_queue.put(("error", name, str(exc)))
        self.after(0, self._process_queue)

    async def _poll_async(self, host: str, port: int, cmds: list) -> dict:
        reader, writer = await asyncio.wait_for(
            telnetlib3.open_connection(host, port), timeout=10
        )

        async def read_prompt(timeout_sec=3.0):
            buf = ""
            deadline = asyncio.get_event_loop().time() + timeout_sec
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=0.4)
                    if chunk:
                        buf += chunk
                        stripped = buf.rstrip()
                        if stripped and stripped[-1] in (">", "#"):
                            break
                except asyncio.TimeoutError:
                    break
            return buf

        results = {}
        try:
            await read_prompt(3.0)
            writer.write("terminal length 0\r\n")
            await asyncio.sleep(0.2)
            await read_prompt(2.0)

            for cmd in cmds:
                writer.write(cmd + "\r\n")
                await asyncio.sleep(0.2)
                output = await read_prompt(5.0)
                results[cmd] = output

            writer.close()
        except Exception as exc:
            try:
                writer.close()
            except Exception:
                pass
            results["_error"] = str(exc)
        return results

    # ── Result processing ──────────────────────────────────────────────────────

    def _process_queue(self):
        while not self._result_queue.empty():
            kind, name, data = self._result_queue.get()
            ts = time.strftime("%H:%M:%S")

            self._clear_results()

            if kind == "error":
                self.lbl_status.configure(text=f"error at {ts}", fg=self.COLORS["danger"])
                self._show_error(f"Could not connect to '{name}':\n{data}")
                return

            self.lbl_status.configure(text=f"last updated: {ts}", fg=self.COLORS["success"])

            if "_error" in data:
                self._show_error(f"Connection error: {data['_error']}")
                return

            # Remove VLAN duplicate: keep show vlan-switch if valid, else show vlan brief
            vlan_switch_raw = data.get("show vlan-switch", "")
            vlan_brief_raw  = data.get("show vlan brief", "")
            vlan_raw        = ""
            vlan_cmd_used   = ""

            if vlan_switch_raw and not _is_invalid(vlan_switch_raw):
                vlan_raw = vlan_switch_raw
                vlan_cmd_used = "show vlan-switch"
            elif vlan_brief_raw and not _is_invalid(vlan_brief_raw):
                vlan_raw = vlan_brief_raw
                vlan_cmd_used = "show vlan brief"

            # Build ordered render plan (skip raw VLAN entries — handled above)
            render_plan = []
            for cmd in ["show version", "show ip interface brief",
                        "show ip dhcp binding"]:
                if cmd in data:
                    render_plan.append((cmd, data[cmd]))
            if vlan_raw:
                render_plan.append((vlan_cmd_used, vlan_raw))

            # ── Health Summary card ──
            self._render_health_summary(name, data, vlan_raw)

            # ── Per-command sections ──
            for cmd, raw in render_plan:
                if _is_invalid(raw) and "version" not in cmd:
                    continue  # silently skip commands the device rejected

                label = _CMD_LABELS.get(cmd, cmd)
                self._render_section_header(label)

                if cmd == "show version":
                    self._render_version_info(raw)
                elif cmd == "show ip interface brief":
                    self._render_interface_table(raw)
                elif cmd == "show ip dhcp binding":
                    self._render_dhcp_table(raw)
                elif "vlan" in cmd:
                    self._render_vlan_table(raw)

    # ── Renderers ──────────────────────────────────────────────────────────────

    def _render_health_summary(self, device_name: str, data: dict, vlan_raw: str):
        """Top-level at-a-glance health card."""
        t = self.COLORS

        # Parse interface up/down counts
        iface_raw = data.get("show ip interface brief", "")
        up_count = down_count = 0
        iface_re = re.compile(r"^(\S+)\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)", re.IGNORECASE)
        for line in iface_raw.splitlines():
            m = iface_re.match(line.strip())
            if m and m.group(1).lower() not in ("interface",):
                if m.group(2).lower() == "up":
                    up_count += 1
                else:
                    down_count += 1

        # Parse active VLAN count
        vlan_count = 0
        if vlan_raw:
            vlan_re = re.compile(r"^\d+\s+\S+\s+active", re.IGNORECASE)
            for line in vlan_raw.splitlines():
                if vlan_re.match(line.strip()):
                    vlan_count += 1

        # Parse DHCP lease count
        dhcp_raw = data.get("show ip dhcp binding", "")
        dhcp_count = 0
        ip_re = re.compile(r"^\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+\S")
        if dhcp_raw and not _is_invalid(dhcp_raw):
            for line in dhcp_raw.splitlines():
                if ip_re.match(line) and "IP address" not in line:
                    dhcp_count += 1

        # Extract short device info from show version
        ver_raw = data.get("show version", "")
        ios_ver = ""
        uptime  = ""
        if ver_raw:
            vm = re.search(r"Version\s+([\d\.\(\)A-Za-z]+)", ver_raw)
            if vm:
                ios_ver = f"IOS {vm.group(1)}"
            um = re.search(r"uptime is (.+)", ver_raw, re.IGNORECASE)
            if um:
                uptime = um.group(1).strip().rstrip(".")

        card = tk.Frame(self.results_inner, bg=t["card"], pady=12)
        card.pack(fill="x", padx=4, pady=(4, 12))

        # Row 1: device name + IOS version + uptime
        top_row = tk.Frame(card, bg=t["card"])
        top_row.pack(fill="x", padx=16)
        tk.Label(
            top_row, text=device_name,
            font=("Segoe UI", 13, "bold"), fg=t["text"], bg=t["card"]
        ).pack(side="left")
        if ios_ver:
            tk.Label(
                top_row, text=f"   {ios_ver}",
                font=("Segoe UI", 10), fg=t["muted"], bg=t["card"]
            ).pack(side="left")
        if uptime:
            tk.Label(
                top_row, text=f"   ⏱ {uptime}",
                font=("Segoe UI", 10), fg=t["muted"], bg=t["card"]
            ).pack(side="left")

        # Row 2: stat badges
        badge_row = tk.Frame(card, bg=t["card"])
        badge_row.pack(fill="x", padx=16, pady=(10, 4))

        def _badge(parent, label, value, color):
            f = tk.Frame(parent, bg=t["sidebar"], padx=12, pady=6)
            f.pack(side="left", padx=(0, 8))
            tk.Label(f, text=str(value), font=("Segoe UI", 16, "bold"),
                     fg=color, bg=t["sidebar"]).pack()
            tk.Label(f, text=label, font=("Segoe UI", 8),
                     fg=t["muted"], bg=t["sidebar"]).pack()

        if up_count or down_count:
            _badge(badge_row, "Interfaces Up",   up_count,   t["success"] if up_count else t["muted"])
            _badge(badge_row, "Interfaces Down",  down_count, t["danger"]  if down_count else t["muted"])

        if vlan_count:
            _badge(badge_row, "VLANs Active", vlan_count, t["accent"])

        if dhcp_count:
            _badge(badge_row, "DHCP Leases", dhcp_count, t["warn"])

        if not (up_count or down_count or vlan_count or dhcp_count):
            tk.Label(
                badge_row, text="No summary data available for this device.",
                font=("Segoe UI", 10), fg=t["muted"], bg=t["card"]
            ).pack(side="left")

    def _render_section_header(self, label: str):
        t = self.COLORS
        hf = tk.Frame(self.results_inner, bg=t["sidebar"], pady=7)
        hf.pack(fill="x", pady=(8, 4))
        tk.Label(
            hf, text=f"  {label}",
            font=("Segoe UI", 11, "bold"), fg=t["text"], bg=t["sidebar"]
        ).pack(side="left", padx=8)

    def _render_version_info(self, raw: str):
        """One-line device info strip: hardware model, IOS version, uptime."""
        t = self.COLORS
        if _is_invalid(raw):
            return

        hardware = ios_ver = uptime = ""

        vm = re.search(r"Version\s+([\d\.\(\)A-Za-z]+)", raw)
        if vm:
            ios_ver = vm.group(1)

        um = re.search(r"uptime is (.+)", raw, re.IGNORECASE)
        if um:
            uptime = um.group(1).strip().rstrip(".")

        # Hardware: first line containing "cisco" followed by model
        hm = re.search(r"[Cc]isco\s+([\w\-]+[^\n,]*)", raw)
        if hm:
            hardware = hm.group(1).strip()[:40]

        row = tk.Frame(self.results_inner, bg=t["card"], pady=8)
        row.pack(fill="x", padx=4, pady=2)

        cols = []
        if hardware:
            cols.append(("Hardware", hardware))
        if ios_ver:
            cols.append(("IOS Version", ios_ver))
        if uptime:
            cols.append(("Uptime", uptime))

        if not cols:
            tk.Label(row, text=raw[:200], fg=t["muted"], bg=t["card"],
                     font=("Courier New", 9), wraplength=600, justify="left").pack(anchor="w", padx=12)
            return

        for label, value in cols:
            cell = tk.Frame(row, bg=t["card"])
            cell.pack(side="left", padx=16)
            tk.Label(cell, text=label, font=("Segoe UI", 8), fg=t["muted"],
                     bg=t["card"]).pack(anchor="w")
            tk.Label(cell, text=value, font=("Segoe UI", 10, "bold"), fg=t["text"],
                     bg=t["card"]).pack(anchor="w")

    def _render_interface_table(self, raw: str):
        t = self.COLORS
        lines = [l for l in raw.splitlines() if l.strip()]
        header_idx = next(
            (i for i, l in enumerate(lines) if "Interface" in l and "Status" in l), None
        )
        if header_idx is None:
            tk.Label(
                self.results_inner, text=raw[:500], fg=t["muted"], bg=t["bg"],
                font=("Courier New", 10), justify="left", wraplength=540
            ).pack(anchor="w", padx=8)
            return

        # Table header row
        hf = tk.Frame(self.results_inner, bg=t["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("  ", 2), ("Interface", 24), ("IP Address", 18),
                       ("Line Status", 12), ("Protocol", 12)]:
            tk.Label(hf, text=col, fg=t["muted"], bg=t["sidebar"],
                     font=("Segoe UI", 9, "bold"), width=w, anchor="w").pack(side="left")

        iface_re = re.compile(
            r"^(\S+)\s+(\S+)\s+\S+\s+\S+\s+(\S+)\s+(\S+)", re.IGNORECASE
        )
        for line in lines[header_idx + 1:]:
            m = iface_re.match(line.strip())
            if not m:
                continue
            iface, ip, status, protocol = m.groups()
            is_up = protocol.lower() == "up"
            row_bg  = t["card"] if is_up else "#2a1a1a"
            dot_col = t["success"] if is_up else t["danger"]

            rf = tk.Frame(self.results_inner, bg=row_bg)
            rf.pack(fill="x", pady=1, padx=4)
            tk.Label(rf, text="●", fg=dot_col, bg=row_bg,
                     font=("Segoe UI", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(iface, 22), (ip, 18), (status, 12), (protocol, 12)]:
                tk.Label(rf, text=val, fg=t["text"], bg=row_bg,
                         font=("Courier New", 10), width=w, anchor="w").pack(side="left")

    def _render_vlan_table(self, raw: str):
        """Render VLAN table — works for both 'show vlan-switch' and 'show vlan brief'."""
        t = self.COLORS

        if _is_invalid(raw):
            tk.Label(
                self.results_inner,
                text="This device does not support the VLAN show command.",
                fg=t["muted"], bg=t["bg"], font=("Segoe UI", 10)
            ).pack(anchor="w", padx=8, pady=6)
            return

        lines = [l for l in raw.splitlines() if l.strip()]
        header_idx = next(
            (i for i, l in enumerate(lines) if "VLAN" in l and "Name" in l), None
        )
        if header_idx is None:
            tk.Label(
                self.results_inner, text=raw[:500], fg=t["muted"], bg=t["bg"],
                font=("Courier New", 10), justify="left", wraplength=540
            ).pack(anchor="w", padx=8)
            return

        hf = tk.Frame(self.results_inner, bg=t["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("  ", 2), ("VLAN ID", 10), ("Name", 26), ("Status", 12)]:
            tk.Label(hf, text=col, fg=t["muted"], bg=t["sidebar"],
                     font=("Segoe UI", 9, "bold"), width=w, anchor="w").pack(side="left")

        vlan_re = re.compile(r"^(\d+)\s+(\S+)\s+(\S+)", re.IGNORECASE)
        found = 0
        for line in lines[header_idx + 1:]:
            m = vlan_re.match(line.strip())
            if not m:
                continue
            vid, vname, status = m.groups()
            is_active = "active" in status.lower()
            row_bg  = t["card"] if is_active else "#2a1a1a"
            dot_col = t["success"] if is_active else t["warn"]

            rf = tk.Frame(self.results_inner, bg=row_bg)
            rf.pack(fill="x", pady=1, padx=4)
            tk.Label(rf, text="●", fg=dot_col, bg=row_bg,
                     font=("Segoe UI", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(vid, 8), (vname, 24), (status, 12)]:
                tk.Label(rf, text=val, fg=t["text"], bg=row_bg,
                         font=("Courier New", 10), width=w, anchor="w").pack(side="left")
            found += 1

        if found == 0:
            tk.Label(
                self.results_inner, text="No VLANs found.",
                fg=t["muted"], bg=t["bg"], font=("Segoe UI", 10)
            ).pack(anchor="w", padx=8, pady=4)

    def _render_dhcp_table(self, raw: str):
        """Parse and render 'show ip dhcp binding' leases."""
        t = self.COLORS

        if _is_invalid(raw):
            return

        lines = [l for l in raw.splitlines() if l.strip()]

        # Find header line
        header_idx = next(
            (i for i, l in enumerate(lines)
             if "IP address" in l or "IP Address" in l), None
        )

        # Parse IP binding rows
        ip_re  = re.compile(
            r"^\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+"   # IP
            r"(\S+)\s+"                                          # Client-ID/Hardware
            r"(\w{3}\s+\d+\s+\d{4}[^\s]*\s+\d+:\d+\s*\w*)",   # Expiry
            re.IGNORECASE
        )
        # Simpler fallback: just any line starting with an IP
        ip_simple = re.compile(r"^\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\S+)")

        rows = []
        start = (header_idx + 1) if header_idx is not None else 0
        for line in lines[start:]:
            m = ip_re.match(line)
            if m:
                rows.append((m.group(1), m.group(2), m.group(3).strip()))
                continue
            ms = ip_simple.match(line)
            if ms and ms.group(1) not in ("0.0.0.0",):
                rows.append((ms.group(1), ms.group(2), "—"))

        if not rows:
            tk.Label(
                self.results_inner,
                text="No active DHCP leases.  (Devices will appear here once they request an IP.)",
                fg=t["muted"], bg=t["bg"], font=("Segoe UI", 10), wraplength=560
            ).pack(anchor="w", padx=8, pady=6)
            return

        # Table header
        hf = tk.Frame(self.results_inner, bg=t["sidebar"])
        hf.pack(fill="x", pady=(0, 2), padx=4)
        for col, w in [("  ", 2), ("IP Address", 18), ("MAC / Client ID", 26), ("Lease Expires", 20)]:
            tk.Label(hf, text=col, fg=t["muted"], bg=t["sidebar"],
                     font=("Segoe UI", 9, "bold"), width=w, anchor="w").pack(side="left")

        for ip, client, expires in rows:
            rf = tk.Frame(self.results_inner, bg=t["card"])
            rf.pack(fill="x", pady=1, padx=4)
            tk.Label(rf, text="●", fg=t["success"], bg=t["card"],
                     font=("Segoe UI", 9)).pack(side="left", padx=(6, 0))
            for val, w in [(ip, 16), (client, 24), (expires, 20)]:
                tk.Label(rf, text=val, fg=t["text"], bg=t["card"],
                         font=("Courier New", 10), width=w, anchor="w").pack(side="left")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _show_placeholder(self, msg: str):
        self._clear_results()
        tk.Label(
            self.results_inner, text=msg, fg=self.COLORS["muted"], bg=self.COLORS["bg"],
            font=("Segoe UI", 11), justify="center"
        ).pack(expand=True, pady=40)

    def _show_error(self, msg: str):
        tk.Label(
            self.results_inner, text=msg, fg=self.COLORS["danger"], bg=self.COLORS["bg"],
            font=("Segoe UI", 10), wraplength=580, justify="left"
        ).pack(anchor="w", padx=8, pady=8)

    def _clear_results(self):
        for w in self.results_inner.winfo_children():
            w.destroy()

    # ── Auto-poll ──────────────────────────────────────────────────────────────

    def _toggle_auto(self):
        if self.auto_var.get():
            self._poll_selected()
            self._poll_timer = self.after(30000, self._auto_poll_tick)
        else:
            if self._poll_timer:
                self.after_cancel(self._poll_timer)
                self._poll_timer = None

    def _auto_poll_tick(self):
        if self.auto_var.get():
            self._poll_selected()
            self._poll_timer = self.after(30000, self._auto_poll_tick)

    def _on_close(self):
        if self._poll_timer:
            try:
                self.after_cancel(self._poll_timer)
            except Exception:
                pass
        self.destroy()
