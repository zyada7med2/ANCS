# ANCS Agent Optimization Instructions

**Context & Architecture Shift**
We are shifting the ANCS Copilot from a static "Push" model to an "Agentic Pull" model. 
Previously, a massive 20,000-character JSON snapshot of the network was injected into the AI's context on boot. This caused extreme TTFT (Time To First Token) latency and wasted massive amounts of API tokens, especially with Reasoning Models (like Kimi-k2.5) that over-analyze large contexts. 
We have already removed the static snapshot. The agent must now pull data using tools. 

Your task is to implement the final 4 safeguards to ensure this new "Agentic Pull" architecture is efficient, safe, and doesn't break the OpenAI API constraints.

Please modify `network_manager/ai_agent.py` to implement the following:

## 1. Infinite Loop Protection (Max Tool Calls)
**Why:** Because the agent now fetches context dynamically, it might get stuck in an endless loop of calling tools if it gets confused, burning through API credits.
**What to do:**
- In both `_process_response_gemini` and `_process_response_openrouter`, locate `MAX_TURNS = 25`.
- Reduce `MAX_TURNS` to `5`.
- Add logic so that if the loop reaches the final turn (`turn == MAX_TURNS - 1`), you forcefully append a system message to the model instructing it to stop using tools and provide a final answer immediately. 
  *(Example for OpenRouter: `self._messages.append({"role": "user", "content": "SYSTEM: Max tool calls reached. You must provide a final answer to the user now."})`)*

## 2. Unified Network Overview Tool
**Why:** Every tool call costs an API round-trip. Calling `list_all_devices` and then `get_topology_links` sequentially wastes time and tokens.
**What to do:**
- Create a new tool function `get_network_overview(project_id: str) -> str` in `ai_agent.py`.
- This function should internally call `list_all_devices` and `get_topology_links`, combine their outputs into a single concise JSON structure, and return it.
- Add `get_network_overview` to the `ALL_TOOLS` list.
- Update the `SYSTEM_PROMPT` to instruct the agent to use `get_network_overview()` instead of the individual tools when it needs to understand the current network state.

## 3. Dynamic History Truncation (Sliding Window)
**Why:** Because tool responses (like the new network overview) are now stored in the chat history, the context window will bloat quickly over a long conversation. We must prune old messages.
**Critical Constraint:** The OpenAI API throws a `400 Bad Request: Invalid message sequence` if an `assistant` message containing `tool_calls` is separated from the subsequent `tool` response message.
**What to do:**
- In `CopilotWorker.run()`, specifically for the Hapuppy/OpenRouter execution path (right before `self._client.chat.completions.create` is called), implement a history truncation algorithm on `self._messages`.
- Keep `Index 0` (the `SYSTEM_PROMPT`) untouched.
- If `len(self._messages) > 15`, attempt to slice the array to keep the last ~10 messages.
- **The Pruning Algorithm:** Scan the slice boundary. If the proposed slice separates a `tool_calls` message from its `tool` response, shift the boundary forward until you find a clean `user` message or an `assistant` message with no pending tool calls. Slice the history safely.

## 4. UI Feedback
**Why:** Since the agent starts "blind", it will pause to run the overview tool before answering the user's first prompt. We need to reassure the user that the app hasn't frozen.
**What to do:**
- In the tool execution loop, before executing a tool from `TOOL_MAP`, emit a log to the terminal: `self.terminal_log_signal.emit("<span style='color: #8b949e'>[Copilot] Analyzing network...</span>\n")`. 
- Ensure this doesn't spam the UI (e.g., only emit it if it's a major data-gathering tool or limit it to once per turn).
