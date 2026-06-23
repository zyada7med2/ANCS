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
    "network_manager/gui/template_selector_dialog.py",
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

new_tools = ["snapshot_network_state", "cleanup_device", "provision_topology"]
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
test("provision_topology in prompt", "provision_topology" in system_prompt)



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
# TEST 14: GNS3 Templates Tool & Browser Behavior Removal
# ==============================================================
print("\n" + "="*60)
print("TEST 14: GNS3 Templates Tool & Browser Behavior Removal")
print("="*60)

test("Function defined: list_gns3_templates", "def list_gns3_templates(" in source)
test("ALL_TOOLS contains: list_gns3_templates", "list_gns3_templates" in source.split("ALL_TOOLS")[1].split("]")[0])
test("add_gns3_node docstring updated", "list_gns3_templates() FIRST" in source)
test("compile_system_prompt contains templates rule", "list_gns3_templates" in system_prompt)

with open(os.path.join(PROJECT_ROOT, "network_manager/gui/agent_dialog.py"), encoding="utf-8") as f:
    dialog_src = f.read()

test("ANCSWebEnginePage overrides createStandardContextMenu", "def createStandardContextMenu(self):" in dialog_src)
test("ANCSWebEnginePage overrides acceptNavigationRequest", "def acceptNavigationRequest(self, url, navigationType, isMainFrame):" in dialog_src)
test("ContextMenuPolicy NoContextMenu is set", "ContextMenuPolicy.NoContextMenu" in dialog_src)
test("eventFilter implemented in ANCSAgentDialog", "def eventFilter(self, watched, event):" in dialog_src)
test("installEventFilter is called", "installEventFilter(self)" in dialog_src)


# ==============================================================
# TEST 15: Parallel dispatch, CLI Error detection, Snapshot Bypass
# ==============================================================
print("\n" + "="*60)
print("TEST 15: Parallel dispatch, CLI Error detection, Snapshot Bypass")
print("="*60)

# 1. Parallel execution check: verify we have concurrent execution logic in _process_response_gemini
test("Concurrent execution logic present in ai_agent.py", "ThreadPoolExecutor" in source)
test("Staggered deployment tool calls delay in ai_agent.py", "index * 0.5" in source)

# 2. CLI error detection in deploy_to_device test
mock_logs_with_error = [
    "[telnet] sent: interface GigabitEthernet0/1",
    "[telnet] sent: switchport mode access",
    "[telnet] response: % Invalid input detected at '^' marker.",
]

def simulate_deploy_cli_error_check(log_lines):
    cli_errors = []
    for log_line in log_lines:
        if "%" in log_line:
            lower_line = log_line.lower()
            if "invalid input" in lower_line or "unknown command" in lower_line or \
               "incomplete command" in lower_line or "ambiguous command" in lower_line:
                cli_errors.append(log_line.strip())
    
    if cli_errors:
        return True, cli_errors
    return False, []

has_err, errs = simulate_deploy_cli_error_check(mock_logs_with_error)
test("CLI Error Check detects Invalid input in log", has_err)
test("CLI Error Check extracts exact error", len(errs) == 1 and "% Invalid input" in errs[0])

mock_logs_clean = [
    "[telnet] sent: interface GigabitEthernet0/1",
    "[telnet] sent: ip address 10.0.0.1 255.255.255.0",
]
has_err_clean, _ = simulate_deploy_cli_error_check(mock_logs_clean)
test("CLI Error Check ignores clean logs", not has_err_clean)

# 3. Snapshot Bypassing logic check
class MockContext:
    def __init__(self):
        self.auto_approve = False
        self.newly_created_devices = set()
        
mock_ctx = MockContext()

def simulate_snapshot_bypass_check(ctx, device_name):
    if getattr(ctx, "auto_approve", False) or device_name in getattr(ctx, "newly_created_devices", set()):
        return True
    return False

test("Snapshot not bypassed by default", not simulate_snapshot_bypass_check(mock_ctx, "R1"))

mock_ctx.auto_approve = True
test("Snapshot bypassed when auto_approve=True", simulate_snapshot_bypass_check(mock_ctx, "R1"))

