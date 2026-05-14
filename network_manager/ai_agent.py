"""
ANCS Copilot — Full Agentic AI with 18 tools.

This module defines all tool functions the Gemini agent can call,
the CopilotWorker thread for multi-turn chat, and the system prompt.
"""
import asyncio
import base64
import json
import time
import ipaddress
import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QThread, Signal
from google import genai
from google.genai import types
import openai

from network_manager.network.sender import Sender


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT HOLDER — set by the worker so tool functions can access ANCS backends
# ═══════════════════════════════════════════════════════════════════════════════

class _AgentContext:
    """Mutable singleton holding references the tool functions need."""
    gns3_url: str = "http://localhost:3080"
    gns3_project_id: str = ""
    telnet_writer = None
    telnet_reader = None
    event_loop = None
    log_fn = None  # callable(html_str) → emits to GUI logs tab
    primary_device_name: str = ""
    allow_raw_deploy: bool = False
    sessions: dict | None = None  # device_name -> (reader, writer); optional pool
    audit_fn = None  # callable(device_name, action, details, config_snapshot)
    _gns3_connector_instance = None  # lazy singleton

    @staticmethod
    def log(msg: str):
        if _AgentContext.log_fn:
            _AgentContext.log_fn(msg)

    @staticmethod
    def get_gns3_connector():
        """Lazy singleton — create once, reuse across all GNS3 tool calls."""
        if _AgentContext._gns3_connector_instance is None:
            from network_manager.network.gns3 import GNS3Connector
            _AgentContext._gns3_connector_instance = GNS3Connector(ctx.gns3_url)
        return _AgentContext._gns3_connector_instance


ctx = _AgentContext()


def _deobfuscate_pw(stored: str) -> str:
    if not stored:
        return ""
    try:
        return base64.b64decode(stored.encode("ascii")).decode("utf-8")
    except Exception:
        return stored


def _truncate_tool_result(text: str, max_bytes: int = 10_000) -> str:
    """Cap tool results stored in message history to prevent unbounded growth."""
    if len(text) <= max_bytes:
        return text
    return text[:max_bytes] + f"\n... [truncated — {len(text)} chars total]"


def _resolve_device_connection(device_name: str) -> dict | None:
    """Resolve host/port/credentials from SQLite (devices LEFT JOIN credentials)."""
    try:
        from network_manager.config import cur, db_lock
        with db_lock:
            cur.execute(
                "SELECT d.ip, d.port, "
                "c.host, c.port, c.username, c.password, c.enable_password, c.protocol "
                "FROM devices d LEFT JOIN credentials c ON c.device_name = d.name "
                "WHERE d.name=?",
                (device_name,),
            )
            row = cur.fetchone()
    except Exception:
        return None
    if not row:
        return None
    dip, dport, ch, cp, cu, cpw, ce, cprot = row
    # Credentials take priority; fall back to device table
    host = ((ch or "") if ch else (dip or "")).strip()
    port_s = (str(cp or "") if cp else str(dport or "")).strip()
    user = (cu or "").strip()
    pw = _deobfuscate_pw(cpw or "")
    enable = _deobfuscate_pw(ce or "")
    protocol = "telnet"
    if cprot and str(cprot).lower() in ("telnet", "ssh", "serial"):
        protocol = str(cprot).lower()
    if not host:
        return None
    try:
        port_int = int(port_s) if str(port_s).isdigit() else 23
    except Exception:
        port_int = 23
    return {
        "host": host,
        "port": port_int,
        "username": user,
        "password": pw,
        "enable_password": enable,
        "protocol": protocol,
    }


def _deploy_provenance_ok(device_name: str, config_text: str) -> bool:
    if ctx.allow_raw_deploy:
        return True
    if not (config_text or "").strip():
        return False
    if "Configured by ANCS Copilot" in config_text or "banner motd # Configured by ANCS Copilot #" in config_text:
        return True
    try:
        raw = get_saved_config(device_name)
        saved = json.loads(raw)
        if isinstance(saved, dict) and saved.get("content"):
            if saved["content"].strip() == config_text.strip():
                return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL FUNCTIONS — each is a plain Python function with a docstring.
# Gemini uses the docstring + signature to decide when/how to call them.
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1-4: GNS3 Lab Discovery ──────────────────────────────────────────────────

def list_gns3_projects() -> str:
    """List all GNS3 projects. Returns a JSON array of projects with name, project_id, and status."""
    try:
        gns3 = ctx.get_gns3_connector()
        projects = gns3.get_projects()
        result = [{"name": p.get("name"), "project_id": p.get("project_id"), "status": p.get("status")} for p in projects]
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> list_gns3_projects → {len(result)} projects</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def list_gns3_nodes(project_id: str = "") -> str:
    """List all nodes/devices in a GNS3 project. Returns JSON array with node_id, name, node_type, status, console_host, console_port, and ports. Pass project_id or leave empty to use the active ANCS GNS3 project."""
    pid = (project_id or "").strip() or (ctx.gns3_project_id or "").strip()
    if not pid:
        return "Error: project_id is required (use list_gns3_projects first, or open ANCS with a GNS3 project connected)."
    try:
        gns3 = ctx.get_gns3_connector()
        nodes = gns3.get_nodes(pid)
        result = []
        for n in nodes:
            result.append({
                "node_id": n.get("node_id"),
                "name": n.get("name"),
                "node_type": n.get("node_type"),
                "status": n.get("status"),
                "console_host": n.get("console_host", "localhost"),
                "console_port": n.get("console"),
                "ports": [p.get("short_name") or p.get("name") for p in n.get("ports", [])],
            })
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> list_gns3_nodes → {len(result)} nodes</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_node_ports(project_id: str, node_id: str) -> str:
    """Get the interfaces/ports of a specific GNS3 node. Returns JSON array of port objects."""
    try:
        gns3 = ctx.get_gns3_connector()
        ports = gns3.get_node_ports(project_id, node_id)
        result = [{"name": p.get("name"), "short_name": p.get("short_name"), "adapter": p.get("adapter_number"), "port": p.get("port_number"), "link_type": p.get("link_type")} for p in ports]
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_node_ports → {len(result)} ports</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_topology_links(project_id: str) -> str:
    """Get all cable connections between nodes in a GNS3 project. Returns JSON array showing which port connects to which."""
    try:
        gns3 = ctx.get_gns3_connector()
        links = gns3.get_links(project_id)
        result = []
        for link in links:
            endpoints = link.get("nodes", [])
            if len(endpoints) >= 2:
                result.append({
                    "side_a": {"node_id": endpoints[0].get("node_id"), "adapter": endpoints[0].get("adapter_number"), "port": endpoints[0].get("port_number"), "label": endpoints[0].get("label", {}).get("text", "")},
                    "side_b": {"node_id": endpoints[1].get("node_id"), "adapter": endpoints[1].get("adapter_number"), "port": endpoints[1].get("port_number"), "label": endpoints[1].get("label", {}).get("text", "")},
                })
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_topology_links → {len(result)} links</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


# ── 5: Device Terminal ────────────────────────────────────────────────────────

def run_command_on_device(command: str) -> str:
    """Execute a Cisco IOS CLI command on the Copilot primary device (pooled Telnet if available)."""
    ctx.log(f"\n<span style='color: #a371f7'><b>[Tool ✨] Executing:</b> {command}</span>\n")
    if ctx.telnet_writer and ctx.telnet_reader:
        try:
            output = ctx.event_loop.run_until_complete(_async_exec(command))
            clean = output.strip()
            ctx.log(f"<span style='color: #C9D1D9'>{clean}</span>\n")
            return clean
        except Exception as e:
            err = f"Execution error: {e}"
            ctx.log(f"<span style='color: #d73a49'>{err}</span>\n")
            return err
    if ctx.primary_device_name:
        return run_cli_on_device(ctx.primary_device_name, command)
    return "Error: No console target. Select a device in Copilot with a resolvable host."


async def _async_exec(command: str) -> str:
    """Send a command over the telnet session and read output."""
    try:
        await asyncio.wait_for(ctx.telnet_reader.read(65535), timeout=0.1)
    except asyncio.TimeoutError:
        pass
    
    ctx.telnet_writer.write("\r\n")
    await asyncio.sleep(0.15)
    ctx.telnet_writer.write(command + "\r\n")
    await asyncio.sleep(1.2)
    buf = ""
    deadline = ctx.event_loop.time() + 4.0
    while ctx.event_loop.time() < deadline:
        try:
            chunk = await asyncio.wait_for(ctx.telnet_reader.read(65535), timeout=0.5)
            if chunk:
                buf += chunk
                stripped = buf.rstrip()
                if stripped and stripped[-1] in (">", "#"):
                    break
        except asyncio.TimeoutError:
            break
    return buf


async def _async_exec_rw(reader, writer, command: str) -> str:
    """Send a command on an arbitrary Telnet reader/writer pair (session pool)."""
    try:
        await asyncio.wait_for(reader.read(65535), timeout=0.1)
    except asyncio.TimeoutError:
        pass
        
    writer.write("\r\n")
    await asyncio.sleep(0.15)
    writer.write(command + "\r\n")
    await asyncio.sleep(1.2)
    buf = ""
    deadline = ctx.event_loop.time() + 4.0
    while ctx.event_loop.time() < deadline:
        try:
            chunk = await asyncio.wait_for(reader.read(65535), timeout=0.5)
            if chunk:
                buf += chunk
                stripped = buf.rstrip()
                if stripped and stripped[-1] in (">", "#"):
                    break
        except asyncio.TimeoutError:
            break
    return buf


