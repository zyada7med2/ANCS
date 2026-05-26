import unittest
import sys
import os

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject
from network_manager.ai_agent import CopilotWorker, ctx

class TestCopilotWorkerSignals(unittest.TestCase):
    def test_worker_signals_and_context(self):
        # We need a dummy QCoreApplication for PySide6 signals to function properly
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication([])
        
        # Instantiate worker with dummy credentials/details
        worker = CopilotWorker(
            api_key="mock_key",
            gns3_url="http://localhost:3080",
            allow_raw_deploy=False,
            workspace_resolved=[],
            gns3_project_id="mock_project",
            project_snapshot="{}",
            audit_fn=None,
            provider="gemini",
            model_name="gemini-1.5-flash",
            initial_messages=[]
        )
        
        # Verify signal exists on worker
        self.assertTrue(hasattr(worker, "refresh_gns3_signal"))
        
        # Verify context refresh_ui_fn matches signal's emit method
        self.assertIsNotNone(ctx.refresh_ui_fn)
        self.assertEqual(ctx.refresh_ui_fn, worker.refresh_gns3_signal.emit)

if __name__ == '__main__':
    unittest.main()
