from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QSize, QUrl, QPoint
from PySide6.QtGui import QDesktopServices, QIcon, QImageReader, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFrame, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSlider, QStackedWidget, QVBoxLayout, QWidget, QMenu, QWidgetAction)

from .config import model_ready
from .gallery import EmptyArt, GalleryDelegate, GalleryModel, GalleryView, IMAGE_ROLE
from .online import ImageCache, reference_discovery_task, public_url, quality_passes, save_to_library, suggested_terms
from .workers import Task


def text_label(text, style="muted"):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setObjectName(style)
    widget.setWordWrap(True)
    return widget


def action(text, callback, style=""):
    widget = QPushButton(text)
    widget.setObjectName(style)
    widget.clicked.connect(callback)
    return widget


class PhotoCanvas(QGraphicsView):
    navigate = Signal(int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.photo = self.scene().addPixmap(QPixmap())
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: #090b0d; border: 0;")
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHints(self.renderHints() | QPainter.SmoothPixmapTransform)
        self.zoom = 1.0
        self.press_point = None
        self.grabGesture(Qt.PinchGesture)
        self.grabGesture(Qt.SwipeGesture)
        self.setAccessibleName("Photo. Wheel to zoom, drag to pan, swipe or use arrow keys for the next image.")

    def load(self, path):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if max(size.width(), size.height()) > 6144:
            size.scale(6144, 6144, Qt.KeepAspectRatio)
            reader.setScaledSize(size)
        image = reader.read()
        if image.isNull():
            return False
        self.photo.setPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.photo.boundingRect())
        self.fit()
        return True

    def fit(self):
        if not self.photo.pixmap().isNull():
            self.resetTransform()
            self.fitInView(self.photo, Qt.KeepAspectRatio)
        self.zoom = 1.0
        self.setDragMode(QGraphicsView.NoDrag)

    def set_zoom(self, factor):
        target = min(10., max(1., self.zoom * factor))
        self.scale(target / self.zoom, target / self.zoom)
        self.zoom = target
        self.setDragMode(QGraphicsView.ScrollHandDrag if self.zoom > 1.01 else QGraphicsView.NoDrag)

    def wheelEvent(self, event):
        self.set_zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.fit() if self.zoom > 1.01 else self.set_zoom(2.5)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.zoom <= 1.01:
            self.fit()

    def mousePressEvent(self, event):
        self.press_point = event.position() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.press_point is not None and self.zoom <= 1.01:
            delta = event.position() - self.press_point
            if abs(delta.x()) > 85 and abs(delta.x()) > abs(delta.y()) * 1.5:
                self.navigate.emit(1 if delta.x() < 0 else -1)
        self.press_point = None
        super().mouseReleaseEvent(event)

    def event(self, event):
        if event.type() == QEvent.Gesture:
            if pinch := event.gesture(Qt.PinchGesture):
                self.set_zoom(pinch.scaleFactor() / max(.01, pinch.lastScaleFactor()))
            if swipe := event.gesture(Qt.SwipeGesture):
                if swipe.state() == Qt.GestureFinished:
                    direction = swipe.horizontalDirection()
                    if direction == swipe.Left:
                        self.navigate.emit(1)
                    elif direction == swipe.Right:
                        self.navigate.emit(-1)
            return True
        return super().event(event)


