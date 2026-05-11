# Network Manager - ANCS

**Auto Network Configuration System**

A modern desktop application for network device configuration management with GNS3 integration, featuring a rich **PySide6** glass-transparent UI and an integrated **Agentic AI Copilot**.

## ✨ Core Features

- **Device & Topology Management**: Manage routers, switches, and core switches. Auto-import entire network topologies (nodes and console links) directly from **GNS3**.
- **Agentic AI Copilot**: An advanced AI network brain (powered by Gemini) built directly into the app. It can:
  - Run multi-hop connectivity traces.
  - Audit network security and routing protocol mismatches.
  - Auto-generate configurations based on network topology.
  - Interact directly with device consoles via the `sender.py` pool.
- **Live State Sync**: Pull live `running-config` from devices using `puller.py` and `parser.py` to detect existing VLANs, IP assignments, and routing protocols, avoiding blind overwrites.
- **Smart Guided Wizards**: Complex multi-step wizards that auto-derive DHCP pools, static routes, and ACLs based on your chosen routing scheme (RIP, OSPF, EIGRP).
- **Async Network Engine**: High-performance concurrent deployments via `telnetlib3` (Telnet) and `paramiko` (SSH), ensuring the UI never freezes during long deployments.
- **Modern PySide6 UI**: A highly polished, custom-themed dark mode interface with true glass transparency, responsive geometry, and custom widget components.

## 🚀 Installation & Running

1. Clone the repository:
```bash
git clone https://github.com/zyada7med2/ANCS.git
cd ANCS
```

2. Setup virtual environment & dependencies:
```bash
python -m venv .venv
# Activate your venv here (e.g., .venv\Scripts\activate on Windows)
pip install -r network_manager/requirements.txt
```

3. Run the application:
```bash
# Uses the main run script which handles virtual environment re-execution
python run.py
```

## 🏗️ Project Architecture

```
ANCS/
├── run.py                          # Primary entry point
├── network_manager/
│   ├── main.py                     # App initialisation
│   ├── config.py                   # Global styling tokens & DB path
│   ├── ai_agent.py                 # The AI Copilot logic and tool definitions
│   ├── models/
│   │   └── devices.py              # SQLite data classes (Router, Switch, CoreSwitch)
│   ├── network/
│   │   ├── sender.py               # Async CLI execution (telnetlib3, paramiko)
│   │   ├── puller.py               # Connects to live devices to scrape configs
│   │   ├── parser.py               # Parses live config into structured wizard data
│   │   └── gns3.py                 # Communicates with GNS3 local server API
│   └── gui/
│       ├── app.py                  # The main PySide6 window and routing layout
│       ├── wizards/
│       │   ├── guided_setup_wizard.py # The core network logic generator
│       │   └── config_engine.py    # Builds raw Cisco IOS strings
│       ├── terminal_panel.py       # Live interactive console for devices
│       ├── topology_viewer.py      # Network graph visualisation
│       └── ...
```

## 📋 Key Dependencies

- `PySide6`: Modern Qt framework for the UI.
- `telnetlib3`: Async communication for GNS3 nodes.
- `paramiko`: Secure SSH communication for physical devices.
- `google-genai`: Powers the intelligent network Copilot.
- `pyserial`: Fallback for physical console connections.

## 📦 Building Executable

To create a standalone executable for Windows:

```bash
python setup_build.py build
```
The executable will be generated in the `build/` directory.

## 📄 License
MIT License
