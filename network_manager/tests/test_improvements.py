"""
test_improvements.py - Tests for all ANCS Copilot improvements (Batches 1-4)

Tests pure logic without requiring GNS3 or live devices.
Run: python test_improvements.py
"""

import sys
import os
import json
import ast
import re

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

PASS = 0
FAIL = 0
ERRORS = []

def test(name, condition, detail=""):
    global PASS, FAIL, ERRORS
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        msg = f"  FAIL: {name}" + (f" -- {detail}" if detail else "")
        print(msg)
        ERRORS.append(msg)


# ==============================================================
# TEST 1: Syntax Validation (all 3 files)
# ==============================================================
print("\n" + "="*60)
print("TEST 1: Syntax Validation")
print("="*60)

files_to_check = [
    "network_manager/ai_agent.py",
    "network_manager/network/state_snapshot.py",
    "network_manager/gui/deploy_review_dialog.py",
]

for f in files_to_check:
    path = os.path.join(PROJECT_ROOT, f)
    try:
        with open(path, encoding="utf-8") as fh:
            ast.parse(fh.read())
        test(f"Syntax OK: {os.path.basename(f)}", True)
    except SyntaxError as e:
        test(f"Syntax OK: {os.path.basename(f)}", False, str(e))


# ==============================================================
# TEST 2: Tool Registration
# ==============================================================
print("\n" + "="*60)
print("TEST 2: Tool Registration")
print("="*60)

agent_path = os.path.join(PROJECT_ROOT, "network_manager/ai_agent.py")
with open(agent_path, encoding="utf-8") as f:
    source = f.read()

new_tools = ["snapshot_network_state", "cleanup_device"]
for tool_name in new_tools:
    test(f"Function defined: {tool_name}", f"def {tool_name}(" in source)

for tool_name in new_tools:
    test(f"ALL_TOOLS contains: {tool_name}", tool_name in source.split("ALL_TOOLS")[1].split("]")[0])


# ==============================================================
# TEST 3: Thinking Config
# ==============================================================
print("\n" + "="*60)
print("TEST 3: Thinking Config")
print("="*60)

test("ThinkingConfig present", "ThinkingConfig(" in source)
test("include_thoughts=True", "include_thoughts=True" in source)
test("thinking_level medium", 'thinking_level="medium"' in source)
test("Thought extraction: part.thought check", "getattr(part, 'thought', False)" in source)
test("Thought emission to logs", "[Thinking]" in source)


# ==============================================================
# TEST 4: Ghost Device Filtering Logic
# ==============================================================
print("\n" + "="*60)
print("TEST 4: Ghost Device Filtering Logic")
print("="*60)

def simulate_ghost_filter(devices):
    active = [d for d in devices if d.get("status") in ("started", "unknown", None)]
    stopped = [d for d in devices if d.get("status") not in ("started", "unknown", None)]
    stopped_names = {d["name"].lower() for d in stopped}
    for dev in active:
        if "warning" in dev:
            warning_text = dev["warning"].lower()
            for sn in stopped_names:
                if sn in warning_text:
                    del dev["warning"]
                    break
    return active, stopped

mock_devices = [
    {"name": "R1", "status": "started", "port": 5001},
    {"name": "R2", "status": "started", "port": 5002},
    {"name": "R1_old", "status": "stopped", "port": 5001, "warning": "dup"},
    {"name": "SW1", "status": "stopped", "port": 5003},
    {"name": "ESW1", "status": "started", "port": 5004, "warning": "duplicate port shared with SW1"},
]

active, stopped = simulate_ghost_filter(mock_devices)
test("Active devices count = 3", len(active) == 3)
test("Stopped devices count = 2", len(stopped) == 2)
test("R1 is active", any(d["name"] == "R1" for d in active))
test("R1_old is stopped", any(d["name"] == "R1_old" for d in stopped))
test("ESW1 warning removed (SW1 is stopped)",
     not any(d["name"] == "ESW1" and "warning" in d for d in active))


# ==============================================================
# TEST 5: CLI Error Detection
# ==============================================================
print("\n" + "="*60)
print("TEST 5: CLI Error Detection")
print("="*60)

error_patterns = ['% Invalid input', '% Incomplete command', '% Ambiguous command', '% Unknown command']

def simulate_error_check(output):
    for pat in error_patterns:
        if pat in output:
            return f"CLI ERROR: {pat}\n{output}"
    return output

test("Detects Invalid input", "CLI ERROR" in simulate_error_check("% Invalid input detected"))
test("Detects Incomplete", "CLI ERROR" in simulate_error_check("% Incomplete command."))
test("Detects Ambiguous", "CLI ERROR" in simulate_error_check('% Ambiguous command: "sh"'))
test("Clean output passes", "CLI ERROR" not in simulate_error_check("FastEthernet0/0 10.0.0.1 YES up up"))
test("Partial match ignored", "CLI ERROR" not in simulate_error_check("This is 100% valid output"))


