# GNS3 Topology Editing Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Enable the ANCS AI Copilot agent to dynamically manage GNS3 topologies, including adding/deleting nodes, cabling (connections), controlling power states, and synchronizing SQLite and the UI.

**Architecture:** We will extend the `GNS3Connector` class with REST POST/DELETE endpoints, register 5 new tools in `ai_agent.py` mapping to these endpoints, and add a thread-safe Qt Signal to trigger the existing background synchronization workflow in `app.py`.

**Tech Stack:** Python 3, PySide6 (Qt6), requests, SQLite.

---

### Task 1: Add POST/DELETE helpers to GNS3Connector

**Files:**
- Modify: `network_manager/network/gns3.py`
- Create: `scratch/test_gns3.py`

**Step 1: Write the failing test**
Create `scratch/test_gns3.py` testing for `_post` and `_delete` methods on `GNS3Connector` with mock responses:
```python
import unittest
from unittest.mock import patch, MagicMock
from network_manager.network.gns3 import GNS3Connector

class TestGNS3Connector(unittest.TestCase):
    @patch('network_manager.network.gns3.requests')
    def test_post_and_delete(self, mock_requests):
        connector = GNS3Connector("http://localhost:3080")
        
        # Test post
        mock_response = MagicMock()
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_requests.post.return_value = mock_response
        
        res = connector._post("/v2/test", {"data": 1})
        self.assertEqual(res, {"status": "ok"})
        mock_requests.post.assert_called_once_with("http://localhost:3080/v2/test", json={"data": 1}, timeout=5)
        
        # Test delete
        mock_response_del = MagicMock()
        mock_response_del.text = ""
        mock_requests.delete.return_value = mock_response_del
        res_del = connector._delete("/v2/test/1")
        self.assertEqual(res_del, {})
        mock_requests.delete.assert_called_once_with("http://localhost:3080/v2/test/1", timeout=5)

if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_gns3.py`
Expected: FAIL (AttributeError: 'GNS3Connector' object has no attribute '_post')

**Step 3: Write minimal implementation**
Add `_post` and `_delete` to `GNS3Connector` in `network_manager/network/gns3.py`:
```python
    def _post(self, path: str, json_data: dict = None, timeout: int = 5):
        if requests is None:
            raise RuntimeError("'requests' library is not installed")
        try:
            r = requests.post(f"{self.server_url}{path}", json=json_data or {}, timeout=timeout)
            r.raise_for_status()
            return r.json() if r.text else {}
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot reach GNS3 server at {self.server_url}. Make sure GNS3 is running."
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"GNS3 server at {self.server_url} did not respond within {timeout} seconds."
            )
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if hasattr(exc, 'response') else "unknown"
            body = exc.response.text if hasattr(exc, 'response') else ""
            raise RuntimeError(
                f"GNS3 API error ({status}): {path}\nResponse: {body[:200]}"
            )

    def _delete(self, path: str, timeout: int = 5):
        if requests is None:
            raise RuntimeError("'requests' library is not installed")
        try:
            r = requests.delete(f"{self.server_url}{path}", timeout=timeout)
            r.raise_for_status()
            return r.json() if r.text else {}
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot reach GNS3 server at {self.server_url}. Make sure GNS3 is running."
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"GNS3 server at {self.server_url} did not respond within {timeout} seconds."
            )
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if hasattr(exc, 'response') else "unknown"
            body = exc.response.text if hasattr(exc, 'response') else ""
            raise RuntimeError(
                f"GNS3 API error ({status}): {path}\nResponse: {body[:200]}"
            )
```

**Step 4: Run test to verify it passes**
Run: `python scratch/test_gns3.py`
Expected: PASS

**Step 5: Commit**
```bash
git add network_manager/network/gns3.py scratch/test_gns3.py
git commit -m "feat: add post and delete HTTP helper methods to GNS3Connector"
```

---

### Task 2: Add topology editing methods to GNS3Connector

**Files:**
- Modify: `network_manager/network/gns3.py`
- Modify: `scratch/test_gns3.py`

**Step 1: Write the failing test**
Add tests in `scratch/test_gns3.py` for `get_templates`, `create_node`, `delete_node`, `create_link`, `delete_link_between_nodes`, `start_node`, and `stop_node`.
Verify they fail due to missing methods.

