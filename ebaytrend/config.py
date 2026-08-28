"""Загрузка конфигов: ниши (seeds.yaml) и правила отсева (exclude.yaml)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .filters import Rules

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@dataclass
class Seed:
    key: str
    label: str = ""
    queries: list[str] = field(default_factory=list)
    season: list[int] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    price_min: float = 80.0
    price_max: float = 500.0
    pages: int = 1
    buy_ratio: float = 0.40
    exclude_words: list[str] = field(default_factory=list)
    category_id: Optional[str] = None
    note: str = ""

    def in_season(self, month: int) -> bool:
        return not self.season or month in self.season

    @property
    def bulky(self) -> bool:
        return "bulky" in self.tags


def load_seeds(path: str | Path | None = None) -> list[Seed]:
    path = Path(path) if path else CONFIG_DIR / "seeds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults: dict[str, Any] = data.get("defaults") or {}
    seeds: list[Seed] = []
    for raw in data.get("seeds") or []:
        seeds.append(
            Seed(
                key=raw["key"],
                label=raw.get("label", raw["key"]),
                queries=list(raw.get("queries") or []),
                season=[int(m) for m in (raw.get("season") or [])],
                tags=list(raw.get("tags") or []),
                price_min=float(raw.get("price_min", defaults.get("price_min", 80))),
                price_max=float(raw.get("price_max", defaults.get("price_max", 500))),
                pages=int(raw.get("pages", defaults.get("pages", 1))),
                buy_ratio=float(raw.get("buy_ratio", defaults.get("buy_ratio", 0.40))),
                exclude_words=list(
                    raw.get("exclude_words") or defaults.get("exclude_words") or []
                ),
                category_id=raw.get("category_id"),
                note=raw.get("note", ""),
            )
        )
    return seeds


def load_rules(path: str | Path | None = None) -> Rules:
    path = Path(path) if path else CONFIG_DIR / "exclude.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return Rules.from_config(data)


def season_window(month: Optional[int] = None, lookahead: int = 1) -> list[int]:
    """Текущий месяц + `lookahead` вперёд.

    Закупка идёт с опережением: то, что берёшь в конце августа, продаётся
    в сентябре-октябре. Поэтому по умолчанию сезон = месяц + 1.
    """
    month = month or current_month()
    return [((month - 1 + offset) % 12) + 1 for offset in range(lookahead + 1)]


def select_seeds(
    seeds: list[Seed],
    *,
    keys: Optional[list[str]] = None,
    season_month: int | list[int] | None = None,
    tags: Optional[list[str]] = None,
    skip_bulky: bool = False,
) -> list[Seed]:
    """Отбор ниш: по ключам, по сезону (месяц или список месяцев), по тегам."""
    selected = seeds
    if keys:
        wanted = {k.lower() for k in keys}
        selected = [s for s in selected if s.key.lower() in wanted]
    if season_month:
        months = [season_month] if isinstance(season_month, int) else list(season_month)
        selected = [s for s in selected if any(s.in_season(m) for m in months)]
    if tags:
        wanted_tags = {t.lower() for t in tags}
        selected = [s for s in selected if wanted_tags & {t.lower() for t in s.tags}]
    if skip_bulky:
        selected = [s for s in selected if not s.bulky]
    return selected


def current_month() -> int:
    return dt.date.today().month
