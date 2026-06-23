# Design Document: Bidirectional (BiDi) Chat Alignment for Mixed Arabic/English Text

**Date**: 2026-05-26  
**Author**: Antigravity Copilot  
**Status**: APPROVED

---

## 1. Overview
The ANCS AI Copilot interface supports multi-language capabilities. However, when Arabic (Right-to-Left, RTL) sentences contain English terms or acronyms (Left-to-Right, LTR) in the middle, the browser's default LTR rendering scrambles the sentence order, word flow, and punctuation. 

This design establishes a robust, native bidirectional layout system inside the ANCS chat window using CSS and HTML standard compliance features, requiring zero changes to the backend AI logic.

---

## 2. Core Problem & Analysis
By default, the QWebEngineView renders standard HTML inside `network_manager/gui/web/index.html` as Left-to-Right (`ltr`), matching the language configuration of the document (`<html lang="en">`).

When mixed Arabic/English text is displayed within this LTR context:
1. **Sentence Fragmentation**: The browser attempts to read Arabic as LTR words. Embedding LTR words in the middle breaks the logical chronological order of words.
2. **Incorrect Alignment**: Arabic explanations are aligned to the left side of the chat bubble instead of the right side, which degrades the readability of RTL text.
3. **Punctuation Relocation**: Question marks, periods, and exclamation marks at the end of Arabic sentences are incorrectly positioned on the far left or right of embedded LTR blocks.

---

## 3. Proposed Solution

### A. CSS `unicode-bidi: plaintext` & `text-align: start` (Option 1)
We will add standard bidirectional layout properties to the `.ai-content` and `.user-content` chat bubble classes in the stylesheet of `index.html`:
```css
.ai-content, .user-content {
    unicode-bidi: plaintext;
    text-align: start;
}
```
*   **Mechanism**: `unicode-bidi: plaintext` directs Chromium's layout engine to ignore the inherited directional properties of the parent document. Instead, it computes the directionality of each paragraph dynamically based on the heuristic rules of the Unicode bidirectional algorithm (looking at the first character of the paragraph).
*   **Result**: 
    *   Arabic paragraphs render RTL and align to the right, with English terms embedded correctly.
    *   English paragraphs render LTR and align to the left.
    *   Multi-line/multi-paragraph mixed answers display each block with its correct alignment automatically.

### B. HTML `dir="auto"` on Dynamic Input & Chat Containers (Option 2)
To supplement the CSS solution and ensure maximum compatibility, we will apply the HTML `dir="auto"` attribute to:
1. The dynamic message container templates created in `_appendUserMessage` and `_appendAgentMessage` in `index.html`.
2. The user text input element (`#chat-text-input`) so that when a user types in Arabic, the input cursor and alignment automatically flip to the right side of the box in real-time.

---

## 4. Affected Files
*   **`network_manager/gui/web/index.html`**:
    *   Inject CSS properties `unicode-bidi: plaintext; text-align: start;` into `.ai-content` and `.user-content` styling definitions.
    *   Add `dir="auto"` to the `<div class="user-content">` and `<div class="ai-content">` templates.
    *   Add `dir="auto"` to the `#chat-text-input` `<input>` field.

---

## 5. Verification & Testing
We will test the rendering using the user's mixed testing paragraph:
```
🌐 تجربة تنسيق النصوص (UI Formatting Test)
أهلاً بك في نظام ANCS Copilot! أنا هنا عشان أساعدك تعمل Automated Configuration لكل الـ Network Devices بتاعتك...
```

### Success Criteria:
1. The paragraph starting with Arabic characters must automatically align to the right side of the chat bubble.
2. English words embedded in the Arabic sentence (e.g., "Automated Configuration", "Network Devices", "Core Switch", "OSPF") must flow chronologically and naturally within the sentence without shuffling positions.
3. Code blocks or logs starting with English characters must remain aligned to the left.
4. The user input textbox must align to the right when typing Arabic characters, and back to the left when typing English.
