import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QScreen
from PySide6.QtCore import Qt

def take_screenshot(output_path: str = None, scale: float = 0.75, quality: int = 75):
    """
    Take a compressed screenshot of the primary screen.
    scale:   resize ratio (0.75 = 75% of original size — keeps files under 5 MB)
    quality: JPEG quality 1-100 (75 is a good balance)
    """
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    screen = QApplication.primaryScreen()
    pixmap = screen.grabWindow(0)

    # Scale down to reduce file size
    if scale != 1.0:
        new_w = int(pixmap.width() * scale)
        new_h = int(pixmap.height() * scale)
        pixmap = pixmap.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    if output_path is None:
        import os
        brain_dir = r"C:\Users\Zyad\.gemini\antigravity\brain"
        output_path = os.path.join(brain_dir, "screenshot.jpg")

    # Save as JPEG (much smaller than PNG)
    pixmap.save(output_path, "JPEG", quality)
    print(f"Screenshot saved to: {output_path}")
    return output_path

if __name__ == "__main__":
    take_screenshot()
