import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.models.devices import DeviceModel, RouterModel, SwitchModel, CoreSwitchModel

class TestDevices(unittest.TestCase):
    def test_device_model_init(self):
        device = DeviceModel("test-device")
        self.assertEqual(device.name, "test-device")
        self.assertEqual(device.templates, {})
        self.assertEqual(device.snapshots, [])
        self.assertEqual(device.state, {})

    def test_template_management(self):
        device = DeviceModel("test")
        device.set_template("base", "hostname router1")
        device.set_template("routing", "router ospf 1")
        
        self.assertEqual(len(device.get_template_names()), 2)
        self.assertIn("base", device.get_template_names())
        self.assertIn("routing", device.get_template_names())
        
        self.assertEqual(device.get_template("base"), "hostname router1")
        self.assertEqual(device.get_template("non_existent"), "")

    def test_build_full_config(self):
        device = DeviceModel("test")
        device.set_template("base", "hostname R1")
        device.set_template("vlan_10", "vlan 10\n name Staff")
        
        full_config = device.build_full_config()
        self.assertIn("! BLOCK 1: Base", full_config)
        self.assertIn("hostname R1", full_config)
        self.assertIn("! BLOCK 2: Vlan 10", full_config)
        self.assertIn("vlan 10\n name Staff", full_config)

    def test_snapshot_restore(self):
        device = DeviceModel("test")
        
        # Initial empty snapshot should not crash but maybe not do anything
        self.assertFalse(device.has_snapshots())
        device.snapshot_templates() # shouldn't do anything because templates are empty
        self.assertFalse(device.has_snapshots())
        
        # Add a template and snapshot
        device.set_template("base", "hostname version1")
        device.snapshot_templates()
        self.assertTrue(device.has_snapshots())
        
        # Modify the template
        device.set_template("base", "hostname version2")
        self.assertEqual(device.get_template("base"), "hostname version2")
        
        # Restore
        success = device.restore_snapshot()
        self.assertTrue(success)
        self.assertEqual(device.get_template("base"), "hostname version1")
        self.assertFalse(device.has_snapshots())

    def test_snapshot_max_limit(self):
        device = DeviceModel("test")
        for i in range(1, 10):
            device.set_template("base", f"version{i}")
            device.snapshot_templates()
            
        # Should keep at most 5 snapshots
        self.assertEqual(len(device.snapshots), 5)
        # The oldest one in the list (index 0) should be version5 (since 5,6,7,8,9 are saved)
        # Wait, if it saves current template, and pops 0:
        # i=1: v1 saved. 
        # i=2: v2 saved.
        # ... i=5: v5 saved.
        # i=6: v6 saved, v1 popped. [v2, v3, v4, v5, v6]
        # ... i=9: v9 saved, v4 popped. [v5, v6, v7, v8, v9]
        self.assertEqual(device.snapshots[0]["base"], "version5")
        self.assertEqual(device.snapshots[-1]["base"], "version9")

    def test_subclasses(self):
        router = RouterModel("r1")
        self.assertEqual(router.name, "r1")
        
        switch = SwitchModel("s1")
        self.assertEqual(switch.name, "s1")
        
        core = CoreSwitchModel("c1")
        self.assertEqual(core.name, "c1")

if __name__ == '__main__':
    unittest.main()
