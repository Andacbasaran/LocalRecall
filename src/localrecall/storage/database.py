"""Thread-safe SQLite + FTS5 database with accent-folded Turkish indexing, telemetry & quotas."""

from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

_TR_FOLD_MAP = str.maketrans(
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


def fold_text(text: str) -> str:
    """Accent- and Turkish-diacritic-folds text for sub-millisecond FTS5 lookup."""
    if not text:
        return ""
    step1 = text.translate(_TR_FOLD_MAP).lower()
    decomposed = unicodedata.normalize("NFKD", step1)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip()


@dataclass(slots=True)
class CaptureRecord:
    """Single screen memory record."""

    id: int
    timestamp: str
    image_path: str
    app_name: str
    window_title: str
    ocr_text: str
    width: int
    height: int
    ocr_done: bool = True
    ocr_boxes: str = "[]"
    file_size_bytes: int = 0
    pinned: bool = False
    note: str = ""
    pii_redacted: bool = False
    image_archived: bool = False


@dataclass(slots=True)
class SearchResult:
    """Full-text or hybrid search match."""

    record: CaptureRecord
    snippet: str
    rank: float
    match_type: str = "fts"


def _extract_tokens(raw_text: str) -> list[str]:
    return re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", raw_text, flags=re.UNICODE)


def _sanitize_fts_query(
    raw_query: str,
    exact_phrases: Sequence[str] = (),
    exclude_terms: Sequence[str] = (),
) -> str:
    """
    Builds a safe FTS5 query matching both original and diacritic-folded columns,
    plus exact phrase quotes and NOT exclusions.
    """
    clauses: list[str] = []

    tokens = _extract_tokens(raw_query)
    for tok in tokens:
        folded = fold_text(tok)
        clean_orig = tok.replace('"', "")
        if folded and folded != clean_orig.lower():
            clauses.append(f'("{clean_orig}"* OR "{folded}"*)')
        else:
            clauses.append(f'"{clean_orig}"*')

    for phrase in exact_phrases:
        p_clean = " ".join(_extract_tokens(phrase))
        p_folded = " ".join(_extract_tokens(fold_text(phrase)))
        if p_clean:
            if p_folded and p_folded != p_clean.lower():
                clauses.append(f'("{p_clean}" OR "{p_folded}")')
            else:
                clauses.append(f'"{p_clean}"')

    if not clauses:
        return ""

    positive = " AND ".join(clauses)

    neg_parts: list[str] = []
    for excl in exclude_terms:
        e_clean = " ".join(_extract_tokens(excl))
        e_folded = " ".join(_extract_tokens(fold_text(excl)))
        if e_clean:
            neg_parts.append(f'NOT "{e_clean}"')
            if e_folded and e_folded != e_clean.lower():
                neg_parts.append(f'NOT "{e_folded}"')

    if neg_parts:
        return f"({positive}) " + " ".join(neg_parts)
    return positive


class Database:
    """Thread-safe SQLite + FTS5 database manager with automatic schema migrations."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=15.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA temp_store=MEMORY;")

            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    app_name TEXT NOT NULL DEFAULT '',
                    window_title TEXT NOT NULL DEFAULT '',
                    ocr_text TEXT NOT NULL DEFAULT '',
                    ocr_text_folded TEXT NOT NULL DEFAULT '',
                    ocr_boxes TEXT NOT NULL DEFAULT '[]',
                    width INTEGER NOT NULL DEFAULT 0,
                    height INTEGER NOT NULL DEFAULT 0,
                    ocr_done INTEGER NOT NULL DEFAULT 0,
                    file_size_bytes INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    pii_redacted INTEGER NOT NULL DEFAULT 0,
                    image_archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_captures_timestamp ON captures(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_captures_app_name ON captures(app_name);

                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '0'
                );
                """
            )

            # Automatic column migration for existing v0.1.0 databases
            cols = {row["name"] for row in cur.execute("PRAGMA table_info(captures)").fetchall()}
            migrations = [
                ("ocr_boxes", "TEXT NOT NULL DEFAULT '[]'"),
                ("ocr_text_folded", "TEXT NOT NULL DEFAULT ''"),
                ("file_size_bytes", "INTEGER NOT NULL DEFAULT 0"),
                ("pinned", "INTEGER NOT NULL DEFAULT 0"),
                ("note", "TEXT NOT NULL DEFAULT ''"),
                ("pii_redacted", "INTEGER NOT NULL DEFAULT 0"),
                ("image_archived", "INTEGER NOT NULL DEFAULT 0"),
            ]
            added_folded = False
            for col_name, col_def in migrations:
                if col_name not in cols:
                    cur.execute(f"ALTER TABLE captures ADD COLUMN {col_name} {col_def}")
                    if col_name == "ocr_text_folded":
                        added_folded = True

            cur.execute("CREATE INDEX IF NOT EXISTS idx_captures_pinned ON captures(pinned, timestamp DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_captures_ocr_done ON captures(ocr_done);")

            # Check if captures_fts exists and already has ocr_text_folded column
            fts_exists = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='captures_fts'"
            ).fetchone()
            fts_cols: set[str] = set()
            if fts_exists:
                fts_cols = {
                    row["name"] for row in cur.execute("PRAGMA table_info(captures_fts)").fetchall()
                }

            needs_fts_rebuild = (not fts_exists) or ("ocr_text_folded" not in fts_cols) or ("note" not in fts_cols)
            if added_folded or needs_fts_rebuild:
                # Backfill ocr_text_folded for any rows missing it
                rows = cur.execute(
                    "SELECT id, app_name, window_title, ocr_text, note FROM captures WHERE ocr_text_folded = '' AND (ocr_text != '' OR window_title != '' OR app_name != '')"
                ).fetchall()
                if rows:
                    cur.executemany(
                        "UPDATE captures SET ocr_text_folded = ? WHERE id = ?",
                        [
                            (
                                fold_text(f"{r['app_name']} {r['window_title']} {r['ocr_text']} {r['note']}"),
                                int(r["id"]),
                            )
                            for r in rows
                        ],
                    )

                cur.executescript(
                    """
                    DROP TRIGGER IF EXISTS captures_ai;
                    DROP TRIGGER IF EXISTS captures_ad;
                    DROP TRIGGER IF EXISTS captures_au;
                    DROP TABLE IF EXISTS captures_fts;

                    CREATE VIRTUAL TABLE captures_fts USING fts5(
                        app_name,
                        window_title,
                        ocr_text,
                        ocr_text_folded,
                        note,
                        content='captures',
                        content_rowid='id',
                        tokenize='unicode61 remove_diacritics 0'
                    );

                    CREATE TRIGGER captures_ai AFTER INSERT ON captures BEGIN
                        INSERT INTO captures_fts(rowid, app_name, window_title, ocr_text, ocr_text_folded, note)
                        VALUES (new.id, new.app_name, new.window_title, new.ocr_text, new.ocr_text_folded, new.note);
                    END;

                    CREATE TRIGGER captures_ad AFTER DELETE ON captures BEGIN
                        INSERT INTO captures_fts(captures_fts, rowid, app_name, window_title, ocr_text, ocr_text_folded, note)
                        VALUES ('delete', old.id, old.app_name, old.window_title, old.ocr_text, old.ocr_text_folded, old.note);
                    END;

                    CREATE TRIGGER captures_au AFTER UPDATE ON captures BEGIN
                        INSERT INTO captures_fts(captures_fts, rowid, app_name, window_title, ocr_text, ocr_text_folded, note)
                        VALUES ('delete', old.id, old.app_name, old.window_title, old.ocr_text, old.ocr_text_folded, old.note);
                        INSERT INTO captures_fts(rowid, app_name, window_title, ocr_text, ocr_text_folded, note)
                        VALUES (new.id, new.app_name, new.window_title, new.ocr_text, new.ocr_text_folded, new.note);
                    END;

                    INSERT INTO captures_fts(captures_fts) VALUES('rebuild');
                    """
                )

            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CaptureRecord:
        keys = set(row.keys())
        return CaptureRecord(
            id=int(row["id"]),
            timestamp=str(row["timestamp"]),
            image_path=str(row["image_path"]),
            app_name=str(row["app_name"]),
            window_title=str(row["window_title"]),
            ocr_text=str(row["ocr_text"]),
            width=int(row["width"]),
            height=int(row["height"]),
            ocr_done=bool(row["ocr_done"]),
            ocr_boxes=str(row["ocr_boxes"] if "ocr_boxes" in keys else "[]"),
            file_size_bytes=int(row["file_size_bytes"] if "file_size_bytes" in keys else 0),
            pinned=bool(row["pinned"] if "pinned" in keys else 0),
            note=str(row["note"] if "note" in keys else ""),
            pii_redacted=bool(row["pii_redacted"] if "pii_redacted" in keys else 0),
            image_archived=bool(row["image_archived"] if "image_archived" in keys else 0),
        )

    def insert_capture(
        self,
        image_path: str,
        app_name: str,
        window_title: str,
        width: int,
        height: int,
        ocr_text: str = "",
        ocr_done: bool = False,
        ocr_boxes: str = "[]",
        timestamp: datetime | None = None,
        file_size_bytes: int = 0,
        pinned: bool = False,
        note: str = "",
        pii_redacted: bool = False,
    ) -> int:
        ts_str = (timestamp or datetime.now()).isoformat(timespec="seconds")
        folded = fold_text(f"{app_name} {window_title} {ocr_text} {note}")
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO captures (
                    timestamp, image_path, app_name, window_title, ocr_text, ocr_text_folded,
                    ocr_boxes, width, height, ocr_done, file_size_bytes, pinned, note, pii_redacted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_str,
                    image_path,
                    app_name,
                    window_title,
                    ocr_text,
                    folded,
                    ocr_boxes,
                    width,
                    height,
                    int(ocr_done),
                    int(file_size_bytes),
                    int(pinned),
                    note,
                    int(pii_redacted),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_ocr_text(
        self,
        capture_id: int,
        ocr_text: str,
        ocr_boxes: str = "[]",
        pii_redacted: bool = False,
        file_size_bytes: int | None = None,
    ) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT app_name, window_title, note FROM captures WHERE id = ?",
                (capture_id,),
            ).fetchone()
            if not row:
                return
            folded = fold_text(f"{row['app_name']} {row['window_title']} {ocr_text} {row['note']}")
            if file_size_bytes is not None:
                self._conn.execute(
                    """
                    UPDATE captures
                    SET ocr_text = ?, ocr_text_folded = ?, ocr_boxes = ?, ocr_done = 1,
                        pii_redacted = ?, file_size_bytes = ?
                    WHERE id = ?
                    """,
                    (ocr_text, folded, ocr_boxes, int(pii_redacted), int(file_size_bytes), capture_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE captures
                    SET ocr_text = ?, ocr_text_folded = ?, ocr_boxes = ?, ocr_done = 1, pii_redacted = ?
                    WHERE id = ?
                    """,
                    (ocr_text, folded, ocr_boxes, int(pii_redacted), capture_id),
                )
            self._conn.commit()

    def get_pending_ocr(self, limit: int = 500) -> list[CaptureRecord]:
        """Returns records where OCR was not yet completed (for startup backfill)."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM captures
                WHERE ocr_done = 0 AND image_archived = 0 AND image_path != ''
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def set_pinned(self, capture_id: int, pinned: bool, note: str | None = None) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT app_name, window_title, ocr_text, note FROM captures WHERE id = ?",
                (capture_id,),
            ).fetchone()
            if not row:
                return
            new_note = row["note"] if note is None else note
            folded = fold_text(f"{row['app_name']} {row['window_title']} {row['ocr_text']} {new_note}")
            self._conn.execute(
                "UPDATE captures SET pinned = ?, note = ?, ocr_text_folded = ? WHERE id = ?",
                (int(pinned), new_note, folded, capture_id),
            )
            self._conn.commit()

    def update_note(self, capture_id: int, note: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT app_name, window_title, ocr_text, pinned FROM captures WHERE id = ?",
                (capture_id,),
            ).fetchone()
            if not row:
                return
            folded = fold_text(f"{row['app_name']} {row['window_title']} {row['ocr_text']} {note}")
            self._conn.execute(
                "UPDATE captures SET note = ?, ocr_text_folded = ? WHERE id = ?",
                (note, folded, capture_id),
            )
            self._conn.commit()

    def get_capture(self, capture_id: int) -> CaptureRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM captures WHERE id = ?",
                (capture_id,),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def get_recent(
        self,
        limit: int = 200,
        app_name: str | None = None,
        app_filter_like: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        pinned_only: bool = False,
    ) -> list[CaptureRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if app_name:
            clauses.append("app_name = ?")
            params.append(app_name)
        if app_filter_like:
            clauses.append("LOWER(app_name) LIKE ?")
            params.append(f"%{app_filter_like.strip().lower()}%")
        if pinned_only:
            clauses.append("pinned = 1")
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start.isoformat(timespec="seconds"))
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end.isoformat(timespec="seconds"))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM captures {where} ORDER BY timestamp DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [self._row_to_record(r) for r in rows]

    def get_timeline(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[CaptureRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start.isoformat(timespec="seconds"))
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end.isoformat(timespec="seconds"))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT * FROM (
                SELECT * FROM captures {where}
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
            ) sub
            ORDER BY timestamp ASC, id ASC
        """
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [self._row_to_record(r) for r in rows]

    def search(
        self,
        query: str,
        app_name: str | None = None,
        app_filter_like: str | None = None,
        exact_phrases: Sequence[str] = (),
        exclude_terms: Sequence[str] = (),
        pinned_only: bool = False,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Instant FTS5 search over original + Turkish/diacritic-folded text + notes."""
        fts_query = _sanitize_fts_query(
            query,
            exact_phrases=exact_phrases,
            exclude_terms=exclude_terms,
        )
        if not fts_query:
            records = self.get_recent(
                limit=limit,
                app_name=app_name,
                app_filter_like=app_filter_like,
                start=start,
                end=end,
                pinned_only=pinned_only,
            )
            if exclude_terms:
                excl_folded = [fold_text(e) for e in exclude_terms if e.strip()]
                records = [
                    r
                    for r in records
                    if not any(
                        ef in fold_text(f"{r.app_name} {r.window_title} {r.ocr_text} {r.note}")
                        for ef in excl_folded
                        if ef
                    )
                ]
            return [
                SearchResult(record=r, snippet=(r.ocr_text or r.window_title)[:160], rank=0.0, match_type="recent")
                for r in records
            ]

        clauses = ["captures_fts MATCH ?"]
        params: list[object] = [fts_query]

        if app_name:
            clauses.append("c.app_name = ?")
            params.append(app_name)
        if app_filter_like:
            clauses.append("LOWER(c.app_name) LIKE ?")
            params.append(f"%{app_filter_like.strip().lower()}%")
        if pinned_only:
            clauses.append("c.pinned = 1")
        if start is not None:
            clauses.append("c.timestamp >= ?")
            params.append(start.isoformat(timespec="seconds"))
        if end is not None:
            clauses.append("c.timestamp <= ?")
            params.append(end.isoformat(timespec="seconds"))

        where = " AND ".join(clauses)
        sql = f"""
            SELECT
                c.*,
                snippet(captures_fts, 2, '[', ']', '…', 18) AS snippet,
                snippet(captures_fts, 3, '[', ']', '…', 18) AS snippet_folded,
                bm25(captures_fts, 2.0, 3.0, 1.0, 1.2, 2.5) AS rank
            FROM captures_fts
            JOIN captures c ON c.id = captures_fts.rowid
            WHERE {where}
            ORDER BY rank ASC, c.timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            results: list[SearchResult] = []
            for r in rows:
                snip = str(r["snippet"] or "")
                if "[" not in snip and r["snippet_folded"]:
                    snip = str(r["snippet_folded"] or "")
                results.append(
                    SearchResult(
                        record=self._row_to_record(r),
                        snippet=snip,
                        rank=float(r["rank"]),
                        match_type="fts",
                    )
                )
            return results

    def list_apps(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT app_name FROM captures WHERE app_name != '' ORDER BY app_name COLLATE NOCASE"
            ).fetchall()
            return [str(r["app_name"]) for r in rows]

    def get_app_breakdown(self, limit: int = 15) -> list[tuple[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT COALESCE(NULLIF(app_name, ''), 'Unknown') AS app, COUNT(*) AS cnt
                FROM captures
                GROUP BY app
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [(str(r["app"]), int(r["cnt"])) for r in rows]

    def get_hourly_activity(self, days: int = 7) -> list[tuple[int, int]]:
        """Returns 24 (hour, capture_count) buckets over the last N days."""
        cutoff = (datetime.now() - timedelta(days=max(1, days))).isoformat(timespec="seconds")
        counts = {h: 0 for h in range(24)}
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT CAST(substr(timestamp, 12, 2) AS INTEGER) AS hr, COUNT(*) AS cnt
                FROM captures
                WHERE timestamp >= ?
                GROUP BY hr
                """,
                (cutoff,),
            ).fetchall()
            for r in rows:
                hr = r["hr"]
                if hr is not None and 0 <= int(hr) <= 23:
                    counts[int(hr)] = int(r["cnt"])
        return [(h, counts[h]) for h in range(24)]

    def delete_capture(self, capture_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT image_path FROM captures WHERE id = ?",
                (capture_id,),
            ).fetchone()
            if not row:
                return None
            image_path = str(row["image_path"])
            self._conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
            self._conn.commit()
            return image_path

    def purge_last_minutes(self, minutes: int) -> list[str]:
        if minutes <= 0:
            return []
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                "SELECT image_path FROM captures WHERE timestamp >= ?",
                (cutoff,),
            ).fetchall()
            if not rows:
                return []
            image_paths = [str(r["image_path"]) for r in rows if r["image_path"]]
            self._conn.execute("DELETE FROM captures WHERE timestamp >= ?", (cutoff,))
            self._conn.commit()
            return image_paths

    def purge_today(self) -> list[str]:
        start_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(
            timespec="seconds"
        )
        with self._lock:
            rows = self._conn.execute(
                "SELECT image_path FROM captures WHERE timestamp >= ?",
                (start_today,),
            ).fetchall()
            if not rows:
                return []
            image_paths = [str(r["image_path"]) for r in rows if r["image_path"]]
            self._conn.execute("DELETE FROM captures WHERE timestamp >= ?", (start_today,))
            self._conn.commit()
            return image_paths

    def purge_by_app(self, app_name: str) -> list[str]:
        if not app_name:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT image_path FROM captures WHERE app_name = ?",
                (app_name,),
            ).fetchall()
            if not rows:
                return []
            image_paths = [str(r["image_path"]) for r in rows if r["image_path"]]
            self._conn.execute("DELETE FROM captures WHERE app_name = ?", (app_name,))
            self._conn.commit()
            return image_paths

    def purge_older_than(self, days: int) -> list[str]:
        if days <= 0:
            return []
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, image_path FROM captures WHERE timestamp < ? AND pinned = 0",
                (cutoff,),
            ).fetchall()
            if not rows:
                return []
            image_paths = [str(r["image_path"]) for r in rows if r["image_path"]]
            self._conn.execute("DELETE FROM captures WHERE timestamp < ? AND pinned = 0", (cutoff,))
            self._conn.commit()
            return image_paths

    def archive_images_older_than(self, days: int) -> list[str]:
        """
        OCR-Only Archival Mode: Marks old unpinned captures as archived so their WebP
        files can be removed while keeping searchable OCR text & timestamps intact.
        """
        if days <= 0:
            return []
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, image_path FROM captures
                WHERE timestamp < ? AND pinned = 0 AND image_archived = 0 AND ocr_done = 1 AND image_path != ''
                """,
                (cutoff,),
            ).fetchall()
            if not rows:
                return []
            ids = [int(r["id"]) for r in rows]
            paths = [str(r["image_path"]) for r in rows if r["image_path"]]
            placeholders = ",".join("?" for _ in ids)
            self._conn.execute(
                f"UPDATE captures SET image_archived = 1, file_size_bytes = 0 WHERE id IN ({placeholders})",
                ids,
            )
            self._conn.commit()
            return paths

    def enforce_storage_quota(self, max_bytes: int) -> list[str]:
        """FIFO deletes oldest unpinned captures until stored image bytes <= max_bytes."""
        if max_bytes <= 0:
            return []
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(file_size_bytes), 0) AS total_bytes FROM captures WHERE image_archived = 0"
            ).fetchone()
            total_bytes = int(row["total_bytes"]) if row else 0
            if total_bytes <= max_bytes:
                return []

            rows = self._conn.execute(
                """
                SELECT id, image_path, file_size_bytes FROM captures
                WHERE pinned = 0 AND image_archived = 0
                ORDER BY timestamp ASC, id ASC
                """
            ).fetchall()
            to_delete_ids: list[int] = []
            to_delete_paths: list[str] = []
            running = total_bytes
            for r in rows:
                if running <= max_bytes:
                    break
                to_delete_ids.append(int(r["id"]))
                if r["image_path"]:
                    to_delete_paths.append(str(r["image_path"]))
                running -= max(1, int(r["file_size_bytes"]))

            if to_delete_ids:
                placeholders = ",".join("?" for _ in to_delete_ids)
                self._conn.execute(
                    f"DELETE FROM captures WHERE id IN ({placeholders})",
                    to_delete_ids,
                )
                self._conn.commit()
            return to_delete_paths

    def increment_metric(self, key: str, delta: int = 1) -> int:
        with self._lock:
            row = self._conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
            current = int(row["value"]) if row and str(row["value"]).lstrip("-").isdigit() else 0
            new_val = max(0, current + int(delta))
            self._conn.execute(
                "INSERT INTO app_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(new_val)),
            )
            self._conn.commit()
            return new_val

    def set_metric(self, key: str, value: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO app_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(max(0, int(value)))),
            )
            self._conn.commit()

    def get_metrics(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM app_meta").fetchall()
            out: dict[str, int] = {}
            for r in rows:
                try:
                    out[str(r["key"])] = int(r["value"])
                except (TypeError, ValueError):
                    out[str(r["key"])] = 0
            return out

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")

    def get_stats(self) -> dict[str, int]:
        """Returns aggregate capture, OCR, storage, and privacy telemetry in O(1) SQL."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(ocr_done), 0) AS ocr_done,
                    COALESCE(SUM(pinned), 0) AS pinned,
                    COALESCE(SUM(image_archived), 0) AS archived,
                    COALESCE(SUM(file_size_bytes), 0) AS total_image_bytes,
                    COALESCE(SUM(pii_redacted), 0) AS pii_captures
                FROM captures
                """
            ).fetchone()
            metrics = self.get_metrics()
            return {
                "total": int(row["total"]),
                "ocr_done": int(row["ocr_done"]),
                "pinned": int(row["pinned"]),
                "archived": int(row["archived"]),
                "total_image_bytes": int(row["total_image_bytes"]),
                "pii_captures": int(row["pii_captures"]),
                "privacy_blocks": metrics.get("privacy_blocks_count", 0),
                "pii_redactions": metrics.get("pii_redactions_count", 0),
                "dedup_checked": metrics.get("dedup_checked_count", 0),
                "dedup_skipped": metrics.get("dedup_skipped_count", 0),
            }
