<div align="center">

<!-- Logo / Banner -->
<img src="https://raw.githubusercontent.com/zyada7med2/ANCS/main/figma_preview.png" alt="ANCS Banner" width="800" style="border-radius:12px"/>

<br/>
<br/>

<h1>
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=700&size=32&pause=1000&color=00C6FF&center=true&vCenter=true&width=600&lines=ANCS+%E2%80%94+Auto+Network+Config+System;AI-Powered+Network+Management;GNS3+Integration+%2B+Smart+Wizards" alt="Typing SVG" />
</h1>

<p align="center">
  <strong>A modern desktop application for network device configuration management<br/>with GNS3 integration and an embedded Agentic AI Copilot.</strong>
</p>

<br/>

<!-- Badges -->
<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/PySide6-Qt%20Framework-41CD52?style=for-the-badge&logo=qt&logoColor=white" alt="PySide6"/>
  <img src="https://img.shields.io/badge/AI-Gemini%20Powered-4285F4?style=for-the-badge&logo=google&logoColor=white" alt="Gemini AI"/>
  <img src="https://img.shields.io/badge/GNS3-Integration-FF6600?style=for-the-badge&logo=cisco&logoColor=white" alt="GNS3"/>
  <img src="https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge" alt="MIT License"/>
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#-installation">Installation</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-ai-copilot">AI Copilot</a> •
  <a href="#-tech-stack">Tech Stack</a>
</p>

</div>

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🤖 Agentic AI Copilot
Powered by **Google Gemini**, the built-in AI brain can:
- Run multi-hop connectivity traces
- Audit network security & routing protocol mismatches
- Auto-generate device configurations from topology
- Interact directly with device consoles

</td>
<td width="50%">

### 🔁 Live State Sync
Pull live `running-config` from devices using smart parsing:
- Detects existing VLANs, IPs, and routing protocols
- Prevents blind configuration overwrites
- Works seamlessly with physical and virtual devices

</td>
</tr>
<tr>
<td width="50%">

### 🗺️ Topology Management
- Import entire network topologies from **GNS3** in one click
- Manage Routers, Switches, and Core Switches
- Visual topology graph with live device status

</td>
<td width="50%">

### ⚡ Smart Guided Wizards
Step-by-step wizards that intelligently auto-derive:
- DHCP pools & static routes
- ACL rules
- Routing protocols: **RIP**, **OSPF**, **EIGRP**

</td>
</tr>
<tr>
<td width="50%">

### 🖥️ Modern Glass UI
- Custom-themed **dark mode** PySide6 interface
- True glass transparency & responsive geometry
- Custom widget components — zero default Qt styling

</td>
<td width="50%">

### 🚀 Async Network Engine
- High-performance concurrent deployments
- **Telnet** (`telnetlib3`) + **SSH** (`paramiko`) support
- UI never freezes during long deployments

</td>
</tr>
</table>

---

## 📦 Installation

> **Requirements:** Python 3.10+, GNS3 (optional), Windows/Linux

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
# Executable is generated in build/
```

---

## 🏗️ Architecture

```
ANCS/
├── run.py                            # 🚀 Primary entry point
├── network_manager/
│   ├── main.py                       # App initialisation
│   ├── config.py                     # Global styling tokens & DB path
│   ├── ai_agent.py                   # 🤖 AI Copilot — logic & tool definitions
│   ├── models/
│   │   └── devices.py                # SQLite data classes (Router, Switch, CoreSwitch)
│   ├── network/
│   │   ├── sender.py                 # Async CLI execution (telnetlib3, paramiko)
│   │   ├── puller.py                 # Connects to live devices & scrapes configs
│   │   ├── parser.py                 # Parses live config into structured wizard data
│   │   └── gns3.py                   # GNS3 local server API client
│   └── gui/
│       ├── app.py                    # Main PySide6 window & routing layout
│       ├── wizards/
│       │   ├── guided_setup_wizard.py # Core network logic generator
│       │   └── config_engine.py      # Builds raw Cisco IOS strings
│       ├── terminal_panel.py         # 💻 Live interactive device console
│       └── topology_viewer.py        # 🗺️ Network graph visualisation
```

---

## 🤖 AI Copilot

The **ANCS AI Copilot** is not a simple chatbot — it's a fully agentic network assistant embedded directly into the application. It holds a live connection to all your managed devices and can:

| Capability | Description |
|---|---|
| **Connectivity Tracing** | Traces multi-hop paths between any two nodes in your topology |
| **Security Auditing** | Detects ACL misconfigurations, open ports, and routing anomalies |
| **Config Generation** | Auto-builds Cisco IOS config blocks from your topology structure |
| **Console Interaction** | Directly executes CLI commands on devices via `sender.py` |
| **Protocol Awareness** | Understands and validates RIP, OSPF, and EIGRP configurations |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **UI Framework** | PySide6 (Qt 6) |
| **AI Backend** | Google Gemini (`google-genai`) |
| **Async Telnet** | `telnetlib3` |
| **SSH** | `paramiko` |
| **GNS3 Integration** | REST API via `gns3.py` |
| **Database** | SQLite (via Python data classes) |
| **Serial (fallback)** | `pyserial` |
| **Build Tool** | PyInstaller (`setup_build.py`) |

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

Made with ❤️ by <a href="https://github.com/zyada7med2"><strong>Zyad Ahmed</strong></a>

<sub>Computer Science Student · Cyber Security Enthusiast · Cairo, Egypt</sub>

</div>
