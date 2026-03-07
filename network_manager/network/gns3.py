"""
GNS3 API connector for project and node management
"""
from ..config import GNS3_DEFAULT_URL

# Optional import
try:
    import requests
except Exception:
    requests = None


class GNS3Connector:
    def __init__(self, server_url: str = GNS3_DEFAULT_URL):
        self.server_url = server_url.rstrip("/")

    def get_projects(self):
        if requests is None:
            raise RuntimeError("requests not installed")
        r = requests.get(f"{self.server_url}/v2/projects", timeout=5)
        r.raise_for_status()
        return r.json()

    def get_nodes(self, project_id):
        if requests is None:
            raise RuntimeError("requests not installed")
        r = requests.get(f"{self.server_url}/v2/projects/{project_id}/nodes", timeout=5)
        r.raise_for_status()
        return r.json()

    def get_node_ports(self, project_id: str, node_id: str):
        """
        Return the list of port dicts for a node from the GNS3 API.
        Each dict contains at minimum: 'name', 'adapter_number', 'port_number'.
        Example names: 'Ethernet0/0', 'FastEthernet1/0', 'GigabitEthernet0/0'.
        """
        if requests is None:
            raise RuntimeError("requests not installed")
        r = requests.get(
            f"{self.server_url}/v2/projects/{project_id}/nodes/{node_id}/ports",
            timeout=5,
        )
        r.raise_for_status()
        return r.json()

    def get_links(self, project_id: str):
        """
        Return the list of link dicts for a project from the GNS3 API.
        Each dict has a 'nodes' list with two endpoint dicts, each containing:
          'node_id', 'adapter_number', 'port_number', 'label' (optional).
        """
        if requests is None:
            raise RuntimeError("requests not installed")
        r = requests.get(
            f"{self.server_url}/v2/projects/{project_id}/links",
            timeout=5,
        )
        r.raise_for_status()
        return r.json()

