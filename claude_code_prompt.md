# Task: Add OpenRouter Support to ANCS AI Agent (Keep Gemini as Option)

## Context
The ANCS (Auto Network Configuration System) has an AI agent in `network_manager/ai_agent.py` that currently uses Google's `google-genai` library to connect to Gemini. The user can no longer use Gemini because their Google Cloud organization blocks API keys. We need to ADD OpenRouter as a second provider (OpenAI-compatible API with free models), while KEEPING the existing Gemini code as a fallback option.

The user's OpenRouter API key is: `[REDACTED]`

## Architecture: Dual-Provider Design
The agent should support TWO providers, selectable in the GUI:
1. **Google Gemini** (existing code, unchanged) — uses `google-genai` library
2. **OpenRouter** (new) — uses `openai` library pointed at `https://openrouter.ai/api/v1`

The provider choice determines:
- Which client library initializes in `run()`
- Which response format `_process_response()` handles
- Which tool schema format is used (Gemini auto-infers from functions; OpenAI needs explicit JSON)

## Files to Modify
1. `network_manager/ai_agent.py` — Core agent logic
2. `network_manager/gui/app.py` — GUI dialog for the Copilot
3. `network_manager/requirements.txt` — Dependencies (already has `openai>=1.0.0` added)

## What Must NOT Change
- **ALL 23 tool Python functions** (lines ~128–952 in ai_agent.py) — pure Python, completely unchanged
- **`ALL_TOOLS` list** (lines ~959–990) — stays as-is
- **`TOOL_MAP` dict** (line ~993) — stays as-is
- **`_AgentContext` / `ctx`** singleton (lines ~23–42) — stays as-is
- **`_establish_pool()`** and all Telnet/session logic — stays as-is
- **`_async_connect()`** — stays as-is
- **Cleanup in `finally` block** of `run()` — stays as-is
- **GUI layout structure** (tabs, chat rendering, CSS, markdown) — stays as-is

## Detailed Changes Required

### 1. ai_agent.py — Imports (lines 13-14)

KEEP the existing google imports AND add new ones:
```python
from google import genai
from google.genai import types
import openai
import inspect
```

### 2. ai_agent.py — Add `_build_openai_tools()` function (insert after TOOL_MAP on line ~993)

Write a function that converts the existing `ALL_TOOLS` list of Python functions into OpenAI tool-calling JSON schemas. Use `inspect.signature()` to read each function's parameters, type annotations, and defaults. Use the function's `__doc__` docstring as the tool description.

Key details:
- Parameters with `str` annotation → `"type": "string"`
- Parameters with `int` annotation → `"type": "integer"`
- Parameters with no default value → add to `"required"` list
- Parameters with a default value → optional
- Parse the `Args:` section of docstrings to extract per-parameter descriptions
- Output format: `[{"type": "function", "function": {"name": ..., "description": ..., "parameters": {"type": "object", "properties": {...}, "required": [...]}}}]`

Store result in module-level: `OPENAI_TOOLS = _build_openai_tools()`

### 3. ai_agent.py — Update SYSTEM_PROMPT (line ~1001)

Change `"You are powered by Gemini"` to `"You are powered by AI"`.

Add this section at the end of the system prompt (before closing `"""`):
```
# CISCO IOS QUICK REFERENCE (for model grounding)
Common commands: show running-config, show ip interface brief, show ip route, show vlan brief, show interfaces trunk, show spanning-tree, ping X.X.X.X
Config mode: configure terminal → hostname X → interface X → ip address X M → no shutdown → end
VLAN database (older IOS): vlan database → vlan 10 name Staff → exit
Trunk: interface X → switchport trunk encapsulation dot1q → switchport mode trunk
```

### 4. ai_agent.py — Update `CopilotWorker.__init__` (lines ~1145–1162)

Add these new parameters:
- `provider: str = "openrouter"` — either `"gemini"` or `"openrouter"`
- `model_name: str = "nousresearch/hermes-3-llama-3.1-405b:free"`

