<div align="center">

<img src="https://raw.githubusercontent.com/zyada7med2/ANCS/main/network_manager/gui/logo.png" alt="ANCS Logo" width="120"/>

<h1>ANCS — Auto Network Configuration System</h1>

<p>
  <strong>A professional desktop application for network device configuration management<br/>
  with GNS3 integration, live topology visualization, and an embedded Agentic AI Copilot.</strong>
</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PySide6-Qt%206-41CD52?style=for-the-badge&logo=qt&logoColor=white"/>
  <img src="https://img.shields.io/badge/AI-Gemini%20Powered-4285F4?style=for-the-badge&logo=google&logoColor=white"/>
  <img src="https://img.shields.io/badge/GNS3-Integration-FF6600?style=for-the-badge&logo=cisco&logoColor=white"/>
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-0078D4?style=for-the-badge&logo=windows&logoColor=white"/>
  <img src="https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge"/>
</p>

<p>
  <a href="#-screenshots">Screenshots</a> •
  <a href="#-features">Features</a> •
  <a href="#-installation">Installation</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-ai-copilot">AI Copilot</a> •
  <a href="#-tech-stack">Tech Stack</a>
</p>

</div>

---

## 📸 Screenshots

<table>
<tr>
<td><b>Main Application — Network Manager</b></td>
<td><b>AI Agent — Chat Interface</b></td>
</tr>
<tr>
<td><img src="https://raw.githubusercontent.com/zyada7med2/ANCS/main/figma_preview.png" alt="Main UI" width="480"/></td>
<td><img src="https://raw.githubusercontent.com/zyada7med2/ANCS/main/ui_selfcheck_after_polish_v2.png" alt="Agent Chat" width="480"/></td>
</tr>
</table>

> **Main View:** Device list, Config Preview, GNS3 Topology tab, Guided Setup & Deploy All buttons, Discovery & Send panel.
> **AI Agent:** Live device status bar, Chat + Execution Logs tabs, Console Stream with color-coded output, Structured Events panel, Network Topology graph with KPI cards.

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🤖 Agentic AI Copilot
A fully autonomous network assistant powered by **Google Gemini** (via Vertex AI). It:
- Opens a **pooled Telnet session** to every managed device
- Runs multi-hop **connectivity traces**
- **Audits** routing protocols and security ACLs
- **Auto-generates** Cisco IOS config blocks from topology
- Streams reasoning live to the **Console Stream** panel
- Logs every tool call to the **Structured Events** panel

</td>
<td width="50%">

### 🗺️ Live Topology Viewer
- Imports entire GNS3 topologies (nodes + console links) in one click
- Renders an interactive **network graph** with labeled interfaces
- Shows per-device details: Console Target, Operational IP, Platform, Connectivity, Last Seen
- **Refresh** button for live topology updates

</td>
</tr>
<tr>
<td width="50%">

### 🔁 Live State Sync
- `puller.py` connects to live devices and scrapes `running-config`
- `parser.py` converts raw CLI output into structured wizard data
- Detects existing VLANs, IPs, and routing protocols
- Prevents blind overwrites on already-configured devices

</td>
<td width="50%">

### ⚡ Smart Guided Wizards
Step-by-step wizards that auto-derive full configs:
- DHCP pools, static routes, and ACL rules
- Routing protocols: **RIP v2**, **OSPF**, **EIGRP**
- Config engine outputs clean **Cisco IOS strings** ready to deploy
- **Deploy Review Dialog** to inspect before pushing

</td>
</tr>
<tr>
<td width="50%">

### 🚀 Async Bulk Deployment
- `bulk_deploy.py` + `parallel_deploy.py` for concurrent multi-device pushes
- **Telnet** (`telnetlib3`) for GNS3 virtual devices
- **SSH** (`paramiko`) for physical hardware
- **Serial** (`pyserial`) fallback for console connections
- UI stays fully responsive during long deployments

</td>
<td width="50%">

### 🖥️ Custom Dark Glass UI
- Frameless, translucent window with custom title bar
- Custom fonts: **Orbitron**, **Michroma**, **Audiowide**, Montserrat
- Animated network background (`bg.png`)
- `monitor.py` for live device monitoring panel
- `calculators/` module for subnet & VLSM tools
- `outlined_label.py` for custom glowing text widgets

</td>
</tr>
</table>

---

## 📦 Installation

> **Requirements:** Python 3.10+, Windows or Linux. GNS3 is optional (for virtual lab mode).

### 1. Clone the repository

```bash
git clone https://github.com/zyada7med2/ANCS.git
cd ANCS
```

