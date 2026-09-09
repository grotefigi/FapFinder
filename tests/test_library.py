from pathlib import Path
import json
import sqlite3
import shutil
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from PIL import Image

from fapfinder.config import Paths
from fapfinder.database import Database, best_tags
from fapfinder.importer import discover_images, import_one
from fapfinder.search import SearchQuery, search, web_search_url
from fapfinder.workers import import_task, analyze_task


@pytest.fixture
def library(tmp_path):
    paths = Paths(tmp_path / "library")
    paths.initialize()
    return paths, Database(paths.database)


def photo(path, color="red", size=(120, 160)):
    Image.new("RGB", size, color).save(path)
    return path


def add(library, tmp_path, name, color):
    paths, db = library
    file = photo(tmp_path / name, color)
    import_one(file, paths, db)
    return db.list_images()[0]["id"]


def test_import_deduplicates_content_preserves_original_and_copy(library, tmp_path):
    paths, db = library
    original = photo(tmp_path / "first.png")
    duplicate = tmp_path / "renamed.png"
    shutil.copyfile(original, duplicate)
    assert import_one(original, paths, db) == "imported"
    assert import_one(duplicate, paths, db) == "duplicate"
    row = db.get_image(db.list_images()[0]["id"])
    assert Path(row["path"]).read_bytes() == original.read_bytes()
    assert Path(row["thumbnail"]).is_file()
    assert row["width"] == 120 and row["height"] == 160
    assert db.stats()["total"] == 1
    original.unlink()
    assert Path(row["path"]).is_file()


def test_recursive_import_case_extensions_corruption_and_cancel(library, tmp_path):
    paths, db = library
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    photo(source / "A.JPG")
    photo(source / "nested" / "B.PNG", "blue")
    (source / "broken.jpg").write_bytes(b"not an image")
    (source / "not.txt").write_text("skip")
    assert len(list(discover_images([source, source / "A.JPG"]))) == 3
    assert list(discover_images([source], lambda: True)) == []
    task = FakeTask()
    summary = import_task([source], paths, db, True)(task)
    assert summary["imported"] == 2
    assert len(summary["errors"]) == 1


def test_exif_orientation_is_applied_to_dimensions(library, tmp_path):
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (200, 100), "green").save(path, exif=exif)
    paths, db = library
    import_one(path, paths, db)
    row = db.list_images()[0]
    assert (row["width"], row["height"]) == (100, 200)
    with Image.open(row["thumbnail"]) as thumb:
        assert not thumb.getexif()


def test_weighted_ranking_manual_overrides_and_persistence(library, tmp_path):
    paths, db = library
    one = add(library, tmp_path, "one.png", "red")
    two = add(library, tmp_path, "two.png", "blue")
    db.save_analysis(one, {"hair_color": {"blonde": .9, "brown": .1}, "build": {"slim": .1}}, [1, 0, 0], "v1")
    db.save_analysis(two, {"hair_color": {"blonde": .2, "brown": .8}, "build": {"slim": .9}}, [0, 1, 0], "v1")
    query = SearchQuery(weights={("hair_color", "blonde"): .9, ("build", "slim"): .1})
    results = search(db, query)
    assert results[0]["id"] == one
    assert results[0]["match_score"] == pytest.approx(82)
    query.weights = {("hair_color", "blonde"): .1, ("build", "slim"): .9}
    assert search(db, query)[0]["id"] == two
    db.save_manual([one], {"build": ("slim", 1.0)}, notes="golden hour", reviewed=True)
    db.save_analysis(one, {"build": {"slim": .05}}, [1, 0, 0], "v1")
    reopened = Database(paths.database)
    assert best_tags(reopened.get_image(one))["build"] == ("slim", 1.0, "manual")
    assert search(reopened, SearchQuery(filename="GOLDEN"))[0]["id"] == one
    assert reopened.get_image(one)["reviewed"] == 1
    reopened.save_manual([one], {"build": None})
    assert best_tags(reopened.get_image(one))["build"][0] == "unknown"


