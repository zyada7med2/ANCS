"""
Robust Cisco IOS configuration parser for ANCS.
Converts raw 'show running-config' text into structured data for the Guided Setup Wizard.
"""
import re
from typing import Dict, List, Any

class IOSParser:
    # Pre-compiled regex patterns (compiled once at class definition)
    HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.MULTILINE | re.IGNORECASE)
    DOMAIN_RE = re.compile(r"^ip domain-name\s+(\S+)", re.MULTILINE | re.IGNORECASE)
    VLAN_RE = re.compile(r"^vlan\s+(\d+)\s*\n(?:\s*name\s+(\S+)\s*\n)?", re.MULTILINE | re.IGNORECASE)
    INTERFACE_RE = re.compile(r"^interface\s+([a-zA-Z0-9/._-]+)\s*\n(.*?)(?=^\S|\Z)", re.MULTILINE | re.DOTALL | re.IGNORECASE)
    IP_ADDRESS_RE = re.compile(r"ip address\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", re.IGNORECASE)
    VLAN_ID_RE = re.compile(r"vlan(\d+)")
    DHCP_POOL_RE = re.compile(r"^ip dhcp pool\s+(\S+)\s*\n(.*?)(?=^!|^ip dhcp pool|^\S|\Z)", re.MULTILINE | re.DOTALL | re.IGNORECASE)
    DHCP_NET_RE = re.compile(r"network\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", re.IGNORECASE)
    DHCP_GW_RE = re.compile(r"default-router\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", re.IGNORECASE)
    ROUTER_RE = re.compile(r"^router\s+(ospf|eigrp|rip|bgp)", re.MULTILINE | re.IGNORECASE)
    NETWORK_RE = re.compile(r"network\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?:\s+([\d\.]+))?", re.IGNORECASE)
    STATIC_ROUTE_RE = re.compile(r"^ip route\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\S+)", re.MULTILINE | re.IGNORECASE)

    @staticmethod
    def parse_config(config_text: str) -> Dict[str, Any]:
        """
        Main entry point for parsing an IOS config into ANCS-compatible structures.
        Uses pre-compiled regex patterns for performance.
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
        hn_match = IOSParser.HOSTNAME_RE.search(config_text)
        if hn_match:
            data["identity"]["hostname"] = hn_match.group(1)

        dom_match = IOSParser.DOMAIN_RE.search(config_text)
        if dom_match:
            data["identity"]["domain"] = dom_match.group(1)

        # 2. VLANs (Layer 2 definitions)
        vlan_blocks = IOSParser.VLAN_RE.finditer(config_text)
        for match in vlan_blocks:
            v_id = match.group(1)
            v_name = match.group(2) or f"VLAN_{v_id}"
            if v_id != "1":  # Ignore default
                data["vlans"].append({"id": v_id, "name": v_name, "ip": "", "mask": "", "ports": ""})

        # 3. SVIs and IP Addresses
        intf_blocks = IOSParser.INTERFACE_RE.finditer(config_text)
        for match in intf_blocks:
            intf_name = match.group(1)
            body = match.group(2)

            ip_m = IOSParser.IP_ADDRESS_RE.search(body)
            if ip_m:
                ip, mask = ip_m.groups()
                # If it's an SVI, update the vlan entry
                if intf_name.lower().startswith("vlan"):
                    vid_match = IOSParser.VLAN_ID_RE.search(intf_name.lower())
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

                # Check if it looks like a WAN interface
                if "/30" in mask or "255.255.255.252" in mask or "GigabitEthernet0/0" in intf_name:
                    if not data["wan"]["interface"]:
                        data["wan"] = {"interface": intf_name, "ip": ip, "mask": mask}

        # 4. DHCP Pools
        dhcp_blocks = IOSParser.DHCP_POOL_RE.finditer(config_text)
        for match in dhcp_blocks:
            p_name = match.group(1)
            p_body = match.group(2)
            net_m = IOSParser.DHCP_NET_RE.search(p_body)
            gw_m = IOSParser.DHCP_GW_RE.search(p_body)
            if net_m:
                net, mask = net_m.groups()
                gw = gw_m.group(1) if gw_m else ""
                data["dhcp_pools"].append({"name": p_name, "network": net, "mask": mask, "gateway": gw})

        # 5. Routing Protocols
        protos = IOSParser.ROUTER_RE.findall(config_text)
        if protos:
            data["routing"]["protocols"] = [p.lower() for p in set(protos)]
            data["routing"]["protocol"] = data["routing"]["protocols"][0]
            # Capture networks
            nw_matches = IOSParser.NETWORK_RE.finditer(config_text)
            for nw in nw_matches:
                net_ip = nw.group(1)
                if net_ip not in data["routing"]["networks"]:
                    data["routing"]["networks"].append(net_ip)
        else:
            data["routing"]["protocols"] = []

        # 6. Static Routes
        static_matches = IOSParser.STATIC_ROUTE_RE.finditer(config_text)
        for sm in static_matches:
            dest, mask, next_hop = sm.groups()
            data["static_routes"].append({"destination": dest, "mask": mask, "next_hop": next_hop})

        return data

