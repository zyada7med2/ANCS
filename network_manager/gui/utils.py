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
