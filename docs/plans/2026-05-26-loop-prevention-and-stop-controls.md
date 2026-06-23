# AI Agent Tool Loop Prevention, Stop Button, and Chat Export Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Intercept and prevent infinite tool-calling loops, add a UI Stop button to abort queries instantly, and expose a chat export button in Settings.

**Architecture:**
1. **Loop Guard:** Track tool invocations (`(fn_name, fn_args)`) within each conversation turn in `CopilotWorker`. Intercept duplicate calls and feed back a loop-prevention error instructing the model to report the issue.
2. **Stop Button:** Transform the Web UI send button to a RED stop button when the agent is thinking. Clicking it stops the worker QThread and restarts a fresh one.
3. **Chat Export:** Embed an "Export Chat Logs" button in the General Settings modal tab inside `index.html` linked to the Python bridge.

**Tech Stack:** PySide6 (Qt6), QWebChannel, JavaScript, HTML5, CSS3

---

### Task 1: Implement Tool Loop Guard & Stop Handler in ai_agent.py

**Files:**
- Modify: `network_manager/ai_agent.py`

**Step 1: Update `_process_response_gemini` to track tool calls**
Track duplicates and check `self._running` inside `_process_response_gemini` around line 2712:
```python
    def _process_response_gemini(self, response):
        """Handle the agentic tool-calling loop and return final text."""
        MAX_TURNS = 10
        turn_tool_calls = set()
        for turn in range(MAX_TURNS):
            if not self._running:
                break
            function_calls = []
            ...
            function_responses = []
            for fc in function_calls:
                fn_name = fc.name
                fn_args = dict(fc.args) if fc.args else {}

                # Track duplicate tool calls to prevent loops
                call_key = (fn_name, json.dumps(fn_args, sort_keys=True))
                if call_key in turn_tool_calls:
                    result = f"Error: Tool loop detected. You have already called {fn_name} with these arguments in this turn. Do not retry. Report this failure/state to the user immediately."
                    ctx.log(f"<span style='color:#d29922'>[Copilot] Loop prevented: {fn_name} called again with same args</span>\n")
                else:
                    turn_tool_calls.add(call_key)
                    t0 = time.monotonic()
                    ...
```

**Step 2: Update `_process_response_openrouter`, `_execute_single_tool` & `_execute_tools_parallel` to track tool calls**
Pass `turn_tool_calls` down to intercept duplicates:
```python
    def _process_response_openrouter(self, response):
        """Handle the agentic tool-calling loop (OpenAI format) and return final text."""
        MAX_TURNS = 10
        turn_tool_calls = set()
        for turn in range(MAX_TURNS):
            if not self._running:
                break
            message = response.choices[0].message
            ...
            tool_calls = message.tool_calls
            if len(tool_calls) == 1:
                tc = tool_calls[0]
                result_str = self._execute_single_tool(tc, turn_tool_calls)
                ...
            else:
                results = self._execute_tools_parallel(tool_calls, turn_tool_calls)
```

Inside `_execute_single_tool`:
```python
    def _execute_single_tool(self, tc, turn_tool_calls=None):
        """Execute a single tool call and return the result string."""
        fn_name = tc.function.name
        try:
            fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except json.JSONDecodeError:
            fn_args = {}
            ctx.log(f"<span style='color:#d29922'>[Copilot] Warning: bad JSON args for {fn_name}</span>\n")

        if turn_tool_calls is not None:
            call_key = (fn_name, json.dumps(fn_args, sort_keys=True))
            if call_key in turn_tool_calls:
                ctx.log(f"<span style='color:#d29922'>[Copilot] Loop prevented: {fn_name} called again with same args</span>\n")
                return f"Error: Tool loop detected. You have already called {fn_name} with these arguments in this turn. Do not retry. Report this failure/state to the user immediately."
            turn_tool_calls.add(call_key)
        ...
```

Inside `_execute_tools_parallel`:
```python
    def _execute_tools_parallel(self, tool_calls, turn_tool_calls=None):
        ...
        def _run_one(tc, stagger_delay=0.0):
            if stagger_delay > 0:
                time.sleep(stagger_delay)
            return tc.id, self._execute_single_tool(tc, turn_tool_calls)
```

---

### Task 2: Implement stopAgent Slot in AgentBridge

**Files:**
- Modify: `network_manager/gui/agent_bridge.py`

