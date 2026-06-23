# Chat History UI/UX Overhaul Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Overhaul the Chat History tab in settings with a stunning glassmorphic card grid, real-time search, inline renaming, and a sliding Quick Preview drawer.

**Architecture:** We will extend the Python backend `AgentBridge` class with slots for fetching a conversation's messages and executing dynamic title updates. The HTML UI in `index.html` will be enhanced with modern CSS grid layouts, CSS sliding panel transitions, and robust client-side event loops that communicate over the QWebChannel bridge.

**Tech Stack:** PySide6 (Qt 6 WebEngine), QWebChannel, SQLite (WAL mode), HTML5, JavaScript (ES6+), Vanilla CSS (Glassmorphism & Flexbox).

---

### Task 1: Extend Python AgentBridge Slots

**Files:**
- Modify: `network_manager/gui/agent_bridge.py:351-409`
- Test: `network_manager/tests/test_improvements.py`

**Step 1: Write the failing test**
Create a new section `TEST 13: Chat History Bridge Slots` in `network_manager/tests/test_improvements.py` to check that the class has slots `getConversationMessages` and `renameConversation` and that `getPastConversations` returns the message count and list of device mentions.

```python
# Insert after lines 364 in test_improvements.py:
print("\n" + "="*60)
print("TEST 13: Chat History Bridge Slots")
print("="*60)

with open("network_manager/gui/agent_bridge.py", encoding="utf-8") as f:
    bridge_src = f.read()

test("getConversationMessages defined", "def getConversationMessages(" in bridge_src)
test("renameConversation defined", "def renameConversation(" in bridge_src)
test("Enriched getPastConversations regex", "re.findall(" in bridge_src and "message_count" in bridge_src)
```

**Step 2: Run test to verify it fails**
Run: `python network_manager/tests/test_improvements.py`
Expected: FAIL due to missing slot definitions in `agent_bridge.py`.

**Step 3: Write minimal implementation in `agent_bridge.py`**
Replace `getPastConversations` and add `getConversationMessages` and `renameConversation` in `network_manager/gui/agent_bridge.py`.

