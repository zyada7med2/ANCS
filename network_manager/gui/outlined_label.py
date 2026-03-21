import sys
from PySide6.QtWidgets import QLabel, QApplication
from PySide6.QtGui import QPainter, QPen, QColor, QFontMetrics, QPainterPath
from PySide6.QtCore import Qt, QSize

class OutlinedLabel(QLabel):
    """
    A specialized QLabel that synthesizes a thick bold stroke using raw QPainter.
    Used for fonts that do not possess native bold glyphs (e.g., Michroma-Regular).
    """
    def __init__(self, text, stroke_width=2, *args, **kwargs):
        super().__init__(text, *args, **kwargs)
        self.stroke_width = stroke_width

    def sizeHint(self):
        metrics = QFontMetrics(self.font())
        # Account for letter-spacing explicitly plus extra buffer for thick strokes
        base_width = metrics.horizontalAdvance(self.text())
        return QSize(base_width + self.stroke_width * 4 + 10, metrics.height() + self.stroke_width * 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        path = QPainterPath()
        font = self.font()
        metrics = QFontMetrics(font)
        
        # Ascent is the distance from the baseline to the top of the highest character.
        # Add stroke width buffer on x to prevent the 'A' from clipping the left boundary.
        x_offset = self.stroke_width + 4
        y_offset = (self.height() + metrics.ascent() - metrics.descent()) / 2
        
        path.addText(x_offset, y_offset, font, self.text())
        
        # Draw the extremely thick outline
        pen = QPen(QColor(255, 255, 255), self.stroke_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.strokePath(path, pen)
        
        # Fill it inside
        painter.fillPath(path, QColor(255, 255, 255))
