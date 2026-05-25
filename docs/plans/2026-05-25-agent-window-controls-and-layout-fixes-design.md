# Design Document: Resizability, Window Controls, and Layout Fixes for ANCS Agent

## 1. Overview
This document outlines the architectural and layout changes required to make the frameless glassmorphic `ANCSAgentDialog` window resizable, controllable, and responsive, matching the native-feel behavior of the main application. It also addresses a CSS Flexbox overflow bug in the Web UI where uncollapsing the logs split pane causes the device details panel to spill out and overlap other elements.

## 2. Goals & Objectives
- **Resizability:** Enable dragging the 8 borders/corners of the dialog to dynamically resize it using Qt-native, transparent resize grips (`_EdgeGrip`).
- **Premium Shadow:** Enable a native Windows DWM desktop drop-shadow around the translucent dialog.
- **Title Control Integration:** Ensure double-clicking the title bar correctly toggles maximize/restore and that standard minimize, maximize, and close controls operate perfectly.
- **Layout Robustness:** Fix the CSS Flexbox overflow bug in the Web UI by adding containment properties to `.device-details-panel`.

## 3. Detailed Architecture & Components

### A. Qt-Native Edge Resizing Grip (`_EdgeGrip` Class)
We will introduce a private helper class `_EdgeGrip(QWidget)` inside `network_manager/gui/agent_dialog.py`.
- **Purpose:** Floating invisible overlays positioned absolute-style on the borders and corners of the dialog window.
- **Operation:**
  - Placed above the `QWebEngineView` in the Z-order using `self.raise_()`.
  - Captures mouse hover and drag events.
  - Dynamically resizes the parent dialog via `self.parent().setGeometry()` while honoring `minimumWidth()` (900px) and `minimumHeight()` (600px).
- **Repositioning:** Recalculated dynamically inside a newly overridden `resizeEvent(self, event)` method on `ANCSAgentDialog`. Hides grips completely if the dialog is maximized.

### B. Hardware-Accelerated DWM Drop Shadow (Windows)
Under Windows platforms (`sys.platform == "win32"`), we call the Desktop Window Manager (DWM) API:
```python
import ctypes
hwnd = int(self.winId())
margins = ctypes.c_int * 4
ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, margins(1, 1, 1, 1))
```
Restores native OS drop shadow to a borderless widget.

### C. Web UI Layout Containment (CSS Flexbox Fix)
Inside `network_manager/gui/web/index.html`, we modify the `.device-details-panel` CSS rule to add flexbox containment and a custom scrollbar:
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
    
    /* containment updates */
    min-height: 0;
    max-height: 100%;
    overflow-y: auto;
}
```

## 4. Verification & Testing Plan
1. **Visual Verification:** Launch the application and open the ANCS Agent dialog.
   - Confirm borders and corners show appropriate cursor icons on hover.
   - Confirm the window can be dynamically dragged/resized from all 8 directions.
   - Confirm the native Windows desktop drop-shadow is rendered.
2. **Behavioral Verification:**
   - Double-click the header to toggle maximize. Confirm size updates seamlessly and restore is smooth.
   - Click the "Show Logs & Events" button. Confirm the topology panel shrinks to `320px` height and the device info panel fits perfectly within it, rendering a vertical scrollbar when contents overflow.
3. **Execution Command:** Run the app:
   ```powershell
   .venv\Scripts\python.exe run.py
   ```