*Target original code:*
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
```

*Replacement code:*
```python
    @Slot(result=str)
    def getPastConversations(self):
        try:
            from network_manager.config import conn, db_lock
            import re
            with db_lock:
                cur = conn.cursor()
                cur.execute("SELECT conversation_id, title, created_at FROM chat_conversations ORDER BY created_at DESC")
                conversations = cur.fetchall()
                
                enriched_list = []
                for conv_id, title, created_at in conversations:
                    # Message count
                    cur.execute("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?", (conv_id,))
                    msg_count = cur.fetchone()[0]
                    
                    # Gather unique device mentions
                    cur.execute("SELECT text FROM chat_messages WHERE conversation_id = ?", (conv_id,))
                    messages = cur.fetchall()
                    unique_mentions = set()
                    for (text,) in messages:
                        if text:
                            mentions = re.findall(r'@(\w+)', text)
                            for m in mentions:
                                unique_mentions.add(m)
                    
                    enriched_list.append({
                        "id": conv_id,
                        "title": title,
                        "created_at": created_at,
                        "message_count": msg_count,
                        "devices": sorted(list(unique_mentions))
                    })
                cur.close()
            return json.dumps(enriched_list)
        except Exception as e:
            print(f"Error in getPastConversations: {e}")
            return json.dumps([])

    @Slot(str, result=str)
    def getConversationMessages(self, conversation_id):
        try:
            from network_manager.config import conn, db_lock
            with db_lock:
                cur = conn.cursor()
                cur.execute("SELECT sender, text, thoughts, created_at FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,))
                rows = cur.fetchall()
                cur.close()
            
            messages_list = []
            for sender, text, thoughts_json, created_at in rows:
                thoughts = []
                if thoughts_json:
                    try:
                        thoughts = json.loads(thoughts_json)
                    except Exception:
                        pass
                messages_list.append({
                    "sender": sender,
                    "text": text,
                    "thoughts": thoughts,
                    "created_at": created_at
                })
            return json.dumps(messages_list)
        except Exception as e:
            print(f"Error getting conversation messages: {e}")
            return json.dumps([])

    @Slot(str, str)
    def renameConversation(self, conversation_id, new_title):
        try:
            from network_manager.config import conn, db_lock
            new_title = new_title.strip()
            if not new_title:
                return
            with db_lock:
                cur = conn.cursor()
                cur.execute("UPDATE chat_conversations SET title = ? WHERE conversation_id = ?", (new_title, conversation_id))
                conn.commit()
                cur.close()
        except Exception as e:
            print(f"Error renaming conversation: {e}")
```

**Step 4: Run test to verify it passes**
Run: `python network_manager/tests/test_improvements.py`
Expected: PASS.

**Step 5: Commit**
```bash
git add network_manager/gui/agent_bridge.py network_manager/tests/test_improvements.py
git commit -m "feat: add rename and message preview slots to AgentBridge"
```

---

### Task 2: Inject Custom Glassmorphism Styles for Cards & Preview Drawer

**Files:**
- Modify: `network_manager/gui/web/index.html:1731-1736`

**Step 1: Check existing stylesheet**
Open `network_manager/gui/web/index.html` and verify location around line 1731 (after `.device-table tr:last-child td` definition).

**Step 2: Write minimal implementation (Styles Injection)**
Insert custom style definitions:

```css
        /* Chat History Card Grid & Preview Layout */
        .history-tab-layout {
            display: flex;
            gap: 16px;
            height: 400px;
            position: relative;
            overflow: hidden;
            width: 100%;
        }

        .history-card-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 12px;
            max-height: 330px;
            overflow-y: auto;
            padding-right: 4px;
            flex: 1;
        }

        .history-card {
            position: relative;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            cursor: pointer;
            min-height: 110px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }

        .history-card:hover {
            background: rgba(255, 255, 255, 0.05);
            border-color: var(--cyan);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(6, 182, 212, 0.15);
        }

        .history-card.selected-preview {
            border-color: var(--cyan);
            background: rgba(6, 182, 212, 0.05);
        }

        .history-card-title {
            font-weight: 600;
            font-size: 13px;
            color: var(--text-pri);
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            line-height: 1.4;
            transition: color 0.2s;
        }

        .history-card-title:hover {
            color: var(--cyan);
        }

        .device-pill {
            font-size: 9px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 4px;
            background: rgba(6, 182, 212, 0.1);
            border: 1px solid rgba(6, 182, 212, 0.25);
            color: var(--cyan);
            display: inline-flex;
            align-items: center;
        }

        .history-icon-btn {
            background: transparent;
            border: none;
            color: var(--text-sec);
            cursor: pointer;
            padding: 4px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }

        .history-icon-btn:hover {
            background: rgba(255,255,255,0.08);
            color: var(--text-pri);
        }

        .history-icon-btn.delete:hover {
            background: rgba(239, 68, 68, 0.15);
            color: #EF4444;
        }

        /* Slide-in preview drawer */
        .history-preview-pane {
            width: 0px;
            opacity: 0;
            display: flex;
            flex-direction: column;
            border: 1px solid var(--border);
            background: rgba(4, 7, 16, 0.6);
            backdrop-filter: blur(10px);
            border-radius: 8px;
            transition: width 0.35s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s;
            min-width: 0;
            overflow: hidden;
        }

        .history-preview-pane.active {
            width: 320px;
            opacity: 1;
        }

        .preview-bubble {
            margin-bottom: 8px;
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 11.5px;
            line-height: 1.5;
            max-width: 85%;
        }

        .preview-bubble.user {
            background: rgba(163, 113, 247, 0.1);
            border: 1px solid rgba(163, 113, 247, 0.2);
            color: #e9d5ff;
            align-self: flex-end;
        }

        .preview-bubble.ai {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.05);
            color: var(--text-pri);
            align-self: flex-start;
        }

        .preview-bubble.system {
            background: rgba(239, 68, 68, 0.05);
            border: 1px solid rgba(239, 68, 68, 0.1);
            color: #fca5a5;
            align-self: center;
            max-width: 95%;
            font-style: italic;
        }
