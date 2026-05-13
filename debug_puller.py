"""
Debug script to trace specifically why Core Switches are marked blank.
"""
import sys
import asyncio
import re
import os

from network_manager.gui.app import App
from network_manager.network.puller import ConfigPuller

def main():
    print("Initializing dummy App to load GNS3 topology...")
    from PySide6.QtWidgets import QApplication
    sys_app = QApplication.instance()
    if sys_app is None:
        sys_app = QApplication(sys.argv)
    
    app = App()
    
    nodes = [d for d in app.devices if d[2].get('console_host')]
    if not nodes:
        print("No GNS3 nodes found!")
        return

    print(f"Found {len(nodes)} nodes. Filtering for Core Switches...")
    
    # "Core Switch" typings can vary in how they are named internally
    switches = [n for n in nodes if "switch" in n[1].device_type.lower() or "sw" in n[0].lower()]
    
    if not switches:
        print("No devices matching 'switch' found, running against all nodes...")
        switches = nodes

    print("="*60)
    for n in switches:
        name, model, meta = n
        host = meta.get('console_host', 'localhost')
        port = int(meta.get('console_port', 23))
        
        print(f"\n[+] Testing node: {name} (Host: {host}:{port})")
        
        # We will use the async puller directly to capture output
        try:
            print("    -> Pulling config...")
            raw_result = asyncio.run(ConfigPuller._pull_single_async(host, port, "", "", ""))
            
            print(f"    -> Pulled {len(raw_result)} characters.")
            
            # Run the regex checks manually to see exactly which fail
            blank = True
            if not raw_result or len(raw_result.strip()) < 50:
                print("    -> REASON IS BLANK: Length < 50 characters")
            else:
                ip_assigned = bool(re.search(r"^\s*ip address \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", raw_result, re.IGNORECASE | re.MULTILINE))
                routing = bool(re.search(r"^\s*router (ospf|eigrp|rip|bgp)", raw_result, re.IGNORECASE | re.MULTILINE))
                
                is_custom_hostname = False
                h = "NONE"
                hm = re.search(r"^\s*hostname\s+(\S+)", raw_result, re.IGNORECASE | re.MULTILINE)
                if hm:
                    h = hm.group(1).lower()
                    if not re.match(r"^(router|switch|r\d+|sw\d+|pc\d+|iou\d+|vios\d+)$", h):
                        is_custom_hostname = True

                vlan_l3 = bool(re.search(r"^\s*interface Vlan(?!1\b)\d+", raw_result, re.IGNORECASE | re.MULTILINE))
                vlan_l2 = bool(re.search(r"^\s*vlan (?!1\b)\d+", raw_result, re.IGNORECASE | re.MULTILINE))
                switchport = bool(re.search(r"^\s*switchport mode (trunk|access)", raw_result, re.IGNORECASE | re.MULTILINE))
                etherchannel = bool(re.search(r"^\s*channel-group \d+", raw_result, re.IGNORECASE | re.MULTILINE))

                print(f"    -> Matches: IP={ip_assigned}, Routing={routing}, Hostname={is_custom_hostname} ({h}), VLAN_L3={vlan_l3}, VLAN_L2={vlan_l2}, Switchport={switchport}, Etherchannel={etherchannel}")
                
                if ip_assigned or routing or is_custom_hostname or vlan_l3 or vlan_l2 or switchport or etherchannel:
                    blank = False
            
            print(f"    -> FINAL VERDICT: {'[BLANK]' if blank else '[CONFIGURED]'}")
            
            # Dump the first 15 lines of raw config just so we can see what it actually looks like
            print("    -> FIRST 15 LINES OF CONFIG:")
            lines = raw_result.splitlines()
            for line in lines[:15]:
                print(f"       {line}")
                
        except Exception as e:
            print(f"    -> Exception occurred: {e}")

if __name__ == "__main__":
    main()