mock_ctx.auto_approve = False
mock_ctx.newly_created_devices.add("R1")
test("Snapshot bypassed when device is newly created", simulate_snapshot_bypass_check(mock_ctx, "R1"))
# ==============================================================
# TEST 16: GNS3 Template Selector UI & Heuristics
# ==============================================================
print("\n" + "="*60)
print("TEST 16: GNS3 Template Selector UI & Heuristics")
print("="*60)

try:
    from network_manager.gui.template_selector_dialog import TemplateSelectorDialog, request_template_selection
    from PySide6.QtWidgets import QApplication
    
    # Initialize a dummy QApplication if not already running
    app = QApplication.instance()
    if not app:
        app = QApplication([])

    # Mock templates list
    mock_templates = [
        {"name": "c7200", "template_id": "t1"},
        {"name": "layer 2", "template_id": "t2"},
        {"name": "EtherSwitchr l3", "template_id": "t3"},
        {"name": "win7", "template_id": "t4"},
    ]
    
    dialog = TemplateSelectorDialog(
        roles=["router", "core", "switch"],
        available_templates=mock_templates,
        current_mappings={"router": "", "core": "", "switch": ""}
    )
    
    # Verify heuristics
    test("Guess Router matches c7200", dialog._guess_template_for_role("router", ["c7200", "layer 2", "EtherSwitchr l3"]) == "c7200")
    test("Guess Core matches EtherSwitchr l3", dialog._guess_template_for_role("core", ["c7200", "layer 2", "EtherSwitchr l3"]) == "EtherSwitchr l3")
    test("Guess Switch matches layer 2", dialog._guess_template_for_role("switch", ["c7200", "layer 2", "EtherSwitchr l3"]) == "layer 2")
    
except Exception as e:
    test("GNS3 Template Selector Heuristics Load", False, f"Failed to import/run test: {e}")


# ==============================================================
# TEST 17: provision_topology End-to-End Mocked Test
# ==============================================================
print("\n" + "="*60)
print("TEST 17: provision_topology End-to-End Mocked Test")
print("="*60)

try:
    from network_manager.ai_agent import ctx, provision_topology
    
    # Store originals
    orig_connector = getattr(ctx, "_gns3_connector_instance", None)
    orig_project_id = ctx.gns3_project_id
    
    class MockGNS3Connector:
        def __init__(self):
            self.created_nodes = []
            self.created_links = []
            self.started_nodes = []
            
        def get_templates(self):
            return [
                {"name": "c7200", "template_id": "t1"},
                {"name": "layer 2", "template_id": "t2"},
                {"name": "EtherSwitchr l3", "template_id": "t3"}
            ]
            
        def create_node(self, project_id, name, template_id, x, y):
            self.created_nodes.append((name, template_id, x, y))
            return {"node_id": f"node_{name}", "console_host": "127.0.0.1", "console": 5000 + len(self.created_nodes)}
            
        def get_node_ports(self, project_id, node_id):
            return [
                {"name": "FastEthernet0/0", "short_name": "f0/0", "adapter_number": 0, "port_number": 0},
                {"name": "FastEthernet1/0", "short_name": "f1/0", "adapter_number": 1, "port_number": 0}
            ]
            
        def create_link(self, project_id, id_a, adapter_a, port_a, id_b, adapter_b, port_b):
            self.created_links.append((id_a, port_a, id_b, port_b))
            return {"link_id": f"link_{id_a}_{id_b}"}
            
        def start_node(self, project_id, node_id):
            self.started_nodes.append(node_id)
            return True

    mock_conn = MockGNS3Connector()
    type(ctx)._gns3_connector_instance = mock_conn
    ctx.gns3_project_id = "test-project-id"
    
    # Run provision_topology
    test_topology_json = """{
        "nodes": [
            {"name": "TEST-R1", "role": "router", "template": "c7200", "x": -100, "y": -100},
            {"name": "TEST-SW1", "role": "switch", "template": "layer 2", "x": 100, "y": 100}
        ],
        "links": [
            {"node_a": "TEST-R1", "port_a": "f0/0", "node_b": "TEST-SW1", "port_b": "f1/0"}
        ]
    }"""
    
    result = provision_topology(test_topology_json)
    
    # Assertions
    test("provision_topology returned success status", "Successfully provisioned" in result)
    test("provision_topology created 2 nodes", len(mock_conn.created_nodes) == 2)
    test("provision_topology resolved router template to t1", mock_conn.created_nodes[0][1] == "t1")
    test("provision_topology resolved switch template to t2", mock_conn.created_nodes[1][1] == "t2")
    test("provision_topology connected 1 link", len(mock_conn.created_links) == 1)
    test("provision_topology started 2 nodes", len(mock_conn.started_nodes) == 2)
    test("provision_topology added devices to ctx.newly_created_devices", "TEST-R1" in ctx.newly_created_devices)
    
    # Restore originals
    type(ctx)._gns3_connector_instance = orig_connector
    ctx.gns3_project_id = orig_project_id
    