```

---

### Task 3: Overhaul HTML Markup structure of Tab 6

**Files:**
- Modify: `network_manager/gui/web/index.html:2403-2436`

**Step 1: Write HTML replacement**
Replace the old `settings-tab-history` markup with our dual-pane flex layout containing real-time search box, bulk controls, card grid container, and the slide-out preview drawer structure.

*Target original code:*
```html
                <!-- TAB 6: CHAT HISTORY -->
                <div class="settings-tab-content" id="settings-tab-history">
                    <h3 class="settings-tab-title">Chat History</h3>
                    
                    <!-- Bulk Actions Toolbar -->
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 12px; gap: 10px; background: rgba(255,255,255,0.02); padding: 8px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);">
                        <span style="font-size:12px; color:var(--text-sec); font-weight: 500;" id="history-selected-count">0 items selected</span>
                        <div style="display:flex; gap: 8px;">
                            <button id="btn-delete-selected" class="settings-btn secondary" style="padding: 5px 12px; font-size:12px; color:#EF4444; border-color:rgba(239, 68, 68, 0.2); display: inline-block; width: auto; opacity: 0.5; cursor: not-allowed; font-weight: bold;" onclick="deleteSelectedHistory()" disabled>Delete Selected</button>
                            <button id="btn-delete-all" class="settings-btn secondary" style="padding: 5px 12px; font-size:12px; color:#EF4444; border-color:rgba(239, 68, 68, 0.4); display: inline-block; width: auto; font-weight: bold;" onclick="deleteAllHistory()">Delete All</button>
                        </div>
                    </div>

                    <div class="device-table-card" style="max-height: 400px; flex: 1; overflow-y: auto; margin-bottom: 20px;">
                        <table class="device-table">
                            <thead>
                                <tr>
                                    <th style="width: 40px; text-align: center; padding: 10px 0;">
                                        <input type="checkbox" id="history-select-all" onclick="toggleSelectAllHistory(this)" style="cursor:pointer; transform: scale(1.1); margin: 0; vertical-align: middle;">
                                    </th>
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

*Replacement code:*
```html
                <!-- TAB 6: CHAT HISTORY -->
                <div class="settings-tab-content" id="settings-tab-history" style="display: flex; flex-direction: column; height: 100%;">
                    <h3 class="settings-tab-title" style="margin-bottom: 12px;">Chat History</h3>
                    
                    <!-- Search & Filter bar -->
                    <div class="search-container" style="position: relative; margin-bottom: 12px; width: 100%;">
                        <span style="position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-sec); display: flex; align-items: center;">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                        </span>
                        <input type="text" id="history-search" placeholder="Search conversations by title or @device mentions..." oninput="filterHistory()" style="width: 100%; padding: 8px 12px 8px 32px; background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 6px; color: var(--text-pri); font-size: 12.5px; outline: none; transition: border-color 0.2s;">
                    </div>

                    <!-- Bulk Actions Toolbar -->
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 12px; gap: 10px; background: rgba(255,255,255,0.02); padding: 6px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);">
                        <div style="display:flex; align-items:center; gap:8px;">
                            <input type="checkbox" id="history-select-all" onclick="toggleSelectAllHistory(this)" style="cursor:pointer; transform: scale(1.1); margin: 0; vertical-align: middle; accent-color: var(--cyan);">
                            <span style="font-size:12px; color:var(--text-sec); font-weight: 500;" id="history-selected-count">0 items selected</span>
                        </div>
                        <div style="display:flex; gap: 8px;">
                            <button id="btn-delete-selected" class="settings-btn secondary" style="padding: 4px 10px; font-size:11px; color:#EF4444; border-color:rgba(239, 68, 68, 0.2); display: inline-block; width: auto; opacity: 0.5; cursor: not-allowed; font-weight: bold;" onclick="deleteSelectedHistory()" disabled>Delete Selected</button>
                            <button id="btn-delete-all" class="settings-btn secondary" style="padding: 4px 10px; font-size:11px; color:#EF4444; border-color:rgba(239, 68, 68, 0.4); display: inline-block; width: auto; font-weight: bold;" onclick="deleteAllHistory()">Delete All</button>
                        </div>
                    </div>

                    <!-- Two-Column Workspace Layout -->
                    <div class="history-tab-layout">
                        <!-- Left Pane: Grid of Cards -->
                        <div id="history-card-grid-container" class="history-card-grid" id="settings-history-tbody">
                            <!-- Populated dynamically with history cards -->
                        </div>

                        <!-- Right Pane: Slide-in dynamic preview drawer -->
                        <div id="history-preview-pane" class="history-preview-pane">
                            <div style="padding: 10px 12px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.25);">
                                <span style="font-size: 11px; font-weight: bold; text-transform: uppercase; color: var(--cyan); letter-spacing: 0.5px;">Quick Preview</span>
                                <button class="history-icon-btn" onclick="closeHistoryPreview()" style="padding: 2px 6px; font-size: 11px;">✕ Close</button>
                            </div>
                            <!-- Preview Details -->
                            <div style="padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.03); background: rgba(255,255,255,0.01);">
                                <h4 id="preview-session-title" style="margin: 0 0 4px 0; font-size: 12.5px; font-weight: 600; color: var(--text-pri); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">Chat Session</h4>
                                <span id="preview-session-date" style="font-size: 10px; color: var(--text-sec);">Created At</span>
                            </div>
                            <!-- Preview Messages List -->
                            <div id="preview-messages-container" style="flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; background: rgba(0,0,0,0.1); min-height: 0;">
                                <!-- Bubbles populated dynamically -->
                            </div>
                            <div style="padding: 8px 12px; border-top: 1px solid var(--border); background: rgba(0,0,0,0.25); display: flex; justify-content: flex-end;">
                                <button id="btn-load-previewed" class="settings-btn primary" style="padding: 4px 10px; font-size: 11px; width: auto;" onclick="loadPreviewedConversation()">Load Full Chat</button>
                            </div>
                        </div>
                    </div>

                    <div class="settings-actions" style="margin-top: auto; padding-top: 15px;">
                        <button class="settings-btn secondary" onclick="toggleSettingsModal()">Close</button>
                    </div>
                </div>
```

