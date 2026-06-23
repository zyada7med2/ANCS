# GNS3 Canvas Annotations Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Enable the ANCS AI Copilot agent to dynamically draw rectangles, ellipses, and text box annotations on GNS3, auto-calculating bounding boxes around target devices.

**Architecture:** We will extend the `GNS3Connector` class with Drawings REST methods, implement custom boundary math and SVG rendering, and register two new tools (`add_gns3_annotation`, `clear_gns3_annotations`) in `ai_agent.py`.

**Tech Stack:** Python 3, PySide6, requests, SQLite.

---

### Task 1: Add Drawings API to GNS3Connector

**Files:**
- Modify: `network_manager/network/gns3.py`
- Modify: `scratch/test_gns3.py`

**Step 1: Write the failing test**
Add tests in `scratch/test_gns3.py` inside `TestGNS3Connector`:
```python
    @patch('network_manager.network.gns3.requests')
    def test_drawing_methods(self, mock_requests):
        connector = GNS3Connector("http://localhost:3080")
        mock_resp = MagicMock()
        mock_resp.text = '{"status": "ok"}'
        mock_resp.json.return_value = {"status": "ok"}
        mock_requests.get.return_value = mock_resp
        mock_requests.post.return_value = mock_resp
        mock_requests.delete.return_value = mock_resp
        
        # Test get_drawings
        connector.get_drawings("proj1")
        mock_requests.get.assert_any_call("http://localhost:3080/v2/projects/proj1/drawings", timeout=5)
        
        # Test create_drawing
        connector.create_drawing("proj1", 10, 20, "<svg></svg>", z=-1)
        mock_requests.post.assert_any_call(
            "http://localhost:3080/v2/projects/proj1/drawings",
            json={"x": 10, "y": 20, "z": -1, "svg": "<svg></svg>", "rotation": 0, "locked": False},
            timeout=5
        )
        
        # Test delete_drawing
        connector.delete_drawing("proj1", "draw123")
        mock_requests.delete.assert_any_call("http://localhost:3080/v2/projects/proj1/drawings/draw123", timeout=5)
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_gns3.py`
Expected: FAIL (AttributeError: 'GNS3Connector' object has no attribute 'get_drawings')

**Step 3: Write minimal implementation**
Implement these methods in `GNS3Connector` at `network_manager/network/gns3.py`:
```python
    def get_drawings(self, project_id: str):
        return self._get(f"/v2/projects/{project_id}/drawings")

    def create_drawing(self, project_id: str, x: int, y: int, svg: str, z: int = -1):
        payload = {
            "x": x,
            "y": y,
            "z": z,
            "svg": svg,
            "rotation": 0,
            "locked": False
        }
        return self._post(f"/v2/projects/{project_id}/drawings", payload)

    def delete_drawing(self, project_id: str, drawing_id: str):
        return self._delete(f"/v2/projects/{project_id}/drawings/{drawing_id}")
```

**Step 4: Run test to verify it passes**
Run: `python scratch/test_gns3.py`
Expected: PASS

**Step 5: Commit**
```powershell
git add network_manager/network/gns3.py scratch/test_gns3.py
git commit -m "feat: add GNS3 drawings REST methods to GNS3Connector"
```

---

### Task 2: Implement add_gns3_annotation tool

**Files:**
- Modify: `network_manager/ai_agent.py`
- Create: `scratch/test_annotations.py`

**Step 1: Write the failing test**
Create `scratch/test_annotations.py` to verify tool logic and boundary math:
```python
import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add parent directory to path to ensure network_manager is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.modules['PySide6.QtWidgets'] = MagicMock()
sys.modules['PySide6.QtWebEngineWidgets'] = MagicMock()
sys.modules['PySide6.QtWebEngineCore'] = MagicMock()
sys.modules['PySide6.QtWebChannel'] = MagicMock()
sys.modules['PySide6.QtCore'] = MagicMock()
sys.modules['PySide6.QtGui'] = MagicMock()

from network_manager.ai_agent import ctx

class TestAnnotations(unittest.TestCase):
    def setUp(self):
        ctx.gns3_project_id = "test-proj"
        ctx.refresh_ui_fn = MagicMock()

    @patch('network_manager.ai_agent.ctx.get_gns3_connector')
    def test_add_annotation_manual(self, mock_get_connector):
        from network_manager.ai_agent import add_gns3_annotation
        mock_conn = MagicMock()
        mock_get_connector.return_value = mock_conn
        
        res = add_gns3_annotation("rectangle", x=10, y=20, width=100, height=50)
        self.assertIn("Success", res)
        mock_conn.create_drawing.assert_called_once()
        args = mock_conn.create_drawing.call_args[0]
        self.assertEqual(args[1], 10)  # x
        self.assertEqual(args[2], 20)  # y
        self.assertIn('rect class="ancs-annotation"', args[3]) # svg
        ctx.refresh_ui_fn.assert_called_once()

    @patch('network_manager.ai_agent.ctx.get_gns3_connector')
    def test_add_annotation_auto_bounding(self, mock_get_connector):
        from network_manager.ai_agent import add_gns3_annotation
        mock_conn = MagicMock()
        mock_conn.get_nodes.return_value = [
            {"name": "R1", "x": 100, "y": 150},
            {"name": "SW1", "x": 200, "y": 250}
        ]
        mock_get_connector.return_value = mock_conn
        
        res = add_gns3_annotation("ellipse", target_devices=["R1", "SW1"])
        self.assertIn("Success", res)
        mock_conn.create_drawing.assert_called_once()
        args = mock_conn.create_drawing.call_args[0]
        # Bounding box math:
        # min_x = 100, max_x = 200 -> width = 100 + 160 = 260
        # min_y = 150, max_y = 250 -> height = 100 + 160 = 260
        # x = min_x - 80 = 20
        # y = min_y - 80 = 70
        self.assertEqual(args[1], 20)  # calculated x
        self.assertEqual(args[2], 70)  # calculated y
        self.assertIn('ellipse class="ancs-annotation"', args[3])

if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_annotations.py`
Expected: FAIL (ImportError: cannot import name 'add_gns3_annotation')

