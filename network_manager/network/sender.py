"""
Network communication sender for serial, telnet, and SSH
"""
import time
import asyncio
import re

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
    def send_serial(log_fn, port, baud, text, newline_delay=0.02, block_delay=3.0):
        if serial is None:
            log_fn("[serial] pyserial not installed")
            return False
        ser = None
        try:
            log_fn(f"[serial] opening {port} @ {baud}")
            ser = serial.Serial(port=port, baudrate=baud, timeout=1)
            time.sleep(0.5)
            # Same IOS "Press RETURN to get started" screen as GNS3 telnet consoles
            ser.write(b"\r\n\r\n")
            time.sleep(0.35)

            def _wait_for_prompt_serial(timeout_sec=8.0):
                """Read from serial until IOS prompt (# or >) appears."""
                buf = b""
                deadline = time.time() + timeout_sec
                while time.time() < deadline:
                    if ser.in_waiting:
                        buf += ser.read(ser.in_waiting)
                        stripped = buf.rstrip()
                        if stripped and chr(stripped[-1]) in ("#", ">"):
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
        logged = False
        for attempt in range(8):
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
            if "press return" in low or "return to get started" in low or "hit return" in low:
                if not logged:
                    log_fn("[telnet] GNS3: sending Enter to pass IOS startup screen (Press RETURN)")
                    logged = True
                writer.write("\r\n")
                await asyncio.sleep(0.5)
                buf += await read_available(1.5)
                continue
            if attempt < 2 and len(buf.strip()) < 80 and "username:" not in low and "login:" not in low:
                writer.write("\r\n")
                await asyncio.sleep(0.4)
                buf += await read_available(1.2)
                continue
            break
        return buf

    @staticmethod
    async def _send_telnet_async(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=4.0):
        """Async implementation of telnet send using telnetlib3"""
        reader, writer = await asyncio.wait_for(
            telnetlib3.open_connection(host, port),
            timeout=timeout
        )
        
        async def read_available(timeout_sec=1.0):
            """Read whatever is available with timeout"""
            try:
                return await asyncio.wait_for(reader.read(4096), timeout=timeout_sec)
            except asyncio.TimeoutError:
                return ""

        async def wait_for_prompt(timeout_sec=8.0):
            """Read until we see an IOS prompt (# or >) — proves the CLI is
            idle and ready for the next command. Returns all text read."""
            buf = ""
            deadline = asyncio.get_event_loop().time() + timeout_sec
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=0.5)
                    if chunk:
                        buf += chunk
                        stripped = buf.rstrip()
                        if stripped and stripped[-1] in ("#", ">"):
                            break
                except asyncio.TimeoutError:
                    # No data for 0.5s — if we already have a prompt, done
                    stripped = buf.rstrip()
                    if stripped and stripped[-1] in ("#", ">"):
                        break
                    # Otherwise keep waiting until deadline
            return buf

        async def send_and_wait(line, extra_wait=0.0):
            """Send a line then wait for the device prompt before returning."""
            writer.write(line + "\r\n")
            if extra_wait:
                await asyncio.sleep(extra_wait)
            await wait_for_prompt()

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
            
            # Enable mode if needed
            if enable_pw:
                await send_and_wait("enable", 0.2)
                await send_and_wait(enable_pw, 0.2)
                log_fn("[telnet] enable sent")
            
            # Reduce noise that can corrupt long commands (syslog/paging)
            try:
                await send_and_wait("terminal length 0")
                await send_and_wait("configure terminal")
                await send_and_wait("no logging console")
                await send_and_wait("end")
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
                        await send_and_wait(stripped)
                        log_fn(f"[telnet] sent: {stripped}")
                
                # Wait between blocks
                if idx < len(blocks):
                    log_fn(f"[telnet] waiting {block_delay}s before next block...")
                    await asyncio.sleep(block_delay)
            
            # Read final output
            await asyncio.sleep(0.4)
            out = await read_available(1.0)
            if out and out.strip():
                log_fn("[telnet] output:\n" + out[:2000])
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
    def send_telnet(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=3.0):
        """Send configuration via telnet using async telnetlib3"""
        if telnetlib3 is None:
            log_fn("[telnet] telnetlib3 not installed")
            return False
        try:
            log_fn(f"[telnet] connecting to {host}:{port} ...")
            # Run the async function in a new event loop
            return asyncio.run(
                Sender._send_telnet_async(log_fn, host, port, username, password, enable_pw, text, timeout, block_delay)
            )
        except Exception as e:
            log_fn(f"[telnet] error: {e}")
            return False

    @staticmethod
    async def _run_show_commands_telnet_async(
        log_fn,
        host: str,
        port: int,
        username: str,
        password: str,
        enable_pw: str,
        commands: list[str],
        timeout: int = 10,
    ) -> dict[str, str]:
        """
        One Telnet session: wake/login/enable, terminal length 0, then each show command.
        Returns {command: output}. Used by the AI agent for device_name-based CLI.
        """
        reader, writer = await asyncio.wait_for(
            telnetlib3.open_connection(host, port),
            timeout=timeout,
        )

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
                        if stripped and stripped[-1] in (">", "#"):
                            break
                except asyncio.TimeoutError:
                    break
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
                if username:
                    await write_line(username)
                    await asyncio.sleep(0.2)
                if password:
                    await write_line(password)
                    await asyncio.sleep(0.2)

            if enable_pw:
                await write_line("enable")
                await asyncio.sleep(0.3)
                await write_line(enable_pw)
                await asyncio.sleep(0.2)

            await write_line("terminal length 0")
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
        if telnetlib3 is None:
            log_fn("[run_show] telnetlib3 not installed")
            return {"_error": "telnetlib3 not installed"}
        try:
            return asyncio.run(
                Sender._run_show_commands_telnet_async(
                    log_fn, host, port, username, password, enable_pw, commands, timeout
                )
            )
        except Exception as e:
            log_fn(f"[run_show] error: {e}")
            return {"_error": str(e)}

    # ─────────────────────────── verification ────────────────────────────────

    @staticmethod
    async def _verify_telnet_async(
        log_fn, host: str, port: int, commands: list[str],
        username: str = "", password: str = "", enable_pw: str = "",
        timeout: int = 10
    ) -> dict[str, str]:
        """
        Open a new Telnet connection, run each show command, and capture output.
        Returns {command: raw_output_text}.
        """
        reader, writer = await asyncio.wait_for(
            telnetlib3.open_connection(host, port), timeout=timeout
        )

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
                        if stripped and stripped[-1] in (">", "#"):
                            break
                except asyncio.TimeoutError:
                    break
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
        timeout: int = 10
    ) -> dict[str, str]:
        """
        Connect via Telnet, run `commands`, and return {command: raw_output}.
        Designed to run after a successful config send.
        """
        if telnetlib3 is None:
            log_fn("[verify] telnetlib3 not installed — skipping verification")
            return {}
        try:
            return asyncio.run(
                Sender._verify_telnet_async(
                    log_fn, host, port, commands,
                    username, password, enable_pw, timeout
                )
            )
        except Exception as exc:
            log_fn(f"[verify] failed: {exc}")
            return {}

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def send_ssh(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=3.0):
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
                """Read from SSH channel until IOS prompt (# or >) appears."""
                buf = ""
                deadline = time.time() + timeout_sec
                while time.time() < deadline:
                    time.sleep(0.15)
                    if chan.recv_ready():
                        buf += chan.recv(4096).decode("utf-8", errors="ignore")
                        stripped = buf.rstrip()
                        if stripped and stripped[-1] in ("#", ">"):
                            break
                    else:
                        stripped = buf.rstrip()
                        if stripped and stripped[-1] in ("#", ">"):
                            break
                return buf

            def _send_and_wait(line, timeout_sec=8.0):
                """Send a command line then wait for device prompt."""
                chan.send(line + "\n")
                _wait_for_prompt_ssh(timeout_sec)

            _send_and_wait("terminal length 0")
            if enable_pw:
                _send_and_wait("enable")
                _send_and_wait(enable_pw)

            try:
                _send_and_wait("configure terminal")
                _send_and_wait("no logging console")
                _send_and_wait("end")
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
                        _send_and_wait(stripped)
                        log_fn(f"[ssh] sent: {stripped}")

                if idx < len(blocks):
                    log_fn(f"[ssh] waiting {block_delay}s before next block...")
                    time.sleep(block_delay)

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
