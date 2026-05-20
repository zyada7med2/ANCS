"""
ANCS Copilot — Agentic AI with 22 tools (pull-based architecture).

This module defines all tool functions the AI agent can call,
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
    workspace_resolved: list | None = None  # live GNS3 connection info (host/port/creds)
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
    """Resolve host/port/credentials — always uses live GNS3 console port."""
    result = None

    # ── Check workspace_resolved first ────────────────────────────────
    if ctx.workspace_resolved:
        for ep in ctx.workspace_resolved:
            if (ep.get("device_name") or "").lower() == device_name.lower():
                result = {
                    "host": ep.get("host", ""),
                    "port": ep.get("port", 23),
                    "username": ep.get("user", ""),
                    "password": ep.get("password", ""),
                    "enable_password": ep.get("enable_password", ""),
                    "protocol": ep.get("protocol", "telnet"),
                }
                break

    # ── Fallback: SQLite database ─────────────────────────────────────
    if result is None:
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                _cur = conn.cursor()
                _cur.execute(
                    "SELECT d.ip, d.port, "
                    "c.host, c.port, c.username, c.password, c.enable_password, c.protocol "
                    "FROM devices d LEFT JOIN credentials c ON c.device_name = d.name "
                    "WHERE d.name=?",
                    (device_name,),
                )
                row = _cur.fetchone()
                _cur.close()
        except Exception:
            return None
        if not row:
            return None
        dip, dport, ch, cp, cu, cpw, ce, cprot = row
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
        result = {
            "host": host,
            "port": port_int,
            "username": user,
            "password": pw,
            "enable_password": enable,
            "protocol": protocol,
        }

    # ── Override port with live GNS3 console port ─────────────────────
    # GNS3 reassigns console ports on every project restart. The DB/credentials
    # value goes stale. Query the GNS3 API to get the actual live port.
    try:
        if ctx.gns3_project_id:
            gns3 = ctx.get_gns3_connector()
            nodes = gns3.get_nodes(ctx.gns3_project_id)
            for node in nodes:
                if (node.get("name") or "").lower() == device_name.lower():
                    live_port = node.get("console")
                    live_host = node.get("console_host", "")
                    if live_port and int(live_port) != result["port"]:
                        ctx.log(
                            f"<span style='color:#d29922'>[Copilot] Port override: "
                            f"{device_name} DB port {result['port']} → GNS3 live port {live_port}"
                            f"</span>\n"
                        )
                        result["port"] = int(live_port)
                    if live_host and live_host != "0.0.0.0":
                        result["host"] = live_host
                    break
    except Exception:
        pass  # GNS3 unavailable — use whatever we already resolved

    return result


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


def get_network_overview(project_id: str = "") -> str:
    """Get a combined overview of all devices and topology links in one call. Returns JSON with 'devices' and 'links'. Call this FIRST when asked about the network."""
    pid = (project_id or "").strip() or (ctx.gns3_project_id or "").strip()
    devices_json = list_all_devices()
    links_json = get_topology_links(pid) if pid else "[]"
    try:
        result = {
            "devices": json.loads(devices_json),
            "links": json.loads(links_json),
        }
    except json.JSONDecodeError:
        result = {"devices_raw": devices_json, "links_raw": links_json}
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_network_overview → combined view</span>\n")
    return json.dumps(result, indent=2)


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
    import re
    try:
        await asyncio.wait_for(reader.read(65535), timeout=0.1)
    except asyncio.TimeoutError:
        pass
        
    writer.write("\r\n")
    await asyncio.sleep(0.15)
    writer.write(command + "\r\n")
    await asyncio.sleep(1.2)
    buf = ""
    deadline = ctx.event_loop.time() + 6.0
    _confirm_sent = False
    while ctx.event_loop.time() < deadline:
        try:
            chunk = await asyncio.wait_for(reader.read(65535), timeout=0.5)
            if chunk:
                buf += chunk
                stripped = buf.rstrip()
                # Check for interactive confirmation prompts like [yes/no], [confirm], [y/n]
                if not _confirm_sent and re.search(
                    r'\[(yes|no|y/n|confirm)\]\s*:?\s*$', stripped, re.IGNORECASE
                ):
                    writer.write("yes\r\n")
                    _confirm_sent = True
                    await asyncio.sleep(1.0)
                    continue
                if stripped and stripped[-1] in (">", "#"):
                    break
        except asyncio.TimeoutError:
            break
    return buf


# ── 6-10: Database Tools ─────────────────────────────────────────────────────

def list_all_devices() -> str:
    """List devices in the current project, enriched with live GNS3 status and ports."""
    try:
        from network_manager.config import conn, db_lock
        with db_lock:
            _cur = conn.cursor()
            # Only select devices belonging to the current project or manually added ones (project_id is NULL/empty)
            if ctx.gns3_project_id:
                _cur.execute(
                    "SELECT name, type, ip, port, status, connection_type FROM devices "
                    "WHERE project_id=? ORDER BY name",
                    (ctx.gns3_project_id,)
                )
            else:
                _cur.execute("SELECT name, type, ip, port, status, connection_type FROM devices ORDER BY name")
            rows = _cur.fetchall()
            _cur.close()

        # Build base list from DB
        result = []
        for r in rows:
            result.append({
                "name": r[0], "type": r[1], "ip": r[2], "port": r[3],
                "status": r[4] or "unknown", "connection_type": r[5],
            })

        # Enrich with live GNS3 data if available
        gns3_nodes = {}
        try:
            if ctx.gns3_project_id:
                gns3 = ctx.get_gns3_connector()
                nodes = gns3.get_nodes(ctx.gns3_project_id)
                for node in nodes:
                    gns3_nodes[(node.get("name") or "").lower()] = node
        except Exception:
            pass

        seen_ports = {}
        for dev in result:
            name_lower = (dev["name"] or "").lower()
            if name_lower in gns3_nodes:
                node = gns3_nodes[name_lower]
                live_port = node.get("console")
                live_status = node.get("status", "unknown")
                if live_port:
                    dev["port"] = live_port
                dev["status"] = live_status  # "started", "stopped", etc.

            # Flag duplicate ports
            port_key = f"{dev.get('ip', '')}:{dev.get('port', '')}"
            if port_key in seen_ports and dev.get("port"):
                dev["warning"] = f"duplicate port — shared with {seen_ports[port_key]}"
            elif dev.get("port"):
                seen_ports[port_key] = dev["name"]

        # Filter out stopped/ghost devices — they pollute the agent's context
        # and their "duplicate port" warnings hijack attention
        active_devices = [d for d in result if d.get("status") in ("started", "unknown", None)]
        stopped_devices = [d for d in result if d.get("status") not in ("started", "unknown", None)]

        # Also remove warning fields from active devices if the conflicting device is stopped
        stopped_names = {d["name"].lower() for d in stopped_devices}
        for dev in active_devices:
            if "warning" in dev:
                # Check if the "shared with" device is stopped — if so, no real conflict
                warning_text = dev["warning"].lower()
                for sn in stopped_names:
                    if sn in warning_text:
                        del dev["warning"]
                        break

        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> list_all_devices → {len(active_devices)} active devices"
                f"{f' ({len(stopped_devices)} stopped/hidden)' if stopped_devices else ''}"
                f" (filtered to current project)</span>\n")
        return json.dumps(active_devices, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_device_credentials(device_name: str) -> str:
    """Get connection info (host, port, username, protocol) for a specific device. Uses live GNS3 port when available."""
    info = _resolve_device_connection(device_name)
    if not info:
        return f"No connection info for '{device_name}'"
    # Redact passwords for display safety — the deploy tools use _resolve_device_connection directly
    result = {
        "host": info["host"],
        "port": info["port"],
        "username": info["username"],
        "password": "***" if info["password"] else "",
        "enable_password": "***" if info["enable_password"] else "",
        "protocol": info["protocol"],
    }
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_device_credentials({device_name})</span>\n")
    return json.dumps(result, indent=2)


def get_saved_config(device_name: str) -> str:
    """Get the last saved configuration for a device from the ANCS database."""
    try:
        from network_manager.config import conn, db_lock
        with db_lock:
            _cur = conn.cursor()
            _cur.execute("""
                SELECT c.config_name, c.content, c.created_at
                FROM configs c JOIN devices d ON c.device_id = d.id
                WHERE d.name=? ORDER BY c.created_at DESC LIMIT 1
            """, (device_name,))
            row = _cur.fetchone()
            _cur.close()
        if not row:
            return f"No saved config for '{device_name}'"
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_saved_config({device_name})</span>\n")
        return json.dumps({"config_name": row[0], "content": row[1], "created_at": row[2]}, indent=2)
    except Exception as e:
        return f"Error: {e}"


def get_send_history(device_name: str) -> str:
    """Get the deployment/send history log for a device. Returns recent log entries."""
    try:
        from network_manager.config import conn, db_lock
        with db_lock:
            _cur = conn.cursor()
            _cur.execute("""
                SELECT action, details, config_snapshot, timestamp
                FROM logs
                WHERE device_name=? ORDER BY timestamp DESC LIMIT 10
            """, (device_name,))
            rows = _cur.fetchall()
            _cur.close()
        result = [{"action": r[0], "details": r[1], "config_snapshot": (r[2] or "")[:200], "timestamp": r[3]} for r in rows]
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_send_history({device_name}) → {len(result)} entries</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


def query_logs(severity: str = "all", limit: int = 20) -> str:
    """Query the ANCS activity logs. Severity can be 'info', 'warning', 'error', or 'all'. Returns recent log entries."""
    try:
        from network_manager.config import conn, db_lock
        with db_lock:
            _cur = conn.cursor()
            if severity == "all":
                _cur.execute("SELECT action, details, severity, created_at FROM logs ORDER BY created_at DESC LIMIT ?", (limit,))
            else:
                _cur.execute("SELECT action, details, severity, created_at FROM logs WHERE severity=? ORDER BY created_at DESC LIMIT ?", (severity, limit))
            rows = _cur.fetchall()
            _cur.close()
        result = [{"action": r[0], "details": r[1], "severity": r[2], "timestamp": r[3]} for r in rows]
        ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> query_logs(severity={severity}) → {len(result)} entries</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


# ── 11-13: Config Generation ─────────────────────────────────────────────────

def _parse_json_raw(val):
    """Core JSON/Python-literal parser — shared by _parse_json_arg and _parse_json_string_list.

    Returns the parsed Python list (items can be any type).
    """
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    if val is None or val == "":
        return []
    import re as _re
    s = val.strip()
    s = _re.sub(r'^```(?:json|python)?\s*\n', '', s)
    s = _re.sub(r'\n```\s*$', '', s)
    s = s.strip()
    if not s or s in ("[]", "null", "None"):
        return []
    import json as _json, ast as _ast
    parsed = None
    try:
        parsed = _json.loads(s)
    except Exception:
        pass
    if parsed is None:
        try:
            parsed = _ast.literal_eval(s)
        except Exception:
            raise ValueError(f"Could not parse as JSON or Python literal: {s[:120]}")
    return parsed if isinstance(parsed, list) else [parsed]


def _parse_json_string_list(val, arg_name: str = "commands") -> list:
    """Parse a JSON array of strings (used by verify_device / verify_deployment).

    Unlike _parse_json_arg, this does NOT require items to be dicts —
    it accepts plain strings like ["show ip interface brief"].
    """
    result = _parse_json_raw(val)
    # Coerce items to strings
    return [str(item) for item in result]


def _parse_json_arg(val: str, arg_name: str = "argument") -> list:
    """Robustly parse JSON/Python lists from LLM outputs.

    Handles markdown code fences, single-quoted Python literals, and
    already-parsed list/dict values passed directly by the model.

    Also validates that every item in the resulting list is a dict —
    the ConfigEngine render methods always call .get() on list items,
    so a bare string or int inside the list causes
    ``'str' object has no attribute 'get'``.
    """
    result = _parse_json_raw(val)
    if not result:
        return []

    # ── Validate items are dicts ──────────────────────────────────────────
    bad = [i for i, item in enumerate(result) if not isinstance(item, dict)]
    if bad:
        samples = [repr(result[i])[:80] for i in bad[:3]]
        raise ValueError(
            f"Bad {arg_name}: every item must be a dict (object), but item(s) at "
            f"index {bad[:3]} are not. Got: {', '.join(samples)}. "
            f"Example of correct format for {arg_name}: "
            + {
                "vlans": '[{{"id": "10", "name": "Staff", "ports": "Ethernet0/0"}}]',
                "routing_entries": '[{{"vlan": "10", "ip": "192.168.10.1", "mask": "255.255.255.0"}}]',
                "dhcp_pools": '[{{"pool": "Staff", "network": "192.168.10.0", "mask": "255.255.255.0", "gateway": "192.168.10.1"}}]',
                "uplinks": '[{{"ports": "Ethernet3/3", "mode": "trunk", "allowed vlans": "all"}}]',
                "static_routes": '[{{"network": "0.0.0.0", "mask": "0.0.0.0", "next-hop": "10.0.0.1"}}]',
                "transit_links": '[{{"local_interface": "FastEthernet0/1", "ip": "10.0.0.1", "mask": "255.255.255.252", "protocol": "ospf"}}]',
                "acl_rules": '[{{"acl #": "101", "action": "deny", "source": "192.168.10.0", "wildcard": "0.0.0.255"}}]',
            }.get(arg_name, '[{"key": "value"}]')
        )

    return result


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
    routing_protocol: str = "none",
    wan_interface: str = "",
    wan_ip: str = "",
    wan_mask: str = "255.255.255.252",
    transit_links: str = "[]",
    stp_root: str = "",
) -> str:
    """Generate a full Cisco IOS configuration using the ANCS ConfigEngine (same engine as Guided Setup).

    This produces block-formatted IOS config identical to the Guided Setup wizard, including
    trunk encapsulation, portfast, speed/duplex, VLAN database syntax for core switches,
    uplink port exclusion from access VLAN assignments, and proper DHCP excluded ranges.

    ROUTING PROTOCOL GUIDANCE (analyze the topology before choosing):
    - device_role='core'    → ALWAYS routing_protocol='none'. Core switches route between VLANs
                              via SVIs locally — they never need a dynamic routing protocol.
                              Use static_routes to point to the upstream router for external traffic.
    - device_role='access'  → ALWAYS routing_protocol='none'. Pure Layer 2, no routing.
    - device_role='router'  → Choose based on the network:
        • 'rip'   — Small/simple labs (≤5 routers, ≤15 hops). Easiest to set up.
        • 'ospf'  — Medium-to-large networks, multi-vendor, or when you need fast convergence.
        • 'eigrp' — All-Cisco environments where fast convergence matters.
        • 'none'  — Single-router topologies or static-only designs.
      Analyze the topology first: count the routers, check if it's all-Cisco, and pick accordingly.
      ALL routers in the same network MUST use the SAME protocol unless redistribution is configured.

    Args:
        hostname: Device hostname
        device_role: 'router', 'core', or 'access'
        vlans: Array of {"id": "10", "name": "Staff", "ports": "Ethernet0/0,Ethernet0/1"}
        routing_entries: Array of {"vlan": "10", "name": "Staff", "ip": "192.168.10.1", "mask": "255.255.255.0"}
        dhcp_pools: Array of {"pool": "Staff", "network": "192.168.10.0", "mask": "255.255.255.0", "gateway": "192.168.10.1", "dns": "8.8.8.8", "start": "192.168.10.50", "end": "192.168.10.200"}
        uplinks: Array of {"ports": "Ethernet3/3", "mode": "trunk", "allowed vlans": "all"}
        static_routes: Array of {"network": "0.0.0.0", "mask": "0.0.0.0", "next-hop": "10.0.0.1", "description": "Default"}
        acl_rules: Array of {"acl #": "101", "action": "deny", "source": "192.168.10.0", "wildcard": "0.0.0.255", "destination": "192.168.30.0", "destination_wildcard": "0.0.0.255", "remark": "Block Guest from Servers"}
        router_interface: Physical interface for router subinterfaces (e.g. FastEthernet0/0)
        routing_protocol: 'ospf', 'eigrp', 'rip', or 'none' (default). ALWAYS specify this explicitly.
        wan_interface: WAN-facing interface (e.g. FastEthernet0/1)
        wan_ip: WAN IP address or 'dhcp'
        wan_mask: WAN subnet mask
        transit_links: Array of {"local_interface": "FastEthernet0/1", "ip": "10.0.0.1", "mask": "255.255.255.252", "protocol": "ospf"}
        stp_root: 'primary' or 'secondary' (core switches only)

    Returns the complete block-formatted IOS configuration text.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> generate_device_config(hostname={hostname}, role={device_role})</span>\n")
    try:
        _vlans   = _parse_json_arg(vlans,           "vlans")
        _routing = _parse_json_arg(routing_entries,  "routing_entries")
        _dhcp    = _parse_json_arg(dhcp_pools,       "dhcp_pools")
        _uplinks = _parse_json_arg(uplinks,          "uplinks")
        _static  = _parse_json_arg(static_routes,    "static_routes")
        _acl     = _parse_json_arg(acl_rules,        "acl_rules")
        _transit = _parse_json_arg(transit_links,    "transit_links")
    except ValueError as e:
        return f"Parse error: {e}"

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
            stp_root=stp_root,
        )

        config_text = engine.build_full_config()
        blocks = engine.render_all_blocks()

        # Add marker so deploy_to_device accepts generated configs
        config_text = f"! Configured by ANCS Copilot\n\n{config_text}"

        # ── Persist config to DB so snapshot shows has_config=true ─────
        _config_saved = False
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                _cur = conn.cursor()
                _cur.execute("SELECT id FROM devices WHERE name=?", (hostname,))
                dev_row = _cur.fetchone()
                if dev_row:
                    _cur.execute(
                        "INSERT INTO configs (device_id, config_name, content, created_at) "
                        "VALUES (?, ?, ?, datetime('now'))",
                        (dev_row[0], f"copilot_{hostname}", config_text),
                    )
                    conn.commit()
                    _config_saved = True
                _cur.close()
        except Exception as save_err:
            ctx.log(f"<span style='color:#d29922'>[Copilot] Warning: could not save config to DB: {save_err}</span>\n")

        # ── Return summary instead of full config (saves tokens) ──────
        block_summaries = []
        for bname, btext in blocks.items():
            label = bname.replace("guided_", "").replace("_", " ").title()
            line_count = len(btext.strip().splitlines())
            block_summaries.append(f"{label} ({line_count} lines)")

        import hashlib
        config_hash = hashlib.md5(config_text.encode()).hexdigest()[:12]

        summary = json.dumps({
            "status": "success",
            "hostname": hostname,
            "device_role": device_role,
            "blocks": block_summaries,
            "total_lines": len(config_text.splitlines()),
            "config_saved_to_db": _config_saved,
            "config_hash": config_hash,
            "note": "Full config saved to DB. Use get_saved_config() to retrieve. "
                    "Use deploy_to_device() or generate_and_deploy_device_config() to deploy.",
        }, indent=2)

        ctx.log(f"<span style='color:#3fb950'><b>[Tool]</b> Config generated via ConfigEngine: {len(blocks)} blocks, {len(config_text.splitlines())} lines (saved={_config_saved})</span>\n")
        return summary
    except Exception as e:
        return f"ConfigEngine error: {e}"