---

### Task 4: Complete JS Logic For Dynamic Rendering, Rename, Search & Preview

**Files:**
- Modify: `network_manager/gui/web/index.html:4288-4388`

**Step 1: Implement Dynamic History Loader and Render**
Update `loadHistorySettings()` to parse the enriched JSON data structure (with `message_count` and `devices` pills) and render beautiful interactive cards instead of table rows.

*Target original code:*
```javascript
                    window.loadHistorySettings = function() {
                        if (!window.bridge || !window.bridge.getPastConversations) return;
                        const tbody = document.getElementById('settings-history-tbody');
                        if (!tbody) return;

                        // Reset select-all checkbox
                        const masterCheckbox = document.getElementById('history-select-all');
                        if (masterCheckbox) masterCheckbox.checked = false;

                        window.bridge.getPastConversations(function(res) {
                            const conversations = JSON.parse(res);
                            if (conversations.length === 0) {
                                tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-sec); padding: 15px;">No saved chat history.</td></tr>`;
                                window.updateHistoryBulkBtnState();
                                return;
                            }
                            let html = '';
                            conversations.forEach(c => {
                                html += `
                                    <tr>
                                        <td style="text-align:center; padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05);">
                                            <input type="checkbox" class="history-row-checkbox" data-id="${c.id}" onclick="updateHistoryBulkBtnState()" style="cursor:pointer; transform: scale(1.1); margin: 0; vertical-align: middle;">
                                        </td>
                                        <td style="padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05);"><strong>${_escapeHtml(c.title)}</strong></td>
                                        <td style="color:var(--text-sec); padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05);">${c.created_at}</td>
                                        <td style="text-align:center; padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05);">
                                            <button class="settings-btn primary" style="padding: 4px 10px; font-size:11px; margin-right: 6px; display: inline-block; width: auto;" onclick="loadPastConversation('${c.id}')">Load</button>
                                            <button class="settings-btn secondary" style="padding: 4px 10px; font-size:11px; color:#EF4444; border-color:rgba(239, 68, 68, 0.2); display: inline-block; width: auto;" onclick="deletePastConversation('${c.id}')">Delete</button>
                                        </td>
                                    </tr>
                                `;
                            });
                            tbody.innerHTML = html;
                            window.updateHistoryBulkBtnState();
                        });
                    };