**Step 3: Write minimal implementation**
Implement `add_gns3_annotation` in `network_manager/ai_agent.py`:
```python
def add_gns3_annotation(
    annotation_type: str,
    text: str = "",
    target_devices: list = None,
    x: int = 0,
    y: int = 0,
    width: int = 200,
    height: int = 80,
    fill_color: str = "",
    border_color: str = ""
) -> str:
    """
    Draw a rectangle, ellipse, or text label directly on GNS3 canvas.
    If target_devices is specified, auto-calculates boundary enclosing those devices.
    """
    pid = ctx.gns3_project_id
    if not pid:
        return "Error: No active GNS3 project connected."
        
    atype = annotation_type.lower().strip()
    if atype not in ("text", "rectangle", "ellipse"):
        return "Error: annotation_type must be 'text', 'rectangle', or 'ellipse'."

    try:
        gns3 = ctx.get_gns3_connector()
        
        # Determine coordinates/size
        final_x, final_y = x, y
        final_w, final_h = width, height
        
        if target_devices:
            # Query nodes to resolve target boundaries
            nodes = gns3.get_nodes(pid)
            matched = []
            for name in target_devices:
                name_l = name.lower().strip()
                node = next((n for n in nodes if n.get("name", "").lower().strip() == name_l or n.get("node_id") == name_l), None)
                if node:
                    matched.append(node)
                    
            if not matched:
                return f"Error: No devices found matching target list: {target_devices}"
                
            xs = [n.get("x", 0) for n in matched]
            ys = [n.get("y", 0) for n in matched]
            
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            
            # Auto dimensions with 80px padding
            final_w = (max_x - min_x) + 160
            final_h = (max_y - min_y) + 160
            final_x = min_x - 80
            final_y = min_y - 80
            
            # Single node override
            if len(matched) == 1:
                final_w = 160
                final_h = 120
                final_x = matched[0].get("x", 0) - 80
                final_y = matched[0].get("y", 0) - 60

        # Colors fallback
        fill = fill_color or "rgba(167, 139, 250, 0.15)"
        border = border_color or "rgba(167, 139, 250, 0.8)"

        # Generate SVG
        if atype == "rectangle":
            svg = (
                f'<svg width="{final_w}" height="{final_h}">'
                f'<rect class="ancs-annotation" width="{final_w}" height="{final_h}" '
                f'fill="{fill}" stroke="{border}" stroke-width="2" rx="8" ry="8" />'
                f'</svg>'
            )
        elif atype == "ellipse":
            svg = (
                f'<svg width="{final_w}" height="{final_h}">'
                f'<ellipse class="ancs-annotation" cx="{final_w // 2}" cy="{final_h // 2}" '
                f'rx="{final_w // 2}" ry="{final_h // 2}" fill="{fill}" stroke="{border}" stroke-width="2" />'
                f'</svg>'
            )
        else: # text label
            svg = (
                f'<svg width="{final_w}" height="{final_h}">'
                f'<rect class="ancs-annotation" width="{final_w}" height="{final_h}" fill="rgba(30, 41, 59, 0.9)" stroke="{border}" stroke-width="1.5" rx="5" ry="5" />'
                f'<text x="12" y="{final_h // 2 + 4}" font-family="monospace" font-size="11" font-weight="bold" fill="#38BDF8">{text}</text>'
                f'</svg>'
            )
            
        gns3.create_drawing(pid, final_x, final_y, svg, z=-1)
        
        if ctx.refresh_ui_fn:
            ctx.refresh_ui_fn()
            
        return f"Success: Added {atype} annotation at coordinates ({final_x}, {final_y}) with size {final_w}x{final_h}."
    except Exception as e:
        return f"Error adding annotation: {e}"
```

**Step 4: Run test to verify it passes**
Run: `python scratch/test_annotations.py`
Expected: PASS

