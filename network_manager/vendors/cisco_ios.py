"""
CiscoIOSProfile — Cisco IOS vendor profile.

All IOS-specific rendering logic, session commands, GNS3 detection keywords,
and config parsing patterns live here.  The code is extracted verbatim from
the original ConfigEngine so that output is byte-for-byte identical.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .base import SessionConfig, VendorProfile


class CiscoIOSProfile(VendorProfile):

    vendor_id = "cisco_ios"
    display_name = "Cisco IOS"

    # ── Session ───────────────────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        return SessionConfig(
            privilege_command="enable",
            privilege_password_prompt="Password:",
            paging_disable="terminal length 0",
            config_mode_enter="configure terminal",
            config_mode_exit="end",
            save_command="write memory",
            save_confirm_prompt=None,
            save_confirm_response=None,
            prompt_pattern_exec=r"[>#]\s*$",
            prompt_pattern_config=r"\(config[^\)]*\)#\s*$",
            logging_disable="no logging console",
            startup_nudge="Press RETURN to get started",
        )

    # ── Config Rendering (verbatim from ConfigEngine) ─────────────────────

    def render_identity_block(self, identity_data: dict, hostname: str) -> str:
        if not identity_data:
            return ""
        hostname = identity_data.get("hostname", hostname)
        domain = identity_data.get("domain", "")
        lines = ["configure terminal", f"hostname {hostname}", "no ip domain-lookup"]
        if domain:
            lines.append(f"ip domain-name {domain}")
        lines += [
            "!", "! ---------------------------------------------------------------",
            "! SECURITY NOTE: Passwords, enable secrets, and login authentication",
            "! have been intentionally left out. Please set up 'enable secret',",
            "! 'username', and 'line con/vty login' manually.",
            "! ---------------------------------------------------------------", "!",
            "line vty 0 4", " transport input telnet ssh", " logging synchronous",
            "exit", "!", "end",
        ]
        return "\n".join(lines)

    def render_vlan_block(self, device_role: str, vlans: list, uplinks: list) -> str:
        if device_role == "router" or not vlans:
            return ""

        uplink_ports: set = set()
        for link in uplinks:
            for p in link.get("ports", "").split(","):
                if p.strip():
                    uplink_ports.add(p.strip())

        lines: list = []
        if device_role == "core":
            lines.append("vlan database")
            for v in vlans:
                lines.append(f"vlan {v.get('id')} name {v.get('name') or 'VLAN' + str(v.get('id', ''))}")
            lines += ["exit", "!", "configure terminal"]
            for v in vlans:
                for iface in self.expand_ports_to_list(v.get("ports", "")):
                    if iface and iface not in uplink_ports:
                        lines += [f"interface {iface}", " switchport mode access",
                                  f" switchport access vlan {v.get('id')}", " no shutdown", "exit"]
            lines += ["!", "end"]
        else:
            lines.append("configure terminal")
            for v in vlans:
                lines += [f"vlan {v.get('id')}", f" name {v.get('name') or 'VLAN' + str(v.get('id', ''))}", "exit"]
            lines.append("!")
            for v in vlans:
                for iface in self.expand_ports_to_list(v.get("ports", "")):
                    if iface and iface not in uplink_ports:
                        lines += [f"interface {iface}", " switchport mode access",
                                  f" switchport access vlan {v.get('id')}", " spanning-tree portfast",
                                  " no shutdown", "exit"]
            lines += ["!", "end"]

        return "\n".join(lines)

    def render_uplink_block(self, uplinks: list) -> str:
        if not uplinks:
            return ""
        lines = ["configure terminal"]
        for link in uplinks:
            ports = link.get("ports", "").strip()
            mode = (link.get("mode") or "trunk").lower()
            allowed = link.get("allowed vlans", "all")
            if not ports:
                continue
            for port in [p.strip() for p in ports.split(",") if p.strip()]:
                lines.append(f"interface {port}")
                if mode == "trunk":
                    lines.append(" switchport trunk encapsulation dot1q")
                    lines.append(" switchport mode trunk")
                    lines.append(
                        f" switchport trunk allowed vlan {allowed}"
                        if allowed.lower() != "all"
                        else " switchport trunk allowed vlan all"
                    )
                else:
                    lines.append(" switchport mode access")
                    if allowed.lower() != "all":
                        lines.append(f" switchport access vlan {allowed}")
                    lines.append(" spanning-tree portfast")

                if port.lower().startswith("fastethernet") or port.lower().startswith("ethernet"):
                    lines.append(" speed 100")
                    lines.append(" duplex full")
                lines += [" no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def render_routing_block(
        self, device_role: str, routing_entries: list,
        router_interface: str, is_boundary_router: bool,
        transit_links: list,
    ) -> str:
        # Boundary routers: only transit links
        if is_boundary_router:
            return self._render_transit_links_block(transit_links)

        parts = []

        # Router-on-a-stick subinterfaces (for inter-VLAN routing)
        if device_role == "router" and routing_entries and router_interface:
            parts.append(self._render_router_on_stick_block(router_interface, routing_entries))

        # Transit links between routers (R1↔R2↔R3) — always render when provided
        if device_role == "router" and transit_links:
            valid_transit = []
            for t in transit_links:
                # Prevent interface conflict: if this is the parent interface for subinterfaces,
                # it cannot ALSO be a transit link with an IP address.
                if routing_entries and router_interface and t.get("local_interface") == router_interface:
                    continue
                valid_transit.append(t)
            
            if valid_transit:
                parts.append(self._render_transit_links_block(valid_transit))

        if device_role == "router" and parts:
            return "\n".join(p for p in parts if p.strip())

        # Core switch SVIs
        if not routing_entries:
            return ""
        if device_role == "router":
            return self._render_router_on_stick_block(router_interface, routing_entries)
        lines = ["configure terminal", "ip routing"]
        for e in routing_entries:
            vlan, ip, mask = e.get("vlan"), e.get("ip"), e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface Vlan{vlan}", f" ip address {ip} {mask}", " no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_router_on_stick_block(self, router_interface: str, routing_entries: list) -> str:
        if not router_interface or not routing_entries:
            return ""
        lines = ["configure terminal", f"interface {router_interface}"]
        if router_interface.lower().startswith("fastethernet") or router_interface.lower().startswith("ethernet"):
            lines.append(" speed 100")
            lines.append(" duplex full")
        lines += [" no shutdown", "exit"]
        for e in routing_entries:
            vlan, ip, mask = e.get("vlan"), e.get("ip"), e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface {router_interface}.{vlan}",
                          f" encapsulation dot1Q {vlan}", f" ip address {ip} {mask}",
                          " no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_transit_links_block(self, transit_links: list) -> str:
        if not transit_links:
            return ""
        lines = ["configure terminal"]
        for link in transit_links:
            iface = link["local_interface"]
            ip, mask = link["ip"], link["mask"]
            lines.append(f"interface {iface}")
            if iface.lower().startswith("fastethernet") or iface.lower().startswith("ethernet"):
                lines.append(" speed 100")
                lines.append(" duplex full")
            lines += [f" ip address {ip} {mask}", " no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def render_wan_block(self, wan_interface: str, wan_ip: str, wan_mask: str) -> str:
        if not wan_interface or not wan_ip:
            return ""
        lines = ["configure terminal", f"interface {wan_interface}"]
        if wan_ip.lower() == "dhcp":
            lines.append(" ip address dhcp")
        else:
            lines.append(f" ip address {wan_ip} {wan_mask or '255.255.255.0'}")
        lines += [" no shutdown", "exit", "!", "end"]
        return "\n".join(lines)

    def render_static_routes_block(self, static_routes: list) -> str:
        if not static_routes:
            return ""
        lines = ["configure terminal"]
        for r in static_routes:
            net, mask, nh, desc = r.get("network"), r.get("mask"), r.get("next-hop"), r.get("description", "")
            if net and nh:
                if desc:
                    lines.append(f"! {desc}")
                lines.append(f"ip route {net} {mask} {nh}")
        lines += ["!", "end"]
        return "\n".join(lines)

    def render_routing_protocol_block(
        self, routing_protocol: str, routing_entries: list,
        static_routes: list, transit_links: list,
        is_redistribution_router: bool, redistribution_protocols: list,
        is_boundary_router: bool, connected_links: list,
    ) -> str:
        proto = routing_protocol
        enable_rip = (routing_protocol == "rip")
        if proto == "none" and not is_redistribution_router:
            return ""
        if proto == "none" and enable_rip:
            proto = "rip"

        has_default = any(
            r.get("network") == "0.0.0.0" and r.get("mask") == "0.0.0.0"
            for r in static_routes
        )

        lines = ["configure terminal"]

        if is_boundary_router and len(redistribution_protocols) >= 2:
            by_proto = self._collect_boundary_networks_by_protocol(transit_links)
            if not by_proto:
                return ""
            proto_a = redistribution_protocols[0]
            proto_b = redistribution_protocols[1]
            nets_a = by_proto.get(proto_a, [])
            nets_b = by_proto.get(proto_b, [])
            lines += self._render_single_protocol_block(proto_a, nets_a, has_default, redistribute_from=proto_b)
            lines.append("!")
            lines += self._render_single_protocol_block(proto_b, nets_b, has_default, redistribute_from=proto_a)
            lines += ["!", "end"]
            return "\n".join(lines)

        networks = self._collect_protocol_networks(routing_entries)

        # Also include transit link networks in routing protocol advertisements
        for link in (transit_links or []):
            lip = link.get("ip", "")
            lmask = link.get("mask", "255.255.255.252")
            if lip and lmask:
                networks.append((lip, lmask))

        if not networks and not is_redistribution_router:
            return ""

        if is_redistribution_router and len(redistribution_protocols) >= 2:
            proto_a = redistribution_protocols[0]
            proto_b = redistribution_protocols[1]
            lines += self._render_single_protocol_block(proto_a, networks, has_default, redistribute_from=proto_b)
            lines.append("!")
            lines += self._render_single_protocol_block(proto_b, networks, has_default, redistribute_from=proto_a)
        else:
            lines += self._render_single_protocol_block(proto, networks, has_default)

        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_single_protocol_block(
        self, proto: str, networks: list, has_default: bool,
        redistribute_from: str = "",
    ) -> list:
        lines: list = []

        if proto == "rip":
            lines += ["router rip", " version 2", " no auto-summary"]
            seen: set = set()
            for ip, mask in networks:
                try:
                    cn = self.to_classful(ip)
                    if cn not in seen:
                        seen.add(cn)
                        lines.append(f" network {cn}")
                except Exception:
                    pass
            if redistribute_from:
                lines.append(self._redist_into_rip(redistribute_from))
            if has_default:
                lines.append(" default-information originate")
            lines.append("exit")

        elif proto == "ospf":
            lines.append("router ospf 1")
            for ip, mask in networks:
                try:
                    net = self.to_network(ip, mask)
                    wc = self.to_wildcard(mask)
                    lines.append(f" network {net} {wc} area 0")
                except Exception:
                    pass
            if redistribute_from:
                lines.append(self._redist_into_ospf(redistribute_from))
            if has_default:
                lines.append(" default-information originate")
            lines.append("exit")

        elif proto == "eigrp":
            lines += ["router eigrp 10", " no auto-summary"]
            for ip, mask in networks:
                try:
                    net = self.to_network(ip, mask)
                    wc = self.to_wildcard(mask)
                    lines.append(f" network {net} {wc}")
                except Exception:
                    pass
            if redistribute_from:
                lines.append(self._redist_into_eigrp(redistribute_from))
            if has_default:
                lines.append(" redistribute static")
            lines.append("exit")

        return lines

    @staticmethod
    def _redist_into_rip(source_proto: str) -> str:
        if source_proto == "ospf":
            return " redistribute ospf 1 metric 3"
        elif source_proto == "eigrp":
            return " redistribute eigrp 10 metric 3"
        return ""

    @staticmethod
    def _redist_into_ospf(source_proto: str) -> str:
        if source_proto == "rip":
            return " redistribute rip subnets"
        elif source_proto == "eigrp":
            return " redistribute eigrp 10 subnets"
        return ""

    @staticmethod
    def _redist_into_eigrp(source_proto: str) -> str:
        if source_proto == "ospf":
            return " redistribute ospf 1 metric 1000 100 255 1 1500"
        elif source_proto == "rip":
            return " redistribute rip metric 1000 100 255 1 1500"
        return ""

    def render_dhcp_block(
        self, device_role: str, is_boundary_router: bool, dhcp_pools: list,
    ) -> str:
        if is_boundary_router or device_role == "access" or not dhcp_pools:
            return ""
        lines = ["configure terminal"]
        for pool in dhcp_pools:
            gw, start, end = pool.get("gateway", ""), pool.get("start", ""), pool.get("end", "")
            if gw and start:
                p = start.split(".")
                try:
                    s_last = int(p[3])
                    pfx = ".".join(gw.split(".")[:3])
                    lines.append(f"ip dhcp excluded-address {gw} {pfx}.{s_last - 1}" if s_last > 1 else f"ip dhcp excluded-address {gw}")
                except (IndexError, ValueError):
                    pass
            elif gw:
                lines.append(f"ip dhcp excluded-address {gw}")
            if end:
                p = end.split(".")
                try:
                    e_last = int(p[3])
                    pfx = ".".join(p[:3])
                    if e_last < 254:
                        lines.append(f"ip dhcp excluded-address {pfx}.{e_last + 1} {pfx}.254")
                except (IndexError, ValueError):
                    pass
            pool_name = (pool.get("pool") or pool.get("name") or "POOL").replace(" ", "_").replace("/", "-")
            lines.append(f"ip dhcp pool {pool_name}")
            lines.append(f" network {pool.get('network')} {pool.get('mask', '255.255.255.0')}")
            if gw:
                lines.append(f" default-router {gw}")
            if pool.get("dns"):
                lines.append(f" dns-server {pool['dns']}")
            lines.append(" lease 0 2")
            lines.append("exit")
        lines += ["!", "end"]
        return "\n".join(lines)

    def render_acl_block(
        self, acl_rules: list, routing_entries: list,
        device_role: str, router_interface: str,
    ) -> str:
        if not acl_rules:
            return ""
        acl_num = acl_rules[0].get("acl #", "101")
        is_extended = int(acl_num) >= 100
        lines = ["configure terminal"]
        for rule in acl_rules:
            num = rule.get("acl #", "101")
            action = rule.get("action", "permit")
            src = rule.get("source", "any")
            wc = rule.get("wildcard", "")
            dst = rule.get("destination", "")
            dst_wc = rule.get("destination_wildcard", "")
            remark = rule.get("remark", "")
            if remark:
                lines.append(f"access-list {num} remark {remark}")
            if is_extended:
                if src.lower() == "any":
                    lines.append(f"access-list {num} {action} ip any any")
                elif dst and dst.lower() != "any":
                    lines.append(f"access-list {num} {action} ip {src} {wc} {dst} {dst_wc}")
                else:
                    lines.append(f"access-list {num} {action} ip {src} {wc} any")
            else:
                if src.lower() == "any":
                    lines.append(f"access-list {num} {action} any")
                else:
                    lines.append(f"access-list {num} {action} {src} {wc}")
        lines.append("!")
        if is_extended:
            applied_ifaces: set = set()
            for rule in acl_rules:
                src_net = rule.get("source", "")
                if not src_net or src_net.lower() == "any":
                    continue
                for e in routing_entries:
                    e_ip = e.get("ip", "")
                    e_net = ".".join(e_ip.split(".")[:3]) + ".0" if e_ip else ""
                    src_prefix = ".".join(src_net.split(".")[:3]) + ".0" if src_net else ""
                    if e_net and src_prefix and e_net == src_prefix:
                        vlan = e.get("vlan")
                        if vlan:
                            iface = (f"{router_interface}.{vlan}"
                                     if device_role == "router" and router_interface
                                     else f"Vlan{vlan}")
                            if iface not in applied_ifaces:
                                applied_ifaces.add(iface)
                                lines += [f"interface {iface}", f" ip access-group {acl_num} in", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def render_save_command(self) -> str:
        return "write memory"

    # ── Metadata ──────────────────────────────────────────────────────────

    def supported_routing_protocols(self) -> List[Tuple[str, str, str]]:
        return [
            ("rip", "RIPv2",
             "Best for small networks (< 15 routers). Simple to set up, low overhead. "
             "Uses hop count — not ideal for complex topologies."),
            ("ospf", "OSPF",
             "Industry standard for medium-to-large networks. Scales well, uses "
             "link-state for optimal paths. Works across all vendors."),
            ("eigrp", "EIGRP",
             "Cisco-proprietary, very fast convergence. Great for all-Cisco networks. "
             "Combines best of distance-vector and link-state."),
            ("none", "None (Static routes only)",
             "No dynamic routing. Use this if you only need static routes or this "
             "router connects to a single network."),
        ]

    def show_vlan_command(self, device_role: str) -> str:
        return "show vlan-switch" if device_role == "core" else "show vlan brief"

    def gns3_detection_keywords(self) -> Dict[str, List[str]]:
        return {
            "l3": ["l3 switch", "layer3", "layer 3", "esw", "c3640", "c3560", "c3750", "multilayer"],
            "router": [
                "router", "ios", "csr", "isr", "iosv", "firepower", "asa", "xrv", "nxos",
                "c2691", "c2600", "c7200", "c3725", "c3745", "c3660", "c3845", "c1900", "c2900",
                "adventerprisek9", "advipservices",
            ],
            "switch": [],
        }

    # ── Config parsing ────────────────────────────────────────────────────

    _IP_PATTERN = re.compile(
        r"ip address\s+((?:\d{1,3}\.){3}\d{1,3})\s+((?:\d{1,3}\.){3}\d{1,3})"
    )
    _VLAN_ID_PATTERN = re.compile(r"\bvlan\s+(\d+)\b", re.IGNORECASE)
    _SUBIF_PATTERN = re.compile(r"interface\s+\S+\.(\d+)", re.IGNORECASE)
    _SVI_PATTERN = re.compile(r"interface\s+[Vv]lan(\d+)")

    def parse_ip_addresses(self, config_text: str) -> List[Tuple[str, str]]:
        return self._IP_PATTERN.findall(config_text)

    def parse_vlan_ids(self, config_text: str) -> Set[str]:
        return set(self._VLAN_ID_PATTERN.findall(config_text))

    def parse_l3_interface_vlans(self, config_text: str) -> Set[str]:
        result = set(self._SUBIF_PATTERN.findall(config_text))
        result.update(self._SVI_PATTERN.findall(config_text))
        return result

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _collect_protocol_networks(routing_entries: list) -> list:
        networks = []
        for e in routing_entries:
            ip = e.get("ip", "")
            mask = e.get("mask", "255.255.255.0")
            if ip and mask:
                networks.append((ip, mask))
        return networks

    @staticmethod
    def _collect_boundary_networks_by_protocol(transit_links: list) -> dict:
        by_proto: dict = {}
        for link in transit_links:
            proto = link.get("protocol", "none")
            if proto == "none":
                continue
            ip, mask = link.get("ip", ""), link.get("mask", "255.255.255.252")
            if ip and mask:
                by_proto.setdefault(proto, []).append((ip, mask))
        return by_proto
