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

# Check for PySide6 before any GUI imports
try:
    import PySide6  # noqa: F401
except ModuleNotFoundError:
    print("PySide6 is not installed. Install it with:")
    print("  pip install PySide6")
    print("Or install all dependencies:")
    print("  pip install -r network_manager/requirements.txt")
    sys.exit(1)

# Handle both direct execution and module execution
if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from network_manager.gui.app import App  # type: ignore  # noqa: E402
else:
    from .gui.app import App

def main():
    """Main entry point for the application"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    window = App()
    window.mainloop()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
