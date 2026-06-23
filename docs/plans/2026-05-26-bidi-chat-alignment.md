# Bidirectional Chat Alignment Implementation Plan

> **For Antigravity**: REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal**: Enable robust native bidirectional (BiDi) text rendering in the ANCS AI Copilot chat window so that Arabic paragraphs with mixed English terms align to the right, flow naturally in chronological word order, and render with correct punctuation, while standard English paragraphs remain LTR left-aligned.

**Architecture**: Add visual bidirectional layout styling properties (`unicode-bidi: plaintext` and `text-align: start`) scoped strictly to chat content bubble CSS classes, and supplement it with HTML5 `dir="auto"` attributes in index.html dynamically rendered templates and user input elements.

**Tech Stack**: HTML5, Vanilla CSS, JavaScript, QWebEngineView (Chromium 3D Engine fallback).

---

### Task 1: Update CSS Stylesheet in index.html

**Files**:
- Modify: `network_manager/gui/web/index.html:317-366`

**Step 1: Write verification test (Verify string changes)**
We will verify that the CSS styles are modified to include `unicode-bidi: plaintext; text-align: start; line-height: 1.8;`.

**Step 2: Apply the minimal CSS changes**

Target lines in CSS to modify:
1. `.user-message` style (around line 316-325) - adjust/ensure it supports plaintext bidi if needed, but primarily the content bubble `.user-content` and `.ai-content`.
2. `.user-content` style (around line 333-337).
3. `.ai-content` style (around line 360-365).

Add the following properties to both `.user-content` and `.ai-content`:
```css
unicode-bidi: plaintext;
text-align: start;
line-height: 1.8; /* enhanced line-height for Arabic glyphs readability */
```

Also add it to `#chat-text-input` parent box/input if needed, but `dir="auto"` on input itself is sufficient.

**Step 3: Verify style definition**
Verify that the stylesheet in `index.html` contains `.ai-content` and `.user-content` with `unicode-bidi: plaintext`.

**Step 4: Commit**
```bash
git add network_manager/gui/web/index.html
git commit -m "style: add bidi support properties to message content bubbles"
```

---

### Task 2: Inject HTML5 `dir="auto"` attributes and input handlers

**Files**:
- Modify: `network_manager/gui/web/index.html:650-675`, `network_manager/gui/web/index.html:3720-3770`

**Step 1: Apply input and container HTML changes**
1. Locate the dynamic input tag with ID `chat-text-input` around lines 650-675 or lines 3720-3770:
   ```html
   <input type="text" id="chat-text-input" placeholder="Ask ANCS anything..." dir="auto">
   ```
   Add the `dir="auto"` attribute to it.

2. In JavaScript functions `_appendUserMessage` (around line 3724) and `_appendAgentMessage` (around line 3742), add the `dir="auto"` attribute to the template divs:
   ```javascript
   // In _appendUserMessage
   <div class="user-content" dir="auto">${_escapeHtml(text)}</div>
   
   // In _appendAgentMessage
   <div class="ai-content" dir="auto">${html}</div>
   ```

**Step 2: Verify changes**
Verify that the `dir="auto"` attribute is present in:
- `<input type="text" id="chat-text-input"`
- `<div class="user-content"`
- `<div class="ai-content"`

**Step 3: Commit**
```bash
git add network_manager/gui/web/index.html
git commit -m "feat: inject dir=auto to dynamic message divs and user chat input"
```

---

### Task 3: Manual Visual Verification

**Files**:
- Test: Manual verification via UI startup.

**Step 1: Launch application**
Run: `python run.py` or `.venv\Scripts\python run.py`

**Step 2: Test Arabic with English terms**
Open the Copilot Agent Dialog, and type or paste the mixed testing paragraph:
```
🌐 تجربة تنسيق النصوص (UI Formatting Test)
أهلاً بك في نظام ANCS Copilot! أنا هنا عشان أساعدك تعمل Automated Configuration لكل الـ Network Devices بتاعتك...
```

**Step 3: Validate visual layout**
1. Verify that the Arabic text starts on the right side of the bubble and reads right-to-left.
2. Verify that English terms embedded (e.g. "Automated Configuration") flow in correct chronological order inside the sentence without scrambling.
3. Verify that the input box direction switches to right-aligned when typing Arabic.