def generate_and_deploy_device_config(
    hostname: str,
    device_role: str,
    vlans: str = "[]",
    routing_entries: str = "[]",
    dhcp_pools: str = "[]",
    uplinks: str = "[]",
    static_routes: str = "[]",
    acl_rules: str = "[]",
    router_interface: str = "",
    routing_protocol: str = "none",
    wan_interface: str = "",
    wan_ip: str = "",
    wan_mask: str = "255.255.255.252",
    transit_links: str = "[]",
    stp_root: str = "",
) -> str:
    """Generate AND immediately deploy a Cisco IOS config in one atomic step. PREFERRED method.

    Same parameters as generate_device_config — see that tool for full parameter docs.
    Generates config via ConfigEngine, saves to DB, then deploys to the device atomically.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> generate_and_deploy_device_config(hostname={hostname})</span>\n")
    
    # 1. Generate the config
    config_result = generate_device_config(
        hostname=hostname, device_role=device_role, vlans=vlans, 
        routing_entries=routing_entries, dhcp_pools=dhcp_pools, uplinks=uplinks, 
        static_routes=static_routes, acl_rules=acl_rules, 
        router_interface=router_interface, routing_protocol=routing_protocol, 
        wan_interface=wan_interface, wan_ip=wan_ip, wan_mask=wan_mask, 
        transit_links=transit_links
    )
    
    if "ConfigEngine error" in config_result or "Parse error" in config_result:
        return f"Failed to generate config: {config_result}"

    # generate_device_config now returns a JSON summary; retrieve full config from DB
    try:
        gen_info = json.loads(config_result)
        if gen_info.get("status") != "success":
            return f"Failed to generate config: {config_result}"
    except (json.JSONDecodeError, TypeError):
        return f"Failed to generate config: {config_result}"

    # 2. Retrieve the full config from DB (just saved by generate_device_config)
    saved_raw = get_saved_config(hostname)
    try:
        saved_data = json.loads(saved_raw)
        config_text = saved_data.get("content", "")
    except (json.JSONDecodeError, TypeError):
        return f"Config generated but could not retrieve from DB for deployment: {saved_raw}"

    if not config_text.strip():
        return "Config generated but saved content is empty — cannot deploy."
        
    # 3. Deploy it immediately
    ctx.log(f"<span style='color:#8b949e'>[Copilot] Auto-deploying generated config to {hostname}...</span>\n")
    deploy_result = deploy_to_device(device_name=hostname, config_text=config_text)
    
    return f"GENERATION: {config_result}\n\nDEPLOYMENT RESULTS:\n{deploy_result}"


def audit_network() -> str:
    """Scan ALL device configurations in the project snapshot for security issues, inconsistencies, and best-practice violations.

    Checks for: missing enable secret, no hostname set, mismatched routing protocols,
    trunks without encapsulation, missing portfast, no default route, open VTY lines, etc.

    Returns a structured JSON report of findings.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> audit_network()</span>\n")
    try:
        from network_manager.config import conn, db_lock

        # Fetch devices in the current project (or unassigned), along with their latest deployed config from logs
        with db_lock:
            _cur = conn.cursor()
            query = """
                SELECT d.name, d.type, l.config_snapshot 
                FROM devices d 
                LEFT JOIN logs l ON l.device_name = d.name 
                  AND l.id = (SELECT MAX(l2.id) FROM logs l2 WHERE l2.device_name = d.name AND l2.config_snapshot IS NOT NULL AND l2.config_snapshot != '') 
            """
            if ctx.gns3_project_id:
                query += "WHERE d.project_id=? ORDER BY d.name"
                _cur.execute(query, (ctx.gns3_project_id,))
            else:
                query += "ORDER BY d.name"
                _cur.execute(query)
            devices_with_configs = _cur.fetchall()
            _cur.close()

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
    """Analyze the current ANCS device list and detect the network topology pattern (router-core-access, core-access, router-only, etc.). Only includes devices in the active GNS3 project."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> detect_topology()</span>\n")
    try:
        from network_manager.config import conn, db_lock
        with db_lock:
            _cur = conn.cursor()
            if ctx.gns3_project_id:
                _cur.execute(
                    "SELECT name, type FROM devices "
                    "WHERE project_id=? ORDER BY name",
                    (ctx.gns3_project_id,)
                )
            else:
                _cur.execute("SELECT name, type FROM devices ORDER BY name")
            rows = _cur.fetchall()
            _cur.close()
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

def _evict_pool_by_host_port(host: str, port: int):
    """Close any pooled session whose resolved host:port matches the target."""
    if not ctx.sessions:
        return
    to_evict = []
    for dname in list(ctx.sessions.keys()):
        info = _resolve_device_connection(dname)
        if info and info["host"] == host and info["port"] == port:
            to_evict.append(dname)
    for dname in to_evict:
        try:
            _r, _w = ctx.sessions[dname]
            w_obj = _w._w if hasattr(_w, "_w") else _w
            sock = w_obj.get_extra_info('socket')
            if sock:
                sock.close()
        except Exception:
            pass
        del ctx.sessions[dname]
        ctx.log(f"<span style='color:#8b949e'>[Copilot] Released pool session for {dname} (deploy needs exclusive console access)</span>\n")


def deploy_config_telnet(host: str, port: int, username: str, password: str, enable_pw: str, config_text: str) -> str:
    """Deploy a configuration to a network device via Telnet. Returns the send log."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> deploy_config_telnet({host}:{port})</span>\n")
    _evict_pool_by_host_port(host, port)
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
    _evict_pool_by_host_port(host, port)
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

    # ── Hostname mismatch guardrail ───────────────────────────────────
    # Prevent dumb models from sending R1's config to SW1, etc.
    import re as _re
    _hostname_match = _re.search(r"(?m)^\s*hostname\s+(\S+)", config_text)
    if _hostname_match:
        _cfg_hostname = _hostname_match.group(1).strip()
        if _cfg_hostname.lower() != device_name.lower():
            return (
                f"DEPLOY BLOCKED — hostname mismatch! The config contains 'hostname {_cfg_hostname}' "
                f"but you are trying to deploy to device '{device_name}'. "
                f"You must deploy this config to '{_cfg_hostname}', not '{device_name}'. "
                f"Call deploy_to_device(device_name='{_cfg_hostname}', config_text=...) instead."
            )
    info = _resolve_device_connection(device_name)
    if not info:
        return f"Error: no host/credentials for '{device_name}'."

    # ── Close pooled session before deploy ─────────────────────────────
    # GNS3 console ports are single-client: the pool's open Telnet
    # connection would block the Sender's fresh connection from working.
    _evicted = False
    if ctx.sessions and device_name in ctx.sessions:
        try:
            _r, _w = ctx.sessions[device_name]
            w_obj = _w._w if hasattr(_w, "_w") else _w
            sock = w_obj.get_extra_info('socket')
            if sock:
                sock.close()
        except Exception:
            pass
        del ctx.sessions[device_name]
        _evicted = True
        ctx.log(f"<span style='color:#8b949e'>[Copilot] Temporarily released pool session for {device_name} (deploy needs exclusive console access)</span>\n")

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
                stripped = out.strip()
                # CLI error detection — flag common IOS errors
                for err_pattern in ['% Invalid input', '% Incomplete command', '% Ambiguous command', '% Unknown command']:
                    if err_pattern in stripped:
                        ctx.log(f"<span style='color:#d73a49'><b>⚠️ CLI ERROR:</b> {err_pattern} detected in output</span>\n")
                        return f"⚠️ CLI ERROR: {err_pattern}\n\n{stripped}"
                return stripped
            except Exception as e:
                ctx.log(f"<span style='color:#d29922'>[Copilot] Pooled session for {device_name} failed: {e} — falling back to fresh connection</span>\n")
        else:
            ctx.log(f"<span style='color:#d29922'>[Copilot] Pooled session for {device_name} is dead — evicting and using fresh connection</span>\n")
        # Evict dead session
        try:
            w_obj = writer._w if hasattr(writer, "_w") else writer
            sock = w_obj.get_extra_info('socket')
            if sock:
                sock.close()
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
    result = (out.get(command.strip()) or next(iter(out.values()), "")).strip()
    # CLI error detection — flag common IOS errors (fresh connection path)
    for err_pattern in ['% Invalid input', '% Incomplete command', '% Ambiguous command', '% Unknown command']:
        if err_pattern in result:
            ctx.log(f"<span style='color:#d73a49'><b>⚠️ CLI ERROR:</b> {err_pattern} detected in output</span>\n")
            return f"⚠️ CLI ERROR: {err_pattern}\n\n{result}"
    return result


