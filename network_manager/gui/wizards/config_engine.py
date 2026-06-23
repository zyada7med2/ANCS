"""
ConfigEngine — Headless Configuration Generator (vendor-aware)

This module extracts the config rendering logic from the Guided Setup Wizard
into a standalone, non-GUI class. Both the wizard UI and the AI Copilot agent
share this engine so that generated configurations are always identical.

The engine delegates all vendor-specific syntax to a ``VendorProfile`` looked
up via ``vendor_id`` (defaults to ``"cisco_ios"`` for backward compatibility).

Usage:
    engine = ConfigEngine(
        device_role="core",
        hostname="Core-SW1",
        vlans=[{"id": "10", "name": "Staff", "ports": "Ethernet0/0,Ethernet0/1"}],
        uplinks=[{"ports": "FastEthernet1/0", "mode": "trunk", "allowed vlans": "all"}],
        routing_entries=[{"vlan": "10", "ip": "192.168.10.1", "mask": "255.255.255.0"}],
        ...
    )
    blocks = engine.render_all_blocks()   # dict of block_name -> config text
    full   = engine.build_full_config()   # concatenated with ! BLOCK N: headers
"""
from __future__ import annotations
from typing import Dict, List, Optional

from ...vendors import get_profile
from ...vendors.base import VendorProfile


class ConfigEngine:
    """Headless config generator — shared by Guided Setup wizard and AI Copilot."""

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
        vendor_id: str = "cisco_ios",
        stp_root: str = "",
    ):
        self.device_role = device_role          # "router" | "core" | "access"
        self.hostname = hostname
        self.vendor_id = vendor_id
        self.profile: VendorProfile = get_profile(vendor_id)

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
        self.stp_root = stp_root

    # ══════════════════════════ Public API ══════════════════════════════════

    def render_all_blocks(self) -> Dict[str, str]:
        """Return a dict of template_key -> config text for all non-empty blocks."""
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
            "guided_save":             self.profile.render_save_command(),
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
    # Kept as static methods for backward compatibility (wizard may reference them).

    @staticmethod
    def _expand_ports_to_list(ports: str) -> List[str]:
        return VendorProfile.expand_ports_to_list(ports)

    @staticmethod
    def _to_wildcard(mask: str) -> str:
        return VendorProfile.to_wildcard(mask)

    @staticmethod
    def _to_network(ip: str, mask: str) -> str:
        return VendorProfile.to_network(ip, mask)

    @staticmethod
    def _to_classful(ip: str) -> str:
        return VendorProfile.to_classful(ip)

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
    # Each method delegates to self.profile, passing needed data as arguments.

    def _render_identity_block(self) -> str:
        return self.profile.render_identity_block(self.identity_data, self.hostname)

    def _render_vlan_block(self) -> str:
        # Pass stp_root to profile if supported, otherwise just pass standard args
        try:
            return self.profile.render_vlan_block(self.device_role, self.vlans, self.uplinks, self.stp_root)
        except TypeError:
            return self.profile.render_vlan_block(self.device_role, self.vlans, self.uplinks)

    def _render_uplink_block(self) -> str:
        return self.profile.render_uplink_block(self.uplinks)

    def _render_routing_block(self) -> str:
        return self.profile.render_routing_block(
            self.device_role, self.routing_entries,
            self.router_interface, self.is_boundary_router,
            self.transit_links,
        )

    def _render_wan_block(self) -> str:
        return self.profile.render_wan_block(self.wan_interface, self.wan_ip, self.wan_mask)

    def _render_static_routes_block(self) -> str:
        return self.profile.render_static_routes_block(self.static_routes)

    def _render_routing_protocol_block(self) -> str:
        return self.profile.render_routing_protocol_block(
            self.routing_protocol, self.routing_entries,
            self.static_routes, self.transit_links,
            self.is_redistribution_router, self.redistribution_protocols,
            self.is_boundary_router, self.connected_links,
        )

    def _render_dhcp_block(self) -> str:
        return self.profile.render_dhcp_block(
            self.device_role, self.is_boundary_router, self.dhcp_pools,
        )

    def _render_acl_block(self) -> str:
        return self.profile.render_acl_block(
            self.acl_rules, self.routing_entries,
            self.device_role, self.router_interface,
        )
