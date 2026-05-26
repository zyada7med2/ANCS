# GNS3 Topology Editing Design Document

This design document outlines the architecture, data structures, and implementation plan for enabling the ANCS AI Copilot agent to dynamically manage GNS3 topologies, including adding/deleting nodes, cabling (connections), controlling power states, and synchronizing SQLite and the UI.

---

## 1. GNS3 REST Extensions (`gns3.py`)

We will extend `GNS3Connector` inside `network_manager/network/gns3.py` with generic HTTP POST and DELETE handlers, as well as specific topology editing wrappers.

### Added Methods
- `_post(self, path: str, json_data: dict = None, timeout: int = 5) -> dict`
- `_delete(self, path: str, timeout: int = 5) -> dict`
- `get_templates(self) -> list`
- `create_node(self, project_id: str, name: str, template_id: str, x: int = 0, y: int = 0) -> dict`
- `delete_node(self, project_id: str, node_id: str) -> dict`
- `create_link(self, project_id: str, node_a_id: str, adapter_a: int, port_a: int, node_b_id: str, adapter_b: int, port_b: int) -> dict`
- `delete_link_between_nodes(self, project_id: str, node_a_id: str, node_b_id: str) -> dict`
- `start_node(self, project_id: str, node_id: str) -> dict`
- `stop_node(self, project_id: str, node_id: str) -> dict`

---

## 2. Database & UI Synchronization Design

To update the UI and database when the AI Copilot modifies GNS3:
1. **Queued Signal in CopilotWorker:**
   - Define a custom signal `refresh_gns3_signal = Signal()` in the `CopilotWorker` class.
   - Bind `ctx.refresh_ui_fn = self.refresh_gns3_signal.emit` in `CopilotWorker.__init__`.
2. **Signal connection in AgentDialog:**
   - In `network_manager/gui/agent_dialog.py`, connect `refresh_gns3_signal` to `self._on_refresh_gns3` using `Qt.ConnectionType.QueuedConnection`.
   - The slot calls `self.app.refresh_gns3_connection()`, which safely fetches nodes from GNS3 on a background thread, updates SQLite, and updates the UI.

---

## 3. Agent Tools Specification

The following tools will be added to the Gemini and OpenAI toolsets in `network_manager/ai_agent.py`:

### A. `add_gns3_node`
- **Signature:** `add_gns3_node(name: str, device_role: str, x: int = 0, y: int = 0, template_id_or_name: str = "") -> str`
- **Logic:**
  1. Clones the template ID of any existing node in the project with the same role (e.g. router, core switch).
  2. Fallback: Fetches templates from GNS3 and matches name using mappings or regexes.
  3. POSTs to GNS3 `/v2/projects/{project_id}/nodes`.
  4. Triggers `ctx.refresh_ui_fn()`.

### B. `delete_gns3_node`
- **Signature:** `delete_gns3_node(node_id_or_name: str) -> str`
- **Logic:**
  1. Resolves name/ID to UUID.
  2. Calls DELETE GNS3 node API.
  3. Triggers `ctx.refresh_ui_fn()`.

### C. `connect_gns3_nodes`
- **Signature:** `connect_gns3_nodes(node_a: str, port_a: str, node_b: str, port_b: str) -> str`
- **Logic:**
  1. Fetches GNS3 ports for both nodes.
  2. Maps port names (e.g., `Ethernet0/0`) to their `adapter_number` and `port_number`.
  3. POSTs to `/links`.
  4. Triggers `ctx.refresh_ui_fn()`.

### D. `delete_gns3_link`
- **Signature:** `delete_gns3_link(node_a: str, node_b: str) -> str`
- **Logic:**
  1. Identifies the link connecting `node_a` and `node_b`.
  2. Calls GNS3 DELETE `/links/{link_id}` endpoint.
  3. Triggers `ctx.refresh_ui_fn()`.

### E. `control_gns3_node_power`
- **Signature:** `control_gns3_node_power(node_id_or_name: str, action: str) -> str`
- **Logic:**
  1. Resolves node ID.
  2. Powers on/off or restarts node via GNS3 API.
  3. Triggers `ctx.refresh_ui_fn()`.

---

## 4. Data Flow & State Synchronization Details

- Background agent tools call `GNS3Connector`.
- REST modification is sent to GNS3 Server.
- Custom signal `refresh_gns3_signal` is emitted.
- Main thread catches signal and runs `app.refresh_gns3_connection()`.
- Local SQLite database and active workspace `devices` list are synced.
- Tables, device grids, and the topology viewer canvas are automatically redrawn.

---

## 5. Error Handling & Edge Cases

- **Missing Mappings:** Raises a helpful warning listing all GNS3 templates.
- **Wrong Port Spec:** Returns error showing available interfaces.
- **Hot-Plug Failures:** Stops node temporarily, cables, and starts it.
- **Already Connected Ports:** Detects GNS3 conflict and instructs agent to use another port.

---

## 6. Testing & Verification Plan

1. **Unit Verification:** Run programmatic tests in `scratch/test_gns3_topology.py` to confirm the REST API wrappers function correctly.
2. **End-to-End Integration:** Execute a multi-device setup task via Copilot chat dialog and ensure coordinates, cabling, status, and db update synchronously without crashing.
