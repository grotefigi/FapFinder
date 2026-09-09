from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

import numpy as np

from .traits import VALID_TAGS, label_for


@dataclass
class SearchQuery:
    weights: dict[tuple[str, str], float] = field(default_factory=dict)
    text: str = ""
    filename: str = ""
    minimum: float = 0
    view: str = "all"
    reference_id: int | None = None


def search(db, query, text_embedding=None, model_version=None):
    rows = db.list_images(query.view, query.filename)
    weights = {key: float(weight) for key, weight in query.weights.items() if key in VALID_TAGS and np.isfinite(weight) and weight > 0}
    scores = {row["id"]: 0.0 for row in rows}
    evidence = set()
    total_weight = sum(weights.values())
    if weights:
        for image_id, group, value, score in db.effective_scores():
            if (group, value) in weights and image_id in scores:
                scores[image_id] += weights[group, value] * score
                evidence.add(image_id)
    vector = text_embedding
    vectors = None
    if query.reference_id is not None:
        source = db.get_image(query.reference_id)
        if source and source["embedding"] is not None:
            model_version = source["model_version"]
            vectors = db.embeddings(model_version)
            vector = vectors.get(query.reference_id)
        else:
            raise ValueError("Analyze this image before finding similar images.")
    if query.text and vector is None:
        raise ValueError("Text similarity requires the local model. Use tags or filename search while setup is incomplete.")
    if vector is not None:
        vector = np.asarray(vector, dtype=np.float32)
        if vector.ndim != 1 or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
            raise ValueError("Invalid search embedding")
        vector = vector / np.linalg.norm(vector)
        vectors = vectors if vectors is not None else db.embeddings(model_version)
        semantic_weight = total_weight if total_weight else 1.0
        total_weight += semantic_weight
        candidates = [(i, v) for i, v in vectors.items() if i in scores and v.shape == vector.shape]
        if candidates:
            similarities = np.stack([v for _, v in candidates]) @ vector
            for (image_id, _), similarity in zip(candidates, similarities):
                scores[image_id] += semantic_weight * float(np.clip(similarity, 0, 1))
                evidence.add(image_id)
    ranked = bool(total_weight)
    results = []
    for row in rows:
        if row["id"] == query.reference_id or (ranked and row["id"] not in evidence):
            continue
        score = float(np.clip(scores[row["id"]] / total_weight * 100, 0, 100)) if ranked else None
        if score is not None and score + 1e-6 < query.minimum:
            continue
        results.append({**row, "match_score": score})
    if ranked:
        results.sort(key=lambda item: (-item["match_score"], -item["id"]))
    return results


def web_search_url(query):
    terms = ["adult woman portrait"]
    if query.text.strip():
        terms.append(query.text.strip()[:400])
    terms.extend(label_for(group, value) for (group, value), weight in query.weights.items()
                 if weight > 0 and (group, value) in VALID_TAGS and value != "unknown")
    return "https://www.google.com/search?" + urlencode({"tbm": "isch", "safe": "active", "q": " ".join(terms)})
