"""
state_snapshot.py — Network State Snapshot Tool (Phase 2.1)

Pulls live state from all running devices in parallel using the existing
Sender.run_show_commands_telnet (raw TCP, NOT deprecated telnetlib).

The "Golden Trio" per device:
1. Interfaces + IP state  (show ip interface brief)
2. Routing table          (show ip route)
3. ARP table              (show arp)

Plus optional extras (full mode):
4. OSPF neighbors         (show ip ospf neighbor)
5. VLAN database          (show vlan brief)
6. Trunk ports            (show interfaces trunk)

This file is PURELY ADDITIVE — it does NOT modify any existing files.
"""

import json
import time
import threading
from typing import Optional

from network_manager.network.sender import Sender

# TextFSM + ntc-templates (optional — graceful fallback to raw output)
try:
    from ntc_templates.parse import parse_output as ntc_parse
    HAS_TEXTFSM = True
except ImportError:
    HAS_TEXTFSM = False


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
    
    Uses Sender.run_show_commands_telnet (raw TCP via asyncio, Python 3.13+ safe).
    
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

    # Run commands via Sender (uses raw TCP — works on Python 3.13+)
    log_lines = []
    def log_fn(msg):
        log_lines.append(msg)

    raw_outputs = Sender.run_show_commands_telnet(
        log_fn,
        host,
        port,
        username,
        password,
        enable_password,
        commands,
    )

    if raw_outputs.get("_error"):
        return {
            "device": device_name,
            "status": "error",
            "error": raw_outputs["_error"],
            "log": log_lines[-3:] if log_lines else [],
            "elapsed_seconds": round(time.time() - t0, 1),
        }

    # Parse each command output
    state: dict = {
        "device": device_name,
        "status": "ok",
    }

    key_map = {
        "show ip interface brief": "interfaces",
        "show ip route": "routing_table",
        "show arp": "arp_table",
        "show ip ospf neighbor": "ospf_neighbors",
        "show vlan brief": "vlan_database",
        "show interfaces trunk": "trunk_ports",
    }

    for cmd in commands:
        raw = raw_outputs.get(cmd, "")
        parsed = _parse_with_textfsm(cmd, raw)
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
            log_fn(f"  Snapshotting {name}...")
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
            status = "OK" if state["status"] == "ok" else "FAIL"
            elapsed = state.get("elapsed_seconds", "?")
            log_fn(f"  {name}: {status} ({elapsed}s)")

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
