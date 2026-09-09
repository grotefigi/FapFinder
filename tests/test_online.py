import io
import json
import socket
import threading
from html import escape
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from fapfinder.config import Paths
from fapfinder.database import Database
from fapfinder.online import (BingParser, ImageCache, OnlineError, discover_task, fetch_bytes,
    public_url, quality_passes, save_to_library, similarity, suggested_terms)
from fapfinder.search import SearchQuery


def photo_bytes(color="red", size=(1400, 900)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "JPEG")
    return stream.getvalue()


def item(key="one", **changes):
    return dict(id=key, image_url=f"https://example.com/{key}.jpg", source_url="https://example.com/photo",
        thumbnail_url=f"https://example.com/{key}-thumb.jpg", name="Landscape", source="example.com",
        width=1800, height=1200, status="online", error="", favorite=0, reviewed=0, **changes)


@pytest.mark.parametrize("url", ["file:///C:/private.jpg", "http://localhost/", "http://127.0.0.1/x",
    "http://[::1]/", "https://10.0.0.1/", "https://192.168.1.2/", "http://169.254.169.254/",
    "https://private.local/", "https://example.com:8181/", "https://user:pass@example.com/",
    "https://example.com/\n", "https://example.com\\@127.0.0.1/"])
def test_reject_non_public_addresses(url):
    with pytest.raises((OnlineError, ValueError)):
        public_url(url)


def test_pin_dns_and_reject_redirect_to_private_network(monkeypatch):
    connected = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    class FakeSocket:
        def __init__(self, *_): pass
        def settimeout(self, *_): pass
        def connect(self, address): connected.append(address)
    monkeypatch.setattr(socket, "socket", FakeSocket)
    class Response:
        status = 302
        def getheader(self, *_): return "http://127.0.0.1/secret"
    class Connection:
        def __init__(self, *_args, **_kwargs): pass
        def request(self, *_args, **_kwargs): self._create_connection(("should-not-resolve-again", 443), 1)
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    with pytest.raises(OnlineError): fetch_bytes("https://example.com/image")
    assert connected == [("8.8.8.8", 443)]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 443))])
    with pytest.raises(OnlineError): fetch_bytes("https://example.com/image")
    assert len(connected) == 1


def test_outgoing_terms_exclude_private_metadata():
    image = {"name": "private-person.jpg", "notes": "sensitive notes", "path": "C:/private/home.jpg", "embedding": b"secret",
             "manual_tags": {"hair_color": {"value": "blonde", "strength": .9}}, "ai_tags": []}
    terms = suggested_terms(image)
    assert "blonde hair" in terms
    assert all(token not in terms for token in ("private", "sensitive", "secret", "home.jpg"))
    query = SearchQuery(text="mountain landscape", filename="private", weights={("hair_color", "brown"): .7})
    assert suggested_terms(query=query) == "mountain landscape brown hair"


def test_parser_dimensions_quality_and_malformed_entries():
    m = {"murl": "https://cdn.example.com/a.jpg", "purl": "https://example.com/photo", "turl": "https://cdn.example.com/t.jpg", "t": "A & B"}
    html = f'<a class="iusc" m="{escape(json.dumps(m), quote=True)}" href="/images?expw=2400&amp;exph=1600"></a>'
    parser = BingParser()
    parser.feed('<a class="iusc" m="not json"></a>' + html)
    assert len(parser.items) == 1
    row = parser.items[0]
    assert row["name"] == "A & B"
    assert (row["width"], row["height"]) == (2400, 1600)
    assert quality_passes(row, 1920)
    assert not quality_passes(dict(row, height=200), 1920)


def test_cache_validation_reuse_prune_and_session_containment(monkeypatch, tmp_path):
    calls = []
    data = photo_bytes()
    def fetch(url, **kwargs): calls.append(url); return data
    monkeypatch.setattr("fapfinder.online.fetch_bytes", fetch)
    cache = ImageCache(tmp_path)
    path, w, h = cache.image("https://example.com/full.jpg", original=True)
    assert (w, h) == (1400, 900)
    assert Path(path).read_bytes() == data  # Save original bytes, no re-encoding or upscaling.
    assert cache.image("https://example.com/full.jpg", original=True)[0] == path
    assert len(calls) == 1
    thumb, _, _ = cache.image("https://example.com/thumb.jpg")
    with Image.open(thumb) as im: assert max(im.size) <= 800
    row = item(thumbnail=thumb, preview_hash="abc", match_score=50)
    cache.save_session("mountains", [row, dict(row, thumbnail=str(tmp_path / "private.jpg"))])
    assert len(cache.load_session()["items"]) == 1
    monkeypatch.setattr("fapfinder.online.fetch_bytes", lambda *_args, **_kwargs: b"<html>not an image</html>")
    with pytest.raises(Exception): cache.image("https://example.com/bad.jpg")
    assert not list(cache.root.glob("*.tmp"))
    cache.prune(limit=0)
    assert not Path(thumb).exists()
    assert cache.load_session()["items"] == []


class Progress:
    def emit(self, *_): pass


class FakeTask:
    progress = Progress()
    stopped = False
    def isInterruptionRequested(self): return self.stopped


def test_discovery_ranks_locally_deduplicates_and_cancels(monkeypatch, tmp_path):
    cache = ImageCache(tmp_path)
    rows = [item("one"), item("one"), item("two"), dict(item("small"), width=300, height=200)]
    class Provider:
        def search(self, terms, page, stop):
            assert terms == "landscape"
            return rows
    monkeypatch.setattr("fapfinder.online.fetch_bytes", lambda url, **kwargs: photo_bytes("red" if "one" in url else "blue"))
    class Engine:
        version = "test-version"
        def load(self, callback): pass
        def encode_text(self, text): return np.array([1., 0.])
        def analyze(self, paths):
            return [({"hair_color": {"blonde": .8}}, np.array([1., 0.]) if Image.open(p).getpixel((0, 0))[0] > 100 else np.array([0., 1.])) for p in paths]
    result = discover_task(cache, Engine(), "landscape", 1, 1280, provider=Provider())(FakeTask())
    assert len(result["items"]) == 2
    assert result["items"][0]["id"] == "one"
    assert result["items"][0]["match_score"] == pytest.approx(100)
    assert result["items"][1]["match_score"] == 0
    stopped = FakeTask()
    stopped.stopped = True
    result = discover_task(cache, Engine(), "landscape", 1, 1280, provider=Provider())(stopped)
    assert result["cancelled"]
    assert similarity(np.array([1., 0.]), np.array([1., 0.]), {"hair_color": {"blonde": .2}}, {("hair_color", "blonde"): .8}) == pytest.approx(60)


def test_save_keeps_original_and_provenance_without_overwriting_notes(tmp_path):
    paths = Paths(tmp_path / "library")
    paths.initialize()
    db = Database(paths.database)
    path = tmp_path / "full.jpg"
    path.write_bytes(photo_bytes())
    row = item()
    first = save_to_library(path, row, paths, db)
    assert first["imported"]
    saved = db.get_image(first["image_id"])
    assert saved["name"] == "Landscape"
    assert saved["source_path"] == row["source_url"]
    assert Path(saved["path"]).read_bytes() == path.read_bytes()
    db.save_manual([saved["id"]], {}, notes="My private note")
    again = save_to_library(path, row, paths, db)
    assert not again["imported"]
    assert db.stats()["total"] == 1
    assert db.get_image(saved["id"])["notes"] == "My private note"
    assert len(db.get_image(saved["id"])["web_sources"]) == 1