Add these new instance variables:
- `self.provider = provider`
- `self.model_name = model_name`
- `self._messages = []` (for OpenRouter chat history management)

Keep ALL existing parameters and instance variables unchanged.

### 5. ai_agent.py — Rename existing `_process_response()` to `_process_response_gemini()` (lines ~1310–1376)

Keep the ENTIRE existing method body unchanged. Just rename it.

### 6. ai_agent.py — Add NEW `_process_response_openrouter()` method (after the renamed method)

New method for OpenAI response format:

```python
def _process_response_openrouter(self, response):
    """Handle the agentic tool-calling loop (OpenAI format) and return final text."""
    MAX_TURNS = 25
    for turn in range(MAX_TURNS):
        message = response.choices[0].message

        # If no tool calls, we're done
        if not message.tool_calls:
            break

        # Add assistant message (with tool_calls) to history
        self._messages.append(message.model_dump())

        # Execute each tool call
        for tc in message.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                fn_args = {}
                ctx.log(f"<span style='color:#d29922'>[Copilot] Warning: bad JSON args for {fn_name}</span>\n")

            # Log tool call with arguments (same style as Gemini version)
            args_preview = ", ".join(f"{k}={repr(v)[:80]}" for k, v in fn_args.items())
            ctx.log(f"<span style='color:#a371f7'><b>[Tool Call]</b> {fn_name}({args_preview})</span>\n")

            t0 = time.monotonic()
            if fn_name in TOOL_MAP:
                try:
                    result = TOOL_MAP[fn_name](**fn_args)
                except (json.JSONDecodeError, TypeError) as e:
                    result = f"ERROR: Bad arguments for {fn_name} — {e}. Please check parameter types and retry."
                    ctx.log(f"<span style='color:#d73a49'><b>[Tool Error]</b> {fn_name}: {e}</span>\n")
                except Exception as e:
                    result = f"Tool error: {e}"
                    ctx.log(f"<span style='color:#d73a49'><b>[Tool Error]</b> {fn_name}: {e}</span>\n")
            else:
                result = f"Unknown tool: {fn_name}"
            dt_ms = (time.monotonic() - t0) * 1000.0

            # Log result preview + timing (same style as Gemini version)
            result_preview = str(result)[:300].replace('<', '&lt;').replace('>', '&gt;')
            ctx.log(
                f"<span style='color:#8b949e'>[Tool Result] {fn_name} → {dt_ms:.0f}ms | "
                f"{result_preview}{'…' if len(str(result)) > 300 else ''}</span>\n"
            )

            # Add tool result to messages
            self._messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            })

        # Context anchoring every 8 tool turns to prevent drift
        if turn > 0 and turn % 8 == 0:
            self._messages.append({
                "role": "system",
                "content": "REMINDER: Stay focused on the user's original request. "
                           "Do not repeat tools you already called successfully."
            })

        # Get next response with retry logic for rate limits
        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=self.model_name,
                    messages=self._messages,
                    tools=OPENAI_TOOLS,
                    extra_headers={"HTTP-Referer": "https://github.com/ANCS", "X-Title": "ANCS Copilot"},
                )
                break
            except openai.RateLimitError:
                if attempt < 2:
                    wait = 2 ** (attempt + 1)
                    self.terminal_log_signal.emit(
                        f"<span style='color:#d29922'>[Copilot] Rate limited, retrying in {wait}s...</span>\n"
                    )
                    time.sleep(wait)
                else:
                    raise

    # Extract final text
    final_text = ""
    try:
        final_text = response.choices[0].message.content or ""
        if final_text:
            self._messages.append({"role": "assistant", "content": final_text})
    except Exception:
        pass

    return final_text or "I completed the requested actions. Check the Execution Logs for details."
```

### 7. ai_agent.py — Add routing `_process_response()` method

Add a simple dispatcher that calls the right version:
```python
def _process_response(self, response):
    if self.provider == "gemini":
        return self._process_response_gemini(response)
    else:
        return self._process_response_openrouter(response)
```

