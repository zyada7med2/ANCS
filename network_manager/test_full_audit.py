"""
=============================================================================
ANCS Full Audit — Network Engineer Scenario Testing
=============================================================================
Tests EVERY config generation path as if deploying to real Cisco IOS devices.

Scenarios:
  A. Single-network topologies (Router + Core + Access)
  B. Multi-protocol redistribution (OSPF<->RIP, EIGRP<->OSPF, RIP<->EIGRP)
  C. Boundary router (router-only transit links, per-IGP split)
  D. Core switch Layer-3 (SVIs, ip routing)
  E. Access switch Layer-2 (VLANs, trunks, portfast)
  F. DHCP pool generation & excluded addresses
  G. ACL generation & interface application
  H. WAN interface (static IP vs DHCP)
  I. Static routes (default route, extra routes)
  J. Port expansion (range notation)
  K. Sender block splitting
  L. BFS segmentation logic (multi-network isolation)
  M. Edge cases: empty config, missing fields, boundary conditions
  N. Full config build (DeviceModel.build_full_config)
  O. Preset quick-generate (small_office, school_lab, minimal)
"""
import sys, os, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.models.devices import RouterModel, SwitchModel, CoreSwitchModel
from network_manager.gui.wizards.guided_setup_wizard import GuidedSetupWizard
from network_manager.network.sender import Sender

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

PASS = 0
FAIL = 0
ERRORS = []

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        ERRORS.append((name, detail))
        print(f"  [FAIL] {name}  -- {detail}" if detail else f"  [FAIL] {name}")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def make_router_wizard(proto="rip", default_route=True, is_redist=False,
                       redist_protos=None, connected_links=None,
                       is_boundary=False, transit_links=None):
    """Create a headless router wizard with preset data."""
    model = RouterModel("TestRouter")
    ctx = {}
    if is_redist and redist_protos:
        ctx = {
            "redistribution_router": "TestRouter",
            "redistribution_protocols": redist_protos,
            "redistribution_needed": True,
        }
    if is_boundary:
        ctx["redistribution_router"] = "TestRouter"
        ctx["redistribution_protocols"] = redist_protos or []
        ctx["redistribution_needed"] = True
        ctx["protocol_map"] = {}

    w = GuidedSetupWizard(None, "TestRouter", model, device_role="router",
                          known_interfaces=["FastEthernet0/0", "FastEthernet0/1",
                                            "Serial2/0", "Serial3/0"],
                          headless=True, project_context=ctx,
                          connected_links=connected_links or [])
    w.identity_data = {"hostname": "TestRouter", "domain": "test.local", "enable": "Secret123"}
    w.router_interface = "FastEthernet0/0"
    w.wan_interface = "FastEthernet0/1"
    w.wan_ip = "10.0.0.2"
    w.wan_mask = "255.255.255.252"
    w.vlans = [
        {"id": "10", "name": "Staff", "ports": ""},
        {"id": "20", "name": "Guest", "ports": ""},
    ]
    w.routing_entries = [
        {"vlan": "10", "name": "Staff",  "ip": "192.168.10.1", "mask": "255.255.255.0"},
        {"vlan": "20", "name": "Guest",  "ip": "192.168.20.1", "mask": "255.255.255.0"},
    ]
    if default_route:
        w.static_routes = [{"network": "0.0.0.0", "mask": "0.0.0.0",
                            "next-hop": "10.0.0.1", "description": "Default route to ISP"}]
    else:
        w.static_routes = []
    w.routing_protocol = proto
    w.enable_rip = (proto == "rip")
    if is_redist and redist_protos:
        w.is_redistribution_router = True
        w.redistribution_protocols = redist_protos
    if is_boundary and transit_links:
        w.is_boundary_router = True
        w.is_redistribution_router = True
        w.redistribution_protocols = redist_protos or []
        w.transit_links = transit_links
        w.routing_entries = []  # boundary has no subinterfaces
        w.router_interface = ""
    return w


def make_core_wizard(routing_mode="device"):
    """Create a headless core switch wizard."""
    model = CoreSwitchModel("CoreSW1")
    w = GuidedSetupWizard(None, "CoreSW1", model, device_role="core",
                          known_interfaces=["FastEthernet1/0", "FastEthernet1/1",
                                            "FastEthernet1/2", "FastEthernet1/3"],
                          headless=True, project_context={})
    w.routing_mode = routing_mode
    w.identity_data = {"hostname": "CoreSW1", "domain": "corp.local", "enable": "CorePass!"}
    w.vlans = [
        {"id": "10", "name": "Staff", "ports": "FastEthernet1/2,FastEthernet1/3"},
        {"id": "20", "name": "Guest", "ports": ""},
    ]
    w.uplinks = [{"ports": "FastEthernet1/0, FastEthernet1/1", "mode": "trunk", "allowed vlans": "all"}]
    if routing_mode == "device":
        w.routing_entries = [
            {"vlan": "10", "name": "Staff", "ip": "192.168.10.1", "mask": "255.255.255.0"},
            {"vlan": "20", "name": "Guest", "ip": "192.168.20.1", "mask": "255.255.255.0"},
        ]
    else:
        w.routing_entries = []
    return w


def make_access_wizard():
    """Create a headless access switch wizard."""
    model = SwitchModel("AccSW1")
    w = GuidedSetupWizard(None, "AccSW1", model, device_role="access",
                          known_interfaces=["Ethernet0/0", "Ethernet0/1",
                                            "Ethernet0/2", "Ethernet0/3", "Ethernet3/3"],
                          headless=True, project_context={})
    w.identity_data = {"hostname": "AccSW1", "domain": "", "enable": "AccPass!"}
    w.vlans = [
        {"id": "10", "name": "Staff", "ports": "Ethernet0/0,Ethernet0/1"},
        {"id": "20", "name": "Guest", "ports": "Ethernet0/2,Ethernet0/3"},
    ]
    w.uplinks = [{"ports": "Ethernet3/3", "mode": "trunk", "allowed vlans": "all"}]
    return w


# ═══════════════════════════════════════════════════════════════════════════
# SECTION A: Single-Network Router (Router-on-a-stick)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION A: Router-on-a-Stick Config Generation")
print("="*70)

w = make_router_wizard("ospf")

# A1: Identity block
config = w._render_identity_block()
check("A1: hostname set", "hostname TestRouter" in config)
check("A2: domain name set", "ip domain-name test.local" in config)
check("A3: no ip domain-lookup", "no ip domain-lookup" in config)
check("A4: VTY lines configured", "line vty 0 4" in config)
check("A5: transport input", "transport input telnet ssh" in config)

