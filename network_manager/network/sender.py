"""
Network communication sender for serial, telnet, and SSH
"""
import time
import asyncio
import re

from ..vendors.base import SessionConfig
from ..vendors import get_profile

# Optional imports
try:
    import serial
except Exception:
    serial = None

try:
    import paramiko
except Exception:
    paramiko = None

try:
    import telnetlib3
except Exception:
    telnetlib3 = None


# ── Raw TCP wrappers (bypass Telnet option negotiation) ──────────────
# GNS3 console ports are TCP proxies to device serial lines.  telnetlib3's
# default Telnet option negotiation (TTYPE, NAWS, …) leaks IAC bytes through
# GNS3's console handler, producing garbage like "}T" and "punknown" on the
# device CLI.  These thin wrappers present the same str-based read/write API
# that the rest of this module expects, but use raw asyncio TCP underneath.
# The reader also strips incoming IAC sequences that GNS3/Dynamips sends as
# a Telnet server, so they never pollute prompt detection or log output.

_IAC = 0xFF
_SB  = 0xFA
_SE  = 0xF0

def _strip_telnet_iac(data: bytes) -> bytes:
    """Remove Telnet IAC command sequences from raw bytes.

    Handles: IAC + 2-byte commands (WILL/WONT/DO/DONT),
             IAC + sub-negotiation (SB … SE),
             IAC IAC → single 0xFF literal.
    """
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        if data[i] == _IAC and i + 1 < n:
            nxt = data[i + 1]
            if nxt == _IAC:
                out.append(_IAC)
                i += 2
            elif nxt == _SB:
                # Skip until IAC SE
                i += 2
                while i < n:
                    if data[i] == _IAC and i + 1 < n and data[i + 1] == _SE:
                        i += 2
                        break
                    i += 1
                else:
                    pass  # unterminated SB — just consume
            elif 0xFB <= nxt <= 0xFE:
                # WILL / WONT / DO / DONT + 1 option byte
                i += 3
            else:
                # Other IAC command (2 bytes)
                i += 2
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


class _RawReader:
    """Async reader that decodes raw TCP bytes to str, stripping Telnet IAC."""
    __slots__ = ("_reader",)

    def __init__(self, reader: asyncio.StreamReader):
        self._reader = reader

    async def read(self, n: int) -> str:
        data = await self._reader.read(n)
        if not data:
            return ""
        cleaned = _strip_telnet_iac(data)
        return cleaned.decode("utf-8", errors="ignore")


class _RawWriter:
    """Writer that encodes str to bytes for raw TCP (same API as telnetlib3 writer)."""
    __slots__ = ("_writer",)

    def __init__(self, writer: asyncio.StreamWriter):
        self._writer = writer

    def write(self, data: str) -> None:
        self._writer.write(data.encode("utf-8") if isinstance(data, str) else data)

    def close(self) -> None:
        self._writer.close()


async def _open_raw_connection(host: str, port: int, timeout: float = 10):
    """Open a raw TCP connection (no Telnet negotiation). Returns (_RawReader, _RawWriter)."""
    raw_r, raw_w = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=timeout
    )
    return _RawReader(raw_r), _RawWriter(raw_w)