class PhotoViewer(QDialog):
    def __init__(self, items, index, cache, owner):
        super().__init__(owner)
        self.setWindowTitle("Photo viewer · FapFinder")
        self.setModal(True)
        self.setStyleSheet("QDialog { background: #090b0d; } QLabel { color: #edf0ed; }")
        self.items = items
        self.cache = cache
        self.owner = owner
        self.index = -1
        self.generation = 0
        self.task = None
        self.full_path = None
        self._closing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 14, 22, 14)
        top = QHBoxLayout()
        self.caption = text_label("", "sectionTitle")
        self.caption.setMaximumHeight(48)
        top.addWidget(self.caption, 1)
        self.counter = text_label("")
        top.addWidget(self.counter)
        top.addWidget(action("Fit", lambda: self.canvas.fit()))
        top.addWidget(action("−", lambda: self.canvas.set_zoom(1 / 1.3)))
        top.addWidget(action("＋", lambda: self.canvas.set_zoom(1.3)))
        top.addWidget(action("Close  ×", self.close))
        layout.addLayout(top)
        middle = QHBoxLayout()
        self.previous = action("‹", lambda: self.move(-1))
        self.previous.setFixedSize(44, 72)
        self.previous.setAccessibleName("Previous photo")
        middle.addWidget(self.previous)
        self.canvas = PhotoCanvas()
        self.canvas.navigate.connect(self.move)
        middle.addWidget(self.canvas, 1)
        self.next = action("›", lambda: self.move(1))
        self.next.setAccessibleName("Next photo")
        self.next.setFixedSize(44, 72)
        middle.addWidget(self.next)
        layout.addLayout(middle, 1)
        bottom = QHBoxLayout()
        self.details = text_label("")
        bottom.addWidget(self.details, 1)
        self.source_button = action("Open source ↗", self.open_source)
        bottom.addWidget(self.source_button)
        self.save_button = action("Save to library", self.save, "primary")
        bottom.addWidget(self.save_button)
        layout.addLayout(bottom)
        self.strip = QListWidget()
        self.strip.setViewMode(QListWidget.IconMode)
        self.strip.setFlow(QListWidget.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setMovement(QListWidget.Static)
        self.strip.setIconSize(QSize(62, 66))
        self.strip.setGridSize(QSize(74, 80))
        self.strip.setFixedHeight(96)
        self.strip.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.strip.setAccessibleName("Photo filmstrip")
        for row in items:
            item = QListWidgetItem(QIcon(row["thumbnail"]), "")
            item.setToolTip(row["name"])
            self.strip.addItem(item)
        self.strip.currentRowChanged.connect(self.show_index)
        layout.addWidget(self.strip)
        hint = text_label("← →  Next / previous     ·     Scroll or double-click to zoom     ·     Drag to pan / swipe     ·     Esc to close")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
        for sequence, callback in (("Left", lambda: self.move(-1)), ("Right", lambda: self.move(1)),
                                   ("Home", lambda: self.show_index(0)), ("End", lambda: self.show_index(len(items) - 1))):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.load_original)
        self.show_index(index)

    def move(self, step):
        self.show_index(max(0, min(len(self.items) - 1, self.index + step)))

    def show_index(self, index):
        if index == self.index or not 0 <= index < len(self.items):
            return
        self.index = index
        self.generation += 1
        if self.task:
            self.task.stop()
        row = self.items[index]
        self.full_path = None
        self.caption.setText(row["name"])
        self.counter.setText(f"{index + 1} / {len(self.items)}")
        self.previous.setEnabled(index > 0)
        self.next.setEnabled(index + 1 < len(self.items))
        self.save_button.setEnabled(False)
        self.canvas.load(row["thumbnail"])
        self.details.setText(f"{row['source']} · {row.get('match_score', 0):.1f} match · Loading original…")
        self.strip.blockSignals(True)
        self.strip.setCurrentRow(index)
        self.strip.scrollToItem(self.strip.item(index), QAbstractItemView.PositionAtCenter)
        self.strip.blockSignals(False)
        self.timer.start()

    def load_original(self):
        if self.task or self._closing:
            return
        generation = self.generation
        row = self.items[self.index]
        def work(task):
            return self.cache.image(row["image_url"], original=True, stop=task.isInterruptionRequested)
        self.begin(work, generation, self.original_ready)

    def begin(self, function, generation, callback, saving=False):
        task = Task(function, self)
        self.task = task
        task.output, task.failure = None, None
        task.result.connect(lambda result: setattr(task, "output", result))
        task.failed.connect(lambda error: setattr(task, "failure", error))
        def finished():
            self.task = None
            if self._closing:
                self.close()
            elif generation != self.generation:
                self.timer.start()
            elif task.failure:
                self.details.setText("Could not save this image: " + task.failure if saving else
                    "Original unavailable. The small preview is shown. Open the source page to view it there.")
                self.details.setToolTip(task.failure)
                self.save_button.setEnabled(saving and self.full_path is not None)
            elif not isinstance(task.output, dict) or not task.output.get("cancelled"):
                callback(task.output)
            task.deleteLater()
        task.finished.connect(finished)
        task.start()

    def original_ready(self, result):
        path, width, height = result
        row = self.items[self.index]
        self.full_path = path
        displayed = self.canvas.load(path)
        self.details.setToolTip("")
        self.details.setText(f"{row['source']} · {width:,} × {height:,} px · {row.get('match_score', 0):.1f} match"
                             + (" · Original loaded" if displayed else " · Preview shown; original ready to save"))
        if not quality_passes({"width": width, "height": height}, row.get("minimum_resolution", 0)):
            self.details.setText(self.details.text() + " · Source is smaller than search reported")
        self.save_button.setEnabled(True)

    def open_source(self):
        QDesktopServices.openUrl(QUrl(public_url(self.items[self.index]["source_url"])))

    def save(self):
        if self.task or not self.full_path:
            return
        path, row = self.full_path, dict(self.items[self.index])
        self.save_button.setEnabled(False)
        self.details.setText("Saving the original to your library…")
        def done(result):
            self.details.setText(result["message"])
            self.owner.refresh()
        self.begin(lambda task: save_to_library(path, row, self.owner.paths, self.owner.db), self.generation, done, saving=True)

    def reject(self):
        self.close()

    def closeEvent(self, event):
        self.timer.stop()
        if self.task:
            self._closing = True
            self.task.stop()
            self.hide()
            event.ignore()
        else:
            self.cache.prune()
            self.done(QDialog.Rejected)
            event.accept()


