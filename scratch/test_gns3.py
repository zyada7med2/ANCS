import unittest
import sys
import os

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
from network_manager.network.gns3 import GNS3Connector

class TestGNS3Connector(unittest.TestCase):
    @patch('network_manager.network.gns3.requests')
    def test_post_and_delete(self, mock_requests):
        connector = GNS3Connector("http://localhost:3080")
        
        # Test post
        mock_response = MagicMock()
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_requests.post.return_value = mock_response
        
        res = connector._post("/v2/test", {"data": 1})
        self.assertEqual(res, {"status": "ok"})
        mock_requests.post.assert_called_once_with("http://localhost:3080/v2/test", json={"data": 1}, timeout=5)
        
        # Test delete
        mock_response_del = MagicMock()
        mock_response_del.text = ""
        mock_requests.delete.return_value = mock_response_del
        res_del = connector._delete("/v2/test/1")
        self.assertEqual(res_del, {})
        mock_requests.delete.assert_called_once_with("http://localhost:3080/v2/test/1", timeout=5)

    @patch('network_manager.network.gns3.requests')
    def test_topology_editing_methods(self, mock_requests):
        connector = GNS3Connector("http://localhost:3080")
        
        # Mock responses
        mock_resp = MagicMock()
        mock_resp.text = '{"status": "ok"}'
        mock_resp.json.return_value = {"status": "ok"}
        mock_requests.get.return_value = mock_resp
        mock_requests.post.return_value = mock_resp
        mock_requests.delete.return_value = mock_resp
        
        # 1. get_templates
        connector.get_templates()
        mock_requests.get.assert_any_call("http://localhost:3080/v2/templates", timeout=5)
        
        # 2. create_node
        connector.create_node("proj1", "R1", "temp1", 100, 200)
        mock_requests.post.assert_any_call("http://localhost:3080/v2/projects/proj1/templates/temp1", json={"name": "R1", "x": 100, "y": 200}, timeout=5)
        
        # 3. delete_node
        connector.delete_node("proj1", "node1")
        mock_requests.delete.assert_any_call("http://localhost:3080/v2/projects/proj1/nodes/node1", timeout=5)
        
        # 4. create_link
        connector.create_link("proj1", "node_a", 0, 0, "node_b", 0, 1)
        mock_requests.post.assert_any_call(
            "http://localhost:3080/v2/projects/proj1/links",
            json={
                "nodes": [
                    {"node_id": "node_a", "adapter_number": 0, "port_number": 0},
                    {"node_id": "node_b", "adapter_number": 0, "port_number": 1}
                ]
            },
            timeout=5
        )
        
        # 5. start_node
        connector.start_node("proj1", "node1")
        mock_requests.post.assert_any_call("http://localhost:3080/v2/projects/proj1/nodes/node1/start", json={}, timeout=5)
        
        # 6. stop_node
        connector.stop_node("proj1", "node1")
        mock_requests.post.assert_any_call("http://localhost:3080/v2/projects/proj1/nodes/node1/stop", json={}, timeout=5)

        # 7. update_node (PUT)
        mock_requests.put.return_value = mock_resp
        connector.update_node("proj1", "node1", {"x": 150, "y": 250})
        mock_requests.put.assert_any_call("http://localhost:3080/v2/projects/proj1/nodes/node1", json={"x": 150, "y": 250}, timeout=5)

    @patch('network_manager.network.gns3.requests')
    def test_delete_link_between_nodes(self, mock_requests):
        connector = GNS3Connector("http://localhost:3080")
        
        # Mock get_links response
        mock_links_resp = MagicMock()
        mock_links_resp.text = '[{"link_id": "link123", "nodes": [{"node_id": "node_a"}, {"node_id": "node_b"}]}]'
        mock_links_resp.json.return_value = [{"link_id": "link123", "nodes": [{"node_id": "node_a"}, {"node_id": "node_b"}]}]
        
        # We need a separate delete response
        mock_del_resp = MagicMock()
        mock_del_resp.text = ""
        mock_del_resp.json.return_value = {}
        
        mock_requests.get.return_value = mock_links_resp
        mock_requests.delete.return_value = mock_del_resp
        
        connector.delete_link_between_nodes("proj1", "node_a", "node_b")
        mock_requests.delete.assert_called_once_with("http://localhost:3080/v2/projects/proj1/links/link123", timeout=5)

if __name__ == '__main__':
    unittest.main()
