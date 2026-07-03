import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests
except ImportError:
    # Create dummy classes for requests and its exceptions
    class DummyRequestsExceptions:
        class ConnectionError(Exception): pass
        class Timeout(Exception): pass
        class HTTPError(Exception): pass

    class DummyRequests:
        exceptions = DummyRequestsExceptions()
        get = MagicMock()
        
    requests = DummyRequests()
    sys.modules['requests'] = requests
    
from network_manager.network.gns3 import GNS3Connector

class TestGNS3Connector(unittest.TestCase):
    def setUp(self):
        self.connector = GNS3Connector("http://test-server:3080")
        # Ensure requests is available in the connector
        import network_manager.network.gns3 as gns3_mod
        gns3_mod.requests = requests

    @patch('network_manager.network.gns3.requests.get')
    def test_get_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_get.return_value = mock_response

        result = self.connector._get("/test")
        mock_get.assert_called_once_with("http://test-server:3080/test", timeout=5)
        self.assertEqual(result, {"status": "ok"})

    @patch('network_manager.network.gns3.requests.get')
    def test_get_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError()
        with self.assertRaises(RuntimeError) as context:
            self.connector._get("/test")
        self.assertIn("Cannot reach GNS3 server", str(context.exception))

    @patch('network_manager.network.gns3.requests.get')
    def test_get_timeout_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        with self.assertRaises(RuntimeError) as context:
            self.connector._get("/test")
        self.assertIn("did not respond within", str(context.exception))

    @patch('network_manager.network.gns3.requests.get')
    def test_get_http_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.HTTPError("404 Not Found")
        with self.assertRaises(RuntimeError) as context:
            self.connector._get("/test")
        self.assertIn("GNS3 API error", str(context.exception))

    @patch.object(GNS3Connector, '_get')
    def test_get_projects(self, mock_get):
        mock_get.return_value = [{"project_id": "123", "name": "test_proj"}]
        result = self.connector.get_projects()
        mock_get.assert_called_once_with("/v2/projects")
        self.assertEqual(result[0]["name"], "test_proj")

    @patch.object(GNS3Connector, '_get')
    def test_get_nodes(self, mock_get):
        mock_get.return_value = [{"node_id": "456", "name": "R1"}]
        result = self.connector.get_nodes("123")
        mock_get.assert_called_once_with("/v2/projects/123/nodes")
        self.assertEqual(result[0]["name"], "R1")

    @patch.object(GNS3Connector, '_get')
    def test_get_node_ports(self, mock_get):
        mock_get.return_value = {"ports": [{"name": "FastEthernet0/0"}]}
        result = self.connector.get_node_ports("123", "456")
        mock_get.assert_called_once_with("/v2/projects/123/nodes/456")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "FastEthernet0/0")

    @patch.object(GNS3Connector, '_get')
    def test_get_links(self, mock_get):
        mock_get.return_value = [{"link_id": "789"}]
        result = self.connector.get_links("123")
        mock_get.assert_called_once_with("/v2/projects/123/links")
        self.assertEqual(result[0]["link_id"], "789")

if __name__ == '__main__':
    unittest.main()
