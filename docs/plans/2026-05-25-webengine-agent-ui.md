# WebEngine Agent UI Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Completely replace the current `agent_dialog.py` with a high-fidelity hybrid UI powered by `QWebEngineView`, matching the layout, typography, and visual quality of the `ancs agent refrence target.png` design.

**Architecture:** Python will act as the backend API/Worker. The UI will be entirely built in HTML/CSS/JS loaded locally into a `QWebEngineView`. Communication between the PySide6 app and the embedded web UI will be handled via `QWebChannel`, allowing Python to push real-time agent thinking, tool execution states, and markdown text to the web view.

**Tech Stack:** `PySide6`, `PySide6-WebEngine`, `HTML5/CSS3` (Vanilla CSS matching target), `Vanilla JS`, `QWebChannel`.

---

### Task 1: Install PySide6-WebEngine

**Files:**
- Modify: `requirements.txt` (or pip install directly if missing)

**Step 1: Install the WebEngine package**
Run: `pip install PySide6-WebEngine`
Wait for the installation to finish successfully.

**Step 2: Verify installation**
Run a quick Python command: `python -c "from PySide6.QtWebEngineWidgets import QWebEngineView; print('Installed successfully')"`
Expected: Prints `Installed successfully`

---

### Task 2: Build the Web Frontend Scaffold (HTML/CSS)

**Files:**
- Create: `network_manager/gui/web/index.html`
- Create: `network_manager/gui/web/style.css`
- Create: `network_manager/gui/web/app.js`

**Step 1: Write `index.html`**
Create a skeleton HTML file with a tabbed layout: A top tab bar to switch between 'Chat' (Page 1) and 'Execution Logs / Network Topology' (Page 2), matching the true Figma design. Include the `qwebchannel.js` bridge script.

**Step 2: Write `style.css`**
Implement the dark mode premium styling. Base background `#0B1018`, elevated cards `#131A24`, accent blue `#3B82F6`. Include Flexbox/CSS Grid layouts.

**Step 3: Write `app.js`**
Setup the initial JS structure and the `new QWebChannel` initialization logic that connects to the Python backend `agentBridge` object.

---

### Task 3: Create the Python WebChannel Bridge

**Files:**
- Create: `network_manager/gui/agent_bridge.py`

**Step 1: Write the `AgentBridge` class**
Subclass `QObject` and define `Slot` methods (e.g. `sendMessageFromUI`) and `Signal` properties (e.g. `messageReceived`, `toolExecutionUpdated`).

**Step 2: Wire up the CopilotWorker**
Map the signals from `CopilotWorker` (which is already emitting `chat_response_signal` and `terminal_log_signal`) so that they trigger the new `AgentBridge` signals to push data down to JS.

---

### Task 4: Replace `agent_dialog.py` QDialog with QWebEngineView

**Files:**
- Modify: `network_manager/gui/agent_dialog.py`

**Step 1: Remove all QPainter/QFrame UI code**
Delete the old `ToolCard`, `AIBubble`, `UserBubble`, and complex layouts. 

**Step 2: Implement QWebEngineView**
Instantiate a `QWebEngineView`, set its URL to the local `network_manager/gui/web/index.html`, and initialize a `QWebChannel`. Register the `AgentBridge` instance with the channel.

**Step 3: Run and test**
Run the application and open the Agent Dialog to ensure the new HTML UI loads successfully without crashing, and verify the bridge works by sending a test message.

---

### Task 5: Implement UI Polish and Streaming Animations

**Files:**
- Modify: `network_manager/gui/web/app.js`
- Modify: `network_manager/gui/web/style.css`

**Step 1: Add smooth scrolling and token streaming logic**
Enhance `app.js` to handle streaming text updates (if supported by the backend) or animate the AI bubbles sliding in. 

**Step 2: Implement Tool Execution Cards**
Add the CSS/JS to dynamically render the "running" spinner and the green "check" state when the agent is executing tools, matching the right side of the target image.
