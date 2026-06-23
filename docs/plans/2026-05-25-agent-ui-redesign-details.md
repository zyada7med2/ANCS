# ANCS Agent UI Redesign Details

This design document outlines the UI details for the new hybrid `QWebEngineView` interface for the ANCS Agent, ensuring full visual and behavioral parity with the Figma targets.

## 1. Send Button Dropdown Options
- **Deploy via Network**: Pushes configurations via SSH/Telnet connections (Default).
- **Deploy via Serial Console**: Fallback serial console port configuration send.
- **Run Security & Audit Scan**: Executes the agent security scan on the running configuration.
- **Send Chat Message**: Normal chat communication with the AI Agent.

## 2. Logs Page Tools Filter Dropdown
- **All Tools (Default)**: Displays logs of all tool executions.
- **run_cli_on_device** (Terminal tool)
- **run_command_on_device** (Terminal tool)
- **verify_device** (Verification terminal)
- **snapshot_network_state** (Network snapshot)
- **get_network_overview** (Network overview)
- **list_all_devices** (Device inventory)
- **get_topology_links** (Topology mapper)
- **generate_device_config** (Config generator)
- **generate_and_deploy_device_config** (Generate and deploy)
- **deploy_to_device** (Deploy config)
- **trace_connectivity** (Connectivity trace)
- **audit_network** (Security audit)
- **validate_configs** (Config validator)
- **cleanup_device** (Cleanup tool)
- **bulk_deploy** (Bulk deploy)
- **calculate_subnet** (Subnet calculator)
- **get_agent_guidelines** (Guidelines tool)

## 3. Settings Modal Updates
- **Model & Provider Tab**: Added a toggle switch for `agent_allow_raw_deploy` labeled `"Allow raw config deploy"` with subtext `"Bypass safety signatures and allow direct deployment of raw configuration text to devices."`

## 4. Device Discovery Modal
Replaces the simple manual add modal with a dual-tabbed layout:
- **Auto Discover Tab**: Inputs for SNMP Range (`192.168.1.1-192.168.1.254`) and Community (`public`), scan animation progress bar, and list of discovered devices with checkboxes to add selected.
- **Manual Add Tab**: Standard protocol inputs (SSH, Telnet, Serial Console), host, port, username, password, enable password, and a submit button.