class OnlinePage(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.setObjectName("page")
        self.owner = owner
        self.cache = ImageCache(owner.paths.root)
        self.reference = None
        self.weights = {}
        self.page = 0
        self.busy = False
        self.has_more = False
        self.search_terms = ""
        self.search_minimum = 1280
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(text_label("DISCOVER SOMETHING NEW", "eyebrow"))
        title.addWidget(text_label("Explore online", "title"))
        title.addWidget(text_label("Find similar photos automatically from a photo in your library."))
        header.addLayout(title, 1)
        header.addWidget(action("← Library", lambda: owner.change_view("all")))
        layout.addLayout(header)
        reference_box = QFrame()
        reference_box.setObjectName("settingsCard")
        reference_layout = QHBoxLayout(reference_box)
        self.reference_preview = QLabel()
        self.reference_preview.setFixedSize(58, 66)
        self.reference_preview.setAlignment(Qt.AlignCenter)
        self.reference_preview.hide()
        reference_layout.addWidget(self.reference_preview)
        self.reference_label = text_label("Select a library photo and choose Find similar online. No typing needed.")
        reference_layout.addWidget(self.reference_label, 1)
        self.clear_reference_button = action("Choose photo", lambda: owner.change_view("all"))
        reference_layout.addWidget(self.clear_reference_button)
        layout.addWidget(reference_box)
        controls = QHBoxLayout()
        self.terms = QLineEdit()
        self.terms.setMaxLength(400)
        self.terms.setReadOnly(True)
        self.terms.setPlaceholderText("Search description is generated from your selected photo")
        self.terms.setAccessibleName("Automatically generated search description; your photo remains local")
        self.terms.setToolTip("Generated from the photo's visual traits. Local filenames, notes, and typed library-search text are excluded.")
        controls.addWidget(self.terms, 1)
        self.traits_button = action("Traits & weights ▾", lambda: owner.toggle_filters(anchor=self.traits_button))
        controls.addWidget(self.traits_button)
        self.options_button = action("View options ▾", self.show_options)
        controls.addWidget(self.options_button)
        self.options_menu = QMenu(self)
        options = QFrame()
        options.setObjectName("settingsCard")
        options.setFixedWidth(280)
        option_layout = QVBoxLayout(options)
        option_layout.setContentsMargins(16, 16, 16, 16)
        option_layout.addWidget(text_label("Minimum resolution", "sectionTitle"))
        self.quality = QComboBox()
        self.quality.addItem("HD · 1280 px+", 1280)
        self.quality.addItem("Full HD · 1920 px+", 1920)
        self.quality.addItem("Large · any size", 0)
        self.quality.setToolTip("Minimum longest edge, with the shorter edge at least half. Search dimensions are checked again when you open the original.")
        self.quality.setAccessibleName("Minimum photo resolution")
        option_layout.addWidget(self.quality)
        self.search_button = action("Find matches", self.search, "primary")
        self.search_button.setEnabled(False)
        controls.addWidget(self.search_button)
        self.cancel_button = action("Stop", lambda: owner.pause_task())
        self.cancel_button.hide()
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        layout.addWidget(text_label("Search uses your photo’s generated description. Your photo stays local. Online results use SafeSearch."))
        bar = QHBoxLayout()
        self.summary = text_label("Select a photo in your library to start. Opening this page does not start a search.")
        bar.addWidget(self.summary, 1)
        self.sort = QComboBox()
        self.sort.addItems(["Best match", "Largest first"])
        self.sort.currentIndexChanged.connect(self.sort_rows)
        option_layout.addWidget(text_label("Order"))
        option_layout.addWidget(self.sort)
        option_layout.addWidget(text_label("Photo size"))
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(155, 310)
        self.size.setValue(220)
        self.size.setAccessibleName("Online gallery photo size")
        self.size.valueChanged.connect(self.resize_tiles)
        option_layout.addWidget(self.size)
        option_layout.addWidget(text_label("Resolution changes apply on the next search."))
        options_action = QWidgetAction(self.options_menu)
        options_action.setDefaultWidget(options)
        self.options_menu.addAction(options_action)
        layout.addLayout(bar)
        self.stack = QStackedWidget()
        self.gallery = GalleryView()
        self.gallery.setAcceptDrops(False)
        self.gallery.setSelectionMode(QAbstractItemView.SingleSelection)
        self.gallery.setAccessibleName("Online photo gallery. Click a photo to open the full-screen viewer.")
        self.model = GalleryModel(self)
        self.delegate = GalleryDelegate(self.gallery)
        self.delegate.tile_width = 220
        self.gallery.setModel(self.model)
        self.gallery.setItemDelegate(self.delegate)
        self.gallery.clicked.connect(lambda index: self.open_viewer(index.row()))
        self.gallery.activated.connect(lambda index: self.open_viewer(index.row()))
        self.stack.addWidget(self.gallery)
        self.empty = QWidget()
        empty = QVBoxLayout(self.empty)
        empty.setAlignment(Qt.AlignCenter)
        empty.addWidget(EmptyArt(), 0, Qt.AlignHCenter)
        empty.addWidget(text_label("Your next discovery", "sectionTitle"), 0, Qt.AlignHCenter)
        self.empty_label = text_label("Choose a photo in your library, then click Find similar online.")
        empty.addWidget(self.empty_label, 0, Qt.AlignHCenter)
        self.stack.addWidget(self.empty)
        layout.addWidget(self.stack, 1)
        footer = QHBoxLayout()
        footer.addWidget(text_label("Click to open · Arrow keys or swipe to browse · Match scores are rankings, not probabilities."), 1)
        self.more_button = action("Load more photos", lambda: self.search(more=True))
        self.more_button.setEnabled(False)
        footer.addWidget(self.more_button)
        layout.addLayout(footer)
        self.cache.prune()
        session = self.cache.load_session()
        self.model.replace(session["items"])
        self.terms.setText(session["terms"])
        self.stack.setCurrentWidget(self.gallery if session["items"] else self.empty)
        if session["items"]:
            self.summary.setText(f"{len(session['items'])} cached photos · Choose a library photo for a new search. Opening uncached originals uses the internet.")
        self._viewer_open = False

    def prepare(self, image=None, query=None):
        self.reference = image
        self.weights = {key: weight for key, weight in query.weights.items() if key[0] != "height"} if query else {}
        self.terms.setText(suggested_terms(image=image) if image else "")
        self.show_reference()
        self.more_button.setEnabled(False)
        self.has_more = False
        self.model.replace([])
        self.stack.setCurrentWidget(self.empty)
        self.search_button.setEnabled(bool(image))
        self.empty_label.setText("Finding similar photos from your selected image…")
        self.summary.setText("Using your photo automatically." + (f" {len(self.weights)} trait weights will also rank results locally." if self.weights else ""))

    def show_reference(self):
        self.reference_preview.setVisible(bool(self.reference))
        self.clear_reference_button.setText("Change photo" if self.reference else "Choose photo")
        if self.reference:
            self.reference_preview.setPixmap(QPixmap(self.reference["thumbnail"]).scaled(58, 66, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.reference_label.setText("Finding a similar look · Your selected photo stays on this computer.")
        else:
            self.reference_label.setText("Select a library photo and choose Find similar online. No typing needed.")

    def clear_reference(self):
        if not self.busy:
            self.reference = None
            self.show_reference()
            self.has_more = False
            self.more_button.setEnabled(False)
            self.model.replace([])
            self.stack.setCurrentWidget(self.empty)
            self.terms.clear()
            self.search_button.setEnabled(False)
            self.summary.setText("Choose another library photo to search for similar images.")

    def show_options(self):
        self.options_menu.popup(self.options_button.mapToGlobal(QPoint(0, self.options_button.height())))

    def set_busy(self, busy):
        self.busy = busy
        for control in (self.terms, self.quality, self.clear_reference_button, self.traits_button):
            control.setEnabled(not busy)
        self.search_button.setEnabled(not busy and self.reference is not None)
        self.cancel_button.setVisible(busy)
        self.more_button.setEnabled(not busy and self.has_more)

    def search(self, checked=False, more=False):
        if self.owner.task is not None or self.busy:
            self.summary.setText("A task is still running. Stop it or wait for it to finish, then search.")
            return
        if self.reference is None:
            self.summary.setText("Choose a library photo first. Online search is based on that photo.")
            return
        if not model_ready(self.owner.paths):
            self.summary.setText("Install the local AI model in Settings to compare online images privately.")
            return
        terms = suggested_terms(image=self.reference)
        # A resolution change starts a new ranking session.
        more = more and terms == self.search_terms and self.quality.currentData() == self.search_minimum and self.has_more
        if not more:
            self.page = 0
            self.has_more = False
            self.model.replace([])
            self.stack.setCurrentWidget(self.empty)
            self.search_terms = terms
            self.search_minimum = self.quality.currentData()
            self.cache.prune()
        page = self.page + 1
        self.set_busy(True)
        self.empty_label.setText("Finding photos and comparing them locally…")
        self.summary.setText("Searching… Results will appear here when their local comparison finishes.")
        seen = [row["id"] for row in self.model.items]
        def done(result):
            if result.get("cancelled"):
                self.summary.setText("Search stopped. Your existing results are still available.")
                self.empty_label.setText("Search stopped. Press Find matches to try again.")
                return
            self.reference = result["reference"]
            self.search_terms = result["terms"]
            self.terms.setText(self.search_terms)
            self.page = result["page"]
            hashes = {row["preview_hash"] for row in self.model.items}
            incoming = [row for row in result["items"] if row["preview_hash"] not in hashes]
            rows = self.model.items + incoming
            self.model.replace(rows)
            self.sort_rows()
            self.has_more = result["more"] and len(rows) < 500 and (bool(incoming) or result["eligible"] == 0)
            self.more_button.setEnabled(self.has_more)
            self.stack.setCurrentWidget(self.gallery if rows else self.empty)
            self.empty_label.setText("No photos matched this time. Try another reference photo or a lower resolution in View options.")
            message = f"{len(rows)} photos · {len(incoming)} new · Compared locally · Dimensions reported by search"
            if result["errors"]:
                message += f" · {len(result['errors'])} unavailable previews skipped"
            if not incoming and rows:
                message += " · No new matches on this page"
            self.summary.setText(message)
            self.cache.save_session(self.search_terms, rows)
            self.owner.status_label.setText("Online search complete. Your reference photo stayed on this computer.")
        def failed(message):
            self.summary.setText(message)
            self.empty_label.setText("Search is unavailable right now. Try again later or use your offline library.")
        self.owner.start_task("Searching online", reference_discovery_task(self.cache, self.owner.engine, self.owner.db,
            self.reference, page, self.search_minimum, dict(self.weights), seen), done, failed, lambda: self.set_busy(False))

    def sort_rows(self, *_):
        rows = self.model.items.copy()
        rows.sort(key=(lambda r: -(r["width"] * r["height"])) if self.sort.currentIndex() else (lambda r: -r.get("match_score", 0)))
        self.model.replace(rows)

    def resize_tiles(self, size):
        self.delegate.tile_width = size
        self.gallery.doItemsLayout()

    def open_viewer(self, index):
        if self._viewer_open or not 0 <= index < len(self.model.items):
            return
        self._viewer_open = True
        viewer = PhotoViewer(self.model.items.copy(), index, self.cache, self.owner)
        viewer.showFullScreen()
        viewer.exec()
        viewer.deleteLater()
        self._viewer_open = False
        if self.owner.prefs["auto_analyze"] and self.owner.task is None and self.owner.db.pending():
            QTimer.singleShot(0, self.owner.analyze_queue)
