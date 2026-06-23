# GNS3 Canvas Annotations & Drawings Design Document

This document describes the design for enabling the ANCS AI Copilot agent to dynamically draw annotations (shaded zones, boundary shapes, and floating text labels) directly on the GNS3 topology canvas, and to clear/delete them.

---

## 1. REST Client Updates (`gns3.py`)

We will add three drawing wrapper methods in `GNS3Connector` at [network_manager/network/gns3.py](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/network/gns3.py):

* **`get_drawings(self, project_id: str) -> list`**: Calls `GET /v2/projects/{project_id}/drawings` to fetch all current shapes/text elements.
* **`create_drawing(self, project_id: str, x: int, y: int, svg: str, z: int = -1) -> dict`**: Calls `POST /v2/projects/{project_id}/drawings` to add an SVG drawing element at coordinate `(x, y)` in layer `z` (default `-1` to ensure it is layered *under* nodes and links).
* **`delete_drawing(self, project_id: str, drawing_id: str) -> dict`**: Calls `DELETE /v2/projects/{project_id}/drawings/{drawing_id}`.

---

## 2. Dynamic Bounding Box & SVG Synthesis

### A. Coordinate Calculations
If `target_devices` is provided (e.g. `["R1", "SW1"]`):
1. Query GNS3 to get coordinates `(x, y)` of all matched devices.
2. If no matched devices are found, return an error message.
3. Compute the minimum and maximum boundaries:
   * $min\_x = \min(x_i)$
   * $max\_x = \max(x_i)$
   * $min\_y = \min(y_i)$
   * $max\_y = \max(y_i)$
4. Add visual padding (default $80\text{px}$) to form the canvas drawing dimensions:
   * $\text{width} = (max\_x - min\_x) + 160$
   * $\text{height} = (max\_y - min\_y) + 160$
   * $x = min\_x - 80$
   * $y = min\_y - 80$
5. If enclosing a single device, default to $width = 160$, $height = 120$, centered around the device.

If `target_devices` is not provided, use the user-supplied values of `x`, `y`, `width`, and `height`.

---

### B. SVG Generation Templates
To differentiate ANCS-generated drawings from other manual GNS3 elements, we will inject a unique identifier class/attribute (`class="ancs-annotation"`) into our SVG strings.

#### Rectangle Template:
```xml
<svg width="{width}" height="{height}">
  <rect class="ancs-annotation" width="{width}" height="{height}" fill="{fill_color}" stroke="{border_color}" stroke-width="2" rx="8" ry="8" />
</svg>
```

#### Ellipse Template:
```xml
<svg width="{width}" height="{height}">
  <ellipse class="ancs-annotation" cx="{width//2}" cy="{height//2}" rx="{width//2}" ry="{height//2}" fill="{fill_color}" stroke="{border_color}" stroke-width="2" />
</svg>
```

#### Text Label Template:
We build a styled capsule shape with a dark slate background to keep the monospace text fully legible:
```xml
<svg width="{width}" height="{height}">
  <rect class="ancs-annotation" width="{width}" height="{height}" fill="rgba(30, 41, 59, 0.9)" stroke="{border_color}" stroke-width="1.5" rx="5" ry="5" />
  <text x="12" y="{height//2 + 4}" font-family="monospace" font-size="11" font-weight="bold" fill="#38BDF8">{text}</text>
</svg>
```

---

## 3. Agent Tool Specifications (`ai_agent.py`)

### A. `add_gns3_annotation`
* **Signature:** `add_gns3_annotation(annotation_type: str, text: str = "", target_devices: list = None, x: int = 0, y: int = 0, width: int = 200, height: int = 80, fill_color: str = "", border_color: str = "") -> str`
* **MIME/Parameter Fallbacks:**
  * `annotation_type`: Must be one of `text`, `rectangle`, or `ellipse`.
  * `fill_color` default: `"rgba(167, 139, 250, 0.15)"` (soft purple transparency).
  * `border_color` default: `"rgba(167, 139, 250, 0.8)"` (semi-opaque purple).
* **Action Flow:**
  1. Computes boundaries (auto-calculating if target devices list exists).
  2. Generates SVG string.
  3. Invokes GNS3 REST client to create drawing.
  4. Calls `ctx.refresh_ui_fn()` to trigger Qt UI refresh.
  5. Returns success status message with coordinates.

### B. `clear_gns3_annotations`
* **Signature:** `clear_gns3_annotations(target_type: str = "all") -> str`
* **Action Flow:**
  1. Retrieves all drawings from GNS3.
  2. Filters for drawings whose `svg` string contains `class="ancs-annotation"`.
  3. If `target_type` is `"text"`, `"rectangle"`, or `"ellipse"`, filter specifically for matching SVG elements.
  4. Deletes each matching drawing in parallel via GNS3 DELETE API.
  5. Calls `ctx.refresh_ui_fn()` to trigger Qt UI refresh.
  6. Returns count of deleted drawings.

---

## 4. Verification Plan

1. **Unit Testing:** Implement programmatic tests in `scratch/test_annotations.py` with mock HTTP responses for `get_drawings`, `create_drawing`, and `delete_drawing`, verifying boundary math and correct SVG assembly.
2. **Live Integration Testing:** Run an integration script that spawns a text label and a shaded boundary rectangle around existing nodes (e.g. `R1`, `R2`) in the running GNS3 server workspace, validates their existence, and then cleans them up.
