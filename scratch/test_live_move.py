import sys
import os

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.ai_agent import ctx, move_gns3_node

def main():
    ctx.gns3_url = "http://localhost:3080"
    ctx.gns3_project_id = "f0d67775-e2b7-4938-acc1-e30525ed9527"
    ctx._gns3_connector_instance = None
    ctx.refresh_ui_fn = lambda: print("--> UI refresh signaled!")

    node_name = "TEST_R4"
    print(f"Moving router '{node_name}' on GNS3 canvas...")

    res = move_gns3_node(node_name, x=-100, y=100)
    print("Move Result:", res)

if __name__ == '__main__':
    main()
