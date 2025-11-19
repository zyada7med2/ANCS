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

