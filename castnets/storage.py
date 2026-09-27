import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import DomainError


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS podcasts (id TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS content (id TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS branches (id TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def table(name):
        if name not in {"podcasts", "episodes", "content", "branches"}:
            raise ValueError("Invalid table")
        return name

    def put(self, table, key, value, db=None):
        if db is None:
            with self.connection() as connection:
                return self.put(table, key, value, connection)
        db.execute(f"INSERT INTO {self.table(table)} VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def get(self, table, key, db=None):
        if db is None:
            with self.connection() as connection:
                return self.get(table, key, connection)
        row = db.execute(f"SELECT value FROM {self.table(table)} WHERE id=?", (key,)).fetchone()
        if row is None:
            raise DomainError(f"{table} record not found: {key}", "not_found", 404)
        return json.loads(row[0])

    def all(self, table):
        with self.connection() as db:
            rows = db.execute(f"SELECT value FROM {self.table(table)} ORDER BY rowid").fetchall()
        return [json.loads(row[0]) for row in rows]