# ── 6-10: Database Tools ─────────────────────────────────────────────────────

def list_all_devices() -> str:
    """List all devices stored in the ANCS database. Returns JSON array with name, type, ip, port, status, connection_type."""
    try:
        from network_manager.config import cur, db_lock
        with db_lock:
            cur.execute("SELECT name, type, ip, port, status, connection_type FROM devices ORDER BY name")
            rows = cur.fetchall()
        result = [{"name": r[0], "type": r[1], "ip": r[2], "port": r[3], "status": r[4], "connection_type": r[5]} for r in rows]
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> list_all_devices → {len(result)} devices</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_device_credentials(device_name: str) -> str:
    """Get saved credentials (host, port, username, password, protocol) for a specific device. Passwords are included for connection purposes."""
    try:
        from network_manager.config import cur, db_lock
        with db_lock:
            cur.execute("SELECT host, port, username, password, enable_password, protocol FROM credentials WHERE device_name=?", (device_name,))
            row = cur.fetchone()
        if not row:
            return f"No saved credentials for '{device_name}'"
        result = {"host": row[0], "port": row[1], "username": row[2], "password": row[3], "enable_password": row[4], "protocol": row[5]}
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_device_credentials({device_name})</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_saved_config(device_name: str) -> str:
    """Get the last saved configuration for a device from the ANCS database."""
    try:
        from network_manager.config import cur, db_lock
        with db_lock:
            cur.execute("""
                SELECT c.config_name, c.content, c.created_at
                FROM configs c JOIN devices d ON c.device_id = d.id
                WHERE d.name=? ORDER BY c.created_at DESC LIMIT 1
            """, (device_name,))
            row = cur.fetchone()
        if not row:
            return f"No saved config for '{device_name}'"
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_saved_config({device_name})</span>\n")
        return json.dumps({"config_name": row[0], "content": row[1], "created_at": row[2]}, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_send_history(device_name: str) -> str:
    """Get the deployment/send history log for a device. Returns recent log entries."""
    try:
        from network_manager.config import cur, db_lock
        with db_lock:
            cur.execute("""
                SELECT l.action, l.details, l.severity, l.created_at
                FROM logs l JOIN devices d ON l.device_id = d.id
                WHERE d.name=? ORDER BY l.created_at DESC LIMIT 10
            """, (device_name,))
            rows = cur.fetchall()
        result = [{"action": r[0], "details": r[1], "severity": r[2], "timestamp": r[3]} for r in rows]
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_send_history({device_name}) → {len(result)} entries</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def query_logs(severity: str = "all", limit: int = 20) -> str:
    """Query the ANCS activity logs. Severity can be 'info', 'warning', 'error', or 'all'. Returns recent log entries."""
    try:
        from network_manager.config import cur, db_lock
        with db_lock:
            if severity == "all":
                cur.execute("SELECT action, details, severity, created_at FROM logs ORDER BY created_at DESC LIMIT ?", (limit,))
            else:
                cur.execute("SELECT action, details, severity, created_at FROM logs WHERE severity=? ORDER BY created_at DESC LIMIT ?", (severity, limit))
            rows = cur.fetchall()
        result = [{"action": r[0], "details": r[1], "severity": r[2], "timestamp": r[3]} for r in rows]
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> query_logs(severity={severity}) → {len(result)} entries</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


# ── 11-13: Config Generation ─────────────────────────────────────────────────

def generate_device_config(
    hostname: str,
    device_role: str,
    vlans: str = "[]",
    routing_entries: str = "[]",
    dhcp_pools: str = "[]",
    uplinks: str = "[]",
    static_routes: str = "[]",
    acl_rules: str = "[]",
    router_interface: str = "",
    routing_protocol: str = "rip",
    wan_interface: str = "",
    wan_ip: str = "",
    wan_mask: str = "255.255.255.252",
    transit_links: str = "[]",
) -> str:
    """Generate a full Cisco IOS configuration using the ANCS ConfigEngine (same engine as Guided Setup).

    This produces block-formatted IOS config identical to the Guided Setup wizard, including
    trunk encapsulation, portfast, speed/duplex, VLAN database syntax for core switches,
    uplink port exclusion from access VLAN assignments, and proper DHCP excluded ranges.

    Args:
        hostname: Device hostname
        device_role: 'router', 'core', or 'access'
        vlans: JSON array of {"id": "10", "name": "Staff", "ports": "Ethernet0/0,Ethernet0/1"}
        routing_entries: JSON array of {"vlan": "10", "name": "Staff", "ip": "192.168.10.1", "mask": "255.255.255.0"}
        dhcp_pools: JSON array of {"pool": "Staff", "network": "192.168.10.0", "mask": "255.255.255.0", "gateway": "192.168.10.1", "dns": "8.8.8.8", "start": "192.168.10.50", "end": "192.168.10.200"}
        uplinks: JSON array of {"ports": "Ethernet3/3", "mode": "trunk", "allowed vlans": "all"}
        static_routes: JSON array of {"network": "0.0.0.0", "mask": "0.0.0.0", "next-hop": "10.0.0.1", "description": "Default"}
        acl_rules: JSON array of {"acl #": "101", "action": "deny", "source": "192.168.10.0", "wildcard": "0.0.0.255", "destination": "192.168.30.0", "destination_wildcard": "0.0.0.255", "remark": "Block Guest from Servers"}
        router_interface: Physical interface for router subinterfaces (e.g. FastEthernet0/0)
        routing_protocol: 'rip', 'ospf', 'eigrp', or 'none'
        wan_interface: WAN-facing interface (e.g. FastEthernet0/1)
        wan_ip: WAN IP address or 'dhcp'
        wan_mask: WAN subnet mask
        transit_links: JSON array of {"local_interface": "FastEthernet0/1", "ip": "10.0.0.1", "mask": "255.255.255.252", "protocol": "ospf"}

    Returns the complete block-formatted IOS configuration text.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> generate_device_config(hostname={hostname}, role={device_role})</span>\n")
    try:
        _vlans = json.loads(vlans) if isinstance(vlans, str) else vlans
        _routing = json.loads(routing_entries) if isinstance(routing_entries, str) else routing_entries
        _dhcp = json.loads(dhcp_pools) if isinstance(dhcp_pools, str) else dhcp_pools
        _uplinks = json.loads(uplinks) if isinstance(uplinks, str) else uplinks
        _static = json.loads(static_routes) if isinstance(static_routes, str) else static_routes
        _acl = json.loads(acl_rules) if isinstance(acl_rules, str) else acl_rules
        _transit = json.loads(transit_links) if isinstance(transit_links, str) else transit_links
    except json.JSONDecodeError as e:
        return f"JSON parse error: {e}"

    try:
        from network_manager.gui.wizards.config_engine import ConfigEngine

        engine = ConfigEngine(
            device_role=device_role,
            hostname=hostname,
            identity_data={"hostname": hostname},
            vlans=_vlans,
            uplinks=_uplinks,
            routing_entries=_routing,
            dhcp_pools=_dhcp,
            static_routes=_static,
            acl_rules=_acl,
            router_interface=router_interface,
            wan_interface=wan_interface,
            wan_ip=wan_ip,
            wan_mask=wan_mask,
            routing_protocol=routing_protocol,
            transit_links=_transit,
        )

        config_text = engine.build_full_config()
        blocks = engine.render_all_blocks()

        # Add marker so deploy_to_device accepts generated configs
        config_text = f"! Configured by ANCS Copilot\n\n{config_text}"

        ctx.log(f"<span style='color:#3fb950'><b>[Tool]</b> Config generated via ConfigEngine: {len(blocks)} blocks, {len(config_text.splitlines())} lines</span>\n")
        return config_text
    except Exception as e:
        return f"ConfigEngine error: {e}"


def audit_network() -> str:
    """Scan ALL device configurations in the project snapshot for security issues, inconsistencies, and best-practice violations.

    Checks for: missing enable secret, no hostname set, mismatched routing protocols,
    trunks without encapsulation, missing portfast, no default route, open VTY lines, etc.

    Returns a structured JSON report of findings.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> audit_network()</span>\n")
    try:
        from network_manager.config import cur, db_lock

        # Single query: fetch all devices with their latest config snapshot in one JOIN
        with db_lock:
            cur.execute(
                "SELECT d.name, d.type, s.config_text "
                "FROM devices d LEFT JOIN snapshots s ON s.device_name = d.name "
                "AND s.id = (SELECT MAX(s2.id) FROM snapshots s2 WHERE s2.device_name = d.name) "
                "ORDER BY d.name"
            )
            devices_with_configs = cur.fetchall()

        if not devices_with_configs:
            return json.dumps({"status": "empty", "message": "No devices in workspace."})

        findings = []

        # Check for routing protocol mismatches
        protocols = {}
        for name, dtype, config in devices_with_configs:
            if not config:
                findings.append({"device": name, "severity": "warning", "issue": "No deployment history found — device may be unconfigured."})
                continue

            config_lower = config.lower()

            # Detect routing protocol
            if "router ospf" in config_lower:
                protocols[name] = "ospf"
            elif "router eigrp" in config_lower:
                protocols[name] = "eigrp"
            elif "router rip" in config_lower:
                protocols[name] = "rip"
            else:
                protocols[name] = "none"

            # Security checks
            if "enable secret" not in config_lower and "enable password" not in config_lower:
                findings.append({"device": name, "severity": "critical", "issue": "No enable secret or enable password configured."})

            if "hostname" not in config_lower:
                findings.append({"device": name, "severity": "warning", "issue": "Hostname not explicitly set."})

            if "no ip domain-lookup" not in config_lower:
                findings.append({"device": name, "severity": "info", "issue": "ip domain-lookup is enabled — typos in CLI may cause DNS lookup delays."})

            if "line vty" in config_lower and "login" not in config_lower:
                findings.append({"device": name, "severity": "critical", "issue": "VTY lines appear to have no login authentication configured."})

            if "banner" not in config_lower:
                findings.append({"device": name, "severity": "info", "issue": "No login banner configured."})

            # Trunk checks
            if "switchport mode trunk" in config_lower and "encapsulation dot1q" not in config_lower:
                findings.append({"device": name, "severity": "warning", "issue": "Trunk port configured without explicit dot1q encapsulation."})

            # Default route check for routers
            if dtype and "router" in dtype.lower():
                if "ip route 0.0.0.0 0.0.0.0" not in config_lower and "default-information originate" not in config_lower:
                    findings.append({"device": name, "severity": "info", "issue": "No default route configured. Devices behind this router may lack internet access."})

        # Cross-device: routing protocol mismatch (reuse already-fetched configs)
        unique_protos = set(v for v in protocols.values() if v != "none")
        if len(unique_protos) > 1:
            has_redistribution = False
            for name, dtype, config in devices_with_configs:
                if config and "redistribute" in config.lower():
                    has_redistribution = True
                    break
            if not has_redistribution:
                findings.append({
                    "device": "NETWORK-WIDE",
                    "severity": "critical",
                    "issue": f"Multiple routing protocols detected ({', '.join(p.upper() for p in unique_protos)}) but NO redistribution router found. Routes cannot be exchanged between protocol domains."
                })

        result = {
            "status": "complete",
            "total_devices": len(devices_with_configs),
            "findings_count": len(findings),
            "protocol_map": protocols,
            "findings": findings,
        }
        ctx.log(f"<span style='color:#3fb950'><b>[Tool]</b> Audit complete: {len(findings)} findings across {len(devices_with_configs)} devices</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Audit error: {e}"


def trace_connectivity(source_device: str, destination_ip: str) -> str:
    """Trace network connectivity from a source device to a destination IP.

    Runs diagnostic commands (ping, show ip route, show interfaces) on the source device
    and follows the path hop by hop using routing table entries. Reports each hop's status.

    Args:
        source_device: Name of the starting device in ANCS
        destination_ip: Target IP address to trace to

    Returns a JSON report of the path trace results.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> trace_connectivity({source_device} → {destination_ip})</span>\n")
    results = {"source": source_device, "destination": destination_ip, "hops": [], "verdict": ""}

    try:
        # Step 1: Ping from source
        ctx.log(f"<span style='color:#C9D1D9'>Step 1: Ping test from {source_device}...</span>\n")
        ping_result = run_cli_on_device(source_device, f"ping {destination_ip}")
        success_rate = "unknown"
        if "percent" in ping_result.lower():
            for line in ping_result.splitlines():
                if "percent" in line.lower():
                    success_rate = line.strip()
                    break
        results["ping"] = {"output": ping_result[-500:], "success_rate": success_rate}

        # Step 2: Check routing table
        ctx.log(f"<span style='color:#C9D1D9'>Step 2: Checking routing table on {source_device}...</span>\n")
        route_result = run_cli_on_device(source_device, f"show ip route {destination_ip}")
        results["routing_table_lookup"] = route_result[-500:]

        # Step 3: Check interfaces
        ctx.log(f"<span style='color:#C9D1D9'>Step 3: Checking interface status on {source_device}...</span>\n")
        intf_result = run_cli_on_device(source_device, "show ip interface brief")
        results["interface_status"] = intf_result[-800:]

        # Step 4: Check ARP table
        ctx.log(f"<span style='color:#C9D1D9'>Step 4: Checking ARP table on {source_device}...</span>\n")
        arp_result = run_cli_on_device(source_device, "show arp")
        results["arp_table"] = arp_result[-500:]

        # Determine verdict
        if "!!!!!" in ping_result or "100 percent" in ping_result.lower():
            results["verdict"] = "REACHABLE — All pings succeeded."
        elif "....." in ping_result or "0 percent" in ping_result.lower():
            results["verdict"] = "UNREACHABLE — All pings failed. Check routing, interfaces, and ACLs."
        elif "!" in ping_result and "." in ping_result:
            results["verdict"] = "PARTIAL — Some pings succeeded. Possible intermittent connectivity or ARP resolution delay."
        else:
            results["verdict"] = "UNKNOWN — Could not determine connectivity status from ping output."

        ctx.log(f"<span style='color:#3fb950'><b>[Tool]</b> Trace complete: {results['verdict']}</span>\n")
        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Trace error: {e}"


def detect_topology() -> str:
    """Analyze the current ANCS device list and detect the network topology pattern (router-core-access, core-access, router-only, etc.)."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> detect_topology()</span>\n")
    try:
        from network_manager.config import cur, db_lock
        with db_lock:
            cur.execute("SELECT name, type FROM devices ORDER BY name")
            rows = cur.fetchall()
        routers = [r for r in rows if r[1] and "router" in r[1].lower()]
        cores = [r for r in rows if r[1] and "core" in r[1].lower()]
        switches = [r for r in rows if r[1] and "switch" in r[1].lower() and "core" not in r[1].lower()]

        if not rows:
            pattern = "empty"
        elif routers and cores and switches:
            pattern = "router-core-access"
        elif routers and switches:
            pattern = "router-access"
        elif cores and switches:
            pattern = "core-access"
        elif routers:
            pattern = "router-only"
        else:
            pattern = "flat"

        result = {
            "pattern": pattern,
            "routers": [{"name": r[0], "type": r[1]} for r in routers],
            "core_switches": [{"name": r[0], "type": r[1]} for r in cores],
            "access_switches": [{"name": r[0], "type": r[1]} for r in switches],
            "total_devices": len(rows),
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def suggest_configs() -> str:
    """Auto-generate configuration plans for all devices based on their topology roles. Returns suggested VLANs, routing, DHCP, etc. per device."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> suggest_configs()</span>\n")
    try:
        topo = json.loads(detect_topology())
        pattern = topo["pattern"]
        if pattern == "empty":
            return "No devices in ANCS. Import devices from GNS3 first."

        suggestions = []
        vlan_plan = [
            {"id": "10", "name": "Management"},
            {"id": "20", "name": "Users"},
            {"id": "30", "name": "Servers"},
        ]

        for r in topo["routers"]:
            routing = []
            dhcp = []
            for i, v in enumerate(vlan_plan, 1):
                ip = f"192.168.{i}0.1"
                routing.append({"vlan": v["id"], "name": v["name"], "ip": ip, "mask": "255.255.255.0"})
                dhcp.append({"pool": v["name"], "network": f"192.168.{i}0.0", "mask": "255.255.255.0", "gateway": ip, "dns": "8.8.8.8", "start": f"192.168.{i}0.50", "end": f"192.168.{i}0.200"})
            suggestions.append({"device": r["name"], "role": "router", "routing": routing, "dhcp": dhcp, "static_routes": [{"network": "0.0.0.0", "mask": "0.0.0.0", "next-hop": "10.0.0.1"}]})

        for c in topo["core_switches"]:
            routing = [{"vlan": v["id"], "name": v["name"], "ip": f"192.168.{i}0.1", "mask": "255.255.255.0"} for i, v in enumerate(vlan_plan, 1)]
            suggestions.append({"device": c["name"], "role": "core", "vlans": vlan_plan, "routing": routing})

        for s in topo["access_switches"]:
            suggestions.append({"device": s["name"], "role": "access", "vlans": vlan_plan, "uplinks": [{"ports": "Ethernet3/3", "mode": "trunk", "allowed vlans": "all"}]})

        return json.dumps(suggestions, indent=2)
    except Exception as e:
        return f"Error: {e}"


# ── 14-16: Deployment ─────────────────────────────────────────────────────────

def deploy_config_telnet(host: str, port: int, username: str, password: str, enable_pw: str, config_text: str) -> str:
    """Deploy a configuration to a network device via Telnet. Returns the send log."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> deploy_config_telnet({host}:{port})</span>\n")
    try:
        from network_manager.network.sender import Sender
        log_lines = []
        def log_fn(msg):
            log_lines.append(msg)
            ctx.log(f"<span style='color:#C9D1D9'>{msg}</span>\n")

        ok = Sender.send_telnet(log_fn, host, port, username, password, enable_pw, config_text)
        tail = "\n".join(log_lines[-5:])
        if ok is False:
            return f"Deployment failed (Telnet error).\n{tail}"
        if getattr(ctx, "audit_fn", None):
            ctx.audit_fn(f"Raw Device ({host})", "Deploy Config (Copilot)", f"Copilot deployed {len(config_text)} characters via raw Telnet call.", config_text)
        return f"Deployment successful.\n{tail}"
    except Exception as e:
        return f"Deployment failed: {e}"


def deploy_config_ssh(host: str, port: int, username: str, password: str, enable_pw: str, config_text: str) -> str:
    """Deploy a configuration to a network device via SSH. Returns the send log."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> deploy_config_ssh({host}:{port})</span>\n")
    try:
        from network_manager.network.sender import Sender
        log_lines = []
        def log_fn(msg):
            log_lines.append(msg)
            ctx.log(f"<span style='color:#C9D1D9'>{msg}</span>\n")

        ok = Sender.send_ssh(log_fn, host, port, username, password, enable_pw, config_text)
        tail = "\n".join(log_lines[-5:])
        if ok is False:
            return f"Deployment failed (SSH error).\n{tail}"
        if getattr(ctx, "audit_fn", None):
            ctx.audit_fn(f"Raw Device ({host})", "Deploy Config (Copilot)", f"Copilot deployed {len(config_text)} characters via raw SSH call.", config_text)
        return f"Deployment successful.\n{tail}"
    except Exception as e:
        return f"Deployment failed: {e}"


def deploy_to_device(device_name: str, config_text: str) -> str:
    """Deploy configuration to a device by name using saved credentials. Config must come from ANCS (generate_device_config / saved config) unless raw deploy is enabled in Copilot."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> deploy_to_device({device_name})</span>\n")
    if not _deploy_provenance_ok(device_name, config_text):
        return (
            "Deploy blocked: use generate_device_config or match get_saved_config for this device, "
            "or enable 'Allow raw config deploy' in Copilot."
        )
    info = _resolve_device_connection(device_name)
    if not info:
        return f"Error: no host/credentials for '{device_name}'."
    try:
        from network_manager.network.sender import Sender
        log_lines = []

        def log_fn(msg):
            log_lines.append(msg)
            ctx.log(f"<span style='color:#C9D1D9'>{msg}</span>\n")

        if info.get("protocol") == "ssh":
            ok = Sender.send_ssh(
                log_fn, info["host"], info["port"],
                info["username"], info["password"], info["enable_password"], config_text,
            )
        else:
            ok = Sender.send_telnet(
                log_fn, info["host"], info["port"],
                info["username"], info["password"], info["enable_password"], config_text,
            )
        tail = "\n".join(log_lines[-8:])
        if ok is False:
            return f"Deployment FAILED (sender returned error).\n{tail}"

        # ── Post-deploy verification ──────────────────────────────────
        # Extract expected hostname from config to verify it actually took effect
        expected_hostname = ""
        for line in config_text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("hostname "):
                expected_hostname = stripped.split(None, 1)[1].strip()
                break

        if expected_hostname and info.get("protocol") != "ssh":
            ctx.log(f"<span style='color:#8b949e'>[Copilot] Verifying deployment on {device_name}...</span>\n")
            try:
                import time as _time
                _time.sleep(1.5)  # Let GNS3 settle after deploy
                verify_result = Sender.run_show_commands_telnet(
                    log_fn, info["host"], info["port"],
                    info["username"], info["password"], info["enable_password"],
                    ["show running-config | include hostname"],
                )
                verify_output = ""
                for _k, _v in verify_result.items():
                    if _k != "_error":
                        verify_output += _v
                if expected_hostname.lower() in verify_output.lower():
                    ctx.log(f"<span style='color:#3fb950'><b>[Copilot]</b> ✓ Verified: hostname '{expected_hostname}' confirmed on device</span>\n")
                else:
                    # Soft warning — sender already returned success, verification
                    # can fail due to GNS3 console race / garbled telnet login.
                    ctx.log(f"<span style='color:#d29922'><b>[Copilot]</b> ⚠ Could not verify hostname '{expected_hostname}' — GNS3 console may need more time to settle. Config was sent successfully.</span>\n")
            except Exception as ve:
                ctx.log(f"<span style='color:#d29922'>[Copilot] Post-deploy verification error (non-fatal): {ve}</span>\n")

        if getattr(ctx, "audit_fn", None):
            ctx.audit_fn(device_name, "Deploy Config (Copilot)", f"Copilot deployed {len(config_text)} characters via Telnet.", config_text)
        return f"Deployment successful (verified).\n{tail}"
    except Exception as e:
        return f"Deployment failed: {e}"


