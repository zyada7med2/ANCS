import sys
import os

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network_manager.network.gns3 import GNS3Connector

def main():
    print("Connecting to GNS3 server at http://localhost:3080...")
    connector = GNS3Connector("http://localhost:3080")
    try:
        projects = connector.get_projects()
        print(f"Connected successfully! Found {len(projects)} projects:")
        for p in projects:
            print(f"- Project Name: {p.get('name')}, ID: {p.get('project_id')}, Status: {p.get('status')}")
            
            # Fetch nodes
            nodes = connector.get_nodes(p.get('project_id'))
            print(f"  Nodes ({len(nodes)}):")
            for n in nodes:
                print(f"    * {n.get('name')} (ID: {n.get('node_id')}, Type: {n.get('node_type')}, Status: {n.get('status')})")
    except Exception as e:
        print(f"Could not connect or fetch projects: {e}")

if __name__ == '__main__':
    main()
