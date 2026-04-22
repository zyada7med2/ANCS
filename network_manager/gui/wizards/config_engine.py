"""
ConfigEngine — Headless IOS Configuration Generator

This module extracts the IOS config rendering logic from the Guided Setup Wizard
into a standalone, non-GUI class. Both the wizard UI and the AI Copilot agent
share this engine so that generated configurations are always identical.

Usage:
    engine = ConfigEngine(
        device_role="core",
        hostname="Core-SW1",
        vlans=[{"id": "10", "name": "Staff", "ports": "Ethernet0/0,Ethernet0/1"}],
        uplinks=[{"ports": "FastEthernet1/0", "mode": "trunk", "allowed vlans": "all"}],
        routing_entries=[{"vlan": "10", "ip": "192.168.10.1", "mask": "255.255.255.0"}],
        ...
    )
    blocks = engine.render_all_blocks()   # dict of block_name -> IOS text
    full   = engine.build_full_config()   # concatenated with ! BLOCK N: headers
"""
from __future__ import annotations
from typing import Dict, List, Optional


class ConfigEngine:
    """Headless IOS config generator — shared by Guided Setup wizard and AI Copilot."""

    def __init__(
        self,
        device_role: str,
        hostname: str = "Router",
        identity_data: dict | None = None,
        vlans: list | None = None,
        uplinks: list | None = None,
        routing_entries: list | None = None,
        dhcp_pools: list | None = None,
        static_routes: list | None = None,
        acl_rules: list | None = None,
        router_interface: str = "",
        wan_interface: str = "",
        wan_ip: str = "",
        wan_mask: str = "255.255.255.252",
        routing_protocol: str = "rip",
        is_redistribution_router: bool = False,
        redistribution_protocols: list | None = None,
        is_boundary_router: bool = False,
        transit_links: list | None = None,
        connected_links: list | None = None,
    ):
        self.device_role = device_role          # "router" | "core" | "access"
        self.hostname = hostname

        # Data buckets
        self.identity_data = identity_data or {"hostname": hostname}
        if "hostname" not in self.identity_data:
            self.identity_data["hostname"] = hostname
        self.vlans = vlans or []
        self.uplinks = uplinks or []
        self.routing_entries = routing_entries or []
        self.dhcp_pools = dhcp_pools or []
        self.static_routes = static_routes or []
        self.acl_rules = acl_rules or []
        self.router_interface = router_interface
        self.wan_interface = wan_interface
        self.wan_ip = wan_ip
        self.wan_mask = wan_mask
        self.routing_protocol = routing_protocol
        self.enable_rip = (routing_protocol == "rip")
        self.is_redistribution_router = is_redistribution_router
        self.redistribution_protocols = redistribution_protocols or []
        self.is_boundary_router = is_boundary_router
        self.transit_links = transit_links or []
        self.connected_links = connected_links or []

    # ══════════════════════════ Public API ══════════════════════════════════

    def render_all_blocks(self) -> Dict[str, str]:
        """Return a dict of template_key -> IOS config text for all non-empty blocks."""
        templates = {
            "guided_identity":         self._render_identity_block(),
            "guided_vlans":            self._render_vlan_block(),
            "guided_uplinks":          self._render_uplink_block(),
            "guided_routing":          self._render_routing_block(),
            "guided_wan":              self._render_wan_block(),
            "guided_static_routes":    self._render_static_routes_block(),
            "guided_routing_protocol": self._render_routing_protocol_block(),
            "guided_dhcp":             self._render_dhcp_block(),
            "guided_acl":              self._render_acl_block(),
            "guided_save":             "write memory",
        }
        return {k: v for k, v in templates.items() if v.strip()}

    def build_full_config(self) -> str:
        """Build a complete config string with ! BLOCK N: headers for the Sender."""
        blocks = self.render_all_blocks()
        out = []
        for idx, (key, text) in enumerate(blocks.items(), start=1):
            title = key.replace("guided_", "").replace("_", " ").title()
            out.append(f"! BLOCK {idx}: {title}")
            out.append(text)
        return "\n".join(out)

    # ══════════════════════════ Helpers ═════════════════════════════════════

    @staticmethod
    def _expand_ports_to_list(ports: str) -> List[str]:
        if not ports:
            return []
        result = []
        for part in str(ports).split(","):
            part = part.strip()
            if not part:
                continue
            slash = part.rfind("/")
            if slash == -1:
                result.append(part)
                continue
            prefix = part[: slash + 1]
            tail = part[slash + 1 :]
            if "-" in tail:
                a, b = tail.split("-", 1)
                try:
                    start, end = int(a), int(b)
                except ValueError:
                    result.append(part)
                    continue
                step = 1 if end >= start else -1
                for n in range(start, end + step, step):
                    result.append(f"{prefix}{n}")
            else:
                result.append(part)
        return result

    @staticmethod
    def _to_wildcard(mask: str) -> str:
        return ".".join(str(255 - int(o)) for o in mask.split("."))

    @staticmethod
    def _to_network(ip: str, mask: str) -> str:
        return ".".join(str(int(a) & int(b)) for a, b in zip(ip.split("."), mask.split(".")))

    @staticmethod
    def _to_classful(ip: str) -> str:
        first = int(ip.split(".")[0])
        parts = ip.split(".")
        if first <= 127:
            return f"{parts[0]}.0.0.0"
        elif first <= 191:
            return f"{parts[0]}.{parts[1]}.0.0"
        else:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0"

    def _find_all_links_to(self, *roles: str) -> List[Dict]:
        return [link for link in self.connected_links if link.get("remote_role") in roles]

    def _has_default_route(self) -> bool:
        return any(
            r.get("network") == "0.0.0.0" and r.get("mask") == "0.0.0.0"
            for r in self.static_routes
        )

    def _collect_protocol_networks(self) -> list:
        networks = []
        for e in self.routing_entries:
            ip = e.get("ip", "")
            mask = e.get("mask", "255.255.255.0")
            if ip and mask:
                networks.append((ip, mask))
        return networks

    def _collect_boundary_networks_by_protocol(self) -> dict:
        by_proto: dict[str, list] = {}
        for link in self.transit_links:
            proto = link.get("protocol", "none")
            if proto == "none":
                continue
            ip, mask = link.get("ip", ""), link.get("mask", "255.255.255.252")
            if ip and mask:
                by_proto.setdefault(proto, []).append((ip, mask))
        return by_proto

    # ══════════════════════════ Render Blocks ═══════════════════════════════

    def _render_identity_block(self) -> str:
        if not self.identity_data:
            return ""
        hostname = self.identity_data.get("hostname", self.hostname)
        domain = self.identity_data.get("domain", "")
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

    def _render_vlan_block(self) -> str:
        if self.device_role == "router" or not self.vlans:
            return ""

        # Gather all ports configured as uplinks so we don't make them access ports
        uplink_ports = set()
        for link in self.uplinks:
            for p in link.get("ports", "").split(","):
                if p.strip():
                    uplink_ports.add(p.strip())

        lines = []
        if self.device_role == "core":
            lines.append("vlan database")
            for v in self.vlans:
                lines.append(f"vlan {v.get('id')} name {v.get('name') or 'VLAN' + str(v.get('id', ''))}")
            lines += ["exit", "!", "configure terminal"]
            for v in self.vlans:
                for iface in self._expand_ports_to_list(v.get("ports", "")):
                    if iface and iface not in uplink_ports:
                        lines += [f"interface {iface}", " switchport mode access",
                                  f" switchport access vlan {v.get('id')}", " no shutdown", "exit"]
            lines += ["!", "end"]
        else:
            lines.append("configure terminal")
            for v in self.vlans:
                lines += [f"vlan {v.get('id')}", f" name {v.get('name') or 'VLAN' + str(v.get('id', ''))}", "exit"]
            lines.append("!")
            for v in self.vlans:
                for iface in self._expand_ports_to_list(v.get("ports", "")):
                    if iface and iface not in uplink_ports:
                        lines += [f"interface {iface}", " switchport mode access",
                                  f" switchport access vlan {v.get('id')}", " spanning-tree portfast",
                                  " no shutdown", "exit"]
            lines += ["!", "end"]
        return "\n".join(lines)

    def _render_uplink_block(self) -> str:
        if not self.uplinks:
            return ""
        lines = ["configure terminal"]
        for link in self.uplinks:
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

    def _render_routing_block(self) -> str:
        if self.is_boundary_router:
            return self._render_transit_links_block()
        if not self.routing_entries:
            return ""
        if self.device_role == "router":
            return self._render_router_on_stick_block()
        # Core switch — SVIs
        lines = ["configure terminal", "ip routing"]
        for e in self.routing_entries:
            vlan, ip, mask = e.get("vlan"), e.get("ip"), e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface Vlan{vlan}", f" ip address {ip} {mask}", " no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_router_on_stick_block(self) -> str:
        if not self.router_interface or not self.routing_entries:
            return ""
        lines = ["configure terminal", f"interface {self.router_interface}"]
        if self.router_interface.lower().startswith("fastethernet") or self.router_interface.lower().startswith("ethernet"):
            lines.append(" speed 100")
            lines.append(" duplex full")
        lines += [" no shutdown", "exit"]
        for e in self.routing_entries:
            vlan, ip, mask = e.get("vlan"), e.get("ip"), e.get("mask", "255.255.255.0")
            if vlan and ip:
                lines += [f"interface {self.router_interface}.{vlan}",
                          f" encapsulation dot1Q {vlan}", f" ip address {ip} {mask}",
                          " no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_transit_links_block(self) -> str:
        if not self.transit_links:
            return ""
        lines = ["configure terminal"]
        for link in self.transit_links:
            iface = link["local_interface"]
            ip, mask = link["ip"], link["mask"]
            lines.append(f"interface {iface}")
            if iface.lower().startswith("fastethernet") or iface.lower().startswith("ethernet"):
                lines.append(" speed 100")
                lines.append(" duplex full")
            lines += [f" ip address {ip} {mask}", " no shutdown", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_wan_block(self) -> str:
        if not self.wan_interface or not self.wan_ip:
            return ""
        lines = ["configure terminal", f"interface {self.wan_interface}"]
        if self.wan_ip.lower() == "dhcp":
            lines.append(" ip address dhcp")
        else:
            lines.append(f" ip address {self.wan_ip} {self.wan_mask or '255.255.255.0'}")
        lines += [" no shutdown", "exit", "!", "end"]
        return "\n".join(lines)

    def _render_static_routes_block(self) -> str:
        if not self.static_routes:
            return ""
        lines = ["configure terminal"]
        for r in self.static_routes:
            net, mask, nh, desc = r.get("network"), r.get("mask"), r.get("next-hop"), r.get("description", "")
            if net and nh:
                if desc:
                    lines.append(f"! {desc}")
                lines.append(f"ip route {net} {mask} {nh}")
        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_routing_protocol_block(self) -> str:
        proto = self.routing_protocol
        if proto == "none" and not self.is_redistribution_router:
            return ""
        if proto == "none" and self.enable_rip:
            proto = "rip"

        lines = ["configure terminal"]

        # Boundary redistribution router
        if self.is_boundary_router and len(self.redistribution_protocols) >= 2:
            by_proto = self._collect_boundary_networks_by_protocol()
            if not by_proto:
                return ""
            proto_a = self.redistribution_protocols[0]
            proto_b = self.redistribution_protocols[1]
            nets_a = by_proto.get(proto_a, [])
            nets_b = by_proto.get(proto_b, [])
            lines += self._render_single_protocol_block(proto_a, nets_a, redistribute_from=proto_b)
            lines.append("!")
            lines += self._render_single_protocol_block(proto_b, nets_b, redistribute_from=proto_a)
            lines += ["!", "end"]
            return "\n".join(lines)

        # Normal redistribution router
        networks = self._collect_protocol_networks()
        if not networks and not self.is_redistribution_router:
            return ""

        if self.is_redistribution_router and len(self.redistribution_protocols) >= 2:
            proto_a = self.redistribution_protocols[0]
            proto_b = self.redistribution_protocols[1]
            lines += self._render_single_protocol_block(proto_a, networks, redistribute_from=proto_b)
            lines.append("!")
            lines += self._render_single_protocol_block(proto_b, networks, redistribute_from=proto_a)
        else:
            lines += self._render_single_protocol_block(proto, networks)

        lines += ["!", "end"]
        return "\n".join(lines)

    def _render_single_protocol_block(self, proto: str, networks: list,
                                       redistribute_from: str = "") -> list:
        lines = []
        has_default = self._has_default_route()

        if proto == "rip":
            lines += ["router rip", " version 2", " no auto-summary"]
            seen = set()
            for ip, mask in networks:
                try:
                    cn = self._to_classful(ip)
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
                    net = self._to_network(ip, mask)
                    wc = self._to_wildcard(mask)
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
                    net = self._to_network(ip, mask)
                    wc = self._to_wildcard(mask)
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

    def _render_dhcp_block(self) -> str:
        if self.is_boundary_router or self.device_role == "access" or not self.dhcp_pools:
            return ""
        lines = ["configure terminal"]
        for pool in self.dhcp_pools:
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

    def _render_acl_block(self) -> str:
        if not self.acl_rules:
            return ""
        acl_num = self.acl_rules[0].get("acl #", "101")
        is_extended = int(acl_num) >= 100
        lines = ["configure terminal"]
        for rule in self.acl_rules:
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
            applied_ifaces = set()
            for rule in self.acl_rules:
                src_net = rule.get("source", "")
                if not src_net or src_net.lower() == "any":
                    continue
                for e in self.routing_entries:
                    e_ip = e.get("ip", "")
                    e_net = ".".join(e_ip.split(".")[:3]) + ".0" if e_ip else ""
                    src_prefix = ".".join(src_net.split(".")[:3]) + ".0" if src_net else ""
                    if e_net and src_prefix and e_net == src_prefix:
                        vlan = e.get("vlan")
                        if vlan:
                            iface = (f"{self.router_interface}.{vlan}"
                                     if self.device_role == "router" and self.router_interface
                                     else f"Vlan{vlan}")
                            if iface not in applied_ifaces:
                                applied_ifaces.add(iface)
                                lines += [f"interface {iface}", f" ip access-group {acl_num} in", "exit"]
        lines += ["!", "end"]
        return "\n".join(lines)