def test_unknown_manual_suppresses_conflicting_ai(library, tmp_path):
    paths, db = library
    image_id = add(library, tmp_path, "one.png", "red")
    db.save_analysis(image_id, {"age": {"18_29": .9, "unknown": .1}}, [1, 0], "v")
    db.save_manual([image_id], {"age": ("unknown", 1)})
    assert search(db, SearchQuery(weights={("age", "18_29"): 1})) == []
    assert search(db, SearchQuery(weights={("age", "unknown"): 1}))[0]["match_score"] == 100
    assert best_tags(db.get_image(image_id))["height"][0] == "unknown"
    assert search(db, SearchQuery(weights={("height", "unknown"): 1}))[0]["id"] == image_id


def test_similarity_excludes_self_and_incompatible_model(library, tmp_path):
    paths, db = library
    one = add(library, tmp_path, "one.png", "red")
    two = add(library, tmp_path, "two.png", "blue")
    three = add(library, tmp_path, "three.png", "green")
    db.save_analysis(one, {}, [1, 0], "v1")
    db.save_analysis(two, {}, [.8, .6], "v1")
    db.save_analysis(three, {}, [1, 0], "v2")
    matches = search(db, SearchQuery(reference_id=one))
    assert [m["id"] for m in matches] == [two]
    assert matches[0]["match_score"] == pytest.approx(80)
    assert search(db, SearchQuery(text="red", minimum=90), np.array([1, 0]), "v1")[0]["id"] == one
    with pytest.raises(ValueError):
        search(db, SearchQuery(text="portrait"))


def test_validation_backup_export_and_safe_removal(library, tmp_path):
    paths, db = library
    image_id = add(library, tmp_path, "one.png", "red")
    with pytest.raises(ValueError):
        db.save_manual([image_id], {"hair_color": ("not-a-tag", 1)})
    with pytest.raises(ValueError):
        db.save_analysis(image_id, {}, [float("nan"), 0], "v1")
    db.save_manual([image_id], {"hair_color": ("blonde", .7)})
    db.set_favorite([image_id], True)
    assert len(db.list_images("favorites")) == 1
    backup = tmp_path / "backup.sqlite3"
    db.backup(backup)
    assert Database(backup).stats()["total"] == 1
    export = tmp_path / "metadata.json"
    db.export_json(export)
    assert json.loads(export.read_text("utf-8"))["images"][0]["manual_tags"]["hair_color"]["strength"] == .7
    with pytest.raises(ValueError):
        db.backup(db.path)
    with pytest.raises(ValueError):
        db.export_json(db.path)
    row = db.get_image(image_id)
    db.remove([image_id])
    assert db.stats()["total"] == 0
    assert Path(row["path"]).is_file()
    with db.connect() as sql:
        assert sql.execute("SELECT COUNT(*) FROM manual_tags").fetchone()[0] == 0


def test_web_search_only_contains_explicit_terms():
    query = SearchQuery(text="outdoor portrait & sunlight", weights={("hair_color", "blonde"): .8}, filename="PRIVATE_FILE.jpg")
    url = web_search_url(query)
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.netloc == "www.google.com"
    assert "Blonde" in parse_qs(parsed.query)["q"][0]
    assert "PRIVATE_FILE" not in url and "path" not in url


class FakeProgress:
    def emit(self, *args):
        pass


class FakeTask:
    progress = FakeProgress()
    def isInterruptionRequested(self):
        return False


def test_analysis_recovers_smaller_batches_and_skips_bad_files(library, tmp_path):
    paths, db = library
    first = add(library, tmp_path, "one.png", "red")
    second = add(library, tmp_path, "two.png", "blue")
    Path(db.get_image(second)["path"]).unlink()
    class Engine:
        version = "test"
        device_name = "Test"
        recovered = False
        def load(self, progress):
            pass
        def analyze(self, paths):
            if len(paths) > 1:
                raise RuntimeError("CUDA out of memory")
            if not Path(paths[0]).exists():
                raise FileNotFoundError("Original moved")
            return [({"hair_color": {"blonde": .8}}, np.array([1, 0]))]
        def recover_memory(self):
            self.recovered = True
    engine = Engine()
    result = analyze_task(db, engine, 16)(FakeTask())
    assert engine.recovered
    assert result["analyzed"] == 1 and len(result["errors"]) == 1
    assert db.get_image(first)["status"] == "ready"
    assert db.get_image(second)["status"] == "error"