### 2. Set up virtual environment & install dependencies

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r network_manager/requirements.txt
```

### 3. Run the application

```bash
python run.py
```

### 🪟 Build a Windows Executable

```bash
python setup_build.py build
# Standalone .exe generated in build/
```

---

## 🏗️ Architecture

```
ANCS/
├── run.py                                  # 🚀 Entry point — handles venv re-execution
├── setup_build.py                          # PyInstaller build script
├── build_exe.py                            # Alternative build helper
└── network_manager/
    ├── main.py                             # App initialisation & Qt event loop
    ├── config.py                           # Global styling tokens, DB path, theme constants
    ├── ai_agent.py                         # 🤖 Agentic AI core — Gemini tools & reasoning
    ├── ancs_config.json                    # Runtime config (model, project, etc.)
    ├── requirements.txt                    # Python dependencies
    │
    ├── models/
    │   └── devices.py                      # SQLite data classes: Router, Switch, CoreSwitch
    │
    ├── network/
    │   ├── sender.py                       # Async CLI execution (Telnet + SSH)
    │   ├── puller.py                       # Live config scraper from running devices
    │   ├── parser.py                       # Parses CLI output → structured wizard data
    │   └── gns3.py                         # GNS3 REST API client
    │
    ├── vendors/                            # Multi-vendor support modules
    │
    └── gui/
        ├── app.py                          # Main PySide6 window, tab routing, layout
        │
        ├── agent_bridge.py                 # Bridge: AI agent ↔ GUI signals
        ├── agent_dialog.py                 # AI Agent dialog (stable release)
        ├── agent_dialog_new.py             # AI Agent dialog (latest — Chat + Exec Logs)
        │
        ├── bulk_deploy.py                  # Sequential bulk deployment engine
        ├── parallel_deploy.py              # Concurrent multi-device deployment
        ├── deploy_review_dialog.py         # Pre-deploy config review UI
        ├── sync_workflows.py               # Live-sync workflow orchestration
        │
        ├── monitor.py                      # Live device monitoring panel
        ├── topology_viewer.py              # 🗺️ Interactive network graph
        ├── terminal_panel.py               # 💻 Live device console (interactive)
        │
        ├── template_selector_dialog.py     # Config template picker
        ├── physical_discovery_dialog.py    # Physical device auto-discovery
        ├── outlined_label.py               # Custom glowing text widget
        ├── validators.py                   # Input validation helpers
        ├── utils.py                        # Shared GUI utilities
        │
        ├── dialogs/                        # Additional dialog windows
        ├── calculators/                    # Subnet & VLSM calculator tools
        ├── web/                            # Embedded web view components
        ├── icons/                          # UI icon assets
        │
        ├── wizards/
        │   ├── guided_setup_wizard.py      # Core network logic generator (multi-step)
        │   └── config_engine.py            # Builds raw Cisco IOS config strings
        │
        ├── logo.png / logo.svg             # ANCS brand assets
        ├── ancs_logo.ico                   # Window icon
        ├── bg.png                          # Animated background
        └── [Orbitron / Michroma / Audiowide / Montserrat].ttf  # Custom fonts
```

---

## 🤖 AI Copilot

The ANCS AI Copilot is a **fully agentic network assistant** — not a simple chatbot. It maintains a live pooled Telnet/SSH session to every device in your topology and can act autonomously.

### Interface

| Panel | Description |
|---|---|
| **Chat** | Natural language interface — ask anything about your network |
| **Execution Logs** | Live view of every tool call and its raw result |
| **Console Stream** | Real-time colored output from device sessions and reasoning steps |
| **Structured Events** | Parsed tool call log with timestamps |
| **Topology (Agent)** | Live topology graph + per-device KPI cards (Devices, Configured, Pending, Connected) |

### Capabilities

| Capability | Description |
|---|---|
| **Connectivity Tracing** | Multi-hop ping/trace between any two nodes |
| **Security Audit** | ACL review, open port scan, routing anomaly detection |
| **Config Generation** | Full Cisco IOS block generation from topology |
| **Console Execution** | Direct CLI on any device via the `sender.py` pool |
| **Protocol Validation** | Validates RIP, OSPF, EIGRP consistency across devices |
| **Live Sync** | Pulls `running-config` before acting to avoid blind overwrites |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **UI Framework** | PySide6 (Qt 6) |
| **AI Backend** | Google Gemini (`google-genai`) via Vertex AI |
| **Async Telnet** | `telnetlib3` |
| **SSH** | `paramiko` |
| **Serial (fallback)** | `pyserial` |
| **GNS3 Integration** | REST API via `network/gns3.py` |
| **Database** | SQLite (Python data classes, no ORM) |
| **Custom Fonts** | Orbitron, Michroma, Audiowide, Montserrat |
| **Build Tool** | PyInstaller via `setup_build.py` |

---

## 📄 License

This project is licensed under the **MIT License**.

---

<div align="center">

Made with ❤️ by <a href="https://github.com/zyada7med2"><strong>Zyad Ahmed</strong></a>

<sub>Computer Science Student · Cyber Security Enthusiast · Cairo, Egypt</sub>

</div>
