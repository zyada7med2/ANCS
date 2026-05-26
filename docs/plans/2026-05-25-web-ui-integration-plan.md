# Web UI Integration Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Replace the complex widget-based `AgentDialog` UI with a premium HTML/CSS `QWebEngineView` dialog, powered by a bidirectional `QWebChannel` communication bridge (`AgentBridge`).

**Architecture:** The PySide6 Python backend will run the async network automation tools and Gemini agent logic, pushing status changes, thinking logs, and chat messages to a `QWebEngineView` via `QWebChannel`. The web view (running our polished `mockup.html`) will send user prompts, settings updates, and manual triggers back to Python.

**Tech Stack:** PySide6, PySide6-WebEngine (`QWebEngineView`, `QWebChannel`), HTML/Vanilla CSS/JavaScript.

---

### Task 1: Environment & File Prep

**Files:**
- Modify: `requirements.txt`
- Create: `network_manager/gui/web/`
- Create: `network_manager/gui/web/index.html` (copied from `mockup.html`)
- Create: `network_manager/gui/web/qwebchannel.js` (Qt QWebChannel client library)

**Step 1: Update python requirements**
- Add `PySide6-WebEngine` dependency to `requirements.txt`.
- Run: `pip install PySide6-WebEngine`

**Step 2: Copy assets to the web package**
- Copy `mockup.html` into `network_manager/gui/web/index.html`.
- Save standard Qt `qwebchannel.js` file into `network_manager/gui/web/qwebchannel.js`.

---

### Task 2: Create the Python-to-Web Bridge

**Files:**
- Create: `network_manager/gui/agent_bridge.py`

**Step 1: Write AgentBridge class**
- Inherit from `QObject`.
- Define backend-to-frontend Signals:
  - `addMessageSignal(sender, content, timestamp)`
  - `addToolLogSignal(time, type, name, description, status)`
  - `updateDevicePillsSignal(json_devices_list)`
  - `updateModelBadgeSignal(model_name)`
  - `setSettingsSignal(provider, model, apiKey, allowRaw)`
- Define frontend-to-backend Slots:
  - `submitMessage(text, mode)`: User typed a prompt and clicked send.
  - `saveSettings(provider, model, apiKey, allowRaw)`: User updated settings dialog.
  - `switchTab(tabName)`: User switched main navigation tab.
  - `addDeviceManual(ip, port, proto, username, password)`: User completed device discovery.

---

### Task 3: Replace AgentDialog UI with QWebEngineView

**Files:**
- Modify: `network_manager/gui/agent_dialog.py`

**Step 1: Import PySide6.QtWebEngineWidgets & QtWebChannel**
- Import `QWebEngineView` and `QWebChannel`.

**Step 2: Reconstruct AgentDialog Layout**
- Replace the 2500 lines of custom Qt UI widgets in `AgentDialog.__init__` with a single `QVBoxLayout` hosting `QWebEngineView`.
- Initialize `QWebChannel` and register `AgentBridge` instance.
- Load `network_manager/gui/web/index.html`.

---

### Task 4: Connect WebChannel in HTML Frontend

**Files:**
- Modify: `network_manager/gui/web/index.html`

**Step 1: Load qwebchannel.js**
- Add `<script src="qwebchannel.js"></script>` in the head.

**Step 2: Hook WebChannel events to DOM**
- Implement `new QWebChannel(qt.webChannelTransport, function(channel) { window.pyBridge = channel.objects.pyBridge; ... })`.
- Wire incoming Python signals to functions that dynamically insert chat messages, update the tool dropdowns, update logs tables, and render device status pills.
- Rewrite UI input events (Send button, settings form submission, add device modal) to invoke Python slots on `window.pyBridge`.

---

### Task 5: Integrate Agent Events & Testing

**Files:**
- Modify: `network_manager/gui/agent_dialog.py`
- Modify: `network_manager/gui/main.py` (if needed to connect MainWindow context)

**Step 1: Pipe ai_agent events to the bridge**
- Listen to real backend agent actions (tool start, tool completion, agent responses) and trigger `addToolLogSignal` / `addMessageSignal` calls.

**Step 2: Verify UI and interaction**
- Run `python run.py`.
- Verify chat input, thinking logs, settings synchronization, and tool logs render successfully within the new high-fidelity interface.
