import unittest
import sys
import os

if __name__ == '__main__':
    # Add parent directory to sys.path
    start_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(start_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        
    # We build the suite explicitly to avoid importing test_routing_protocols.py 
    # which is a procedural script that requires PySide6 (GUI framework).
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    
    test_modules = [
        'test_parser',
        'test_devices',
        'test_puller',
        'test_sender',
        'test_gns3'
    ]
    
    for module_name in test_modules:
        try:
            # We import relatively from the current directory context
            mod = __import__(module_name)
            suite.addTests(loader.loadTestsFromModule(mod))
        except ImportError as e:
            print(f"Failed to load {module_name}: {e}")

    print("\nRunning Core Unit Tests:")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "="*70)
    print("NOTE: 'test_routing_protocols.py' is a procedural UI test script.")
    print("To run it, you must first install the GUI dependencies:")
    print("   pip install -r requirements.txt")
    print("Then run it directly:")
    print("   python test_routing_protocols.py")
    print("="*70 + "\n")
    
    if not result.wasSuccessful():
        sys.exit(1)