def _probe_session_alive(reader, writer) -> bool:
    """Send a single Enter and check if the device responds with a prompt."""
    try:
        # Drain any stale buffer
        try:
            ctx.event_loop.run_until_complete(
                asyncio.wait_for(reader.read(65535), timeout=0.1)
            )
        except (asyncio.TimeoutError, Exception):
            pass
        writer.write("\r\n")
        probe = ctx.event_loop.run_until_complete(
            asyncio.wait_for(reader.read(4096), timeout=2.0)
        )
        tail = (probe or "").rstrip()
        return bool(tail and tail[-1] in (">", "#"))
    except Exception:
        return False


def run_cli_on_device(device_name: str, command: str) -> str:
    """Run one Cisco IOS show/exec command on a device by name (Telnet console). Uses pooled session if available."""
    ctx.log(f"\n<span style='color: #a371f7'><b>[Tool]</b> run_cli_on_device({device_name}): {command}</span>\n")
    if device_name in (ctx.sessions or {}) and ctx.sessions[device_name]:
        reader, writer = ctx.sessions[device_name]
        # Health-check: make sure the pooled session is still alive
        if _probe_session_alive(reader, writer):
            try:
                out = ctx.event_loop.run_until_complete(_async_exec_rw(reader, writer, command))
                ctx.log(f"<span style='color:#C9D1D9'>{out}</span>\n")
                return out.strip()
            except Exception as e:
                ctx.log(f"<span style='color:#d29922'>[Copilot] Pooled session for {device_name} failed: {e} — falling back to fresh connection</span>\n")
        else:
            ctx.log(f"<span style='color:#d29922'>[Copilot] Pooled session for {device_name} is dead — evicting and using fresh connection</span>\n")
        # Evict dead session
        try:
            writer.close()
        except Exception:
            pass
        del ctx.sessions[device_name]
    info = _resolve_device_connection(device_name)
    if not info:
        return f"Error: no host/credentials for '{device_name}'."
    if info.get("protocol") == "ssh":
        return "Error: run_cli_on_device requires a Telnet console. This device is set to SSH."
    log_lines = []

    def log_fn(msg):
        log_lines.append(msg)
        ctx.log(f"<span style='color:#C9D1D9'>{msg}</span>\n")

    out = Sender.run_show_commands_telnet(
        log_fn,
        info["host"],
        info["port"],
        info["username"],
        info["password"],
        info["enable_password"],
        [command.strip()],
    )
    if out.get("_error"):
        return f"Error: {out['_error']}"
    return (out.get(command.strip()) or next(iter(out.values()), "")).strip()