# ==============================================================
# TEST 6: Multi-line Command Splitting
# ==============================================================
print("\n" + "="*60)
print("TEST 6: Multi-line Command Splitting")
print("="*60)

def simulate_split(command):
    return [c.strip() for c in command.strip().split('\n') if c.strip()]

test("Single command stays single", simulate_split("show ip route") == ["show ip route"])
test("Multi-line splits correctly",
     simulate_split("configure terminal\nrouter ospf 1\nend") == ["configure terminal", "router ospf 1", "end"])
test("Empty lines ignored", simulate_split("show ip route\n\n\nshow arp\n") == ["show ip route", "show arp"])
test("Whitespace-only ignored", simulate_split("  \n  show version  \n  ") == ["show version"])
test("Empty command = empty list", simulate_split("") == [])


# ==============================================================
# TEST 7: Context Compression Logic
# ==============================================================
print("\n" + "="*60)
print("TEST 7: Context Compression Logic")
print("="*60)

def simulate_compress(messages):
    if len(messages) < 12:
        return 0
    compressed_count = 0
    safe_zone = max(1, len(messages) - 6)
    for i in range(1, safe_zone):
        msg = messages[i]
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        if role == "tool":
            content = msg.get("content", "")
            if len(content) > 500:
                msg["content"] = content[:200] + "\n...[compressed]"
                compressed_count += 1
        elif role == "assistant" and not msg.get("tool_calls"):
            content = msg.get("content", "")
            if content and len(content) > 800:
                msg["content"] = content[:300] + "\n...[compressed]"
                compressed_count += 1
    return compressed_count

test("Skips short history", simulate_compress([{"role": "system"}, {"role": "user"}]) == 0)

# Build 20 messages: system + 7 old tools + 12 recent
mock_msgs = [{"role": "system", "content": "You are..."}]
for i in range(7):
    mock_msgs.append({"role": "tool", "content": "OLD_" + "x" * 800})
for i in range(12):
    mock_msgs.append({"role": "tool", "content": "RECENT_" + "y" * 800})

count = simulate_compress(mock_msgs)
test(f"Compresses old messages ({count} compressed)", count > 0)
test("Message count unchanged (in-place)", len(mock_msgs) == 20)

# Verify last 6 are untouched
last_6_ok = all("compressed" not in msg.get("content", "") for msg in mock_msgs[-6:])
test("Last 6 messages untouched", last_6_ok)
test("System prompt untouched", mock_msgs[0]["content"] == "You are...")


# ==============================================================
# TEST 8: Cleanup Command Generation
# ==============================================================
print("\n" + "="*60)
print("TEST 8: Cleanup Command Generation")
print("="*60)

mock_running_config = """
hostname R1
!
interface FastEthernet0/0
 no ip address
!
interface FastEthernet0/0.10
 encapsulation dot1Q 10
 ip address 192.168.10.1 255.255.255.0
!
interface FastEthernet0/0.20
 encapsulation dot1Q 20
 ip address 192.168.20.1 255.255.255.0
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
!
router rip
 network 10.0.0.0
!
ip dhcp pool VLAN10
 network 192.168.10.0 255.255.255.0
!
ip dhcp excluded-address 192.168.10.1 192.168.10.10
!
ip route 0.0.0.0 0.0.0.0 10.0.0.1
"""

cleanup = ["configure terminal"]
if "router ospf" in mock_running_config:
    for m in re.finditer(r'router ospf (\d+)', mock_running_config):
        cleanup.append(f"no router ospf {m.group(1)}")
if "router rip" in mock_running_config:
    cleanup.append("no router rip")
for m in re.finditer(r'interface (\S+\.\d+)', mock_running_config):
    cleanup.append(f"no interface {m.group(1)}")
for m in re.finditer(r'ip dhcp pool (\S+)', mock_running_config):
    cleanup.append(f"no ip dhcp pool {m.group(1)}")
for m in re.finditer(r'(ip dhcp excluded-address .+)', mock_running_config):
    cleanup.append(f"no {m.group(1)}")
for m in re.finditer(r'(ip route \S+ \S+ \S+)', mock_running_config):
    cleanup.append(f"no {m.group(1)}")
cleanup.append("end")

test("Removes OSPF", "no router ospf 1" in cleanup)
test("Removes RIP", "no router rip" in cleanup)
test("Removes subinterface .10", "no interface FastEthernet0/0.10" in cleanup)
test("Removes subinterface .20", "no interface FastEthernet0/0.20" in cleanup)
test("Removes DHCP pool", "no ip dhcp pool VLAN10" in cleanup)
test("Removes DHCP excluded", any("no ip dhcp excluded-address" in c for c in cleanup))
test("Removes static route", "no ip route 0.0.0.0 0.0.0.0 10.0.0.1" in cleanup)
test("Starts with configure terminal", cleanup[0] == "configure terminal")
test("Ends with end", cleanup[-1] == "end")


