import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.network.sender import Sender

class TestSender(unittest.TestCase):
    def test_split_into_blocks_single_block(self):
        config = """
! BLOCK 1: Identity & Security
hostname R1
enable secret test
"""
        blocks = Sender.split_into_blocks(config)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][0], "Identity & Security")
        self.assertEqual(blocks[0][1], "hostname R1\nenable secret test")

    def test_split_into_blocks_multiple(self):
        config = """
! BLOCK 1: Identity
hostname R1
! BLOCK 2: Routing
router ospf 1
 network 0.0.0.0 255.255.255.255 area 0
"""
        blocks = Sender.split_into_blocks(config)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0][0], "Identity")
        self.assertEqual(blocks[0][1], "hostname R1")
        self.assertEqual(blocks[1][0], "Routing")
        self.assertEqual(blocks[1][1], "router ospf 1\n network 0.0.0.0 255.255.255.255 area 0")

    def test_split_into_blocks_no_headers(self):
        config = """
hostname R1
interface Vlan10
 ip address 10.0.0.1 255.255.255.0
"""
        blocks = Sender.split_into_blocks(config)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][0], "Configuration")
        self.assertEqual(blocks[0][1], "hostname R1\ninterface Vlan10\n ip address 10.0.0.1 255.255.255.0")

    def test_split_into_blocks_skips_comments(self):
        config = """
! PASTE EACH BLOCK
! Wait for device prompt
! BLOCK 1: Main
hostname R1
! Just a regular comment
ip routing
"""
        blocks = Sender.split_into_blocks(config)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][0], "Main")
        # Regular comments shouldn't be added to block according to logic
        # wait, the logic says:
        # if current_title is not None and stripped and not stripped.startswith("!"):
        # current_block.append(line)
        self.assertEqual(blocks[0][1], "hostname R1\nip routing")

if __name__ == '__main__':
    unittest.main()