**Step 1: Add `stopAgent` Slot**
Expose the slot to JavaScript:
```python
    @Slot()
    def stopAgent(self):
        """Forcefully stops the current worker thread and restarts a clean one."""
        self._dialog._stop_worker()
        self._dialog._launch_agent()
        self.setThinking.emit(False, "")
        self.addChatMessage.emit("system", "Process stopped by user.", "")
```

---

### Task 3: Implement Web UI Stop Button and Settings Export Controls

**Files:**
- Modify: `network_manager/gui/web/index.html`

**Step 1: Update `_showThinking(active, label)`**
When `active` is true, transform the send button into a RED stop button that triggers `triggerStop()`. When `active` is false, restore it.
```javascript
        function _showThinking(active, label) {
            let thinkingEl = document.getElementById('bridge-thinking');
            const sendBtn = document.getElementById('send-mode-btn');
            const dropdownBtn = document.querySelector('.split-btn-dropdown');
            
            if (active) {
                if (!thinkingEl) {
                    const chatHistory = document.querySelector('.chat-history');
                    if (!chatHistory) return;
                    thinkingEl = document.createElement('div');
                    thinkingEl.id = 'bridge-thinking';
                    thinkingEl.className = 'loading-status-container';
                    thinkingEl.innerHTML = `
                        <div class="bouncing-dots"><span></span><span></span><span></span></div>
                        <span id="bridge-thinking-label">${_escapeHtml(label || 'Processing...')}</span>
                    `;
                    chatHistory.appendChild(thinkingEl);
                    chatHistory.scrollTop = chatHistory.scrollHeight;
                } else {
                    const lbl = document.getElementById('bridge-thinking-label');
                    if (lbl) lbl.textContent = label || 'Processing...';
                }
                
                // Transform into RED Stop Process button
                if (sendBtn) {
                    sendBtn.title = "Stop Agent Process";
                    sendBtn.setAttribute('onclick', 'triggerStop()');
                    sendBtn.style.background = 'rgba(239, 68, 68, 0.2)';
                    sendBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                    sendBtn.style.color = '#f87171';
                    sendBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect></svg>`;
                }
                if (dropdownBtn) {
                    dropdownBtn.style.pointerEvents = 'none';
                    dropdownBtn.style.opacity = '0.4';
                }
            } else {
                if (thinkingEl) thinkingEl.remove();
                
                if (sendBtn) {
                    sendBtn.style.background = '';
                    sendBtn.style.borderColor = '';
                    sendBtn.style.color = '';
                    sendBtn.setAttribute('onclick', 'triggerSend()');
                }
                if (dropdownBtn) {
                    dropdownBtn.style.pointerEvents = 'auto';
                    dropdownBtn.style.opacity = '1';
                }
                selectSendMode(_currentSendMode || 'chat');
                ...
            }
        }
```

**Step 2: Add `triggerStop` and `exportChatConversation` JS Functions**
Add them inside the scripts block in `index.html` around line 3030:
```javascript
        function triggerStop() {
            _showThinking(true, 'Stopping process...');
            if (window.bridge && window.bridge.stopAgent) {
                window.bridge.stopAgent();
            }
        }

        function exportChatConversation() {
            if (window.bridge && window.bridge.exportLogs) {
                window.bridge.exportLogs();
            }
        }
```

**Step 3: Embed Export Button in General Settings Layout**
At line 2021 inside `settings-actions`, add the export button:
```html
                    <div class="settings-actions" style="display: flex; width: 100%;">
                        <button class="settings-btn secondary" onclick="exportChatConversation()" style="margin-right: auto; background: rgba(52, 211, 153, 0.1); border: 1px solid rgba(52, 211, 153, 0.2); color: #34d399;">Export Chat Logs</button>
                        <button class="settings-btn secondary" onclick="toggleSettingsModal()">Cancel</button>
                        <button class="settings-btn primary" onclick="saveSettings()">Save Changes</button>
                    </div>
```

---

### Task 4: Run Application & Verify Features

**Files:**
- Verification: `run.py`

**Step 1: Start the application**
Run command: `.venv\Scripts\python.exe run.py`

**Step 2: Test features**
- Ask the agent a command. When it starts thinking, confirm the Send button turns red with a stop icon. Click it and confirm it stops immediately.
- Open Settings dialog and click **Export Chat Logs** at the bottom-left of General tab. Confirm QFileDialog launches and successfully exports conversation to a text file.