def verify_device(device_name: str, verify_commands: str = '["show ip interface brief"]') -> str:
    """Run verification show commands on a device by name (uses Telnet + saved credentials). verify_commands is a JSON array of strings."""
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> verify_device({device_name})</span>\n")
    try:
        cmds = _parse_json_string_list(verify_commands, "verify_commands")
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
        cmds = _parse_json_string_list(verify_commands, "verify_commands")

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


def get_agent_guidelines(topic: str) -> str:
    """Get ANCS help or network engineering guidelines. Call this when you need design principles, routing protocol guidance, IOS syntax reference, or deployment rules.

    Args:
        topic: One of 'network_design', 'ip_addressing', 'routing_protocol', 'ios_reference', 'deployment_order', 'dhcp_placement', 'trunk_design', 'hsrp', 'stp', 'error_recovery', 'vlan', 'acl', 'subnet', 'gateway', 'svi', 'guided_setup', 'gns3', 'deploy', 'overview'
    """
    help_db = {
        # ── Original ANCS help topics ──
        "overview": "ANCS (Auto Network Configuration System) is a desktop app for managing Cisco network device configurations. Features: Device Management (Router/Switch/CoreSwitch), Guided Setup Wizard, GNS3 Integration, Config Deployment (Telnet/SSH), Subnet Calculator, SQLite Database.",
        "vlan": "A VLAN (Virtual LAN) is a logical network segment. Devices in one VLAN cannot communicate with another without routing. Common setup: VLAN 10 for Management, VLAN 20 for Users, VLAN 30 for Servers.",
        "trunk": "A trunk port carries traffic for multiple VLANs using 802.1Q tags. Used between switches or between a switch and router (router-on-a-stick). Configure with: switchport mode trunk.",
        "acl": "Access Control Lists filter traffic. Standard ACLs (1-99) match source IP. Extended ACLs (100-199) match source, dest, protocol. Apply to interfaces with: ip access-group.",
        "subnet": "Subnetting divides networks. /24 = 256 addresses (254 hosts), /25 = 128 (126 hosts), /26 = 64 (62 hosts). Use the calculate_subnet tool for exact calculations.",
        "gateway": "The default gateway is the router IP that devices use to reach other networks. Usually the first usable IP in the subnet (e.g., 192.168.10.1).",
        "svi": "Switch Virtual Interface — an IP assigned to a VLAN on a Layer 3 switch. Acts as the default gateway for that VLAN. Configure with: interface vlan X, ip address.",
        "guided_setup": "The Guided Setup Wizard walks through device configuration step by step: Identity -> VLANs -> Uplinks -> Routing -> WAN -> Static Routes -> DHCP -> ACLs -> Review. Use generate_device_config tool to generate configs programmatically.",
        "gns3": "GNS3 is a network emulator. ANCS connects to GNS3's REST API (default http://localhost:3080) to import projects, nodes, ports, and links. Devices run classic IOS images (c3725, c7200).",
        "deploy": "ANCS deploys configs via Telnet (port 23) or SSH (port 22). Configs are split into blocks with delays between each. Use deploy_to_device(device_name, config_text) for deployment.",
        # ── Network design principles (moved from system prompt) ──
        "network_design": (
            "## Network Design Principles\n"
            "1. **IP Addressing**: Each device on a VLAN gets a unique host address. The gateway IP (.1) belongs to whichever device routes for that VLAN (router subinterface or core switch SVI). Other L3 devices use .2, .3, etc.\n"
            "2. **DHCP Placement**: DHCP pools go ONLY on the device that is the default gateway for that VLAN. Router does router-on-a-stick -> DHCP on router. Core switch routes via SVIs -> DHCP on core switch. Access switches NEVER run DHCP.\n"
            "3. **Trunk Design**: Both ends must be trunk with same encapsulation (dot1q). Allowed VLANs should list only VLANs in use. Uplink ports must NOT also be access ports.\n"
            "4. **Cross-Device Consistency**: When adding a VLAN, update ALL devices: add VLAN definition on every switch, add to trunk allowed lists, create SVI/subinterface on gateway device, add DHCP pool.\n"
            "5. **Inbound Static Routes (CRITICAL)**: Core switches use static default route to WAN router. But the WAN router MUST have static routes pointing internal VLAN subnets back to the core switch's transit IP. Without this, return traffic fails."
        ),
        "ip_addressing": (
            "## IP Addressing Rules\n"
            "- Each device on a VLAN gets a unique host address. Never assign the same IP to two devices.\n"
            "- The gateway IP (typically .1) belongs to whichever device does routing for that VLAN.\n"
            "- If a router does router-on-a-stick -> router's subinterface gets .1\n"
            "- If a core switch routes via SVIs -> core switch's SVI gets .1\n"
            "- Other L3 devices on the same VLAN use .2, .3, etc.\n"
            "- Plan subnets before configuring: e.g. VLAN 10 = 192.168.10.0/24, VLAN 20 = 192.168.20.0/24."
        ),
        "hsrp": (
            "## Gateway Redundancy (HSRP)\n"
            "- If you have dual core switches (e.g., ESW1 and ESW2) as gateways for the same VLANs, you MUST configure HSRP.\n"
            "- Assign unique physical IPs (.2 to ESW1, .3 to ESW2) and a shared virtual IP (.1) using hsrp_virtual_ip in routing_entries.\n"
            "- Do NOT just assign .1 to ESW1 and .2 to ESW2 without HSRP — single point of failure."
        ),
        "stp": (
            "## Spanning Tree Protocol (STP)\n"
            "- STP prevents loops in switched networks. Elects a root bridge and blocks redundant paths.\n"
            "- If you have dual core switches, you MUST define STP root bridges.\n"
            "- Pass stp_root='primary' to the primary core switch, stp_root='secondary' to the secondary.\n"
            "- Use 'show spanning-tree' to check status."
        ),
        "dhcp_placement": (
            "## DHCP Placement Rules\n"
            "- DHCP pools go on the device that is the default gateway for that VLAN — and ONLY on that device.\n"
            "- Router does router-on-a-stick -> DHCP on that router.\n"
            "- Core switch does inter-VLAN routing via SVIs -> DHCP on the core switch.\n"
            "- Access switches NEVER run DHCP.\n"
            "- If multiple routers exist, only ONE should serve DHCP per subnet to avoid IP conflicts."
        ),
        "trunk_design": (
            "## Trunk Design Rules\n"
            "- Both ends of a trunk must be configured as trunk with the same encapsulation (dot1q).\n"
            "- Trunk allowed VLANs should list only the VLANs actually in use — avoid 'all' when possible.\n"
            "- Uplink ports must NOT also be assigned as access ports to a VLAN."
        ),
        "deployment_order": (
            "## Deployment Order (always follow this)\n"
            "0. **Pre-flight check**: Call validate_configs() to catch IP conflicts, routing mismatches, missing VLANs. Fix issues FIRST.\n"
            "1. **Core switches first** — VLANs, trunks, SVIs, static routes\n"
            "2. **Routers next** — subinterfaces, routing protocol, DHCP, WAN\n"
            "3. **Access switches last** — VLANs, trunks, access ports\n"
            "This ensures trunk/routing infrastructure is ready before endpoints are assigned.\n"
            "For multi-device deploys, prefer bulk_deploy() — it handles ordering automatically."
        ),
        "error_recovery": (
            "## Error Recovery & Fallback Protocol\n"
            "- If a deploy fails on one device, log the error and continue with remaining devices. Report all failures at the end.\n"
            "- Never silently swallow errors.\n"
            "- If generate_device_config is broken, you ARE allowed to use deploy_config_telnet as a backup.\n"
            "- DO NOT PANIC: If you fall back to manual CLI, you MUST still follow all architectural rules and call get_topology_links first."
        ),
        "routing_protocol": (
            "## Routing Protocol Decision Guide\n\n"
            "### Switches — NEVER get a routing protocol\n"
            "- Core (L3 switch): routing_protocol='none', ALWAYS. SVIs route between VLANs locally. Give it a static default route to the upstream router.\n"
            "- Access switch: routing_protocol='none', ALWAYS. Pure Layer 2.\n\n"
            "### Routers — analyze the topology, then choose\n"
            "- How many routers? 1-5 in a simple lab -> 'rip' is fine. 6+ or complex -> 'ospf' or 'eigrp'.\n"
            "- Vendor mix? All Cisco -> 'eigrp' (fast convergence). Mixed vendors -> 'ospf'.\n"
            "- Single router with no peers? -> 'none' (static routes only).\n"
            "- ALL routers in the same domain MUST run the SAME protocol.\n\n"
            "### Quick Flowchart\n"
            "1. Is it a switch? -> 'none'. Done.\n"
            "2. Only router? -> 'none' + static routes.\n"
            "3. Count routers: <=5 simple? -> 'rip'. Larger? -> 'ospf' or 'eigrp'.\n"
            "4. All Cisco? -> prefer 'eigrp'. Mixed? -> 'ospf'.\n"
            "5. Apply the SAME choice to ALL routers."
        ),
        "ios_reference": (
            "## Cisco IOS Quick Reference\n"
            "**Show commands** (read-only, safe): show running-config, show ip interface brief, show ip route, show vlan brief (or show vlan-switch on core), show interfaces trunk, show spanning-tree, show ip ospf neighbor, show ip eigrp neighbors, show cdp neighbors, show ip dhcp binding, show ip dhcp pool, show access-lists, ping X.X.X.X\n"
            "**Config mode**: configure terminal -> hostname X -> interface X -> ip address X M -> no shutdown -> end\n"
            "**VLAN database** (older IOS): vlan database -> vlan 10 name Staff -> exit\n"
            "**Trunk**: interface X -> switchport trunk encapsulation dot1q -> switchport mode trunk"
        ),
    }
    result = help_db.get(topic.lower(), f"Unknown topic: '{topic}'. Available topics: {', '.join(help_db.keys())}")
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> get_agent_guidelines({topic})</span>\n")
    return result

