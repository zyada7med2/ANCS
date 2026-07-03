# Design Doc: OpenModel DeepSeek API Integration

## Goal
Integrate the free OpenModel DeepSeek API provider into ANCS to allow the user to utilize DeepSeek models (like `deepseek-v4-flash` and `deepseek-v4-pro`) at zero cost.

## Background
OpenModel is a free model provider that exposes a service compatible with the Anthropic Messages API format. The endpoint is `https://api.openmodel.ai/v1/messages`. It does not support the OpenAI `/v1/chat/completions` endpoint.

## Proposed Design

### 1. Settings UI Updates
We will add `openmodel` as a provider option:
- **`index.html`**:
  - Add `<option value="openmodel">OpenModel (Free DeepSeek)</option>` under the `settings-provider` select element.
  - Define `openmodel` models list:
    ```javascript
    openmodel: [
        { value: 'deepseek-v4-flash',  label: 'DeepSeek V4 Flash' },
        { value: 'deepseek-v4-pro',    label: 'DeepSeek V4 Pro' },
    ]
    ```
- **`agent_bridge.py`**:
  - Map `"openmodel": "openmodel"` in `provider_map`.

### 2. Default Configuration & Pre-population
We will overwrite/update `ancs_config.json` with the following:
- `agent_provider`: `"openmodel"`
- `agent_model`: `"deepseek-v4-flash"`
- `gemini_api_key`: `"om-ofU1esnaC3qDnJ2zNV1JTzRGcGBYRU6W5wYt8LNBy"`

### 3. Backend Client & Translation Layer (`ai_agent.py`)
- **API Call**: If `provider == "openmodel"`, query `https://api.openmodel.ai/v1/messages` using `requests.post`.
- **Tool Mapping**: Translate our `OPENAI_TOOLS` schema to Anthropic's tools schema (naming the parameters object as `input_schema` and omitting the wrapping `{"type": "function", ...}`).
- **Message Format Translation**:
  - Convert OpenAI-formatted message history (stored in `self._messages`) to Anthropic's messages.
  - Set the system prompt as a top-level `"system"` parameter.
  - Map assistant `tool_calls` to content blocks of type `"tool_use"`.
  - Group successive tool responses (`role: "tool"`) as blocks of type `"tool_result"` under a single user message.
- **Thinking Process Logging**:
  - Extract `"thinking"` blocks from the Anthropic response content blocks and stream them to the log view as `💭 [Thinking] ...` in real-time.
- **Token and Cost Tracking**:
  - Track `input_tokens` and `output_tokens` returned in the response metadata.
  - Record the estimated cost as `$0.00` (since it's a free event).