class Sender:
    @staticmethod
    def split_into_blocks(text):
        """
        Split configuration text into blocks based on the wizard headers.

        Looks for lines like:
            ! BLOCK 1: Identity & Security
        and groups everything after that (until the next BLOCK header)
        as one block. Instruction/separator comment lines are skipped.
        Returns list of (block_title, block_content) tuples.
        """
        blocks = []
        lines = text.splitlines()
        current_title = None
        current_block = []
        
        for line in lines:
            stripped = line.strip()

            # Start of a new block, e.g.:
            #   ! BLOCK 1: Identity & Security
            #   ! BLOCK 1 — Identity & Security
            if stripped.startswith("! BLOCK "):
                # Flush previous block
                if current_block and current_title is not None:
                    blocks.append((current_title, "\n".join(current_block)))
                    current_block = []

                # Match colon, dash, or em-dash (with optional surrounding whitespace)
                m = re.search(r"BLOCK\s+\d+\s*[:\-\u2014]\s*(.+)", stripped)
                current_title = m.group(1).strip() if m else "Configuration Block"
                continue

            # Skip instruction / decoration lines
            if stripped.startswith("! PASTE EACH BLOCK") or \
               stripped.startswith("! Wait for device prompt") or \
               stripped.startswith("! COPY THIS BLOCK") or \
               stripped.startswith("! Block complete") or \
               stripped.startswith("! ALL BLOCKS COMPLETE") or \
               stripped.startswith("! Now save your configuration") or \
               (stripped.startswith("!") and ("===" in stripped or "---" in stripped)):
                continue

            # Real config line inside a block
            if current_title is not None and stripped and not stripped.startswith("!"):
                current_block.append(line)

        # Flush last block
        if current_block and current_title is not None:
            blocks.append((current_title, "\n".join(current_block)))

        # If no blocks detected, treat everything (except comments) as one block
        if not blocks:
            filtered = [l for l in lines if l.strip() and not l.strip().startswith("!")]
            if filtered:
                blocks.append(("Configuration", "\n".join(filtered)))

        return blocks

    @staticmethod
    def _get_default_session_config() -> SessionConfig:
        """Get Cisco IOS default session config."""
        return get_profile("cisco_ios").session_config()

    @staticmethod
    async def _handle_save_confirmation_async(
        writer, read_available, log_fn, session_config: SessionConfig, timeout_sec: float = 3.0
    ):
        """Handle interactive save confirmation (e.g., Huawei's 'Are you sure?')."""
        if not session_config.save_confirm_prompt:
            return  # No confirmation needed (Cisco)

        buf = ""
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            try:
                chunk = await asyncio.wait_for(read_available(0.3), timeout=0.3)
                if chunk:
                    buf += chunk
                    if session_config.save_confirm_prompt in buf:
                        log_fn(f"[telnet] save confirmation prompt detected: sending '{session_config.save_confirm_response}'")
                        writer.write(session_config.save_confirm_response + "\r\n")
                        await asyncio.sleep(0.2)
                        return
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def _handle_save_confirmation_serial(
        ser, log_fn, session_config: SessionConfig, timeout_sec: float = 3.0
    ):
        """Handle interactive save confirmation for serial."""
        if not session_config.save_confirm_prompt:
            return

        buf = b""
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if ser.in_waiting:
                buf += ser.read(ser.in_waiting)
                if session_config.save_confirm_prompt.encode() in buf:
                    log_fn(f"[serial] save confirmation prompt detected: sending '{session_config.save_confirm_response}'")
                    ser.write((session_config.save_confirm_response + "\r\n").encode("utf-8"))
                    time.sleep(0.2)
                    return
            time.sleep(0.1)

    @staticmethod
    def _handle_save_confirmation_ssh(
        chan, log_fn, session_config: SessionConfig, timeout_sec: float = 3.0
    ):
        """Handle interactive save confirmation for SSH."""
        if not session_config.save_confirm_prompt:
            return

        buf = ""
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(0.15)
            if chan.recv_ready():
                buf += chan.recv(4096).decode("utf-8", errors="ignore")
                if session_config.save_confirm_prompt in buf:
                    log_fn(f"[ssh] save confirmation prompt detected: sending '{session_config.save_confirm_response}'")
                    chan.send(session_config.save_confirm_response + "\n")
                    time.sleep(0.2)
                    return

    @staticmethod
    def send_serial(log_fn, port, baud, text, newline_delay=0.02, block_delay=3.0, session_config: SessionConfig = None):
        if session_config is None:
            session_config = Sender._get_default_session_config()
        if serial is None:
            log_fn("[serial] pyserial not installed")
            return False
        ser = None
        try:
            log_fn(f"[serial] opening {port} @ {baud}")
            ser = serial.Serial(port=port, baudrate=baud, timeout=1)
            time.sleep(0.5)
            ser.write(b"\r\n\r\n")
            time.sleep(0.35)

            def _wait_for_prompt_serial(timeout_sec=8.0):
                """Read from serial until device prompt appears."""
                buf = b""
                deadline = time.time() + timeout_sec
                while time.time() < deadline:
                    if ser.in_waiting:
                        buf += ser.read(ser.in_waiting)
                        stripped = buf.rstrip()
                        if stripped and re.search(session_config.prompt_pattern_exec, stripped.decode("utf-8", errors="ignore")):
                            break
                    time.sleep(0.1)
                return buf.decode("utf-8", errors="ignore")

            def _send_and_wait_serial(line, timeout_sec=8.0):
                """Send a line then wait for device prompt."""
                ser.write((line + "\r\n").encode("utf-8"))
                _wait_for_prompt_serial(timeout_sec)

            blocks = Sender.split_into_blocks(text)

            if len(blocks) > 1:
                log_fn(f"[serial] detected {len(blocks)} configuration blocks")

            for idx, (title, block_content) in enumerate(blocks, 1):
                if len(blocks) > 1:
                    log_fn(f"[serial] sending block {idx}/{len(blocks)}: {title}")

                # Wait for a clean prompt before starting the block
                _wait_for_prompt_serial(3.0)

                for line in block_content.splitlines():
                    stripped = line.strip()
                    if stripped:
                        _send_and_wait_serial(stripped)
                        log_fn(f"[serial] sent: {stripped}")

                if idx < len(blocks):
                    log_fn(f"[serial] waiting {block_delay}s before next block...")
                    time.sleep(block_delay)

            log_fn("[serial] finished ✅")
            return True
        except Exception as e:
            log_fn(f"[serial] error: {e}")
            return False
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass

    @staticmethod
    async def _telnet_wake_gns3_console(writer, read_available, log_fn, initial: str = "") -> str:
        """
        GNS3 IOS consoles often show 'Press RETURN to get started' before login.
        Send CR/LF until a login line or IOS prompt appears (or attempts exhausted).
        `read_available(timeout_sec)` must be an async callable returning str/bytes.
        """
        buf = initial or ""
        
        # 1. Drain active boot-up stream. Wait for output silence before sending commands.
        last_len = len(buf)
        settle_attempts = 0
        while settle_attempts < 15:
            await asyncio.sleep(0.5)
            new_data = await read_available(1.0)
            if new_data:
                buf += new_data
                last_len = len(buf)
                settle_attempts = 0  # reset because we are actively receiving bytes
            else:
                settle_attempts += 1
                if len(buf) == last_len:
                    break  # settled (no new characters for 0.5s)
                    
        # 2. Interactive wake-up loop
        for attempt in range(3):
            low = buf.lower()
            if "username:" in low or "login:" in low:
                break
            if "password:" in low and "username:" not in low and "login:" not in low:
                break
                
            tail = buf.rstrip()
            if (
                tail
                and tail[-1] in ("#", ">")
                and "press return" not in low
                and "return to get started" not in low
            ):
                break
                
            # If console says "press return", or if it does not end in a prompt (# or >), send wake-up Enter
            if (
                "press return" in low
                or "return to get started" in low
                or "hit return" in low
                or not tail
                or tail[-1] not in ("#", ">")
            ):
                log_fn(f"[telnet] GNS3: sending Enter keypress to wake/bypass console (attempt {attempt+1}/3)")
                writer.write("\r\n")
                await asyncio.sleep(0.8)
                buf += await read_available(1.5)
                continue
                
            break
            
        return buf

    @staticmethod
    async def _send_telnet_async(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=4.0, session_config: SessionConfig = None):
        """Async implementation of telnet send using telnetlib3"""
        if session_config is None:
            session_config = Sender._get_default_session_config()
        reader, writer = await _open_raw_connection(host, port, timeout)

        async def read_available(timeout_sec=1.0):
            """Read whatever is available with timeout"""
            try:
                return await asyncio.wait_for(reader.read(4096), timeout=timeout_sec)
            except asyncio.TimeoutError:
                return ""

        async def wait_for_prompt(timeout_sec=8.0):
            """Read until we see a device prompt — proves the CLI is ready."""
            buf = ""
            deadline = asyncio.get_event_loop().time() + timeout_sec
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=0.5)
                    if chunk:
                        buf += chunk
                        if re.search(session_config.prompt_pattern_exec, buf):
                            break
                except asyncio.TimeoutError:
                    if re.search(session_config.prompt_pattern_exec, buf):
                        break
            return buf

        async def send_and_wait(line, extra_wait=0.0):
            """Send a line then wait for the device prompt before returning."""
            writer.write(line + "\r\n")
            if extra_wait:
                await asyncio.sleep(extra_wait)
            return await wait_for_prompt()

        try:
            await asyncio.sleep(0.4)

            # Best-effort login - read initial prompt (wake past GNS3 "Press RETURN" if needed)
            initial = await read_available(2.0)
            initial = await Sender._telnet_wake_gns3_console(writer, read_available, log_fn, initial)
            log_fn(f"[telnet] initial: {initial[:200] if initial else '(empty)'}")
            
            # Check for login prompts
            initial_lower = initial.lower() if initial else ""
            if "username:" in initial_lower or "login:" in initial_lower:
                if username:
                    writer.write(username + "\r\n")
                    await asyncio.sleep(0.3)
                    resp = await read_available(1.0)
                    if "password:" in resp.lower():
                        if password:
                            writer.write(password + "\r\n")
                            await asyncio.sleep(0.3)
                    log_fn("[telnet] login sent")
            elif "password:" in initial_lower:
                if password:
                    writer.write(password + "\r\n")
                    await asyncio.sleep(0.3)
                    log_fn("[telnet] password sent")
            else:
                if username:
                    writer.write(username + "\r\n")
                    await asyncio.sleep(0.2)
                if password:
                    writer.write(password + "\r\n")
                    await asyncio.sleep(0.2)

            # Wait for the device to settle into a prompt after login
            await wait_for_prompt(5.0)

            # Privilege mode if needed
            if session_config.privilege_command:
                await send_and_wait(session_config.privilege_command, 0.2)
                if enable_pw:
                    await send_and_wait(enable_pw, 0.2)
                log_fn("[telnet] privilege mode entered")

            # Reduce noise that can corrupt long commands
            try:
                await send_and_wait(session_config.paging_disable)
                await send_and_wait(session_config.config_mode_enter)
                if session_config.logging_disable:
                    await send_and_wait(session_config.logging_disable)
                await send_and_wait(session_config.config_mode_exit)
                log_fn("[telnet] disabled console logging for this session")
            except Exception:
                pass
            
            # Split into blocks
            blocks = Sender.split_into_blocks(text)
            
            if len(blocks) > 1:
                log_fn(f"[telnet] detected {len(blocks)} configuration blocks")
            
            for idx, (title, block_content) in enumerate(blocks, 1):
                if len(blocks) > 1:
                    log_fn(f"[telnet] sending block {idx}/{len(blocks)}: {title}")

                # Wait for a clean prompt before starting the block
                await wait_for_prompt(3.0)
                
                for line in block_content.splitlines():
                    stripped = line.strip()
                    if stripped:
                        resp = await send_and_wait(stripped)
                        log_fn(f"[telnet] sent: {stripped}")
                        if resp and resp.strip():
                            log_fn(f"[telnet] response: {resp.strip()}")

                        # If this was "write memory", send an extra Enter to confirm
                        if stripped.lower() == "write memory":
                            log_fn(f"[telnet] sending Enter after 'write memory' to confirm save")
                            writer.write("\r\n")
                            await asyncio.sleep(0.3)

                # Wait between blocks
                if idx < len(blocks):
                    log_fn(f"[telnet] waiting {block_delay}s before next block...")
                    await asyncio.sleep(block_delay)

            # Handle save confirmation (e.g. Huawei's Y/N prompt)
            if session_config and session_config.save_confirm_prompt:
                await Sender._handle_save_confirmation_async(
                    writer, read_available, log_fn, session_config
                )


            # Read final output
            await asyncio.sleep(0.4)
            out = await read_available(1.0)
            if out and str(out).strip():
                out_str = out if isinstance(out, str) else str(out)
                log_fn("[telnet] output:\n" + out_str[:2000])
            else:
                log_fn("[telnet] no output")
            
            writer.close()
            log_fn("[telnet] closed")
            return True
            
        except Exception as e:
            try:
                writer.close()
            except Exception:
                pass
            raise e

    @staticmethod
    def send_telnet(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=3.0, session_config: SessionConfig = None):
        """Send configuration via telnet (raw TCP to GNS3 console)"""
        if session_config is None:
            session_config = Sender._get_default_session_config()
        try:
            log_fn(f"[telnet] connecting to {host}:{port} ...")
            coro = Sender._send_telnet_async(log_fn, host, port, username, password, enable_pw, text, timeout, block_delay, session_config)

            # Check if we're in the main event loop's thread
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context — can't run_until_complete
                # This shouldn't happen in normal deployment flow
                log_fn(f"[telnet] ERROR: called from async context")
                return False
            except RuntimeError:
                # No running loop — safe to use asyncio.run()
                return asyncio.run(coro)
        except Exception as e:
            log_fn(f"[telnet] error: {e}")
            return False

    @staticmethod
    async def _run_show_commands_telnet_async(
        log_fn,
        host: str,
        port: int,
        commands: list[str],
        username: str = "",
        password: str = "",
        enable_pw: str = "",
        timeout: int = 10,
        session_config: SessionConfig = None,
    ) -> dict[str, str]:
        """
        One Telnet session: wake/login/enable, terminal length 0, then each show command.
        Returns {command: output}. Used by the AI agent for device_name-based CLI.
        """
        reader, writer = await _open_raw_connection(host, port, timeout)

        async def write_line(line: str):
            writer.write(line + "\r\n")
            await asyncio.sleep(0.1)

        async def read_available(timeout_sec: float = 1.0) -> str:
            try:
                return await asyncio.wait_for(reader.read(4096), timeout=timeout_sec)
            except asyncio.TimeoutError:
                return ""

        async def read_until_prompt(timeout_sec: float = 5.0) -> str:
            buf = ""
            deadline = asyncio.get_event_loop().time() + timeout_sec
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=0.5)
                    if chunk:
                        buf += chunk
                        stripped = buf.rstrip()
                        if stripped and (stripped[-1] in (">", "#") or stripped[-1] == "]"):
                            break
                except asyncio.TimeoutError:
                    pass
            return buf

        results: dict[str, str] = {}
        try:
            await asyncio.sleep(0.4)
            initial = await read_available(2.0)
            initial = await Sender._telnet_wake_gns3_console(
                writer, read_available, log_fn, initial
            )
            log_fn(f"[run_show] initial: {initial[:200] if initial else '(empty)'}")

            initial_lower = initial.lower() if initial else ""
            if "username:" in initial_lower or "login:" in initial_lower:
                if username:
                    await write_line(username)
                    await asyncio.sleep(0.3)
                    resp = await read_available(1.0)
                    if "password:" in resp.lower() and password:
                        await write_line(password)
                        await asyncio.sleep(0.3)
            elif "password:" in initial_lower:
                if password:
                    await write_line(password)
                    await asyncio.sleep(0.3)
            else:
                # No recognizable prompt — send credentials with reads between
                # to avoid garbled output (e.g. "ERuMnpnownenable")
                if username:
                    await write_line(username)
                    await asyncio.sleep(0.3)
                    await read_available(0.5)
                if password:
                    await write_line(password)
                    await asyncio.sleep(0.3)
                    await read_available(0.5)

            # Use session_config if provided, otherwise fall back to Cisco defaults
            if session_config and session_config.privilege_command:
                await write_line(session_config.privilege_command)
                await asyncio.sleep(0.3)
                if enable_pw:
                    await write_line(enable_pw)
                    await asyncio.sleep(0.2)
            elif enable_pw:
                await write_line("enable")
                await asyncio.sleep(0.3)
                await write_line(enable_pw)
                await asyncio.sleep(0.2)

            paging_cmd = session_config.paging_disable if session_config else "terminal length 0"
            await write_line(paging_cmd)
            await asyncio.sleep(0.25)
            await read_until_prompt(2.5)

            for cmd in commands:
                if not (cmd or "").strip():
                    continue
                log_fn(f"[run_show] {cmd}")
                await write_line(cmd.strip())
                results[cmd] = await read_until_prompt(6.0)

            writer.close()
        except Exception as exc:
            log_fn(f"[run_show] error: {exc}")
            results["_error"] = str(exc)
            try:
                writer.close()
            except Exception:
                pass
        return results

    @staticmethod
    def run_show_commands_telnet(
        log_fn,
        host: str,
        port: int,
        username: str,
        password: str,
        enable_pw: str,
        commands: list[str],
        timeout: int = 10,
    ) -> dict[str, str]:
        try:
            coro = Sender._run_show_commands_telnet_async(
                log_fn, host, port,
                commands=commands,
                username=username,
                password=password,
                enable_pw=enable_pw,
                timeout=timeout,
            )
            try:
                asyncio.get_running_loop()
                return {"_error": "called from async context"}
            except RuntimeError:
                return asyncio.run(coro)
        except Exception as e:
            log_fn(f"[run_show] error: {e}")
            return {"_error": str(e)}

    # ─────────────────────────── verification ────────────────────────────────

    @staticmethod
    async def _verify_telnet_async(
        log_fn, host: str, port: int, commands: list[str],
        username: str = "", password: str = "", enable_pw: str = "",
        timeout: int = 10, session_config: SessionConfig = None
    ) -> dict[str, str]:
        """
        Open a new Telnet connection, run each show command, and capture output.
        Returns {command: raw_output_text}.
        """
        reader, writer = await _open_raw_connection(host, port, timeout)

        async def write_line(line: str):
            writer.write(line + "\r\n")
            await asyncio.sleep(0.15)

        async def read_until_prompt(timeout_sec: float = 5.0) -> str:
            buf = ""
            deadline = asyncio.get_event_loop().time() + timeout_sec
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=0.5)
                    if chunk:
                        buf += chunk
                        stripped = buf.rstrip()
                        if stripped and (stripped[-1] in (">", "#") or stripped[-1] == "]"):
                            break
                except asyncio.TimeoutError:
                    pass
            return buf

        async def read_available(timeout_sec: float = 1.0) -> str:
            try:
                return await asyncio.wait_for(reader.read(4096), timeout=timeout_sec)
            except asyncio.TimeoutError:
                return ""

        results: dict[str, str] = {}
        try:
            # Brief settling pause for GNS3 console banner
            await asyncio.sleep(0.6)
            banner = await read_available(2.0)
            await Sender._telnet_wake_gns3_console(writer, read_available, log_fn, banner)
            await read_until_prompt(3.0)  # drain banner / reach prompt

            if session_config and session_config.paging_disable:
                await write_line(session_config.paging_disable)
            else:
                await write_line("terminal length 0")
            await read_until_prompt(2.0)

            for cmd in commands:
                log_fn(f"[verify] running: {cmd}")
                await write_line(cmd)
                output = await read_until_prompt(5.0)
                results[cmd] = output
                log_fn(f"[verify] output ({len(output)} chars)")

            writer.close()
        except Exception as exc:
            log_fn(f"[verify] error during verification: {exc}")
            try:
                writer.close()
            except Exception:
                pass
        return results

    @staticmethod
    def verify_telnet(
        log_fn, host: str, port: int, commands: list[str],
        username: str = "", password: str = "", enable_pw: str = "",
        timeout: int = 10, session_config: SessionConfig = None
    ) -> dict[str, str]:
        """
        Connect via Telnet, run `commands`, and return {command: raw_output}.
        Designed to run after a successful config send.
        """
        if session_config is None:
            session_config = Sender._get_default_session_config()
        try:
            coro = Sender._verify_telnet_async(
                log_fn, host, port, commands,
                username, password, enable_pw, timeout, session_config
            )
            try:
                asyncio.get_running_loop()
                return {}
            except RuntimeError:
                return asyncio.run(coro)
        except Exception as exc:
            log_fn(f"[verify] failed: {exc}")
            return {}

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def send_ssh(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=3.0, session_config: SessionConfig = None):
        if session_config is None:
            session_config = Sender._get_default_session_config()
        if paramiko is None:
            log_fn("[ssh] paramiko not installed")
            return False
        client = None
        chan = None
        try:
            log_fn(f"[ssh] connecting to {host}:{port} as {username}")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host, port=port,
                username=username, password=password,
                timeout=timeout, look_for_keys=False, allow_agent=False,
            )
            chan = client.invoke_shell()
            time.sleep(0.4)

            def _wait_for_prompt_ssh(timeout_sec=8.0):
                """Read from SSH channel until device prompt appears."""
                buf = ""
                deadline = time.time() + timeout_sec
                while time.time() < deadline:
                    time.sleep(0.15)
                    if chan.recv_ready():
                        buf += chan.recv(4096).decode("utf-8", errors="ignore")
                        if re.search(session_config.prompt_pattern_exec, buf):
                            break
                    else:
                        if re.search(session_config.prompt_pattern_exec, buf):
                            break
                return buf

            def _send_and_wait(line, timeout_sec=8.0):
                """Send a command line then wait for device prompt."""
                chan.send(line + "\n")
                return _wait_for_prompt_ssh(timeout_sec)

            _send_and_wait(session_config.paging_disable)
            if session_config.privilege_command:
                _send_and_wait(session_config.privilege_command)
                if enable_pw:
                    _send_and_wait(enable_pw)

            try:
                _send_and_wait(session_config.config_mode_enter)
                if session_config.logging_disable:
                    _send_and_wait(session_config.logging_disable)
                _send_and_wait(session_config.config_mode_exit)
                log_fn("[ssh] disabled console logging for this session")
            except Exception:
                pass

            blocks = Sender.split_into_blocks(text)

            if len(blocks) > 1:
                log_fn(f"[ssh] detected {len(blocks)} configuration blocks")

            for idx, (title, block_content) in enumerate(blocks, 1):
                if len(blocks) > 1:
                    log_fn(f"[ssh] sending block {idx}/{len(blocks)}: {title}")

                # Wait for a clean prompt before starting the block
                _wait_for_prompt_ssh(3.0)

                for line in block_content.splitlines():
                    stripped = line.strip()
                    if stripped:
                        resp = _send_and_wait(stripped)
                        log_fn(f"[ssh] sent: {stripped}")
                        if resp and resp.strip():
                            log_fn(f"[ssh] response: {resp.strip()}")

                if idx < len(blocks):
                    log_fn(f"[ssh] waiting {block_delay}s before next block...")
                    time.sleep(block_delay)

            # Handle save confirmation if the last block was a save command.
            # The guided_save block already sent the save command in the loop
            # above, so we only need to handle the interactive confirmation
            # (e.g. Huawei's Y/N prompt). We do NOT send save again.
            Sender._handle_save_confirmation_ssh(chan, log_fn, session_config)

            time.sleep(0.4)
            output = ""
            while chan.recv_ready():
                output += chan.recv(9999).decode("utf-8", errors="ignore")
            if output.strip():
                log_fn("[ssh] output:\n" + output[:2000])
            else:
                log_fn("[ssh] no output")

            log_fn("[ssh] finished")
            return True
        except Exception as e:
            log_fn(f"[ssh] error: {e}")
            return False
        finally:
            for obj in (chan, client):
                if obj is not None:
                    try:
                        obj.close()
                    except Exception:
                        pass