### 8. ai_agent.py — Update `run()` method (lines ~1394–1457)

Keep steps 1-2 (event loop + pool) completely unchanged.

Replace step 3 (Gemini init, lines ~1394-1421) with a provider branch:

```python
# 3. Init AI Client
if self.provider == "gemini":
    # ── Gemini path (original, unchanged) ──
    self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Initializing Gemini...</span>\n")
    self._client = genai.Client(
        api_key=self.api_key,
        http_options=types.HttpOptions(api_version="v1alpha"),
    )
    models_to_try = [self.model_name] if self.model_name else ["gemini-2.0-flash", "gemini-1.5-flash"]
    for mn in models_to_try:
        try:
            self.terminal_log_signal.emit(f"<span style='color: #8b949e'>[Copilot] Trying model: {mn}...</span>\n")
            self._chat = self._client.chats.create(
                model=mn,
                config=types.GenerateContentConfig(
                    tools=ALL_TOOLS,
                    temperature=0.2,
                    system_instruction=SYSTEM_PROMPT,
                )
            )
            self.terminal_log_signal.emit(f"<span style='color: #3fb950'>[Copilot] Model loaded: {mn} ✓</span>\n")
            break
        except Exception as e:
            self.terminal_log_signal.emit(f"<span style='color: #d73a49'>[Copilot] {mn} failed: {e}</span>\n")
            self._chat = None
    if not self._chat:
        self.finished_signal.emit("Failed to initialize any Gemini model.", False)
        return

else:
    # ── OpenRouter path (new) ──
    self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Initializing OpenRouter...</span>\n")
    self._client = openai.OpenAI(
        api_key=self.api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    self._messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    self.terminal_log_signal.emit(f"<span style='color: #3fb950'>[Copilot] Model: {self.model_name} ✓</span>\n")
```

Replace step 4 (greeting, lines ~1423-1443) with a provider branch:

```python
# 4. Inject snapshot + greeting
self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Building project snapshot...</span>\n")
snap_preview = self.project_snapshot[:500]
self.terminal_log_signal.emit(
    f"<span style='color:#8b949e'>[Snapshot] {snap_preview}{'…' if len(self.project_snapshot) > 500 else ''}</span>\n"
)
self.terminal_log_signal.emit(
    f"<span style='color: #8b949e'>[Copilot] Injecting snapshot ({len(self.project_snapshot)} chars) into agent context...</span>\n"
)

greeting_prompt = (
    f"Here is the current ANCS project state (all devices, their configs, deploy status):\n"
    f"```json\n{self.project_snapshot}\n```\n\n"
    f"The user just opened Copilot. Greet briefly and summarize what you see in the project: "
    f"how many devices, what's configured vs not, what's been deployed, and flag any obvious "
    f"issues you notice (e.g. mismatched routing protocols, missing configs, devices not deployed). "
    f"Do NOT ask an open-ended 'what would you like to do?'."
)

if self.provider == "gemini":
    greeting_response = self._chat.send_message(greeting_prompt)
else:
    self._messages.append({"role": "user", "content": greeting_prompt})
    greeting_response = self._client.chat.completions.create(
        model=self.model_name,
        messages=self._messages,
        tools=OPENAI_TOOLS,
        extra_headers={"HTTP-Referer": "https://github.com/ANCS", "X-Title": "ANCS Copilot"},
    )

greeting_text = self._process_response(greeting_response)
self.chat_response_signal.emit(greeting_text)
self.ready_signal.emit()
```

Replace step 5 (message loop, lines ~1445-1457) with a provider branch:

```python
# 5. Message loop
while self._running:
    if self._msg_queue:
        user_msg = self._msg_queue.pop(0)
        self.terminal_log_signal.emit(f"\n<span style='color: #58A6FF'><b>[User]</b> {user_msg}</span>\n")
        try:
            if self.provider == "gemini":
                response = self._chat.send_message(user_msg)
            else:
                self._messages.append({"role": "user", "content": user_msg})
                response = self._client.chat.completions.create(
                    model=self.model_name,
                    messages=self._messages,
                    tools=OPENAI_TOOLS,
                    extra_headers={"HTTP-Referer": "https://github.com/ANCS", "X-Title": "ANCS Copilot"},
                )
            reply = self._process_response(response)
            self.chat_response_signal.emit(reply)
        except Exception as e:
            self.chat_response_signal.emit(f"**Error:** {e}")
    else:
        time.sleep(0.1)
```

