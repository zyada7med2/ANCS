# Agent Dialog Resizability, Window Controls, and Layout Fixes Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Enable smooth, interactive window resizing, premium Windows native drop-shadows, and robust layout styling for the glassmorphic `ANCSAgentDialog`.

**Architecture:** 
1. Place 8 floating transparent `_EdgeGrip` widgets around the border of `ANCSAgentDialog` to intercept mouse resize gestures and adjust dialog geometry dynamically.
2. Extend the client area frame by 1px under Windows using DWM ctypes to enable native hardware-accelerated drop shadow.
3. Fix the CSS flexbox layout of `.device-details-panel` inside the HTML UI to enable vertical containment and clean scrolling.

**Tech Stack:** PySide6 (Qt6), Win32 DWM API (ctypes), HTML5, CSS3

---

### Task 1: Add `_EdgeGrip` Helper Class to agent_dialog.py

**Files:**
- Modify: `network_manager/gui/agent_dialog.py` (Add class `_EdgeGrip`)

**Step 1: Write a minimal test or verify existing codebase styling imports**
Verify that `QWidget`, `Qt`, `QPoint`, `QCursor` are imported or accessible in `agent_dialog.py`.

**Step 2: Add `_EdgeGrip` definition**
Append the `_EdgeGrip` class directly above `class ANCSAgentDialog(QDialog):` inside [agent_dialog.py](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/gui/agent_dialog.py):

```python
class _EdgeGrip(QWidget):
    """Invisible widget placed on a window edge/corner to handle resize."""
    _CURSORS = {
        'left':         Qt.CursorShape.SizeHorCursor,
        'right':        Qt.CursorShape.SizeHorCursor,
        'top':          Qt.CursorShape.SizeVerCursor,
        'bottom':       Qt.CursorShape.SizeVerCursor,
        'top-left':     Qt.CursorShape.SizeFDiagCursor,
        'bottom-right': Qt.CursorShape.SizeFDiagCursor,
        'top-right':    Qt.CursorShape.SizeBDiagCursor,
        'bottom-left':  Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, parent: QDialog, edge: str, thickness: int = 6):
        super().__init__(parent)
        self._edge = edge
        self._thickness = thickness
        self._drag_start_pos = None
        self._drag_start_geo = None
        self.setMouseTracking(True)
        self.setCursor(self._CURSORS.get(edge, Qt.CursorShape.ArrowCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.raise_()

    def reposition(self):
        """Recompute geometry relative to parent window size."""
        pw = self.parent().width()
        ph = self.parent().height()
        t = self._thickness
        e = self._edge
        if e == 'left':
            self.setGeometry(0, t, t, ph - 2 * t)
        elif e == 'right':
            self.setGeometry(pw - t, t, t, ph - 2 * t)
        elif e == 'top':
            self.setGeometry(t, 0, pw - 2 * t, t)
        elif e == 'bottom':
            self.setGeometry(t, ph - t, pw - 2 * t, t)
        elif e == 'top-left':
            self.setGeometry(0, 0, t, t)
        elif e == 'top-right':
            self.setGeometry(pw - t, 0, t, t)
        elif e == 'bottom-left':
            self.setGeometry(0, ph - t, t, t)
        elif e == 'bottom-right':
            self.setGeometry(pw - t, ph - t, t, t)
        self.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_start_geo = self.parent().geometry()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is None or self._drag_start_geo is None:
            return
        delta = event.globalPosition().toPoint() - self._drag_start_pos
        geo = self._drag_start_geo
        parent = self.parent()
        min_w = parent.minimumWidth()
        min_h = parent.minimumHeight()

        new_x, new_y = geo.x(), geo.y()
        new_w, new_h = geo.width(), geo.height()

        e = self._edge
        if 'left' in e:
            proposed_w = geo.width() - delta.x()
            if proposed_w >= min_w:
                new_x = geo.x() + delta.x()
                new_w = proposed_w
        if 'right' in e:
            new_w = max(min_w, geo.width() + delta.x())
        if 'top' in e:
            proposed_h = geo.height() - delta.y()
            if proposed_h >= min_h:
                new_y = geo.y() + delta.y()
                new_h = proposed_h
        if 'bottom' in e:
            new_h = max(min_h, geo.height() + delta.y())

        parent.setGeometry(new_x, new_y, new_w, new_h)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        self._drag_start_geo = None
        super().mouseReleaseEvent(event)
```

---

### Task 2: Initialize grips and add window resizing and shadow logic to ANCSAgentDialog

**Files:**
- Modify: `network_manager/gui/agent_dialog.py` (Inside `ANCSAgentDialog`)

**Step 1: Update imports in agent_dialog.py**
Ensure `QWidget` and other relevant types are imported.
```python
from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox, QWidget
```

**Step 2: Add grip initialization inside `ANCSAgentDialog.__init__`**
Around line 108 of [agent_dialog.py](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/gui/agent_dialog.py), instantiate the grips:
```python
        # ── Invisible edge grips for frameless resize ──────────────────
        self._resize_grips = []
        for edge in ('left', 'right', 'top', 'bottom',
                     'top-left', 'top-right', 'bottom-left', 'bottom-right'):
            g = _EdgeGrip(self, edge, thickness=6)
            self._resize_grips.append(g)
```

**Step 3: Enable hardware drop shadow under Windows**
At the end of `__init__` in `ANCSAgentDialog`, add the DWM frame extension:
```python
        # ── Enable native Windows drop shadow for frameless dialog ────
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                margins = ctypes.c_int * 4
                ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, margins(1, 1, 1, 1))
            except Exception:
                pass
```

**Step 4: Implement `resizeEvent(self, event)` on `ANCSAgentDialog`**
Add the `resizeEvent` method inside the `ANCSAgentDialog` class to position or hide grips:
```python
    def resizeEvent(self, event):
        super().resizeEvent(event)
        for grip in getattr(self, '_resize_grips', []):
            if self._is_maximized:
                grip.hide()
            else:
                grip.reposition()
                grip.show()
```

---

### Task 3: Fix CSS Flexbox Overflow on `.device-details-panel`

**Files:**
- Modify: `network_manager/gui/web/index.html`

**Step 1: Add flexbox containment styles**
In `index.html` around line 1123, update `.device-details-panel` styling:
```css
        .device-details-panel {
            flex: 1;
            max-width: 320px;
            background: var(--bg-deep);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            min-height: 0;
            max-height: 100%;
            overflow-y: auto;
        }
```

---

### Task 4: Run Application & Verify All Features

**Files:**
- Verification: `run.py`

**Step 1: Start the application**
Run command: `.venv\Scripts\python.exe run.py`

**Step 2: Perform interactive tests**
- Verify borders/corners trigger resize mouse cursors on hover.
- Drag any border or corner and ensure the window resizes dynamically.
- Confirm standard minimize, maximize, close buttons on Web UI header work cleanly.
- Go to "Logs" page and toggle the bottom split pane uncollapsed. Ensure the device details panel displays scrollbars and stays neatly contained.
