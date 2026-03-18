from cx_Freeze import setup, Executable
import os
import sys

build_options = {
    "packages": [
        "customtkinter",
        "tkinter",
        "network_manager",
        "sqlite3",
        "PIL",
        "paramiko",
        "serial",
        "requests",
    ],
    "include_files": [
        ("network_manager/gui/ancs_logo.png", "gui/ancs_logo.png"),
        ("network_manager/gui/ancs_logo.ico", "gui/ancs_logo.ico"),
    ],
    "excludes": ["matplotlib", "numpy", "scipy", "pandas"],
    "optimize": 2,
}

base = "Win32GUI" if sys.platform == "win32" else None

setup(
    name="ANCS",
    version="2.1.0",
    description="Auto Network Configuration System - Router-on-a-Stick & RIPv2 Support",
    author="ANCS Team",
    options={"build_exe": build_options},
    executables=[
        Executable(
            "network_manager/main.py",
            base=base,
            target_name="ANCS.exe",
            icon="network_manager/gui/ancs_logo.ico",
            shortcut_name="ANCS",
            shortcut_dir="DesktopFolder",
        )
    ],
)