Keep the `except`/`finally` block completely unchanged.

---

### 9. gui/app.py — Add QComboBox import (line ~2756)

Add `QComboBox` to the existing PySide6.QtWidgets import line:
```python
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                QLineEdit, QPushButton, QTextBrowser, QMessageBox,
                                QTabWidget, QWidget, QScrollArea, QFrame, QCheckBox, QComboBox)
```

### 10. gui/app.py — Load config (lines ~2761-2768)

Add loading of saved provider and model from config:
```python
saved_provider = cfg.get("agent_provider", "openrouter")
saved_model = cfg.get("agent_model", "nousresearch/hermes-3-llama-3.1-405b:free")
```

### 11. gui/app.py — Update settings UI (lines ~2820-2857)

Replace the single "API Key" row with a vertical layout containing:

**Row 1: Provider selector** (NEW)
- Add a QComboBox with two options: `"OpenRouter (Free Models)"` and `"Google Gemini (API Key)"`
- Set current from `saved_provider`

**Row 2: API Key**
- Change placeholder to "OpenRouter or Gemini API key"

**Row 3: Model selector** (NEW)
- Add an EDITABLE QComboBox with these preset models:
  - `nousresearch/hermes-3-llama-3.1-405b:free` (default for OpenRouter)
  - `openai/gpt-4o-mini`
  - `qwen/qwen-2-72b-instruct:free`
  - `google/gemma-2-27b-it:free`
  - `meta-llama/llama-3.1-8b-instruct:free`
  - `gemini-2.0-flash` (for Gemini provider)
  - `gemini-1.5-flash` (for Gemini provider)
  - `gemini-1.5-pro` (for Gemini provider)
- Set current text from `saved_model`
- Make editable so user can type custom model IDs

Keep the Connect Agent and Disconnect buttons.

### 12. gui/app.py — Update launch_agent() (lines ~3112-3176)

- Read `provider = "gemini" if provider_combo.currentIndex() == 1 else "openrouter"`
- Read `model_name = model_combo.currentText()`
- Save `cfg["agent_provider"] = provider` and `cfg["agent_model"] = model_name`
- Pass `provider=provider, model_name=model_name` to CopilotWorker constructor
- Update the "Missing Key" warning to say "API key" generically
- Update the "same settings" check to also compare provider and model_name

---

## Quality Mitigations (build into OpenRouter path only)
1. **Auto-retry on bad tool args**: Catch `TypeError` and `json.JSONDecodeError` in tool execution, return helpful error so model self-corrects
2. **Context anchoring**: Every 8 tool turns, inject system reminder to stay focused
3. **Rate limit retry**: Exponential backoff (3 attempts) on `openai.RateLimitError`
4. **Graceful JSON parsing**: Wrap `json.loads(tc.function.arguments)` in try/except

## Verification
After making changes, run:
```bash
python -c "from network_manager.ai_agent import OPENAI_TOOLS, TOOL_MAP; print(f'{len(OPENAI_TOOLS)} tools converted, {len(TOOL_MAP)} in map')"
```
Expected output: `23 tools converted, 23 in map`

## Important Notes
- KEEP `google-genai` in both imports AND requirements.txt — Gemini is still a valid provider
- OpenRouter requires `extra_headers` with `HTTP-Referer` and `X-Title` on every API call
- The `base_url` for OpenRouter is `https://openrouter.ai/api/v1`
- All 23 tool functions must remain completely untouched — only the AI client layer changes
- The Gemini code path should work EXACTLY as it does today — zero changes to it
- The new OpenRouter path is additive — it runs alongside the existing Gemini path
