"""
ANCS - Auto Network Configuration System
Main launcher script

Run this file from the ANCS directory:
    python run.py
"""
import sys
import os

# Add current directory to path so network_manager package can be found
if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    from network_manager.main import main
    main()

