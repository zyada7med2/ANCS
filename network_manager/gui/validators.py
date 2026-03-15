"""
Pre-send configuration validator for ANCS.

Scans all device templates for common network mistakes before sending
any config to a device, giving the user a chance to review and abort.
"""
import re


class ConfigValidator:
    """Static helper that checks a device list for configuration errors."""

    @staticmethod
    def check_all(devices: list) -> list[str]:
        """
        Run all checks against the full device list.

        devices: list of (name, DeviceModel, meta) tuples
        Returns a list of human-readable warning strings (empty = all clear).
        """
        warnings: list[str] = []
        warnings.extend(ConfigValidator._check_duplicate_ips(devices))
        warnings.extend(ConfigValidator._check_vlan_mismatches(devices))
        warnings.extend(ConfigValidator._check_missing_routing(devices))
        return warnings

    # ─────────────────────────────────────────────────────────────────────────
    # Check 1: Duplicate IP addresses across devices
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _check_duplicate_ips(devices: list) -> list[str]:
        """Flag any IP address that appears on more than one device."""
        ip_to_devices: dict[str, list[str]] = {}
        ip_pattern = re.compile(
            r"ip address\s+((?:\d{1,3}\.){3}\d{1,3})\s+((?:\d{1,3}\.){3}\d{1,3})"
        )
        for name, model, _meta in devices:
            full = model.build_full_config()
            for match in ip_pattern.finditer(full):
                ip = match.group(1)
                if ip in ("0.0.0.0",):
                    continue
                ip_to_devices.setdefault(ip, []).append(name)

        warnings = []
        for ip, owners in ip_to_devices.items():
            if len(owners) > 1:
                warnings.append(
                    f"Duplicate IP {ip} found on: {', '.join(owners)}"
                )
        return warnings

    # ─────────────────────────────────────────────────────────────────────────
    # Check 2: VLAN IDs defined on switches but missing from router routing
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _check_vlan_mismatches(devices: list) -> list[str]:
        """
        Collect VLANs from switch guided_vlans templates and routing VLANs
        from router guided_routing (subinterface .VLAN) templates.
        Warn if a VLAN exists on a switch but no router has a matching route.
        """
        switch_vlans: dict[str, set[str]] = {}   # device_name -> {vlan_id}
        router_vlans: set[str] = set()

        vlan_id_pattern   = re.compile(r"\bvlan\s+(\d+)\b", re.IGNORECASE)
        subif_pattern     = re.compile(r"interface\s+\S+\.(\d+)", re.IGNORECASE)
        svi_pattern       = re.compile(r"interface\s+[Vv]lan(\d+)")

        for name, model, _meta in devices:
            vlan_tmpl    = model.get_template("guided_vlans")
            routing_tmpl = model.get_template("guided_routing")

            if vlan_tmpl.strip():
                ids = set(vlan_id_pattern.findall(vlan_tmpl))
                ids.discard("1")  # VLAN 1 is the default, not worth flagging
                if ids:
                    switch_vlans[name] = ids

            if routing_tmpl.strip():
                # subinterfaces (router-on-stick)
                router_vlans.update(subif_pattern.findall(routing_tmpl))
                # SVIs (core switch)
                router_vlans.update(svi_pattern.findall(routing_tmpl))

        warnings = []
        for dev_name, vlans in switch_vlans.items():
            missing = vlans - router_vlans
            if missing:
                warnings.append(
                    f"VLANs {sorted(missing)} on '{dev_name}' have no matching "
                    "routing entry (subinterface or SVI) on any device."
                )
        return warnings

    # ─────────────────────────────────────────────────────────────────────────
    # Check 3: Device has VLAN config but no routing config
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _check_missing_routing(devices: list) -> list[str]:
        """
        Warn when a core switch has VLANs but no routing AND no router in the
        workspace is already handling inter-VLAN routing.
        If a router has guided_routing configured, it is the designated routing
        device — the core switch deliberately has no SVIs and the warning is
        a false positive.
        """
        from ..models.devices import CoreSwitchModel, RouterModel

        # If any router already handles routing, suppress the warning entirely —
        # the core switch is acting as a pure L2 switch by design.
        router_handles_routing = any(
            isinstance(model, RouterModel)
            and bool(model.get_template("guided_routing").strip())
            for _n, model, _m in devices
        )
        if router_handles_routing:
            return []

        warnings = []
        for name, model, _meta in devices:
            if not isinstance(model, CoreSwitchModel):
                continue
            has_vlans   = bool(model.get_template("guided_vlans").strip())
            has_routing = bool(model.get_template("guided_routing").strip())
            if has_vlans and not has_routing:
                warnings.append(
                    f"Core switch '{name}' has VLANs configured but no routing "
                    "(SVIs / ip routing). Inter-VLAN traffic will not be forwarded."
                )
        return warnings
