from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPixmapCache
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QWidget

from .theme import THEMES

IMAGE_ROLE = Qt.UserRole + 1


class GalleryModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        item = self.items[index.row()]
        if role == Qt.DisplayRole:
            return item["name"]
        if role == IMAGE_ROLE:
            return item
        if role == Qt.ToolTipRole:
            return f"{item['name']}\n{item['width']} × {item['height']}\n{item['status'].capitalize()}" + (f"\n{item['error']}" if item["error"] else "")

    def replace(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()


class GalleryDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tile_width = 202
        self.theme = "dark"
        QPixmapCache.setCacheLimit(64 * 1024)

    def sizeHint(self, option, index):
        return QSize(self.tile_width + 14, int(self.tile_width * 1.24) + 65)

    def paint(self, painter, option, index):
        item = index.data(IMAGE_ROLE)
        if not item:
            return
        c = THEMES[self.theme]
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        outer = QRectF(option.rect).adjusted(6, 6, -7, -7)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.setBrush(QColor(c["selection"] if selected else c["surface"] if hovered else c["panel"]))
        painter.setPen(QPen(QColor(c["accent"] if selected else c["border"]), 1.5 if selected else 1))
        painter.drawRoundedRect(outer, 10, 10)
        photo = QRectF(outer.x() + 5, outer.y() + 5, outer.width() - 10, outer.height() - 58)
        path = QPainterPath()
        path.addRoundedRect(photo, 7, 7)
        painter.setClipPath(path)
        painter.fillRect(photo, QColor(c["bg"]))
        cache_key = item["thumbnail"]
        pixmap = QPixmapCache.find(cache_key)
        if pixmap is None:
            pixmap = QPixmap(cache_key)
            if not pixmap.isNull():
                QPixmapCache.insert(cache_key, pixmap)
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(photo.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = photo.x() + (photo.width() - scaled.width()) / 2
            y = photo.y() + (photo.height() - scaled.height()) / 2
            painter.drawPixmap(int(x), int(y), scaled)
        else:
            painter.setPen(QColor(c["muted"]))
            painter.drawText(photo, Qt.AlignCenter, "Preview unavailable")
        painter.setClipping(False)
        if item.get("match_score") is not None:
            badge = QRectF(photo.x() + 8, photo.y() + 8, 94, 25)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(c["accent"]))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(c["accent_text"]))
            painter.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
            painter.drawText(badge, Qt.AlignCenter, f"{item['match_score']:.1f} match")
        if item["favorite"]:
            painter.setPen(QColor("#f4d593"))
            painter.setFont(QFont("Segoe UI Symbol", 15))
            painter.drawText(QRectF(photo.right() - 28, photo.y() + 5, 24, 28), Qt.AlignCenter, "★")
        painter.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        painter.setPen(QColor(c["text"]))
        name_rect = QRectF(outer.x() + 11, photo.bottom() + 8, outer.width() - 22, 20)
        painter.drawText(name_rect, Qt.AlignVCenter, painter.fontMetrics().elidedText(item["name"], Qt.ElideMiddle, int(name_rect.width())))
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor(c["muted"]))
        status = {"pending": "Queued for analysis", "ready": "Reviewed" if item["reviewed"] else "AI analyzed · review", "error": "Analysis needs attention"}.get(item["status"], item["status"])
        if item["status"] == "online":
            status = f"{item['width']} × {item['height']} · {item['source']}"
        status = painter.fontMetrics().elidedText(status, Qt.ElideRight, int(name_rect.width()))
        painter.drawText(QRectF(name_rect.x(), name_rect.bottom() + 1, name_rect.width(), 17), Qt.AlignVCenter, status)
        painter.restore()


class GalleryView(QListView):
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setLayoutMode(QListView.Batched)
        self.setBatchSize(100)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.ExtendedSelection)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListView.DropOnly)
        self.setSpacing(0)
        self.setAccessibleName("Image gallery. Use Control or Shift to select multiple images. Double-click to edit.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class EmptyArt(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(224, 150)
        self.setAccessibleName("Illustration of an organized photo collection")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = [("#3a5141", -12, -27), ("#5e7862", 12, 25), ("#bed8b2", 0, 0)]
        for color, angle, shift in colors:
            painter.save()
            painter.translate(112 + shift, 77)
            painter.rotate(angle)
            painter.setPen(QPen(QColor("#819d80"), 1))
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(-43, -57, 86, 114), 8, 8)
            if angle == 0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#6b8b60"))
                painter.drawRoundedRect(QRectF(-34, -47, 68, 78), 4, 4)
                painter.setBrush(QColor("#d6e3b9"))
                painter.drawEllipse(QRectF(3, -34, 15, 15))
                mountains = QPainterPath()
                mountains.moveTo(-34, 31)
                mountains.lineTo(-34, 8)
                mountains.lineTo(-10, -14)
                mountains.lineTo(9, 8)
                mountains.lineTo(19, -1)
                mountains.lineTo(34, 19)
                mountains.lineTo(34, 31)
                mountains.closeSubpath()
                painter.setBrush(QColor("#91ac7f"))
                painter.drawPath(mountains)
                painter.setBrush(QColor("#769570"))
                painter.drawRoundedRect(QRectF(-30, 41, 42, 4), 2, 2)
            painter.restore()
