"""
HuaweiVRPProfile — Huawei VRP vendor profile.

All VRP-specific rendering logic, session commands, GNS3 detection keywords,
and config parsing patterns live here. Translations from Cisco IOS to Huawei VRP
are implemented for all config blocks.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .base import SessionConfig, VendorProfile


class HuaweiVRPProfile(VendorProfile):

    vendor_id = "huawei_vrp"
    display_name = "Huawei VRP"

    # ── Session ───────────────────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        return SessionConfig(
            privilege_command="",  # Huawei has no separate enable mode
            privilege_password_prompt="",
            paging_disable="screen-length 0 temporary",
            config_mode_enter="system-view",
            config_mode_exit="return",
            save_command="save",
            save_confirm_prompt="Y/N]",
            save_confirm_response="Y",
            prompt_pattern_exec=r"(?:^|\n)\s*[\[<]\S+[\]>]\s*$",
            prompt_pattern_config=r"\[.*\]\s*$",
            logging_disable="undo terminal monitor",
            startup_nudge="Press RETURN to get started",
        )

    # ── Config Rendering ──────────────────────────────────────────────────

    def render_identity_block(self, identity_data: dict, hostname: str) -> str:
        if not identity_data:
            return ""
        hostname = identity_data.get("hostname", hostname)
        domain = identity_data.get("domain", "")
        lines = ["system-view", f"sysname {hostname}"]
        if domain:
            lines.append(f"ip domain-name {domain}")
        lines += [
            "!", "! ---------------------------------------------------------------",
            "! SECURITY NOTE: Passwords, authentication, and login credentials",
            "! have been intentionally left out. Please set up 'local-user' and",
            "! 'stelnet' authentication manually.",
            "! ---------------------------------------------------------------", "!",
            "line vty 0 4", " authentication-mode aaa", " protocol inbound telnet ssh",
            "return", "!", "return",
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
            # Huawei batch VLAN creation
            vlan_ids = [v.get("id") for v in vlans if v.get("id")]
            if vlan_ids:
                lines.append("system-view")
                lines.append(f"vlan batch {' '.join(vlan_ids)}")
                for v in vlans:
                    for iface in self.expand_ports_to_list(v.get("ports", "")):
                        if iface and iface not in uplink_ports:
                            lines.append(f"interface {iface}")
                            lines.append(" port link-type access")
                            lines.append(f" port default vlan {v.get('id')}")
                            lines.append(" undo shutdown")
                            lines.append("quit")
                lines.append("return")
        else:
            # Access switch
            vlan_ids = [v.get("id") for v in vlans if v.get("id")]
            if vlan_ids:
                lines.append("system-view")
                lines.append(f"vlan batch {' '.join(vlan_ids)}")
                for v in vlans:
                    lines.append(f"vlan {v.get('id')}")
                    lines.append(f" description {v.get('name') or 'VLAN' + str(v.get('id', ''))}")
                    lines.append("quit")
                lines.append("!")
                for v in vlans:
                    for iface in self.expand_ports_to_list(v.get("ports", "")):
                        if iface and iface not in uplink_ports:
                            lines.append(f"interface {iface}")
                            lines.append(" port link-type access")
                            lines.append(f" port default vlan {v.get('id')}")
                            lines.append(" stp edged-port enable")
                            lines.append(" undo shutdown")
                            lines.append("quit")
                lines.append("return")
        return "\n".join(lines)

    def render_uplink_block(self, uplinks: list) -> str:
        if not uplinks:
            return ""
        lines = ["system-view"]
        for link in uplinks:
            ports = link.get("ports", "").strip()
            mode = (link.get("mode") or "trunk").lower()
            allowed = link.get("allowed vlans", "all")
            if not ports:
                continue
            for port in [p.strip() for p in ports.split(",") if p.strip()]:
                lines.append(f"interface {port}")
                if mode == "trunk":
                    lines.append(" port link-type trunk")
                    if allowed.lower() != "all":
                        lines.append(f" port trunk allow-pass vlan {allowed}")
                    else:
                        lines.append(" port trunk allow-pass vlan all")
                else:
                    lines.append(" port link-type access")
                    if allowed.lower() != "all":
                        lines.append(f" port default vlan {allowed}")
                    lines.append(" stp edged-port enable")
                lines.append(" undo shutdown")
                lines.append("quit")
        lines.append("return")
        return "\n".join(lines)

    def render_routing_block(
        self, device_role: str, routing_entries: list,
        router_interface: str, is_boundary_router: bool,
        transit_links: list,
    ) -> str:
        if is_boundary_router:
            return self._render_transit_links_block(transit_links)
        if not routing_entries:
            return ""
        if device_role == "router":
            return self._render_router_on_stick_block(router_interface, routing_entries)
        # Core switch with SVIs
        lines = ["system-view", "ip routing-enable"]
        for e in routing_entries:
            vlan, ip, mask = e.get("vlan"), e.get("ip"), e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface Vlanif{vlan}", f" ip address {ip} {mask}", " undo shutdown", "quit"]
        lines.append("return")
        return "\n".join(lines)

    def _render_router_on_stick_block(self, router_interface: str, routing_entries: list) -> str:
        if not router_interface or not routing_entries:
            return ""
        lines = ["system-view", f"interface {router_interface}"]
        lines += [" undo shutdown", "quit"]
        for e in routing_entries:
            vlan, ip, mask = e.get("vlan"), e.get("ip"), e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface {router_interface}.{vlan}",
                          " dot1q termination vid " + str(vlan),
                          " ip address " + ip + " " + mask,
                          " arp broadcast enable",
                          " undo shutdown", "quit"]
        lines.append("return")
        return "\n".join(lines)

    def _render_transit_links_block(self, transit_links: list) -> str:
        if not transit_links:
            return ""
        lines = ["system-view"]
        for link in transit_links:
            iface = link["local_interface"]
            ip, mask = link["ip"], link["mask"]
            lines.append(f"interface {iface}")
            lines += [f" ip address {ip} {mask}", " undo shutdown", "quit"]
        lines.append("return")
        return "\n".join(lines)

    def render_wan_block(self, wan_interface: str, wan_ip: str, wan_mask: str) -> str:
        if not wan_interface or not wan_ip:
            return ""
        lines = ["system-view", f"interface {wan_interface}"]
        if wan_ip.lower() == "dhcp":
            lines.append(" ip address dhcp-alloc")
        else:
            lines.append(f" ip address {wan_ip} {wan_mask or '255.255.255.0'}")
        lines += [" undo shutdown", "quit", "!", "return"]
        return "\n".join(lines)

    def render_static_routes_block(self, static_routes: list) -> str:
        if not static_routes:
            return ""
        lines = ["system-view"]
        for r in static_routes:
            net, mask, nh, desc = r.get("network"), r.get("mask"), r.get("next-hop"), r.get("description", "")
            if net and nh:
                if desc:
                    lines.append(f"! {desc}")
                lines.append(f"ip route-static {net} {mask} {nh}")
        lines += ["!", "return"]
        return "\n".join(lines)

    def render_routing_protocol_block(
        self, routing_protocol: str, routing_entries: list,
        static_routes: list, transit_links: list,
        is_redistribution_router: bool, redistribution_protocols: list,
        is_boundary_router: bool, connected_links: list,
    ) -> str:
        proto = routing_protocol
        if proto == "none" and not is_redistribution_router:
            return ""
        if proto == "none" and routing_protocol == "rip":
            proto = "rip"

        has_default = any(
            r.get("network") == "0.0.0.0" and r.get("mask") == "0.0.0.0"
            for r in static_routes
        )

        lines = ["system-view"]

        # Boundary redistribution
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
            lines.append("return")
            return "\n".join(lines)

        networks = self._collect_protocol_networks(routing_entries)
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

        lines.append("return")
        return "\n".join(lines)

    def _render_single_protocol_block(
        self, proto: str, networks: list, has_default: bool,
        redistribute_from: str = "",
    ) -> list:
        lines: list = []

        if proto == "rip":
            lines += ["rip", " version 2", " undo summary"]
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
                lines.append(" default-route-advertise")
            lines.append("quit")

        elif proto == "ospf":
            lines.append("ospf 1")
            lines.append(" area 0")
            for ip, mask in networks:
                try:
                    net = self.to_network(ip, mask)
                    wc = self.to_wildcard(mask)
                    lines.append(f"  network {net} {wc}")
                except Exception:
                    pass
            lines.append(" quit")
            if redistribute_from:
                lines.append(self._redist_into_ospf(redistribute_from))
            if has_default:
                lines.append(" default-route-advertise always")
            lines.append("quit")

        elif proto == "eigrp":
            # EIGRP is Cisco proprietary — not supported on Huawei
            lines.append("! EIGRP not supported on Huawei VRP (Cisco proprietary)")

        return lines

    @staticmethod
    def _redist_into_rip(source_proto: str) -> str:
        if source_proto == "ospf":
            return " import-route ospf 1 cost 3"
        return ""

    @staticmethod
    def _redist_into_ospf(source_proto: str) -> str:
        if source_proto == "rip":
            return " import-route rip"
        return ""

    def render_dhcp_block(
        self, device_role: str, is_boundary_router: bool, dhcp_pools: list,
    ) -> str:
        if is_boundary_router or device_role == "access" or not dhcp_pools:
            return ""
        lines = ["system-view", "dhcp enable"]
        for pool in dhcp_pools:
            gw, start, end = pool.get("gateway", ""), pool.get("start", ""), pool.get("end", "")
            pool_name = (pool.get("pool") or pool.get("name") or "POOL").replace(" ", "_").replace("/", "-")
            net = pool.get("network", "")
            mask = pool.get("mask", "255.255.255.0")

            lines.append(f"ip pool {pool_name}")
            if net and mask:
                lines.append(f" network {net} mask {mask}")
            if gw:
                lines.append(f" gateway-list {gw}")
                # Exclude the gateway IP from the pool to prevent conflicts
                lines.append(f" excluded-ip-address {gw}")
            if start and end:
                lines.append(f" lease day 1 hour 0 minute 0")
            if pool.get("dns"):
                lines.append(f" dns-list {pool['dns']}")
            lines.append("quit")
        lines.append("return")
        return "\n".join(lines)

    def render_acl_block(
        self, acl_rules: list, routing_entries: list,
        device_role: str, router_interface: str,
    ) -> str:
        if not acl_rules:
            return ""
        acl_num = acl_rules[0].get("acl #", "3000")
        # Huawei uses numbered ACLs starting at 3000 for extended
        try:
            acl_num_int = int(acl_num)
            if acl_num_int < 3000:
                acl_num = str(3000 + (acl_num_int - 100))
        except ValueError:
            acl_num = "3000"

        lines = ["system-view", f"acl number {acl_num}"]
        for rule_idx, rule in enumerate(acl_rules, 1):
            action = rule.get("action", "permit")
            src = rule.get("source", "any")
            remark = rule.get("remark", "")
            if remark:
                lines.append(f"rule {rule_idx * 5} remark {remark}")
            if src.lower() == "any":
                lines.append(f"rule {rule_idx * 5} {action} ip source any")
            else:
                wc = rule.get("wildcard", "0.0.0.0")
                lines.append(f"rule {rule_idx * 5} {action} ip source {src} {wc}")
        lines.append("quit")

        # Apply ACL to interfaces (simplified)
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
                                 else f"Vlanif{vlan}")
                        if iface not in applied_ifaces:
                            applied_ifaces.add(iface)
                            lines += [f"interface {iface}", f" traffic-filter inbound acl {acl_num}", "quit"]
        lines.append("return")
        return "\n".join(lines)

    def render_save_command(self) -> str:
        return "save"

    # ── Metadata ──────────────────────────────────────────────────────────

    def supported_routing_protocols(self) -> List[Tuple[str, str, str]]:
        return [
            ("rip", "RIPv2",
             "Best for small networks (< 15 routers). Simple to set up, low overhead. "
             "Uses hop count — not ideal for complex topologies."),
            ("ospf", "OSPF",
             "Industry standard for medium-to-large networks. Scales well, uses "
             "link-state for optimal paths. Works across all vendors."),
            ("none", "None (Static routes only)",
             "No dynamic routing. Use this if you only need static routes or this "
             "router connects to a single network."),
        ]

    def show_vlan_command(self, device_role: str) -> str:
        return "display vlan"

    def gns3_detection_keywords(self) -> Dict[str, List[str]]:
        return {
            "l3": ["huawei", "s5700", "s6700", "ce"],
            "router": ["ar1220", "ar2220", "ar6120", "ne40", "ne20", "huawei", "vrp", "ensp"],
            "switch": ["s3700", "s5700", "huawei"],
        }

    # ── Config parsing ────────────────────────────────────────────────────

    _IP_PATTERN = re.compile(
        r"ip address\s+((?:\d{1,3}\.){3}\d{1,3})\s+((?:\d{1,3}\.){3}\d{1,3})"
    )
    _VLAN_ID_PATTERN = re.compile(r"\bvlan\s+(\d+)\b", re.IGNORECASE)
    _VLANIF_PATTERN = re.compile(r"interface\s+[Vv]lanif(\d+)", re.IGNORECASE)
    _SUBIF_PATTERN = re.compile(r"interface\s+\S+\.(\d+)", re.IGNORECASE)

    def parse_ip_addresses(self, config_text: str) -> List[Tuple[str, str]]:
        return self._IP_PATTERN.findall(config_text)

    def parse_vlan_ids(self, config_text: str) -> Set[str]:
        return set(self._VLAN_ID_PATTERN.findall(config_text))

    def parse_l3_interface_vlans(self, config_text: str) -> Set[str]:
        result = set(self._VLANIF_PATTERN.findall(config_text))
        result.update(self._SUBIF_PATTERN.findall(config_text))
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
