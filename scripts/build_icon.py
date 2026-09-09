from pathlib import Path
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication
from PIL import Image

root = Path(__file__).resolve().parent.parent
app = QApplication([])
renderer = QSvgRenderer(str(root / "assets" / "app.svg"))
image = QImage(256, 256, QImage.Format_ARGB32)
image.fill(0)
painter = QPainter(image)
renderer.render(painter)
painter.end()
target = root / "assets" / "app.png"
image.save(str(target))
with Image.open(target) as source:
    source.save(root / "assets" / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
