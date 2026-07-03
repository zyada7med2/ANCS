import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.network.puller import ConfigPuller

class TestConfigPuller(unittest.TestCase):
    def test_is_blank_config_short(self):
        is_blank, reason = ConfigPuller.is_blank_config("Too short")
        self.assertTrue(is_blank)
        self.assertIn("Too short/empty", reason)

    def test_is_blank_config_ip_assigned(self):
        config = "!\n" * 50 + "interface GigabitEthernet0/0\n ip address 192.168.1.1 255.255.255.0\n" + "!\n" * 50
        is_blank, reason = ConfigPuller.is_blank_config(config)
        self.assertFalse(is_blank)
        self.assertIn("Detected IP assigning line", reason)

    def test_is_blank_config_routing(self):
        config = "!\n" * 50 + "router ospf 1\n network 0.0.0.0 255.255.255.255 area 0\n" + "!\n" * 50
        is_blank, reason = ConfigPuller.is_blank_config(config)
        self.assertFalse(is_blank)
        self.assertIn("Detected routing protocol", reason)

    def test_is_blank_config_custom_hostname(self):
        config = "!\n" * 50 + "hostname MyCustomRouter\n" + "!\n" * 50
        is_blank, reason = ConfigPuller.is_blank_config(config)
        self.assertFalse(is_blank)
        self.assertIn("Detected custom hostname", reason)

    def test_is_blank_config_default_hostname(self):
        config = "!\n" * 50 + "hostname Router\n" + "!\n" * 50
        is_blank, reason = ConfigPuller.is_blank_config(config)
        self.assertTrue(is_blank)
        self.assertIn("No configuration hallmarks found", reason)

    def test_is_blank_config_manual_vlan(self):
        config = "!\n" * 50 + "vlan 10\n name Staff\n" + "!\n" * 50
        is_blank, reason = ConfigPuller.is_blank_config(config)
        self.assertFalse(is_blank)
        self.assertIn("Detected manual vlan", reason)

    def test_is_blank_config_manual_svi(self):
        config = "!\n" * 50 + "interface Vlan10\n no shut\n" + "!\n" * 50
        is_blank, reason = ConfigPuller.is_blank_config(config)
        self.assertFalse(is_blank)
        self.assertIn("Detected Manual SVI", reason)

    def test_extract_hostname(self):
        config = "!\nhostname R1\n!\n"
        self.assertEqual(ConfigPuller.extract_hostname(config), "R1")
        self.assertEqual(ConfigPuller.extract_hostname("no hostname here"), "")

if __name__ == '__main__':
    unittest.main()