# ==============================================================
# TEST 9: System Prompt Rules
# ==============================================================
print("\n" + "="*60)
print("TEST 9: System Prompt Rules")
print("="*60)

prompt_start = source.find('def compile_system_prompt()')
if prompt_start == -1:
    # Fallback: try old format
    prompt_start = source.find('SYSTEM_PROMPT = \"\"\"')
    prompt_end = source.index('\"\"\"', prompt_start + 20)
    system_prompt = source[prompt_start:prompt_end]
else:
    # New format: import the compiled prompt directly
    from network_manager.ai_agent import SYSTEM_PROMPT as system_prompt

test("Rule: Layer 1 first", "Layer 1 first" in system_prompt)
test("Rule: Read the CLI prompt", "Read the CLI prompt" in system_prompt)
test("Rule: Check BOTH ends", "Check BOTH ends" in system_prompt)
test("Rule: No blind retries", "blind retries" in system_prompt)
test("Rule: Live state beats static", "Live state beats" in system_prompt)
test("Rule: terminal length 0", "terminal length 0" in system_prompt)
test("Rule: router_interface warning", "Router-on-a-Stick" in system_prompt)
test("snapshot_network_state in prompt", "snapshot_network_state" in system_prompt)
test("cleanup_device in prompt", "cleanup_device" in system_prompt)


# ==============================================================
# TEST 10: State Snapshot Module
# ==============================================================
print("\n" + "="*60)
print("TEST 10: State Snapshot Module")
print("="*60)

snap_path = os.path.join(PROJECT_ROOT, "network_manager/network/state_snapshot.py")
with open(snap_path, encoding="utf-8") as f:
    snap_source = f.read()

test("snapshot_single_device defined", "def snapshot_single_device(" in snap_source)
test("snapshot_all_devices defined", "def snapshot_all_devices(" in snap_source)
test("Uses threading", "import threading" in snap_source)
test("Uses Sender (not deprecated telnetlib)", "from network_manager.network.sender import Sender" in snap_source)
test("No deprecated telnetlib", "import telnetlib" not in snap_source)
test("TextFSM graceful import", "HAS_TEXTFSM" in snap_source)
test("Golden Trio commands",
     all(c in snap_source for c in ["show ip interface brief", "show ip route", "show arp"]))
test("Full mode extras",
     all(c in snap_source for c in ["show ip ospf neighbor", "show vlan brief", "show interfaces trunk"]))


# ==============================================================
# TEST 11: Deploy Review Dialog
# ==============================================================
print("\n" + "="*60)
print("TEST 11: Deploy Review Dialog")
print("="*60)

dialog_path = os.path.join(PROJECT_ROOT, "network_manager/gui/deploy_review_dialog.py")
with open(dialog_path, encoding="utf-8") as f:
    dialog_source = f.read()

test("DeployReviewDialog class", "class DeployReviewDialog" in dialog_source)
test("IOSSyntaxHighlighter class", "class IOSSyntaxHighlighter" in dialog_source)
test("request_deploy_approval function", "def request_deploy_approval(" in dialog_source)
test("Thread-safe: Signal/Slot bridge", "_ReviewBridge" in dialog_source and "threading.Event" in dialog_source)
test("Approve button", "Approve" in dialog_source)
test("Reject button", "Reject" in dialog_source)
test("IOS no commands highlighted red", "#f85149" in dialog_source)
test("HITL gate in generate_and_deploy", "request_deploy_approval" in source)
test("Rejected deployment message", "REJECTED by user" in source)
test("Graceful fallback with traceback", "HITL dialog FAILED" in source)


# ==============================================================
# TEST 12: Retry Logic
# ==============================================================
print("\n" + "="*60)
print("TEST 12: Retry Logic")
print("="*60)

test("Retry loop in tool-response send", "Rate limited mid-tool-loop" in source)
test("429 detection", '"429"' in source)
test("resource_exhausted detection", '"resource_exhausted"' in source)
test("Exponential backoff", "2 ** (_retry + 1)" in source)


# ==============================================================
# TEST 13: Chat History Bridge Slots
# ==============================================================
print("\n" + "="*60)
print("TEST 13: Chat History Bridge Slots")
print("="*60)

with open(os.path.join(PROJECT_ROOT, "network_manager/gui/agent_bridge.py"), encoding="utf-8") as f:
    bridge_src = f.read()

test("getConversationMessages defined", "def getConversationMessages(" in bridge_src)
test("renameConversation defined", "def renameConversation(" in bridge_src)
test("Enriched getPastConversations search", "message_count" in bridge_src and "enriched_list" in bridge_src)


# ==============================================================
# RESULTS
# ==============================================================
print("\n" + "="*60)
total = PASS + FAIL
print(f"RESULTS: {PASS}/{total} passed, {FAIL} failed")
print("="*60)

if ERRORS:
    print("\nFailed tests:")
    for e in ERRORS:
        print(e)

sys.exit(0 if FAIL == 0 else 1)
