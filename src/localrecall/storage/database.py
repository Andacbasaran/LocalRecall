"""SQLite + FTS5 tabanlı ekran hafızası veritabanı."""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(slots=True)
class CaptureRecord:
    """Tek bir ekran yakalama kaydı."""

    id: int
    timestamp: str
    image_path: str
    app_name: str
    window_title: str
    ocr_text: str
    width: int
    height: int
    ocr_done: bool = True


@dataclass(slots=True)
class SearchResult:
    """FTS5 tam metin arama sonucu."""

    record: CaptureRecord
    snippet: str
    rank: float


def _sanitize_fts_query(raw_query: str) -> str:
    """Kullanıcı arama sorgusunu güvenli FTS5 prefix/phrase sorgusuna dönüştürür."""
    tokens = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", raw_query, flags=re.UNICODE)
    if not tokens:
        return ""
    return " AND ".join(f'"{t}"*' for t in tokens)


class Database:
    """Thread-safe SQLite + FTS5 veritabanı yöneticisi."""

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
                    width INTEGER NOT NULL DEFAULT 0,
                    height INTEGER NOT NULL DEFAULT 0,
                    ocr_done INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_captures_timestamp ON captures(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_captures_app_name ON captures(app_name);

                CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
                    app_name,
                    window_title,
                    ocr_text,
                    content='captures',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 0'
                );

                CREATE TRIGGER IF NOT EXISTS captures_ai AFTER INSERT ON captures BEGIN
                    INSERT INTO captures_fts(rowid, app_name, window_title, ocr_text)
                    VALUES (new.id, new.app_name, new.window_title, new.ocr_text);
                END;

                CREATE TRIGGER IF NOT EXISTS captures_ad AFTER DELETE ON captures BEGIN
                    INSERT INTO captures_fts(captures_fts, rowid, app_name, window_title, ocr_text)
                    VALUES ('delete', old.id, old.app_name, old.window_title, old.ocr_text);
                END;

                CREATE TRIGGER IF NOT EXISTS captures_au AFTER UPDATE ON captures BEGIN
                    INSERT INTO captures_fts(captures_fts, rowid, app_name, window_title, ocr_text)
                    VALUES ('delete', old.id, old.app_name, old.window_title, old.ocr_text);
                    INSERT INTO captures_fts(rowid, app_name, window_title, ocr_text)
                    VALUES (new.id, new.app_name, new.window_title, new.ocr_text);
                END;
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CaptureRecord:
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
        timestamp: datetime | None = None,
    ) -> int:
        ts_str = (timestamp or datetime.now()).isoformat(timespec="seconds")
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO captures (timestamp, image_path, app_name, window_title, ocr_text, width, height, ocr_done)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts_str, image_path, app_name, window_title, ocr_text, width, height, int(ocr_done)),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_ocr_text(self, capture_id: int, ocr_text: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE captures SET ocr_text = ?, ocr_done = 1 WHERE id = ?",
                (ocr_text, capture_id),
            )
            self._conn.commit()

    def get_capture(self, capture_id: int) -> CaptureRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM captures WHERE id = ?",
                (capture_id,),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def get_recent(self, limit: int = 200, app_name: str | None = None) -> list[CaptureRecord]:
        with self._lock:
            if app_name:
                rows = self._conn.execute(
                    "SELECT * FROM captures WHERE app_name = ? ORDER BY timestamp DESC, id DESC LIMIT ?",
                    (app_name, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM captures ORDER BY timestamp DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def get_timeline(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[CaptureRecord]:
        """Zaman çizelgesi için kronolojik (eskiden yeniye) kayıt listesi döndürür."""
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
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """FTS5 kullanarak uygulama adı, pencere başlığı ve OCR metninde anında arama yapar."""
        fts_query = _sanitize_fts_query(query)
        if not fts_query:
            records = self.get_recent(limit=limit, app_name=app_name)
            return [SearchResult(record=r, snippet=r.ocr_text[:160], rank=0.0) for r in records]

        clauses = ["captures_fts MATCH ?"]
        params: list[object] = [fts_query]

        if app_name:
            clauses.append("c.app_name = ?")
            params.append(app_name)
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
                bm25(captures_fts, 2.0, 3.0, 1.0) AS rank
            FROM captures_fts
            JOIN captures c ON c.id = captures_fts.rowid
            WHERE {where}
            ORDER BY rank ASC, c.timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [
                SearchResult(
                    record=self._row_to_record(r),
                    snippet=str(r["snippet"] or ""),
                    rank=float(r["rank"]),
                )
                for r in rows
            ]

    def list_apps(self) -> list[str]:
        """Veritabanında kayıtlı benzersiz uygulama adlarını döndürür."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT app_name FROM captures WHERE app_name != '' ORDER BY app_name COLLATE NOCASE"
            ).fetchall()
            return [str(r["app_name"]) for r in rows]

    def delete_capture(self, capture_id: int) -> str | None:
        """Kaydı siler ve silinen kaydın image_path değerini döndürür."""
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

    def purge_older_than(self, days: int) -> list[str]:
        """Belirtilen günden eski kayıtları siler ve diskten silinecek image_path listesini döndürür."""
        if days <= 0:
            return []
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, image_path FROM captures WHERE timestamp < ?",
                (cutoff,),
            ).fetchall()
            if not rows:
                return []
            image_paths = [str(r["image_path"]) for r in rows]
            self._conn.execute("DELETE FROM captures WHERE timestamp < ?", (cutoff,))
            self._conn.commit()
            return image_paths

    def get_stats(self) -> dict[str, int]:
        """Toplam kayıt ve OCR tamamlanan kayıt sayısını döndürür."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(ocr_done), 0) AS ocr_done FROM captures"
            ).fetchone()
            return {
                "total": int(row["total"]),
                "ocr_done": int(row["ocr_done"]),
            }
