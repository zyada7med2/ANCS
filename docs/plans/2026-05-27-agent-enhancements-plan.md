# Agent Enhancements Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal**: Build past conversations history loading, `@` device mention autocomplete, and multi-mode (Ask Agent, Auto Approved, Planning) send functionality for the ANCS Hybrid Agent UI.

**Architecture**: Expose data tables and queries in `config.py` under the DB lock. Use `AgentBridge` slots for Python-to-JS communication (getting devices, loading history). Update `CopilotWorker` and the prompt reminder block to support Planning Mode and skip HITL confirmation under Auto Approved. Update `index.html` to render settings history tab, mention suggestions overlay, and handle input auto-switching.

**Tech Stack**: PySide6, SQLite, QWebEngineView (HTML, CSS, Vanilla JS), markdown, google-genai

---

### Task 1: Database Tables Initialization

**Files**:
- Modify: [config.py](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/config.py)
- Test: [test_improvements.py](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/tests/test_improvements.py)

**Step 1: Write the schema initialization code**
Open `network_manager/config.py` and define the creation of `chat_conversations` and `chat_messages` tables, plus the index.

```python
    # Under section "# New tables"
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        sender TEXT CHECK(sender IN ('user', 'agent', 'system')) NOT NULL,
        text TEXT NOT NULL,
        thoughts TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(conversation_id) REFERENCES chat_conversations(conversation_id) ON DELETE CASCADE
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_id ON chat_messages(conversation_id)")
```

**Step 2: Run verification test**
Run: `python -c "from network_manager.config import conn; cur=conn.cursor(); cur.execute('SELECT name FROM sqlite_master WHERE type=\'table\''); print(cur.fetchall())"`
Expected: Output contains `('chat_conversations',)` and `('chat_messages',)`

**Step 3: Commit**
```bash
git add network_manager/config.py
git commit -m "feat: initialize database tables for chat conversations"
```

---

### Task 2: Expose Python slots in Agent Bridge

**Files**:
- Modify: [agent_bridge.py](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/gui/agent_bridge.py)

**Step 1: Add DB logic and Slots for conversation list, load, delete, and devices list**
Modify `network_manager/gui/agent_bridge.py` to add:

```python
    @Slot(result=str)
    def getPastConversations(self):
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                cur = conn.cursor()
                cur.execute("SELECT conversation_id, title, created_at FROM chat_conversations ORDER BY created_at DESC")
                rows = cur.fetchall()
                cur.close()
            return json.dumps([{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows])
        except Exception as e:
            return json.dumps([])

    @Slot(str)
    def deleteConversation(self, conversation_id):
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                cur = conn.cursor()
                cur.execute("DELETE FROM chat_conversations WHERE conversation_id = ?", (conversation_id,))
                conn.commit()
                cur.close()
            if getattr(self._dialog, '_current_conversation_id', None) == conversation_id:
                self._dialog._current_conversation_id = None
                self.clearChat()
        except Exception as e:
            print(f"Error deleting conversation: {e}")

    @Slot(str)
    def loadConversation(self, conversation_id):
        try:
            from network_manager.config import conn, db_lock
            from network_manager.ai_agent import SYSTEM_PROMPT
            with db_lock:
                cur = conn.cursor()
                cur.execute("SELECT sender, text, thoughts FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,))
                rows = cur.fetchall()
                cur.close()

            chat_data = []
            history = []
            history.append({"role": "system", "content": SYSTEM_PROMPT})

            for sender, text, thoughts_json in rows:
                thoughts = []
                if thoughts_json:
                    try:
                        thoughts = json.loads(thoughts_json)
                    except Exception:
                        pass
                chat_data.append({
                    "type": "user" if sender == "user" else "ai" if sender == "agent" else "system",
                    "text": text,
                    "thoughts": thoughts
                })
                if sender == "user":
                    history.append({"role": "user", "content": text})
                elif sender == "agent":
                    history.append({"role": "assistant", "content": text})

            self._dialog._current_conversation_id = conversation_id
            self.app._copilot_chat_data = chat_data
            self.app._copilot_history = history

            # Restart the worker
            self._dialog._stop_worker()
            self._dialog._launch_agent()

            # Tell QWebEngine to render replayed logs
            self._dialog._web.page().runJavaScript("clearAndReplayChat();")
        except Exception as e:
            print(f"Error loading conversation: {e}")

    @Slot(result=str)
    def getDevicesList(self):
        if not hasattr(self.app, 'devices'):
            return json.dumps([])
        
        dev_list = []
        for name, model, meta in self.app.devices:
            # Determine type
            lower_name = name.lower()
            if "switch" in lower_name or "esw" in lower_name or "sw" in lower_name:
                dev_type = "switch"
            else:
                dev_type = "router"
            dev_list.append({"name": name, "type": dev_type})
        return json.dumps(dev_list)
```