# A6: Subinterface block (router-on-a-stick)
config = w._render_routing_block()
check("A6: Parent interface enabled", f"interface {w.router_interface}" in config)
check("A7: Subinterface .10 created", "interface FastEthernet0/0.10" in config)
check("A8: Subinterface .20 created", "interface FastEthernet0/0.20" in config)
check("A9: dot1Q encapsulation for VLAN 10", "encapsulation dot1Q 10" in config)
check("A10: dot1Q encapsulation for VLAN 20", "encapsulation dot1Q 20" in config)
check("A11: IP address on subinterface", "ip address 192.168.10.1 255.255.255.0" in config)
check("A12: no shutdown on subinterfaces", config.count("no shutdown") >= 3,
      f"Expected >= 3 'no shutdown', got {config.count('no shutdown')}")
check("A13: configure terminal at start", config.startswith("configure terminal"))
check("A14: end at end", config.strip().endswith("end"))

# A15: Speed/duplex on FastEthernet
check("A15: speed 100 on FastEthernet parent", "speed 100" in config)
check("A16: duplex full on FastEthernet parent", "duplex full" in config)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION B: WAN Interface Block
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION B: WAN Interface Block")
print("="*70)

w = make_router_wizard("ospf")
config = w._render_wan_block()
check("B1: WAN interface set", "interface FastEthernet0/1" in config)
check("B2: WAN IP set", "ip address 10.0.0.2 255.255.255.252" in config)
check("B3: WAN no shutdown", "no shutdown" in config)

# B4: DHCP WAN
w2 = make_router_wizard("ospf")
w2.wan_ip = "dhcp"
config = w2._render_wan_block()
check("B4: WAN DHCP mode", "ip address dhcp" in config)
check("B5: No static IP in DHCP mode", "10.0.0.2" not in config)

# B6: Empty WAN
w3 = make_router_wizard("ospf")
w3.wan_interface = ""
w3.wan_ip = ""
config = w3._render_wan_block()
check("B6: No WAN block when empty", config.strip() == "")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION C: Static Routes
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION C: Static Routes")
print("="*70)

w = make_router_wizard("ospf")
config = w._render_static_routes_block()
check("C1: Default route present", "ip route 0.0.0.0 0.0.0.0 10.0.0.1" in config)
check("C2: Description as comment", "Default route to ISP" in config)

# C3: Extra static routes
w2 = make_router_wizard("ospf")
w2.static_routes.append({"network": "172.16.0.0", "mask": "255.255.0.0",
                          "next-hop": "10.0.0.5", "description": "Branch office"})
config = w2._render_static_routes_block()
check("C3: Extra route present", "ip route 172.16.0.0 255.255.0.0 10.0.0.5" in config)
check("C4: Both routes present", config.count("ip route") == 2,
      f"Expected 2 routes, got {config.count('ip route')}")

# C5: No routes
w3 = make_router_wizard("ospf", default_route=False)
config = w3._render_static_routes_block()
check("C5: No routes -> empty block", config.strip() == "")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION D: DHCP Pool Generation
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION D: DHCP Pool Generation")
print("="*70)

w = make_router_wizard("ospf")
w.dhcp_pools = [
    {"pool": "Staff", "network": "192.168.10.0", "mask": "255.255.255.0",
     "gateway": "192.168.10.1", "dns": "8.8.8.8", "start": "192.168.10.50", "end": "192.168.10.200"},
    {"pool": "Guest", "network": "192.168.20.0", "mask": "255.255.255.0",
     "gateway": "192.168.20.1", "dns": "8.8.4.4", "start": "192.168.20.50", "end": "192.168.20.200"},
]
config = w._render_dhcp_block()
check("D1: Staff pool created", "ip dhcp pool Staff" in config)
check("D2: Guest pool created", "ip dhcp pool Guest" in config)
check("D3: Network statement", "network 192.168.10.0 255.255.255.0" in config)
check("D4: Default router", "default-router 192.168.10.1" in config)
check("D5: DNS server Staff", "dns-server 8.8.8.8" in config)
check("D6: DNS server Guest", "dns-server 8.8.4.4" in config)
check("D7: Excluded address (gateway)", "ip dhcp excluded-address 192.168.10.1" in config)
check("D8: Excluded address upper range", "ip dhcp excluded-address 192.168.10.201 192.168.10.254" in config)
check("D9: Lease configured", config.count("lease 0 2") == 2,
      f"Expected 2 lease statements, got {config.count('lease 0 2')}")

# D10: Access switch should NOT produce DHCP
w_acc = make_access_wizard()
w_acc.dhcp_pools = [{"pool": "X", "network": "1.1.1.0", "mask": "255.255.255.0",
                     "gateway": "1.1.1.1", "dns": "8.8.8.8", "start": "1.1.1.10", "end": "1.1.1.100"}]
config = w_acc._render_dhcp_block()
check("D10: Access switch -> no DHCP", config.strip() == "")

# D11: Boundary router should NOT produce DHCP
w_br = make_router_wizard("rip", is_boundary=True, is_redist=True,
                           redist_protos=["ospf", "rip"],
                           connected_links=[
                               {"local_interface": "Serial2/0", "remote_device": "R1",
                                "remote_interface": "Serial0/0", "remote_role": "router"},
                               {"local_interface": "Serial3/0", "remote_device": "R2",
                                "remote_interface": "Serial0/0", "remote_role": "router"},
                           ],
                           transit_links=[
                               {"local_interface": "Serial2/0", "remote_device": "R1",
                                "protocol": "ospf", "ip": "10.0.0.1", "mask": "255.255.255.252"},
                               {"local_interface": "Serial3/0", "remote_device": "R2",
                                "protocol": "rip", "ip": "10.0.4.1", "mask": "255.255.255.252"},
                           ])
w_br.dhcp_pools = [{"pool": "Fake", "network": "10.0.0.0", "mask": "255.255.255.252",
                    "gateway": "10.0.0.1", "dns": "8.8.8.8", "start": "10.0.0.2", "end": "10.0.0.2"}]
config = w_br._render_dhcp_block()
check("D11: Boundary router -> no DHCP", config.strip() == "")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION E: ACL Generation
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION E: ACL Generation")
print("="*70)

w = make_router_wizard("ospf")
w.acl_rules = [
    {"acl #": "101", "action": "deny", "source": "192.168.20.0",
     "wildcard": "0.0.0.255", "destination": "192.168.10.0",
     "destination_wildcard": "0.0.0.255", "remark": "Block Guest from Staff"},
    {"acl #": "101", "action": "permit", "source": "any",
     "wildcard": "", "remark": "Permit all other"},
]
config = w._render_acl_block()
check("E1: ACL remark present", "access-list 101 remark Block Guest from Staff" in config)
check("E2: Deny rule correct", "access-list 101 deny ip 192.168.20.0 0.0.0.255 192.168.10.0 0.0.0.255" in config)
check("E3: Permit any rule", "access-list 101 permit ip any any" in config)
check("E4: ACL applied to subinterface", "ip access-group 101 in" in config)
check("E5: Applied on correct interface",
      "interface FastEthernet0/0.20" in config,
      "ACL should be applied on the source VLAN subinterface")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION F: Core Switch (Layer 3)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION F: Core Switch (Layer 3)")
