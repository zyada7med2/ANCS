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
            if stripped.startswith("! BLOCK ") and ":" in stripped:
                # Flush previous block
                if current_block and current_title is not None:
                    blocks.append((current_title, "\n".join(current_block)))
                    current_block = []

                m = re.search(r"BLOCK\s+\d+:\s*(.+)", stripped)
                current_title = m.group(1) if m else "Configuration Block"
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
        try:
            log_fn(f"[serial] opening {port} @ {baud}")
            ser = serial.Serial(port=port, baudrate=baud, timeout=1)
            time.sleep(0.5)
            
            # Split into blocks
            blocks = Sender.split_into_blocks(text)
            
            if len(blocks) > 1:
                log_fn(f"[serial] detected {len(blocks)} configuration blocks")
                
            for idx, (title, block_content) in enumerate(blocks, 1):
                if len(blocks) > 1:
                    log_fn(f"[serial] sending block {idx}/{len(blocks)}: {title}")
                
                for line in block_content.splitlines():
                    if line.strip():
                        ser.write((line + "\r\n").encode("utf-8"))
                        log_fn(f"[serial] sent: {line}")
                        time.sleep(newline_delay)
                
                # Wait between blocks
                if idx < len(blocks):
                    log_fn(f"[serial] waiting {block_delay}s before next block...")
                    time.sleep(block_delay)
            
            ser.close()
            log_fn("[serial] finished ✅")
            return True
        except Exception as e:
            log_fn(f"[serial] error: {e}")
            return False

    @staticmethod
    async def _send_telnet_async(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=3.0):
        """Async implementation of telnet send using telnetlib3"""
        reader, writer = await asyncio.wait_for(
            telnetlib3.open_connection(host, port),
            timeout=timeout
        )
        
        async def write_line(line):
            """Helper to write a line and flush"""
            writer.write(line + "\r\n")
            await asyncio.sleep(0.1)
        
        async def read_available(timeout_sec=1.0):
            """Read whatever is available with timeout"""
            try:
                return await asyncio.wait_for(reader.read(4096), timeout=timeout_sec)
            except asyncio.TimeoutError:
                return ""
        
        try:
            await asyncio.sleep(0.4)
            
            # Best-effort login - read initial prompt
            initial = await read_available(2.0)
            log_fn(f"[telnet] initial: {initial[:200] if initial else '(empty)'}")
            
            # Check for login prompts
            initial_lower = initial.lower() if initial else ""
            if "username:" in initial_lower or "login:" in initial_lower:
                if username:
                    await write_line(username)
                    await asyncio.sleep(0.3)
                    resp = await read_available(1.0)
                    if "password:" in resp.lower():
                        if password:
                            await write_line(password)
                            await asyncio.sleep(0.3)
                    log_fn("[telnet] login sent")
            elif "password:" in initial_lower:
                if password:
                    await write_line(password)
                    await asyncio.sleep(0.3)
                    log_fn("[telnet] password sent")
            else:
                # No login prompt, try sending credentials blind if provided
                if username:
                    await write_line(username)
                    await asyncio.sleep(0.2)
                if password:
                    await write_line(password)
                    await asyncio.sleep(0.2)
            
            # Enable mode if needed
            if enable_pw:
                await write_line("enable")
                await asyncio.sleep(0.3)
                await write_line(enable_pw)
                await asyncio.sleep(0.2)
                log_fn("[telnet] enable sent")
            
            # Reduce noise that can corrupt long commands (syslog/paging)
            try:
                await write_line("terminal length 0")
                await asyncio.sleep(0.2)
                await write_line("configure terminal")
                await asyncio.sleep(0.2)
                await write_line("no logging console")
                await asyncio.sleep(0.2)
                await write_line("exit")
                await asyncio.sleep(0.2)
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
                
                for line in block_content.splitlines():
                    if line.strip():
                        await write_line(line)
                        log_fn(f"[telnet] sent: {line}")
                        await asyncio.sleep(0.2)
                
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
    def send_ssh(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=3.0):
        if paramiko is None:
            log_fn("[ssh] paramiko not installed")
            return False
        try:
            log_fn(f"[ssh] connecting to {host}:{port} as {username}")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=host, port=port, username=username, password=password, timeout=timeout, look_for_keys=False)
            chan = client.invoke_shell()
            time.sleep(0.4)
            chan.send("terminal length 0\n")
            time.sleep(0.1)
            if enable_pw:
                chan.send("enable\n")
                time.sleep(0.2)
                chan.send(enable_pw + "\n")
                time.sleep(0.1)

            # Reduce noise that can corrupt long commands (syslog/paging)
            try:
                chan.send("configure terminal\n")
                time.sleep(0.2)
                chan.send("no logging console\n")
                time.sleep(0.2)
                chan.send("exit\n")
                time.sleep(0.2)
                log_fn("[ssh] disabled console logging for this session")
            except Exception:
                # Best-effort; continue even if device doesn't like these
                pass
            
            # Split into blocks
            blocks = Sender.split_into_blocks(text)
            
            if len(blocks) > 1:
                log_fn(f"[ssh] detected {len(blocks)} configuration blocks")
            
            for idx, (title, block_content) in enumerate(blocks, 1):
                if len(blocks) > 1:
                    log_fn(f"[ssh] sending block {idx}/{len(blocks)}: {title}")
                
                for line in block_content.splitlines():
                    if line.strip():
                        chan.send(line + "\n")
                        log_fn(f"[ssh] sent: {line}")
                        time.sleep(0.2)
                
                # Wait between blocks
                if idx < len(blocks):
                    log_fn(f"[ssh] waiting {block_delay}s before next block...")
                    time.sleep(block_delay)
            
            time.sleep(0.4)
            output = ""
            while chan.recv_ready():
                output += chan.recv(9999).decode('utf-8', errors='ignore')
            if output.strip():
                log_fn("[ssh] output:\n" + output[:2000])
            else:
                log_fn("[ssh] no output")
            try:
                chan.close()
            except Exception:
                pass
            client.close()
            log_fn("[ssh] finished")
            return True
        except Exception as e:
            log_fn(f"[ssh] error: {e}")
            return False