**Step 2: Modify `sendMessage` to support device mentions, create conversations dynamically, and save messages**
Modify `sendMessage(self, text, mode)` inside `AgentBridge`:

```python
    @Slot(str, str)
    def sendMessage(self, text, mode):
        text = text.strip()
        if not text:
            return

        self._dialog._user_has_sent = True
        self._dialog._current_mode = mode

        # Resolve Current Conversation ID
        conv_id = getattr(self._dialog, '_current_conversation_id', None)
        from network_manager.config import conn, db_lock
        if not conv_id:
            import time
            conv_id = f"chat_{int(time.time())}"
            self._dialog._current_conversation_id = conv_id
            title = text[:40] + ("..." if len(text) > 40 else "")
            with db_lock:
                cur = conn.cursor()
                cur.execute("INSERT INTO chat_conversations (conversation_id, title) VALUES (?, ?)", (conv_id, title))
                conn.commit()
                cur.close()

        # Save User Message to DB
        with db_lock:
            cur = conn.cursor()
            cur.execute("INSERT INTO chat_messages (conversation_id, sender, text, thoughts) VALUES (?, ?, ?, ?)",
                        (conv_id, "user", text, json.dumps([])))
            conn.commit()
            cur.close()

        # Add to local app cache for replay
        if not hasattr(self.app, '_copilot_chat_data'):
            self.app._copilot_chat_data = []
        self.app._copilot_chat_data.append({"type": "user", "text": text})

        self.setThinking.emit(True, "Processing...")

        # `@` Mentions Resolution & Context Prepending
        augmented_text = text
        mentions = re.findall(r'@(\w+)', text)
        if mentions:
            context_blocks = []
            for dev_name in mentions:
                dev_info = self._get_device_info_for_mention(dev_name)
                if dev_info:
                    context_blocks.append(dev_info)
            if context_blocks:
                augmented_text = "\n\n".join(context_blocks) + "\n\nUser Message:\n" + text

        # Queue message to the CopilotWorker
        worker = getattr(self.app, '_copilot_worker', None)
        if worker and worker.isRunning():
            worker.queue_message(augmented_text)
        else:
            self._dialog._launch_agent()
            QTimer.singleShot(1500, lambda: self._delayed_send(augmented_text))
```
Add the helper method `_get_device_info_for_mention(self, dev_name)`:
```python
    def _get_device_info_for_mention(self, dev_name):
        if not hasattr(self.app, 'devices'):
            return None
        matched_dev = None
        for name, model, meta in self.app.devices:
            if name.lower() == dev_name.lower():
                matched_dev = (name, model, meta)
                break
        if not matched_dev:
            return None
        name, model, meta = matched_dev
        config_content = "No saved configuration found in database."
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                cur = conn.cursor()
                cur.execute(
                    "SELECT content FROM configs WHERE device_id = (SELECT id FROM devices WHERE name = ?)",
                    (name,)
                )
                row = cur.fetchone()
                if row:
                    config_content = row[0]
                cur.close()
        except Exception:
            pass
        platform = getattr(model, "platform", "Cisco IOS") if model else "Cisco IOS"
        return f"""<mentioned-device name="{name}">
Platform: {platform}
Connection: {meta.get("console_host", "N/A")}:{meta.get("console_port", "N/A")}
Saved Configuration:
```
{config_content}
```
</mentioned-device>"""
```

