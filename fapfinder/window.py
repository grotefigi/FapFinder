from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget, QWidgetAction)

from .config import Paths, model_ready
from .database import Database
from .editor import TagEditor
from .gallery import EmptyArt, GalleryDelegate, GalleryModel, GalleryView, IMAGE_ROLE
from .search import SearchQuery, search, web_search_url
from .theme import apply_theme
from .traits import TRAITS
from .vision import VisionEngine
from .workers import Task, analyze_task, download_task, import_task
from .online_ui import OnlinePage


def label(text, style=None, wrap=False):
    item = QLabel(text)
    if style:
        item.setObjectName(style)
    item.setWordWrap(wrap)
    return item


def button(text, callback, style=None):
    item = QPushButton(text)
    if style:
        item.setObjectName(style)
    item.clicked.connect(callback)
    return item


class MainWindow(QMainWindow):
    def __init__(self, paths: Paths):
        super().__init__()
        self.paths = paths
        paths.initialize()
        self.db = Database(paths.database)
        self.prefs = paths.preferences()
        self.engine = VisionEngine(paths, self.prefs["device"])
        self.task = None
        self._closing = False
        self.view = "all"
        self.active_query = None
        self.last_text_embedding = None
        self._search_generation = 0
        self.result_rows = []
        self.setWindowTitle("FapFinder · Private image library")
        self.setMinimumSize(1060, 680)
        available = self.screen().availableGeometry()
        self.resize(min(1480, available.width() - 40), min(940, available.height() - 70))
        self.setAcceptDrops(True)
        self.setObjectName("mainWindow")
        self.build_ui()
        self.set_theme(self.prefs["theme"])
        self.bind_shortcuts()
        self.refresh()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_container = QWidget()
        nav = QVBoxLayout(nav_container)
        sidebar_scroll.setWidget(nav_container)
        sidebar_layout.addWidget(sidebar_scroll)
        nav.setContentsMargins(18, 28, 18, 20)
        nav.setSpacing(7)
        nav.addWidget(label("◈  FapFinder", "brand"))
        nav.addWidget(label("A library of your own.", "muted"))
        nav.addSpacing(34)
        nav.addWidget(label("WORKSPACE", "eyebrow"))
        self.nav_buttons = {}
        for key, text in (("all", "▦    All images"), ("favorites", "☆    Favorites"), ("review", "✓    To review"), ("pending", "◷    Analysis queue")):
            b = button(text, lambda checked=False, k=key: self.change_view(k), "nav")
            b.setCheckable(True)
            nav.addWidget(b)
            self.nav_buttons[key] = b
        self.online_nav = button("◎    Explore online", self.show_online, "nav")
        self.online_nav.setCheckable(True)
        nav.addWidget(self.online_nav)
        nav.addSpacing(22)
        nav.addWidget(label("LIBRARY TOOLS", "eyebrow"))
        nav.addWidget(button("＋    Import folder", self.import_folder, "nav"))
        nav.addWidget(button("↗    Export metadata", self.export_metadata, "nav"))
        nav.addStretch()
        self.model_status = label("LOCAL AI", "eyebrow")
        nav.addWidget(self.model_status)
        self.model_label = label("SigLIP 2\nReady for offline use", "muted", True)
        nav.addWidget(self.model_label)
        nav.addSpacing(12)
        nav.addWidget(button("⚙    Settings", self.show_settings, "nav"))
        self.theme_button = button("☼    Light appearance", self.toggle_theme, "nav")
        nav.addWidget(self.theme_button)
        nav.addSpacing(12)
        nav.addWidget(label("●  Stored on this computer", "muted"))
        shell.addWidget(sidebar)
        right = QVBoxLayout()
        right.setContentsMargins(28, 26, 28, 15)
        right.setSpacing(14)
        self.pages = QStackedWidget()
        self.library_page = QWidget()
        self.library_page.setObjectName("page")
        self.settings_page = QWidget()
        self.settings_page.setObjectName("page")
        self.pages.addWidget(self.library_page)
        self.pages.addWidget(self.settings_page)
        right.addWidget(self.pages, 1)
        self.build_library()
        self.build_settings()
        self.online_page = OnlinePage(self)
        self.pages.addWidget(self.online_page)
        self.pages.currentChanged.connect(self.update_navigation)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        right.addWidget(self.progress)
        status_row = QHBoxLayout()
        self.status_label = label("Your images stay yours. All analysis runs locally.", "muted")
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)
        self.pause_button = button("Pause", self.pause_task, "quiet")
        self.pause_button.hide()
        status_row.addWidget(self.pause_button)
        self.details_button = button("View report", self.show_report, "quiet")
        self.details_button.hide()
        self.last_report = ""
        status_row.addWidget(self.details_button)
        right.addLayout(status_row)
        shell.addLayout(right, 1)

    def build_library(self):
        layout = QVBoxLayout(self.library_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(5)
        heading.addWidget(label("YOUR PRIVATE LIBRARY", "eyebrow"))
        self.title = label("All images", "title")
        heading.addWidget(self.title)
        self.subtitle = label("Collect, discover, and find your favorites.", "muted")
        heading.addWidget(self.subtitle)
        header.addLayout(heading, 1)
        local_badge = label("●  Local processing", "badge")
        local_badge.setFixedHeight(28)
        header.addWidget(local_badge)
        self.import_button = button("＋  Import images", self.import_files, "primary")
        self.import_button.setMinimumHeight(40)
        menu = QMenu(self)
        menu.addAction("Choose images…", self.import_files)
        menu.addAction("Choose a folder…", self.import_folder)
        self.import_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.import_button.customContextMenuRequested.connect(lambda p: menu.exec(self.import_button.mapToGlobal(p)))
        header.addWidget(self.import_button)
        layout.addLayout(header)
        search_row = QHBoxLayout()
        self.text_search = QLineEdit()
        self.text_search.setPlaceholderText("Describe a look, a setting, or an image…")
        self.text_search.setAccessibleName("Describe images for local AI search")
        self.text_search.setMinimumHeight(41)
        self.text_search.setClearButtonEnabled(True)
        self.text_search.returnPressed.connect(self.run_search)
        search_row.addWidget(self.text_search, 1)
        self.search_button = button("Search library", self.run_search, "primary")
        search_row.addWidget(self.search_button)
        self.filters_button = button("Traits & weights ▾", self.toggle_filters)
        search_row.addWidget(self.filters_button)
        layout.addLayout(search_row)
        self.active_label = label("", "muted", True)
        self.active_label.hide()
        layout.addWidget(self.active_label)
        body = QHBoxLayout()
        body.setSpacing(18)
        gallery_column = QVBoxLayout()
        gallery_column.setSpacing(10)
        toolbar = QHBoxLayout()
        self.count_label = label("0 images", "muted")
        toolbar.addWidget(self.count_label)
        toolbar.addStretch()
        self.online_similar_button = button("Find similar online", self.online_selected)
        self.online_similar_button.setEnabled(False)
        toolbar.addWidget(self.online_similar_button)
        self.sort = QComboBox()
        self.sort.addItems(["Newest first", "Name A–Z", "Best match"])
        self.sort.setAccessibleName("Sort images")
        self.sort.currentIndexChanged.connect(self.apply_sort)
        toolbar.addWidget(self.sort)
        gallery_column.addLayout(toolbar)
        self.gallery_stack = QStackedWidget()
        self.gallery = GalleryView()
        self.gallery_model = GalleryModel(self)
        self.gallery_delegate = GalleryDelegate(self.gallery)
        self.gallery.setModel(self.gallery_model)
        self.gallery.setItemDelegate(self.gallery_delegate)
        self.gallery.doubleClicked.connect(lambda index: self.edit_images([index.data(IMAGE_ROLE)["id"]]))
        self.gallery.files_dropped.connect(self.import_paths)
        self.gallery.selectionModel().selectionChanged.connect(self.update_selection)
        self.gallery.setContextMenuPolicy(Qt.CustomContextMenu)
        self.gallery.customContextMenuRequested.connect(self.gallery_menu)
        self.gallery_stack.addWidget(self.gallery)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(12)
        self.empty_art = EmptyArt()
        empty_layout.addWidget(self.empty_art, 0, Qt.AlignHCenter)
        self.empty_title = label("Your collection starts here", "sectionTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_body = label("Drop a folder of images here.\nWe’ll organize the details, you make the discoveries.", "muted", True)
        self.empty_body.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_body)
        self.empty_import = button("＋  Choose a folder", self.import_folder, "primary")
        empty_layout.addWidget(self.empty_import, 0, Qt.AlignHCenter)
        self.empty_clear = button("Clear search", self.clear_search)
        self.empty_clear.hide()
        empty_layout.addWidget(self.empty_clear, 0, Qt.AlignHCenter)
        empty_layout.addWidget(label("JPG, PNG, WebP, BMP, TIFF  ·  1,500+ images welcome", "muted"), 0, Qt.AlignHCenter)
        self.gallery_stack.addWidget(self.empty)
        gallery_column.addWidget(self.gallery_stack, 1)
        footer = QHBoxLayout()
        self.selection_label = label("Double-click an image to edit its traits", "muted")
        footer.addWidget(self.selection_label, 1)
        self.edit_button = button("Edit selected", self.edit_selected)
        self.edit_button.setEnabled(False)
        footer.addWidget(self.edit_button)
        self.analyze_button = button("Analyze queue", self.analyze_queue)
        footer.addWidget(self.analyze_button)
        gallery_column.addLayout(footer)
        body.addLayout(gallery_column, 1)
        self.filters = QFrame()
        self.filters.setObjectName("filters")
        self.filters.setFixedWidth(330)
        self.filters.setFixedHeight(min(650, max(350, self.screen().availableGeometry().height() - 180)))
        filters_layout = QVBoxLayout(self.filters)
        filters_layout.setContentsMargins(16, 17, 12, 16)
        filters_layout.setSpacing(10)
        filter_header = QHBoxLayout()
        filter_header.addWidget(label("Refine your search", "sectionTitle"))
        filter_header.addStretch()
        filters_layout.addLayout(filter_header)
        filters_layout.addWidget(label("Choose traits. Slide to set importance.", "muted", True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        form = QVBoxLayout(container)
        form.setContentsMargins(0, 8, 8, 5)
        form.setSpacing(17)
        self.trait_controls = {}
        for trait in TRAITS:
            row = QVBoxLayout()
            row.setSpacing(6)
            title_row = QHBoxLayout()
            title = label(trait.label)
            title.setToolTip(trait.note)
            title_row.addWidget(title)
            title_row.addStretch()
            row.addLayout(title_row)
            combo = QComboBox()
            combo.addItem("Any", None)
            for value, text in trait.options:
                combo.addItem(text, value)
            combo.addItem("Unknown / not visible", "unknown")
            combo.setAccessibleName(trait.label + " search filter")
            row.addWidget(combo)
            weights = QHBoxLayout()
            weight = QSlider(Qt.Horizontal)
            weight.setRange(0, 100)
            weight.setValue(75)
            weight.setEnabled(False)
            weight.setAccessibleName(trait.label + " search importance")
            caption = label("75", "muted")
            caption.setFixedWidth(25)
            caption.setAlignment(Qt.AlignRight)
            weight.valueChanged.connect(lambda value, target=caption: target.setText(str(value)))
            combo.currentIndexChanged.connect(lambda _, c=combo, s=weight: s.setEnabled(c.currentData() is not None))
            weights.addWidget(weight, 1)
            weights.addWidget(caption)
            row.addLayout(weights)
            form.addLayout(row)
            self.trait_controls[trait.key] = combo, weight
        form.addSpacing(4)
        form.addWidget(label("FILENAME OR NOTES", "eyebrow"))
        self.filename_filter = QLineEdit()
        self.filename_filter.setPlaceholderText("Contains…")
        self.filename_filter.setAccessibleName("Filename or notes contains")
        self.filename_filter.returnPressed.connect(self.run_search)
        form.addWidget(self.filename_filter)
        min_row = QHBoxLayout()
        min_row.addWidget(label("Minimum score"))
        self.minimum_score = QSpinBox()
        self.minimum_score.setRange(0, 100)
        self.minimum_score.setAccessibleName("Minimum match score out of 100")
        min_row.addWidget(self.minimum_score)
        form.addLayout(min_row)
        form.addWidget(label("Match scores rank visual similarity. They are not probabilities.", "muted", True))
        form.addStretch()
        scroll.setWidget(container)
        filters_layout.addWidget(scroll, 1)
        filters_layout.addWidget(button("Reset traits & search", self.clear_search, "quiet"))
        filters_layout.addWidget(button("Apply weights", self.apply_trait_filters, "primary"))
        self.web_button = button("Find similar online →", self.search_web)
        self.web_button.setToolTip("Automatically find web matches for the selected library photo. Only its generated description goes online.")
        filters_layout.addWidget(self.web_button)
        filters_layout.addWidget(label("Online only when clicked. Text terms only.", "muted", True))
        self.filters_menu = QMenu(self)
        filter_action = QWidgetAction(self.filters_menu)
        filter_action.setDefaultWidget(self.filters)
        self.filters_menu.addAction(filter_action)
        layout.addLayout(body, 1)

    def build_settings(self):
        layout = QVBoxLayout(self.settings_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(label("MAKE YOURSELF AT HOME", "eyebrow"))
        layout.addWidget(label("Settings", "title"))
        layout.addWidget(label("Private by default. Everything you need, on this computer.", "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        cards = QVBoxLayout(container)
        cards.setContentsMargins(0, 12, 15, 10)
        cards.setSpacing(18)

        def card(title, description):
            frame = QFrame()
            frame.setObjectName("settingsCard")
            content = QVBoxLayout(frame)
            content.setContentsMargins(22, 20, 22, 20)
            content.setSpacing(11)
            content.addWidget(label(title, "sectionTitle"))
            content.addWidget(label(description, "muted", True))
            cards.addWidget(frame)
            return content

        model_card = card("Local AI", "SigLIP 2 · Base · 224 px. Optimized for the RTX 4050 with 6 GB VRAM. CPU mode is available too.")
        self.settings_model_status = label("")
        model_card.addWidget(self.settings_model_status)
        model_card.addWidget(label("The model is a one-time 1.54 GB download from Hugging Face. After setup, analysis and search load only local files. No cloud AI or telemetry.", "muted", True))
        model_row = QHBoxLayout()
        self.download_button = button("Download model (1.54 GB)", self.download_ai, "primary")
        model_row.addWidget(self.download_button)
        model_row.addStretch()
        model_row.addWidget(label("Processor"))
        self.device_combo = QComboBox()
        self.device_combo.addItem("Automatic · prefer NVIDIA GPU", "auto")
        self.device_combo.addItem("CPU · lower GPU usage", "cpu")
        self.device_combo.setCurrentIndex(max(0, self.device_combo.findData(self.prefs["device"])))
        self.device_combo.currentIndexChanged.connect(self.save_settings)
        model_row.addWidget(self.device_combo)
        model_card.addLayout(model_row)
        batch_row = QHBoxLayout()
        batch_row.addWidget(label("Images per batch"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 32)
        self.batch_spin.setValue(self.prefs["batch_size"])
        self.batch_spin.valueChanged.connect(self.save_settings)
        batch_row.addWidget(self.batch_spin)
        batch_row.addStretch()
        batch_row.addWidget(label("Automatically reduces batches if GPU memory is low.", "muted"))
        model_card.addLayout(batch_row)
        library = card("Your library", "Imports preserve your original files. Duplicates are detected by file contents, even when filenames differ.")
        self.copy_check = QCheckBox("Copy imported originals into the local library (recommended)")
        self.copy_check.setChecked(self.prefs["copy_originals"])
        self.copy_check.toggled.connect(self.save_settings)
        library.addWidget(self.copy_check)
        library.addWidget(label("If switched off, originals are referenced in place. Moving those files will prevent opening or reanalyzing them. Cached thumbnails and tags stay available.", "muted", True))
        self.auto_check = QCheckBox("Analyze new images automatically after import")
        self.auto_check.setChecked(self.prefs["auto_analyze"])
        self.auto_check.toggled.connect(self.save_settings)
        library.addWidget(self.auto_check)
        path_label = label(str(self.paths.root), "muted", True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        library.addWidget(path_label)
        tools = QHBoxLayout()
        tools.addWidget(button("Open library folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.root)))))
        tools.addWidget(button("Back up database…", self.backup_database))
        tools.addStretch()
        library.addLayout(tools)
        info = card("About the estimates", "Use AI suggestions as a starting point, then review what matters to you.")
        info.addWidget(label("Hair, visible skin tone, apparent body build, broad apparent age, face shape, framing, glasses, and setting are estimated from the whole image. Multiple people, lighting, crops, and clothing can make estimates wrong. Low-confidence labels remain Unknown.", "muted", True))
        info.addWidget(label("Actual height requires a known measurement and is manual. Skin tone is not race or ethnicity. Apparent age is not age verification. AI scores are relative to the available descriptions, not calibrated confidence percentages.", "muted", True))
        info.addWidget(label("Search blends selected trait scores using your importance sliders. Text or reference similarity uses cosine similarity; when combined with traits, each side contributes half. Explore online finds public candidates from your description and compares them locally. Your reference image is never uploaded.", "muted", True))
        cards.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)
        layout.addWidget(button("← Back to library", lambda: self.change_view("all")), 0, Qt.AlignLeft)

    def bind_shortcuts(self):
        for sequence, handler in (("Ctrl+O", self.import_files), ("Ctrl+Shift+O", self.import_folder),
            ("Ctrl+F", self.focus_search), ("Ctrl+E", self.edit_selected), ("Escape", self.clear_search)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(handler)

    def focus_search(self):
        self.pages.setCurrentWidget(self.library_page)
        self.text_search.setFocus()

    def set_theme(self, theme):
        theme = theme if theme in ("dark", "light") else "dark"
        apply_theme(QApplication.instance(), theme)
        self.gallery_delegate.theme = theme
        self.gallery.viewport().update()
        self.online_page.delegate.theme = theme
        self.online_page.gallery.viewport().update()
        self.prefs["theme"] = theme
        self.theme_button.setText("☼    Light appearance" if theme == "dark" else "☾    Dark appearance")
        self.paths.save_preferences(self.prefs)

    def toggle_theme(self):
        self.set_theme("light" if self.prefs["theme"] == "dark" else "dark")

    def save_settings(self, *_):
        if not hasattr(self, "auto_check"):
            return
        old_device = self.prefs["device"]
        self.prefs.update(device=self.device_combo.currentData(), batch_size=self.batch_spin.value(),
            copy_originals=self.copy_check.isChecked(), auto_analyze=self.auto_check.isChecked())
        self.paths.save_preferences(self.prefs)
        if old_device != self.prefs["device"]:
            self.engine = VisionEngine(self.paths, self.prefs["device"])

    def change_view(self, view):
        self.view = view
        self.pages.setCurrentWidget(self.library_page)
        if self.active_query:
            self.active_query.view = view
        self.refresh()

    def show_settings(self):
        self.pages.setCurrentWidget(self.settings_page)
        self.update_model_status()

    def toggle_filters(self, checked=False, anchor=None):
        anchor = anchor or self.filters_button
        self.filters_menu.popup(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def apply_trait_filters(self):
        self.filters_menu.hide()
        if self.pages.currentWidget() == self.online_page:
            self.online_page.weights = {key: value for key, value in self.query_from_controls().weights.items() if key[0] != "height"}
            self.online_page.search()
        else:
            self.run_search()

    def query_from_controls(self):
        weights = {(group, combo.currentData()): slider.value() / 100
                   for group, (combo, slider) in self.trait_controls.items()
                   if combo.currentData() is not None and slider.value() > 0}
        return SearchQuery(weights=weights, text=self.text_search.text().strip(), filename=self.filename_filter.text().strip(),
            minimum=self.minimum_score.value(), view=self.view)

    def run_search(self):
        query = self.query_from_controls()
        if query.text:
            if self.task is not None:
                self.status_label.setText("Analysis is busy. Pause it to run a new text search; trait search stays available.")
                return
            if not model_ready(self.paths):
                self.show_settings()
                self.status_label.setText("Download the local model to enable text search. Trait and filename search work without it.")
                return
            self._search_generation += 1
            generation = self._search_generation
            def work(task):
                task.progress.emit(0, 0, "Searching with local AI…")
                self.engine.load(lambda msg: task.progress.emit(0, 0, msg))
                vector = self.engine.encode_text(query.text)
                return {"vector": vector}
            def done(result):
                if generation != self._search_generation:
                    return
                query.view = self.view
                self.last_text_embedding = result["vector"]
                self.active_query = query
                self.display_results(search(self.db, query, result["vector"], self.engine.version), True)
                self.status_label.setText("Search complete · processed on this computer.")
            self.start_task("Searching", work, done)
        else:
            self._search_generation += 1
            self.last_text_embedding = None
            self.active_query = query
            self.display_results(search(self.db, query), True)

    def clear_search(self):
        self._search_generation += 1
        self.text_search.clear()
        self.filename_filter.clear()
        self.minimum_score.setValue(0)
        for combo, slider in self.trait_controls.values():
            combo.setCurrentIndex(0)
            slider.setValue(75)
        self.active_query = None
        self.last_text_embedding = None
        self.active_label.hide()
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(0)
        self.sort.blockSignals(False)
        self.refresh()

    def refresh(self):
        stats = self.db.stats()
        names = {"all": "All images", "favorites": "Favorites", "review": "To review", "pending": "Analysis queue"}
        self.title.setText(names[self.view])
        self.subtitle.setText(f"{stats['total']:,} images in your library · {stats['ready']:,} analyzed · {stats['pending']:,} queued")
        self.update_navigation()
        self.nav_buttons["favorites"].setText(f"☆    Favorites  {stats['favorites']:,}")
        self.nav_buttons["review"].setText(f"✓    To review  {stats['review']:,}")
        self.nav_buttons["pending"].setText(f"◷    Analysis queue  {stats['pending'] + stats['errors']:,}")
        try:
            if self.active_query:
                rows = search(self.db, self.active_query, self.last_text_embedding, self.engine.version)
            else:
                rows = self.db.list_images(self.view)
            self.display_results(rows)
        except ValueError as error:
            self.active_query = None
            self.last_text_embedding = None
            self.active_label.hide()
            self.display_results(self.db.list_images(self.view))
            self.status_label.setText(str(error))
        self.update_model_status()

    def display_results(self, rows, searched=False):
        self.result_rows = rows
        if searched:
            self.sort.blockSignals(True)
            self.sort.setCurrentIndex(2)
            self.sort.blockSignals(False)
        self.apply_sort()
        if self.active_query:
            q = self.active_query
            text = f"{len(rows):,} matches"
            if q.reference_id is not None:
                text += " · visually similar images"
            elif q.text:
                text += f" · “{q.text[:85]}”"
            if q.weights:
                text += f" · {len(q.weights)} weighted traits"
            text += " · scores are out of 100"
            self.active_label.setText(text)
            self.active_label.show()
        self.count_label.setText(f"{len(rows):,} {'matches' if self.active_query else 'images'}")
        self.gallery_stack.setCurrentWidget(self.gallery if rows else self.empty)
        empty_library = self.db.stats()["total"] == 0
        self.empty_title.setText("Your collection starts here" if empty_library else "No images here yet" if not self.active_query else "No matches this time")
        self.empty_body.setText("Drop a folder of images here.\nWe’ll organize the details, you make the discoveries." if empty_library else "Try fewer traits, lower the minimum score, or choose another view.")
        self.empty_import.setVisible(empty_library)
        self.empty_clear.setVisible(bool(self.active_query))
        self.update_selection()

    def apply_sort(self, *_):
        rows = self.result_rows.copy()
        if self.sort.currentIndex() == 1:
            rows.sort(key=lambda row: row["name"].lower())
        elif self.sort.currentIndex() == 2:
            rows.sort(key=lambda row: (-(row.get("match_score") or 0), -row["id"]))
        else:
            rows.sort(key=lambda row: -row["id"])
        self.gallery_model.replace(rows)

    def selected_ids(self):
        return [index.data(IMAGE_ROLE)["id"] for index in self.gallery.selectionModel().selectedIndexes()]

    def update_selection(self, *_):
        count = len(self.selected_ids())
        self.selection_label.setText(f"{count:,} selected · Ctrl / Shift to select more" if count else "Double-click an image to edit its traits")
        self.edit_button.setEnabled(count > 0)
        self.online_similar_button.setEnabled(count == 1)

    def edit_selected(self):
        self.edit_images(self.selected_ids())

    def edit_images(self, ids):
        if not ids:
            return
        editor = TagEditor(self.db, ids, self)
        if editor.exec() == QDialog.Accepted:
            self.refresh()
            self.status_label.setText(f"Saved changes to {len(ids):,} image(s).")

    def gallery_menu(self, point):
        index = self.gallery.indexAt(point)
        if not index.isValid():
            return
        if not self.gallery.selectionModel().isSelected(index):
            self.gallery.setCurrentIndex(index)
        ids = self.selected_ids()
        menu = QMenu(self)
        menu.addAction("Edit traits…", lambda: self.edit_images(ids))
        menu.addAction("Add to favorites", lambda: self.favorite(ids, True))
        menu.addAction("Remove from favorites", lambda: self.favorite(ids, False))
        if len(ids) == 1:
            similar = menu.addAction("Find similar images", lambda: self.find_similar(ids[0]))
            similar.setEnabled(index.data(IMAGE_ROLE)["status"] == "ready")
            menu.addAction("Find similar online…", lambda: self.show_online_reference(ids[0]))
        menu.addSeparator()
        remove = menu.addAction("Remove from library…", lambda: self.remove_images(ids))
        remove.setEnabled(self.task is None)
        menu.exec(self.gallery.viewport().mapToGlobal(point))

    def favorite(self, ids, value):
        self.db.set_favorite(ids, value)
        self.refresh()

    def find_similar(self, image_id):
        self.clear_search()
        query = SearchQuery(reference_id=image_id, view=self.view)
        self.active_query = query
        self.display_results(search(self.db, query), True)

    def remove_images(self, ids):
        answer = QMessageBox.question(self, "Remove from library", f"Remove {len(ids):,} image(s) and their tags from this library?\n\nOriginal image files and cached copies will be kept.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.db.remove(ids)
            self.refresh()

    def import_files(self):
        if self.task is not None:
            self.status_label.setText("Pause the current task before starting another import.")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Import images", "", "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)")
        if files:
            self.import_paths(files)

    def import_folder(self):
        if self.task is not None:
            self.status_label.setText("Pause the current task before starting another import.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Import folder, including subfolders")
        if folder:
            self.import_paths([folder])

    def import_paths(self, paths):
        if self.task is not None:
            self.status_label.setText("Pause the current task before starting another import.")
            return
        self.change_view("all")
        def done(result):
            errors = result.get("errors", [])
            self.last_report = f"Imported: {result.get('imported', 0):,}\nDuplicates skipped: {result.get('duplicate', 0):,}\nUnreadable files: {len(errors):,}\n\n" + "\n".join(errors)
            self.details_button.show()
            self.status_label.setText(f"Imported {result.get('imported', 0):,} · {result.get('duplicate', 0):,} duplicates skipped · {len(errors):,} unreadable" + (" · paused" if result.get("cancelled") else ""))
            if self.prefs["auto_analyze"] and model_ready(self.paths) and not result.get("cancelled") and result.get("imported", 0):
                QTimer.singleShot(0, self.analyze_queue)
        self.start_task("Importing", import_task(paths, self.paths, self.db, self.prefs["copy_originals"]), done)

    def analyze_queue(self):
        if self.task is not None:
            return
        if not model_ready(self.paths):
            self.show_settings()
            self.status_label.setText("Set up the local model to start automatic tagging.")
            return
        if not self.db.pending(include_errors=True):
            self.status_label.setText("Everything in your library is already analyzed.")
            return
        def done(result):
            errors = result.get("errors", [])
            self.last_report = f"Analyzed: {result.get('analyzed', 0):,}\nProcessor: {result.get('device', '')}\nFailed: {len(errors):,}\n\n" + "\n".join(errors)
            self.details_button.show()
            self.status_label.setText(f"{'Paused' if result.get('cancelled') else 'Analysis complete'} · {result.get('analyzed', 0):,} images · {len(errors):,} errors · {result.get('device', '')}")
        self.start_task("Analyzing", analyze_task(self.db, self.engine, self.prefs["batch_size"]), done)

    def download_ai(self):
        if self.task is not None:
            return
        def done(result):
            self.status_label.setText(result.get("message", "Model ready."))
            self.update_model_status()
        self.start_task("Downloading model", download_task(self.paths), done)

    def start_task(self, name, function, callback, failure_callback=None, final_callback=None):
        if self.task is not None:
            return
        task = Task(function, self)
        task.output = None
        task.failure = None
        self.task = task
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status_label.setText(name + "…")
        self.pause_button.setText("Pause")
        self.pause_button.setEnabled(True)
        self.pause_button.show()
        for item in (self.import_button, self.analyze_button, self.download_button, self.device_combo, self.batch_spin):
            item.setEnabled(False)
        task.progress.connect(self.on_progress)
        task.result.connect(lambda result: setattr(task, "output", result))
        task.failed.connect(lambda error: setattr(task, "failure", error))
        def finished():
            self.task = None
            self.progress.hide()
            self.pause_button.hide()
            for item in (self.import_button, self.analyze_button, self.device_combo, self.batch_spin):
                item.setEnabled(True)
            self.refresh()
            if final_callback:
                final_callback()
            if task.failure:
                self.status_label.setText("Could not complete the task. See the report for details.")
                self.last_report = task.failure
                self.details_button.show()
                if failure_callback and not self._closing:
                    failure_callback(task.failure)
            elif task.output is not None and not self._closing:
                callback(task.output)
            task.deleteLater()
            if self._closing:
                self.close()
        task.finished.connect(finished)
        task.start()

    def on_progress(self, done, total, message):
        self.progress.setRange(0, total)
        if total:
            self.progress.setValue(done)
        self.status_label.setText(message)

    def pause_task(self):
        if self.task:
            self.task.stop()
            self.pause_button.setText("Pausing…")
            self.pause_button.setEnabled(False)

    def update_model_status(self):
        ready = model_ready(self.paths)
        self.model_label.setText("SigLIP 2\n" + (self.engine.device_name if self.engine.model is not None else "Ready for offline use" if ready else "One-time setup needed"))
        self.settings_model_status.setText("●  Installed · ready for offline use" if ready else "○  Model not installed yet")
        self.download_button.setEnabled(not ready and self.task is None)
        self.download_button.setText("Model installed ✓" if ready else "Download model (1.54 GB)")

    def search_web(self):
        self.filters_menu.hide()
        if self.pages.currentWidget() == self.online_page and self.online_page.reference:
            self.apply_trait_filters()
        else:
            self.online_selected()

    def show_online(self):
        self.pages.setCurrentWidget(self.online_page)

    def update_navigation(self, *_):
        for key, widget in self.nav_buttons.items():
            widget.setChecked(key == self.view and self.pages.currentWidget() == self.library_page)
        self.online_nav.setChecked(self.pages.currentWidget() == self.online_page)

    def online_selected(self):
        ids = self.selected_ids()
        if len(ids) == 1:
            self.show_online_reference(ids[0])
        else:
            self.change_view("all")
            self.status_label.setText("Select one library photo, then click Find similar online.")

    def show_online_reference(self, image_id):
        if not self.online_page.busy and self.task is None:
            image = self.db.get_image(image_id)
            if image:
                self.online_page.prepare(image=image, query=self.query_from_controls())
                self.show_online()
                self.online_page.search()
                return
        self.show_online()
        self.online_page.summary.setText("Finish or stop the current task before starting a new image search.")

    def export_metadata(self):
        if self.task is not None:
            self.status_label.setText("Pause the current task before exporting metadata.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Export library metadata", "fapfinder-metadata.json", "JSON (*.json)")
        if filename:
            def work(task):
                self.db.export_json(filename)
                return {"message": "Metadata exported, including tags, scores, notes, and local file paths."}
            self.start_task("Exporting metadata", work, lambda result: self.status_label.setText(result["message"]))

    def backup_database(self):
        if self.task is not None:
            self.status_label.setText("Pause the current task before making a backup.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Back up local database", "fapfinder-backup.sqlite3", "SQLite database (*.sqlite3)")
        if filename:
            try:
                self.db.backup(filename)
                self.status_label.setText("Database backed up. Copy the library folder too to back up your image files.")
            except Exception as error:
                QMessageBox.warning(self, "Backup failed", str(error))

    def show_report(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Task report")
        dialog.setText(self.last_report[:1000] or "No errors to report.")
        if len(self.last_report) > 1000:
            dialog.setDetailedText(self.last_report)
        dialog.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.import_paths(paths)
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.task and self.task.isRunning():
            self._closing = True
            self.task.stop()
            self.status_label.setText("Saving current work before closing…")
            event.ignore()
        else:
            event.accept()
