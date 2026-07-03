import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.network.parser import IOSParser

class TestIOSParser(unittest.TestCase):
    def test_parse_config_empty(self):
        data = IOSParser.parse_config("")
        self.assertEqual(data["identity"], {})
        self.assertEqual(data["vlans"], [])
        self.assertEqual(data["dhcp_pools"], [])
        self.assertEqual(data["routing"], {"protocol": "none", "networks": []})
        self.assertEqual(data["wan"], {"interface": "", "ip": "", "mask": ""})
        self.assertEqual(data["static_routes"], [])

    def test_parse_identity(self):
        config_text = "hostname R1\nip domain-name local.domain"
        data = IOSParser.parse_config(config_text)
        self.assertEqual(data["identity"]["hostname"], "R1")
        self.assertEqual(data["identity"]["domain"], "local.domain")

    def test_parse_vlans(self):
        config_text = "vlan 10\n name STAFF\nvlan 20\nvlan 1\n name default"
        data = IOSParser.parse_config(config_text)
        self.assertEqual(len(data["vlans"]), 2)
        self.assertEqual(data["vlans"][0]["id"], "10")
        self.assertEqual(data["vlans"][0]["name"], "STAFF")
        self.assertEqual(data["vlans"][1]["id"], "20")
        self.assertEqual(data["vlans"][1]["name"], "VLAN_20")

    def test_parse_interfaces_and_wan(self):
        config_text = """
interface Vlan10
 ip address 192.168.10.1 255.255.255.0
interface GigabitEthernet0/0
 ip address 10.0.0.1 255.255.255.252
"""
        data = IOSParser.parse_config(config_text)
        
        # Test SVI created VLAN entry
        vlan10 = next((v for v in data["vlans"] if v["id"] == "10"), None)
        self.assertIsNotNone(vlan10)
        self.assertEqual(vlan10["ip"], "192.168.10.1")
        self.assertEqual(vlan10["mask"], "255.255.255.0")
        
        # Test WAN interface detection
        self.assertEqual(data["wan"]["interface"], "GigabitEthernet0/0")
        self.assertEqual(data["wan"]["ip"], "10.0.0.1")
        self.assertEqual(data["wan"]["mask"], "255.255.255.252")

    def test_parse_dhcp_pools(self):
        config_text = """
ip dhcp pool STAFF_POOL
 network 192.168.10.0 255.255.255.0
 default-router 192.168.10.1
!
ip dhcp pool NO_GW_POOL
 network 10.0.0.0 255.0.0.0
"""
        data = IOSParser.parse_config(config_text)
        self.assertEqual(len(data["dhcp_pools"]), 2)
        self.assertEqual(data["dhcp_pools"][0]["name"], "STAFF_POOL")
        self.assertEqual(data["dhcp_pools"][0]["network"], "192.168.10.0")
        self.assertEqual(data["dhcp_pools"][0]["gateway"], "192.168.10.1")
        self.assertEqual(data["dhcp_pools"][1]["name"], "NO_GW_POOL")
        self.assertEqual(data["dhcp_pools"][1]["gateway"], "")

    def test_parse_routing_protocols(self):
        config_text = """
router ospf 1
 network 192.168.10.0 0.0.0.255 area 0
 network 10.0.0.0
"""
        data = IOSParser.parse_config(config_text)
        self.assertIn("ospf", data["routing"]["protocols"])
        self.assertEqual(data["routing"]["protocol"], "ospf")
        self.assertIn("192.168.10.0", data["routing"]["networks"])
        self.assertIn("10.0.0.0", data["routing"]["networks"])

    def test_parse_static_routes(self):
        config_text = "ip route 0.0.0.0 0.0.0.0 10.0.0.2\nip route 192.168.20.0 255.255.255.0 GigabitEthernet0/1"
        data = IOSParser.parse_config(config_text)
        self.assertEqual(len(data["static_routes"]), 2)
        self.assertEqual(data["static_routes"][0]["destination"], "0.0.0.0")
        self.assertEqual(data["static_routes"][0]["mask"], "0.0.0.0")
        self.assertEqual(data["static_routes"][0]["next_hop"], "10.0.0.2")

if __name__ == '__main__':
    unittest.main()
