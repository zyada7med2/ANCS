"""
ANCS - Auto Network Configuration System
Main launcher script

Run this file from the ANCS directory:
    python run.py
"""
import sys
import os
import subprocess


def _venv_python_path(project_root: str) -> str:
    if os.name == "nt":
        return os.path.join(project_root, ".venv", "Scripts", "python.exe")
    return os.path.join(project_root, ".venv", "bin", "python")


def _maybe_reexec_in_venv(project_root: str) -> None:
    """Relaunch with local .venv interpreter to avoid dependency mismatches."""
    venv_python = _venv_python_path(project_root)
    if not os.path.exists(venv_python):
        return

    current_python = os.path.abspath(sys.executable)
    target_python = os.path.abspath(venv_python)
    if current_python.lower() == target_python.lower():
        return

    if os.environ.get("ANCS_VENV_REEXEC") == "1":
        return

    env = os.environ.copy()
    env["ANCS_VENV_REEXEC"] = "1"
    subprocess.run([target_python, os.path.abspath(__file__)], env=env, check=False)
    raise SystemExit(0)

# Add current directory to path so network_manager package can be found
if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    _maybe_reexec_in_venv(current_dir)
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    from network_manager.main import main
    main()

