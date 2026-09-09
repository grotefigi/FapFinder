from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from .database import best_tags
from .traits import TRAITS, label_for


class TagEditor(QDialog):
    def __init__(self, db, image_ids, parent=None):
        super().__init__(parent)
        self.db = db
        self.image_ids = image_ids
        self.bulk = len(image_ids) > 1
        self.setWindowTitle(f"Edit {len(image_ids)} images" if self.bulk else "Image details")
        self.resize(1000, 740)
        self.setMinimumSize(820, 560)
        screen = self.screen().availableGeometry()
        self.resize(min(self.width(), screen.width() - 40), min(self.height(), screen.height() - 70))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(25, 22, 25, 20)
        title = QLabel(f"Edit {len(image_ids):,} images" if self.bulk else "Make it your own")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)
        subtitle = QLabel("Choose a tag, then adjust its visual strength. Your edits take priority over AI suggestions.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)
        body = QHBoxLayout()
        body.setSpacing(28)
        outer.addLayout(body, 1)
        item = db.get_image(image_ids[0])
        self.item = item
        if not item:
            raise ValueError("This image is no longer in the library.")
        if not self.bulk:
            preview_column = QVBoxLayout()
            preview_column.setSpacing(12)
            preview = QLabel()
            preview.setAlignment(Qt.AlignCenter)
            preview.setMinimumSize(250, 220)
            preview.setPixmap(QPixmap(item["thumbnail"]).scaled(350, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            preview_column.addWidget(preview, 1)
            name = QLabel(item["name"])
            name.setWordWrap(True)
            preview_column.addWidget(name)
            meta = QLabel(f"{item['width']:,} × {item['height']:,} px  ·  {item['bytes'] / 1e6:.1f} MB")
            meta.setObjectName("muted")
            preview_column.addWidget(meta)
            open_button = QPushButton("Open original image ↗")
            open_button.clicked.connect(self.open_original)
            preview_column.addWidget(open_button)
            self.notes = QPlainTextEdit(item["notes"])
            self.notes.setPlaceholderText("Add private notes…")
            self.notes.setMaximumHeight(95)
            self.notes.setAccessibleName("Private image notes")
            preview_column.addWidget(self.notes)
            if item["error"]:
                error = QLabel(item["error"])
                error.setWordWrap(True)
                error.setObjectName("error")
                preview_column.addWidget(error)
            body.addLayout(preview_column, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        form = QVBoxLayout(container)
        form.setContentsMargins(4, 10, 14, 8)
        form.setSpacing(20)
        self.controls = {}
        resolved = best_tags(item)
        for trait in TRAITS:
            block = QVBoxLayout()
            block.setSpacing(5)
            title_row = QHBoxLayout()
            label = QLabel(trait.label)
            label.setToolTip(trait.note)
            title_row.addWidget(label)
            title_row.addStretch()
            block.addLayout(title_row)
            combo = QComboBox()
            combo.setAccessibleName(trait.label + " manual tag")
            if self.bulk:
                combo.addItem("Leave unchanged", "_keep")
            combo.addItem("Use AI suggestion" if trait.automatic else "No known measurement", None)
            combo.addItem("Unknown / not visible", "unknown")
            for value, label_text in trait.options:
                combo.addItem(label_text, value)
            block.addWidget(combo)
            slider_row = QHBoxLayout()
            strength = QSlider(Qt.Horizontal)
            strength.setRange(0, 100)
            strength.setValue(100)
            strength.setAccessibleName(trait.label + " visual strength")
            value_label = QLabel("100 / 100")
            value_label.setObjectName("muted")
            value_label.setMinimumWidth(70)
            strength.valueChanged.connect(lambda value, label=value_label: label.setText(f"{value} / 100"))
            slider_row.addWidget(strength, 1)
            slider_row.addWidget(value_label)
            block.addLayout(slider_row)
            combo.currentIndexChanged.connect(lambda _, c=combo, s=strength: s.setEnabled(c.currentData() not in (None, "_keep", "unknown")))
            if not self.bulk:
                manual = item["manual_tags"].get(trait.key)
                if manual:
                    combo.setCurrentIndex(combo.findData(manual["value"]))
                    strength.setValue(round(manual["strength"] * 100))
                candidates = [row for row in item["ai_tags"] if row["trait"] == trait.key]
                if candidates:
                    auto_value, _, source = resolved[trait.key]
                    automatic_label = QLabel(f"Current tag: {label_for(trait.key, auto_value)} · {source}")
                    automatic_label.setWordWrap(True)
                    block.addWidget(automatic_label)
                    top = max(candidates, key=lambda r: r["score"])
                    suggestion = QLabel(f"AI suggestion: {label_for(trait.key, top['value'])} · {top['score'] * 100:.1f} / 100")
                    suggestion.setWordWrap(True)
                    suggestion.setObjectName("muted")
                    block.addWidget(suggestion)
            strength.setEnabled(combo.currentData() not in (None, "_keep", "unknown"))
            if trait.key in ("height", "age", "skin_tone"):
                note = QLabel(trait.note)
                note.setWordWrap(True)
                note.setObjectName("muted")
                block.addWidget(note)
            self.controls[trait.key] = (combo, strength)
            form.addLayout(block)
        form.addStretch()
        scroll.setWidget(container)
        body.addWidget(scroll, 5)
        note = QLabel("AI scores compare predefined descriptions; they are not calibrated probabilities. Manual strength is your rating.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        outer.addWidget(note)
        footer = QHBoxLayout()
        self.reviewed = QCheckBox("Mark as reviewed")
        self.reviewed.setChecked(bool(item["reviewed"]) if not self.bulk else False)
        footer.addWidget(self.reviewed)
        footer.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save changes")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        outer.addLayout(footer)

    def open_original(self):
        from pathlib import Path
        if not Path(self.item["path"]).is_file():
            QMessageBox.information(self, "Original unavailable", "The original file was moved or removed. The cached thumbnail is still available.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.item["path"]))

    def save(self):
        edits = {}
        for group, (combo, strength) in self.controls.items():
            value = combo.currentData()
            if value == "_keep":
                continue
            edits[group] = None if value is None else (value, 1.0 if value == "unknown" else strength.value() / 100)
        try:
            # In bulk mode an unchecked checkbox preserves each image's review state.
            reviewed = (True if self.reviewed.isChecked() else None) if self.bulk else self.reviewed.isChecked()
            self.db.save_manual(self.image_ids, edits, None if self.bulk else self.notes.toPlainText(), reviewed)
        except Exception as error:
            QMessageBox.warning(self, "Could not save", str(error))
            return
        self.accept()
