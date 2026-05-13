# ANCS Master Context (CLAUDE.md)
> **Claude Code Instructions:** Read this file to understand the architecture, state management, and file structure of the project. Do not re-explore directories unless asked.

## 1. System Overview
ANCS (Auto Network Configuration System) is a high-performance network automation desktop app built with **PySide6** (Qt for Python). It automates Cisco IOS device configurations, integrates deeply with **GNS3**, and features an **Agentic AI Copilot**.

- **Entry Point**: `run.py` (handles virtual environment management) -> calls `network_manager/main.py`.
- **Database**: SQLite (`network_manager.db`) using `PRAGMA journal_mode=WAL` for concurrent thread access. Schema includes `devices`, `credentials`, `configs`, `logs`, and `tasks`.
- **UI Architecture**: Glass-transparent, frameless PySide6 windows with custom CSS styling in `config.py` and `app.py`.

## 2. Technical Stack
- **Framework**: PySide6 (Qt 6)
- **Networking**: 
    - `telnetlib3` (Async Telnet for GNS3 nodes)
    - `paramiko` (SSH for physical/production nodes)
    - `pyserial` (Serial console fallback)
- **AI Engine**: `google-genai` (Gemini-based Copilot)
- **GNS3**: Communicates with GNS3 local server via REST API (`network/gns3.py`).

## 3. Directory & Module Map
### Core Logic (`network_manager/`)
- `ai_agent.py`: **The Brain**. Contains 18+ tools (Gemini function calling) for network discovery, auditing, and connectivity tracing.
- `network/sender.py`: The deployment engine. Handles multi-block IOS configuration sends, GNS3 "Press RETURN" bypass, and prompt detection.
- `network/puller.py`: Connects to live devices to scrape `show running-config`.
- `network/parser.py`: Analyzes raw IOS config into structured JSON for the wizard.
- `config.py`: Global constants, SQLite schema initialization, and thread-safe `db_lock`.

### GUI & UX (`gui/`)
- `app.py`: Main dashboard, device grid, and navigation controller.
- `wizards/guided_setup_wizard.py`: Huge (3000+ lines) logic engine that derives complex IOS configurations (VLANs, Routing, DHCP, ACLs) from user intent.
- `wizards/config_engine.py`: The syntax generator that builds the actual Cisco IOS string blocks.
- `terminal_panel.py`: An interactive, non-blocking terminal emulator for device consoles.

## 4. AI Copilot Capabilities
The integrated AI Agent has specialized tools defined in `ai_agent.py`:
- `list_gns3_nodes`: Maps out the GNS3 topology.
- `audit_network`: Scans all configs for security flaws (open VTY, missing enable secret).
- `trace_connectivity`: Hop-by-hop path tracing using `show ip route`.
- `generate_device_config`: Direct interface to the `ConfigEngine` to build valid IOS syntax.
- `deploy_to_device`: Safely pushes configs to nodes using saved credentials.

## 5. Development Rules
1. **Thread Safety**: All DB operations *must* use `with db_lock:` from `config.py`.
2. **UI Updates**: Never update the UI from a background thread. Use Qt Signals (`Signal`).
3. **Async Network**: Networking is async (asyncio) in the core, but usually wrapped in `QThread` or `asyncio.run` for the GUI.
4. **Cisco IOS Syntax**: Always use the `! BLOCK X: Title` header format when generating configs to ensure the `Sender` can deploy in chunks correctly.
5. **Styling**: Adhere to the glass-transparent dark theme. Shared tokens are in `config.py`.

## 6. Common Workflows
- **GNS3 Sync**: `app.py` -> `gns3.py` -> SQLite `devices` table update.
- **Live Sync**: `puller.py` -> `parser.py` -> `GuidedSetupWizard` (pre-populates fields).
- **Deployment**: `GuidedSetupWizard` -> `ConfigEngine` -> `Sender` -> `telnetlib3/paramiko` -> Device.

## 7. Behavioral Guidelines (Karpathy Style)
To ensure high-quality, surgical, and simple code changes:
1. **Think Before Coding**: State assumptions and tradeoffs explicitly before implementation.
2. **Simplicity First**: Minimum code that solves the problem. No speculative abstractions.
3. **Surgical Changes**: Touch only what you must. Match existing style.
4. **Goal-Driven Execution**: Define success criteria and verify after each step.
