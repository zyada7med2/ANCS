"""
Interactive CLI terminal panel.

Maintains a persistent Telnet session with a network device so the user
can type raw CLI commands and see responses in real time — without leaving ANCS.

Supports:
  - Command history (Up/Down arrow keys)
  - Automatic 'terminal length 0' on connect
  - Connect / Disconnect / Reconnect
  - Clear output
"""
import tkinter as tk
import threading
import asyncio
import queue
import time

try:
    import telnetlib3
except Exception:
    telnetlib3 = None


class TerminalPanel(tk.Toplevel):
    COLORS = {
        "bg":       "#0D1117",
        "card":     "#1F2630",
        "sidebar":  "#161B22",
        "text":     "#C9D1D9",
        "muted":    "#8B949E",
        "success":  "#3FB950",
        "danger":   "#F85149",
        "warn":     "#D29922",
        "border":   "#30363D",
        "accent":   "#58A6FF",
        "input_bg": "#161B22",
    }

    def __init__(self, parent, device_name: str, host: str, port: int):
        super().__init__(parent)
        self.title(f"Terminal  —  {device_name}")
        self.geometry("740x500")
        self.minsize(540, 360)
        self.resizable(True, True)
        self.configure(bg=self.COLORS["bg"])

        self.device_name = device_name
        self.host = host
        self.port = port

        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_queue: asyncio.Queue | None = None
        self._resp_queue: queue.Queue = queue.Queue()
        self._poll_id = None
        self._thread = None
        self._cmd_history: list[str] = []
        self._history_idx: int = -1

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if telnetlib3 is None:
            self._append("  [error] telnetlib3 is not installed — cannot open terminal\n", "danger")
            self.btn_connect.configure(state="disabled")
        else:
            self.after(300, self._connect)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = self.COLORS

        # Header
        hdr = tk.Frame(self, bg=t["card"], pady=8)
        hdr.pack(fill="x")

        tk.Label(
            hdr, text=f"  {self.device_name}",
            font=("Segoe UI", 13, "bold"), fg=t["text"], bg=t["card"]
        ).pack(side="left")

        self.lbl_status = tk.Label(
            hdr, text="⬤ disconnected",
            fg=t["danger"], bg=t["card"], font=("Segoe UI", 10)
        )
        self.lbl_status.pack(side="left", padx=10)

        tk.Label(
            hdr, text=f"{self.host}:{self.port}  ",
            fg=t["muted"], bg=t["card"], font=("Segoe UI", 9)
        ).pack(side="right")

        tk.Button(
            hdr, text="Clear",
            bg=t["sidebar"], fg=t["muted"],
            relief="flat", padx=10, pady=4,
            font=("Segoe UI", 9), cursor="hand2",
            command=self._clear_output
        ).pack(side="right", padx=(0, 4))

        tk.Button(
            hdr, text="Disconnect",
            bg="#3a1818", fg=t["danger"],
            relief="flat", padx=10, pady=4,
            font=("Segoe UI", 9), cursor="hand2",
            command=self._disconnect
        ).pack(side="right", padx=(0, 4))

        self.btn_connect = tk.Button(
            hdr, text="Connect",
            bg="#183a18", fg=t["success"],
            relief="flat", padx=12, pady=4,
            font=("Segoe UI", 9, "bold"), cursor="hand2",
            command=self._connect
        )
        self.btn_connect.pack(side="right", padx=(0, 8))

        # Output text area
        out_frame = tk.Frame(self, bg=t["bg"])
        out_frame.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        self.txt_out = tk.Text(
            out_frame,
            bg=t["input_bg"], fg=t["text"],
            font=("Courier New", 11),
            relief="flat", borderwidth=0,
            insertbackground=t["text"],
            state="disabled", wrap="word",
        )
        vsb = tk.Scrollbar(out_frame, orient="vertical", command=self.txt_out.yview)
        self.txt_out.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.txt_out.pack(fill="both", expand=True)

        self.txt_out.tag_configure("success", foreground=t["success"])
        self.txt_out.tag_configure("danger",  foreground=t["danger"])
        self.txt_out.tag_configure("warn",    foreground=t["warn"])
        self.txt_out.tag_configure("muted",   foreground=t["muted"])
        self.txt_out.tag_configure("accent",  foreground=t["accent"])

        # Input row
        inp = tk.Frame(self, bg=t["card"], pady=8)
        inp.pack(fill="x", padx=8, pady=(0, 8))

        tk.Label(
            inp, text=">",
            fg=t["success"], bg=t["card"],
            font=("Courier New", 13, "bold")
        ).pack(side="left", padx=(8, 4))

        self.ent_cmd = tk.Entry(
            inp, bg=t["input_bg"], fg=t["text"],
            insertbackground=t["text"],
            relief="flat", font=("Courier New", 11), borderwidth=0,
        )
        self.ent_cmd.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.ent_cmd.bind("<Return>",  lambda _e: self._send_command())
        self.ent_cmd.bind("<Up>",      self._history_up)
        self.ent_cmd.bind("<Down>",    self._history_down)

        tk.Button(
            inp, text="Send",
            bg=t["accent"], fg="white",
            relief="flat", padx=16, pady=4,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            command=self._send_command
        ).pack(side="right", padx=(0, 8))

        self._append(
            f"Terminal ready — {self.device_name}  ({self.host}:{self.port})\n"
            "Connecting...\n\n",
            "muted"
        )

    # ── connection ────────────────────────────────────────────────────────────

    def _connect(self):
        if self._running:
            return
        self._running = True
        self.lbl_status.configure(text="⬤ connecting...", fg=self.COLORS["warn"])
        self.btn_connect.configure(state="disabled")
        self._append(f"Connecting to {self.host}:{self.port}...\n", "muted")
        self._thread = threading.Thread(target=self._telnet_loop, daemon=True)
        self._thread.start()
        self._schedule_poll()

    def _disconnect(self):
        self._running = False
        if self._loop and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        self.lbl_status.configure(text="⬤ disconnected", fg=self.COLORS["danger"])
        self.btn_connect.configure(state="normal", text="Reconnect")
        self._append("\nDisconnected.\n", "warn")

    def _telnet_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_session())
        except (RuntimeError, asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as exc:
            self._resp_queue.put(("error", str(exc)))
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
        self._running = False
        try:
            self.after(0, lambda: self.lbl_status.configure(
                text="⬤ disconnected", fg=self.COLORS["danger"]
            ))
            self.after(0, lambda: self.btn_connect.configure(
                state="normal", text="Reconnect"
            ))
        except Exception:
            pass

    async def _async_session(self):
        # Create async queue inside the running event loop
        self._async_queue = asyncio.Queue()

        try:
            reader, writer = await asyncio.wait_for(
                telnetlib3.open_connection(self.host, self.port), timeout=10
            )
        except Exception as exc:
            self._resp_queue.put(("error", f"Connection failed: {exc}"))
            return

        self._resp_queue.put(("connected", None))

        async def read_burst(max_wait: float = 1.5) -> str:
            buf = ""
            deadline = asyncio.get_event_loop().time() + max_wait
            while asyncio.get_event_loop().time() < deadline:
                remaining = max(0.05, deadline - asyncio.get_event_loop().time())
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=min(remaining, 0.3))
                    if chunk:
                        buf += chunk
                    else:
                        break
                except asyncio.TimeoutError:
                    break
            return buf

        # Read initial banner
        banner = await read_burst(2.0)
        if banner:
            self._resp_queue.put(("output", banner))

        # Disable paging
        writer.write("terminal length 0\r\n")
        await asyncio.sleep(0.3)
        await read_burst(1.0)  # discard

        while self._running:
            try:
                cmd = await asyncio.wait_for(self._async_queue.get(), timeout=0.5)
                writer.write(cmd + "\r\n")
                await asyncio.sleep(0.2)
                output = await read_burst(3.0)
                self._resp_queue.put(("output", output))
            except asyncio.TimeoutError:
                # Check for unsolicited data (e.g. syslog messages)
                try:
                    chunk = await asyncio.wait_for(reader.read(512), timeout=0.05)
                    if chunk:
                        self._resp_queue.put(("output", chunk))
                except asyncio.TimeoutError:
                    pass

        try:
            writer.write("exit\r\n")
            await asyncio.sleep(0.2)
            writer.close()
        except Exception:
            pass

    # ── command handling ──────────────────────────────────────────────────────

    def _send_command(self):
        cmd = self.ent_cmd.get().strip()
        if not cmd:
            return
        if not self._running or self._loop is None or self._loop.is_closed():
            self._append("[not connected — use Connect first]\n", "danger")
            return

        # Add to history
        if not self._cmd_history or self._cmd_history[-1] != cmd:
            self._cmd_history.append(cmd)
        self._history_idx = len(self._cmd_history)

        try:
            self._loop.call_soon_threadsafe(self._async_queue.put_nowait, cmd)
        except Exception:
            pass

        self.ent_cmd.delete(0, "end")
        self._append(f"\n> {cmd}\n", "accent")

    def _history_up(self, _event=None):
        if not self._cmd_history:
            return "break"
        self._history_idx = max(0, self._history_idx - 1)
        self.ent_cmd.delete(0, "end")
        self.ent_cmd.insert(0, self._cmd_history[self._history_idx])
        return "break"

    def _history_down(self, _event=None):
        if not self._cmd_history:
            return "break"
        self._history_idx = min(len(self._cmd_history), self._history_idx + 1)
        self.ent_cmd.delete(0, "end")
        if self._history_idx < len(self._cmd_history):
            self.ent_cmd.insert(0, self._cmd_history[self._history_idx])
        return "break"

    # ── response polling ──────────────────────────────────────────────────────

    def _schedule_poll(self):
        self._poll_id = self.after(100, self._poll_responses)

    def _poll_responses(self):
        try:
            while not self._resp_queue.empty():
                kind, data = self._resp_queue.get_nowait()
                if kind == "connected":
                    self.lbl_status.configure(
                        text="⬤ connected", fg=self.COLORS["success"]
                    )
                    self.btn_connect.configure(state="disabled")
                    self._append("Connected.\n\n", "success")
                elif kind == "output":
                    self._append(data)
                elif kind == "error":
                    self._append(f"\n[error] {data}\n", "danger")
        except Exception:
            pass

        if self._running or not self._resp_queue.empty():
            self._poll_id = self.after(100, self._poll_responses)

    # ── output helpers ────────────────────────────────────────────────────────

    def _append(self, text: str, tag: str | None = None):
        try:
            self.txt_out.configure(state="normal")
            if tag:
                self.txt_out.insert("end", text, tag)
            else:
                self.txt_out.insert("end", text)
            self.txt_out.see("end")
            self.txt_out.configure(state="disabled")
        except Exception:
            pass

    def _clear_output(self):
        try:
            self.txt_out.configure(state="normal")
            self.txt_out.delete("1.0", "end")
            self.txt_out.configure(state="disabled")
        except Exception:
            pass

    # ── cleanup ───────────────────────────────────────────────────────────────

    def _on_close(self):
        self._running = False
        if self._poll_id:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
        if self._loop and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        try:
            self.destroy()
        except Exception:
            pass