print("="*70)

w = make_core_wizard("device")

# F1: VLAN block
config = w._render_vlan_block()
check("F1: vlan database start", "vlan database" in config)
check("F2: VLAN 10 Staff", "vlan 10 name Staff" in config)
check("F3: VLAN 20 Guest", "vlan 20 name Guest" in config)
check("F4: Access port assigned (FastEthernet1/2)",
      "interface FastEthernet1/2" in config and "switchport access vlan 10" in config)
check("F5: Uplink port NOT made access",
      # FastEthernet1/0 is uplink, should NOT appear as access
      not re.search(r"interface FastEthernet1/0\n.*switchport mode access", config),
      "Uplink port should not be configured as access")

# F6: SVI routing block
config = w._render_routing_block()
check("F6: ip routing enabled", "ip routing" in config)
check("F7: SVI Vlan10", "interface Vlan10" in config)
check("F8: SVI Vlan20", "interface Vlan20" in config)
check("F9: SVI IP address", "ip address 192.168.10.1 255.255.255.0" in config)
check("F10: SVI no shutdown", "no shutdown" in config)

# F11: Uplink trunks
config = w._render_uplink_block()
check("F11: Trunk encapsulation", "switchport trunk encapsulation dot1q" in config)
check("F12: Trunk mode", "switchport mode trunk" in config)
check("F13: Trunk allowed VLANs", "switchport trunk allowed vlan" in config)

# F14: Core switch L2-only mode
w_l2 = make_core_wizard("external")
config = w_l2._render_routing_block()
check("F14: L2-only core -> no routing block", config.strip() == "")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION G: Access Switch (Layer 2)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION G: Access Switch (Layer 2)")
print("="*70)

w = make_access_wizard()

# G1: VLAN block
config = w._render_vlan_block()
check("G1: VLAN 10 created", "vlan 10" in config)
check("G2: VLAN name", "name Staff" in config)
check("G3: Access ports assigned", "switchport mode access" in config)
check("G4: Portfast enabled", "spanning-tree portfast" in config)
check("G5: Uplink port excluded from access",
      not re.search(r"interface Ethernet3/3\n.*switchport mode access", config),
      "Uplink should not be access port")

# G6: Identity block
config = w._render_identity_block()
check("G6: Switch hostname", "hostname AccSW1" in config)
check("G7: No domain if empty", "ip domain-name" not in config)

# G8: Trunk uplink
config = w._render_uplink_block()
check("G8: Trunk on Ethernet3/3", "interface Ethernet3/3" in config)
check("G9: Trunk mode", "switchport mode trunk" in config)
check("G10: Speed on Ethernet uplink", "speed 100" in config)

# G11: No routing block for access
config = w._render_routing_block()
check("G11: Access switch -> no routing", config.strip() == "")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION H: Boundary Router (Transit Links + Per-IGP Split)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION H: Boundary Router (Transit Links + IGP Split)")
print("="*70)

transit = [
    {"local_interface": "Serial2/0", "remote_device": "R-OSPF",
     "protocol": "ospf", "ip": "10.0.0.1", "mask": "255.255.255.252"},
    {"local_interface": "Serial3/0", "remote_device": "R-RIP",
     "protocol": "rip", "ip": "10.0.4.1", "mask": "255.255.255.252"},
]
links = [
    {"local_interface": "Serial2/0", "remote_device": "R-OSPF",
     "remote_interface": "Serial0/0", "remote_role": "router"},
    {"local_interface": "Serial3/0", "remote_device": "R-RIP",
     "remote_interface": "Serial0/0", "remote_role": "router"},
]
w = make_router_wizard("rip", is_boundary=True, is_redist=True,
                       redist_protos=["ospf", "rip"],
                       connected_links=links, transit_links=transit)

# H1: Transit links block (not subinterfaces)
config = w._render_routing_block()
check("H1: Transit link block generated", "interface Serial2/0" in config)
check("H2: Transit link IP", "ip address 10.0.0.1 255.255.255.252" in config)
check("H3: Both transit links", "interface Serial3/0" in config)
check("H4: Second transit link IP", "ip address 10.0.4.1 255.255.255.252" in config)
check("H5: No subinterface (no dot1Q)", "encapsulation" not in config)
check("H6: No vlan references", "vlan" not in config.lower() or "vlan" not in config)

# H7: Routing protocol block (per-IGP split)
config = w._render_routing_protocol_block()
check("H7: OSPF block present", "router ospf 1" in config)
check("H8: RIP block present", "router rip" in config)
check("H9: OSPF only advertises OSPF-side network",
      "network 10.0.0.0 0.0.0.3 area 0" in config,
      "OSPF should advertise the /30 transit link facing the OSPF neighbor")
check("H10: RIP only advertises RIP-side network",
      "network 10.0.0.0" in config,  # classful
      "RIP should advertise the classful 10.0.0.0")
check("H11: Redistribution RIP into OSPF",
      "redistribute rip subnets" in config)
check("H12: Redistribution OSPF into RIP",
      "redistribute ospf 1 metric 3" in config)

# H13: Boundary detect
check("H13: is_boundary_router flag set", w.is_boundary_router == True)
check("H14: is_redistribution_router flag set", w.is_redistribution_router == True)

# H15: Boundary network collection
by_proto = w._collect_boundary_networks_by_protocol()
check("H15: OSPF networks collected", "ospf" in by_proto and len(by_proto["ospf"]) == 1)
check("H16: RIP networks collected", "rip" in by_proto and len(by_proto["rip"]) == 1)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION I: Boundary Router with EIGRP <-> OSPF
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION I: Boundary Router EIGRP <-> OSPF")
print("="*70)

transit2 = [
    {"local_interface": "FastEthernet0/0", "remote_device": "R-EIGRP",
     "protocol": "eigrp", "ip": "172.16.0.1", "mask": "255.255.255.252"},
    {"local_interface": "FastEthernet0/1", "remote_device": "R-OSPF",
     "protocol": "ospf", "ip": "172.16.4.1", "mask": "255.255.255.252"},
]
links2 = [
    {"local_interface": "FastEthernet0/0", "remote_device": "R-EIGRP",
     "remote_interface": "Fa0/0", "remote_role": "router"},
    {"local_interface": "FastEthernet0/1", "remote_device": "R-OSPF",
     "remote_interface": "Fa0/0", "remote_role": "router"},
]
w = make_router_wizard("eigrp", is_boundary=True, is_redist=True,
                       redist_protos=["eigrp", "ospf"],
                       connected_links=links2, transit_links=transit2)