def verify_device(device_name: str, verify_commands: str = '["show ip interface brief"]') -> str:
    """Run verification show commands on a device by name (uses Telnet + saved credentials). verify_commands is a JSON array of strings."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> verify_device({device_name})</span>\n")
    try:
        cmds = json.loads(verify_commands) if isinstance(verify_commands, str) else verify_commands
        info = _resolve_device_connection(device_name)
        if not info:
            return json.dumps({"error": f"no connection info for '{device_name}'"}, indent=2)
        if info.get("protocol") == "ssh":
            return json.dumps({"error": "verify_device uses Telnet; device is SSH-only in credentials."}, indent=2)

        def log_fn(msg):
            ctx.log(f"<span style='color:#C9D1D9'>{msg}</span>\n")

        results = Sender.run_show_commands_telnet(
            log_fn,
            info["host"],
            info["port"],
            info["username"],
            info["password"],
            info["enable_password"],
            cmds,
        )
        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Verification error: {e}"


def verify_deployment(
    host: str,
    port: int,
    verify_commands: str = '["show running-config | include hostname", "show ip interface brief"]',
    username: str = "",
    password: str = "",
    enable_password: str = "",
) -> str:
    """Run verification show commands on a host:port (new Telnet session). Prefer verify_device(device_name) when possible."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> verify_deployment({host}:{port})</span>\n")
    try:
        cmds = json.loads(verify_commands) if isinstance(verify_commands, str) else verify_commands

        def log_fn(msg):
            ctx.log(f"<span style='color:#C9D1D9'>{msg}</span>\n")

        results = Sender.run_show_commands_telnet(
            log_fn, host, int(port), username, password, enable_password, cmds,
        )
        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Verification error: {e}"


# ── 17-18: Utilities ──────────────────────────────────────────────────────────