**Step 2: Run test to verify it fails**
Run: `python scratch/test_gns3.py`
Expected: FAIL

**Step 3: Write minimal implementation**
Implement these methods in `GNS3Connector`:
```python
    def get_templates(self):
        return self._get("/v2/templates")

    def create_node(self, project_id: str, name: str, template_id: str, x: int = 0, y: int = 0):
        payload = {"name": name, "x": x, "y": y}
        return self._post(f"/v2/projects/{project_id}/templates/{template_id}", payload)

    def delete_node(self, project_id: str, node_id: str):
        return self._delete(f"/v2/projects/{project_id}/nodes/{node_id}")

    def create_link(self, project_id: str, node_a_id: str, adapter_a: int, port_a: int, node_b_id: str, adapter_b: int, port_b: int):
        payload = {
            "nodes": [
                {"node_id": node_a_id, "adapter_number": adapter_a, "port_number": port_a},
                {"node_id": node_b_id, "adapter_number": adapter_b, "port_number": port_b}
            ]
        }
        return self._post(f"/v2/projects/{project_id}/links", payload)

    def delete_link_between_nodes(self, project_id: str, node_a_id: str, node_b_id: str):
        links = self.get_links(project_id)
        for link in links:
            endpoints = link.get("nodes", [])
            if len(endpoints) >= 2:
                id_a = endpoints[0].get("node_id")
                id_b = endpoints[1].get("node_id")
                if (id_a == node_a_id and id_b == node_b_id) or (id_a == node_b_id and id_b == node_a_id):
                    link_id = link.get("link_id")
                    if link_id:
                        return self._delete(f"/v2/projects/{project_id}/links/{link_id}")
        raise RuntimeError(f"No link found between node {node_a_id} and node {node_b_id}")

    def start_node(self, project_id: str, node_id: str):
        return self._post(f"/v2/projects/{project_id}/nodes/{node_id}/start", {})

    def stop_node(self, project_id: str, node_id: str):
        return self._post(f"/v2/projects/{project_id}/nodes/{node_id}/stop", {})
```

**Step 4: Run test to verify it passes**
Run: `python scratch/test_gns3.py`
Expected: PASS

**Step 5: Commit**
```bash
git add network_manager/network/gns3.py scratch/test_gns3.py
git commit -m "feat: implement node and link topology modification methods in GNS3Connector"
```

---

### Task 3: Add custom signal and callback to CopilotWorker

**Files:**
- Modify: `network_manager/ai_agent.py`

**Step 1: Write the failing test**
We will add checks in a new script `scratch/test_copilot_signals.py` verifying that:
1. `CopilotWorker` defines `refresh_gns3_signal` as a PySide6 `Signal`.
2. `ctx.refresh_ui_fn` maps to the signal's emit method when worker is constructed.

**Step 2: Run test to verify it fails**
Run: `python scratch/test_copilot_signals.py`
Expected: FAIL

**Step 3: Write minimal implementation**
1. In `network_manager/ai_agent.py`, add the signal to `CopilotWorker`:
   ```python
   refresh_gns3_signal = Signal()
   ```
2. In `CopilotWorker.__init__`:
   ```python
   ctx.refresh_ui_fn = self.refresh_gns3_signal.emit
   ```
3. Initialize a placeholder `ctx.refresh_ui_fn = None` on `_AgentContext` definition (line 41).

**Step 4: Run test to verify it passes**
Run: `python scratch/test_copilot_signals.py`
Expected: PASS

**Step 5: Commit**
```bash
git add network_manager/ai_agent.py scratch/test_copilot_signals.py
git commit -m "feat: add refresh_gns3_signal to CopilotWorker and set context callback"
```

---

### Task 4: Handle signal in AgentDialog

**Files:**
- Modify: `network_manager/gui/agent_dialog.py`

**Step 1: Write the failing test**
We can check that `_connect_worker_signals` connects `refresh_gns3_signal` to `_on_refresh_gns3`.

**Step 2: Run test to verify it fails**
Run: `python scratch/test_dialog_signals.py` (checks connection behavior via import/mocks)
Expected: FAIL