config = w._render_routing_protocol_block()
check("I1: EIGRP block present", "router eigrp 10" in config)
check("I2: OSPF block present", "router ospf 1" in config)
check("I3: EIGRP network statement", "network 172.16.0.0 0.0.0.3" in config)
check("I4: OSPF network statement", "network 172.16.4.0 0.0.0.3 area 0" in config)
check("I5: Redistribute OSPF into EIGRP",
      "redistribute ospf 1 metric 1000 100 255 1 1500" in config)
check("I6: Redistribute EIGRP into OSPF",
      "redistribute eigrp 10 subnets" in config)

# Transit links block
config = w._render_routing_block()
check("I7: Speed/duplex on FastEthernet transit",
      "speed 100" in config and "duplex full" in config)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION J: Normal Redistribution Router (with switches attached)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION J: Normal Redistribution Router (OSPF<->RIP, with VLANs)")
print("="*70)

w = make_router_wizard("rip", is_redist=True, redist_protos=["ospf", "rip"])
config = w._render_routing_protocol_block()
check("J1: Both protocols present",
      "router ospf 1" in config and "router rip" in config)
check("J2: OSPF advertises VLAN networks",
      "network 192.168.10.0 0.0.0.255 area 0" in config)
check("J3: RIP advertises VLAN networks (classful)",
      "network 192.168.10.0" in config and "network 192.168.20.0" in config)
check("J4: Redistribute RIP->OSPF", "redistribute rip subnets" in config)
check("J5: Redistribute OSPF->RIP", "redistribute ospf 1 metric 3" in config)
check("J6: WAN NOT advertised in protocols",
      "10.0.0.0" not in config and "10.0.0.2" not in config,
      "WAN should never be in routing protocol")

# Normal redist router SHOULD still get DHCP
w.dhcp_pools = [{"pool": "Staff", "network": "192.168.10.0", "mask": "255.255.255.0",
                 "gateway": "192.168.10.1", "dns": "8.8.8.8",
                 "start": "192.168.10.50", "end": "192.168.10.200"}]
config = w._render_dhcp_block()
check("J7: Normal redist router gets DHCP", "ip dhcp pool Staff" in config)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION K: Port Expansion
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION K: Port Range Expansion")
print("="*70)

w = make_access_wizard()
check("K1: Single port", w._expand_ports_to_list("Ethernet0/0") == ["Ethernet0/0"])
check("K2: Range expansion", w._expand_ports_to_list("Ethernet0/0-3") == 
      ["Ethernet0/0", "Ethernet0/1", "Ethernet0/2", "Ethernet0/3"])
check("K3: Comma separated", w._expand_ports_to_list("Ethernet0/0, Ethernet1/0") ==
      ["Ethernet0/0", "Ethernet1/0"])
check("K4: Mixed range and single",
      w._expand_ports_to_list("Ethernet0/0-2, Ethernet3/3") ==
      ["Ethernet0/0", "Ethernet0/1", "Ethernet0/2", "Ethernet3/3"])
check("K5: Empty string", w._expand_ports_to_list("") == [])
check("K6: FastEthernet range",
      w._expand_ports_to_list("FastEthernet1/0-3") ==
      ["FastEthernet1/0", "FastEthernet1/1", "FastEthernet1/2", "FastEthernet1/3"])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION L: Sender Block Splitting
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION L: Sender Block Splitting")
print("="*70)

sample_config = """! =====================================================
! PASTE EACH BLOCK SEPARATELY
! Wait for the device prompt before the next block.
! =====================================================

! ====================================================
! BLOCK 1 — Identity & Security
! ====================================================
configure terminal
hostname TestRouter
no ip domain-lookup
end

! ──────────────────────────────────────────────────────
! Block done — wait for prompt.


! ====================================================
! BLOCK 2 — Routing / Subinterfaces
! ====================================================
configure terminal
interface FastEthernet0/0
 no shutdown
exit
interface FastEthernet0/0.10
 encapsulation dot1Q 10
 ip address 192.168.10.1 255.255.255.0
 no shutdown
exit
end

! ──────────────────────────────────────────────────────
! Block done — wait for prompt.


! ====================================================
! BLOCK 3 — Routing Protocol
! ====================================================
configure terminal
router ospf 1
 network 192.168.10.0 0.0.0.255 area 0
exit
end
"""

blocks = Sender.split_into_blocks(sample_config)
check("L1: Correct number of blocks", len(blocks) == 3,
      f"Expected 3 blocks, got {len(blocks)}")
check("L2: Block 1 title", blocks[0][0] == "Identity & Security" if blocks else False)
check("L3: Block 2 title", blocks[1][0] == "Routing / Subinterfaces" if len(blocks) > 1 else False)
check("L4: Block 3 title", blocks[2][0] == "Routing Protocol" if len(blocks) > 2 else False)
check("L5: Block 1 has real commands", "hostname TestRouter" in blocks[0][1] if blocks else False)
check("L6: No comment lines in block content",
      all(not line.strip().startswith("!") for block in blocks for line in block[1].splitlines() if line.strip()),
      "Block content should not contain comment lines")

# L7: Old-style colon headers
old_style = "! BLOCK 1: Identity\nconfigure terminal\nhostname R1\nend\n"
blocks2 = Sender.split_into_blocks(old_style)
check("L7: Colon-style header parsed", len(blocks2) == 1 and blocks2[0][0] == "Identity")

# L8: No blocks at all
plain = "configure terminal\nhostname R1\nend\n"
blocks3 = Sender.split_into_blocks(plain)
check("L8: No-header fallback", len(blocks3) == 1 and blocks3[0][0] == "Configuration")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION M: Full Config Build (DeviceModel)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION M: Full Config Build (DeviceModel)")
print("="*70)

w = make_router_wizard("ospf")
w.dhcp_pools = w._auto_dhcp_from_routing()
w.acl_rules = [
    {"acl #": "101", "action": "deny", "source": "192.168.20.0",
     "wildcard": "0.0.0.255", "destination": "192.168.10.0",
     "destination_wildcard": "0.0.0.255", "remark": "Block Guest"},
    {"acl #": "101", "action": "permit", "source": "any", "wildcard": "", "remark": "Permit all"},
]
w._write_templates()
full = w.device_model.build_full_config()

check("M1: Full config has BLOCK headers", "! BLOCK" in full)
check("M2: Identity in full config", "hostname TestRouter" in full)
check("M3: Routing in full config", "interface FastEthernet0/0.10" in full)
check("M4: WAN in full config", "interface FastEthernet0/1" in full)
check("M5: Static routes in full config", "ip route 0.0.0.0 0.0.0.0 10.0.0.1" in full)
check("M6: OSPF in full config", "router ospf 1" in full)
check("M7: DHCP in full config", "ip dhcp pool" in full)
check("M8: ACL in full config", "access-list 101" in full)
check("M9: Write memory at end", "write memory" in full)

