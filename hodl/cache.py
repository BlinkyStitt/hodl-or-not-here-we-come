"""SQLite evidence cache. Immutable block hashes form part of every state key."""

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any

from hodl.model import Unavailable


class Cache:
    def __init__(self, path: Path, *, offline: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = RLock()
        self.offline = offline
        self.hits = 0
        self.misses = 0
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS evidence (
            key TEXT PRIMARY KEY, namespace TEXT NOT NULL, request TEXT NOT NULL,
            source TEXT NOT NULL, block_hash TEXT, payload TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        )""")

    def get(
        self,
        namespace: str,
        request: Any,
        source: str,
        fetch: Callable[[], Any],
        *,
        block_hash: str | None = None,
    ) -> Any:
        request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256(
            json.dumps([namespace, request_json, source, block_hash]).encode()
        ).hexdigest()
        with self.lock:
            row = self.db.execute(
                "SELECT payload FROM evidence WHERE key=?", (key,)
            ).fetchone()
        if row:
            self.hits += 1
            return json.loads(row[0])
        self.misses += 1
        if self.offline:
            raise Unavailable(f"cache miss: {namespace} {request_json}")
        payload = fetch()
        with self.lock:
            self.db.execute(
                "INSERT OR IGNORE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    namespace,
                    request_json,
                    source,
                    block_hash,
                    json.dumps(payload, sort_keys=True),
                    int(time.time()),
                ),
            )
            self.db.commit()
        return payload

    def close(self) -> None:
        self.db.close()