**Step 3: Write minimal implementation**
1. In `network_manager/gui/agent_dialog.py`, inside `_connect_worker_signals`:
   ```python
   w.refresh_gns3_signal.connect(self._on_refresh_gns3, Qt.ConnectionType.QueuedConnection)
   ```
2. Inside `_disconnect_worker_signals`:
   ```python
   w.refresh_gns3_signal.disconnect(self._on_refresh_gns3)
   ```
3. Add slot method to `ANCSAgentDialog`:
   ```python
   def _on_refresh_gns3(self):
       self.app.refresh_gns3_connection()
   ```

**Step 4: Run test to verify it passes**
Run: `python scratch/test_dialog_signals.py`
Expected: PASS

**Step 5: Commit**
```bash
git add network_manager/gui/agent_dialog.py
git commit -m "feat: connect refresh_gns3_signal in AgentDialog to trigger refresh_gns3_connection"
```

---

### Task 5: Implement `add_gns3_node` tool

**Files:**
- Modify: `network_manager/ai_agent.py`

**Step 1: Write the failing test**
Verify `add_gns3_node` is in `ALL_TOOLS` and fails when called with mock project ID.

**Step 2: Run test to verify it fails**
Run: `python scratch/test_agent_tools.py`
Expected: FAIL

**Step 3: Write minimal implementation**
1. Include `x` and `y` coordinates in GNS3 nodes returned by `list_gns3_nodes` (lines 215-218 of `ai_agent.py`):
   ```python
   "x": n.get("x", 0),
   "y": n.get("y", 0),
   ```
2. Implement `add_gns3_node`:
   ```python
   def add_gns3_node(name: str, device_role: str, x: int = 0, y: int = 0, template_id_or_name: str = "") -> str:
       """
       Add a new node to the active GNS3 project. Spawns device of role 'router', 'core', or 'access'/'switch'.
       Automatically clones template from existing same-role node if found. Fallback: matches via global templates.
       """
       pid = ctx.gns3_project_id
       if not pid:
           return "Error: No active GNS3 project connected."
       try:
           gns3 = ctx.get_gns3_connector()
           template_id = ""
           
           # If template name/id is given, use it
           if template_id_or_name:
               templates = gns3.get_templates()
               for t in templates:
                   if template_id_or_name.lower() in t.get("name", "").lower() or template_id_or_name == t.get("template_id"):
                       template_id = t.get("template_id")
                       break
           
           # Try cloning template from existing same-role node
           if not template_id:
               nodes = gns3.get_nodes(pid)
               target_type = "router" if device_role == "router" else "core switch" if device_role == "core" else "switch"
               
               # Keywords for role detection to match gui/app.py logic
               l3_keywords = ['l3 switch', 'layer3', 'layer 3', 'esw', 'c3640', 'c3560', 'c3750', 'multilayer']
               rtr_keywords = ['router', 'ios', 'csr', 'isr', 'iosv', 'firepower', 'asa', 'xrv', 'nxos', 'c2691', 'c2600', 'c7200', 'c3725', 'c3745', 'c3660', 'c3845', 'c1900', 'c2900']
               
               for node in nodes:
                   raw_type = node.get('node_type', '')
                   n_name = node.get('name', '')
                   platform = node.get('platform', '')
                   console_type = node.get('console_type', '')
                   image_name = (node.get('properties') or {}).get('image', '')
                   full_desc = " ".join([raw_type, platform, console_type, image_name, n_name]).lower()
                   
                   ntype = 'switch'
                   if any(k in full_desc for k in l3_keywords):
                       ntype = 'core switch'
                   elif any(k in full_desc for k in rtr_keywords):
                       ntype = 'router'
                       
                   if ntype == target_type and node.get("template_id"):
                       template_id = node.get("template_id")
                       break
                       
           # Check config mappings
           if not template_id:
               import os
               import json
               from network_manager.config import _BASE_DIR
               mapping_file = os.path.join(_BASE_DIR, "gns3_template_mappings.json")
               if os.path.exists(mapping_file):
                   try:
                       with open(mapping_file, "r") as f:
                           mappings = json.load(f)
                           val = mappings.get(device_role)
                           if val:
                               templates = gns3.get_templates()
                               for t in templates:
                                   if val.lower() in t.get("name", "").lower() or val == t.get("template_id"):
                                       template_id = t.get("template_id")
                                       break
                   except Exception:
                       pass
                       
           # Fetch all templates and try standard naming match
           if not template_id:
               templates = gns3.get_templates()
               candidates = []
               for t in templates:
                   name_lower = t.get("name", "").lower()
                   if device_role == "router" and any(k in name_lower for k in ("iosv", "c3725", "c7200", "router")):
                       candidates.append(t)
                   elif device_role == "core" and any(k in name_lower for k in ("l3", "layer3", "layer 3", "ioul3")):
                       candidates.append(t)
                   elif device_role in ("switch", "access") and any(k in name_lower for k in ("iosvl2", "switch", "ioul2")):
                       candidates.append(t)
               if candidates:
                   template_id = candidates[0].get("template_id")
                   
           if not template_id:
               # Return failure listing templates
               templates = gns3.get_templates()
               t_names = [t.get("name") for t in templates if t.get("name")]
               return f"Error: No template mapped or found for role '{device_role}'. Available templates: {t_names}. Add template_id_or_name or create a mapping in gns3_template_mappings.json."

           # Spawning node
           node_res = gns3.create_node(pid, name, template_id, x, y)
           
           # Sync database
           from network_manager.config import conn, db_lock
           import time
           ts = time.strftime("%Y-%m-%d %H:%M:%S")
           with db_lock:
               cur = conn.cursor()
               cur.execute(
                   "INSERT OR REPLACE INTO devices (name, type, ip, port, connection_type, added_from_gns3, project_id, node_id, created_at) "
                   "VALUES (?, ?, ?, ?, 'gns3-console', 1, ?, ?, ?)",
                   (name, "core switch" if device_role == "core" else "router" if device_role == "router" else "switch", 
                    node_res.get("console_host", "localhost"), str(node_res.get("console", "")), pid, node_res.get("node_id"), ts)
               )
               conn.commit()
               cur.close()
           
           # Trigger UI sync
           if ctx.refresh_ui_fn:
               ctx.refresh_ui_fn()
               
           return f"Success: Created node '{name}' from template ID '{template_id}' at coordinate ({x}, {y})."
       except Exception as e:
           return f"Error adding node: {e}"
   ```
