"""Hybrid Search Engine: Structured Operators + Diacritic-Folded SQLite FTS5 + N-Gram RRF."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from localrecall.storage.database import CaptureRecord, Database, SearchResult, fold_text


def normalize_for_matching(text: str) -> str:
    """Normalizes Turkish/Unicode diacritics and punctuation for fuzzy matching."""
    folded = fold_text(text)
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


@dataclass(slots=True)
class ParsedQuery:
    """Structured search operators parsed from a user query string."""

    raw: str
    free_text: str = ""
    app_filter: str | None = None
    exact_phrases: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    pinned_only: bool = False

    @property
    def highlight_query(self) -> str:
        parts = [self.free_text, *self.exact_phrases]
        return " ".join(p for p in parts if p).strip()

    @property
    def has_text_query(self) -> bool:
        return bool(self.free_text.strip() or self.exact_phrases)


_OPERATOR_TOKEN_RE = re.compile(
    r'(?P<neg>-)?(?:(?P<key>app|pinned|is):(?P<val>"[^"]+"|\S+)|(?P<quote>"[^"]+")|(?P<word>\S+))',
    re.UNICODE,
)


def parse_search_query(raw_query: str) -> ParsedQuery:
    """
    Parses structured operators:
      - `app:vscode` or `app:"Visual Studio"` -> app substring filter
      - `"exact phrase"` -> exact phrase match
      - `-exclude` / `-"excluded phrase"` -> negative filter
      - `pinned:true` / `pinned:1` / `is:pinned` -> bookmarked captures only
    """
    parsed = ParsedQuery(raw=raw_query)
    free_tokens: list[str] = []

    for m in _OPERATOR_TOKEN_RE.finditer(raw_query or ""):
        is_neg = bool(m.group("neg"))
        key = (m.group("key") or "").lower()
        val = (m.group("val") or "").strip('"')
        quote = m.group("quote")
        word = m.group("word")

        if key == "app" and val:
            parsed.app_filter = val
        elif key == "pinned" and val.lower() in ("true", "1", "yes", "on"):
            parsed.pinned_only = True
        elif key == "is" and val.lower() in ("pinned", "bookmark", "bookmarked", "star"):
            parsed.pinned_only = True
        elif quote is not None:
            inner = quote.strip('"').strip()
            if inner:
                if is_neg:
                    parsed.exclude_terms.append(inner)
                else:
                    parsed.exact_phrases.append(inner)
        elif word is not None:
            if is_neg:
                if word.strip():
                    parsed.exclude_terms.append(word.strip())
            else:
                free_tokens.append(word)

    parsed.free_text = " ".join(free_tokens).strip()
    return parsed


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
    """
    Combines instant diacritic-folded SQLite FTS5 (scales to 100k+ records in <2 ms)
    with character n-gram RRF fuzzy fallback for OCR typos (e.g. 'LocaIRecall').
    """

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
        pinned_only: bool = False,
        limit: int = 100,
    ) -> list[SearchResult]:
        parsed = parse_search_query(query)
        eff_pinned = pinned_only or parsed.pinned_only
        eff_app_like = parsed.app_filter

        if not parsed.has_text_query:
            return self.db.search(
                query="",
                app_name=app_name,
                app_filter_like=eff_app_like,
                exclude_terms=parsed.exclude_terms,
                pinned_only=eff_pinned,
                start=start,
                end=end,
                limit=limit,
            )

        # 1. Fast FTS5 query (covers exact, prefix, AND Turkish diacritic-folded across ALL rows!)
        fts_results = self.db.search(
            query=parsed.free_text,
            app_name=app_name,
            app_filter_like=eff_app_like,
            exact_phrases=parsed.exact_phrases,
            exclude_terms=parsed.exclude_terms,
            pinned_only=eff_pinned,
            start=start,
            end=end,
            limit=limit,
        )
        if mode == "fts":
            return fts_results

        # 2. OCR-typo resilient character n-gram fuzzy candidate scan
        text_for_fuzzy = parsed.highlight_query
        q_norm = normalize_for_matching(text_for_fuzzy)
        q_tokens = [t for t in q_norm.split() if len(t) >= 2]
        q_grams = _char_ngrams(text_for_fuzzy, n=3)
        if not q_grams:
            return fts_results

        candidates = self.db.get_recent(
            limit=self.fuzzy_pool_size,
            app_name=app_name,
            app_filter_like=eff_app_like,
            start=start,
            end=end,
            pinned_only=eff_pinned,
        )

        excl_norm = [normalize_for_matching(e) for e in parsed.exclude_terms if e.strip()]
        exact_norm = [normalize_for_matching(p) for p in parsed.exact_phrases if p.strip()]

        fuzzy_scored: list[tuple[float, CaptureRecord]] = []
        for rec in candidates:
            haystack = f"{rec.app_name} {rec.window_title} {rec.note} {rec.ocr_text[:2000]}"
            hay_norm = normalize_for_matching(haystack)
            if not hay_norm:
                continue
            if excl_norm and any(ex in hay_norm for ex in excl_norm if ex):
                continue
            if exact_norm and not all(ep in hay_norm for ep in exact_norm if ep):
                continue

            token_hits = sum(1 for tok in q_tokens if tok in hay_norm)
            token_ratio = (token_hits / len(q_tokens)) if q_tokens else 0.0

            snippet_focus = _extract_best_snippet(rec, q_tokens, max_len=240)
            focus_text = f"{rec.app_name} {rec.window_title} {rec.note} {snippet_focus}"
            sim = _cosine_similarity(q_grams, _char_ngrams(focus_text, n=3))

            combined = (sim * 0.65) + (token_ratio * 0.35)
            if combined >= self.min_fuzzy_score:
                fuzzy_scored.append((combined, rec))

        fuzzy_scored.sort(key=lambda item: item[0], reverse=True)

        # 3. Reciprocal Rank Fusion (RRF)
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
