"""
state_snapshot.py — Network State Snapshot Tool (Phase 2.1)

Pulls live state from all running devices in parallel using disposable
Telnet connections (NOT the shared session pool). Parses outputs with
TextFSM + ntc-templates for tabular show commands, and returns structured
JSON that the AI agent can analyze offline.

The "Golden Trio" per device:
1. Interfaces + IP state  (show ip interface brief)
2. Routing table          (show ip route)
3. ARP table              (show arp)

Plus optional extras:
4. OSPF neighbors         (show ip ospf neighbor)
5. VLAN database          (show vlan-switch brief / show vlan brief)
6. Trunk ports            (show interfaces trunk)

This file is PURELY ADDITIVE — it does NOT modify any existing files.
"""

import json
import time
import telnetlib
import threading
from typing import Optional

# TextFSM + ntc-templates (optional — graceful fallback to raw output)
try:
    import textfsm
    from ntc_templates.parse import parse_output as ntc_parse
    HAS_TEXTFSM = True
except ImportError:
    HAS_TEXTFSM = False


def _telnet_run_commands(
    host: str,
    port: int,
    username: str,
    password: str,
    enable_password: str,
    commands: list[str],
    timeout: float = 12.0,
) -> dict[str, str]:
    """
    Open a disposable Telnet connection, login, run a list of show commands,
    and return a dict mapping command -> raw output.
    
    This does NOT use the shared session pool — it's a fresh, throwaway connection.
    """
    results = {}
    try:
        tn = telnetlib.Telnet(host, port, timeout=8)

        # Login sequence — handle various IOS console prompts
        idx, _, _ = tn.expect([b"Username:", b"Password:", b">", b"#"], timeout=5)
        if idx == 0:  # Username prompt
            tn.write(username.encode("ascii") + b"\n")
            tn.read_until(b"Password:", timeout=3)
            tn.write(password.encode("ascii") + b"\n")
        elif idx == 1:  # Password prompt (no username)
            tn.write(password.encode("ascii") + b"\n")
        # else: already at > or # prompt

        # Wait for prompt
        tn.expect([b">", b"#"], timeout=3)

        # Enter enable mode if we're at >
        tn.write(b"enable\n")
        idx2, _, _ = tn.expect([b"Password:", b"#"], timeout=2)
        if idx2 == 0:
            tn.write((enable_password or password or "").encode("ascii") + b"\n")
            tn.expect([b"#"], timeout=2)

        # Disable paging
        tn.write(b"terminal length 0\n")
        time.sleep(0.3)
        tn.read_very_eager()  # clear buffer

        # Run each command
        for cmd in commands:
            tn.write(cmd.encode("ascii") + b"\n")
            time.sleep(1.5)  # Wait for output
            # Read until we see the prompt again
            raw = b""
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    chunk = tn.read_very_eager()
                    if chunk:
                        raw += chunk
                        # Check if we're back at the prompt
                        text = raw.decode("ascii", errors="replace").rstrip()
                        if text and text[-1] == "#":
                            break
                    else:
                        time.sleep(0.3)
                except EOFError:
                    break
            results[cmd] = raw.decode("ascii", errors="replace")

        tn.write(b"exit\n")
        tn.close()
    except Exception as e:
        results["_error"] = str(e)

    return results


def _parse_with_textfsm(command: str, raw_output: str, platform: str = "cisco_ios") -> list[dict] | str:
    """
    Parse raw CLI output using ntc-templates TextFSM.
    Returns structured list of dicts, or the raw string if parsing fails.
    """
    if not HAS_TEXTFSM:
        return raw_output

    try:
        parsed = ntc_parse(platform=platform, command=command, data=raw_output)
        return parsed if parsed else raw_output
    except Exception:
        return raw_output


def snapshot_single_device(
    device_name: str,
    host: str,
    port: int,
    username: str,
    password: str,
    enable_password: str,
    mode: str = "lite",
) -> dict:
    """
    Snapshot one device. Returns structured state dict.
    
    mode="lite":  Golden Trio only (interfaces, ARP, routing table) — ~5-6s
    mode="full":  All commands — ~13-15s
    """
    t0 = time.time()

    # Define commands by mode
    lite_commands = [
        "show ip interface brief",
        "show ip route",
        "show arp",
    ]
    full_extras = [
        "show ip ospf neighbor",
        "show vlan brief",
        "show interfaces trunk",
    ]

    commands = lite_commands if mode == "lite" else lite_commands + full_extras

    # Run commands via disposable connection
    raw_outputs = _telnet_run_commands(
        host, port, username, password, enable_password, commands
    )

    if "_error" in raw_outputs:
        return {
            "device": device_name,
            "status": "error",
            "error": raw_outputs["_error"],
            "elapsed_seconds": round(time.time() - t0, 1),
        }

    # Parse each command output
    state: dict = {
        "device": device_name,
        "status": "ok",
    }

    for cmd in commands:
        raw = raw_outputs.get(cmd, "")
        parsed = _parse_with_textfsm(cmd, raw)
        # Map command to a clean key name
        key_map = {
            "show ip interface brief": "interfaces",
            "show ip route": "routing_table",
            "show arp": "arp_table",
            "show ip ospf neighbor": "ospf_neighbors",
            "show vlan brief": "vlan_database",
            "show interfaces trunk": "trunk_ports",
        }
        key = key_map.get(cmd, cmd.replace(" ", "_"))
        state[key] = parsed

    state["elapsed_seconds"] = round(time.time() - t0, 1)
    return state


def snapshot_all_devices(
    devices: list[dict],
    mode: str = "lite",
    max_threads: int = 8,
    log_fn: Optional[callable] = None,
) -> dict:
    """
    Snapshot multiple devices in parallel using threads.
    
    Args:
        devices: list of dicts with keys: name, host, port, username, password, enable_password
        mode: "lite" (Golden Trio) or "full" (all commands)
        max_threads: max parallel connections
        log_fn: optional callback for progress logging
    
    Returns:
        dict with keys: devices (list of per-device snapshots), summary, elapsed_seconds
    """
    t0 = time.time()
    results = {}
    lock = threading.Lock()

    def worker(dev: dict):
        name = dev["name"]
        if log_fn:
            log_fn(f"  ├── Snapshotting {name}...")
        state = snapshot_single_device(
            device_name=name,
            host=dev["host"],
            port=dev["port"],
            username=dev.get("username", ""),
            password=dev.get("password", ""),
            enable_password=dev.get("enable_password", ""),
            mode=mode,
        )
        with lock:
            results[name] = state
        if log_fn:
            status = "✅" if state["status"] == "ok" else "❌"
            elapsed = state.get("elapsed_seconds", "?")
            log_fn(f"  ├── {name}: {status} ({elapsed}s)")

    # Run in parallel with bounded threads
    threads = []
    for dev in devices:
        t = threading.Thread(target=worker, args=(dev,), daemon=True)
        threads.append(t)

    # Start threads in batches
    for i in range(0, len(threads), max_threads):
        batch = threads[i:i + max_threads]
        for t in batch:
            t.start()
        for t in batch:
            t.join(timeout=30)

    # Build summary
    ok_count = sum(1 for r in results.values() if r["status"] == "ok")
    err_count = sum(1 for r in results.values() if r["status"] == "error")
    total_elapsed = round(time.time() - t0, 1)

    return {
        "summary": {
            "total_devices": len(devices),
            "successful": ok_count,
            "failed": err_count,
            "mode": mode,
            "elapsed_seconds": total_elapsed,
        },
        "devices": results,
    }