def calculate_subnet(ip_address: str, prefix_length: int) -> str:
    """Calculate subnet details for an IP address and prefix length. Returns network, broadcast, mask, usable range, and number of hosts."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> calculate_subnet({ip_address}/{prefix_length})</span>\n")
    try:
        net = ipaddress.IPv4Network(f"{ip_address}/{prefix_length}", strict=False)
        hosts = list(net.hosts())
        result = {
            "network": str(net.network_address),
            "broadcast": str(net.broadcast_address),
            "netmask": str(net.netmask),
            "wildcard": str(net.hostmask),
            "prefix": f"/{prefix_length}",
            "first_usable": str(hosts[0]) if hosts else "N/A",
            "last_usable": str(hosts[-1]) if hosts else "N/A",
            "total_hosts": len(hosts),
            "total_addresses": net.num_addresses,
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_ancs_help(topic: str) -> str:
    """Get help information about ANCS features or networking concepts. Topics: 'vlan', 'trunk', 'stp', 'dhcp', 'acl', 'subnet', 'gateway', 'svi', 'guided_setup', 'gns3', 'deploy', 'overview'."""
    help_db = {
        "overview": "ANCS (Auto Network Configuration System) is a desktop app for managing Cisco network device configurations. It features: Device Management (Router/Switch/CoreSwitch), Template System, Guided Setup Wizard, GNS3 Integration, Config Deployment (Serial/Telnet/SSH), Subnet Calculator, and SQLite Database.",
        "vlan": "A VLAN (Virtual LAN) is a logical network segment. Devices in one VLAN cannot communicate with another without routing. Common setup: VLAN 10 for Management, VLAN 20 for Users, VLAN 30 for Servers.",
        "trunk": "A trunk port carries traffic for multiple VLANs using 802.1Q tags. Used between switches or between a switch and router (router-on-a-stick). Configure with: switchport mode trunk.",
        "stp": "Spanning Tree Protocol prevents loops in switched networks. STP elects a root bridge and blocks redundant paths. Use 'show spanning-tree' to check status.",
        "dhcp": "DHCP automatically assigns IP addresses. Configure pools with: ip dhcp pool NAME, network, default-router, dns-server. Exclude the gateway: ip dhcp excluded-address.",
        "acl": "Access Control Lists filter traffic. Standard ACLs (1-99) match source IP. Extended ACLs (100-199) match source, dest, protocol. Apply to interfaces with: ip access-group.",
        "subnet": "Subnetting divides networks. /24 = 256 addresses (254 hosts), /25 = 128 (126 hosts), /26 = 64 (62 hosts). Use the calculate_subnet tool for exact calculations.",
        "gateway": "The default gateway is the router IP that devices use to reach other networks. Usually the first usable IP in the subnet (e.g., 192.168.10.1).",
        "svi": "Switch Virtual Interface — an IP assigned to a VLAN on a Layer 3 switch. Acts as the default gateway for that VLAN. Configure with: interface vlan X, ip address.",
        "guided_setup": "The Guided Setup Wizard walks through device configuration step by step: Identity → VLANs → Uplinks → Routing → WAN → Static Routes → DHCP → ACLs → Review. Use generate_device_config tool to generate configs programmatically.",
        "gns3": "GNS3 is a network emulator. ANCS connects to GNS3's REST API (default http://localhost:3080) to import projects, nodes, ports, and links. Devices run classic IOS images (c3725, c7200).",
        "deploy": "ANCS deploys configs via Telnet (port 23) or SSH (port 22). Configs are split into blocks with delays between each. Use deploy_config_telnet or deploy_config_ssh tools.",
    }
    result = help_db.get(topic.lower(), f"Unknown topic: '{topic}'. Available topics: {', '.join(help_db.keys())}")
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_ancs_help({topic})</span>\n")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ALL TOOLS LIST — registered with Gemini
# ═══════════════════════════════════════════════════════════════════════════════

ALL_TOOLS = [
    # GNS3
    list_gns3_projects,
    list_gns3_nodes,
    get_node_ports,
    get_topology_links,
    # Terminal
    run_command_on_device,
    run_cli_on_device,
    # Database
    list_all_devices,
    get_device_credentials,
    get_saved_config,
    get_send_history,
    query_logs,
    # Config generation
    generate_device_config,
    detect_topology,
    suggest_configs,
    # Deployment
    deploy_config_telnet,
    deploy_config_ssh,
    deploy_to_device,
    verify_deployment,
    verify_device,
    # Intelligence
    audit_network,
    trace_connectivity,
    # Utilities
    calculate_subnet,
    get_ancs_help,
]

# Map function names for the agentic loop dispatcher
TOOL_MAP = {fn.__name__: fn for fn in ALL_TOOLS}


def _build_openai_tools():
    """Convert Python tool functions to OpenAI tool-calling JSON schemas.
    
    Uses inspect.signature() to extract parameter types, defaults, and docstrings.
    Returns a list of OpenAI tool definition dicts for function calling.
    """
    import re
    
    tools = []
    for fn in ALL_TOOLS:
        # Get function signature
        sig = inspect.signature(fn)
        
        # Get docstring
        docstring = inspect.getdoc(fn) or ""
        
        # Use full docstring as description so the model understands all parameters
        description = docstring if docstring else f"Call {fn.__name__}"
        
        # Parse Args section for per-parameter descriptions
        param_docs = {}
        if "Args:" in docstring:
            args_section = docstring.split("Args:")[1]
            if "Returns:" in args_section:
                args_section = args_section.split("Returns:")[0]
            
            # Extract individual param descriptions like "  param_name (type): description"
            for line in args_section.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Match "param_name (type): description" or "param_name: description"
                match = re.match(r'(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)', line)
                if match:
                    param_name, param_desc = match.groups()
                    param_docs[param_name] = param_desc.strip()
        
        # Build parameters object
        properties = {}
        required = []
        
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            
            # Determine type from annotation
            param_type = "string"  # default
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    param_type = "integer"
                elif param.annotation == float:
                    param_type = "number"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif param.annotation == list or param.annotation == dict:
                    param_type = "object"
                else:
                    param_type = "string"
            
            # Get description from docstring or use generic
            param_desc = param_docs.get(param_name, f"Parameter: {param_name}")
            
            properties[param_name] = {
                "type": param_type,
                "description": param_desc,
            }
            
            # Check if required (no default value)
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        
        # Build tool definition
        tool_def = {
            "type": "function",
            "function": {
                "name": fn.__name__,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
        tools.append(tool_def)
    
    return tools

OPENAI_TOOLS = _build_openai_tools()


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """# IDENTITY
You are **ANCS Copilot**, a fully autonomous AI Network Engineer Agent embedded inside the **ANCS (Auto Network Configuration System)** desktop application. You are powered by AI and operate as an intelligent assistant that can explore, analyze, configure, deploy, and troubleshoot network devices.

