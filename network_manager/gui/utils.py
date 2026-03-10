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

    Args:
        win: Any tkinter window (Tk, CTk, Toplevel, CTkToplevel).
        desired_w: Preferred window width in pixels.
        desired_h: Preferred window height in pixels.
        min_w: Minimum width (also capped to screen). Skipped if None.
        min_h: Minimum height (also capped to screen). Skipped if None.
        margin: Screen-edge margin kept free on each side (default 80 px).
    """
    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()
    w = min(desired_w, screen_w - margin)
    h = min(desired_h, screen_h - margin)
    x = (screen_w - w) // 2
    y = max(0, (screen_h - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")
    if min_w is not None and min_h is not None:
        win.minsize(
            min(min_w, screen_w - margin),
            min(min_h, screen_h - margin),
        )
