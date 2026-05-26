import unittest
import sys
import os
import traceback
from unittest.mock import patch, MagicMock

# Define DummyBase for QtWidgets mock
class DummyBase:
    def __init__(self, *args, **kwargs):
        pass
    def __getattr__(self, name):
        return MagicMock()

# Mock PySide6 modules before any imports happen
mock_qtwidgets = MagicMock()
mock_qtwidgets.QDialog = DummyBase
mock_qtwidgets.QWidget = DummyBase
mock_qtwidgets.QVBoxLayout = DummyBase
mock_qtwidgets.QMessageBox = DummyBase

sys.modules['PySide6.QtWidgets'] = mock_qtwidgets

# Mock QtWebEngineWidgets and QtWebChannel as well
sys.modules['PySide6.QtWebEngineWidgets'] = MagicMock()
sys.modules['PySide6.QtWebEngineCore'] = MagicMock()
sys.modules['PySide6.QtWebChannel'] = MagicMock()
sys.modules['PySide6.QtCore'] = MagicMock()
sys.modules['PySide6.QtGui'] = MagicMock()

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestAgentDialogSignals(unittest.TestCase):
    def test_signal_handling(self):
        try:
            # Mock Parent Application
            mock_app = MagicMock()
            mock_app._copilot_chat_data = []
            mock_app._copilot_worker = MagicMock()
            
            # Import inside test now that sys.modules is mocked
            from network_manager.gui.agent_dialog import ANCSAgentDialog
            
            dialog = ANCSAgentDialog(mock_app)
            print("dialog.app is:", dialog.app)
            
            # Verify _on_refresh_gns3 exists
            self.assertTrue(hasattr(dialog, "_on_refresh_gns3"))
            
            # Verify it delegates to parent app
            dialog._on_refresh_gns3()
            mock_app.refresh_gns3_connection.assert_called_once()
            print("TEST PASSED!")
        except Exception as e:
            print("TEST EXCEPTION:", e)
            traceback.print_exc()
            raise

if __name__ == '__main__':
    unittest.main()
