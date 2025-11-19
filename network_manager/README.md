# Network Manager - ANCS

**Auto Network Configuration System**

A desktop application for network device configuration management with GNS3 integration.

## Project Structure

```
network_manager/
├── main.py                 # Entry point - run this to start the app
├── config.py              # Configuration constants and database setup
├── models/
│   ├── __init__.py
│   └── devices.py         # Device model classes (Router, Switch, CoreSwitch)
├── network/
│   ├── __init__.py
│   ├── sender.py          # Network communication (Serial, Telnet, SSH)
│   └── gns3.py            # GNS3 API connector
├── gui/
│   ├── __init__.py
│   ├── app.py            # Main application window
│   ├── wizards/
│   │   ├── __init__.py
│   │   ├── vlan_wizard.py    # VLAN configuration wizard
│   │   └── stp_wizard.py     # STP configuration wizard
│   ├── calculators/
│   │   ├── __init__.py
│   │   └── subnet_calculator.py  # Subnet calculator GUI
│   └── dialogs/
│       ├── __init__.py
│       └── text_editor.py      # Text editor popup
└── requirements.txt       # Python dependencies
```

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python -m network_manager.main
```

Or from the project root:
```bash
python network_manager/main.py
```

## Building Executable

To create an executable using cx_Freeze:

```bash
python setup_build.py build
```

The executable will be in the `build/exe.win-amd64-3.x/` directory.

## Features

- **Device Management**: Create and manage router, switch, and core switch configurations
- **Template System**: Create reusable configuration templates
- **GNS3 Integration**: Auto-import devices from GNS3 projects
- **Network Communication**: Send configurations via Serial, Telnet, or SSH
- **Wizards**: GUI wizards for VLAN and STP configuration
- **Subnet Calculator**: Calculate and plan network subnets
- **Database**: SQLite database for device and configuration persistence

## Requirements

- Python 3.7+
- customtkinter
- sqlite3 (built-in)
- Optional: paramiko (for SSH), pyserial (for serial), requests (for GNS3)

