"""FTS5 + karakter n-gram kosinüs benzerliği tabanlı Hibrit Arama Motoru (RRF)."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime

from localrecall.storage.database import CaptureRecord, Database, SearchResult

_TR_FOLD = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "Ç": "c",
        "Ğ": "g",
        "İ": "i",
        "I": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
    }
)


def normalize_for_matching(text: str) -> str:
    """Türkçe karakterleri normalize ederek OCR/klavye farklarını azaltır."""
    folded = text.translate(_TR_FOLD).lower()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _char_ngrams(text: str, n: int = 3) -> Counter[str]:
    norm = normalize_for_matching(text)
    if not norm:
        return Counter()
    padded = f" {norm} "
    if len(padded) < n:
        return Counter({padded: 1})
    return Counter(padded[i : i + n] for i in range(len(padded) - n + 1))


def _cosine_similarity(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_best_snippet(record: CaptureRecord, query_tokens: list[str], max_len: int = 140) -> str:
    """OCR metninden sorgu kelimelerine en yakın satırı özet olarak seçer."""
    if not record.ocr_text:
        return record.window_title[:max_len]

    lines = [ln.strip() for ln in record.ocr_text.splitlines() if ln.strip()]
    if not lines:
        return record.window_title[:max_len]

    best_line = lines[0]
    best_hits = -1
    for ln in lines:
        norm_ln = normalize_for_matching(ln)
        hits = sum(1 for tok in query_tokens if tok in norm_ln)
        if hits > best_hits:
            best_hits = hits
            best_line = ln
    return best_line[:max_len]


class HybridSearchEngine:
    """SQLite FTS5 ile karakter n-gram bulanık eşleşmeyi RRF ile birleştirir."""

    def __init__(self, db: Database, fuzzy_pool_size: int = 400, min_fuzzy_score: float = 0.16) -> None:
        self.db = db
        self.fuzzy_pool_size = fuzzy_pool_size
        self.min_fuzzy_score = min_fuzzy_score

    def search(
        self,
        query: str,
        mode: str = "hybrid",
        app_name: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        cleaned = query.strip()
        if not cleaned:
            return self.db.search(
                query="",
                app_name=app_name,
                start=start,
                end=end,
                limit=limit,
            )

        fts_results = self.db.search(
            query=cleaned,
            app_name=app_name,
            start=start,
            end=end,
            limit=limit,
        )
        if mode == "fts":
            return fts_results

        # Bulanık / OCR-hatasına dayanıklı aday taraması
        q_norm = normalize_for_matching(cleaned)
        q_tokens = [t for t in q_norm.split() if len(t) >= 2]
        q_grams = _char_ngrams(cleaned, n=3)
        if not q_grams:
            return fts_results

        candidates = self.db.get_recent(
            limit=self.fuzzy_pool_size,
            app_name=app_name,
            start=start,
            end=end,
        )

        fuzzy_scored: list[tuple[float, CaptureRecord]] = []
        for rec in candidates:
            haystack = f"{rec.app_name} {rec.window_title} {rec.ocr_text[:2000]}"
            hay_norm = normalize_for_matching(haystack)
            if not hay_norm:
                continue

            # Token bazlı hızlı bonus + 3-gram kosinüs benzerliği
            token_hits = sum(1 for tok in q_tokens if tok in hay_norm)
            token_ratio = (token_hits / len(q_tokens)) if q_tokens else 0.0

            # Sadece metnin en alakalı bölümünde 3-gram karşılaştır (uzun metinlerde seyrelmeyi önler)
            snippet_focus = _extract_best_snippet(rec, q_tokens, max_len=240)
            focus_text = f"{rec.app_name} {rec.window_title} {snippet_focus}"
            sim = _cosine_similarity(q_grams, _char_ngrams(focus_text, n=3))

            combined = (sim * 0.65) + (token_ratio * 0.35)
            if combined >= self.min_fuzzy_score:
                fuzzy_scored.append((combined, rec))

        fuzzy_scored.sort(key=lambda item: item[0], reverse=True)

        # Reciprocal Rank Fusion (RRF)
        rrf_k = 60.0
        scores: dict[int, float] = {}
        records_by_id: dict[int, CaptureRecord] = {}
        snippets_by_id: dict[int, str] = {}
        match_types: dict[int, str] = {}

        for rank_idx, res in enumerate(fts_results, start=1):
            cid = res.record.id
            scores[cid] = scores.get(cid, 0.0) + (2.0 / (rrf_k + rank_idx))
            records_by_id[cid] = res.record
            snippets_by_id[cid] = res.snippet
            match_types[cid] = "fts"

        for rank_idx, (sim_score, rec) in enumerate(fuzzy_scored[:limit], start=1):
            cid = rec.id
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (rrf_k + rank_idx)) + (sim_score * 0.01)
            records_by_id.setdefault(cid, rec)
            snippets_by_id.setdefault(cid, _extract_best_snippet(rec, q_tokens))
            match_types.setdefault(cid, "fuzzy")

        ordered_ids = sorted(
            scores.keys(),
            key=lambda cid: (scores[cid], records_by_id[cid].timestamp),
            reverse=True,
        )[:limit]

        return [
            SearchResult(
                record=records_by_id[cid],
                snippet=snippets_by_id[cid],
                rank=-scores[cid],
                match_type=match_types[cid],
            )
            for cid in ordered_ids
        ]
