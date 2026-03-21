"""Shared GUI utility helpers."""
from __future__ import annotations


def apply_responsive_geometry(
    win,
    desired_w: int,
    desired_h: int,
    min_w: int | None = None,
    min_h: int | None = None,
    margin: int = 80,
) -> None:
    """Set a responsive geometry, capping to screen size and centering the window.

    Works with both Tkinter and PySide6 windows by duck-typing.
    """
    try:
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        sg = screen.geometry()
        screen_w, screen_h = sg.width(), sg.height()
    except Exception:
        try:
            win.update_idletasks()
            screen_w = win.winfo_screenwidth()
            screen_h = win.winfo_screenheight()
        except Exception:
            return

    w = min(desired_w, screen_w - margin)
    h = min(desired_h, screen_h - margin)
    x = (screen_w - w) // 2
    y = max(0, (screen_h - h) // 2)

    try:
        win.setGeometry(x, y, w, h)
        if min_w is not None and min_h is not None:
            win.setMinimumSize(
                min(min_w, screen_w - margin),
                min(min_h, screen_h - margin),
            )
    except AttributeError:
        win.geometry(f"{w}x{h}+{x}+{y}")
        if min_w is not None and min_h is not None:
            win.minsize(
                min(min_w, screen_w - margin),
                min(min_h, screen_h - margin),
            )

def apply_windows_dark_title_bar(win) -> None:
    """Request native Windows dark title bar."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(win.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
        value = ctypes.c_int(1)
        set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute
        hr = set_attr(ctypes.c_void_p(hwnd), ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE), ctypes.byref(value), ctypes.sizeof(value))
        if hr != 0:
            set_attr(ctypes.c_void_p(hwnd), ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE_OLD), ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass

def enable_global_dark_dialogs(app) -> None:
    """Uses an Event Filter to automatically apply dark title bars to all dialogs."""
    import sys
    if sys.platform != "win32":
        return
    try:
        from PySide6.QtWidgets import QDialog, QMessageBox, QInputDialog, QFileDialog
        from PySide6.QtCore import QObject, QEvent

        class DarkModeEventFilter(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Show:
                    if isinstance(obj, (QDialog, QMessageBox, QInputDialog, QFileDialog)):
                        apply_windows_dark_title_bar(obj)
                return False

        if app:
            # Keep a reference to prevent garbage collection
            app._dark_mode_filter = DarkModeEventFilter()
            app.installEventFilter(app._dark_mode_filter)
    except Exception:
        pass
