import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QScreen

def take_screenshot():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        
    screen = QApplication.primaryScreen()
    screenshot = screen.grabWindow(0)
    screenshot.save("C:\\Users\\Zyad\\.gemini\\antigravity\\brain\\b67223ba-7a9e-4a15-8c43-acc22580ff50\\media__pyside.png", "png")
    print("Screenshot saved.")

take_screenshot()