```

*Replacement code:*
```javascript
                    let currentPreviewId = null;

                    window.loadHistorySettings = function() {
                        if (!window.bridge || !window.bridge.getPastConversations) return;
                        const container = document.getElementById('history-card-grid-container');
                        if (!container) return;

                        // Reset select-all checkbox & close preview
                        const masterCheckbox = document.getElementById('history-select-all');
                        if (masterCheckbox) masterCheckbox.checked = false;
                        closeHistoryPreview();

                        window.bridge.getPastConversations(function(res) {
                            const conversations = JSON.parse(res);
                            if (conversations.length === 0) {
                                container.innerHTML = `<div style="grid-column: 1/-1; text-align:center; color:var(--text-sec); padding: 30px; font-size: 13px; background: rgba(255,255,255,0.01); border: 1px dashed var(--border); border-radius: 8px;">No saved chat history found. Start chatting to save sessions!</div>`;
                                window.updateHistoryBulkBtnState();
                                return;
                            }
                            let html = '';
                            conversations.forEach(c => {
                                const devicePills = c.devices && c.devices.length > 0 
                                    ? `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-top:2px;">` + c.devices.map(dev => `<span class="device-pill">@${_escapeHtml(dev)}</span>`).join('') + `</div>`
                                    : '';
                                
                                html += `
                                    <div class="history-card" id="history-card-${c.id}" data-id="${c.id}" data-title="${_escapeHtml(c.title)}" data-devices="${_escapeHtml((c.devices || []).join(','))}" onclick="previewPastConversation('${c.id}')">
                                        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom: 2px;">
                                            <input type="checkbox" class="history-row-checkbox" data-id="${c.id}" onclick="event.stopPropagation(); updateHistoryBulkBtnState();" style="cursor:pointer; transform: scale(1.1); margin: 0; vertical-align: middle; accent-color: var(--cyan);">
                                            
                                            <div style="display:flex; gap:2px; margin-top: -4px; margin-right: -4px;">
                                                <button class="history-icon-btn" onclick="event.stopPropagation(); startRenameHistory('${c.id}')" title="Rename Session">
                                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                                                </button>
                                                <button class="history-icon-btn" onclick="event.stopPropagation(); previewPastConversation('${c.id}')" title="Quick Preview">
                                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                                                </button>
                                                <button class="history-icon-btn delete" onclick="event.stopPropagation(); deletePastConversation('${c.id}')" title="Delete Session">
                                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                                                </button>
                                            </div>
                                        </div>

                                        <div id="title-wrapper-${c.id}" style="margin: 2px 0;">
                                            <span class="history-card-title">${_escapeHtml(c.title)}</span>
                                        </div>

                                        ${devicePills}

                                        <div style="display:flex; justify-content:space-between; align-items:center; font-size:10px; color:var(--text-sec); margin-top:auto; border-top: 1px solid rgba(255,255,255,0.03); padding-top: 6px;">
                                            <span style="display:flex; align-items:center; gap:4px;">
                                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                                                ${c.message_count || 0} messages
                                            </span>
                                            <span>
                                                ${c.created_at ? c.created_at.split(' ')[0] : 'N/A'}
                                            </span>
                                        </div>
                                    </div>
                                `;
                            });
                            container.innerHTML = html;
                            window.updateHistoryBulkBtnState();
                            
                            // Clear search input on full reload
                            const searchInput = document.getElementById('history-search');
                            if (searchInput) searchInput.value = '';
                        });
                    };
```

**Step 2: Implement Real-Time Client Filter**
Add `filterHistory()`:
```javascript
                    window.filterHistory = function() {
                        const query = document.getElementById('history-search').value.toLowerCase().trim();
                        const cards = document.querySelectorAll('.history-card');
                        
                        cards.forEach(card => {
                            const title = card.getAttribute('data-title').toLowerCase();
                            const devices = card.getAttribute('data-devices').toLowerCase();
                            
                            if (title.includes(query) || devices.includes(query) || query === '') {
                                card.style.display = 'flex';
                            } else {
                                card.style.display = 'none';
                            }
                        });
                    };