**Step 3: Commit**
```bash
git add network_manager/gui/agent_bridge.py
git commit -m "feat: add slot methods and mentions parsing to AgentBridge"
```

---

### Task 3: Modify CopilotWorker & Safety Rails in python backend

**Files**:
- Modify: [ai_agent.py](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/ai_agent.py)
- Modify: [agent_dialog.py](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/gui/agent_dialog.py)

**Step 1: Pass mode in ANCSAgentDialog to CopilotWorker**
In `network_manager/gui/agent_dialog.py`, initialize `self._current_conversation_id = None` and `self._current_mode = "chat"` inside `__init__`.
In `_launch_agent(self)`, pass `self._current_mode` to `CopilotWorker` constructor:
```python
        self.app._copilot_worker = CopilotWorker(
            ...
            initial_messages=self.app._copilot_history,
            mode=getattr(self, '_current_mode', 'chat')
        )
```
In `_on_chat_response(self, text)`, save the response to DB:
```python
        if getattr(self, '_current_conversation_id', None):
            try:
                from network_manager.config import conn, db_lock
                with db_lock:
                    cur = conn.cursor()
                    cur.execute("INSERT INTO chat_messages (conversation_id, sender, text, thoughts) VALUES (?, ?, ?, ?)",
                                (self._current_conversation_id, "agent", text, json.dumps(list(self._current_thoughts))))
                    conn.commit()
                    cur.close()
            except Exception as e:
                print(f"Error saving AI message: {e}")
```

**Step 2: Update CopilotWorker constructor & run loop to check mode**
In `network_manager/ai_agent.py`, update `CopilotWorker.__init__` parameter signature to add `mode: str = "chat"`. Save it to `self.mode = mode`.
Inside `CopilotWorker.run()` setting up context:
```python
        ctx.auto_approve = (self.mode == "auto_approve")
```
Inside `generate_and_deploy_device_config` and `deploy_to_device` (if used), skip dialog:
```python
    if getattr(ctx, 'auto_approve', False):
        ctx.log(f"<span style='color:#3fb950'>[Copilot] Auto-approve mode active. Skipping deploy confirmation dialog.</span>\n")
        approved = True
        final_commands = commands
    else:
        approved, final_commands = request_deploy_approval(hostname, device_role, commands)
```
Inside `_build_system_reminder(self)`, append Claude XML directives if `self.mode == "planning"`:
```python
        reminder_str = (
            "<system-reminder>\n"
            "CRITICAL RULES — ACTIVE FOR THIS TURN:\n"
            "1. NEVER write IOS commands in your response. Call generate_and_deploy_device_config() or generate_device_config().\n"
            "2. If a deployment was REJECTED by user, do NOT retry. Acknowledge and move on.\n"
            "3. NEVER guess interface names. Call get_topology_links() to verify physical connections first.\n"
            "4. Switches NEVER get routing protocols. routing_protocol='none' for core and access switches.\n"
            f"5. You have {rejected_count} rejected device(s) this session: {rejected_list}. Do NOT deploy to them again.\n"
            f"6. Session tool calls so far: {ctx.tool_call_count}/200.\n"
        )
        if self.mode == "planning":
            reminder_str += (
                "\n<planning-mode-directives>\n"
                "YOU MUST FOLLOW THESE PLANNING INSTRUCTIONS:\n"
                "1. Since you are in PLANNING MODE, you are forbidden from invoking any configuration or deployment tools on this turn.\n"
                "2. You must think step-by-step and write out a detailed, structured implementation plan in your response.\n"
                "3. Your plan must list:\n"
                "   - Involved devices\n"
                "   - Commands to be executed\n"
                "   - Order of operations\n"
                "   - Risks and verification checks\n"
                "4. End your response by asking the user to review the plan and confirm execution.\n"
                "</planning-mode-directives>\n"
            )
        reminder_str += "</system-reminder>"
        return reminder_str
```

