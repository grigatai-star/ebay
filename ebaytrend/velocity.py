"""Расчёт скорости ставок.

Две метрики:

1. delta — честная: (ставки_сейчас − ставки_раньше) / часы между наблюдениями.
   Нужны минимум два скана одного лота, поэтому `watch` полезнее одиночного `scan`.

2. est — оценочная, из одного скана: ставки / прошедшие_часы, где прошедшее время
   восстанавливается из остатка времени и стандартной длительности аукциона eBay
   (1/3/5/7/10 дней). Это верхняя граница скорости, годится для первого прохода.

Важно: на eBay ставки идут волной в последний час (снайпинг). Поэтому лот с
"20 ставок/час" за 10 минут до конца — это норма, а не сигнал. Сравнивать
имеет смысл лоты в похожей фазе: см. поле `phase` и фильтр --min-hours-left.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

STANDARD_DURATIONS_H = [24, 72, 120, 168, 240]  # 1, 3, 5, 7, 10 дней
MIN_GAP_HOURS = 0.3      # минимальный интервал между наблюдениями (18 минут)
MIN_ELAPSED_HOURS = 0.5


def _parse(ts: str | dt.datetime | None) -> Optional[dt.datetime]:
    if ts is None or isinstance(ts, dt.datetime):
        return ts
    try:
        return dt.datetime.fromisoformat(ts)
    except ValueError:
        return None


def estimate_elapsed_hours(hours_left: Optional[float]) -> Optional[float]:
    """Сколько аукцион уже идёт, исходя из остатка и стандартных длительностей."""
    if hours_left is None or hours_left < 0:
        return None
    for duration in STANDARD_DURATIONS_H:
        if hours_left <= duration - 0.01:
            return max(MIN_ELAPSED_HOURS, duration - hours_left)
    return max(MIN_ELAPSED_HOURS, STANDARD_DURATIONS_H[-1] - hours_left)


@dataclass
class ItemMetrics:
    item_id: str
    title: str = ""
    url: str = ""
    seed: str = ""
    query: str = ""
    condition: str = ""
    price: Optional[float] = None
    price_start: Optional[float] = None
    bids: Optional[int] = None
    hours_left: Optional[float] = None
    elapsed_hours: Optional[float] = None
    phase: Optional[float] = None            # доля пройденного аукциона, 0..1
    observations: int = 0
    span_hours: float = 0.0                  # длина окна наблюдений
    bids_delta: Optional[int] = None
    bids_per_hour_delta: Optional[float] = None
    bids_per_hour_est: Optional[float] = None
    price_per_hour_delta: Optional[float] = None
    price_growth: Optional[float] = None      # прирост цены за окно наблюдений, EUR

    @property
    def bids_per_hour(self) -> Optional[float]:
        """Лучшая доступная оценка: delta, если есть, иначе est."""
        if self.bids_per_hour_delta is not None:
            return self.bids_per_hour_delta
        return self.bids_per_hour_est

    @property
    def method(self) -> str:
        return "delta" if self.bids_per_hour_delta is not None else "est"


def compute_item_metrics(record: dict, *, min_gap_hours: float = MIN_GAP_HOURS) -> ItemMetrics:
    """record — элемент из Store.items_with_observations()."""
    obs = sorted(
        (o for o in record.get("observations", []) if o.get("observed_at")),
        key=lambda o: o["observed_at"],
    )
    metrics = ItemMetrics(
        item_id=record["item_id"],
        title=record.get("title", ""),
        url=record.get("url", ""),
        seed=record.get("seed", ""),
        query=record.get("query", ""),
        condition=record.get("condition", ""),
        observations=len(obs),
    )
    if not obs:
        return metrics

    last, first = obs[-1], obs[0]
    metrics.price = last.get("price")
    metrics.price_start = first.get("price")
    metrics.bids = last.get("bids")
    if last.get("seconds_left") is not None:
        metrics.hours_left = round(last["seconds_left"] / 3600.0, 3)

    metrics.elapsed_hours = estimate_elapsed_hours(metrics.hours_left)
    if metrics.elapsed_hours and metrics.hours_left is not None:
        total = metrics.elapsed_hours + metrics.hours_left
        metrics.phase = round(metrics.elapsed_hours / total, 3) if total else None

    if metrics.bids is not None and metrics.elapsed_hours:
        metrics.bids_per_hour_est = round(metrics.bids / metrics.elapsed_hours, 3)

    # --- дельта между первым и последним наблюдением --------------------------
    t_first, t_last = _parse(first["observed_at"]), _parse(last["observed_at"])
    if t_first and t_last:
        span = (t_last - t_first).total_seconds() / 3600.0
        metrics.span_hours = round(span, 3)
        if span >= min_gap_hours:
            if first.get("bids") is not None and last.get("bids") is not None:
                delta = last["bids"] - first["bids"]
                if delta >= 0:
                    metrics.bids_delta = delta
                    metrics.bids_per_hour_delta = round(delta / span, 3)
            if first.get("price") is not None and last.get("price") is not None:
                growth = last["price"] - first["price"]
                if growth >= 0:
                    metrics.price_growth = round(growth, 2)
                    metrics.price_per_hour_delta = round(growth / span, 3)
    return metrics


def compute_all(records: list[dict], **kwargs) -> list[ItemMetrics]:
    return [compute_item_metrics(r, **kwargs) for r in records]