3. Add `add_gns3_node` to `ALL_TOOLS` and `_MAJOR_TOOL_STATUS` in `network_manager/ai_agent.py`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_agent_tools.py`
Expected: PASS

**Step 5: Commit**
```bash
git add network_manager/ai_agent.py
git commit -m "feat: implement add_gns3_node tool function with template cloning"
```

---

### Task 6: Implement `delete_gns3_node` tool

**Files:**
- Modify: `network_manager/ai_agent.py`

**Step 1: Write the failing test**
Verify `delete_gns3_node` is in `ALL_TOOLS` and fails correctly.

**Step 2: Run test to verify it fails**
Run: `python scratch/test_agent_tools.py`
Expected: FAIL

**Step 3: Write minimal implementation**
1. Implement `delete_gns3_node`:
   ```python
   def delete_gns3_node(node_id_or_name: str) -> str:
       """
       Delete a device/node from GNS3 and synchronize database and UI.
       """
       pid = ctx.gns3_project_id
       if not pid:
           return "Error: No active GNS3 project connected."
       try:
           gns3 = ctx.get_gns3_connector()
           nodes = gns3.get_nodes(pid)
           node_id = ""
           resolved_name = ""
           for n in nodes:
               if n.get("node_id") == node_id_or_name or n.get("name", "").lower() == node_id_or_name.lower():
                   node_id = n.get("node_id")
                   resolved_name = n.get("name")
                   break
           if not node_id:
               return f"Error: Node '{node_id_or_name}' not found."
               
           gns3.delete_node(pid, node_id)
           
           # Delete from local DB
           from network_manager.config import conn, db_lock
           with db_lock:
               cur = conn.cursor()
               cur.execute("DELETE FROM configs WHERE device_id = (SELECT id FROM devices WHERE name = ?)", (resolved_name,))
               cur.execute("DELETE FROM credentials WHERE device_name = ?", (resolved_name,))
               cur.execute("DELETE FROM devices WHERE name = ?", (resolved_name,))
               conn.commit()
               cur.close()
               
           if ctx.refresh_ui_fn:
               ctx.refresh_ui_fn()
               
           return f"Success: Deleted node '{resolved_name}' ({node_id}) from topology."
       except Exception as e:
           return f"Error deleting node: {e}"
   ```
2. Register `delete_gns3_node` in `ALL_TOOLS` and `_MAJOR_TOOL_STATUS`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_agent_tools.py`
Expected: PASS

