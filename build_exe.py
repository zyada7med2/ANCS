"""
Build ANCS as a standalone Windows executable.

Requires: pip install pyinstaller
Run from ANCS directory: python build_exe.py

Output: dist/ANCS.exe
"""
import subprocess
import sys
import os

def main():
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)
    
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "ANCS.spec"]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print("\nDone! Executable: dist/ANCS.exe")

if __name__ == "__main__":
    main()
