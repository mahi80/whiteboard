"""Board storage: Postgres if DATABASE_URL is set, otherwise a local SQLite file."""
import json
import os
import sqlite3
import threading
import time

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


class Storage:
    def __init__(self):
        self.pg = DATABASE_URL.startswith(("postgres://", "postgresql://"))
        self.lock = threading.Lock()
        if self.pg:
            import psycopg

            self.conn = psycopg.connect(DATABASE_URL, autocommit=True)
            self._exec(
                "CREATE TABLE IF NOT EXISTS boards ("
                "id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL)"
            )
        else:
            path = os.getenv("SQLITE_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "boards.db"))
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self._exec(
                "CREATE TABLE IF NOT EXISTS boards ("
                "id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL)"
            )

    @property
    def kind(self):
        return "postgres" if self.pg else "sqlite"

    def _exec(self, sql, params=()):
        if self.pg:
            sql = sql.replace("?", "%s")
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else None
            if not self.pg:
                self.conn.commit()
            return rows

    def _reconnect_pg(self):
        import psycopg

        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = psycopg.connect(DATABASE_URL, autocommit=True)

    def _safe(self, fn, *a):
        try:
            return fn(*a)
        except Exception:
            if not self.pg:
                raise
            self._reconnect_pg()  # free Postgres tiers drop idle connections
            return fn(*a)

    def load(self, board_id):
        rows = self._safe(self._exec, "SELECT data FROM boards WHERE id = ?", (board_id,))
        if not rows:
            return {"elements": {}, "files": {}}
        return json.loads(rows[0][0])

    def save(self, board_id, data):
        payload = json.dumps(data, separators=(",", ":"))
        self._safe(
            self._exec,
            "INSERT INTO boards (id, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (board_id, payload, time.time()),
        )