**Step 5: Commit**
```bash
git add network_manager/ai_agent.py
git commit -m "feat: implement delete_gns3_node tool function"
```

---

### Task 7: Implement `connect_gns3_nodes` and `delete_gns3_link` tools

**Files:**
- Modify: `network_manager/ai_agent.py`

**Step 1: Write failing test**
Ensure tool functions are defined in `ALL_TOOLS` and verify failures on bad parameters.

**Step 2: Run test to verify it fails**
Run: `python scratch/test_agent_tools.py`
Expected: FAIL

**Step 3: Write minimal implementation**
1. Implement `connect_gns3_nodes`:
   ```python
   def connect_gns3_nodes(node_a: str, port_a: str, node_b: str, port_b: str) -> str:
       """
       Connect two GNS3 nodes using specified port/interface names (e.g. Ethernet0/0).
       """
       pid = ctx.gns3_project_id
       if not pid:
           return "Error: No active GNS3 project connected."
       try:
           gns3 = ctx.get_gns3_connector()
           nodes = gns3.get_nodes(pid)
           
           id_a, id_b = "", ""
           name_a, name_b = "", ""
           for n in nodes:
               n_id = n.get("node_id")
               n_name = n.get("name", "")
               if n_id == node_a or n_name.lower() == node_a.lower():
                   id_a = n_id
                   name_a = n_name
               if n_id == node_b or n_name.lower() == node_b.lower():
                   id_b = n_id
                   name_b = n_name
           if not id_a or not id_b:
               return f"Error: Could not resolve node IDs. Node A: '{node_a}' ({'resolved' if id_a else 'missing'}), Node B: '{node_b}' ({'resolved' if id_b else 'missing'})"
               
           # Resolve port names to GNS3 numbers
           def resolve_port(node_id, device_name, target_port):
               ports = gns3.get_node_ports(pid, node_id)
               for p in ports:
                   name_l = p.get("name", "").lower()
                   short_l = p.get("short_name", "").lower()
                   target_l = target_port.lower()
                   if target_l in (name_l, short_l) or target_l.replace(" ", "") in (name_l.replace(" ", ""), short_l.replace(" ", "")):
                       return p.get("adapter_number"), p.get("port_number")
               # If not found, list ports
               avail = [f"{p.get('name')} ({p.get('short_name')})" for p in ports]
               raise RuntimeError(f"Port '{target_port}' not found on {device_name}. Available ports: {avail}")
               
           try:
               adapter_a, port_num_a = resolve_port(id_a, name_a, port_a)
               adapter_b, port_num_b = resolve_port(id_b, name_b, port_b)
           except RuntimeError as err:
               return f"Error: {err}"
               
           # Hot-plug check: stop if running, then connect
           state_a, state_b = "stopped", "stopped"
           for n in nodes:
               if n.get("node_id") == id_a:
                   state_a = n.get("status")
               if n.get("node_id") == id_b:
                   state_b = n.get("status")
                   
           stopped_a, stopped_b = False, False
           if state_a == "started":
               gns3.stop_node(pid, id_a)
               stopped_a = True
           if state_b == "started":
               gns3.stop_node(pid, id_b)
               stopped_b = True
               
           try:
               gns3.create_link(pid, id_a, adapter_a, port_num_a, id_b, adapter_b, port_num_b)
           finally:
               # Restart if stopped
               if stopped_a:
                   gns3.start_node(pid, id_a)
               if stopped_b:
                   gns3.start_node(pid, id_b)
                   
           if ctx.refresh_ui_fn:
               ctx.refresh_ui_fn()
               
           return f"Success: Connected {name_a} ({port_a}) to {name_b} ({port_b})."
       except Exception as e:
           return f"Error establishing connection: {e}"
   ```
