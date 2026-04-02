"""
Comprehensive test for multi-protocol routing config generation.
Tests all 3 protocols (RIP, OSPF, EIGRP), redistribution, and
validates IOS syntax against known-correct patterns.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.models.devices import RouterModel
from network_manager.gui.wizards.guided_setup_wizard import GuidedSetupWizard

# ── Suppress Qt GUI ──────────────────────────────────────────────────────
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {'— ' + detail if detail else ''}")

def make_wizard(proto, enable_default_route=True, is_redist=False, redist_protos=None):
    """Create a headless wizard with preset data and a specific protocol."""
    model = RouterModel("TestRouter")
    ctx = {}
    if is_redist and redist_protos:
        ctx = {
            "redistribution_router": "TestRouter",
            "redistribution_protocols": redist_protos,
            "redistribution_needed": True,
        }
    w = GuidedSetupWizard(None, "TestRouter", model, device_role="router",
                           known_interfaces=["FastEthernet0/0", "FastEthernet0/1"],
                           headless=True, project_context=ctx)
    w.identity_data = {"hostname": "TestRouter", "domain": "test.local", "enable": "Secret123"}
    w.router_interface = "FastEthernet0/0"
    w.wan_interface = "FastEthernet0/1"
    w.wan_ip = "10.0.0.2"
    w.wan_mask = "255.255.255.252"
    w.routing_entries = [
        {"vlan": "10", "name": "Staff",  "ip": "192.168.10.1", "mask": "255.255.255.0"},
        {"vlan": "20", "name": "Guest",  "ip": "192.168.20.1", "mask": "255.255.255.0"},
    ]
    if enable_default_route:
        w.static_routes = [{"network": "0.0.0.0", "mask": "0.0.0.0",
                            "next-hop": "10.0.0.1", "description": "Default route to ISP"}]
    else:
        w.static_routes = []
    w.routing_protocol = proto
    w.enable_rip = (proto == "rip")
    if is_redist and redist_protos:
        w.is_redistribution_router = True
        w.redistribution_protocols = redist_protos
    return w


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 1: RIP Config Generation ══════")
w = make_wizard("rip")
config = w._render_routing_protocol_block()
print(config)
print()
check("Contains 'router rip'", "router rip" in config)
check("Contains 'version 2'", "version 2" in config)
check("Contains 'no auto-summary'", "no auto-summary" in config)
check("Contains 'network 192.168.10.0' (classful)", "network 192.168.10.0" in config)
check("Contains 'network 192.168.20.0' (classful)", "network 192.168.20.0" in config)
check("Does NOT contain WAN network 10.0.0.0",
      "network 10.0.0.0" not in config,
      f"WAN should not be in RIP — found 'network 10.0.0.0'")
check("Contains 'default-information originate'",
      "default-information originate" in config,
      "Needed so other routers learn the default route")
check("Does NOT contain 'redistribute'",
      "redistribute" not in config,
      "Single protocol should not have redistribution")


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 2: OSPF Config Generation ══════")
w = make_wizard("ospf")
config = w._render_routing_protocol_block()
print(config)
print()
check("Contains 'router ospf 1'", "router ospf 1" in config)
check("Contains 'network 192.168.10.0 0.0.0.255 area 0'",
      "network 192.168.10.0 0.0.0.255 area 0" in config)
check("Contains 'network 192.168.20.0 0.0.0.255 area 0'",
      "network 192.168.20.0 0.0.0.255 area 0" in config)
check("Does NOT contain WAN network 10.0.0.0",
      "10.0.0.0" not in config and "10.0.0.2" not in config,
      "WAN should not be advertised in OSPF")
check("Contains 'default-information originate'",
      "default-information originate" in config)
check("Does NOT contain 'router rip' or 'router eigrp'",
      "router rip" not in config and "router eigrp" not in config)


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 3: EIGRP Config Generation ══════")
w = make_wizard("eigrp")
config = w._render_routing_protocol_block()
print(config)
print()
check("Contains 'router eigrp 10'", "router eigrp 10" in config)
check("Contains 'no auto-summary'", "no auto-summary" in config)
check("Contains 'network 192.168.10.0 0.0.0.255'",
      "network 192.168.10.0 0.0.0.255" in config)
check("Does NOT contain WAN network",
      "10.0.0.0" not in config and "10.0.0.2" not in config)
check("Contains 'redistribute static' (for default route)",
      "redistribute static" in config,
      "EIGRP needs redistribute static, not default-information originate")
check("Does NOT contain 'default-information originate'",
      "default-information originate" not in config,
      "EIGRP uses redistribute static, not default-info")


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 4: None (Static Only) ══════")
w = make_wizard("none")
config = w._render_routing_protocol_block()
check("Config is empty for 'none' protocol", config.strip() == "")


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 5: No Default Route → No default-info originate ══════")
w = make_wizard("ospf", enable_default_route=False)
config = w._render_routing_protocol_block()
print(config)
print()
check("Contains 'router ospf 1'", "router ospf 1" in config)
check("Does NOT contain 'default-information originate'",
      "default-information originate" not in config,
      "No default route → no originate command")


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 6: Redistribution Router (OSPF ↔ RIP) ══════")
w = make_wizard("rip", is_redist=True, redist_protos=["ospf", "rip"])
config = w._render_routing_protocol_block()
print(config)
print()
check("Contains 'router ospf 1'", "router ospf 1" in config)
check("Contains 'router rip'", "router rip" in config)
check("Contains 'redistribute rip subnets' (in OSPF block)",
      "redistribute rip subnets" in config)
check("Contains 'redistribute ospf 1 metric 3' (in RIP block)",
      "redistribute ospf 1 metric 3" in config)
check("Does NOT contain WAN network",
      "10.0.0.0" not in config and "10.0.0.2" not in config)


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 7: Redistribution Router (EIGRP ↔ OSPF) ══════")
w = make_wizard("ospf", is_redist=True, redist_protos=["eigrp", "ospf"])
config = w._render_routing_protocol_block()
print(config)
print()
check("Contains 'router eigrp 10'", "router eigrp 10" in config)
check("Contains 'router ospf 1'", "router ospf 1" in config)
check("Contains 'redistribute ospf 1 metric 1000 100 255 1 1500' (in EIGRP)",
      "redistribute ospf 1 metric 1000 100 255 1 1500" in config)
check("Contains 'redistribute eigrp 10 subnets' (in OSPF)",
      "redistribute eigrp 10 subnets" in config)


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 8: WAN Block is independent ══════")
w = make_wizard("ospf")
wan = w._render_wan_block()
print(wan)
print()
check("WAN block sets IP on WAN interface",
      "ip address 10.0.0.2 255.255.255.252" in wan)
check("WAN block uses correct interface",
      "interface FastEthernet0/1" in wan)


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 9: Static Routes Block ══════")
w = make_wizard("ospf")
sr = w._render_static_routes_block()
print(sr)
print()
check("Contains 'ip route 0.0.0.0 0.0.0.0 10.0.0.1'",
      "ip route 0.0.0.0 0.0.0.0 10.0.0.1" in sr)


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 10: Wildcard / Network Helpers ══════")
check("Wildcard 255.255.255.0 → 0.0.0.255",
      GuidedSetupWizard._to_wildcard("255.255.255.0") == "0.0.0.255")
check("Wildcard 255.255.255.252 → 0.0.0.3",
      GuidedSetupWizard._to_wildcard("255.255.255.252") == "0.0.0.3")
check("Network 192.168.10.1 / 255.255.255.0 → 192.168.10.0",
      GuidedSetupWizard._to_network("192.168.10.1", "255.255.255.0") == "192.168.10.0")
check("Network 10.0.0.2 / 255.255.255.252 → 10.0.0.0",
      GuidedSetupWizard._to_network("10.0.0.2", "255.255.255.252") == "10.0.0.0")
check("Classful 192.168.10.1 → 192.168.10.0 (Class C)",
      GuidedSetupWizard._to_classful("192.168.10.1") == "192.168.10.0")
check("Classful 172.16.5.1 → 172.16.0.0 (Class B)",
      GuidedSetupWizard._to_classful("172.16.5.1") == "172.16.0.0")
check("Classful 10.0.0.2 → 10.0.0.0 (Class A)",
      GuidedSetupWizard._to_classful("10.0.0.2") == "10.0.0.0")


# ═══════════════════════════════════════════════════════════════════════
print("\n══════ TEST 11: Template Key Updated ══════")
w = make_wizard("ospf")
w._write_templates()
check("Template key is 'guided_routing_protocol' (not guided_rip)",
      "guided_routing_protocol" in w.device_model.templates)
check("Legacy 'guided_rip' NOT written",
      "guided_rip" not in w.device_model.templates)
check("guided_routing_protocol contains 'router ospf'",
      "router ospf" in w.device_model.templates.get("guided_routing_protocol", ""))


# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(f"{'='*60}")
if FAIL:
    sys.exit(1)
else:
    print("  All tests passed! ✓")
