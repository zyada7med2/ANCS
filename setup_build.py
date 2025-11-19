from cx_Freeze import setup, Executable
import os

build_options = {
    "packages": [
        "customtkinter",
        "tkinter",
        "network_manager",
    ],
    "include_files": [
        ("network_manager/gui/ancs_logo.png", "gui/ancs_logo.png"),
        ("network_manager/gui/ancs_logo.ico", "gui/ancs_logo.ico"),
    ],
    "excludes": [],
}

base = "Win32GUI"

setup(
    name="ANCS",
    version="1.0",
    description="Auto Network Configuration System",
    options={"build_exe": build_options},
    executables=[Executable("network_manager/main.py", base=base, target_name="ANCS.exe")],
)

