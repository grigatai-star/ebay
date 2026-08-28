"""Хранилище снапшотов (SQLite).

Скорость ставок считается по разнице между наблюдениями, поэтому важно
хранить каждое наблюдение отдельной строкой, а не перезаписывать товар.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id      TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT,
    seed         TEXT,
    query        TEXT,
    condition    TEXT,
    location     TEXT,
    seller       TEXT,
    image        TEXT,
    category_id  TEXT,
    is_auction   INTEGER,
    buy_it_now   INTEGER,
    end_time     TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL,
    observed_at  TEXT NOT NULL,
    price        REAL,
    shipping     REAL,
    bids         INTEGER,
    seconds_left INTEGER,
    seed         TEXT,
    UNIQUE(item_id, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_obs_item ON observations(item_id, observed_at);

CREATE TABLE IF NOT EXISTS sold (
    item_id     TEXT PRIMARY KEY,
    title       TEXT,
    url         TEXT,
    seed        TEXT,
    query       TEXT,
    price       REAL,
    shipping    REAL,
    bids        INTEGER,
    condition   TEXT,
    was_sold    INTEGER,
    observed_at TEXT
);

CREATE TABLE IF NOT EXISTS scans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    seed          TEXT,
    query         TEXT,
    mode          TEXT,
    backend       TEXT,
    n_items       INTEGER,
    total_results INTEGER,
    blocked       INTEGER,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS item_details (
    item_id       TEXT PRIMARY KEY,
    watchers      INTEGER,
    start_time    TEXT,
    duration_days INTEGER,
    category_path TEXT,
    fetched_at    TEXT
);
"""


def _iso(value: Optional[dt.datetime]) -> Optional[str]:
    return value.isoformat() if value else None


class Store:
    def __init__(self, path: str | Path = "data/ebay.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- запись -------------------------------------------------------------

    def save_listings(self, listings: Iterable[Listing]) -> int:
        rows = 0
        cur = self.conn.cursor()
        for item in listings:
            observed = item.observed_at.isoformat()
            cur.execute(
                """
                INSERT INTO items (item_id, title, url, seed, query, condition, location,
                                   seller, image, category_id, is_auction, buy_it_now,
                                   end_time, first_seen, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(item_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    end_time  = COALESCE(excluded.end_time, items.end_time),
                    title     = excluded.title
                """,
                (
                    item.item_id, item.title, item.url, item.seed, item.query,
                    item.condition, item.location, item.seller, item.image,
                    item.category_id, int(item.is_auction), int(item.buy_it_now),
                    _iso(item.end_time), observed, observed,
                ),
            )
            cur.execute(
                """
                INSERT OR IGNORE INTO observations
                    (item_id, observed_at, price, shipping, bids, seconds_left, seed)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    item.item_id, observed, item.price, item.shipping,
                    item.bids, item.seconds_left, item.seed,
                ),
            )
            rows += 1
        self.conn.commit()
        return rows

    def save_sold(self, listings: Iterable[Listing]) -> int:
        rows = 0
        cur = self.conn.cursor()
        for item in listings:
            cur.execute(
                """
                INSERT INTO sold (item_id, title, url, seed, query, price, shipping,
                                  bids, condition, was_sold, observed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(item_id) DO UPDATE SET
                    price = excluded.price,
                    was_sold = excluded.was_sold,
                    observed_at = excluded.observed_at
                """,
                (
                    item.item_id, item.title, item.url, item.seed, item.query,
                    item.price, item.shipping, item.bids, item.condition,
                    None if item.sold is None else int(item.sold),
                    item.observed_at.isoformat(),
                ),
            )
            rows += 1
        self.conn.commit()
        return rows

    def log_scan(self, **kwargs: Any) -> None:
        self.conn.execute(
            """
            INSERT INTO scans (started_at, seed, query, mode, backend, n_items,
                               total_results, blocked, error)
            VALUES (:started_at, :seed, :query, :mode, :backend, :n_items,
                    :total_results, :blocked, :error)
            """,
            {
                "started_at": kwargs.get("started_at", dt.datetime.now(dt.timezone.utc).isoformat()),
                "seed": kwargs.get("seed", ""),
                "query": kwargs.get("query", ""),
                "mode": kwargs.get("mode", "auction"),
                "backend": kwargs.get("backend", "html"),
                "n_items": kwargs.get("n_items", 0),
                "total_results": kwargs.get("total_results"),
                "blocked": int(bool(kwargs.get("blocked"))),
                "error": kwargs.get("error", ""),
            },
        )
        self.conn.commit()

    def save_details(self, details: Iterable[Any]) -> int:
        rows = 0
        for d in details:
            self.conn.execute(
                """
                INSERT INTO item_details (item_id, watchers, start_time, duration_days,
                                          category_path, fetched_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(item_id) DO UPDATE SET
                    watchers = excluded.watchers,
                    start_time = COALESCE(excluded.start_time, item_details.start_time),
                    fetched_at = excluded.fetched_at
                """,
                (
                    d.item_id, d.watchers, _iso(d.start_time), d.duration_days,
                    d.category_path, d.fetched_at.isoformat(),
                ),
            )
            rows += 1
        self.conn.commit()
        return rows

    # ---- чтение -------------------------------------------------------------

    def items_with_observations(self, *, since_hours: Optional[float] = None) -> list[dict]:
        """Товары + все их наблюдения, отсортированные по времени."""
        params: list[Any] = []
        where = ""
        if since_hours:
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)
            where = "WHERE o.observed_at >= ?"
            params.append(cutoff.isoformat())
        rows = self.conn.execute(
            f"""
            SELECT i.*, o.observed_at AS obs_at, o.price AS obs_price,
                   o.bids AS obs_bids, o.seconds_left AS obs_left, o.shipping AS obs_ship
            FROM items i JOIN observations o ON o.item_id = i.item_id
            {where}
            ORDER BY i.item_id, o.observed_at
            """,
            params,
        ).fetchall()

        grouped: dict[str, dict] = {}
        for row in rows:
            entry = grouped.setdefault(
                row["item_id"],
                {
                    "item_id": row["item_id"], "title": row["title"], "url": row["url"],
                    "seed": row["seed"], "query": row["query"], "condition": row["condition"],
                    "location": row["location"], "end_time": row["end_time"],
                    "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                    "observations": [],
                },
            )
            entry["observations"].append(
                {
                    "observed_at": row["obs_at"], "price": row["obs_price"],
                    "bids": row["obs_bids"], "seconds_left": row["obs_left"],
                    "shipping": row["obs_ship"],
                }
            )
        return list(grouped.values())

    def sold_rows(self, *, seed: Optional[str] = None) -> list[dict]:
        query = "SELECT * FROM sold"
        params: list[Any] = []
        if seed:
            query += " WHERE seed = ?"
            params.append(seed)
        return [dict(r) for r in self.conn.execute(query, params).fetchall()]

    def details_map(self) -> dict[str, dict]:
        return {
            r["item_id"]: dict(r)
            for r in self.conn.execute("SELECT * FROM item_details").fetchall()
        }

    def stats(self) -> dict[str, int]:
        def count(table: str) -> int:
            return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        return {
            "items": count("items"),
            "observations": count("observations"),
            "sold": count("sold"),
            "scans": count("scans"),
        }

    def close(self) -> None:
        self.conn.close()
