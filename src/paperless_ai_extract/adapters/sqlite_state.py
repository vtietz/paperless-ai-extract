"""Local SQLite state: extraction cache, run history/retries, open proposals.

Losing this file is safe: documents are re-analysed (cost) and treated as
first runs (fill empty fields only). It is not a source of truth.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS extractions (
  doc_id INTEGER NOT NULL, source_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
  created_at REAL NOT NULL, result TEXT NOT NULL, metrics TEXT NOT NULL,
  PRIMARY KEY (doc_id, source_key, fingerprint));
CREATE TABLE IF NOT EXISTS runs (
  doc_id INTEGER PRIMARY KEY, first_success_at REAL, last_success_at REAL,
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, next_attempt_at REAL);
CREATE TABLE IF NOT EXISTS proposals (
  doc_id INTEGER PRIMARY KEY, created_at REAL NOT NULL, changes TEXT NOT NULL);
"""


class SqliteStateStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.commit()

    # extraction cache
    def cached(self, doc_id: int, source_key: str, fingerprint: str) -> dict | None:
        row = self.db.execute(
            "SELECT result FROM extractions WHERE doc_id=? AND source_key=? AND fingerprint=?",
            (doc_id, source_key, fingerprint)).fetchone()
        return json.loads(row[0]) if row else None

    def store(self, doc_id: int, source_key: str, fingerprint: str, result: dict, metrics: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?)",
                            (doc_id, source_key, fingerprint, time.time(),
                             json.dumps(result), json.dumps(metrics)))

    # runs
    def has_succeeded(self, doc_id: int) -> bool:
        row = self.db.execute("SELECT first_success_at FROM runs WHERE doc_id=?", (doc_id,)).fetchone()
        return bool(row and row[0])

    def retry_due(self, doc_id: int, now: float | None = None) -> bool:
        row = self.db.execute("SELECT next_attempt_at FROM runs WHERE doc_id=?", (doc_id,)).fetchone()
        return not row or not row[0] or row[0] <= (now or time.time())

    def success(self, doc_id: int):
        now = time.time()
        with self.db:
            self.db.execute(
                "INSERT INTO runs (doc_id, first_success_at, last_success_at, attempts) VALUES (?,?,?,0) "
                "ON CONFLICT(doc_id) DO UPDATE SET last_success_at=excluded.last_success_at, "
                "first_success_at=COALESCE(runs.first_success_at, excluded.first_success_at), "
                "attempts=0, last_error=NULL, next_attempt_at=NULL", (doc_id, now, now))

    def failure(self, doc_id: int, error: str, retry_delay: float) -> int:
        with self.db:
            self.db.execute(
                "INSERT INTO runs (doc_id, attempts, last_error) VALUES (?,1,?) "
                "ON CONFLICT(doc_id) DO UPDATE SET attempts=runs.attempts+1, last_error=excluded.last_error",
                (doc_id, error[:500]))
            attempts = self.db.execute("SELECT attempts FROM runs WHERE doc_id=?", (doc_id,)).fetchone()[0]
            self.db.execute("UPDATE runs SET next_attempt_at=? WHERE doc_id=?",
                            (time.time() + retry_delay * attempts, doc_id))
        return attempts

    def reset_attempts(self, doc_id: int):
        with self.db:
            self.db.execute("UPDATE runs SET attempts=0, next_attempt_at=NULL WHERE doc_id=?", (doc_id,))

    # proposals
    def save_proposal(self, doc_id: int, changes: list[dict]):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO proposals VALUES (?,?,?)",
                            (doc_id, time.time(), json.dumps(changes)))

    def proposal(self, doc_id: int) -> list[dict] | None:
        row = self.db.execute("SELECT changes FROM proposals WHERE doc_id=?", (doc_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def drop_proposal(self, doc_id: int):
        with self.db:
            self.db.execute("DELETE FROM proposals WHERE doc_id=?", (doc_id,))