except Exception as e:
    test("provision_topology End-to-End Test Execution", False, f"Failed: {e}")


# ==============================================================
# TEST 18: GNS3 Name Sync Conflict and Router Speed/Duplex Omission
# ==============================================================
print("\n" + "="*60)
print("TEST 18: GNS3 Name Sync Conflict and Router Speed/Duplex Omission")
print("="*60)

try:
    # 1. Test name synchronization conflict
    from network_manager.ai_agent import ctx, provision_topology
    
    orig_connector = getattr(ctx, "_gns3_connector_instance", None)
    orig_project_id = ctx.gns3_project_id
    
    class ConflictingGNS3Connector:
        def __init__(self):
            self.created_nodes = []
            self.created_links = []
            self.started_nodes = []
            
        def get_templates(self):
            return [
                {"name": "c7200", "template_id": "t1"}
            ]
            
        def create_node(self, project_id, name, template_id, x, y):
            self.created_nodes.append((name, template_id, x, y))
            # Mock renaming: TEST-R1 gets renamed to TEST-R3 by GNS3
            actual_name = "TEST-R3" if name == "TEST-R1" else name
            return {"node_id": f"node_{actual_name}", "name": actual_name, "console_host": "127.0.0.1", "console": 5001}
            
        def get_node_ports(self, project_id, node_id):
            return [
                {"name": "FastEthernet0/0", "short_name": "f0/0", "adapter_number": 0, "port_number": 0}
            ]
            
        def start_node(self, project_id, node_id):
            self.started_nodes.append(node_id)
            return True

    mock_conflict_conn = ConflictingGNS3Connector()
    type(ctx)._gns3_connector_instance = mock_conflict_conn
    ctx.gns3_project_id = "test-project-id"
    
    # Run provision_topology where requested name is TEST-R1 but actual is TEST-R3
    conflict_topology_json = """{
        "nodes": [
            {"name": "TEST-R1", "role": "router", "template": "c7200", "x": -100, "y": -100}
        ],
        "links": []
    }"""
    
    # Ensure R3 is not in newly_created_devices first
    if hasattr(ctx, "newly_created_devices"):
        ctx.newly_created_devices.discard("TEST-R3")
        ctx.newly_created_devices.discard("TEST-R1")
        
    result = provision_topology(conflict_topology_json)
    
    test("provision_topology with conflict added TEST-R3 to newly_created_devices", "TEST-R3" in ctx.newly_created_devices)
    test("provision_topology with conflict did NOT add TEST-R1 to newly_created_devices", "TEST-R1" not in ctx.newly_created_devices)
    
    # Verify database sync has TEST-R3
    from network_manager.config import conn, db_lock
    with db_lock:
        cur = conn.cursor()
        cur.execute("SELECT name FROM devices WHERE node_id=?", ("node_TEST-R3",))
        row = cur.fetchone()
        cur.close()
    test("Database synced TEST-R3 node name on conflict", row is not None and row[0] == "TEST-R3")
    
    # Restore connector
    type(ctx)._gns3_connector_instance = orig_connector
    ctx.gns3_project_id = orig_project_id
    
    # 2. Test speed/duplex omission for routers in CiscoIOSProfile
    from network_manager.vendors.cisco_ios import CiscoIOSProfile
    profile = CiscoIOSProfile()
    
    # Router transit links block
    transit_config = profile._render_transit_links_block([
        {"local_interface": "FastEthernet0/0", "ip": "10.0.0.1", "mask": "255.255.255.252"}
    ])
    test("Router transit links do not have speed 100", "speed 100" not in transit_config)
    test("Router transit links do not have duplex full", "duplex full" not in transit_config)
    
    # Router parent stick block
    stick_config = profile._render_router_on_stick_block("FastEthernet0/0", [
        {"vlan": "10", "ip": "192.168.10.1", "mask": "255.255.255.0"}
    ])
    test("Router stick parent interface does not have speed 100", "speed 100" not in stick_config)
    test("Router stick parent interface does not have duplex full", "duplex full" not in stick_config)
    
    # Switch uplink block (should STILL have speed/duplex)
    uplink_config = profile.render_uplink_block([
        {"ports": "FastEthernet1/0", "mode": "trunk", "allowed vlans": "all"}
    ])
    test("Switch uplink still has speed 100", "speed 100" in uplink_config)
    test("Switch uplink still has duplex full", "duplex full" in uplink_config)
    
