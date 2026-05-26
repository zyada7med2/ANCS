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

if __name__ == '__main__':
    unittest.main()