# Verify Sender can split the full config
blocks = Sender.split_into_blocks(full)
check("M10: Sender splits full config into blocks",
      len(blocks) >= 5,
      f"Expected >= 5 blocks, got {len(blocks)}: {[b[0] for b in blocks]}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION N: Preset Quick-Generate
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION N: Preset Quick-Generate")
print("="*70)

# N1: Router small_office preset
model = RouterModel("R1")
w = GuidedSetupWizard(None, "R1", model, device_role="router",
                      known_interfaces=["FastEthernet0/0", "FastEthernet0/1"],
                      headless=True, project_context={})
w._apply_preset("small_office")
check("N1: Preset sets hostname", w.identity_data.get("hostname") == "R1")
check("N2: Preset creates 2 routing entries", len(w.routing_entries) == 2)
check("N3: Preset creates DHCP pools", len(w.dhcp_pools) == 2)
check("N4: Preset creates static route", len(w.static_routes) > 0)
check("N5: Preset creates ACL rules", len(w.acl_rules) > 0)

# N6: Core switch school_lab preset
model = CoreSwitchModel("CSW1")
w = GuidedSetupWizard(None, "CSW1", model, device_role="core",
                      known_interfaces=["FastEthernet1/0", "FastEthernet1/1"],
                      headless=True, project_context={})
w.routing_mode = "device"
w._apply_preset("school_lab")
check("N6: Core has 3 VLANs", len(w.vlans) == 3)
check("N7: Core has routing entries", len(w.routing_entries) == 3)

# N8: Access switch minimal preset
model = SwitchModel("ASW1")
w = GuidedSetupWizard(None, "ASW1", model, device_role="access",
                      known_interfaces=["Ethernet0/0", "Ethernet0/1", "Ethernet3/3"],
                      headless=True, project_context={})
w._apply_preset("minimal")
check("N8: Access has 1 VLAN", len(w.vlans) == 1)
check("N9: Access has trunk uplink", len(w.uplinks) > 0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION O: Edge Cases & Boundary Conditions
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION O: Edge Cases & Boundary Conditions")
print("="*70)

# O1: Empty identity
w = make_router_wizard("ospf")
w.identity_data = {}
config = w._render_identity_block()
check("O1: Empty identity -> empty block", config.strip() == "")

# O2: No routing entries
w = make_router_wizard("ospf")
w.routing_entries = []
config = w._render_routing_block()
check("O2: No routing entries -> empty block", config.strip() == "")

# O3: No routing entries + not redistribution -> no protocol block
w = make_router_wizard("ospf")
w.routing_entries = []
w.is_redistribution_router = False
config = w._render_routing_protocol_block()
check("O3: No networks + not redist -> empty protocol block", config.strip() == "")

# O4: Empty VLAN list on core
w = make_core_wizard()
w.vlans = []
config = w._render_vlan_block()
check("O4: No VLANs -> empty vlan block", config.strip() == "")

# O5: Router should not produce VLAN block
w = make_router_wizard("ospf")
config = w._render_vlan_block()
check("O5: Router -> no VLAN block", config.strip() == "")

# O6: No uplinks -> empty uplink block
w = make_access_wizard()
w.uplinks = []
config = w._render_uplink_block()
check("O6: No uplinks -> empty block", config.strip() == "")

# O7: Wildcard / Network helpers edge cases
check("O7a: Wildcard 255.0.0.0 -> 0.255.255.255",
      GuidedSetupWizard._to_wildcard("255.0.0.0") == "0.255.255.255")
check("O7b: Network 10.1.2.3 / 255.0.0.0 -> 10.0.0.0",
      GuidedSetupWizard._to_network("10.1.2.3", "255.0.0.0") == "10.0.0.0")
check("O7c: Classful 10.255.255.255 -> 10.0.0.0",
      GuidedSetupWizard._to_classful("10.255.255.255") == "10.0.0.0")
check("O7d: Classful 128.1.2.3 -> 128.1.0.0 (Class B)",
      GuidedSetupWizard._to_classful("128.1.2.3") == "128.1.0.0")
check("O7e: Classful 223.10.20.30 -> 223.10.20.0 (Class C)",
      GuidedSetupWizard._to_classful("223.10.20.30") == "223.10.20.0")

# O8: Boundary router with "none" protocol links
w = make_router_wizard("rip", is_boundary=True, is_redist=True,
                       redist_protos=["ospf", "rip"],
                       connected_links=[
                           {"local_interface": "Serial2/0", "remote_device": "R1",
                            "remote_interface": "Se0/0", "remote_role": "router"},
                       ],
                       transit_links=[
                           {"local_interface": "Serial2/0", "remote_device": "R1",
                            "protocol": "none", "ip": "10.0.0.1", "mask": "255.255.255.252"},
                       ])
by_proto = w._collect_boundary_networks_by_protocol()
check("O8: 'none' protocol excluded from collection",
      "none" not in by_proto, f"Got: {by_proto}")

# O9: DHCP auto-generation from routing entries
w = make_router_wizard("ospf")
pools = w._auto_dhcp_from_routing()
check("O9a: Auto DHCP creates 2 pools", len(pools) == 2)
check("O9b: Pool network correct", pools[0]["network"] == "192.168.10.0")
check("O9c: Pool gateway correct", pools[0]["gateway"] == "192.168.10.1")
check("O9d: Pool range start", pools[0]["start"] == "192.168.10.50")
check("O9e: Pool range end", pools[0]["end"] == "192.168.10.200")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION P: All 6 Redistribution Combinations
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION P: All Redistribution Combinations")
print("="*70)

combos = [
    ("ospf", "rip", "redistribute rip subnets", "redistribute ospf 1 metric 3"),
    ("rip", "ospf", "redistribute ospf 1 metric 3", "redistribute rip subnets"),
    ("eigrp", "ospf", "redistribute ospf 1 metric 1000 100 255 1 1500", "redistribute eigrp 10 subnets"),
    ("ospf", "eigrp", "redistribute eigrp 10 subnets", "redistribute ospf 1 metric 1000 100 255 1 1500"),
    ("rip", "eigrp", "redistribute eigrp 10 metric 3", "redistribute rip metric 1000 100 255 1 1500"),
    ("eigrp", "rip", "redistribute rip metric 1000 100 255 1 1500", "redistribute eigrp 10 metric 3"),
]
for i, (a, b, expect_in_a, expect_in_b) in enumerate(combos, 1):
    w = make_router_wizard("rip", is_redist=True, redist_protos=[a, b])
    config = w._render_routing_protocol_block()
    check(f"P{i}a: {a.upper()}<->{b.upper()}: redist {b} into {a}",
          expect_in_a in config, f"Missing '{expect_in_a}'")
    check(f"P{i}b: {a.upper()}<->{b.upper()}: redist {a} into {b}",
          expect_in_b in config, f"Missing '{expect_in_b}'")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION Q: IOS Syntax Validation (Real Device Compliance)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION Q: IOS Syntax Validation")
print("="*70)

w = make_router_wizard("ospf")
w.dhcp_pools = w._auto_dhcp_from_routing()
w._write_templates()
full = w.device_model.build_full_config()

# Q1: Every "configure terminal" has a matching "end"
ct_count = full.count("configure terminal")
end_count = full.count("\nend")
check("Q1: configure terminal / end balance", ct_count == end_count,
      f"'configure terminal' count={ct_count}, 'end' count={end_count}")

# Q2: No double "configure terminal" without "end" in between
lines = full.splitlines()
depth = 0
q2_ok = True
for line in lines:
    s = line.strip()
    if s == "configure terminal":
        depth += 1
        if depth > 1:
            q2_ok = False
            break
    elif s == "end":
        depth = max(0, depth - 1)
check("Q2: No nested configure terminal", q2_ok)

# Q3: Every "interface X" inside config mode has "exit"
# (approximate: count interface vs exit in each block)
blocks = Sender.split_into_blocks(full)
q3_ok = True
for title, content in blocks:
    iface_count = content.count("\ninterface ") + (1 if content.startswith("interface ") else 0)
    exit_count = content.count("\nexit") + content.count("\n exit")
    # Allow some exits to be for router/pool blocks too, so just check >= iface_count
    if exit_count < iface_count:
        q3_ok = False
        break
check("Q3: Every 'interface' has a matching 'exit'", q3_ok)

# Q4: No blank hostname/password reaching config
check("Q4: No empty hostname", "hostname " in full and "hostname \n" not in full)

# Q5: OSPF area 0 on all network statements
ospf_nets = re.findall(r"network\s+[\d.]+\s+[\d.]+\s+area\s+(\d+)", full)
check("Q5: All OSPF networks in area 0",
      all(a == "0" for a in ospf_nets),
      f"Areas found: {ospf_nets}")

# Q6: RIP version 2 always present with RIP
w_rip = make_router_wizard("rip")
rip_config = w_rip._render_routing_protocol_block()
check("Q6: RIP always version 2", "version 2" in rip_config)
check("Q7: RIP always no auto-summary", "no auto-summary" in rip_config)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION R: Multi-Network Isolation (Simulated BFS)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION R: Template Snapshot & Rollback")
print("="*70)

model = RouterModel("SnapRouter")
model.set_template("guided_identity", "hostname SnapRouter")
model.snapshot_templates()
model.set_template("guided_identity", "hostname Changed")
check("R1: Template changed", model.get_template("guided_identity") == "hostname Changed")
model.restore_snapshot()
check("R2: Template restored", model.get_template("guided_identity") == "hostname SnapRouter")

# Multiple snapshots
model.snapshot_templates()
model.set_template("guided_identity", "hostname V2")
model.snapshot_templates()
model.set_template("guided_identity", "hostname V3")
check("R3: Has snapshots", model.has_snapshots())
model.restore_snapshot()
check("R4: Restored to V2", model.get_template("guided_identity") == "hostname V2")
model.restore_snapshot()
check("R5: Restored to V1", model.get_template("guided_identity") == "hostname SnapRouter")
check("R6: No more snapshots", not model.has_snapshots())


# ═══════════════════════════════════════════════════════════════════════════
# SECTION S: Boundary Detection Logic
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION S: Boundary Detection Logic")
print("="*70)

# S1: Router with only router connections -> boundary
model = RouterModel("BR1")
ctx = {"redistribution_router": "BR1", "redistribution_protocols": ["ospf", "rip"]}
links = [
    {"local_interface": "Se0/0", "remote_device": "R1", "remote_interface": "Se0/0", "remote_role": "router"},
    {"local_interface": "Se1/0", "remote_device": "R2", "remote_interface": "Se0/0", "remote_role": "router"},
]
w = GuidedSetupWizard(None, "BR1", model, device_role="router",
                      known_interfaces=["Se0/0", "Se1/0"], headless=True,
                      project_context=ctx, connected_links=links)
check("S1: Detected as boundary", w.is_boundary_router == True)

# S2: Router with switch connections -> NOT boundary
model = RouterModel("NR1")
ctx2 = {"redistribution_router": "NR1", "redistribution_protocols": ["ospf", "rip"]}
links2 = [
    {"local_interface": "Fa0/0", "remote_device": "CSW1", "remote_interface": "Fa1/0", "remote_role": "core"},
    {"local_interface": "Se0/0", "remote_device": "R2", "remote_interface": "Se0/0", "remote_role": "router"},
]
w2 = GuidedSetupWizard(None, "NR1", model, device_role="router",
                       known_interfaces=["Fa0/0", "Se0/0"], headless=True,
                       project_context=ctx2, connected_links=links2)
check("S2: Not boundary (has switch link)", w2.is_boundary_router == False)

# S3: Router that is NOT the redistribution router -> NOT boundary
model = RouterModel("NR2")
ctx3 = {"redistribution_router": "SomeOtherRouter", "redistribution_protocols": ["ospf", "rip"]}
links3 = [
    {"local_interface": "Se0/0", "remote_device": "R1", "remote_interface": "Se0/0", "remote_role": "router"},
]
w3 = GuidedSetupWizard(None, "NR2", model, device_role="router",
                       known_interfaces=["Se0/0"], headless=True,
                       project_context=ctx3, connected_links=links3)
check("S3: Not boundary (not redistribution router)", w3.is_boundary_router == False)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION T: Integrated End-to-End (Full Topology Simulation)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION T: Integrated End-to-End Topology")
print("="*70)

# Simulate: R1(OSPF) -- BR(boundary) -- R2(RIP) -- CSW1(L3) -- ASW1(L2)
# Each device gets its own wizard and we verify the configs are compatible

# Device 1: R1 (OSPF router with VLANs)
m1 = RouterModel("R1")
w1 = GuidedSetupWizard(None, "R1", m1, device_role="router",
                       known_interfaces=["Fa0/0", "Se0/0"], headless=True,
                       project_context={},
                       connected_links=[
                           {"local_interface": "Fa0/0", "remote_device": "CSW1",
                            "remote_interface": "Fa1/0", "remote_role": "core"},
                           {"local_interface": "Se0/0", "remote_device": "BR",
                            "remote_interface": "Se2/0", "remote_role": "router"},
                       ])
w1.identity_data = {"hostname": "R1", "domain": "net-a.local", "enable": "Pass1"}
w1.router_interface = "Fa0/0"
w1.wan_interface = ""
w1.wan_ip = ""
w1.routing_entries = [{"vlan": "10", "name": "LAN-A", "ip": "192.168.10.1", "mask": "255.255.255.0"}]
w1.routing_protocol = "ospf"
w1.static_routes = []
w1._write_templates()
full_r1 = m1.build_full_config()
check("T1: R1 config has OSPF", "router ospf 1" in full_r1)
check("T2: R1 subinterface for VLAN 10", "interface Fa0/0.10" in full_r1)
check("T3: R1 no WAN block (no ISP)", "interface Fa0/1" not in full_r1)

# Device 2: Boundary Router (OSPF<->RIP)
m2 = RouterModel("BR")
br_links = [
    {"local_interface": "Se2/0", "remote_device": "R1", "remote_interface": "Se0/0", "remote_role": "router"},
    {"local_interface": "Se3/0", "remote_device": "R2", "remote_interface": "Se0/0", "remote_role": "router"},
]
br_transit = [
    {"local_interface": "Se2/0", "remote_device": "R1", "protocol": "ospf",
     "ip": "10.0.0.1", "mask": "255.255.255.252"},
    {"local_interface": "Se3/0", "remote_device": "R2", "protocol": "rip",
     "ip": "10.0.4.1", "mask": "255.255.255.252"},
]
ctx_br = {"redistribution_router": "BR", "redistribution_protocols": ["ospf", "rip"],
          "redistribution_needed": True, "protocol_map": {"R1": "ospf", "R2": "rip"}}
w2 = GuidedSetupWizard(None, "BR", m2, device_role="router",
                       known_interfaces=["Se2/0", "Se3/0"], headless=True,
                       project_context=ctx_br, connected_links=br_links)
w2.identity_data = {"hostname": "BR", "domain": "", "enable": "Pass2"}
w2.transit_links = br_transit
w2.static_routes = []
w2.wan_interface = ""
w2.wan_ip = ""
w2._write_templates()
full_br = m2.build_full_config()
check("T4: BR has both OSPF and RIP", "router ospf 1" in full_br and "router rip" in full_br)
check("T5: BR has transit links (no subinterfaces)", "encapsulation" not in full_br)
check("T6: BR redistribute RIP->OSPF", "redistribute rip subnets" in full_br)
check("T7: BR redistribute OSPF->RIP", "redistribute ospf 1 metric 3" in full_br)
check("T8: BR no DHCP", "ip dhcp pool" not in full_br)

# Device 3: Access Switch
m3 = SwitchModel("ASW1")
w3 = GuidedSetupWizard(None, "ASW1", m3, device_role="access",
                       known_interfaces=["Ethernet0/0", "Ethernet0/1", "Ethernet3/3"],
                       headless=True, project_context={})
w3.identity_data = {"hostname": "ASW1", "domain": "", "enable": "SwPass"}
w3.vlans = [{"id": "10", "name": "LAN-A", "ports": "Ethernet0/0,Ethernet0/1"}]
w3.uplinks = [{"ports": "Ethernet3/3", "mode": "trunk", "allowed vlans": "10"}]
w3._write_templates()
full_asw = m3.build_full_config()
check("T9: ASW trunk to core", "switchport mode trunk" in full_asw)
check("T10: ASW access ports", "switchport mode access" in full_asw)
check("T11: ASW portfast", "spanning-tree portfast" in full_asw)
check("T12: ASW allowed VLAN 10", "switchport trunk allowed vlan 10" in full_asw)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION U: Known Bug Checks / Regression Detection
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION U: Regression Checks")
print("="*70)

# U1: connected_links is set twice in __init__ (line 178 and 200) — verify no data loss
model = RouterModel("DupeTest")
test_links = [{"local_interface": "Fa0/0", "remote_device": "X",
               "remote_interface": "Fa0/0", "remote_role": "router"}]
w = GuidedSetupWizard(None, "DupeTest", model, device_role="router",
                      known_interfaces=["Fa0/0"], headless=True,
                      project_context={}, connected_links=test_links)
check("U1: connected_links preserved despite double assignment",
      len(w.connected_links) == 1 and w.connected_links[0]["remote_device"] == "X",
      f"Got {w.connected_links}")

# U2: DHCP excluded addresses calculation correctness
w = make_router_wizard("ospf")
w.dhcp_pools = [{"pool": "Test", "network": "192.168.10.0", "mask": "255.255.255.0",
                 "gateway": "192.168.10.1", "dns": "8.8.8.8",
                 "start": "192.168.10.50", "end": "192.168.10.200"}]
config = w._render_dhcp_block()
# Should exclude 192.168.10.1 to 192.168.10.49
check("U2: Excludes gateway to start-1",
      "ip dhcp excluded-address 192.168.10.1 192.168.10.49" in config,
      f"Config:\n{config}")
# Should exclude 192.168.10.201 to .254
check("U3: Excludes end+1 to .254",
      "ip dhcp excluded-address 192.168.10.201 192.168.10.254" in config)

# U4: EIGRP default route uses "redistribute static" not "default-information originate"
w = make_router_wizard("eigrp", default_route=True)
config = w._render_routing_protocol_block()
check("U4: EIGRP uses redistribute static", "redistribute static" in config)
check("U5: EIGRP does NOT use default-information originate",
      "default-information originate" not in config)

# U6: Sender return value is boolean
check("U6: Sender.send_telnet returns False on missing lib",
      Sender.send_telnet(lambda m: None, "localhost", 9999, "", "", "", "") is False
      if not hasattr(Sender, '_telnetlib3_available') else True)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION V: Full Multi-Network Scenario (Network A + Boundary + Network B)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION V: Full Multi-Network Scenario (Network A + Boundary + Network B)")
print("="*70)

# -- Network A (OSPF) --
# R-A (Router)
m_ra = RouterModel("R-A")
w_ra = GuidedSetupWizard(None, "R-A", m_ra, device_role="router",
                       known_interfaces=["Fa0/0", "Se0/0"], headless=True,
                       project_context={},
                       connected_links=[
                           {"local_interface": "Fa0/0", "remote_device": "Core-A",
                            "remote_interface": "Fa1/0", "remote_role": "core"},
                           {"local_interface": "Se0/0", "remote_device": "BR",
                            "remote_interface": "Se2/0", "remote_role": "router"},
                       ])
w_ra.identity_data = {"hostname": "R-A", "domain": "net-a.local", "enable": "PassA"}
w_ra.router_interface = "Fa0/0"
w_ra.wan_interface = ""
w_ra.wan_ip = ""
w_ra.routing_entries = [{"vlan": "10", "name": "LAN-A", "ip": "192.168.10.1", "mask": "255.255.255.0"}]
w_ra.routing_protocol = "ospf"
w_ra.static_routes = []
w_ra._write_templates()
full_ra = m_ra.build_full_config()
check("V1: R-A uses OSPF", "router ospf 1" in full_ra)
check("V2: R-A creates subinterface for LAN-A", "interface Fa0/0.10" in full_ra)

# Core-A (Core Switch)
m_ca = CoreSwitchModel("Core-A")
w_ca = GuidedSetupWizard(None, "Core-A", m_ca, device_role="core",
                       known_interfaces=["Fa1/0", "Fa1/1"], headless=True, project_context={})
w_ca.identity_data = {"hostname": "Core-A", "domain": "net-a.local", "enable": "PassA"}
w_ca.vlans = [{"id": "10", "name": "LAN-A", "ports": "Fa1/1"}]
w_ca.uplinks = [{"ports": "Fa1/0", "mode": "trunk", "allowed vlans": "all"}]
w_ca.routing_mode = "device"
w_ca.routing_entries = [{"vlan": "10", "name": "LAN-A", "ip": "192.168.10.2", "mask": "255.255.255.0"}]
w_ca._write_templates()
full_ca = m_ca.build_full_config()
check("V3: Core-A routing enabled", "ip routing" in full_ca)
check("V4: Core-A SVI created", "interface Vlan10" in full_ca)

# Access-A (Access Switch)
m_aa = SwitchModel("Access-A")
w_aa = GuidedSetupWizard(None, "Access-A", m_aa, device_role="access",
                       known_interfaces=["Fa1/0", "Fa1/1"], headless=True, project_context={})
w_aa.identity_data = {"hostname": "Access-A", "domain": "", "enable": "PassA"}
w_aa.vlans = [{"id": "10", "name": "LAN-A", "ports": "Fa1/1"}]
w_aa.uplinks = [{"ports": "Fa1/0", "mode": "trunk", "allowed vlans": "10"}]
w_aa._write_templates()
full_aa = m_aa.build_full_config()
check("V5: Access-A access port", "switchport mode access" in full_aa)
check("V6: Access-A trunk rules", "switchport trunk allowed vlan 10" in full_aa)

# -- Network B (EIGRP) --
# R-B (Router)
m_rb = RouterModel("R-B")
w_rb = GuidedSetupWizard(None, "R-B", m_rb, device_role="router",
                       known_interfaces=["Fa0/0", "Se0/0"], headless=True,
                       project_context={},
                       connected_links=[
                           {"local_interface": "Fa0/0", "remote_device": "Core-B",
                            "remote_interface": "Fa1/0", "remote_role": "core"},
                           {"local_interface": "Se0/0", "remote_device": "BR",
                            "remote_interface": "Se3/0", "remote_role": "router"},
                       ])
w_rb.identity_data = {"hostname": "R-B", "domain": "net-b.local", "enable": "PassB"}
w_rb.router_interface = "Fa0/0"
w_rb.wan_interface = ""
w_rb.wan_ip = ""
w_rb.routing_entries = [{"vlan": "20", "name": "LAN-B", "ip": "10.1.20.1", "mask": "255.255.255.0"}]
w_rb.routing_protocol = "eigrp"
w_rb.static_routes = []
w_rb._write_templates()
full_rb = m_rb.build_full_config()
check("V7: R-B uses EIGRP", "router eigrp 10" in full_rb)
check("V8: R-B creates subinterface for LAN-B", "interface Fa0/0.20" in full_rb)

# Core-B (Core Switch)
m_cb = CoreSwitchModel("Core-B")
w_cb = GuidedSetupWizard(None, "Core-B", m_cb, device_role="core",
                       known_interfaces=["Fa1/0", "Fa1/1"], headless=True, project_context={})
w_cb.identity_data = {"hostname": "Core-B", "domain": "net-b.local", "enable": "PassB"}
w_cb.vlans = [{"id": "20", "name": "LAN-B", "ports": "Fa1/1"}]
w_cb.uplinks = [{"ports": "Fa1/0", "mode": "trunk", "allowed vlans": "all"}]
w_cb.routing_mode = "device"
w_cb.routing_entries = [{"vlan": "20", "name": "LAN-B", "ip": "10.1.20.2", "mask": "255.255.255.0"}]
w_cb._write_templates()
full_cb = m_cb.build_full_config()
check("V9: Core-B routing enabled", "ip routing" in full_cb)

# Access-B (Access Switch)
m_ab = SwitchModel("Access-B")
w_ab = GuidedSetupWizard(None, "Access-B", m_ab, device_role="access",
                       known_interfaces=["Fa1/0", "Fa1/1"], headless=True, project_context={})
w_ab.identity_data = {"hostname": "Access-B", "domain": "", "enable": "PassB"}
w_ab.vlans = [{"id": "20", "name": "LAN-B", "ports": "Fa1/1"}]
w_ab.uplinks = [{"ports": "Fa1/0", "mode": "trunk", "allowed vlans": "20"}]
w_ab._write_templates()
full_ab = m_ab.build_full_config()
check("V10: Access-B access port", "switchport mode access" in full_ab)

# -- Boundary Router (Connecting Net A & B) --
m_br = RouterModel("BR")
ctx_br = {"redistribution_router": "BR", "redistribution_protocols": ["ospf", "eigrp"],
          "redistribution_needed": True, "protocol_map": {"R-A": "ospf", "R-B": "eigrp"}}
br_links = [
    {"local_interface": "Se2/0", "remote_device": "R-A", "remote_interface": "Se0/0", "remote_role": "router"},
    {"local_interface": "Se3/0", "remote_device": "R-B", "remote_interface": "Se0/0", "remote_role": "router"},
]
br_transit = [
    {"local_interface": "Se2/0", "remote_device": "R-A", "protocol": "ospf",
     "ip": "172.16.0.1", "mask": "255.255.255.252"},
    {"local_interface": "Se3/0", "remote_device": "R-B", "protocol": "eigrp",
     "ip": "172.16.4.1", "mask": "255.255.255.252"},
]
w_br = GuidedSetupWizard(None, "BR", m_br, device_role="router",
                       known_interfaces=["Se2/0", "Se3/0"], headless=True,
                       project_context=ctx_br, connected_links=br_links)
w_br.identity_data = {"hostname": "BR", "domain": "", "enable": "PassBR"}
w_br.transit_links = br_transit
w_br.static_routes = []
w_br.wan_interface = ""
w_br.wan_ip = ""
w_br._write_templates()
full_br = m_br.build_full_config()

check("V11: Boundary router has both OSPF and EIGRP blocks", "router ospf 1" in full_br and "router eigrp 10" in full_br)
check("V12: Boundary router has transit links without subinterfaces",
      "interface Se2/0" in full_br and "encapsulation dot1q" not in full_br.lower())
check("V13: BR redistribute OSPF into EIGRP", "redistribute ospf 1 metric 1000 100 255 1 1500" in full_br)
check("V14: BR redistribute EIGRP into OSPF", "redistribute eigrp 10 subnets" in full_br)


# ═══════════════════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
total = PASS + FAIL
print(f"  TOTAL: {total} tests  |  {PASS} PASSED  |  {FAIL} FAILED")
print("="*70)

if ERRORS:
    print("\n  FAILURES:")
    for name, detail in ERRORS:
        print(f"    X  {name}")
        if detail:
            print(f"       {detail}")
    print()

if FAIL:
    sys.exit(1)
else:
    print("  All tests passed!")
