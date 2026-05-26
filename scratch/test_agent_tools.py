import unittest
import sys
import os
import json
from unittest.mock import patch, MagicMock

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.modules['PySide6.QtWidgets'] = MagicMock()
sys.modules['PySide6.QtWebEngineWidgets'] = MagicMock()
sys.modules['PySide6.QtWebEngineCore'] = MagicMock()
sys.modules['PySide6.QtWebChannel'] = MagicMock()
sys.modules['PySide6.QtCore'] = MagicMock()
sys.modules['PySide6.QtGui'] = MagicMock()

# Import context and tools from network_manager.ai_agent
from network_manager.ai_agent import ctx, ALL_TOOLS

class TestAgentTools(unittest.TestCase):
    def setUp(self):
        ctx.gns3_project_id = "test-proj-id"
        ctx.refresh_ui_fn = MagicMock()
        
    @patch('network_manager.ai_agent.ctx.get_gns3_connector')
    def test_add_gns3_node(self, mock_get_connector):
        from network_manager.ai_agent import add_gns3_node
        
        # Verify tool is in ALL_TOOLS
        tool_names = [t.__name__ for t in ALL_TOOLS if hasattr(t, '__name__')]
        self.assertIn("add_gns3_node", tool_names)
        
        # Setup mock connector
        mock_connector = MagicMock()
        mock_connector.get_nodes.return_value = []
        mock_connector.get_templates.return_value = [{"name": "iosv-router", "template_id": "t-router"}]
        mock_connector.create_node.return_value = {
            "node_id": "new-node-123",
            "console": 5001,
            "console_host": "127.0.0.1"
        }
        mock_get_connector.return_value = mock_connector
        
        # Call tool with mocked DB conn
        with patch('network_manager.config.db_lock'), \
             patch('network_manager.config.conn') as mock_conn:
             
            mock_cur = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            
            res = add_gns3_node(name="R3", device_role="router", x=100, y=200, template_id_or_name="iosv-router")
            
            self.assertIn("Success", res)
            mock_connector.create_node.assert_called_once_with("test-proj-id", "R3", "t-router", 100, 200)
            mock_cur.execute.assert_called_once()
            ctx.refresh_ui_fn.assert_called_once()

if __name__ == '__main__':
    unittest.main()
