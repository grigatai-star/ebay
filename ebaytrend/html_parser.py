"""Разбор страницы результатов поиска ebay.de.

Стратегия устойчивости к редизайну:
  1. находим все ссылки вида /itm/<id>;
  2. поднимаемся к ближайшему контейнеру карточки (li / div[data-testid] / ...);
  3. вытаскиваем поля регулярками по тексту карточки, а не по CSS-классам.

Так парсер переживает переименование классов (s-item -> s-card -> ...),
которое eBay делает регулярно.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup, Tag

from .models import Listing, utcnow
from .textutils import (
    looks_sold,
    normalize_ws,
    parse_bids,
    parse_condition,
    parse_item_id,
    parse_price,
    parse_shipping,
    parse_time_left,
)

# карточки, которые eBay подмешивает как рекламу/похожие товары
_PROMO_MARKERS = re.compile(
    r"(anzeige\b|gesponsert|sponsored|shop on ebay|ergebnisse für weniger suchbegriffe|"
    r"results matching fewer words|ähnliche artikel|similar sponsored)",
    re.IGNORECASE,
)
_BIN_MARKERS = re.compile(r"(sofort[- ]?kaufen|buy it now|preisvorschlag|best offer)", re.IGNORECASE)
_CARD_TAGS = {"li", "article"}
_RESULT_COUNT_RE = re.compile(r"([\d.,\s ']+)\s*(?:Ergebnisse|results|Artikel gefunden)", re.IGNORECASE)


def _nearest_card(node: Tag) -> Optional[Tag]:
    """Ближайший предок, похожий на контейнер одной карточки."""
    cur = node
    for _ in range(8):
        cur = cur.parent
        if cur is None or not isinstance(cur, Tag):
            return None
        if cur.name in _CARD_TAGS:
            return cur
        cls = " ".join(cur.get("class") or [])
        if re.search(r"\b(s-item|s-card|su-card-container|srp-results__item)\b", cls):
            return cur
        if cur.get("data-testid") in {"item-card", "s-card"}:
            return cur
    return None


def _card_text(card: Tag) -> str:
    return normalize_ws(card.get_text(" ", strip=True))


def _first_link(card: Tag, item_id: str) -> str:
    for a in card.find_all("a", href=True):
        if item_id in a["href"]:
            return a["href"].split("?")[0]
    return f"https://www.ebay.de/itm/{item_id}"


def _title(card: Tag, item_id: str, text: str) -> str:
    # 1) явные заголовочные узлы
    for sel in (
        '[class*="s-item__title"]',
        '[class*="s-card__title"]',
        '[data-testid="item-title"]',
        "h3",
        "h2",
    ):
        node = card.select_one(sel)
        if node:
            t = normalize_ws(node.get_text(" ", strip=True))
            t = re.sub(r"^(Neues Angebot|New Listing|NEUES ANGEBOT)\s*", "", t).strip()
            if t and len(t) > 3:
                return t
    # 2) текст ссылки на товар
    for a in card.find_all("a", href=True):
        if item_id in a["href"]:
            t = normalize_ws(a.get_text(" ", strip=True))
            if t and len(t) > 3:
                return t
    # 3) первые слова карточки
    return text[:120]


def _image(card: Tag) -> str:
    img = card.find("img")
    if not img:
        return ""
    return img.get("src") or img.get("data-src") or ""


def _location(text: str) -> str:
    m = re.search(r"aus\s+([A-ZÄÖÜ][\wäöüß.\- ]{2,30})", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"from\s+([A-Z][\w.\- ]{2,30})", text)
    return m.group(1).strip() if m else ""


def parse_search_page(
    html: str,
    *,
    seed: str = "",
    query: str = "",
    include_promoted: bool = False,
    observed_at: Optional[dt.datetime] = None,
) -> list[Listing]:
    """Возвращает список объявлений со страницы выдачи."""
    soup = BeautifulSoup(html, "lxml")
    observed_at = observed_at or utcnow()

    cards: dict[str, Tag] = {}
    for a in soup.find_all("a", href=True):
        item_id = parse_item_id(a["href"])
        if not item_id or item_id in cards:
            continue
        card = _nearest_card(a)
        if card is not None:
            cards[item_id] = card

    listings: list[Listing] = []
    for item_id, card in cards.items():
        text = _card_text(card)
        if not include_promoted and _PROMO_MARKERS.search(text):
            continue

        seconds_left = parse_time_left(text)
        bids = parse_bids(text)
        listing = Listing(
            item_id=item_id,
            title=_title(card, item_id, text),
            url=_first_link(card, item_id),
            price=parse_price(text),
            shipping=parse_shipping(text),
            bids=bids,
            is_auction=bids is not None,
            buy_it_now=bool(_BIN_MARKERS.search(text)),
            seconds_left=seconds_left,
            end_time=(observed_at + dt.timedelta(seconds=seconds_left)) if seconds_left else None,
            condition=parse_condition(text),
            location=_location(text),
            image=_image(card),
            seed=seed,
            query=query,
            observed_at=observed_at,
            sold=looks_sold(text),
            raw_text=text[:400],
        )
        listings.append(listing)
    return listings


def parse_result_count(html: str) -> Optional[int]:
    """Сколько всего результатов нашёл eBay (для оценки объёма ниши)."""
    soup = BeautifulSoup(html, "lxml")
    for sel in ('[class*="srp-controls__count"]', '[class*="result-count"]', "h1", "h2"):
        for node in soup.select(sel):
            m = _RESULT_COUNT_RE.search(node.get_text(" ", strip=True))
            if m:
                digits = re.sub(r"\D", "", m.group(1))
                if digits:
                    return int(digits)
    m = _RESULT_COUNT_RE.search(soup.get_text(" ", strip=True)[:4000])
    if m:
        digits = re.sub(r"\D", "", m.group(1))
        if digits:
            return int(digits)
    return None


def looks_blocked(html: str) -> bool:
    """Признаки капчи/бана вместо выдачи."""
    if len(html) < 2000:
        return True
    low = html[:6000].lower()
    return any(
        marker in low
        for marker in (
            "pardon our interruption",
            "are you a human",
            "unusual traffic",
            "captcha",
            "zugriff verweigert",
            "access denied",
            "splashui",
        )
    )