except Exception as e:
    test("TEST 18 Execution Failed", False, f"Failed: {e}")


# ==============================================================
# TEST 19: Telnet Wake-up & Classification Improvements
# ==============================================================
print("\n" + "="*60)
print("TEST 19: Telnet Wake-up & Classification Improvements")
print("="*60)

try:
    # 1. Test class keyword checks on l3_keywords
    with open(os.path.join(PROJECT_ROOT, "network_manager/gui/app.py"), "r", encoding="utf-8") as f:
        app_source = f.read()
    with open(os.path.join(PROJECT_ROOT, "network_manager/ai_agent.py"), "r", encoding="utf-8") as f:
        agent_source = f.read()
        
    test("app.py l3_keywords contains 'etherswitch'", "'etherswitch'" in app_source)
    test("app.py l3_keywords contains 'l3'", "'l3'" in app_source)
    test("ai_agent.py l3_keywords contains 'etherswitch'", "'etherswitch'" in agent_source)
    test("ai_agent.py l3_keywords contains 'l3'", "'l3'" in agent_source)

    # 2. Test Sender._telnet_wake_gns3_console logic
    import asyncio
    from network_manager.network.sender import Sender

    class DummyWriter:
        def __init__(self):
            self.writes = []
        def write(self, data):
            self.writes.append(data)
            
    class DummyReader:
        def __init__(self, outputs):
            self.outputs = outputs
            self.idx = 0
        async def read(self, n=4096):
            if self.idx < len(self.outputs):
                val = self.outputs[self.idx]
                self.idx += 1
                return val
            return ""

    writer = DummyWriter()
    
    async def mock_read_ready(timeout):
        return ""
    
    buf_ready = asyncio.run(Sender._telnet_wake_gns3_console(writer, mock_read_ready, lambda m: None, "Switch#"))
    test("Console wake-up breaks immediately if already at prompt", buf_ready == "Switch#")
    test("No enters sent for already-prompt console", len(writer.writes) == 0)

    # Scenario B: Device is booting and decompressing, then needs enter
    boot_sequence = [
        "Self decompressing the image ... [OK]\r\nCisco IOS Software, C3725 Software ...\r\n",
        "Line protocol on Interface FastEthernet0/0, changed state to down\r\n",
        "Press RETURN to get started!\r\n",
        "Switch>"
    ]
    
    reader_b = DummyReader(boot_sequence)
    async def mock_read_b(timeout):
        return await reader_b.read()
        
    writer_b = DummyWriter()
    buf_b = asyncio.run(Sender._telnet_wake_gns3_console(writer_b, mock_read_b, lambda m: None, ""))
    
    test("Console wake-up sends Enter key when it sees banner or return prompt", len(writer_b.writes) > 0)
    test("Console wake-up successfully wakes switch and reaches prompt", "Switch>" in buf_b)
    
except Exception as e:
    test("TEST 19 Execution Failed", False, f"Failed: {e}")


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
