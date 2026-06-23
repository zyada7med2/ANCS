"""
VendorProfile ABC and SessionConfig dataclass.

Every network operating system gets one VendorProfile subclass that encapsulates
all vendor-specific behaviour: session commands, config syntax rendering, GNS3
detection keywords, and config-text parsing patterns.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class SessionConfig:
    """Encapsulates every command/pattern that differs between NOS session types."""

    privilege_command: str = "enable"
    privilege_password_prompt: str = "Password:"
    paging_disable: str = "terminal length 0"
    config_mode_enter: str = "configure terminal"
    config_mode_exit: str = "end"
    save_command: str = "write memory"
    save_confirm_prompt: Optional[str] = None
    save_confirm_response: Optional[str] = None
    prompt_pattern_exec: str = r"[>#]\s*$"
    prompt_pattern_config: str = r"\(config[^\)]*\)#\s*$"
    logging_disable: str = "no logging console"
    startup_nudge: str = "Press RETURN to get started"


class VendorProfile(ABC):
    """Abstract base class for a network-OS vendor profile."""

    vendor_id: str = ""
    display_name: str = ""

    # ── Session ───────────────────────────────────────────────────────────

    @abstractmethod
    def session_config(self) -> SessionConfig: ...

    # ── Config rendering ──────────────────────────────────────────────────
    # Each method receives the data it needs as arguments (stateless).

    @abstractmethod
    def render_identity_block(self, identity_data: dict, hostname: str) -> str: ...

    @abstractmethod
    def render_vlan_block(self, device_role: str, vlans: list, uplinks: list) -> str: ...

    @abstractmethod
    def render_uplink_block(self, uplinks: list) -> str: ...

    @abstractmethod
    def render_routing_block(
        self, device_role: str, routing_entries: list,
        router_interface: str, is_boundary_router: bool,
        transit_links: list,
    ) -> str: ...

    @abstractmethod
    def render_wan_block(self, wan_interface: str, wan_ip: str, wan_mask: str) -> str: ...

    @abstractmethod
    def render_static_routes_block(self, static_routes: list) -> str: ...

    @abstractmethod
    def render_routing_protocol_block(
        self, routing_protocol: str, routing_entries: list,
        static_routes: list, transit_links: list,
        is_redistribution_router: bool, redistribution_protocols: list,
        is_boundary_router: bool, connected_links: list,
    ) -> str: ...

    @abstractmethod
    def render_dhcp_block(
        self, device_role: str, is_boundary_router: bool, dhcp_pools: list,
    ) -> str: ...

    @abstractmethod
    def render_acl_block(
        self, acl_rules: list, routing_entries: list,
        device_role: str, router_interface: str,
    ) -> str: ...

    @abstractmethod
    def render_save_command(self) -> str: ...

    # ── Metadata ──────────────────────────────────────────────────────────

    @abstractmethod
    def supported_routing_protocols(self) -> List[Tuple[str, str, str]]:
        """Return list of (value, label, description) tuples for the wizard UI."""
        ...

    @abstractmethod
    def show_vlan_command(self, device_role: str) -> str: ...

    @abstractmethod
    def gns3_detection_keywords(self) -> Dict[str, List[str]]:
        """Return {"l3": [...], "router": [...], "switch": [...]} for GNS3 auto-detection."""
        ...

    # ── Config parsing (for validators) ───────────────────────────────────

    @abstractmethod
    def parse_ip_addresses(self, config_text: str) -> List[Tuple[str, str]]:
        """Return list of (ip, mask) tuples found in config text."""
        ...

    @abstractmethod
    def parse_vlan_ids(self, config_text: str) -> Set[str]:
        """Return set of VLAN ID strings found in config text."""
        ...

    @abstractmethod
    def parse_l3_interface_vlans(self, config_text: str) -> Set[str]:
        """Return VLAN IDs from subinterfaces and SVIs in config text."""
        ...

    # ── Shared helpers (vendor-agnostic network math) ─────────────────────

    @staticmethod
    def expand_ports_to_list(ports: str) -> List[str]:
        if not ports:
            return []
        result: List[str] = []
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
    def to_wildcard(mask: str) -> str:
        return ".".join(str(255 - int(o)) for o in mask.split("."))

    @staticmethod
    def to_network(ip: str, mask: str) -> str:
        return ".".join(
            str(int(a) & int(b)) for a, b in zip(ip.split("."), mask.split("."))
        )

    @staticmethod
    def to_classful(ip: str) -> str:
        first = int(ip.split(".")[0])
        parts = ip.split(".")
        if first <= 127:
            return f"{parts[0]}.0.0.0"
        elif first <= 191:
            return f"{parts[0]}.{parts[1]}.0.0"
        else:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
