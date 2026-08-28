"""Агрегация по нишам и итоговый скор спроса.

Метрики намеренно разные по природе, поэтому сводим их не через сырые
значения, а через перцентильные ранги внутри выборки ниш: это устойчиво
к выбросам и к тому, что «ставок в час» и «доля проданных» живут в разных
шкалах.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from .velocity import ItemMetrics

LATE_PHASE_HOURS = 24.0     # «поздняя» фаза аукциона: меньше суток до конца


def _median(values: Sequence[float]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return round(statistics.median(clean), 2) if clean else None


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return round(clean[0], 3)
    pos = q * (len(clean) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(clean) - 1)
    frac = pos - lo
    return round(clean[lo] * (1 - frac) + clean[hi] * frac, 3)


def percentile_ranks(values: Sequence[Optional[float]]) -> list[float]:
    """Ранг каждого значения в [0,1]. None -> 0.5 (нейтрально)."""
    known = sorted(v for v in values if v is not None)
    if not known:
        return [0.5] * len(values)
    if len(known) == 1:
        return [0.5 if v is None else 1.0 for v in values]
    ranks: list[float] = []
    for v in values:
        if v is None:
            ranks.append(0.5)
            continue
        below = sum(1 for k in known if k < v)
        equal = sum(1 for k in known if k == v)
        ranks.append(round((below + 0.5 * equal) / len(known), 4))
    return ranks


@dataclass
class ClusterMetrics:
    key: str
    label: str = ""
    tags: list[str] = field(default_factory=list)
    note: str = ""
    buy_ratio: float = 0.40

    n_items: int = 0
    n_late: int = 0                          # лотов в поздней фазе (<24ч до конца)
    n_with_bids: int = 0
    bid_rate_late: Optional[float] = None    # доля лотов со ставками в поздней фазе
    median_price: Optional[float] = None
    median_bids_late: Optional[float] = None
    bids_per_hour_p75: Optional[float] = None
    price_growth_median: Optional[float] = None
    total_results: Optional[int] = None      # объём ниши по данным eBay

    n_completed: int = 0
    n_sold: int = 0
    sell_through: Optional[float] = None     # доля проданных среди завершённых
    median_sold_price: Optional[float] = None

    demand_score: float = 0.0
    top_items: list[ItemMetrics] = field(default_factory=list)

    @property
    def target_buy_price(self) -> Optional[float]:
        """Потолок закупки в ломбарде, чтобы осталась маржа."""
        base = self.median_sold_price or self.median_price
        return round(base * self.buy_ratio, 2) if base else None

    @property
    def bulky(self) -> bool:
        return "bulky" in self.tags


def aggregate_cluster(
    key: str,
    items: list[ItemMetrics],
    *,
    label: str = "",
    tags: Optional[list[str]] = None,
    note: str = "",
    buy_ratio: float = 0.40,
    total_results: Optional[int] = None,
    sold_rows: Optional[list[dict]] = None,
) -> ClusterMetrics:
    cluster = ClusterMetrics(
        key=key, label=label or key, tags=list(tags or []), note=note,
        buy_ratio=buy_ratio, total_results=total_results, n_items=len(items),
    )
    if items:
        cluster.median_price = _median([i.price for i in items])
        cluster.price_growth_median = _median(
            [i.price_growth for i in items if i.price_growth is not None]
        )
        cluster.bids_per_hour_p75 = _quantile(
            [i.bids_per_hour for i in items if i.bids_per_hour is not None], 0.75
        )
        late = [
            i for i in items
            if i.hours_left is not None and i.hours_left <= LATE_PHASE_HOURS
        ]
        cluster.n_late = len(late)
        if late:
            with_bids = [i for i in late if (i.bids or 0) > 0]
            cluster.n_with_bids = len(with_bids)
            cluster.bid_rate_late = round(len(with_bids) / len(late), 3)
            cluster.median_bids_late = _median([i.bids for i in late])
        else:
            cluster.n_with_bids = sum(1 for i in items if (i.bids or 0) > 0)

        cluster.top_items = sorted(
            items,
            key=lambda i: (i.bids_per_hour or 0, i.bids or 0),
            reverse=True,
        )[:5]

    if sold_rows:
        cluster.n_completed = len(sold_rows)
        sold = [r for r in sold_rows if r.get("was_sold")]
        cluster.n_sold = len(sold)
        if cluster.n_completed:
            cluster.sell_through = round(cluster.n_sold / cluster.n_completed, 3)
        cluster.median_sold_price = _median([r.get("price") for r in sold])
    return cluster


def score_clusters(clusters: list[ClusterMetrics]) -> list[ClusterMetrics]:
    """Проставляет demand_score (0-100) и возвращает список, отсортированный по нему."""
    if not clusters:
        return []

    ranks = {
        "bid_rate": percentile_ranks([c.bid_rate_late for c in clusters]),
        "bids": percentile_ranks([c.median_bids_late for c in clusters]),
        "velocity": percentile_ranks([c.bids_per_hour_p75 for c in clusters]),
        "sell_through": percentile_ranks([c.sell_through for c in clusters]),
        "volume": percentile_ranks(
            [float(c.total_results) if c.total_results else float(c.n_items) for c in clusters]
        ),
    }
    have_sell_through = any(c.sell_through is not None for c in clusters)
    weights = (
        {"bid_rate": 0.28, "bids": 0.17, "velocity": 0.20, "sell_through": 0.25, "volume": 0.10}
        if have_sell_through
        else {"bid_rate": 0.38, "bids": 0.22, "velocity": 0.27, "sell_through": 0.0, "volume": 0.13}
    )

    for idx, cluster in enumerate(clusters):
        score = sum(weights[name] * ranks[name][idx] for name in weights)
        # штраф за крупногабарит: продать можно только локально
        if cluster.bulky:
            score *= 0.92
        # штраф за пустую выборку — не доверяем нишам с парой лотов
        if cluster.n_items < 5:
            score *= 0.75
        cluster.demand_score = round(100 * score, 1)

    return sorted(clusters, key=lambda c: c.demand_score, reverse=True)


def item_heat(item: ItemMetrics) -> float:
    """Скор отдельного лота: ставки в час с поправкой на фазу аукциона.

    Лот за 10 минут до конца почти всегда «горячий» — это снайпинг, а не спрос.
    Поэтому ранние ставки весят больше поздних.
    """
    bph = item.bids_per_hour or 0.0
    if item.hours_left is None:
        phase_factor = 0.8
    elif item.hours_left < 1:
        phase_factor = 0.35
    elif item.hours_left < 6:
        phase_factor = 0.6
    elif item.hours_left < 24:
        phase_factor = 0.9
    else:
        phase_factor = 1.0
    confidence = 1.0 if item.method == "delta" else 0.7
    return round(bph * phase_factor * confidence, 3)