```

**Step 3: Implement Quick Preview Pane Logic**
Add `previewPastConversation(id)`, `closeHistoryPreview()`, and `loadPreviewedConversation()`:
```javascript
                    window.previewPastConversation = function(id) {
                        if (!window.bridge || !window.bridge.getConversationMessages) return;

                        // Toggle active style on cards
                        document.querySelectorAll('.history-card').forEach(c => {
                            if (c.getAttribute('data-id') === id) {
                                c.classList.add('selected-preview');
                            } else {
                                c.classList.remove('selected-preview');
                            }
                        });

                        currentPreviewId = id;

                        const card = document.getElementById(`history-card-${id}`);
                        const title = card ? card.getAttribute('data-title') : 'Chat Session';
                        
                        // Set Title & Date
                        document.getElementById('preview-session-title').innerText = title;
                        document.getElementById('preview-session-title').title = title;
                        
                        const previewPane = document.getElementById('history-preview-pane');
                        const container = document.getElementById('preview-messages-container');
                        
                        if (previewPane) previewPane.classList.add('active');
                        if (container) container.innerHTML = `<div style="color:var(--text-sec); font-size:11px; text-align:center; padding: 20px;">Loading messages...</div>`;

                        window.bridge.getConversationMessages(id, function(res) {
                            const messages = JSON.parse(res);
                            if (messages.length === 0) {
                                container.innerHTML = `<div style="color:var(--text-sec); font-size:11px; text-align:center; padding: 20px;">No messages in this conversation.</div>`;
                                return;
                            }
                            
                            let html = '';
                            messages.forEach(m => {
                                const senderName = m.sender === 'user' ? 'You' : m.sender === 'agent' ? 'Copilot' : 'System';
                                const bubbleClass = m.sender === 'user' ? 'user' : m.sender === 'agent' ? 'ai' : 'system';
                                
                                // Parse thoughts if any
                                let thoughtsHtml = '';
                                if (m.thoughts && m.thoughts.length > 0) {
                                    thoughtsHtml = `
                                        <details style="margin-top: 4px; font-size: 10px; color: var(--cyan); background: rgba(6,182,212,0.03); border: 1px solid rgba(6,182,212,0.1); border-radius: 4px; padding: 4px 6px;">
                                            <summary style="cursor:pointer; font-weight:600;">Show thinking process (${m.thoughts.length} steps)</summary>
                                            <div style="margin-top: 4px; white-space: pre-wrap; font-family: monospace; max-height: 80px; overflow-y:auto; line-height:1.4;">${_escapeHtml(m.thoughts.join('\n'))}</div>
                                        </details>
                                    `;
                                }

                                html += `
                                    <div class="preview-bubble ${bubbleClass}">
                                        <strong style="font-size: 10px; opacity: 0.8; display: block; margin-bottom: 2px;">${senderName}</strong>
                                        <div style="white-space: pre-wrap;">${_escapeHtml(m.text)}</div>
                                        ${thoughtsHtml}
                                    </div>
                                `;
                            });
                            container.innerHTML = html;
                            container.scrollTop = container.scrollHeight;
                        });
                    };

                    window.closeHistoryPreview = function() {
                        const previewPane = document.getElementById('history-preview-pane');
                        if (previewPane) previewPane.classList.remove('active');
                        currentPreviewId = null;
                        document.querySelectorAll('.history-card').forEach(c => c.classList.remove('selected-preview'));
                    };

                    window.loadPreviewedConversation = function() {
                        if (currentPreviewId) {
                            window.loadPastConversation(currentPreviewId);
                        }
                    };
