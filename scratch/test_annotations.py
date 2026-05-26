import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.modules['PySide6.QtWidgets'] = MagicMock()
sys.modules['PySide6.QtWebEngineWidgets'] = MagicMock()
sys.modules['PySide6.QtWebEngineCore'] = MagicMock()
sys.modules['PySide6.QtWebChannel'] = MagicMock()
sys.modules['PySide6.QtCore'] = MagicMock()
sys.modules['PySide6.QtGui'] = MagicMock()

from network_manager.ai_agent import ctx

class TestAnnotations(unittest.TestCase):
    def setUp(self):
        ctx.gns3_project_id = "test-proj"
        ctx.refresh_ui_fn = MagicMock()

    @patch('network_manager.ai_agent.ctx.get_gns3_connector')
    def test_add_annotation_manual(self, mock_get_connector):
        from network_manager.ai_agent import add_gns3_annotation
        mock_conn = MagicMock()
        mock_get_connector.return_value = mock_conn
        
        res = add_gns3_annotation("rectangle", x=10, y=20, width=100, height=50)
        self.assertIn("Success", res)
        mock_conn.create_drawing.assert_called_once()
        args = mock_conn.create_drawing.call_args[0]
        self.assertEqual(args[1], 10)  # x
        self.assertEqual(args[2], 20)  # y
        self.assertIn('rect class="ancs-annotation"', args[3]) # svg
        ctx.refresh_ui_fn.assert_called_once()

    @patch('network_manager.ai_agent.ctx.get_gns3_connector')
    def test_add_annotation_auto_bounding(self, mock_get_connector):
        from network_manager.ai_agent import add_gns3_annotation
        mock_conn = MagicMock()
        mock_conn.get_nodes.return_value = [
            {"name": "R1", "x": 100, "y": 150},
            {"name": "SW1", "x": 200, "y": 250}
        ]
        mock_get_connector.return_value = mock_conn
        
        res = add_gns3_annotation("ellipse", target_devices=["R1", "SW1"])
        self.assertIn("Success", res)
        mock_conn.create_drawing.assert_called_once()
        args = mock_conn.create_drawing.call_args[0]
        # Bounding box math:
        # min_x = 100, max_x = 200 -> width = 100 + 160 = 260
        # min_y = 150, max_y = 250 -> height = 100 + 160 = 260
        # x = min_x - 80 = 20
        # y = min_y - 80 = 70
        self.assertEqual(args[1], 20)  # calculated x
        self.assertEqual(args[2], 70)  # calculated y
        self.assertIn('ellipse class="ancs-annotation"', args[3])

    @patch('network_manager.ai_agent.ctx.get_gns3_connector')
    def test_clear_annotations(self, mock_get_connector):
        from network_manager.ai_agent import clear_gns3_annotations
        mock_conn = MagicMock()
        mock_conn.get_drawings.return_value = [
            {"drawing_id": "d1", "svg": '<rect class="ancs-annotation" />'},
            {"drawing_id": "d2", "svg": '<svg><ellipse class="ancs-annotation" /></svg>'},
            {"drawing_id": "d3", "svg": '<rect fill="blue" />'} # not an ancs drawing
        ]
        mock_get_connector.return_value = mock_conn
        
        res = clear_gns3_annotations(target_type="all")
        self.assertIn("Success", res)
        # Verify it deleted exactly 2 drawings (d1, d2) and ignored d3
        self.assertEqual(mock_conn.delete_drawing.call_count, 2)
        mock_conn.delete_drawing.assert_any_call("test-proj", "d1")
        mock_conn.delete_drawing.assert_any_call("test-proj", "d2")
        ctx.refresh_ui_fn.assert_called_once()

if __name__ == '__main__':
    unittest.main()