**Step 3: Commit**
```bash
git add network_manager/ai_agent.py network_manager/gui/agent_dialog.py
git commit -m "feat: wire sending modes, auto approve bypass, and planning mode prompt block"
```

---

### Task 4: HTML Settings Dialog, `@` mentions, and Mode switching

**Files**:
- Modify: [index.html](file:///c:/Users/Zyad/Downloads/ANCS/network_manager/gui/web/index.html)

**Step 1: Replace Dropdown Menu options in `index.html`**
Find `<div class="dropdown-menu" id="send-options-menu">` and replace the options:
```html
                <div class="dropdown-menu" id="send-options-menu">
                    <div class="dropdown-item active" id="mode-chat" onclick="selectSendMode('chat')">
                        <span class="dropdown-item-title">Ask Agent (Default)</span>
                        <span class="dropdown-item-desc">Require confirmation before deploying configurations</span>
                    </div>
                    <div class="dropdown-item" id="mode-auto" onclick="selectSendMode('auto_approve')">
                        <span class="dropdown-item-title">Auto Approved</span>
                        <span class="dropdown-item-desc">Deploy configurations automatically without confirmation</span>
                    </div>
                    <div class="dropdown-item" id="mode-planning" onclick="selectSendMode('planning')">
                        <span class="dropdown-item-title">Planning Mode</span>
                        <span class="dropdown-item-desc">Agent formulates a detailed step-by-step plan before execution</span>
                    </div>
                </div>
```

**Step 2: Add New Chat and History toggle button to Header**
Add `+` (New Chat) next to Settings gear:
```html
            <!-- New Chat -->
            <button class="window-btn" title="New Chat" onclick="startNewChat()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            </button>
```

**Step 3: Implement Settings History tab nav item & pane**
In the settings sidebar `<div class="settings-nav">`, add:
```html
                    <div class="settings-nav-item" id="settings-nav-history" onclick="switchSettingsTab('history')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3"></path><path d="M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5"></path></svg>
                        <span>Chat History</span>
                    </div>
```
In the settings content container, add the corresponding tab content pane:
```html
                <!-- TAB 6: CHAT HISTORY -->
                <div class="settings-tab-content" id="settings-tab-history">
                    <h3 class="settings-tab-title">Chat History</h3>
                    <div class="device-table-card" style="max-height: 400px; flex: 1;">
                        <table class="device-table">
                            <thead>
                                <tr>
                                    <th>Conversation</th>
                                    <th>Created At</th>
                                    <th style="width: 150px; text-align: center;">Actions</th>
                                </tr>
                            </thead>
                            <tbody id="settings-history-tbody">
                                <!-- Populated dynamically -->
                            </tbody>
                        </table>
                    </div>
                    <div class="settings-actions">
                        <button class="settings-btn secondary" onclick="toggleSettingsModal()">Close</button>
                    </div>
                </div>
```

**Step 4: Implement JS Autocomplete, Replaying, Loading, and Auto-Switching**
Define functions in the script tag of `index.html`:
```javascript
        // Replay chat history callback
        window.clearAndReplayChat = function() {
            const chatHistory = document.querySelector('.chat-history');
            if (chatHistory) {
                chatHistory.innerHTML = '';
            }
            if (window.bridge) {
                // Re-run bridge history replay
                window.bridge.sendMessage("", "replay_history"); 
            }
        };

        // Render history in settings tab
        function loadHistorySettings() {
            if (!window.bridge) return;
            const tbody = document.getElementById('settings-history-tbody');
            if (!tbody) return;

            window.bridge.getPastConversations(function(res) {
                const conversations = JSON.parse(res);
                if (conversations.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; color:var(--text-muted);">No saved chat history.</td></tr>`;
                    return;
                }
                let html = '';
                conversations.forEach(c => {
                    html += `
                        <tr>
                            <td><strong>${_escapeHtml(c.title)}</strong></td>
                            <td style="color:var(--text-sec);">${c.created_at}</td>
                            <td style="text-align:center;">
                                <button class="settings-btn primary" style="padding: 4px 10px; font-size:11px; margin-right: 6px;" onclick="loadPastConversation('${c.id}')">Load</button>
                                <button class="settings-btn secondary" style="padding: 4px 10px; font-size:11px; color:#EF4444; border-color:rgba(239, 68, 68, 0.2);" onclick="deletePastConversation('${c.id}')">Delete</button>
                            </td>
                        </tr>
                    `;
                });
                tbody.innerHTML = html;
            });
        }

        window.loadPastConversation = function(id) {
            if (window.bridge) {
                window.bridge.loadConversation(id);
                toggleSettingsModal();
                switchTab('chat');
            }
        };

        window.deletePastConversation = function(id) {
            if (window.bridge && confirm("Are you sure you want to delete this conversation?")) {
                window.bridge.deleteConversation(id);
                loadHistorySettings();
            }
        };

        window.startNewChat = function() {
            if (window.bridge && confirm("Start a new chat session? Current session is saved in History.")) {
                window.bridge.clearChat();
                // Reset conversation ID on bridge/dialog
                window.bridge.sendMessage("", "new_session");
                window.clearAndReplayChat();
            }
        };

        // Hook up history load on Settings tab click
        const origSwitchSettingsTab = switchSettingsTab;
        window.switchSettingsTab = function(tabName) {
            origSwitchSettingsTab(tabName);
            if (tabName === 'history') {
                loadHistorySettings();
            }
        };

        // Autocomplete Mention box elements
        let mentionDevices = [];
        let mentionActive = false;
        let mentionQueryStart = -1;

        // Fetch devices on load
        function fetchMentionDevices() {
            if (window.bridge && window.bridge.getDevicesList) {
                window.bridge.getDevicesList(function(res) {
                    mentionDevices = JSON.parse(res);
                });
            }
        }
        
        // Add mention dropdown HTML dynamically if not present
        function setupMentionUI() {
            const container = document.querySelector('.chat-input-area');
            if (container && !document.getElementById('mention-dropdown')) {
                const div = document.createElement('div');
                div.id = 'mention-dropdown';
                div.className = 'dropdown-menu';
                div.style.cssText = 'position:absolute; bottom:60px; left:20px; width:220px; display:none; max-height:180px; overflow-y:auto; z-index:100; box-shadow:0 10px 25px rgba(0,0,0,0.6);';
                container.appendChild(div);
            }
        }

        // Listen on input for autocomplete and auto-switching
        document.addEventListener('DOMContentLoaded', function() {
            setupMentionUI();
            setTimeout(fetchMentionDevices, 1000);

            const input = document.getElementById('chat-text-input');
            if (input) {
                input.addEventListener('input', function(e) {
                    const text = input.value;
                    const pos = input.selectionStart;
                    
                    // Auto-switching intent detection
                    const lowerText = text.toLowerCase();
                    if (lowerText.includes("auto approve") || lowerText.includes("auto-approve") || lowerText.includes("approve automatically")) {
                        if (_currentSendMode !== 'auto_approve') {
                            selectSendMode('auto_approve');
                            showToast("Switched to Auto Approved Mode");
                        }
                    }

                    // Autocomplete detection
                    const wordStart = text.lastIndexOf(' ', pos - 1) + 1;
                    const currentWord = text.substring(wordStart, pos);
                    
                    if (currentWord.startsWith('@')) {
                        mentionActive = true;
                        mentionQueryStart = wordStart + 1;
                        showMentionDropdown(currentWord.substring(1));
                    } else {
                        hideMentionDropdown();
                    }
                });

                input.addEventListener('keydown', function(e) {
                    if (mentionActive) {
                        const dropdown = document.getElementById('mention-dropdown');
                        const activeItem = dropdown.querySelector('.dropdown-item.active');
                        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                            e.preventDefault();
                            const items = Array.from(dropdown.querySelectorAll('.dropdown-item'));
                            if (items.length === 0) return;
                            let idx = items.indexOf(activeItem);
                            if (e.key === 'ArrowDown') idx = (idx + 1) % items.length;
                            else idx = (idx - 1 + items.length) % items.length;
                            items.forEach(item => item.classList.remove('active'));
                            items[idx].classList.add('active');
                            items[idx].scrollIntoView({ block: 'nearest' });
                        } else if (e.key === 'Enter') {
                            e.preventDefault();
                            if (activeItem) {
                                activeItem.click();
                            }
                        } else if (e.key === 'Escape') {
                            e.preventDefault();
                            hideMentionDropdown();
                        }
                    }
                });
            }
        });

        function showMentionDropdown(query) {
            const dropdown = document.getElementById('mention-dropdown');
            if (!dropdown) return;

            const filtered = mentionDevices.filter(d => d.name.toLowerCase().includes(query.toLowerCase()));
            if (filtered.length === 0) {
                dropdown.style.display = 'none';
                return;
            }

            let html = '';
            filtered.forEach((d, idx) => {
                const iconSvg = d.type === 'switch' 
                    ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px;"><rect x="2" y="6" width="20" height="12" rx="2" ry="2"></rect><line x1="6" y1="12" x2="6.01" y2="12"></line><line x1="10" y1="12" x2="10.01" y2="12"></line><line x1="14" y1="12" x2="14.01" y2="12"></line></svg>`
                    : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 8 8 12 12 16"></polyline><polyline points="16 12 12 12"></polyline></svg>`;

                html += `
                    <div class="dropdown-item ${idx === 0 ? 'active' : ''}" onclick="insertMention('${d.name}')">
                        ${iconSvg}
                        <span class="dropdown-item-title">${d.name}</span>
                    </div>
                `;
            });
            dropdown.innerHTML = html;
            dropdown.style.display = 'flex';
        }

        function hideMentionDropdown() {
            const dropdown = document.getElementById('mention-dropdown');
            if (dropdown) {
                dropdown.style.display = 'none';
            }
            mentionActive = false;
        }

        window.insertMention = function(name) {
            const input = document.getElementById('chat-text-input');
            const text = input.value;
            const pos = input.selectionStart;
            const before = text.substring(0, mentionQueryStart - 1);
            const after = text.substring(pos);
            input.value = before + '@' + name + ' ' + after;
            input.focus();
            const newPos = mentionQueryStart + name.length + 1;
            input.setSelectionRange(newPos, newPos);
            hideMentionDropdown();
        };

        // Modern Toast Notification helper
        function showToast(message) {
            let toast = document.getElementById('toast-notification');
            if (!toast) {
                toast = document.createElement('div');
                toast.id = 'toast-notification';
                toast.style.cssText = 'position:fixed; top:20px; right:20px; background:rgba(37,99,235,0.9); backdrop-filter:blur(8px); color:white; padding:12px 24px; border-radius:6px; border:1px solid rgba(255,255,255,0.15); box-shadow:0 10px 30px rgba(0,0,0,0.5); font-size:13px; font-weight:600; z-index:9999; opacity:0; transition:opacity 0.3s; pointer-events:none;';
                document.body.appendChild(toast);
            }
            toast.textContent = message;
            toast.style.opacity = '1';
            setTimeout(() => {
                toast.style.opacity = '0';
            }, 3000);
        }
```

Add CSS styles:
```css
        .dropdown-item {
            padding: 8px 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            transition: background 0.15s;
        }
        .dropdown-item:hover, .dropdown-item.active {
            background: rgba(255, 255, 255, 0.05);
        }
```

**Step 5: Commit**
```bash
git add network_manager/gui/web/index.html
git commit -m "feat: add HTML elements and JS controls for history, autocomplete, modes, and switching"
```
