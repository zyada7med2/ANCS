"""
Robust Cisco IOS configuration parser for ANCS.
Converts raw 'show running-config' text into structured data for the Guided Setup Wizard.
"""
import re
from typing import Dict, List, Any

class IOSParser:
    @staticmethod
    def parse_config(config_text: str) -> Dict[str, Any]:
        """
        Main entry point for parsing an IOS config into ANCS-compatible structures.
        """
        data = {
            "identity": {},
            "vlans": [],
            "dhcp_pools": [],
            "routing": {
                "protocol": "none",
                "networks": []
            },
            "wan": {"interface": "", "ip": "", "mask": ""},
            "static_routes": []
        }

        if not config_text:
            return data

        # 1. Identity & Hostname
        hn_match = re.search(r"^hostname\s+(\S+)", config_text, re.MULTILINE | re.IGNORECASE)
        if hn_match:
            data["identity"]["hostname"] = hn_match.group(1)

        dom_match = re.search(r"^ip domain-name\s+(\S+)", config_text, re.MULTILINE | re.IGNORECASE)
        if dom_match:
            data["identity"]["domain"] = dom_match.group(1)

        # 2. VLANs (Layer 2 definitions)
        # Pattern: vlan 10 \n name STAFF
        vlan_blocks = re.finditer(r"^vlan\s+(\d+)\s*\n(?:\s*name\s+(\S+)\s*\n)?", config_text, re.MULTILINE | re.IGNORECASE)
        for match in vlan_blocks:
            v_id = match.group(1)
            v_name = match.group(2) or f"VLAN_{v_id}"
            if v_id != "1": # Ignore default
                data["vlans"].append({"id": v_id, "name": v_name, "ip": "", "mask": "", "ports": ""})

        # 3. SVIs and IP Addresses
        # Pattern: interface Vlan10 \n ip address 10.1.1.1 255.255.255.0
        intf_blocks = re.finditer(r"^interface\s+([a-zA-Z0-9/._-]+)\s*\n(.*?)(?=^\S|\Z)", config_text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        for match in intf_blocks:
            intf_name = match.group(1)
            body = match.group(2)
            
            ip_m = re.search(r"ip address\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", body, re.IGNORECASE)
            if ip_m:
                ip, mask = ip_m.groups()
                # If it's an SVI, update the vlan entry
                if intf_name.lower().startswith("vlan"):
                    vid_match = re.search(r"vlan(\d+)", intf_name.lower())
                    if vid_match:
                        vid = vid_match.group(1)
                        # Find existing vlan or add new one
                        v_found = False
                        for v in data["vlans"]:
                            if v["id"] == vid:
                                v["ip"] = ip
                                v["mask"] = mask
                                v_found = True
                                break
                        if not v_found and vid != "1":
                            data["vlans"].append({"id": vid, "name": f"VLAN_{vid}", "ip": ip, "mask": mask, "ports": ""})
                
                # Check if it looks like a WAN interface (usually /30 or /31, or specific naming)
                if "/30" in mask or "255.255.255.252" in mask or "GigabitEthernet0/0" in intf_name:
                    if not data["wan"]["interface"]:
                        data["wan"] = {"interface": intf_name, "ip": ip, "mask": mask}

        # 4. DHCP Pools
        dhcp_blocks = re.finditer(r"^ip dhcp pool\s+(\S+)\s*\n(.*?)(?=^!|^ip dhcp pool|^\S|\Z)", config_text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        for match in dhcp_blocks:
            p_name = match.group(1)
            p_body = match.group(2)
            net_m = re.search(r"network\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", p_body, re.IGNORECASE)
            gw_m = re.search(r"default-router\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", p_body, re.IGNORECASE)
            if net_m:
                net, mask = net_m.groups()
                gw = gw_m.group(1) if gw_m else ""
                data["dhcp_pools"].append({"name": p_name, "network": net, "mask": mask, "gateway": gw})

        # 5. Routing Protocols
        # Detect all active protocols for redistribution logic
        protos = re.findall(r"^router\s+(ospf|eigrp|rip|bgp)", config_text, re.MULTILINE | re.IGNORECASE)
        if protos:
            data["routing"]["protocols"] = [p.lower() for p in set(protos)]
            data["routing"]["protocol"] = data["routing"]["protocols"][0]
            # Capture networks
            nw_matches = re.finditer(r"network\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?:\s+([\d\.]+))?", config_text, re.IGNORECASE)
            for nw in nw_matches:
                net_ip = nw.group(1)
                if net_ip not in data["routing"]["networks"]:
                    data["routing"]["networks"].append(net_ip)
        else:
            data["routing"]["protocols"] = []

        # 6. Static Routes
        static_matches = re.finditer(r"^ip route\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\S+)", config_text, re.MULTILINE | re.IGNORECASE)
        for sm in static_matches:
            dest, mask, next_hop = sm.groups()
            data["static_routes"].append({"destination": dest, "mask": mask, "next_hop": next_hop})

        return data
