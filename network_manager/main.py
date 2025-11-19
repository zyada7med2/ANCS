"""
Network Manager - Main Entry Point

ANCS (Auto Network Configuration System)
A desktop application for network device configuration management.

Run: python -m network_manager.main
Or: python run.py (from parent directory)
"""
import sys
import os

# Handle both direct execution and module execution
if __name__ == "__main__":
    # If running directly, add parent directory to path
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from network_manager.gui.app import App
else:
    # If running as module, use relative imports
    from gui.app import App


def main():
    """Main entry point for the application"""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

