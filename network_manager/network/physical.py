import asyncio
import socket
import ipaddress
import re
from typing import Callable, Dict, List, Optional
try:
    import paramiko
except Exception:
    paramiko = None

from .sender import Sender

class PhysicalDiscovery:
    """Engine for discovering physical network devices via Subnet Sweep or CDP/LLDP."""

    @staticmethod
    async def _check_port_async(ip: str, port: int, timeout: float = 0.5) -> bool:
        """Attempt to open a TCP connection to a port."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            return False

    @staticmethod
    async def scan_subnet(subnet_cidr: str, log_fn: Callable[[str], None], concurrency: int = 50) -> List[Dict]:
        """Sweep a subnet for alive devices answering on typical management ports (22, 23)."""
        log_fn(f"[Scan] Starting trace sweep on {subnet_cidr} ...")
        try:
            network = ipaddress.ip_network(subnet_cidr, strict=False)
        except ValueError as e:
            log_fn(f"[Scan] Error parsing network: {e}")
            return []

        hosts = list(network.hosts())
        found_devices = []

        semaphore = asyncio.Semaphore(concurrency)

        async def check_host(ip_obj):
            ip_str = str(ip_obj)
            async with semaphore:
                # Try Telnet first, then SSH
                if await PhysicalDiscovery._check_port_async(ip_str, 23, 0.5):
                    log_fn(f"[Scan] {ip_str} responsive on Telnet (23)")
                    found_devices.append({"ip": ip_str, "port": 23, "protocol": "telnet"})
                elif await PhysicalDiscovery._check_port_async(ip_str, 22, 0.5):
                    log_fn(f"[Scan] {ip_str} responsive on SSH (22)")
                    found_devices.append({"ip": ip_str, "port": 22, "protocol": "ssh"})

        tasks = [asyncio.create_task(check_host(ip)) for ip in hosts]
        if tasks:
            await asyncio.wait(tasks)

        log_fn(f"[Scan] Sweep complete. Found {len(found_devices)} reachable potentials.")
        return found_devices

    @staticmethod
    def identify_device(ip: str, protocol: str, port: int, user: str, psw: str, en: str, log_fn) -> Optional[Dict]:
        """Logs into the device, runs 'show version', and identifies it."""
        try:
            output = ""
            log_fn(f"[Identify] Probing {ip}:{port} via {protocol}...")
            if protocol == "telnet":
                res = Sender.run_show_commands_telnet(
                    log_fn=lambda m: None, # silences standard sender logs
                    host=ip, port=port, username=user, password=psw, enable_pw=en,
                    commands=["show version", "show privilege"], timeout=12
                )
                if "_error" in res:
                    log_fn(f"[Identify] Error connecting to {ip}: {res['_error']}")
                    return None
                output = res.get("show version", "") + "\n" + res.get("show privilege", "")
            elif protocol == "ssh":
                # For graduation project MVP, if it's SSH, we just return a stub if we don't have run_show_ssh
                log_fn(f"[Identify] SSH probe not fully implemented, logging stub for {ip}.")
                output = "Cisco IOS Software, C3750" 

            if not output.strip():
                log_fn(f"[Identify] No output received from {ip}.")
                return None

            hostname = "Unknown"
            device_type = "router"

            # Parse a rudimentary hostname from prompt if visible
            lines = output.splitlines()
            for line in reversed(lines):
                if line.endswith("#") or line.endswith(">"):
                    hostname = line.strip("#> ")
                    break

            # Parse version for device type heuristic
            output_lower = output.lower()
            if "switch" in output_lower or "c3750" in output_lower or "c3560" in output_lower or "c2960" in output_lower or "nx-os" in output_lower:
                device_type = "switch"
                if "core" in hostname.lower() or "nexus" in output_lower:
                    device_type = "core switch"
            elif "router" in output_lower or "c7200" in output_lower or "c3600" in output_lower or "isr" in output_lower:
                device_type = "router"

            return {
                "name": hostname if hostname != "Unknown" else f"Node-{ip}",
                "ip": ip,
                "port": port,
                "protocol": protocol,
                "type": device_type
            }

        except Exception as e:
            log_fn(f"[Identify] Failed to investigate {ip}: {e}")
            return None

    @staticmethod
    def crawl_cdp(seed_ip: str, seed_port: int, protocol: str, user: str, psw: str, en: str, log_fn) -> List[Dict]:
        """Connects to a seed device, runs CDP, and discovers neighbors."""
        log_fn(f"[CDP Crawl] Targeting seed {seed_ip}:{seed_port}...")
        
        output = ""
        if protocol == "telnet":
            res = Sender.run_show_commands_telnet(
                log_fn=lambda m: None,
                host=seed_ip, port=seed_port, username=user, password=psw, enable_pw=en,
                commands=["show cdp neighbors detail"], timeout=15
            )
            output = res.get("show cdp neighbors detail", "")
        else:
            log_fn("[CDP Crawl] SSH crawling requested but only Telnet is supported for graduation MVP.")
            return []

        if not output.strip():
            log_fn(f"[CDP Crawl] No CDP data received from {seed_ip}.")
            return []

        # Parse CDP neighbors detail output
        # Example:
        # Device ID: Switch2
        # Entry address(es):
        #   IP address: 10.0.0.2
        # Platform: cisco WS-C3560-24TS,  Capabilities: Switch IGMP
        
        neighbors = []
        blocks = output.split("-------------------------")
        for block in blocks:
            if "Device ID:" not in block:
                continue
            
            # Extract ID
            id_match = re.search(r"Device ID:\s*([^\n\r]+)", block)
            ip_match = re.search(r"IP address:\s*([0-9\.]+)", block)
            platform_match = re.search(r"Platform:\s*([^\,]+)", block)
            
            if id_match and ip_match:
                name = id_match.group(1).strip()
                n_ip = ip_match.group(1).strip()
                plat = platform_match.group(1).strip() if platform_match else ""
                
                device_type = "switch" if "switch" in plat.lower() or "ws-c" in plat.lower() else "router"
                if "core" in name.lower():
                    device_type = "core switch"
                    
                neighbors.append({
                    "name": name.split(".")[0], # strip domain if present
                    "ip": n_ip,
                    "port": 23, # Assuming standard telnet for now
                    "protocol": "telnet",
                    "type": device_type
                })
                log_fn(f"[CDP Crawl] Found neighbor {name} ({n_ip}) parsed as {device_type}.")
        
        log_fn(f"[CDP Crawl] Seed {seed_ip} revealed {len(neighbors)} immediate neighbors.")
        return neighbors

