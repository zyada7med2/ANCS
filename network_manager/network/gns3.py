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

    def _get(self, path: str, timeout: int = 5):
        """Internal GET helper with consistent error handling.

        Raises RuntimeError for any connection/HTTP problem so callers get a
        single, predictable exception type with a human-readable message.
        """
        if requests is None:
            raise RuntimeError("'requests' library is not installed")
        try:
            r = requests.get(f"{self.server_url}{path}", timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot reach GNS3 server at {self.server_url}. "
                "Make sure GNS3 is running."
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"GNS3 server at {self.server_url} did not respond within "
                f"{timeout} seconds."
            )
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(f"GNS3 API error: {exc}")
        except ValueError as exc:
            raise RuntimeError(f"GNS3 returned non-JSON response: {exc}")

    def get_projects(self):
        return self._get("/v2/projects")

    def get_nodes(self, project_id: str):
        return self._get(f"/v2/projects/{project_id}/nodes")

    def get_node_ports(self, project_id: str, node_id: str):
        """
        Return the list of port dicts for a node from the GNS3 API.
        Each dict contains at minimum: 'name', 'adapter_number', 'port_number'.
        Example names: 'Ethernet0/0', 'FastEthernet1/0', 'GigabitEthernet0/0'.
        """
        return self._get(f"/v2/projects/{project_id}/nodes/{node_id}/ports")

    def get_links(self, project_id: str):
        """
        Return the list of link dicts for a project from the GNS3 API.
        Each dict has a 'nodes' list with two endpoint dicts, each containing:
          'node_id', 'adapter_number', 'port_number', 'label' (optional).
        """
        return self._get(f"/v2/projects/{project_id}/links")
