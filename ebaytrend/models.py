"""Модели данных, общие для всех бэкендов (HTML-скрейпер и Browse API)."""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Optional


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass
class Listing:
    """Одно объявление в момент наблюдения (снапшот)."""

    item_id: str
    title: str
    url: str = ""
    price: Optional[float] = None            # текущая цена / ставка, EUR
    currency: str = "EUR"
    shipping: Optional[float] = None         # стоимость доставки, EUR (0.0 = бесплатно)
    bids: Optional[int] = None               # число ставок на момент наблюдения
    is_auction: bool = True
    buy_it_now: bool = False
    seconds_left: Optional[int] = None       # до конца аукциона
    end_time: Optional[dt.datetime] = None   # если бэкенд отдаёт абсолютное время
    condition: str = ""
    location: str = ""
    seller: str = ""
    image: str = ""
    category_id: str = ""
    seed: str = ""                           # ключ ниши из config/seeds.yaml
    query: str = ""                          # поисковая фраза, по которой нашли
    observed_at: dt.datetime = field(default_factory=utcnow)
    sold: Optional[bool] = None              # для режима completed/sold
    raw_text: str = ""                       # исходный текст карточки (для отладки)

    # ---- производные величины -------------------------------------------------

    @property
    def total_price(self) -> Optional[float]:
        if self.price is None:
            return None
        return round(self.price + (self.shipping or 0.0), 2)

    @property
    def hours_left(self) -> Optional[float]:
        if self.seconds_left is None:
            return None
        return self.seconds_left / 3600.0

    def in_price_band(self, lo: float, hi: float) -> bool:
        p = self.price
        return p is not None and lo <= p <= hi

    def to_row(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["observed_at"] = self.observed_at.isoformat()
        d["end_time"] = self.end_time.isoformat() if self.end_time else None
        return d


@dataclass
class ItemDetails:
    """Данные, которые доступны только на карточке товара (опциональное обогащение)."""

    item_id: str
    watchers: Optional[int] = None
    start_time: Optional[dt.datetime] = None
    duration_days: Optional[int] = None
    category_path: str = ""
    seller_feedback: Optional[int] = None
    fetched_at: dt.datetime = field(default_factory=utcnow)