**Step 5: Commit**
```powershell
git add network_manager/ai_agent.py scratch/test_annotations.py
git commit -m "feat: implement add_gns3_annotation tool with automatic boundaries and SVG rendering"
```

---

### Task 3: Implement clear_gns3_annotations tool

**Files:**
- Modify: `network_manager/ai_agent.py`
- Modify: `scratch/test_annotations.py`

**Step 1: Write the failing test**
Add `test_clear_annotations` to `scratch/test_annotations.py`:
```python
    @patch('network_manager.ai_agent.ctx.get_gns3_connector')
    def test_clear_annotations(self, mock_get_connector):
        from network_manager.ai_agent import clear_gns3_annotations
        mock_conn = MagicMock()
        mock_conn.get_drawings.return_value = [
            {"drawing_id": "d1", "svg": '<rect class="ancs-annotation" />'},
            {"drawing_id": "d2", "svg": '<svg><ellipse class="ancs-annotation" /></svg>'},
            {"drawing_id": "d3", "svg": '<rect fill="blue" />'} # not an ancs drawing
        ]
        mock_get_connector.return_value = mock_conn
        
        res = clear_gns3_annotations(target_type="all")
        self.assertIn("Success", res)
        # Verify it deleted exactly 2 drawings (d1, d2) and ignored d3
        self.assertEqual(mock_conn.delete_drawing.call_count, 2)
        mock_conn.delete_drawing.assert_any_call("test-proj", "d1")
        mock_conn.delete_drawing.assert_any_call("test-proj", "d2")
        ctx.refresh_ui_fn.assert_called_once()
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_annotations.py`
Expected: FAIL (ImportError: cannot import name 'clear_gns3_annotations')

**Step 3: Write minimal implementation**
Implement `clear_gns3_annotations` in `network_manager/ai_agent.py`:
```python
def clear_gns3_annotations(target_type: str = "all") -> str:
    """
    Remove GNS3 canvas annotations spawned by the AI agent.
    target_type can be 'all', 'text', 'rectangle', or 'ellipse'.
    """
    pid = ctx.gns3_project_id
    if not pid:
        return "Error: No active GNS3 project connected."
        
    ttype = target_type.lower().strip()
    if ttype not in ("all", "text", "rectangle", "ellipse"):
        return "Error: target_type must be 'all', 'text', 'rectangle', or 'ellipse'."

    try:
        gns3 = ctx.get_gns3_connector()
        drawings = gns3.get_drawings(pid)
        deleted_count = 0
        
        for d in drawings:
            svg = d.get("svg", "")
            if 'class="ancs-annotation"' not in svg:
                continue
                
            # Type filtering checks
            is_match = False
            if ttype == "all":
                is_match = True
            elif ttype == "rectangle" and "rect " in svg and "text " not in svg:
                is_match = True
            elif ttype == "ellipse" and "ellipse " in svg:
                is_match = True
            elif ttype == "text" and "text " in svg:
                is_match = True
                
            if is_match:
                drawing_id = d.get("drawing_id")
                if drawing_id:
                    gns3.delete_drawing(pid, drawing_id)
                    deleted_count += 1
                    
        if deleted_count > 0 and ctx.refresh_ui_fn:
            ctx.refresh_ui_fn()
            
        return f"Success: Cleared {deleted_count} {ttype} GNS3 canvas annotations."
    except Exception as e:
        return f"Error clearing annotations: {e}"
```

**Step 4: Run test to verify it passes**
Run: `python scratch/test_annotations.py`
Expected: PASS

**Step 5: Commit**
```powershell
git add network_manager/ai_agent.py scratch/test_annotations.py
git commit -m "feat: implement clear_gns3_annotations tool with category filtering"
```

---

### Task 4: Register tools in Copilot

**Files:**
- Modify: `network_manager/ai_agent.py`

**Step 1: Write the failing test**
Inside `scratch/test_annotations.py`, check that the new tools are registered:
```python
    def test_tools_registration(self):
        from network_manager.ai_agent import ALL_TOOLS
        tool_names = [t.__name__ for t in ALL_TOOLS if hasattr(t, '__name__')]
        self.assertIn("add_gns3_annotation", tool_names)
        self.assertIn("clear_gns3_annotations", tool_names)
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_annotations.py`
Expected: FAIL

**Step 3: Write minimal implementation**
1. Append `add_gns3_annotation` and `clear_gns3_annotations` to `ALL_TOOLS` in `network_manager/ai_agent.py`:
```python
    add_gns3_annotation,
    clear_gns3_annotations,
```
2. Map their UI statuses in `_MAJOR_TOOL_STATUS`:
```python
    "add_gns3_annotation": "Drawing canvas annotation...",
    "clear_gns3_annotations": "Clearing canvas annotations...",
```

**Step 4: Run test to verify it passes**
Run: `python scratch/test_annotations.py`
Expected: PASS

**Step 5: Commit**
```powershell
git add network_manager/ai_agent.py
git commit -m "feat: register GNS3 annotation tools in ALL_TOOLS list"
```
