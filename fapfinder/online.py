"""Opt-in public image discovery. Private reference images never leave this process."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import http.client
from html.parser import HTMLParser
import io
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import time
import uuid
import warnings
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import numpy as np
from PIL import Image, ImageOps

from .database import best_tags
from .traits import BY_KEY, DESCRIPTIONS, VALID_TAGS
from .vision import Cancelled


class OnlineError(ValueError):
    pass


def check_cancel(stop):
    if stop():
        raise Cancelled("Online search stopped.")


def public_url(url):
    """Validate syntax without network access. DNS is validated at connection time."""
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url) or "\\" in url:
        raise OnlineError("Invalid image address.")
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise OnlineError("Only public HTTP and HTTPS images are supported.")
    host = p.hostname.rstrip(".").lower()
    if "." not in host and ":" not in host or host.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
        raise OnlineError("Local network addresses are not allowed.")
    if p.port not in (None, 80, 443):
        raise OnlineError("Nonstandard network ports are not supported.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise OnlineError("Local network addresses are not allowed.")
    return urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))


def fetch_bytes(url, *, limit=4_000_000, stop=lambda: False, timeout=10):
    """No cookies, proxies, uploads or auth. Pin a validated public IP for each hop."""
    deadline = time.monotonic() + 25
    for _ in range(5):
        check_cancel(stop)
        url = public_url(url)
        p = urlsplit(url)
        port = p.port or (443 if p.scheme == "https" else 80)
        addresses = socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise OnlineError("The image address resolves to a private network.")

        def connect_validated(_address, _timeout, source_address=None):
            last_error = None
            for family, kind, proto, _, address in addresses:
                check_cancel(stop)
                sock = socket.socket(family, kind, proto)
                sock.settimeout(min(timeout, max(.1, deadline - time.monotonic())))
                try:
                    sock.connect(address)
                    return sock
                except OSError as error:
                    sock.close()
                    last_error = error
                if time.monotonic() >= deadline:
                    break
            raise last_error or OnlineError("Could not connect to the image site.")

        cls = http.client.HTTPSConnection if p.scheme == "https" else http.client.HTTPConnection
        kwargs = {"context": ssl.create_default_context()} if p.scheme == "https" else {}
        connection = cls(p.hostname, port, timeout=timeout, **kwargs)
        connection._create_connection = connect_validated
        try:
            connection.request("GET", urlunsplit(("", "", p.path or "/", p.query, "")), headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FapFinder/1.1",
                "Accept": "image/webp,image/jpeg,image/png,text/html,application/json;q=0.8,*/*;q=0.5",
                "Accept-Encoding": "identity", "Accept-Language": "en-US,en;q=0.8"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise OnlineError("The image site returned an empty redirect.")
                url = urljoin(url, location)
                continue
            if response.status in (403, 429):
                raise OnlineError("This site is limiting requests. Try later or open the source page.")
            if response.status != 200:
                raise OnlineError(f"The image site returned HTTP {response.status}.")
            if int(response.getheader("Content-Length", "0")) > limit:
                raise OnlineError("This download is too large to preview safely.")
            chunks, size = [], 0
            while True:
                check_cancel(stop)
                if time.monotonic() > deadline:
                    raise OnlineError("The image site took too long to respond.")
                block = response.read(min(65536, limit + 1 - size))
                if not block:
                    return b"".join(chunks)
                size += len(block)
                if size > limit:
                    raise OnlineError("This download is too large to preview safely.")
                chunks.append(block)
        finally:
            connection.close()
    raise OnlineError("The image site returned too many redirects.")


def trait_phrase(group, value):
    if group not in DESCRIPTIONS or value == "unknown":
        return ""
    keys = [key for key, _ in BY_KEY[group].options]
    return DESCRIPTIONS[group][keys.index(value)] if value in keys else ""


def suggested_terms(image=None, query=None):
    # Deliberate allowlist: filenames, paths, notes and embeddings are never included.
    if query and query.text.strip():
        terms = [query.text.strip()]
    else:
        terms = ["adult woman photography"]
    if query and query.weights:
        choices = [(group, value) for (group, value), weight in sorted(query.weights.items(), key=lambda pair: -pair[1])
                   if weight > 0 and (group, value) in VALID_TAGS]
    elif image:
        allowed = {"hair_color", "hair_length", "hair_texture", "framing", "setting", "build", "glasses"}
        choices = [(group, value) for group, (value, score, source) in best_tags(image).items()
                   if group in allowed and value != "unknown" and (source == "manual" or score >= .6)]
    else:
        choices = []
    terms.extend(phrase for group, value in choices[:5] if (phrase := trait_phrase(group, value)))
    return " ".join(" ".join(terms).split())[:400]


class BingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag != "a" or "iusc" not in a.get("class", "").split() or "m" not in a:
            return
        try:
            data = json.loads(a["m"])
            dims = parse_qs(urlsplit(a.get("href", "")).query)
            original = public_url(data["murl"])
            source = public_url(data["purl"])
            thumbnail = public_url(data["turl"])
            width = max(0, int(dims.get("expw", [data.get("w", 0)])[0]))
            height = max(0, int(dims.get("exph", [data.get("h", 0)])[0]))
            self.items.append(dict(id=hashlib.sha256(original.encode()).hexdigest(), name=str(data.get("t") or "Web image")[:240],
                image_url=original, source_url=source, thumbnail_url=thumbnail, width=width, height=height,
                source=urlsplit(source).hostname.removeprefix("www."), status="online", error="", favorite=0, reviewed=0))
        except (ValueError, KeyError, TypeError, IndexError):
            return


class BingImages:
    """Public search-page adapter; bounded and opt-in, no account or API key."""
    def search(self, terms, page=1, stop=lambda: False):
        terms = " ".join(terms.split())
        if not terms or len(terms) > 400:
            raise OnlineError("Enter a search description of up to 400 characters.")
        # A page contains up to 35 results. Keep the same offset sequence for Load more.
        url = "https://www.bing.com/images/search?" + urlencode({"q": terms, "first": (page - 1) * 35 + 1,
            "count": 35, "adlt": "strict", "qft": "+filterui:photo-photo+filterui:imagesize-large", "setlang": "en-us"})
        body = fetch_bytes(url, stop=stop).decode("utf-8", "replace")
        parser = BingParser()
        parser.feed(body)
        if not parser.items and any(word in body.lower() for word in ("captcha", "verify you are human", "unusual traffic")):
            raise OnlineError("Image search needs a browser verification. Try again later; the app cannot bypass it.")
        return parser.items[:80]


def quality_passes(item, minimum):
    w, h = item.get("width", 0), item.get("height", 0)
    return not minimum or max(w, h) >= minimum and min(w, h) >= minimum / 2


class ImageCache:
    def __init__(self, root):
        self.root = Path(root) / "web-cache"
        self.root.mkdir(parents=True, exist_ok=True)

    def image(self, url, original=False, stop=lambda: False):
        url = public_url(url)
        key = hashlib.sha256(url.encode()).hexdigest() + ("-full" if original else "-thumb")
        # Only cache files created by this class are considered.
        for ext in ("jpg", "png", "webp", "bmp", "tif"):
            path = self.root / f"{key}.{ext}"
            if path.is_file():
                check_cancel(stop)
                path.touch()
                with Image.open(path) as im:
                    width, height = im.size
                    if im.getexif().get(274) in (5, 6, 7, 8):
                        width, height = height, width
                return str(path), width, height
        data = fetch_bytes(url, limit=24_000_000 if original else 4_000_000, stop=stop)
        check_cancel(stop)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "BMP": "bmp", "TIFF": "tif"}.get(im.format)
                if not ext or im.width * im.height > (50_000_000 if original else 8_000_000):
                    raise OnlineError("The site did not return a supported, reasonably sized photo.")
                im.verify()
            with Image.open(io.BytesIO(data)) as im:
                corrected = ImageOps.exif_transpose(im)
                width, height = corrected.size
                if min(width, height) < 64:
                    raise OnlineError("This image is too small to preview.")
                if not original:
                    corrected.thumbnail((640, 800), Image.Resampling.LANCZOS)
                    out = io.BytesIO()
                    corrected.convert("RGB").save(out, "JPEG", quality=90)
                    data, ext = out.getvalue(), "jpg"
        path = self.root / f"{key}.{ext}"
        temp = self.root / f"{key}-{uuid.uuid4().hex}.tmp"
        try:
            temp.write_bytes(data)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        return str(path), width, height

    def prune(self, limit=300 * 1024 * 1024):
        files = [p for p in self.root.iterdir() if p.is_file() and p.suffix in (".jpg", ".png", ".webp", ".bmp", ".tif")]
        total = sum(p.stat().st_size for p in files)
        for path in sorted(files, key=lambda p: p.stat().st_mtime):
            if total <= limit:
                break
            size = path.stat().st_size
            try:
                path.unlink()
                total -= size
            except OSError:
                pass

    def save_session(self, terms, items):
        temp = self.root / "last-search.tmp"
        temp.write_text(json.dumps({"terms": terms, "items": items}, ensure_ascii=False), "utf-8")
        temp.replace(self.root / "last-search.json")

    def load_session(self):
        try:
            data = json.loads((self.root / "last-search.json").read_text("utf-8"))
            # A tampered session must not display arbitrary local files.
            data["items"] = [r for r in data["items"][:500] if Path(r["thumbnail"]).resolve().parent == self.root.resolve()
                             and Path(r["thumbnail"]).is_file() and public_url(r["source_url"]) and public_url(r["image_url"])]
            return data
        except (OSError, ValueError, KeyError, TypeError):
            return {"terms": "", "items": []}


def similarity(vector, target, traits, weights):
    semantic = float(np.clip(np.dot(vector, target), 0, 1))
    valid = {k: float(w) for k, w in weights.items() if k in VALID_TAGS and np.isfinite(w) and w > 0 and k[0] != "height"}
    if valid:
        trait_score = sum(traits.get(group, {}).get(value, 0) * w for (group, value), w in valid.items()) / sum(valid.values())
        semantic = .5 * semantic + .5 * trait_score
    return 100 * semantic


def discover_task(cache, engine, terms, page, minimum, reference=None, weights=None, seen=(), provider=None):
    """Download public previews, then compute every match score on this computer."""
    def run(task):
        stop = task.isInterruptionRequested
        task.progress.emit(0, 0, "Searching public images…")
        candidates = (provider or BingImages()).search(terms, page, stop)
        unique, used = [], set(seen)
        for item in candidates:
            if item["id"] not in used and quality_passes(item, minimum):
                unique.append(dict(item, minimum_resolution=minimum))
                used.add(item["id"])
        rows, errors, hashes = [], [], set()
        def preview(item):
            check_cancel(stop)
            path, _, _ = cache.image(item["thumbnail_url"], stop=stop)
            item = dict(item, thumbnail=path)
            item["preview_hash"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            return item
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(preview, row) for row in unique]
            for index, future in enumerate(as_completed(futures)):
                try:
                    row = future.result()
                    if row["preview_hash"] not in hashes:
                        rows.append(row)
                        hashes.add(row["preview_hash"])
                except Cancelled:
                    pass
                except Exception as error:
                    errors.append(str(error))
                task.progress.emit(index + 1, len(unique), f"Loading previews · {index + 1} of {len(unique)}")
        if stop():
            return {"cancelled": True, "items": [], "page": page}
        if rows:
            engine.load(lambda msg: task.progress.emit(0, 0, msg))
            check_cancel(stop)
            if reference and reference.get("embedding") is not None and reference.get("model_version") == engine.version:
                target = np.frombuffer(reference["embedding"], dtype=np.float32).copy()
            elif reference:
                target = engine.analyze([reference["path"]])[0][1]
            else:
                target = engine.encode_text(terms)
            target = target / max(float(np.linalg.norm(target)), 1e-8)
            for start in range(0, len(rows), 8):
                check_cancel(stop)
                chunk = rows[start:start + 8]
                analyses = engine.analyze([r["thumbnail"] for r in chunk])
                for row, (traits, vector) in zip(chunk, analyses):
                    row["match_score"] = similarity(vector, target, traits, weights or {})
                task.progress.emit(min(start + 8, len(rows)), len(rows), "Comparing images locally…")
            rows.sort(key=lambda row: -row["match_score"])
        return {"items": rows, "page": page, "candidates": len(candidates), "eligible": len(unique), "errors": errors,
                "cancelled": False, "more": bool(candidates) and page < 15}
    return run


def save_to_library(path, item, paths, db):
    from .importer import import_one
    result = import_one(path, paths, db, copy=True)
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with db.connect() as connection:
        row = connection.execute("SELECT id FROM images WHERE digest=?", (digest,)).fetchone()
        image_id = row["id"]
        connection.execute("INSERT OR IGNORE INTO web_sources(image_id,source_url,image_url) VALUES (?,?,?)",
                           (image_id, item["source_url"], item["image_url"]))
        if result == "imported":
            connection.execute("UPDATE images SET name=?,source_path=? WHERE id=?", (item["name"][:240], item["source_url"], image_id))
    return {"image_id": image_id, "message": "Saved to your library." if result == "imported" else "Already in your library.", "imported": result == "imported"}


def reference_discovery_task(cache, engine, db, reference, page, minimum, weights=None, seen=()):
    """Derive search terms solely from a local photo, analyzing it first when needed."""
    def run(task):
        check_cancel(task.isInterruptionRequested)
        image = db.get_image(reference["id"]) if page == 1 else reference
        if not image:
            raise OnlineError("This photo is no longer in the library. Select another photo.")
        if image.get("embedding") is None or image.get("model_version") != engine.version:
            task.progress.emit(0, 0, "Understanding your selected photo locally…")
            engine.load(lambda message: task.progress.emit(0, 0, message))
            check_cancel(task.isInterruptionRequested)
            scores, vector = engine.analyze([image["path"]])[0]
            db.save_analysis(image["id"], scores, vector, engine.version)
            image = db.get_image(image["id"])
        check_cancel(task.isInterruptionRequested)
        terms = suggested_terms(image=image)
        result = discover_task(cache, engine, terms, page, minimum, image, weights, seen)(task)
        return dict(result, terms=terms, reference=image)
    return run
