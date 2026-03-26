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
from PySide6.QtCore import QThread, Signal
from google import genai
from google.genai import types

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

    @staticmethod
    def log(msg: str):
        if _AgentContext.log_fn:
            _AgentContext.log_fn(msg)


ctx = _AgentContext()


def _deobfuscate_pw(stored: str) -> str:
    if not stored:
        return ""
    try:
        return base64.b64decode(stored.encode("ascii")).decode("utf-8")
    except Exception:
        return stored


def _resolve_device_connection(device_name: str) -> dict | None:
    """Resolve host/port/credentials from SQLite (devices + credentials)."""
    try:
        from network_manager.config import cur, db_lock
        with db_lock:
            cur.execute("SELECT ip, port FROM devices WHERE name=?", (device_name,))
            drow = cur.fetchone()
            cur.execute(
                "SELECT host, port, username, password, enable_password, protocol "
                "FROM credentials WHERE device_name=?",
                (device_name,),
            )
            crow = cur.fetchone()
    except Exception:
        return None
    dip, dport = "", ""
    if drow:
        dip = (drow[0] or "").strip()
        dport = str(drow[1] or "").strip()
    host, port_s, user, pw, enable, protocol = "", "", "", "", "", "telnet"
    if crow:
        ch, cp, cu, cpw, ce, cprot = crow
        host = (ch or "").strip()
        port_s = str(cp or "").strip()
        user = (cu or "").strip()
        pw = _deobfuscate_pw(cpw or "")
        enable = _deobfuscate_pw(ce or "")
        if cprot and str(cprot).lower() in ("telnet", "ssh", "serial"):
            protocol = str(cprot).lower()
    if not host and dip:
        host = dip
    if not port_s and dport:
        port_s = dport
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
        from network_manager.network.gns3 import GNS3Connector
        gns3 = GNS3Connector(ctx.gns3_url)
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
        from network_manager.network.gns3 import GNS3Connector
        gns3 = GNS3Connector(ctx.gns3_url)
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
        from network_manager.network.gns3 import GNS3Connector
        gns3 = GNS3Connector(ctx.gns3_url)
        ports = gns3.get_node_ports(project_id, node_id)
        result = [{"name": p.get("name"), "short_name": p.get("short_name"), "adapter": p.get("adapter_number"), "port": p.get("port_number"), "link_type": p.get("link_type")} for p in ports]
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_node_ports → {len(result)} ports</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_topology_links(project_id: str) -> str:
    """Get all cable connections between nodes in a GNS3 project. Returns JSON array showing which port connects to which."""
    try:
        from network_manager.network.gns3 import GNS3Connector
        gns3 = GNS3Connector(ctx.gns3_url)
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
    enable_password: str = "cisco",
    vlans: str = "[]",
    routing_entries: str = "[]",
    dhcp_pools: str = "[]",
    uplinks: str = "[]",
    static_routes: str = "[]",
    acl_rules: str = "[]",
    router_interface: str = "FastEthernet0/0",
    enable_rip: bool = False,
    rip_networks: str = "[]",
) -> str:
    """Generate a full Cisco IOS configuration using the ANCS Guided Setup engine.

    Args:
        hostname: Device hostname
        device_role: 'router', 'core', or 'access'
        enable_password: Enable secret password
        vlans: JSON array of {"id": "10", "name": "Staff", "ports": "Ethernet0/0-3"}
        routing_entries: JSON array of {"vlan": "10", "name": "Staff", "ip": "192.168.10.1", "mask": "255.255.255.0"}
        dhcp_pools: JSON array of {"pool": "Staff", "network": "192.168.10.0", "mask": "255.255.255.0", "gateway": "192.168.10.1", "dns": "8.8.8.8", "start": "192.168.10.50", "end": "192.168.10.200"}
        uplinks: JSON array of {"ports": "Ethernet3/3", "mode": "trunk", "allowed vlans": "all"}
        static_routes: JSON array of {"network": "0.0.0.0", "mask": "0.0.0.0", "next-hop": "10.0.0.1", "description": "Default"}
        acl_rules: JSON array of {"number": "100", "action": "permit", "protocol": "ip", "source": "192.168.10.0", "wildcard": "0.0.0.255", "dest": "any"}
        router_interface: Physical interface for router subinterfaces
        enable_rip: Whether to enable RIP routing
        rip_networks: JSON array of network strings like ["192.168.10.0", "192.168.20.0"]

    Returns the complete IOS configuration text.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> generate_device_config(hostname={hostname}, role={device_role})</span>\n")
    try:
        _vlans = json.loads(vlans) if isinstance(vlans, str) else vlans
        _routing = json.loads(routing_entries) if isinstance(routing_entries, str) else routing_entries
        _dhcp = json.loads(dhcp_pools) if isinstance(dhcp_pools, str) else dhcp_pools
        _uplinks = json.loads(uplinks) if isinstance(uplinks, str) else uplinks
        _static = json.loads(static_routes) if isinstance(static_routes, str) else static_routes
        _acl = json.loads(acl_rules) if isinstance(acl_rules, str) else acl_rules
        _rip_nets = json.loads(rip_networks) if isinstance(rip_networks, str) else rip_networks
    except json.JSONDecodeError as e:
        return f"JSON parse error: {e}"

    config_lines = []
    config_lines.append("enable")
    config_lines.append("configure terminal")

    # Identity block
    config_lines.append(f"hostname {hostname}")
    config_lines.append(f"enable secret {enable_password}")
    config_lines.append("no ip domain-lookup")
    config_lines.append("service password-encryption")
    config_lines.append("banner motd # Configured by ANCS Copilot #")

    # VLAN block (switches)
    if _vlans and device_role in ("access", "core"):
        for v in _vlans:
            config_lines.append(f"vlan {v['id']}")
            config_lines.append(f" name {v['name']}")
        # Port assignments
        for v in _vlans:
            ports = v.get("ports", "")
            if ports:
                config_lines.append(f"interface range {ports}")
                config_lines.append(f" switchport mode access")
                config_lines.append(f" switchport access vlan {v['id']}")
                config_lines.append(f" no shutdown")

    # Uplinks (trunk ports)
    for up in _uplinks:
        config_lines.append(f"interface {up['ports']}")
        config_lines.append(f" switchport mode trunk")
        allowed = up.get("allowed vlans", "all")
        if allowed and allowed != "all":
            config_lines.append(f" switchport trunk allowed vlan {allowed}")
        config_lines.append(f" no shutdown")

    # Routing (SVIs for core, subinterfaces for router)
    if device_role == "core":
        config_lines.append("ip routing")
        for r in _routing:
            config_lines.append(f"interface vlan {r['vlan']}")
            config_lines.append(f" ip address {r['ip']} {r['mask']}")
            config_lines.append(f" no shutdown")
    elif device_role == "router" and _routing:
        for r in _routing:
            sub = f"{router_interface}.{r['vlan']}"
            config_lines.append(f"interface {sub}")
            config_lines.append(f" encapsulation dot1Q {r['vlan']}")
            config_lines.append(f" ip address {r['ip']} {r['mask']}")
            config_lines.append(f" no shutdown")
        config_lines.append(f"interface {router_interface}")
        config_lines.append(f" no shutdown")

    # Static routes
    for sr in _static:
        desc = sr.get("description", "")
        cmd = f"ip route {sr['network']} {sr['mask']} {sr['next-hop']}"
        if desc:
            cmd += f" name {desc}"
        config_lines.append(cmd)

    # DHCP pools
    for pool in _dhcp:
        config_lines.append(f"ip dhcp pool {pool['pool']}")
        config_lines.append(f" network {pool['network']} {pool['mask']}")
        config_lines.append(f" default-router {pool['gateway']}")
        if pool.get("dns"):
            config_lines.append(f" dns-server {pool['dns']}")
        config_lines.append(f"ip dhcp excluded-address {pool['gateway']} {pool['gateway']}")

    # ACL rules
    for rule in _acl:
        config_lines.append(f"access-list {rule['number']} {rule['action']} {rule['protocol']} {rule['source']} {rule['wildcard']} {rule.get('dest', 'any')}")

    # RIP
    if enable_rip and _rip_nets:
        config_lines.append("router rip")
        config_lines.append(" version 2")
        config_lines.append(" no auto-summary")
        for net in _rip_nets:
            config_lines.append(f" network {net}")

    config_lines.append("end")
    config_lines.append("write memory")

    config_text = "\n".join(config_lines)
    ctx.log(f"<span style='color:#3fb950'><b>[Tool]</b> Config generated: {len(config_lines)} lines</span>\n")
    return config_text


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

        Sender.send_telnet(log_fn, host, port, username, password, enable_pw, config_text)
        return "Deployment successful.\n" + "\n".join(log_lines[-5:])
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

        Sender.send_ssh(log_fn, host, port, username, password, enable_pw, config_text)
        return "Deployment successful.\n" + "\n".join(log_lines[-5:])
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
            Sender.send_ssh(
                log_fn, info["host"], info["port"],
                info["username"], info["password"], info["enable_password"], config_text,
            )
        else:
            Sender.send_telnet(
                log_fn, info["host"], info["port"],
                info["username"], info["password"], info["enable_password"], config_text,
            )
        return "Deployment successful.\n" + "\n".join(log_lines[-8:])
    except Exception as e:
        return f"Deployment failed: {e}"


def run_cli_on_device(device_name: str, command: str) -> str:
    """Run one Cisco IOS show/exec command on a device by name (Telnet console). Uses pooled session if available."""
    ctx.log(f"\n<span style='color: #a371f7'><b>[Tool]</b> run_cli_on_device({device_name}): {command}</span>\n")
    if device_name in (ctx.sessions or {}) and ctx.sessions[device_name]:
        reader, writer = ctx.sessions[device_name]
        try:
            out = ctx.event_loop.run_until_complete(_async_exec_rw(reader, writer, command))
            ctx.log(f"<span style='color:#C9D1D9'>{out}</span>\n")
            return out.strip()
        except Exception as e:
            return f"Execution error: {e}"
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
    # Utilities
    calculate_subnet,
    get_ancs_help,
]

# Map function names for the agentic loop dispatcher
TOOL_MAP = {fn.__name__: fn for fn in ALL_TOOLS}


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """# IDENTITY
You are **ANCS Copilot**, a fully autonomous AI Network Engineer Agent embedded inside the **ANCS (Auto Network Configuration System)** desktop application. You are powered by Gemini and operate as an intelligent assistant that can explore, analyze, configure, deploy, and troubleshoot network devices.

