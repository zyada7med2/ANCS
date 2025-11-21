"""
Network Manager - Main Entry Point

ANCS (Auto Network Configuration System)
A desktop application for network device configuration management.

Run from ANCS directory:
    python run.py
Or:
    python -m network_manager.main
"""
import sys
import os

# Handle both direct execution and module execution
if __name__ == "__main__":
    # Get the directory containing main.py (network_manager directory)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Get parent directory (ANCS directory) for module-style imports
    # This assumes the structure: ANCS/network_manager/main.py
    parent_dir = os.path.dirname(current_dir)
    
    # Add parent directory to path so we can import network_manager as a package
    # This is required because app.py uses relative imports (from ..config, etc.)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    
    # Import using absolute path since parent is in sys.path
    # This allows app.py to use relative imports (from ..config, etc.)
    from network_manager.gui.app import App  # type: ignore  # noqa: E402
else:
    # If running as module (python -m network_manager.main), use relative imports
    from .gui.app import App


def main():
    """Main entry point for the application"""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

