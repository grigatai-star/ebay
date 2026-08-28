"""Отсев мусора и перегретых/мошеннических ниш.

Логика ровно та, что нужна для перепродажи на Kleinanzeigen/Vinted:
покупателю должно быть *не страшно* платить. Ниши, где рынок забит скамом
(смартфоны, GPS-часы, AirPods, кроссовки-реплики), режем целиком — там любой
продавец без истории вызывает подозрение, и товар зависает.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .models import Listing

# Ниши, где на Kleinanzeigen продавца по умолчанию считают мошенником.
SATURATED_BRANDS = [
    "iphone", "ipad", "macbook", "airpods", "apple watch", "airtag",
    "samsung galaxy", "galaxy s2", "galaxy s1", "xiaomi", "huawei p", "pixel 7", "pixel 8",
    "garmin", "fenix 7", "fenix 8", "forerunner", "epix",
    "playstation 5", "ps5", "xbox series", "nintendo switch",
    "gopro", "dji", "mavic", "osmo",
    "rolex", "omega speedmaster", "breitling", "cartier",
    "louis vuitton", "gucci", "prada", "balenciaga", "moncler", "canada goose",
    "jordan 1", "yeezy", "dunk low", "air max", "nike tn",
    "thermomix", "tm6", "tm5",
    "e-bike akku", "ebike akku", "bosch powertube", "powerpack",
    "gutschein", "guthaben", "steam key", "psn card",
]

# Слова, после которых лот бесполезен как товар для перепродажи.
JUNK_KEYWORDS = [
    "defekt", "bastler", "ersatzteil", "ersatzteilspender", "nicht funktionsfähig",
    "kaputt", "beschädigt", "reparatur", "for parts",
    "replica", "replika", "fake", "nachbau", "nachbildung", "china",
    "leer", "leerkarton", "nur karton", "nur verpackung", "ohne inhalt",
    "prospekt", "katalog", "anleitung", "bedienungsanleitung", "handbuch",
    "aufkleber", "sticker", "poster", "werbung", "reklame",
    "konvolut", "restposten", "posten ", "sammlung auflösung",
    "hülle", "tasche für", "schutzfolie", "displayschutz", "adapter für",
    "abholung nur", "nur abholung",
]

# Крупногабарит: продать можно, но только локально — помечаем, не режем.
BULKY_KEYWORDS = [
    "sofa", "couch", "schrank", "kommode", "sessel", "esstisch", "bett",
    "waschmaschine", "trockner", "kühlschrank", "spülmaschine", "klavier",
    "e-piano", "kaminofen", "hebebühne", "anhänger", "rudergerät", "laufband",
    "crosstrainer", "kraftstation", "dachbox", "winterreifen", "alufelgen",
]


@dataclass
class Rules:
    price_min: float = 80.0
    price_max: float = 500.0
    saturated: list[str] = field(default_factory=lambda: list(SATURATED_BRANDS))
    junk: list[str] = field(default_factory=lambda: list(JUNK_KEYWORDS))
    bulky: list[str] = field(default_factory=lambda: list(BULKY_KEYWORDS))
    allow_defect: bool = False
    require_auction: bool = True
    min_title_len: int = 12

    @classmethod
    def from_config(cls, data: Optional[dict]) -> "Rules":
        data = data or {}
        rules = cls()
        rules.price_min = float(data.get("price_min", rules.price_min))
        rules.price_max = float(data.get("price_max", rules.price_max))
        if data.get("saturated_brands"):
            rules.saturated = [str(x).lower() for x in data["saturated_brands"]]
        if data.get("extra_saturated_brands"):
            rules.saturated += [str(x).lower() for x in data["extra_saturated_brands"]]
        if data.get("junk_keywords"):
            rules.junk = [str(x).lower() for x in data["junk_keywords"]]
        if data.get("extra_junk_keywords"):
            rules.junk += [str(x).lower() for x in data["extra_junk_keywords"]]
        if data.get("bulky_keywords"):
            rules.bulky = [str(x).lower() for x in data["bulky_keywords"]]
        rules.allow_defect = bool(data.get("allow_defect", rules.allow_defect))
        return rules


def _hit(text: str, needles: Iterable[str]) -> Optional[str]:
    for needle in needles:
        if needle in text:
            return needle
    return None


def is_bulky(title: str, rules: Optional[Rules] = None) -> bool:
    rules = rules or Rules()
    return _hit((title or "").lower(), rules.bulky) is not None


def reject_reason(listing: Listing, rules: Rules) -> Optional[str]:
    """None — лот проходит. Иначе строка с причиной отсева."""
    title = (listing.title or "").lower()

    if len(title) < rules.min_title_len:
        return "слишком короткий заголовок (мусорная карточка)"
    if rules.require_auction and not listing.is_auction:
        return "не аукцион"
    if listing.price is None:
        return "не удалось разобрать цену"
    if not (rules.price_min <= listing.price <= rules.price_max):
        return f"цена вне диапазона {rules.price_min:g}-{rules.price_max:g} EUR"

    hit = _hit(title, rules.saturated)
    if hit:
        return f"перегретая/скам-ниша: {hit}"

    hit = _hit(title, rules.junk)
    if hit and not (rules.allow_defect and hit in {"defekt", "bastler", "ersatzteil"}):
        return f"мусорное слово: {hit}"

    if not rules.allow_defect and listing.condition == "defekt":
        return "состояние: дефект"
    return None


def apply(listings: Iterable[Listing], rules: Rules) -> tuple[list[Listing], dict[str, int]]:
    """Возвращает (прошедшие, счётчик причин отсева)."""
    kept: list[Listing] = []
    rejected: dict[str, int] = {}
    for item in listings:
        reason = reject_reason(item, rules)
        if reason is None:
            kept.append(item)
        else:
            key = reason.split(":")[0]
            rejected[key] = rejected.get(key, 0) + 1
    return kept, rejected