```

**Step 4: Implement Inline Renaming Workflows**
Add `startRenameHistory(id)`, `saveRenameHistory(id)`, and `cancelRenameHistory(id, title)`:
```javascript
                    window.startRenameHistory = function(id) {
                        const card = document.getElementById(`history-card-${id}`);
                        if (!card) return;
                        
                        const title = card.getAttribute('data-title');
                        const wrapper = document.getElementById(`title-wrapper-${id}`);
                        if (!wrapper) return;

                        // Replace card title HTML inline
                        wrapper.innerHTML = `
                            <div style="display: flex; gap: 4px; width: 100%; margin: 2px 0;" onclick="event.stopPropagation()">
                                <input type="text" id="rename-input-${id}" value="${_escapeHtml(title)}" style="flex:1; font-size:12px; padding: 3px 6px; background: rgba(0,0,0,0.5); border: 1px solid var(--border); border-radius: 4px; color: white; outline: none; font-weight: normal;" onkeydown="if(event.key==='Enter') saveRenameHistory('${id}'); if(event.key==='Escape') cancelRenameHistory('${id}', '${_escapeHtml(title)}');">
                                <button onclick="event.stopPropagation(); saveRenameHistory('${id}')" style="background: var(--cyan); border: none; border-radius: 4px; color: black; padding: 2px 6px; cursor: pointer; font-size: 10.5px; font-weight:bold;">Save</button>
                                <button onclick="event.stopPropagation(); cancelRenameHistory('${id}', '${_escapeHtml(title)}')" style="background: rgba(255,255,255,0.1); border: none; border-radius: 4px; color: white; padding: 2px 6px; cursor: pointer; font-size: 10.5px;">✕</button>
                            </div>
                        `;
                        const input = document.getElementById(`rename-input-${id}`);
                        if (input) {
                            input.focus();
                            input.select();
                        }
                    };

                    window.saveRenameHistory = function(id) {
                        const input = document.getElementById(`rename-input-${id}`);
                        if (!input || !window.bridge || !window.bridge.renameConversation) return;

                        const newTitle = input.value.trim();
                        if (!newTitle) return;

                        window.bridge.renameConversation(id, newTitle);
                        
                        // Update attribute and reload card inline
                        const card = document.getElementById(`history-card-${id}`);
                        if (card) {
                            card.setAttribute('data-title', newTitle);
                        }
                        
                        const wrapper = document.getElementById(`title-wrapper-${id}`);
                        if (wrapper) {
                            wrapper.innerHTML = `<span class="history-card-title">${_escapeHtml(newTitle)}</span>`;
                        }

                        // If active preview is currently open for this session, sync its title
                        if (currentPreviewId === id) {
                            const previewTitle = document.getElementById('preview-session-title');
                            if (previewTitle) {
                                previewTitle.innerText = newTitle;
                                previewTitle.title = newTitle;
                            }
                        }
                    };

                    window.cancelRenameHistory = function(id, originalTitle) {
                        const wrapper = document.getElementById(`title-wrapper-${id}`);
                        if (wrapper) {
                            wrapper.innerHTML = `<span class="history-card-title">${_escapeHtml(originalTitle)}</span>`;
                        }
                    };
```

---

### Task 5: Adapt Bulk & Single Actions Bindings for Cards Layout

**Files:**
- Modify: `network_manager/gui/web/index.html:4324-4364`

**Step 1: Write HTML replacement**
Update `toggleSelectAllHistory` and `updateHistoryBulkBtnState` to query the checkbox element structures in our new card layout instead of standard rows.

*Target original code:*
```javascript
                    window.toggleSelectAllHistory = function(masterCheckbox) {
                        const checkboxes = document.querySelectorAll('.history-row-checkbox');
                        checkboxes.forEach(cb => {
                            cb.checked = masterCheckbox.checked;
                        });
                        window.updateHistoryBulkBtnState();
                    };

                    window.updateHistoryBulkBtnState = function() {
                        const checkboxes = document.querySelectorAll('.history-row-checkbox');
                        const checkedCount = Array.from(checkboxes).filter(cb => cb.checked).length;
                        const btnDeleteSelected = document.getElementById('btn-delete-selected');
                        const countSpan = document.getElementById('history-selected-count');

                        if (countSpan) {
                            countSpan.innerText = `${checkedCount} items selected`;
                        }

                        if (btnDeleteSelected) {
                            if (checkedCount > 0) {
                                btnDeleteSelected.style.opacity = '1';
                                btnDeleteSelected.style.cursor = 'pointer';
                                btnDeleteSelected.disabled = false;
                            } else {
                                btnDeleteSelected.style.opacity = '0.5';
                                btnDeleteSelected.style.cursor = 'not-allowed';
                                btnDeleteSelected.disabled = true;
                            }
                        }

                        // Sync master checkbox
                        const masterCheckbox = document.getElementById('history-select-all');
                        if (masterCheckbox && checkboxes.length > 0) {
                            masterCheckbox.checked = (checkedCount === checkboxes.length);
                        }
                    };
```

*Replacement code:*
Keep this exact code because our custom cards use the exact class name `history-row-checkbox` on card checkboxes!
This ensures maximum stability, simplicity, and zero regression of existing bulk actions!
We only need to make sure `loadHistorySettings()` triggers `window.updateHistoryBulkBtnState()` properly on fetch, which it does.
Let's make sure we also clean up any duplicate or leftover old JS event listener references in `index.html`.