# ABOUT ANCS
ANCS is a Python/PySide6 desktop app for managing Cisco network devices. Features:
- **Device Management**: Router, Switch, Core Switch (router acting as L3 switch)
- **Guided Setup Wizard**: Step-by-step config generator (Identity → VLANs → Routing → DHCP → ACLs)
- **GNS3 Integration**: Auto-import devices from GNS3 via REST API (default http://localhost:3080)
- **Config Deployment**: Send configs via Telnet or SSH with per-block delays
- **Subnet Calculator**, **SQLite Database**, **Bulk Deploy**, **Health Monitor**

# ENVIRONMENT
- Devices run inside **GNS3** (emulator), NOT physical hardware
- **Older Cisco IOS images** (c3725, c3640, c7200, vIOS) — classic CLI syntax
- **Telnet** is the primary connection method (GNS3 console ports, 5000+)
- `terminal length 0` is pre-configured on connected sessions

# YOUR TOOLS (ground truth)
You have access to these tool functions. **Prefer device_name-based tools** over pasting IP/port.

**GNS3 Lab Discovery:**
- `list_gns3_projects()` — list all GNS3 projects
- `list_gns3_nodes(project_id)` — optional; empty project_id uses the active ANCS GNS3 project when set
- `get_node_ports(project_id, node_id)` — get interfaces
- `get_topology_links(project_id)` — get cable connections

**Device Terminal:**
- `run_command_on_device(command)` — primary Copilot console (pooled session when available)
- `run_cli_on_device(device_name, command)` — run a command on any device by name (Telnet)

**Database:**
- `list_all_devices()` — all ANCS devices
- `get_device_credentials(device_name)` — saved login info
- `get_saved_config(device_name)` — last saved config
- `get_send_history(device_name)` — deployment log
- `query_logs(severity, limit)` — activity logs

**Config Generation:**
- `generate_device_config(hostname, device_role, ...)` — build IOS config from parameters
- `detect_topology()` — analyze device roles and topology pattern
- `suggest_configs()` — auto-generate config plans for all devices

**Deployment:**
- `deploy_to_device(device_name, config_text)` — **preferred**; uses saved credentials; config must be from ANCS or saved DB unless user enabled raw deploy in Copilot
- `deploy_config_telnet(...)` / `deploy_config_ssh(...)` — advanced: explicit host/port
- `verify_device(device_name, verify_commands)` — **preferred** verification by name
- `verify_deployment(host, port, ...)` — optional credentials for Telnet verify

**Utilities:**
- `calculate_subnet(ip, prefix)` — subnet calculations
- `get_ancs_help(topic)` — help on ANCS features and networking concepts

# GROUNDING (CRITICAL)
- **Facts** about devices/labs must come from **tool outputs** (GNS3 JSON, DB, or CLI `show` text). Do not invent interface names, IPs, or states.
- **Configuration that is applied to devices** must come from **`generate_device_config`**, **`get_saved_config`**, or user-approved raw deploy — never fabricate full configs from memory.
- When summarizing tool output, you may paraphrase; when stating status, tie it to what a tool returned.

# AUDIENCE (IMPORTANT)
**Primary users are beginners** — they may not know Cisco jargon, CLI commands, or what “console” vs “Telnet” means. Your job is to **reduce fear and confusion**, not to sound like a certification exam.

# RULES
1. **Read-first**: Always explore before modifying. Use GNS3 and DB tools to understand the state.
2. **Ask before deploying**: Never deploy a config without the user explicitly asking. Suggest configs, show them, wait for approval.
3. **Use tools**: Always use your tools to get real data. Never guess or hallucinate device states.
4. **Markdown output**: Use clear headings, **bold**, short lists. Avoid huge tables unless the user asked for detail.
5. **Plain language first**: Lead with a **simple verdict** (“Yes, your three routers/switches are powered on in the lab.”). Put names like `show ip interface brief` in **backticks** and add **one short plain-English gloss** when you mention them (e.g. “lists IP addresses on each interface”).
6. **Do not end with vague technical questions.** Avoid: “Would you like me to run X?” without saying what X does. Prefer: **either** run the safe check yourself when a live session exists and report results, **or** explain in one sentence what extra step would prove responsiveness and why it matters, then offer it only if needed.
7. **If you must ask something**: Ask **one** clear question, in everyday words, and say what happens next. Never imply the user should already know obscure command names.
8. **Chain tools intelligently**: If a task requires multiple steps, execute them in sequence.
9. **Explain actions for beginners**: Before calling tools, one short line (“I’m listing your lab devices from GNS3 so we see what’s on or off.”) — not jargon stacks.

# CONVERSATION STYLE
- **Answer-first**: Give the understandable summary before optional detail. PCs “stopped” in GNS3 usually means they’re turned off in the lab — say that plainly; don’t assume they know it’s normal for end hosts.
- **No “engineer voice”**: Friendly, patient, concise. You’re a tutor, not a grader.
- Examples of intent:
  - “Are my devices OK?” → Use tools, then say clearly which gear is running vs off, in normal words; only then mention diagnostics if a session is missing.
  - “Show me my GNS3 topology” → use GNS3 tools and describe links in plain language.
  - “What is a VLAN?” → use get_ancs_help or answer with a simple analogy first.

Do **not** open the chat by asking “what would you like to do?” unless the user’s message is empty. Respond directly to what they asked."""


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
                 host: str = "", port: int = 23,
                 user: str = "", pw: str = "", enable_pw: str = "",
                 device_name: str = "",
                 allow_raw_deploy: bool = False,
                 workspace_resolved: list | None = None,
                 gns3_project_id: str = ""):
        super().__init__()
        self.api_key = api_key
        self.gns3_url = gns3_url
        self.host = host
        self.port = port
        self.user = user
        self.pw = pw
        self.enable_pw = enable_pw
        self.device_name = device_name
        self.allow_raw_deploy = allow_raw_deploy
        self.workspace_resolved = workspace_resolved or []
        self.gns3_project_id = gns3_project_id
        self._loop = None
        self._chat = None
        self._client = None
        self._msg_queue = []
        self._running = True

        # Wire context
        ctx.gns3_url = gns3_url
        ctx.gns3_project_id = gns3_project_id or ""
        ctx.primary_device_name = device_name or ""
        ctx.allow_raw_deploy = allow_raw_deploy
        ctx.sessions = {}
        ctx.log_fn = lambda msg: self.terminal_log_signal.emit(msg)

    def queue_message(self, text: str):
        """Called from the GUI thread to queue a user message."""
        self._msg_queue.append(text)

    def stop(self):
        self._running = False

    async def _async_connect(self) -> bool:
        """Open telnet connection if host is provided."""
        if not self.host:
            self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] No device host specified — running without live terminal connection.</span>\n")
            return True  # Agent works without a device connection

        import telnetlib3
        self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] Opening Telnet session to {self.host}:{self.port}...</span>\n")
        try:
            ctx.telnet_reader, ctx.telnet_writer = await asyncio.wait_for(
                telnetlib3.open_connection(self.host, self.port), timeout=10
            )
        except Exception as e:
            self.terminal_log_signal.emit(f"<span style='color: #d73a49'>[Copilot] Telnet Connection Failed: {e}</span>\n")
            return True  # Still proceed without connection

        await asyncio.sleep(0.5)

        async def read_available(timeout_sec: float = 1.0) -> str:
            try:
                return await asyncio.wait_for(ctx.telnet_reader.read(4096), timeout=timeout_sec)
            except asyncio.TimeoutError:
                return ""

        initial = ""
        try:
            initial = await asyncio.wait_for(ctx.telnet_reader.read(4096), timeout=3.0)
        except asyncio.TimeoutError:
            pass

        def _copilot_wake_log(msg: str):
            self.terminal_log_signal.emit(f"<span style='color: #8b949e'>{msg}</span>\n")

        initial = await Sender._telnet_wake_gns3_console(
            ctx.telnet_writer, read_available, _copilot_wake_log, initial
        )

        initial_lower = initial.lower() if initial else ""
        if "username:" in initial_lower or "login:" in initial_lower:
            if self.user:
                ctx.telnet_writer.write(self.user + "\r\n")
                await asyncio.sleep(0.3)
                resp = ""
                try:
                    resp = await asyncio.wait_for(ctx.telnet_reader.read(4096), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                if "password:" in resp.lower() and self.pw:
                    ctx.telnet_writer.write(self.pw + "\r\n")
                    await asyncio.sleep(0.3)
        elif "password:" in initial_lower:
            if self.pw:
                ctx.telnet_writer.write(self.pw + "\r\n")
                await asyncio.sleep(0.3)

        if self.enable_pw:
            ctx.telnet_writer.write("enable\r\n")
            await asyncio.sleep(0.3)
            ctx.telnet_writer.write(self.enable_pw + "\r\n")
            await asyncio.sleep(0.3)

        ctx.telnet_writer.write("terminal length 0\r\n")
        await asyncio.sleep(0.2)
        try:
            await asyncio.wait_for(ctx.telnet_reader.read(65535), timeout=1.0)
        except asyncio.TimeoutError:
            pass

        self.terminal_log_signal.emit("<span style='color: #3fb950'>[Copilot] Telnet session established ✓</span>\n")
        if self.device_name and ctx.telnet_reader and ctx.telnet_writer:
            ctx.sessions[self.device_name] = (ctx.telnet_reader, ctx.telnet_writer)
        return True

    async def _establish_pool(self) -> None:
        """Open Telnet sessions for other workspace devices (parallel-friendly CLI)."""
        import telnetlib3

        for ep in self.workspace_resolved:
            name = ep.get("device_name") or ""
            if not name or name == self.device_name:
                continue
            if ep.get("protocol") == "ssh":
                continue
            host, port = ep.get("host"), ep.get("port")
            if not host:
                continue
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

            async def read_available(timeout_sec: float = 1.0) -> str:
                try:
                    return await asyncio.wait_for(reader.read(4096), timeout=timeout_sec)
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
            writer.write("terminal length 0\r\n")
            await asyncio.sleep(0.2)
            try:
                await asyncio.wait_for(reader.read(65535), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            ctx.sessions[name] = (reader, writer)
            self.terminal_log_signal.emit(
                f"<span style='color: #3fb950'>[Copilot] Pool ✓ {name}</span>\n"
            )

    def _process_response(self, response):
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
                t0 = time.monotonic()
                if fn_name in TOOL_MAP:
                    try:
                        result = TOOL_MAP[fn_name](**fn_args)
                    except Exception as e:
                        result = f"Tool error: {e}"
                else:
                    result = f"Unknown tool: {fn_name}"
                dt_ms = (time.monotonic() - t0) * 1000.0
                try:
                    ctx.log(
                        f"<span style='color:#8b949e'>[audit] {fn_name} {dt_ms:.0f}ms</span>\n"
                    )
                except Exception:
                    pass
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

    def run(self):
        try:
            # 1. Create event loop
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ctx.event_loop = self._loop

            # 2. Connect (optional) + pool other devices
            self._loop.run_until_complete(self._async_connect())
            self._loop.run_until_complete(self._establish_pool())

            # 3. Init Gemini
            self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Initializing Gemini...</span>\n")
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(api_version="v1alpha"),
            )

            models_to_try = ["gemini-3-flash-preview", "gemini-3-flash"]
            for model_name in models_to_try:
                try:
                    self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] Trying model: {model_name}...</span>\n")
                    self._chat = self._client.chats.create(
                        model=model_name,
                        config=types.GenerateContentConfig(
                            tools=ALL_TOOLS,
                            temperature=0.2,
                            system_instruction=SYSTEM_PROMPT,
                        )
                    )
                    self.terminal_log_signal.emit(f"<span style='color: #3fb950'>[Copilot] Model loaded: {model_name} ✓</span>\n")
                    break
                except Exception as e:
                    self.terminal_log_signal.emit(f"<span style='color: #d73a49'>[Copilot] {model_name} failed: {e}</span>\n")
                    self._chat = None

            if not self._chat:
                self.finished_signal.emit("Failed to initialize any Gemini model.", False)
                return

            # 4. Send greeting
            self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Agent ready — sending greeting...</span>\n")
            primary = self.device_name or "no primary device"
            greeting_response = self._chat.send_message(
                f"The user opened ANCS Copilot. Primary console focus: {primary}. "
                "Greet briefly in plain language; do not ask an open-ended 'what would you like to do?'. "
                "Offer one helpful example (e.g. list lab devices or check a show command) if appropriate."
            )
            greeting_text = self._process_response(greeting_response)
            self.chat_response_signal.emit(greeting_text)
            self.ready_signal.emit()

            # 5. Message loop — wait for user messages
            while self._running:
                if self._msg_queue:
                    user_msg = self._msg_queue.pop(0)
                    self.terminal_log_signal.emit(f"\n<span style='color: #58A6FF'><b>[User]</b> {user_msg}</span>\n")
                    try:
                        response = self._chat.send_message(user_msg)
                        reply = self._process_response(response)
                        self.chat_response_signal.emit(reply)
                    except Exception as e:
                        self.chat_response_signal.emit(f"**Error:** {e}")
                else:
                    time.sleep(0.1)  # Idle wait

        except Exception as e:
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
