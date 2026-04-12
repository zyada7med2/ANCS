"""
Bulk Configuration Puller for ANCS.
Handles concurrent connections to multiple devices to securely pull 'show running-config'.
Detects if a retrieved configuration is essentially blank (factory fresh).
"""
import asyncio
import re
import time
from typing import Dict, Any, List

try:
    import telnetlib3
except ImportError:
    telnetlib3 = None


class ConfigPuller:
    @staticmethod
    def is_blank_config(config_text: str) -> tuple[bool, str]:
        """
        Hyper-strict detection of 'blank' vs 'configured' devices.
        Returns (is_blank, reason).
        """
        if not config_text or len(config_text.strip()) < 100:
            return True, f"Too short/empty ({len(config_text.strip())} chars)"
        
        # 1. Manual IP Assignments (Ignore 'no ip address', 'ip address dhcp', or 127.x.x.x)
        ip_assigned = re.search(r"^\s*ip address (?!dhcp|pool|127\.|0\.0\.0\.0)\d{1,3}\.", config_text, re.IGNORECASE | re.MULTILINE)
        if ip_assigned:
            return False, f"Detected IP assigning line: {ip_assigned.group(0).strip()}"
        
        # 2. Routing Protocols (Explicit blocks like OSPF, EIGRP, RIP, BGP)
        routing = re.search(r"^\s*router (ospf|eigrp|rip|bgp)", config_text, re.IGNORECASE | re.MULTILINE)
        if routing:
            return False, f"Detected routing protocol: {routing.group(1)}"
        
        # 3. Custom Hostnames
        hostname_match = re.search(r"^\s*hostname\s+(\S+)", config_text, re.IGNORECASE | re.MULTILINE)
        if hostname_match:
            h = hostname_match.group(1).lower()
            # Extensive list of common default template patterns in GNS3/IOU/vIOS/ESW
            defaults = [
                r"router", r"switch", r"r\d+", r"sw\d+", r"sw-\d+", r"esw\d+",
                r"iou.*", r"vios.*", r"asw\d+", r"csw\d+", r"dsw\d+", r"core.*", 
                r"dist.*", r"acc.*", r"gateway", r"edge.*", r"node.*"
            ]
            if not any(re.match(f"^{pattern}$", h) for pattern in defaults):
                return False, f"Detected custom hostname: {hostname_match.group(1)}"
                
        # 4. Explicit User-Created VLANs (Ignore default 1 and reserved 1002-1005)
        # We look for 'vlan' followed exactly by a non-reserved digit on its own line
        manual_vlan = re.search(r"^\s*vlan\s+(?!1\b|1002\b|1003\b|1004\b|1005\b)\d+", config_text, re.IGNORECASE | re.MULTILINE)
        if manual_vlan:
            return False, f"Detected manual vlan definition: {manual_vlan.group(0).strip()}"
        
        # 5. Switch Virtual Interfaces (SVI)
        manual_svi = re.search(r"^\s*interface Vlan(?!1\b)\d+", config_text, re.IGNORECASE | re.MULTILINE)
        if manual_svi:
            return False, f"Detected Manual SVI: {manual_svi.group(0).strip()}"

        return True, "No configuration hallmarks found"

    @staticmethod
    async def _pull_single_async(host: str, port: int, username: str = "", password: str = "", enable_pw: str = "") -> str:
        """
        Async implementation to pull exactly `show running-config` from a single device.
        Requires sending an early Enter key to wake up GNS3 and handles optional credentials.
        """
        if not telnetlib3:
            raise Exception("telnetlib3 is not installed.")

        reader, writer = await asyncio.wait_for(telnetlib3.open_connection(host, port), timeout=10)

        async def _read_avail(timeout=1.0):
            try:
                return await asyncio.wait_for(reader.read(8192), timeout=timeout)
            except asyncio.TimeoutError:
                return ""

        async def _read_prompt(timeout=5.0):
            buf = ""
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                chunk = await _read_avail(0.5)
                if chunk:
                    buf += chunk
                    # Check for prompt tail
                    if buf.rstrip().endswith(">") or buf.rstrip().endswith("#"):
                        break
            return buf

        async def _write_line(line: str):
            writer.write(line + "\r\n")
            await asyncio.sleep(0.2)

        try:
            # 1. Send ENTER to wake up GNS3 connection
            writer.write("\r\n\r\n")
            await asyncio.sleep(0.5)
            
            buf = await _read_avail(2.0)

            # 2. Handle Authentication (if applicable or requested)
            # Some devices won't ask, some will. We match common prompts.
            lower_buf = buf.lower()
            if "login:" in lower_buf or "username:" in lower_buf:
                if username:
                    await _write_line(username)
                else:
                    await _write_line("") # Try to just push past it or fail
                buf = await _read_avail(1.0)
                lower_buf = buf.lower()
            
            if "password:" in lower_buf:
                if password:
                    await _write_line(password)
                else:
                    await _write_line("")
                await _read_avail(1.0)
            
            # Wait for user or exec prompt
            prompt = await _read_prompt(3.0)

            # 3. Enter Enable mode
            if ">" in prompt:
                await _write_line("enable")
                enb_buf = await _read_avail(1.0)
                if "password:" in enb_buf.lower():
                    if enable_pw:
                        await _write_line(enable_pw)
                    else:
                        await _write_line("") # Try empty
                await _read_prompt(3.0)
            
            # 4. Disable Paging
            await _write_line("terminal length 0")
            await _read_prompt(2.0)
            
            # 5. Execute show running-config
            await _write_line("show running-config")
            
            config_buf = ""
            # Reading a potentially long config can take several seconds
            read_deadline = asyncio.get_event_loop().time() + 15.0
            while asyncio.get_event_loop().time() < read_deadline:
                chunk = await _read_avail(0.5)
                if chunk:
                    config_buf += chunk
                    # Stop reading if we hit the prompt again (hostname#)
                    if config_buf.rstrip().endswith("#"):
                        break
            
            # Clean up the output to remove the command echo and trailing prompt
            lines = config_buf.splitlines()
            if lines and "show run" in lines[0].lower():
                lines = lines[1:]
            if lines and lines[-1].strip().endswith("#"):
                lines = lines[:-1]
                
            writer.close()
            return "\n".join(lines).strip()
            
        except Exception as e:
            try:
                writer.close()
            except:
                pass
            raise e

    @staticmethod
    def extract_hostname(config_text: str) -> str:
        """Extracts the hostname from a block of running-config text."""
        match = re.search(r"^hostname\s+(\S+)", config_text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def pull_sync(host: str, port: int, username: str = "", password: str = "", enable_pw: str = "") -> Dict[str, Any]:
        """
        Synchronous wrapper to pull config from one device. 
        Returns dict containing 'config', 'is_blank', 'reason', 'hostname', and any 'error'.
        """
        res = {"config": "", "is_blank": False, "reason": "", "hostname": "", "error": None}
        try:
            config = asyncio.run(ConfigPuller._pull_single_async(host, port, username, password, enable_pw))
            res["config"] = config
            is_blank, reason = ConfigPuller.is_blank_config(config)
            res["is_blank"] = is_blank
            res["reason"] = reason
            res["hostname"] = ConfigPuller.extract_hostname(config)
        except Exception as str_err:
            res["error"] = str(str_err)
        return res
