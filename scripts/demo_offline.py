#!/usr/bin/env python3
"""Демка без сети: наполняет БД синтетическими наблюдениями и печатает отчёт.

Нужна, чтобы посмотреть формат вывода и проверить сборку до первого
реального скана:  python3 scripts/demo_offline.py
"""

from __future__ import annotations

import datetime as dt
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebaytrend.config import load_seeds, season_window, select_seeds  # noqa: E402
from ebaytrend.models import Listing  # noqa: E402
from ebaytrend.pipeline import build_clusters  # noqa: E402
from ebaytrend.report import render_clusters, render_items  # noqa: E402
from ebaytrend.storage import Store  # noqa: E402

# «Температура» ниши в демо-данных: (шанс ставок, ставок в час, цена)
PROFILE = {
    "profi_akkuwerkzeug": (0.85, 1.6, 180),
    "kaffeevollautomat": (0.78, 1.3, 260),
    "ferngläser_optik": (0.72, 1.1, 380),
    "naehmaschinen": (0.70, 0.9, 210),
    "outdoor_bekleidung": (0.66, 0.8, 130),
    "heizen_entfeuchten": (0.62, 0.7, 150),
    "auto_winter": (0.58, 0.6, 300),
    "design_moebel": (0.35, 0.3, 320),
}
DEFAULT_PROFILE = (0.45, 0.4, 200)


def main() -> int:
    random.seed(42)
    seeds = load_seeds()
    selected = select_seeds(seeds, season_month=season_window())
    db_path = Path(tempfile.mkdtemp()) / "demo.sqlite3"
    store = Store(db_path)

    now = dt.datetime.now(dt.timezone.utc)
    for seed in selected:
        bid_chance, rate, base_price = PROFILE.get(seed.key, DEFAULT_PROFILE)
        for n in range(random.randint(12, 26)):
            hours_left = random.choice([0.4, 2, 5, 11, 20, 30, 60, 120])
            has_bids = random.random() < bid_chance
            bids_first = int(rate * random.uniform(2, 14)) if has_bids else 0
            price_first = round(base_price * random.uniform(0.55, 1.25), 2)
            item_id = f"{abs(hash((seed.key, n))) % 10**12:012d}"
            gained = int(rate * random.uniform(0.5, 2.5)) if has_bids else 0

            for offset, bids, price in (
                (dt.timedelta(hours=-2), bids_first, price_first),
                (dt.timedelta(0), bids_first + gained, round(price_first * (1 + 0.04 * gained), 2)),
            ):
                store.save_listings([
                    Listing(
                        item_id=item_id,
                        title=f"{seed.label.split(' (')[0]} — демо-лот {n}",
                        url=f"https://www.ebay.de/itm/{item_id}",
                        price=price,
                        bids=bids,
                        seconds_left=int((hours_left * 3600) - offset.total_seconds()),
                        seed=seed.key,
                        query=seed.queries[0],
                        condition="gebraucht",
                        observed_at=now + offset,
                    )
                ])
        store.log_scan(seed=seed.key, query=seed.queries[0], mode="auction",
                       n_items=20, total_results=random.randint(200, 6000))

    clusters, items = build_clusters(store, seeds)
    print("\nНИШИ ПО СПРОСУ (синтетические данные!)\n")
    print(render_clusters(clusters, limit=20))
    print("\nГОРЯЧИЕ ЛОТЫ\n")
    print(render_items(items, limit=12))
    print(f"\nДемо-БД: {db_path}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
