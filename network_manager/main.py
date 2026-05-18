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
    import traceback
    import faulthandler

    # Enable faulthandler to capture C-level crashes (segfaults, access violations)
    # that bypass Python's exception handling entirely.
    _fault_path = os.path.join(os.path.dirname(__file__), "..", "crash_native.log")
    _fault_file = open(_fault_path, "a", encoding="utf-8")
    faulthandler.enable(file=_fault_file, all_threads=True)

    def handle_exception(exc_type, exc_value, exc_tb):
        """Log all exceptions to crash.log"""
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            crash_path = os.path.join(os.path.dirname(__file__), "..", "crash.log")
            with open(crash_path, "a", encoding="utf-8") as f:
                import time
                f.write(f"\n{'='*60}\n{time.strftime('%Y-%m-%d %H:%M:%S')} Unhandled exception:\n{tb}\n")
        except Exception:
            pass
        # Also print to stderr
        print(f"\n{'='*60}\nUNHANDLED EXCEPTION:\n{tb}\n{'='*60}\n", file=sys.stderr, flush=True)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_exception

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    window = App()
    window.mainloop()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