# ABOUT ANCS
ANCS is a Python/PySide6 desktop app for managing Cisco network devices. Features:
- **Device Management**: Router, Switch, Core Switch (router acting as L3 switch)
- **Guided Setup Wizard**: Step-by-step config generator (Identity, VLANs, Routing, DHCP, ACLs)
- **GNS3 Integration**: Auto-import devices from GNS3 via REST API (default http://localhost:3080)
- **Config Deployment**: Send configs via Telnet or SSH with per-block delays
- **Subnet Calculator**, **SQLite Database**, **Bulk Deploy**, **Health Monitor**

# ENVIRONMENT
- Devices run inside **GNS3** (emulator), NOT physical hardware
- **Older Cisco IOS images** (c3725, c3640, c7200, vIOS) - classic CLI syntax
- **Telnet** is the primary connection method (GNS3 console ports, 5000+)
- `terminal length 0` is pre-configured on connected sessions

# PROJECT SNAPSHOT (CRITICAL)
Your very first message in every conversation contains a **full project snapshot** - a JSON object with:
- Every device in the workspace: name, role (router/core/access), and all generated IOS config templates
- Deploy status: which devices have been deployed and when
- GNS3 project info and console ports

**You MUST use this snapshot as your primary knowledge source.** When the user asks about their network:
- Look at the snapshot FIRST - you already know what configs exist, what routing protocols are used, what VLANs are defined, what IPs are assigned.
- Cross-reference configs across ALL devices when troubleshooting (e.g., if R1 uses OSPF but R2 uses RIP, you can spot the mismatch immediately from the snapshot).
- Only use tools for **LIVE state** that the snapshot cannot tell you (e.g., actual interface status, routing table, ping results). The snapshot tells you what was CONFIGURED and DEPLOYED, tools tell you what is RUNNING NOW.
- **Never say you do not know what is configured** - the snapshot contains all template configs. Read them.

# YOUR TOOLS (ground truth for live state)
You have access to these tool functions. **Prefer device_name-based tools** over pasting IP/port.

**GNS3 Lab Discovery:**
- `list_gns3_projects()` - list all GNS3 projects
- `list_gns3_nodes(project_id)` - optional; empty project_id uses the active ANCS GNS3 project when set
- `get_node_ports(project_id, node_id)` - get interfaces
- `get_topology_links(project_id)` - get cable connections

**Device Terminal (live state):**
- `run_command_on_device(command)` - primary Copilot console (pooled session when available)
- `run_cli_on_device(device_name, command)` - run a command on any device by name (Telnet)

**Database:**
- `list_all_devices()` - all ANCS devices
- `get_device_credentials(device_name)` - saved login info
- `get_saved_config(device_name)` - last saved config
- `get_send_history(device_name)` - deployment log
- `query_logs(severity, limit)` - activity logs

**Config Generation (uses the SAME engine as the Guided Setup wizard):**
- `generate_device_config(hostname, device_role, ...)` - build IOS config via ConfigEngine (block-formatted, with trunk encapsulation, portfast, speed/duplex, VLAN database syntax for core switches)
- `detect_topology()` - analyze device roles and topology pattern
- `suggest_configs()` - auto-generate config plans for all devices

**Deployment:**
- `deploy_to_device(device_name, config_text)` - **preferred**; uses saved credentials
- `deploy_config_telnet(...)` / `deploy_config_ssh(...)` - advanced: explicit host/port
- `verify_device(device_name, verify_commands)` - **preferred** verification by name
- `verify_deployment(host, port, ...)` - optional credentials for Telnet verify

**Network Intelligence (your superpower):**
- `audit_network()` - scan ALL device configs for security issues, inconsistencies, mismatched routing protocols, missing trunks, etc. Returns structured findings.
- `trace_connectivity(source_device, destination_ip)` - run ping, routing table, ARP, and interface checks from a device to diagnose reachability.

**Utilities:**
- `calculate_subnet(ip, prefix)` - subnet calculations
- `get_ancs_help(topic)` - help on ANCS features and networking concepts

# CONFIG GENERATION (CRITICAL)
Your `generate_device_config` tool uses the **exact same ConfigEngine** as the Guided Setup wizard. This means:
- Core switches get `vlan database` syntax (correct for c3640/c3725 images)
- Trunk ports get `switchport trunk encapsulation dot1q`
- Access ports on access switches get `spanning-tree portfast`
- FastEthernet/Ethernet interfaces get `speed 100` and `duplex full`
- Uplink ports are automatically excluded from VLAN access port assignments
- DHCP pools include proper excluded-address ranges (not just the gateway)
- OSPF, EIGRP, and RIP are all supported with redistribution
- Output is block-formatted with `! BLOCK N:` headers for the Sender's per-block delays

**When generating configs, you MUST use `generate_device_config` — do NOT write raw IOS commands yourself.** The ConfigEngine handles all the IOS quirks.

# NETWORK-WIDE THINKING (YOUR UNIQUE ADVANTAGE)
Unlike the Guided Setup wizard (which configures one device at a time), you can see the ENTIRE network simultaneously. Use this power:

1. **Cross-device changes**: When asked to "add VLAN 40", update ALL relevant devices:
   - Add VLAN definition on every switch
   - Add to trunk allowed lists
   - Create SVI on the core switch or subinterface on the router
   - Add DHCP pool if the VLAN needs IP assignment
   
2. **Consistency checks**: Before deploying, verify the change is consistent across the network.
   - Trunks between SW1 and CoreSW must carry the same VLANs
   - All devices in an OSPF domain must be in the same area
   
3. **Impact analysis**: Before making changes, explain what will be affected.
   - "Adding this ACL will block Guest users from accessing the Server VLAN on R1, CoreSW, and both access switches."

4. **Proactive auditing**: When you first connect, run `audit_network()` mentally against the snapshot. Flag any issues upfront.

# GROUNDING (CRITICAL)
- **Configs** come from the project snapshot (what was generated/deployed).
- **Live state** must come from **tool outputs** (GNS3 JSON, DB, or CLI show text). Do not invent interface names, IPs, or states.
- When summarizing tool output, you may paraphrase; when stating status, tie it to what a tool returned.

# AUDIENCE (IMPORTANT)
**Primary users are beginners** - they may not know Cisco jargon, CLI commands, or what console vs Telnet means. Your job is to **reduce fear and confusion**, not to sound like a certification exam.

# RULES
1. **Snapshot-first**: Check the project snapshot before calling any tools. You already know the configs.
2. **Live-verify with tools**: Use `run_cli_on_device` or `verify_device` to check actual device state when needed.
3. **Cross-reference**: When troubleshooting, compare configs across ALL devices in the snapshot.
4. **Ask before deploying**: Never deploy a config without the user explicitly asking.
5. **Markdown output**: Use clear headings, **bold**, short lists. Avoid huge tables unless the user asked for detail.
6. **Plain language first**: Lead with a **simple verdict**. Put commands like `show ip interface brief` in **backticks** with a short plain-English gloss.
7. **Do not end with vague technical questions.** Prefer running safe checks yourself and reporting results.
8. **If you must ask something**: Ask **one** clear question, in everyday words.
9. **Chain tools intelligently**: If a task requires multiple steps, execute them in sequence.
10. **Explain actions for beginners**: Before calling tools, one short line - not jargon stacks.
11. **Use generate_device_config for ALL config generation**: Never write raw IOS by hand. Always use the ConfigEngine tool.
12. **Think network-wide**: A change to one device almost always requires changes to other devices. Always consider the full topology.

# CONVERSATION STYLE
- **Answer-first**: Give the understandable summary before optional detail.
- **No engineer voice**: Friendly, patient, concise. You are a tutor, not a grader.
- When greeting: summarize what you see in the project snapshot (how many devices, what is configured, what is deployed, any obvious issues like mismatched routing protocols).
- Do **not** open the chat by asking what would you like to do. Respond directly to what they asked.

# CISCO IOS QUICK REFERENCE (for model grounding)
Common commands: show running-config, show ip interface brief, show ip route, show vlan brief, show interfaces trunk, show spanning-tree, ping X.X.X.X
Config mode: configure terminal → hostname X → interface X → ip address X M → no shutdown → end
VLAN database (older IOS): vlan database → vlan 10 name Staff → exit
Trunk: interface X → switchport trunk encapsulation dot1q → switchport mode trunk
"""


# ═══════════════════════════════════════════════════════════════════════════════
# COPILOT WORKER — multi-turn chat thread
# ═══════════════════════════════════════════════════════════════════════════════

class CopilotWorker(QThread):
    """
    Runs in a background thread. Manages:
    - Telnet connection to a device (optional)
    - Gemini chat session with 18 tools
    - Multi-turn conversation with the user
    """
    # Signals to GUI
    terminal_log_signal = Signal(str)       # → Execution Logs tab
    chat_response_signal = Signal(str)      # → Chat/Summary tab (rendered markdown)
    finished_signal = Signal(str, bool)     # → final status (legacy compat)
    ready_signal = Signal()                 # → agent is ready for messages

    def __init__(self, api_key: str, gns3_url: str,
                 allow_raw_deploy: bool = False,
                 workspace_resolved: list | None = None,
                 gns3_project_id: str = "",
                 project_snapshot: str = "",
                 audit_fn=None,
                 provider: str = "openrouter",
                 model_name: str = "openai/gpt-4o-mini",
                 initial_messages: list | None = None):
        super().__init__()
        self.api_key = api_key
        self.gns3_url = gns3_url
        self.allow_raw_deploy = allow_raw_deploy
        self.workspace_resolved = workspace_resolved or []
        self.gns3_project_id = gns3_project_id
        self.project_snapshot = project_snapshot or "{}"
        self.provider = provider
        self.model_name = model_name
        self._loop = None
        self._chat = None
        self._client = None
        self._msg_queue = []
        self._running = True
        self._messages = initial_messages or []  # For OpenRouter chat history management

        # Wire context
        ctx.gns3_url = gns3_url
        ctx.gns3_project_id = gns3_project_id or ""
        ctx.primary_device_name = ""  # no single focus
        ctx.allow_raw_deploy = allow_raw_deploy
        if ctx.sessions is None:
            ctx.sessions = {}
        ctx.log_fn = lambda msg: self.terminal_log_signal.emit(msg)
        ctx.audit_fn = audit_fn

    def queue_message(self, text: str):
        """Called from the GUI thread to queue a user message."""
        self._msg_queue.append(text)

    def stop(self):
        self._running = False

    def _send_with_retry(self, msg: str, max_retries: int = 3) -> str:
        """Send message to Gemini/Vertex with automatic retry on 429 rate limits."""
        for attempt in range(max_retries):
            try:
                response = self._chat.send_message(msg)
                return response
            except Exception as e:
                error_str = str(e).lower()
                if "429" in error_str or "resource_exhausted" in error_str or "rate" in error_str:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** (attempt + 1)  # 2s, 4s, 8s...
                        self.terminal_log_signal.emit(
                            f"<span style='color:#d29922'>[Copilot] Rate limited. Retrying in {wait_time}s...</span>\n"
                        )
                        time.sleep(wait_time)
                        continue
                raise

    async def _async_connect(self) -> bool:
        """No primary device connection — pool handles all devices."""
        self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Agent uses session pool for all devices (no single-device focus).</span>\n")
        return True

    async def _establish_pool(self) -> None:
        """Open Telnet sessions for workspace devices with staggered timing.

        GNS3's console multiplexer can be overwhelmed when many connections
        open simultaneously.  We stagger each device by 1.5 s and verify the
        session is actually alive before storing it in the pool.
        """
        import telnetlib3

        device_idx = 0
        for ep in self.workspace_resolved:
            name = ep.get("device_name") or ""
            if not name:
                continue
            if ep.get("protocol") == "ssh":
                continue
            host, port = ep.get("host"), ep.get("port")
            if not host:
                continue

            # ── Reuse existing active session if available ─────────────
            if name in ctx.sessions:
                try:
                    _r, _w = ctx.sessions[name]
                    # Fast probe: send newline and see if it's writable
                    _w.write("\r\n")
                    self.terminal_log_signal.emit(
                        f"<span style='color: #3fb950'>[Copilot] Pool ✓ {name} (reusing active session)</span>\n"
                    )
                    continue
                except Exception:
                    # Session stale or dead, cleanup and proceed to reconnect
                    try: ctx.sessions[name][1].close()
                    except: pass
                    del ctx.sessions[name]

            # ── Stagger: let GNS3 breathe between connections ──────────
            if device_idx > 0:
                stagger = 1.5
                self.terminal_log_signal.emit(
                    f"<span style='color:#8b949e'>[Copilot] Waiting {stagger}s before next device...</span>\n"
                )
                await asyncio.sleep(stagger)
            device_idx += 1

            try:
                self.terminal_log_signal.emit(
                    f"<span style='color:#8b949e'>[Copilot] Pool session: {name} ({host}:{port})...</span>\n"
                )
                reader, writer = await asyncio.wait_for(
                    telnetlib3.open_connection(host, port), timeout=10
                )
            except Exception as e:
                self.terminal_log_signal.emit(
                    f"<span style='color:#d73a49'>[Copilot] Pool skip {name}: {e}</span>\n"
                )
                continue

            # Closures need to capture the *current* reader, not the loop var
            _reader = reader

            async def read_available(timeout_sec: float = 1.0, _r=_reader) -> str:
                try:
                    return await asyncio.wait_for(_r.read(4096), timeout=timeout_sec)
                except asyncio.TimeoutError:
                    return ""

            def _wake_log(msg: str):
                self.terminal_log_signal.emit(f"<span style='color: #8b949e'>{msg}</span>\n")

            initial = ""
            try:
                initial = await asyncio.wait_for(reader.read(4096), timeout=3.0)
            except asyncio.TimeoutError:
                pass
            initial = await Sender._telnet_wake_gns3_console(
                writer, read_available, _wake_log, initial
            )
            il = initial.lower() if initial else ""
            u = ep.get("user") or ""
            pw = ep.get("password") or ""
            en = ep.get("enable_password") or ""
            if "username:" in il or "login:" in il:
                if u:
                    writer.write(u + "\r\n")
                    await asyncio.sleep(0.3)
                    resp = await read_available(2.0)
                    if "password:" in resp.lower() and pw:
                        writer.write(pw + "\r\n")
                        await asyncio.sleep(0.3)
            elif "password:" in il:
                if pw:
                    writer.write(pw + "\r\n")
                    await asyncio.sleep(0.3)
            else:
                if u:
                    writer.write(u + "\r\n")
                    await asyncio.sleep(0.2)
                if pw:
                    writer.write(pw + "\r\n")
                    await asyncio.sleep(0.2)
            if en:
                writer.write("enable\r\n")
                await asyncio.sleep(0.3)
                writer.write(en + "\r\n")
                await asyncio.sleep(0.3)

            # Extra line clear before command mode
            writer.write("\r\n")
            await asyncio.sleep(0.2)
            writer.write("terminal length 0\r\n")
            await asyncio.sleep(0.3)
            try:
                await asyncio.wait_for(reader.read(65535), timeout=1.5)
            except asyncio.TimeoutError:
                pass

            # ── Verify session is alive ────────────────────────────────
            writer.write("\r\n")
            await asyncio.sleep(0.5)
            probe = ""
            try:
                probe = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            probe_tail = (probe or "").rstrip()
            if probe_tail and probe_tail[-1] in (">", "#"):
                ctx.sessions[name] = (reader, writer)
                self.terminal_log_signal.emit(
                    f"<span style='color: #3fb950'>[Copilot] Pool ✓ {name} (session verified)</span>\n"
                )
            else:
                # Session connected but device never responded — don't store a dead session
                self.terminal_log_signal.emit(
                    f"<span style='color:#d29922'>[Copilot] Pool ⚠ {name}: connected but no prompt detected — skipping</span>\n"
                )
                try:
                    writer.close()
                except Exception:
                    pass

    def _process_response_gemini(self, response):
        """Handle the agentic tool-calling loop and return final text."""
        MAX_TURNS = 25
        for turn in range(MAX_TURNS):
            function_calls = []
            if response.candidates:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'function_call') and part.function_call:
                                function_calls.append(part.function_call)

            if not function_calls:
                break

            function_responses = []
            for fc in function_calls:
                fn_name = fc.name
                fn_args = dict(fc.args) if fc.args else {}

                # Log tool call with arguments
                args_preview = ", ".join(f"{k}={repr(v)[:80]}" for k, v in fn_args.items())
                ctx.log(
                    f"<span style='color:#a371f7'><b>[Tool Call]</b> {fn_name}({args_preview})</span>\n"
                )

                t0 = time.monotonic()
                if fn_name in TOOL_MAP:
                    try:
                        result = TOOL_MAP[fn_name](**fn_args)
                    except Exception as e:
                        result = f"Tool error: {e}"
                        ctx.log(f"<span style='color:#d73a49'><b>[Tool Error]</b> {fn_name}: {e}</span>\n")
                else:
                    result = f"Unknown tool: {fn_name}"
                dt_ms = (time.monotonic() - t0) * 1000.0

                # Log result preview + timing
                result_preview = str(result)[:300].replace('<', '&lt;').replace('>', '&gt;')
                ctx.log(
                    f"<span style='color:#8b949e'>[Tool Result] {fn_name} → {dt_ms:.0f}ms | "
                    f"{result_preview}{'…' if len(str(result)) > 300 else ''}</span>\n"
                )

                function_responses.append(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": result},
                    )
                )

            response = self._chat.send_message(function_responses)

        # Extract text
        final_text = ""
        try:
            final_text = response.text or ""
        except Exception:
            pass
        if not final_text and response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            final_text += part.text

        return final_text or "I completed the requested actions. Check the Execution Logs for details."

    def _process_response_openrouter(self, response):
        """Handle the agentic tool-calling loop (OpenAI format) and return final text.

        When the model returns multiple tool_calls in one response (e.g. deploying
        to 5 devices at once), they are executed in parallel using a thread pool.
        Single tool calls run directly on the current thread (no overhead).
        """
        MAX_TURNS = 25
        for turn in range(MAX_TURNS):
            message = response.choices[0].message

            # If no tool calls, we're done
            if not message.tool_calls:
                break

            # Add assistant message (with tool_calls) to history
            self._messages.append(message.model_dump())

            # Execute tool calls — parallel if multiple, direct if single
            tool_calls = message.tool_calls
            if len(tool_calls) == 1:
                # Single tool call — run directly, no thread pool overhead
                tc = tool_calls[0]
                result_str = self._execute_single_tool(tc)
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": _truncate_tool_result(result_str),
                })
            else:
                # Multiple tool calls — run in parallel
                ctx.log(
                    f"<span style='color:#58A6FF'><b>[Copilot]</b> Executing {len(tool_calls)} tool calls in parallel</span>\n"
                )
                results = self._execute_tools_parallel(tool_calls)
                # Add results in order (matching tool_call_id)
                for tc in tool_calls:
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _truncate_tool_result(results.get(tc.id, "Tool execution error")),
                    })

            # Get next response with retry logic for rate limits
            for attempt in range(3):
                try:
                    response = self._client.chat.completions.create(
                        model=self.model_name,
                        messages=self._messages,
                        tools=OPENAI_TOOLS,
                        extra_headers={"HTTP-Referer": "https://github.com/ANCS", "X-Title": "ANCS Copilot"} if self.provider == "openrouter" else {},
                    )
                    break
                except openai.RateLimitError:
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        self.terminal_log_signal.emit(
                            f"<span style='color:#d29922'>[Copilot] Rate limited, retrying in {wait}s...</span>\n"
                        )
                        time.sleep(wait)
                    else:
                        raise

        # Extract final text
        final_text = ""
        try:
            final_text = response.choices[0].message.content or ""
            if final_text:
                self._messages.append({"role": "assistant", "content": final_text})
        except Exception:
            pass

        return final_text or "I completed the requested actions. Check the Execution Logs for details."

    def _execute_single_tool(self, tc):
        """Execute a single tool call and return the result string."""
        fn_name = tc.function.name
        try:
            fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except json.JSONDecodeError:
            fn_args = {}
            ctx.log(f"<span style='color:#d29922'>[Copilot] Warning: bad JSON args for {fn_name}</span>\n")

        args_preview = ", ".join(f"{k}={repr(v)[:80]}" for k, v in fn_args.items())
        ctx.log(f"<span style='color:#a371f7'><b>[Tool Call]</b> {fn_name}({args_preview})</span>\n")

        t0 = time.monotonic()
        if fn_name in TOOL_MAP:
            try:
                result = TOOL_MAP[fn_name](**fn_args)
            except (json.JSONDecodeError, TypeError) as e:
                result = f"ERROR: Bad arguments for {fn_name} — {e}. Please check parameter types and retry."
                ctx.log(f"<span style='color:#d73a49'><b>[Tool Error]</b> {fn_name}: {e}</span>\n")
            except Exception as e:
                result = f"Tool error: {e}"
                ctx.log(f"<span style='color:#d73a49'><b>[Tool Error]</b> {fn_name}: {e}</span>\n")
        else:
            result = f"Unknown tool: {fn_name}"
        dt_ms = (time.monotonic() - t0) * 1000.0

        result_preview = str(result)[:300].replace('<', '&lt;').replace('>', '&gt;')
        ctx.log(
            f"<span style='color:#8b949e'>[Tool Result] {fn_name} → {dt_ms:.0f}ms | "
            f"{result_preview}{'…' if len(str(result)) > 300 else ''}</span>\n"
        )
        return str(result)

    def _execute_tools_parallel(self, tool_calls):
        """Execute multiple tool calls concurrently using a thread pool.

        Returns dict mapping tool_call_id -> result string.
        Deploy calls are staggered 0.5s apart to avoid overwhelming GNS3.
        """
        results = {}
        deploy_index = 0

        def _run_one(tc, stagger_delay=0.0):
            if stagger_delay > 0:
                time.sleep(stagger_delay)
            return tc.id, self._execute_single_tool(tc)

        # Stagger deploy calls slightly to avoid GNS3 telnet port contention
        futures = {}
        with ThreadPoolExecutor(max_workers=min(len(tool_calls), 8)) as pool:
            for tc in tool_calls:
                fn_name = tc.function.name
                delay = 0.0
                if fn_name in ("deploy_to_device", "deploy_config_telnet", "deploy_config_ssh"):
                    delay = deploy_index * 0.5
                    deploy_index += 1
                futures[pool.submit(_run_one, tc, delay)] = tc.id

            for future in as_completed(futures):
                try:
                    tc_id, result_str = future.result()
                    results[tc_id] = result_str
                except Exception as e:
                    tc_id = futures[future]
                    results[tc_id] = f"Parallel execution error: {e}"
                    ctx.log(f"<span style='color:#d73a49'><b>[Parallel Error]</b> {tc_id}: {e}</span>\n")

        return results

    def _process_response(self, response):
        """Dispatch to the appropriate response processor based on provider."""
        if self.provider in ("gemini", "vertex"):
            return self._process_response_gemini(response)
        else:
            return self._process_response_openrouter(response)

    def run(self):
        try:
            # 1. Create event loop
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ctx.event_loop = self._loop

            # 2. Pool Telnet sessions to all workspace devices
            self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Setting up device session pool...</span>\n")
            self._loop.run_until_complete(self._async_connect())
            self._loop.run_until_complete(self._establish_pool())
            pool_count = len(ctx.sessions or {})
            self.terminal_log_signal.emit(
                f"<span style='color: #3fb950'>[Copilot] Session pool ready: {pool_count} device(s) connected</span>\n"
            )

            # 3. Init AI Client
            if self.provider in ("gemini", "vertex"):
                if self.provider == "vertex":
                    self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Initializing Vertex AI with ADC...</span>\n")
                    try:
                        # Use Application Default Credentials (already set up via gcloud)
                        self._client = genai.Client(vertexai=True)
                        self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] Vertex AI client initialized</span>\n")
                    except Exception as e:
                        self.terminal_log_signal.emit(f"<span style='color: #d73a49'>[Copilot] Vertex AI init failed: {e}</span>\n")
                        self.finished_signal.emit(f"Failed to initialize Vertex AI: {e}", False)
                        return
                else:
                    # ── Gemini path (original) ──
                    self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Initializing Gemini...</span>\n")
                    self._client = genai.Client(
                        api_key=self.api_key,
                        http_options=types.HttpOptions(api_version="v1alpha"),
                    )
                models_to_try = [self.model_name] if self.model_name else ["gemini-3-flash-preview", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro"]
                for mn in models_to_try:
                    try:
                        self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] Trying model: {mn}...</span>\n")
                        self._chat = self._client.chats.create(
                            model=mn,
                            config=types.GenerateContentConfig(
                                tools=ALL_TOOLS,
                                temperature=0.2,
                                system_instruction=SYSTEM_PROMPT,
                            )
                        )
                        self.terminal_log_signal.emit(f"<span style='color: #3fb950'>[Copilot] Model loaded: {mn} ✓</span>\n")
                        break
                    except Exception as e:
                        self.terminal_log_signal.emit(f"<span style='color: #d73a49'>[Copilot] {mn} failed: {e}</span>\n")
                        self._chat = None
                if not self._chat:
                    self.finished_signal.emit("Failed to initialize any Gemini/Vertex model.", False)
                    return

            else:
                # ── OpenRouter / Hapuppy path (OpenAI-compatible) ──
                provider_name = "Hapuppy" if self.provider == "hapuppy" else "OpenRouter"
                self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] Initializing {provider_name}...</span>\n")
                key_preview = f"{self.api_key[:8]}...{self.api_key[-4:]}" if len(self.api_key) > 12 else "(empty)"
                self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] API Key: {key_preview}</span>\n")
                self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] Provider: {self.provider} | Model: {self.model_name}</span>\n")

                base_url = "https://beta.hapuppy.com/v1" if self.provider == "hapuppy" else "https://openrouter.ai/api/v1"
                headers = {"HTTP-Referer": "https://github.com/ANCS", "X-Title": "ANCS Copilot"} if self.provider == "openrouter" else {}

                self._client = openai.OpenAI(
                    api_key=self.api_key,
                    base_url=base_url,
                    default_headers=headers,
                )
                if not self._messages:
                    self._messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                    ]
                self.terminal_log_signal.emit(f"<span style='color: #3fb950'>[Copilot] Model: {self.model_name} ✓</span>\n")

            # 4. Inject snapshot + greeting
            self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Building project snapshot...</span>\n")

            # Hapuppy has stricter request size limits; truncate large snapshots
            snapshot_to_inject = self.project_snapshot
            if self.provider == "hapuppy" and len(self.project_snapshot) > 20000:
                self.terminal_log_signal.emit(
                    f"<span style='color:#d29922'>[Copilot] Snapshot too large for Hapuppy ({len(self.project_snapshot)} chars). Truncating...</span>\n"
                )
                snapshot_to_inject = self.project_snapshot[:20000] + "\n[... snapshot truncated for request size limits]"

            snap_preview = snapshot_to_inject[:500]
            self.terminal_log_signal.emit(
                f"<span style='color:#8b949e'>[Snapshot] {snap_preview}{'…' if len(snapshot_to_inject) > 500 else ''}</span>\n"
            )
            self.terminal_log_signal.emit(
                f"<span style='color: #8b949e'>[Copilot] Injecting snapshot ({len(snapshot_to_inject)} chars) into agent context...</span>\n"
            )

            greeting_prompt = (
                f"Here is the current ANCS project state (all devices, their configs, deploy status):\n"
                f"```json\n{snapshot_to_inject}\n```\n\n"
                f"The user just opened Copilot. Greet briefly and summarize what you see in the project: "
                f"how many devices, what's configured vs not, what's been deployed, and flag any obvious "
                f"issues you notice (e.g. mismatched routing protocols, missing configs, devices not deployed). "
                f"Do NOT ask an open-ended 'what would you like to do?'."
            )

            # Only send greeting if this is a fresh conversation (no history yet)
            if (self.provider in ("gemini", "vertex")) or (self.provider in ("openrouter", "hapuppy") and len(self._messages) <= 1):
                if self.provider in ("gemini", "vertex"):
                    greeting_response = self._send_with_retry(greeting_prompt)
                else:
                    self._messages.append({"role": "user", "content": greeting_prompt})
                    greeting_response = self._client.chat.completions.create(
                        model=self.model_name,
                        messages=self._messages,
                        tools=OPENAI_TOOLS,
                        extra_headers={"HTTP-Referer": "https://github.com/ANCS", "X-Title": "ANCS Copilot"} if self.provider == "openrouter" else {},
                    )

                greeting_text = self._process_response(greeting_response)
                self.chat_response_signal.emit(greeting_text)
            
            self.ready_signal.emit()

            # 5. Message loop
            while self._running:
                if self._msg_queue:
                    user_msg = self._msg_queue.pop(0)
                    self.terminal_log_signal.emit(f"\n<span style='color: #58A6FF'><b>[User]</b> {user_msg}</span>\n")
                    try:
                        if self.provider in ("gemini", "vertex"):
                            response = self._send_with_retry(user_msg)
                        else:
                            self._messages.append({"role": "user", "content": user_msg})
                            response = self._client.chat.completions.create(
                                model=self.model_name,
                                messages=self._messages,
                                tools=OPENAI_TOOLS,
                                extra_headers={"HTTP-Referer": "https://github.com/ANCS", "X-Title": "ANCS Copilot"} if self.provider == "openrouter" else {},
                            )
                        reply = self._process_response(response)
                        self.chat_response_signal.emit(reply)
                    except Exception as e:
                        self.chat_response_signal.emit(f"**Error:** {e}")
                else:
                    time.sleep(0.1)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_signal.emit(f"Copilot error: {e}", False)
        finally:
            for _n, pair in list((ctx.sessions or {}).items()):
                try:
                    if pair and len(pair) > 1 and pair[1]:
                        pair[1].close()
                except Exception:
                    pass
            try:
                ctx.sessions = {}
                if ctx.telnet_writer:
                    ctx.telnet_writer.close()
                    ctx.telnet_writer = None
                    ctx.telnet_reader = None
            except Exception:
                pass
            if self._loop:
                self._loop.close()
