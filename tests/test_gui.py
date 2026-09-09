import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog
from PIL import Image

from fapfinder.config import Paths
from fapfinder.window import MainWindow
from fapfinder.editor import TagEditor
from fapfinder.importer import import_one


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_native_gallery_search_editor_and_theme(app, tmp_path):
    paths = Paths(tmp_path / "library")
    window = MainWindow(paths)
    window.show()
    app.processEvents()
    assert window.gallery_model.rowCount() == 0
    source = tmp_path / "test.png"
    Image.new("RGB", (100, 160), "red").save(source)
    import_one(source, paths, window.db)
    window.refresh()
    app.processEvents()
    assert window.gallery_model.rowCount() == 1
    image_id = window.gallery_model.items[0]["id"]
    editor = TagEditor(window.db, [image_id], window)
    combo, strength = editor.controls["hair_color"]
    combo.setCurrentIndex(combo.findData("blonde"))
    strength.setValue(82)
    editor.reviewed.setChecked(True)
    editor.notes.setPlainText("A private note")
    editor.save()
    assert editor.result() == QDialog.Accepted
    assert window.db.get_image(image_id)["manual_tags"]["hair_color"]["strength"] == .82
    combo, weight = window.trait_controls["hair_color"]
    combo.setCurrentIndex(combo.findData("blonde"))
    window.run_search()
    assert window.gallery_model.items[0]["match_score"] == pytest.approx(82)
    window.minimum_score.setValue(90)
    window.run_search()
    assert window.gallery_model.rowCount() == 0
    window.clear_search()
    assert window.gallery_model.rowCount() == 1
    window.favorite([image_id], True)
    window.change_view("favorites")
    assert window.gallery_model.rowCount() == 1
    window.set_theme("light")
    assert paths.preferences()["theme"] == "light"
    window.show_settings()
    assert window.pages.currentWidget() == window.settings_page
    window.close()


def test_bulk_editor_keeps_unedited_traits(app, tmp_path):
    paths = Paths(tmp_path / "library")
    window = MainWindow(paths)
    ids = []
    for i, color in enumerate(("red", "blue")):
        source = tmp_path / f"test-{i}.png"
        Image.new("RGB", (100, 100), color).save(source)
        import_one(source, paths, window.db)
        ids.append(window.db.list_images()[0]["id"])
    window.db.save_manual([ids[0]], {"hair_color": ("blonde", .8)}, reviewed=True)
    window.db.save_manual([ids[1]], {"hair_color": ("brown", .6)}, reviewed=False)
    editor = TagEditor(window.db, ids, window)
    combo, strength = editor.controls["build"]
    combo.setCurrentIndex(combo.findData("muscular"))
    strength.setValue(70)
    editor.save()
    assert window.db.get_image(ids[0])["manual_tags"]["hair_color"]["value"] == "blonde"
    assert window.db.get_image(ids[1])["manual_tags"]["hair_color"]["value"] == "brown"
    for image_id in ids:
        assert window.db.get_image(image_id)["manual_tags"]["build"]["strength"] == .7
    assert window.db.get_image(ids[0])["reviewed"] == 1
    assert window.db.get_image(ids[1])["reviewed"] == 0
    window.close()


def test_background_import_finishes_and_refreshes_gallery(app, tmp_path):
    import time
    paths = Paths(tmp_path / "library")
    window = MainWindow(paths)
    source = tmp_path / "background.png"
    Image.new("RGB", (140, 220), "green").save(source)
    window.prefs["auto_analyze"] = False
    window.import_paths([str(source)])
    assert window.task is not None
    deadline = time.monotonic() + 10
    while window.task is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert window.task is None
    assert window.gallery_model.rowCount() == 1
    assert "Imported 1" in window.status_label.text()
    assert window.import_button.isEnabled()
    window.close()


def wait_for(app, predicate, timeout=5):
    import time
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate()


def test_online_gallery_stays_offline_until_search_and_viewer_saves(app, tmp_path, monkeypatch):
    from fapfinder.online_ui import PhotoViewer
    import socket
    def deny(*_args, **_kwargs):
        raise AssertionError("Opening the app or online page must not contact the network")
    monkeypatch.setattr(socket.socket, "connect", deny)
    paths = Paths(tmp_path / "library")
    window = MainWindow(paths)
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (1400, 1000), "green").save(source)
    import_one(source, paths, window.db)
    window.refresh()
    image_id = window.db.list_images()[0]["id"]
    window.db.save_manual([image_id], {"hair_color": ("brown", .9)})
    window.show_online_reference(image_id)
    page = window.online_page
    assert window.pages.currentWidget() == page
    assert "brown hair" in page.terms.text()
    assert page.model.rowCount() == 0
    monkeypatch.setattr(page.cache, "image", lambda *_args, **_kwargs: (str(source), 1400, 1000))
    row = dict(name="A public photo", source="example.com", source_url="https://example.com/photo",
        image_url="https://example.com/photo.jpg", thumbnail=str(source), match_score=70)
    viewer = PhotoViewer([row, dict(row, name="Second photo")], 0, page.cache, window)
    viewer.show()
    wait_for(app, lambda: viewer.full_path is not None)
    assert "1,400 × 1,000" in viewer.details.text()
    assert viewer.save_button.isEnabled()
    viewer.canvas.set_zoom(2)
    assert viewer.canvas.zoom == 2
    viewer.move(1)
    assert viewer.index == 1
    wait_for(app, lambda: viewer.full_path is not None)
    viewer.save()
    wait_for(app, lambda: viewer.task is None)
    assert "Already" in viewer.details.text()
    assert window.db.get_image(image_id)["web_sources"][0]["source_url"] == row["source_url"]
    viewer.close()
    app.processEvents()
    assert not viewer.isVisible()
    window.close()


def test_viewer_fast_navigation_and_close_wait_for_download(app, tmp_path):
    import time
    from fapfinder.online_ui import PhotoViewer
    from fapfinder.vision import Cancelled
    window = MainWindow(Paths(tmp_path / "library"))
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (800, 600), "blue").save(source)
    class SlowCache:
        def image(self, url, original, stop):
            for _ in range(15):
                if stop(): raise Cancelled("Stopped")
                time.sleep(.01)
            return str(source), 800, 600
        def prune(self): pass
    row = dict(name="First", source="example.com", source_url="https://example.com/",
               image_url="https://example.com/1.jpg", thumbnail=str(source), match_score=70)
    viewer = PhotoViewer([row, dict(row, name="Second", image_url="https://example.com/2.jpg")], 0, SlowCache(), window)
    viewer.show()
    wait_for(app, lambda: viewer.task is not None)
    viewer.move(1)
    wait_for(app, lambda: viewer.full_path is not None)
    assert viewer.caption.text() == "Second"
    viewer.move(-1)
    wait_for(app, lambda: viewer.task is not None)
    viewer.close()
    wait_for(app, lambda: viewer.task is None)
    assert not viewer.isVisible()
    window.close()
