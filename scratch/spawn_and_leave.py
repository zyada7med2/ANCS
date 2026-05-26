import sys
import os
from unittest.mock import patch

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.ai_agent import ctx, add_gns3_node, connect_gns3_nodes

def main():
    ctx.gns3_url = "http://localhost:3080"
    ctx.gns3_project_id = "f0d67775-e2b7-4938-acc1-e30525ed9527"
    ctx._gns3_connector_instance = None
    ctx.refresh_ui_fn = lambda: print("--> UI refresh signaled!")

    node_name = "TEST_R4"
    print(f"Spawning router '{node_name}' and leaving it in GNS3...")

    with patch('network_manager.config.db_lock'), \
         patch('network_manager.config.conn'):
         
        # Add node
        add_res = add_gns3_node(name=node_name, device_role="router", x=300, y=300)
        print("Add Result:", add_res)
        
        # Connect to R2
        conn_res = connect_gns3_nodes(node_a=node_name, port_a="FastEthernet0/0", node_b="R2", port_b="GigabitEthernet1/0")
        print("Connection Result:", conn_res)

if __name__ == '__main__':
    main()
