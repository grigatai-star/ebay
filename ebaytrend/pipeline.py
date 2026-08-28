"""Оркестрация: скан ниш -> фильтры -> хранилище -> метрики -> кластеры."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import Seed
from .filters import Rules, apply as apply_filters
from .models import Listing
from .scoring import ClusterMetrics, aggregate_cluster, score_clusters
from .storage import Store
from .velocity import ItemMetrics, compute_all

log = logging.getLogger(__name__)


@dataclass
class ScanStats:
    queries: int = 0
    raw: int = 0
    kept: int = 0
    blocked: int = 0
    errors: list[str] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)

    def merge_rejected(self, other: dict[str, int]) -> None:
        for key, count in other.items():
            self.rejected[key] = self.rejected.get(key, 0) + count


def scan_seeds(
    backend,
    store: Store,
    seeds: list[Seed],
    rules: Rules,
    *,
    mode: str = "auction",       # auction | sold
    pages: Optional[int] = None,
    dry_run: bool = False,
) -> ScanStats:
    """Проходит по нишам и запросам, сохраняет наблюдения."""
    stats = ScanStats()
    sold_mode = mode == "sold"

    for seed in seeds:
        for query in seed.queries:
            stats.queries += 1
            log.info("[%s] %s", seed.key, query)
            result = backend.search(
                query,
                seed=seed.key,
                price_min=seed.price_min,
                price_max=seed.price_max,
                pages=pages or seed.pages,
                sold=sold_mode,
                category_id=seed.category_id,
                exclude_words=seed.exclude_words,
            )
            stats.raw += len(result.listings)
            if result.blocked:
                stats.blocked += 1
            if result.error:
                stats.errors.append(f"{seed.key}/{query}: {result.error}")

            # в режиме sold не режем по «аукцион/не аукцион»: там всё завершено
            seed_rules = Rules(**{**rules.__dict__})
            seed_rules.price_min = seed.price_min
            seed_rules.price_max = seed.price_max
            if sold_mode:
                seed_rules.require_auction = False

            kept, rejected = apply_filters(result.listings, seed_rules)
            stats.kept += len(kept)
            stats.merge_rejected(rejected)

            if not dry_run and kept:
                if sold_mode:
                    store.save_sold(kept)
                else:
                    store.save_listings(kept)
            if not dry_run:
                store.log_scan(
                    seed=seed.key, query=query, mode=mode, backend=backend.name,
                    n_items=len(kept), total_results=result.total_results,
                    blocked=result.blocked, error=result.error,
                )
            log.info(
                "    найдено %d, после фильтров %d%s",
                len(result.listings), len(kept),
                " [БЛОКИРОВКА]" if result.blocked else "",
            )
    return stats


def build_clusters(
    store: Store,
    seeds: list[Seed],
    *,
    since_hours: Optional[float] = None,
    min_hours_left: Optional[float] = None,
    max_hours_left: Optional[float] = None,
) -> tuple[list[ClusterMetrics], list[ItemMetrics]]:
    """Считает метрики по лотам и агрегаты по нишам."""
    records = store.items_with_observations(since_hours=since_hours)
    items = compute_all(records)

    if min_hours_left is not None:
        items = [i for i in items if (i.hours_left or 0) >= min_hours_left]
    if max_hours_left is not None:
        items = [i for i in items if i.hours_left is not None and i.hours_left <= max_hours_left]

    by_seed: dict[str, list[ItemMetrics]] = {}
    for item in items:
        by_seed.setdefault(item.seed, []).append(item)

    totals = {
        row["seed"]: row["total"]
        for row in store.conn.execute(
            "SELECT seed, MAX(total_results) AS total FROM scans "
            "WHERE mode='auction' GROUP BY seed"
        ).fetchall()
    }
    sold_by_seed: dict[str, list[dict]] = {}
    for row in store.sold_rows():
        sold_by_seed.setdefault(row["seed"], []).append(row)

    clusters: list[ClusterMetrics] = []
    seed_map = {s.key: s for s in seeds}
    for key in set(by_seed) | set(sold_by_seed):
        seed = seed_map.get(key)
        clusters.append(
            aggregate_cluster(
                key,
                by_seed.get(key, []),
                label=seed.label if seed else key,
                tags=seed.tags if seed else [],
                note=seed.note if seed else "",
                buy_ratio=seed.buy_ratio if seed else 0.40,
                total_results=totals.get(key),
                sold_rows=sold_by_seed.get(key),
            )
        )
    return score_clusters(clusters), items
