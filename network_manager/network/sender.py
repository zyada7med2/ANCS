"""
Network communication sender for serial, telnet, and SSH
"""
import time
import telnetlib
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
    def send_telnet(log_fn, host, port, username, password, enable_pw, text, timeout=10, block_delay=3.0):
        try:
            log_fn(f"[telnet] connecting to {host}:{port} ...")
            tn = telnetlib.Telnet(host, port, timeout=timeout)
            time.sleep(0.4)
            # best-effort login
            try:
                idx, _, _ = tn.expect([b"Username:", b"login:"], timeout=1)
                tn.write(username.encode('utf-8') + b"\r\n")
                tn.read_until(b"Password:", timeout=1)
                tn.write(password.encode('utf-8') + b"\r\n")
                log_fn("[telnet] login sent")
            except Exception:
                # fallback: try sending username/password blind
                try:
                    if username:
                        tn.write(username.encode('utf-8') + b"\r\n")
                        time.sleep(0.1)
                    if password:
                        tn.write(password.encode('utf-8') + b"\r\n")
                        time.sleep(0.1)
                except Exception:
                    pass
            if enable_pw:
                tn.write(b"enable\r\n")
                time.sleep(0.2)
                tn.write(enable_pw.encode('utf-8') + b"\r\n")
                log_fn("[telnet] enable sent")

            # Reduce noise that can corrupt long commands (syslog/paging)
            try:
                tn.write(b"terminal length 0\r\n")
                time.sleep(0.2)
                tn.write(b"configure terminal\r\n")
                time.sleep(0.2)
                tn.write(b"no logging console\r\n")
                time.sleep(0.2)
                tn.write(b"exit\r\n")
                time.sleep(0.2)
                log_fn("[telnet] disabled console logging for this session")
            except Exception:
                # Best-effort; continue even if device doesn't like these
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
                        tn.write((line + "\r\n").encode('utf-8'))
                        log_fn(f"[telnet] sent: {line}")
                        time.sleep(0.2)
                
                # Wait between blocks
                if idx < len(blocks):
                    log_fn(f"[telnet] waiting {block_delay}s before next block...")
                    time.sleep(block_delay)
            
            time.sleep(0.4)
            out = b""
            try:
                out = tn.read_very_eager()
            except Exception:
                pass
            out = out.decode('utf-8', errors='ignore') if out else ""
            if out.strip():
                log_fn("[telnet] output:\n" + out[:2000])
            else:
                log_fn("[telnet] no output")
            tn.close()
            log_fn("[telnet] closed")
            return True
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

