# ANCS Agent Mockup UI Update Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Update `mockup.html` to fully implement the send button dropdown options, the execution logs tools filter dropdown, the "Allow raw config deploy" setting toggle, and the dual-tabbed Device Discovery modal.

**Architecture:** We will modify `mockup.html` directly, replacing the simple inputs and static layouts with fully interactive, styled HTML/CSS structures and JavaScript event handlers. The changes are completely self-contained in `mockup.html` and use standard CSS and Vanilla JavaScript.

**Tech Stack:** `HTML5`, `Vanilla CSS3`, `Vanilla JS`

---

### Task 1: Update Send Button Dropdown Options
Update the split send button dropdown next to the input area to contain the transport options (`Deploy via Network`, `Deploy via Serial Console`, `Run Security & Audit Scan`, `Send Chat Message`).

**Files:**
- Modify: `mockup.html` (CSS styles for `.dropdown-menu` and HTML in `.chat-input-area`)

**Step 1: Check CSS for dropdown positioning**
Ensure `.dropdown-menu` has standard dropdown styles and displays nicely above the input bar.

**Step 2: Update HTML for dropdown options**
Modify the dropdown options inside `#send-options-menu` to list:
```html
<div class="dropdown-item active" id="mode-chat" onclick="selectSendMode('chat')">
    <span class="dropdown-item-title">Send Chat Message</span>
    <span class="dropdown-item-desc">Ask questions or explain configs (Default)</span>
</div>
<div class="dropdown-item" id="mode-network" onclick="selectSendMode('network')">
    <span class="dropdown-item-title">Deploy via Network</span>
    <span class="dropdown-item-desc">Deploy configurations via SSH or Telnet</span>
</div>
<div class="dropdown-item" id="mode-serial" onclick="selectSendMode('serial')">
    <span class="dropdown-item-title">Deploy via Serial Console</span>
    <span class="dropdown-item-desc">Deploy configurations via serial console fallback</span>
</div>
<div class="dropdown-item" id="mode-audit" onclick="selectSendMode('audit')">
    <span class="dropdown-item-title">Run Security & Audit Scan</span>
    <span class="dropdown-item-desc">Check for security flaws (VTY, enable secret)</span>
</div>
```

**Step 3: Update `selectSendMode` function in JavaScript**
Modify `selectSendMode(mode)` to support the new modes, changing the main button's SVG icon, tooltip, and input placeholder.

---

### Task 2: Implement Logs Page Tools Filter Dropdown
Create a custom tool filter dropdown next to the "Clear Logs" button and write JavaScript logic to filter logs dynamically.

**Files:**
- Modify: `mockup.html` (Add CSS for `.filter-dropdown-menu`, add HTML for logs tools dropdown, and add JS filter logic)

**Step 1: Write CSS for filter dropdown**
Add style rules for `#logs-tool-filter-menu` positioned absolute below `.logs-dropdown` filter button.

**Step 2: Add HTML for tool filter menu**
Insert the HTML list containing all major tools from the codebase.

**Step 3: Write JS toggle and filtering logic**
Implement `toggleLogsFilterDropdown` and `selectLogsFilter(toolName)` to dynamically show/hide the menu, change the label, and show/hide the matching `.log-row` items based on class or text matching.

---

### Task 3: Add "Allow raw config deploy" Toggle in Settings
Insert the new toggle checkbox option inside the Model & Provider tab of the Settings modal.

**Files:**
- Modify: `mockup.html` (Tab 2 Settings Content HTML and JavaScript saveSettings/loadSettings)

**Step 1: Update settings HTML**
Insert the checkbox row under `#settings-tab-model`:
```html
<label class="checkbox-row" style="margin-top: 15px;">
    <input type="checkbox" id="settings-allow-raw-deploy">
    <span>Allow raw config deploy</span>
</label>
<span class="settings-desc">Bypass Copilot safety signatures and allow direct deployment of raw configuration text to devices.</span>
```

**Step 2: Update JS to load/save state**
Ensure `toggleSettingsModal` loads `agent_allow_raw_deploy` from global configuration/mockup settings, and `saveSettings` saves the state.

---

### Task 4: Upgrade Add Device Modal to Device Discovery Tabbed Modal
Upgrade the nested modal to a dual-tabbed layout supporting Auto Discover scanning and Manual Add.

**Files:**
- Modify: `mockup.html` (CSS styles for modal tabs, HTML for `#add-device-modal` to have tab bar, and JS to switch tabs and simulate scanning progress)

**Step 1: Write CSS for nested modal tabs**
Add styles for `.discovery-tabs`, `.discovery-tab`, and `.discovery-tab-content`.

**Step 2: Update HTML structure**
Create a dual tab layout:
- **Auto Discover Tab**: Input row for IP scan range and SNMP community, a `Start Discovery` button, progress bar container, and table of discovered devices with action row.
- **Manual Add Tab**: Standard protocol connection form inputs.

**Step 3: Implement JS scanning simulation**
Write `startAutoDiscovery()` to show a progress bar animation, simulate scanning, and then render the discovered devices list in the table. Implement checking/unchecking checkboxes and appending selected items to the main Workspace list.

---

### Task 5: Verify Mockup Renderings
Run playwright checks to verify the visual state of the mockup pages with all dropdowns, checkboxes, and modals open.

**Files:**
- Modify: `scratch/inspect_mockup.py` or write new test script to take screenshots with settings open.

**Step 1: Write and run verification script**
Take screenshots of page 1, page 2, the settings modal with raw config checkbox visible, and the Device Discovery dialog with auto discovery scan results active.