2. Implement `delete_gns3_link`:
   ```python
   def delete_gns3_link(node_a: str, node_b: str) -> str:
       """
       Disconnect the cable/link between node_a and node_b.
       """
       pid = ctx.gns3_project_id
       if not pid:
           return "Error: No active GNS3 project connected."
       try:
           gns3 = ctx.get_gns3_connector()
           nodes = gns3.get_nodes(pid)
           
           id_a, id_b = "", ""
           name_a, name_b = "", ""
           for n in nodes:
               n_id = n.get("node_id")
               n_name = n.get("name", "")
               if n_id == node_a or n_name.lower() == node_a.lower():
                   id_a = n_id
                   name_a = n_name
               if n_id == node_b or n_name.lower() == node_b.lower():
                   id_b = n_id
                   name_b = n_name
           if not id_a or not id_b:
               return f"Error: Could not resolve node IDs. Node A: '{node_a}' ({'resolved' if id_a else 'missing'}), Node B: '{node_b}' ({'resolved' if id_b else 'missing'})"
               
           gns3.delete_link_between_nodes(pid, id_a, id_b)
           
           if ctx.refresh_ui_fn:
               ctx.refresh_ui_fn()
               
           return f"Success: Disconnected link between {name_a} and {name_b}."
       except Exception as e:
           return f"Error deleting link: {e}"
   ```
3. Register `connect_gns3_nodes` and `delete_gns3_link` in `ALL_TOOLS` and `_MAJOR_TOOL_STATUS`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_agent_tools.py`
Expected: PASS

**Step 5: Commit**
```bash
git add network_manager/ai_agent.py
git commit -m "feat: implement connect_gns3_nodes and delete_gns3_link tool functions"
```

---

### Task 8: Implement `control_gns3_node_power` tool

**Files:**
- Modify: `network_manager/ai_agent.py`

**Step 1: Write the failing test**
Ensure tool behaves correctly under mock environments.

**Step 2: Run test to verify it fails**
Run: `python scratch/test_agent_tools.py`
Expected: FAIL

**Step 3: Write minimal implementation**
1. Implement `control_gns3_node_power`:
   ```python
   def control_gns3_node_power(node_id_or_name: str, action: str) -> str:
       """
       Control node power state. Action must be 'start', 'stop', or 'restart'.
       """
       pid = ctx.gns3_project_id
       if not pid:
           return "Error: No active GNS3 project connected."
       act = action.lower().strip()
       if act not in ("start", "stop", "restart"):
           return "Error: Action must be 'start', 'stop', or 'restart'."
       try:
           gns3 = ctx.get_gns3_connector()
           nodes = gns3.get_nodes(pid)
           node_id = ""
           resolved_name = ""
           for n in nodes:
               if n.get("node_id") == node_id_or_name or n.get("name", "").lower() == node_id_or_name.lower():
                   node_id = n.get("node_id")
                   resolved_name = n.get("name")
                   break
           if not node_id:
               return f"Error: Node '{node_id_or_name}' not found."
               
           if act == "start":
               gns3.start_node(pid, node_id)
           elif act == "stop":
               gns3.stop_node(pid, node_id)
           else:
               gns3.stop_node(pid, node_id)
               import time
               time.sleep(1.0)
               gns3.start_node(pid, node_id)
               
           # Sync database state
           from network_manager.config import conn, db_lock
           with db_lock:
               cur = conn.cursor()
               cur.execute(
                   "UPDATE devices SET status=? WHERE name=?",
                   ("started" if act in ("start", "restart") else "stopped", resolved_name)
               )
               conn.commit()
               cur.close()
               
           if ctx.refresh_ui_fn:
               ctx.refresh_ui_fn()
               
           return f"Success: Node '{resolved_name}' power state set to '{action}'."
       except Exception as e:
           return f"Error changing node power: {e}"
   ```
2. Register `control_gns3_node_power` in `ALL_TOOLS` and `_MAJOR_TOOL_STATUS`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_agent_tools.py`
Expected: PASS

**Step 5: Commit**
```bash
git add network_manager/ai_agent.py
git commit -m "feat: implement control_gns3_node_power tool function"
```