# ── 19-20: Validation & Bulk Deploy ──────────────────────────────────────────

def validate_configs(device_names: str = "all") -> str:
    """Dry-run validation: cross-check generated configs across devices for IP conflicts,
    VLAN consistency, trunk mismatches, and routing protocol consistency BEFORE deploying.

    Call this BEFORE deploying to catch issues early. Pass a JSON array of device names,
    or "all" to validate every device that has a saved config.

    Returns a JSON report with pass/fail per check and specific issues found.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> validate_configs({device_names})</span>\n")
    try:
        from network_manager.config import conn, db_lock

        # Determine which devices to validate
        if device_names == "all":
            with db_lock:
                _cur = conn.cursor()
                if ctx.gns3_project_id:
                    _cur.execute(
                        "SELECT d.name, d.type FROM devices d "
                        "WHERE d.project_id=? ORDER BY d.name",
                        (ctx.gns3_project_id,)
                    )
                else:
                    _cur.execute("SELECT name, type FROM devices ORDER BY name")
                device_list = _cur.fetchall()
                _cur.close()
        else:
            names = _parse_json_string_list(device_names, "device_names")
            with db_lock:
                _cur = conn.cursor()
                device_list = []
                for n in names:
                    _cur.execute("SELECT name, type FROM devices WHERE name=?", (n,))
                    row = _cur.fetchone()
                    if row:
                        device_list.append(row)
                _cur.close()

        if not device_list:
            return json.dumps({"status": "error", "message": "No devices found to validate."})

        # Collect configs
        configs = {}
        for name, dtype in device_list:
            with db_lock:
                _cur = conn.cursor()
                _cur.execute("""
                    SELECT c.content FROM configs c JOIN devices d ON c.device_id = d.id
                    WHERE d.name=? ORDER BY c.created_at DESC LIMIT 1
                """, (name,))
                row = _cur.fetchone()
                _cur.close()
            if row and row[0]:
                configs[name] = {"type": dtype, "config": row[0]}

        if not configs:
            return json.dumps({"status": "warning", "message": "No saved configs found. Generate configs first."})

        findings = []
        ip_map = {}  # ip -> device_name
        vlan_map = {}  # device -> set of vlan ids
        protocols = {}  # device -> protocol
        trunk_devices = {}  # device -> set of trunk ports

        import re as _re
        for name, data in configs.items():
            config = data["config"]
            dtype = data["type"] or ""

            # Extract IP addresses
            for match in _re.finditer(r"ip address\s+((?:\d{1,3}\.){3}\d{1,3})\s+", config):
                ip = match.group(1)
                if ip in ip_map and ip_map[ip] != name:
                    findings.append({
                        "severity": "critical",
                        "check": "IP Conflict",
                        "issue": f"IP {ip} is assigned on both {ip_map[ip]} and {name}",
                    })
                ip_map[ip] = name

            # Extract VLANs
            vlan_ids = set(_re.findall(r"\bvlan\s+(\d+)\b", config, _re.IGNORECASE))
            vlan_map[name] = vlan_ids

            # Detect routing protocol
            config_lower = config.lower()
            if "router ospf" in config_lower:
                protocols[name] = "ospf"
            elif "router eigrp" in config_lower:
                protocols[name] = "eigrp"
            elif "router rip" in config_lower:
                protocols[name] = "rip"
            else:
                protocols[name] = "none"

            # Detect trunks
            if "switchport mode trunk" in config_lower:
                trunk_devices[name] = True

        # Cross-check: routing protocol consistency (routers only)
        router_protos = {n: p for n, p in protocols.items() if p != "none"}
        unique_protos = set(router_protos.values())
        if len(unique_protos) > 1:
            findings.append({
                "severity": "critical",
                "check": "Routing Protocol Mismatch",
                "issue": f"Multiple protocols detected: {dict(router_protos)}. All routers must use the same protocol.",
            })

        # Cross-check: VLAN consistency (access switches should have same VLANs as cores)
        core_vlans = set()
        access_vlans = {}
        for name, vlans in vlan_map.items():
            dtype = configs[name]["type"] or ""
            if "core" in dtype.lower():
                core_vlans.update(vlans)
            elif "switch" in dtype.lower() and "core" not in dtype.lower():
                access_vlans[name] = vlans

        for acc_name, acc_vlans in access_vlans.items():
            missing = core_vlans - acc_vlans - {"1"}  # VLAN 1 is always implicit
            if missing:
                findings.append({
                    "severity": "warning",
                    "check": "VLAN Consistency",
                    "issue": f"{acc_name} is missing VLANs {sorted(missing)} that exist on core switches.",
                })

        status = "PASS" if not findings else ("FAIL" if any(f["severity"] == "critical" for f in findings) else "WARNING")
        result = {
            "status": status,
            "devices_checked": len(configs),
            "findings_count": len(findings),
            "ip_assignments": ip_map,
            "protocol_map": protocols,
            "findings": findings,
        }
        ctx.log(f"<span style='color:#3fb950'><b>[Tool]</b> Validation complete: {status} ({len(findings)} findings across {len(configs)} devices)</span>\n")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Validation error: {e}"


def bulk_deploy(device_names: str) -> str:
    """Deploy saved configs to multiple devices sequentially in the correct order.

    Deploys core switches first, then routers, then access switches.
    If a device fails, logs the error and continues with remaining devices.

    Args:
        device_names: JSON array of device names to deploy, e.g. '["ESW1", "ESW2", "R1", "IOU1"]'

    Returns a structured per-device deployment status report.
    """
    ctx.log(f"<span style='color:#a371f7'><b>[Tool]</b> bulk_deploy()</span>\n")
    try:
        names = _parse_json_string_list(device_names, "device_names")
        if not names:
            return json.dumps({"error": "No device names provided."})

        from network_manager.config import conn, db_lock

        # Sort into deployment order: core → router → access
        ordered = {"core": [], "router": [], "access": [], "unknown": []}
        for name in names:
            with db_lock:
                _cur = conn.cursor()
                _cur.execute("SELECT type FROM devices WHERE name=?", (name,))
                row = _cur.fetchone()
                _cur.close()
            dtype = (row[0] or "").lower() if row else ""
            if "core" in dtype:
                ordered["core"].append(name)
            elif "router" in dtype:
                ordered["router"].append(name)
            elif "switch" in dtype:
                ordered["access"].append(name)
            else:
                ordered["unknown"].append(name)

        deploy_order = ordered["core"] + ordered["router"] + ordered["access"] + ordered["unknown"]
        ctx.log(f"<span style='color:#8b949e'>[Copilot] Deploy order: {' → '.join(deploy_order)}</span>\n")

        import concurrent.futures

        results = []
        for phase in ["core", "router", "access", "unknown"]:
            phase_devices = ordered[phase]
            if not phase_devices:
                continue

            ctx.log(f"<span style='color:#58A6FF'><b>[Bulk Deploy]</b> Starting phase '{phase}' — {len(phase_devices)} devices concurrently...</span>\n")

            def _deploy_single(name: str):
                saved_raw = get_saved_config(name)
                try:
                    saved_data = json.loads(saved_raw)
                    config_text = saved_data.get("content", "")
                except (json.JSONDecodeError, TypeError):
                    return {"device": name, "status": "SKIPPED", "reason": "No saved config found."}

                if not config_text.strip():
                    return {"device": name, "status": "SKIPPED", "reason": "Saved config is empty."}

                # Brief jitter to avoid hammering GNS3 multiplexer at the exact same millisecond
                import random
                time.sleep(random.uniform(0.1, 0.5))

                deploy_result = deploy_to_device(device_name=name, config_text=config_text)
                if "FAILED" in deploy_result.upper() or "BLOCKED" in deploy_result.upper():
                    return {"device": name, "status": "FAILED", "reason": deploy_result[:300]}
                else:
                    return {"device": name, "status": "SUCCESS", "reason": deploy_result[:200]}

            # Run concurrently for all devices in this phase
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(phase_devices)) as executor:
                futures = {executor.submit(_deploy_single, name): name for name in phase_devices}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        name = futures[future]
                        results.append({"device": name, "status": "FAILED", "reason": f"Exception: {exc}"})
            
            # Brief pause between phases so topology can settle (e.g. trunks come up)
            time.sleep(2.0)

        # Summary
        success_count = sum(1 for r in results if r["status"] == "SUCCESS")
        fail_count = sum(1 for r in results if r["status"] == "FAILED")
        skip_count = sum(1 for r in results if r["status"] == "SKIPPED")

        report = {
            "total": len(deploy_order),
            "success": success_count,
            "failed": fail_count,
            "skipped": skip_count,
            "deploy_order": deploy_order,
            "results": results,
        }
        ctx.log(f"<span style='color:#3fb950'><b>[Tool]</b> Bulk deploy complete: {success_count}/{len(deploy_order)} succeeded</span>\n")
        return json.dumps(report, indent=2)
    except Exception as e:
        return f"Bulk deploy error: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# ALL TOOLS LIST — registered with Gemini
# ═══════════════════════════════════════════════════════════════════════════════

ALL_TOOLS = [
    # GNS3
    list_gns3_projects,
    list_gns3_nodes,
    get_node_ports,
    get_topology_links,
    get_network_overview,
    # Terminal
    run_cli_on_device,
    # Database
    list_all_devices,
    get_device_credentials,
    get_saved_config,
    get_send_history,
    query_logs,
    # Config generation
    generate_device_config,
    generate_and_deploy_device_config,
    detect_topology,
    suggest_configs,
    # Deployment
    deploy_to_device,
    verify_device,
    bulk_deploy,
    # Intelligence
    audit_network,
    trace_connectivity,
    validate_configs,
    # Utilities
    calculate_subnet,
    get_agent_guidelines,
]

# Map function names for the agentic loop dispatcher
TOOL_MAP = {fn.__name__: fn for fn in ALL_TOOLS}

# Friendly UI status messages for major tools
_MAJOR_TOOL_STATUS = {
    "get_network_overview": "Analyzing network topology...",
    "list_all_devices": "Fetching device list...",
    "get_topology_links": "Mapping topology links...",
    "audit_network": "Running security audit...",
    "trace_connectivity": "Tracing connectivity path...",
    "validate_configs": "Validating configurations...",
    "bulk_deploy": "Deploying to multiple devices...",
    "generate_device_config": "Generating device configuration...",
    "generate_and_deploy_device_config": "Generating and deploying configuration...",
    "deploy_to_device": "Deploying configuration...",
}


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
        
        # Only use the top description (before Args:) for the main tool description
        # to prevent massively bloated schemas that cause API 500 errors.
        if "Args:" in docstring:
            description = docstring.split("Args:")[0].strip()
        else:
            description = docstring.strip() if docstring else f"Call {fn.__name__}"
        
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
You are **ANCS Copilot**, a fully autonomous AI Network Engineer Agent embedded inside ANCS (Auto Network Configuration System). You explore, analyze, configure, deploy, and troubleshoot network devices.

# ENVIRONMENT
- Devices run inside **GNS3** (emulator), NOT physical hardware
- **Older Cisco IOS images** (c3725, c3640, c7200, vIOS) — classic CLI syntax
- **Telnet** is the primary connection method (GNS3 console ports, 5000+)

## Device Roles
- **Router** (`device_role='router'`): Routes between networks. Runs dynamic protocols (RIP/OSPF/EIGRP). Does router-on-a-stick (subinterfaces). Connects to WAN. Runs DHCP for its VLANs.
- **Core switch** (`device_role='core'`): L3 switch. Routes between VLANs via SVIs. Does NOT run dynamic routing — uses static default route to upstream router. May run DHCP if it's the gateway.
- **Access switch** (`device_role='access'`): Pure Layer 2. Assigns ports to VLANs, trunks up. No routing, no DHCP, no SVIs. Ever.

# YOUR TOOLS

**Network Discovery:**
- `get_network_overview(project_id)` — **START HERE**. Returns all devices + topology links in one call.
- `list_gns3_projects()`, `list_gns3_nodes(project_id)`, `get_node_ports(project_id, node_id)`, `get_topology_links(project_id)`

**Device Terminal (live state):**
- `run_cli_on_device(device_name, command)` — run any IOS command on any device by name

**Database:**
- `list_all_devices()`, `get_device_credentials(device_name)`, `get_saved_config(device_name)`, `get_send_history(device_name)`, `query_logs(severity, limit)`

**Config Generation & Deployment:**
- `generate_and_deploy_device_config(hostname, device_role, ...)` — **PREFERRED**. Generates + deploys atomically.
- `generate_device_config(hostname, device_role, ...)` — generate only (saves to DB)
- `deploy_to_device(device_name, config_text)` — deploy a saved/existing config
- `bulk_deploy(device_names)` — deploy to multiple devices in correct order
- `detect_topology()`, `suggest_configs()`

**Network Intelligence:**
- `validate_configs(device_names)` — dry-run cross-check for IP conflicts, VLAN mismatches, protocol issues
- `audit_network()` — scan configs for security issues
- `trace_connectivity(source_device, destination_ip)` — hop-by-hop diagnosis

**Reference & Utilities:**
- `get_agent_guidelines(topic)` — **call this** when you need design principles, routing protocol guidance, IOS syntax, or deployment order rules
- `calculate_subnet(ip, prefix)`

# CONFIG GENERATION (ABSOLUTE RULE)
Config generation runs 100% locally via the ConfigEngine. Your job is ONLY to supply correct parameters.

**NEVER write IOS commands in your response.** Call `generate_and_deploy_device_config(...)` with correct parameters and report the result.

## Parameter Checklist
**Router**: hostname, device_role='router', router_interface (REQUIRED), vlans, routing_entries, routing_protocol (call `get_agent_guidelines('routing_protocol')` if unsure), dhcp_pools, wan_interface, wan_ip
**Core switch**: hostname, device_role='core', vlans, uplinks (REQUIRED), routing_entries (SVIs), routing_protocol='none' (ALWAYS), static_routes
**Access switch**: hostname, device_role='access', vlans, uplinks (REQUIRED). No routing, no DHCP.

# GROUNDING & CONTEXT
- You start with NO knowledge of the network. Call `get_network_overview()` FIRST when asked about devices, topology, or configuration tasks.
- For design decisions, call `get_agent_guidelines(topic)` to get the relevant principles.
- For simple queries (ping, status): execute tools immediately, don't over-analyze.

## Interface Mapping — NEVER GUESS
Before passing interface names to any config tool:
1. Call `get_topology_links(project_id)` to see what interfaces are physically cabled.
2. Call `list_gns3_nodes(project_id)` to map node IDs to device names.
3. Trace connections: verify an interface actually connects where you think it does.
Guessing interfaces causes silent config failures.

# RULES
1. **Live-verify with tools**: Use `run_cli_on_device` to check actual device state when needed.
2. **Cross-reference**: When troubleshooting, compare configs across ALL devices.
3. **Deploy when asked**: If the user says "configure", "deploy", or "set up" — that is permission. Only ask for confirmation when ambiguous or destructive.
4. **Markdown output**: Clear headings, **bold**, short lists.
5. **Plain language first**: Lead with a simple verdict. CLI commands in backticks with plain-English gloss.
6. **Don't end with vague questions.** Run safe checks yourself and report results.
7. **Chain tools intelligently**: Multiple steps -> execute in sequence.
8. **NEVER WRITE IOS IN YOUR RESPONSE**: Call tools. Let the ConfigEngine handle syntax.
9. **Think network-wide**: A change to one device almost always requires changes to others.
10. **Deployment report**: After configuring multiple devices, summarize with a per-device status table.

## TROUBLESHOOTING DISCIPLINE (CRITICAL)
11. **Layer 1 first, ALWAYS.** Run `show ip interface brief` BEFORE debugging routing protocols. If Status is not "up/up", STOP — the issue is physical/admin, not routing.
12. **Read the CLI prompt.** Before sending any command, check the last prompt (`R1#`, `R1(config)#`, `R1(config-router)#`). If you're in the wrong mode, send `end` first. NEVER retry a command with a syntax tweak without checking the prompt mode.
13. **Check BOTH ends.** When troubleshooting a link, ALWAYS check the interface and config on BOTH devices, not just the failing one.
14. **No blind retries.** If a command or ping fails, you are BANNED from retrying it immediately. You MUST first: (a) form a hypothesis, (b) run a diagnostic command to test it, (c) apply a fix, THEN retry.
15. **Live state beats static validation.** `validate_configs` returning PASS does NOT mean the network works. Always verify critical changes with live pings or `show` commands. Trust hierarchy: live pings > show commands > running-config > DB configs.
16. **`terminal length 0` first.** Always run `terminal length 0` as the first command in any new session to prevent `--More--` truncation.
17. **`router_interface` = Router-on-a-Stick ONLY.** When calling `generate_device_config` for a router with routed ports (no subinterfaces), leave `router_interface` EMPTY. Setting it generates unwanted subinterfaces that conflict with direct IP assignments.

# AUDIENCE
Primary users are beginners. Reduce fear and confusion. Be a tutor, not a grader.

# CONVERSATION STYLE
- **Answer-first**: Understandable summary before optional detail.
- **Friendly, patient, concise.**
- Do **not** open with "what would you like to do?" — respond to what they asked.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# COPILOT LOGGER — structured session log files
# ═══════════════════════════════════════════════════════════════════════════════

class CopilotLogger:
    """Writes structured session logs to timestamped files.

    Each session creates a new log file in `copilot_logs/` (next to the DB file).
    Logs: user messages, AI responses, tool calls (name+args), tool results, timings.
    """

    def __init__(self):
        self._file = None
        self._path = None
        self._start_time = None

    def start(self, provider: str = "", model: str = "") -> str:
        """Open a new session log file. Returns the file path."""
        import os
        from datetime import datetime

        self._start_time = datetime.now()
        timestamp = self._start_time.strftime("%Y-%m-%d_%H%M%S")

        # Determine log directory (next to the DB file)
        try:
            from network_manager.config import CONFIG_FILE
            log_dir = os.path.join(os.path.dirname(CONFIG_FILE), "copilot_logs")
        except Exception:
            log_dir = os.path.join(os.path.expanduser("~"), "copilot_logs")

        os.makedirs(log_dir, exist_ok=True)
        self._path = os.path.join(log_dir, f"session_{timestamp}.log")

        try:
            self._file = open(self._path, "w", encoding="utf-8")
            self._write_header(provider, model)
        except Exception:
            self._file = None
        return self._path or ""

    def _write_header(self, provider: str, model: str):
        """Write session metadata header."""
        if not self._file:
            return
        from datetime import datetime
        self._file.write("=" * 72 + "\n")
        self._file.write(f"ANCS Copilot Session Log\n")
        self._file.write(f"Started: {datetime.now().isoformat()}\n")
        self._file.write(f"Provider: {provider}\n")
        self._file.write(f"Model: {model}\n")
        self._file.write("=" * 72 + "\n\n")
        self._file.flush()

    def log_user_message(self, text: str):
        """Log a user message."""
        self._write_entry("USER", text)

    def log_ai_response(self, text: str):
        """Log an AI response."""
        self._write_entry("AI", text[:2000])  # Truncate to avoid massive logs

    def log_tool_call(self, name: str, args: dict):
        """Log a tool invocation with its arguments."""
        import json
        args_str = json.dumps(args, indent=2, default=str)[:1000]
        self._write_entry("TOOL_CALL", f"{name}({args_str})")

    def log_tool_result(self, name: str, result: str, duration_ms: float = 0):
        """Log a tool result (truncated) with timing."""
        result_preview = result[:500] if result else "(empty)"
        timing = f" [{duration_ms:.0f}ms]" if duration_ms else ""
        self._write_entry("TOOL_RESULT", f"{name}{timing}: {result_preview}")

    def log_error(self, error: str):
        """Log an error."""
        self._write_entry("ERROR", error)

    def log_terminal(self, html_text: str):
        """Log terminal output (strip HTML tags)."""
        import re
        clean = re.sub(r'<[^>]+>', '', html_text).strip()
        if clean:
            self._write_entry("LOG", clean)

    def _write_entry(self, tag: str, content: str):
        """Write a timestamped log entry."""
        if not self._file:
            return
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._file.write(f"[{ts}] [{tag}] {content}\n")
        self._file.flush()

    def close(self):
        """Close the log file with a footer."""
        if not self._file:
            return
        from datetime import datetime
        self._file.write("\n" + "=" * 72 + "\n")
        self._file.write(f"Session ended: {datetime.now().isoformat()}\n")
        if self._start_time:
            duration = datetime.now() - self._start_time
            self._file.write(f"Duration: {duration}\n")
        self._file.write("=" * 72 + "\n")
        self._file.flush()
        self._file.close()
        self._file = None

    @property
    def path(self) -> str:
        return self._path or ""


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

        # Session logger
        self._logger = CopilotLogger()
        self._log_path = self._logger.start(provider=provider, model=model_name)

        # Wire context
        ctx.gns3_url = gns3_url
        ctx.gns3_project_id = gns3_project_id or ""
        ctx.primary_device_name = ""  # no single focus
        ctx.allow_raw_deploy = allow_raw_deploy
        if ctx.sessions is None:
            ctx.sessions = {}
        ctx.log_fn = lambda msg: self.terminal_log_signal.emit(msg)
        ctx.audit_fn = audit_fn
        ctx.workspace_resolved = self.workspace_resolved  # live GNS3 ports for tool functions

    def queue_message(self, text: str):
        """Called from the GUI thread to queue a user message."""
        self._msg_queue.append(text)

    def stop(self):
        self._running = False
        try:
            self._logger.close()
        except Exception:
            pass

    @property
    def session_log_path(self) -> str:
        """Return the path to the current session log file."""
        return self._logger.path if self._logger else ""

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
        import asyncio

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
                    try:
                        _ww = ctx.sessions[name][1]
                        _wo = _ww._w if hasattr(_ww, "_w") else _ww
                        _sk = _wo.get_extra_info('socket')
                        if _sk: _sk.close()
                    except Exception: pass
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
                    asyncio.open_connection(host, port), timeout=10
                )
            except Exception as e:
                self.terminal_log_signal.emit(
                    f"<span style='color:#d73a49'>[Copilot] Pool skip {name}: {e}</span>\n"
                )
                continue

            # Wrap raw streams: str-based API + strip Telnet IAC from GNS3
            from network_manager.network.sender import _strip_telnet_iac
            class _StrReader:
                def __init__(self, r): self._r = r
                async def read(self, n):
                    data = await self._r.read(n)
                    if not data: return ""
                    return _strip_telnet_iac(data).decode("utf-8", errors="ignore")
            class _StrWriter:
                def __init__(self, w): self._w = w
                def write(self, s): self._w.write(s.encode("utf-8") if isinstance(s, str) else s)
                def close(self): self._w.close()
            reader = _StrReader(reader)
            writer = _StrWriter(writer)

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
                    w_obj = writer._w if hasattr(writer, "_w") else writer
                    sock = w_obj.get_extra_info('socket')
                    if sock:
                        sock.close()
                except Exception:
                    pass

    def _process_response_gemini(self, response):
        """Handle the agentic tool-calling loop and return final text."""
        MAX_TURNS = 10
        for turn in range(MAX_TURNS):
            function_calls = []
            if response.candidates:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            # Stream thinking to Logs tab (Gemini 3.5 Flash)
                            if getattr(part, 'thought', False) and hasattr(part, 'text') and part.text:
                                thought_preview = part.text[:500]
                                self.terminal_log_signal.emit(
                                    f"<span style='color: #d2a8ff'>💭 [Thinking] {thought_preview}</span>\n"
                                )
                            elif hasattr(part, 'function_call') and part.function_call:
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

                # Session logger
                self._logger.log_tool_call(fn_name, fn_args)
                self._logger.log_tool_result(fn_name, str(result), dt_ms)

                function_responses.append(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": result},
                    )
                )

            if turn == MAX_TURNS - 2:
                function_responses.append(
                    types.Part.from_text(
                        "SYSTEM: Maximum tool calls approaching. You MUST provide a final answer on your next response. Do not call more tools."
                    )
                )

            response = self._chat.send_message(function_responses)

        # Extract text (skip thought parts — those were already streamed to Logs)
        final_text = ""
        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        # Stream any remaining thoughts from final response
                        if getattr(part, 'thought', False) and hasattr(part, 'text') and part.text:
                            thought_preview = part.text[:500]
                            self.terminal_log_signal.emit(
                                f"<span style='color: #d2a8ff'>💭 [Thinking] {thought_preview}</span>\n"
                            )
                        elif hasattr(part, 'text') and part.text:
                            final_text += part.text

        return final_text or "I completed the requested actions. Check the Execution Logs for details."

    def _process_response_openrouter(self, response):
        """Handle the agentic tool-calling loop (OpenAI format) and return final text.

        When the model returns multiple tool_calls in one response (e.g. deploying
        to 5 devices at once), they are executed in parallel using a thread pool.
        Single tool calls run directly on the current thread (no overhead).
        """
        MAX_TURNS = 10
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

            # Force-stop injection near the end of allowed turns
            if turn == MAX_TURNS - 2:
                self._messages.append({
                    "role": "user",
                    "content": "SYSTEM: Maximum tool calls approaching. You MUST provide a final answer on your next response. Do not call more tools.",
                })

            # Get next response with retry logic for rate limits / timeouts
            self._truncate_history()
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
                except openai.APITimeoutError:
                    # Hapuppy's Cloudflare proxy enforces a 120 s read timeout.
                    # The model took too long to generate a response for this turn.
                    raise RuntimeError(
                        "⏱️ **Request timed out** — the model took too long to respond on this turn.\n\n"
                        "This usually happens when you ask for a very large output (e.g. full VLAN + "
                        "routing configs for many devices) in a single message.\n\n"
                        "**Try breaking the task into smaller steps**, for example:\n"
                        "- *'Generate and deploy VLANs only first'*\n"
                        "- *'Now add routing'*\n"
                        "- *'Now add DHCP'*"
                    )
                except openai.APIStatusError as exc:
                    if exc.status_code == 524:
                        raise RuntimeError(
                            "⏱️ **Gateway timeout (524)** — Hapuppy's Cloudflare proxy dropped the "
                            "connection after 120 s because the model was still generating.\n\n"
                            "**Break the task into smaller steps** to keep each response short enough "
                            "to complete within the 120-second window."
                        )
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

        if fn_name in _MAJOR_TOOL_STATUS:
            self.terminal_log_signal.emit(
                f"<span style='color: #8b949e'>[Copilot] {_MAJOR_TOOL_STATUS[fn_name]}</span>\n"
            )

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

        # Session logger
        self._logger.log_tool_call(fn_name, fn_args)
        self._logger.log_tool_result(fn_name, str(result), dt_ms)

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
                if fn_name in ("deploy_to_device", "deploy_config_telnet", "deploy_config_ssh", "generate_and_deploy_device_config"):
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

    def _truncate_history(self, max_messages=20):
        """Sliding window: keep system prompt + last N messages, cutting at safe boundaries.

        Never separates an assistant message with tool_calls from its subsequent
        tool response messages — doing so causes an API 400 error.
        """
        if len(self._messages) <= max_messages:
            return
        keep_from = len(self._messages) - (max_messages - 1)
        while keep_from < len(self._messages):
            msg = self._messages[keep_from]
            role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
            if role == "user":
                break
            if role == "assistant":
                tc = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
                if not tc:
                    break
            keep_from += 1
        if keep_from >= len(self._messages):
            return
        old_len = len(self._messages)
        self._messages = [self._messages[0]] + self._messages[keep_from:]
        self.terminal_log_signal.emit(
            f"<span style='color:#8b949e'>[Copilot] History trimmed: {old_len} → {len(self._messages)} messages</span>\n"
        )

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
                        import os
                        location = "global"
                        try:
                            from network_manager.config import CONFIG_FILE
                            if os.path.exists(CONFIG_FILE):
                                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                                    cfg_data = json.load(f)
                                    location = cfg_data.get("gemini_location", "us-central1")
                        except Exception:
                            pass
                        
                        project_id = self.api_key.strip() if self.api_key else None
                        self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] Project: {project_id} | Location: {location}</span>\n")
                        self._client = genai.Client(vertexai=True, project=project_id, location=location)
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
                                thinking_config=types.ThinkingConfig(
                                    include_thoughts=True,
                                    thinking_level="medium",
                                ),
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

                # Set timeout to 115 s — just under Hapuppy/Cloudflare's 120 s proxy
                # read-timeout window.  This makes Python raise openai.APITimeoutError
                # cleanly instead of waiting for a Cloudflare 524 response.
                client_timeout = 115.0 if self.provider == "hapuppy" else 180.0
                self._client = openai.OpenAI(
                    api_key=self.api_key,
                    base_url=base_url,
                    default_headers=headers,
                    timeout=client_timeout,
                )
                if not self._messages:
                    self._messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                    ]
                self.terminal_log_signal.emit(f"<span style='color: #3fb950'>[Copilot] Model: {self.model_name} ✓</span>\n")

            # 4. Hardcoded greeting — no API call needed
            greeting_text = (
                f"**Hello!** I'm your ANCS Copilot, ready to manage your network. "
                f"I'm connected to GNS3 project `{self.gns3_project_id}`. "
                f"Ask me anything — configure devices, troubleshoot connectivity, "
                f"audit security, or deploy configs."
            )
            self.chat_response_signal.emit(greeting_text)
            self.ready_signal.emit()

            # 5. Message loop
            while self._running:
                if self._msg_queue:
                    user_msg = self._msg_queue.pop(0)
                    self.terminal_log_signal.emit(f"\n<span style='color: #58A6FF'><b>[User]</b> {user_msg}</span>\n")
                    self._logger.log_user_message(user_msg)
                    try:
                        if self.provider in ("gemini", "vertex"):
                            response = self._send_with_retry(user_msg)
                        else:
                            self._messages.append({"role": "user", "content": user_msg})
                            self._truncate_history()
                            response = self._client.chat.completions.create(
                                model=self.model_name,
                                messages=self._messages,
                                tools=OPENAI_TOOLS,
                                extra_headers={"HTTP-Referer": "https://github.com/ANCS", "X-Title": "ANCS Copilot"} if self.provider == "openrouter" else {},
                            )
                        reply = self._process_response(response)
                        self._logger.log_ai_response(reply)
                        self.chat_response_signal.emit(reply)
                    except openai.APITimeoutError:
                        self.chat_response_signal.emit(
                            "⏱️ **Request timed out** — the model took longer than 115 seconds to respond.\n\n"
                            "This happens when you ask for a very large output (many configs) in one go. "
                            "**Break the task into smaller steps** — e.g. generate VLANs first, then routing, then DHCP."
                        )
                    except openai.APIStatusError as exc:
                        if exc.status_code == 524:
                            self.chat_response_signal.emit(
                                "⏱️ **Gateway timeout (524)** — Hapuppy's Cloudflare proxy dropped the connection "
                                "after 120 s because the model was still generating a very long response.\n\n"
                                "**Try breaking the task into smaller steps** — one device or one config section at a time."
                            )
                        else:
                            self.chat_response_signal.emit(f"**API Error {exc.status_code}:** {exc.message}")
                    except Exception as e:
                        self.chat_response_signal.emit(f"**Error:** {e}")
                else:
                    time.sleep(0.1)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            traceback.print_exc()
            try:
                crash_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "crash.log")
                with open(crash_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*80}\n{time.strftime('%Y-%m-%d %H:%M:%S')} CopilotWorker.run() crash:\n{tb}\n{'='*80}\n")
                print(f"\n\n*** CRASH LOGGED TO {crash_path} ***\n\n", flush=True)
            except Exception:
                pass
            self.finished_signal.emit(f"Copilot error: {e}", False)
        finally:
            for _n, pair in list((ctx.sessions or {}).items()):
                try:
                    if pair and len(pair) > 1 and pair[1]:
                        _w = pair[1]
                        w_obj = _w._w if hasattr(_w, "_w") else _w
                        sock = w_obj.get_extra_info('socket')
                        if sock:
                            sock.close()
                except Exception:
                    pass
            try:
                ctx.sessions = {}
                if ctx.telnet_writer:
                    _w = ctx.telnet_writer
                    w_obj = _w._w if hasattr(_w, "_w") else _w
                    sock = w_obj.get_extra_info('socket')
                    if sock:
                        sock.close()
                    ctx.telnet_writer = None
                    ctx.telnet_reader = None
            except Exception:
                pass
            if self._loop:
                self._loop.close()
