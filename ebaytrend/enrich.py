"""Опциональное обогащение: карточка товара и история ставок.

В выдаче нет числа наблюдающих и времени старта аукциона. Для топ-кандидатов
их можно дотянуть с карточки лота — это дороже по запросам, поэтому делается
отдельной командой и только для верхушки списка.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Iterable, Optional

from .http import HttpClient
from .models import ItemDetails, utcnow
from .urls import bid_history_url, item_url

log = logging.getLogger(__name__)

_WATCHERS_PATTERNS = [
    re.compile(r'"watchCount"\s*:\s*(\d+)'),
    re.compile(r"(\d[\d.\s]*)\s*(?:Beobachter|Personen beobachten)", re.IGNORECASE),
    re.compile(r"(\d[\d.\s]*)\s*(?:watchers?|people are watching)", re.IGNORECASE),
]
_START_PATTERNS = [
    re.compile(
        r"(?:Startzeit|Startdatum|Start time|Started)\D{0,40}?"
        r"(\d{1,2}\.\d{1,2}\.\d{2,4}[^<\n]{0,20}\d{1,2}:\d{2})",
        re.IGNORECASE,
    ),
    re.compile(r'"startTime"\s*:\s*"([^"]+)"'),
]
_CATEGORY_RE = re.compile(r'"categoryPath"\s*:\s*"([^"]+)"')


def _int(raw: str) -> Optional[int]:
    digits = re.sub(r"\D", "", raw or "")
    return int(digits) if digits else None


def _parse_german_dt(raw: str) -> Optional[dt.datetime]:
    raw = raw.strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%y %H:%M", "%d.%m.%Y, %H:%M", "%d.%m.%y, %H:%M"):
        try:
            return dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_details(
    client: HttpClient, item_id: str, *, with_bid_history: bool = True
) -> Optional[ItemDetails]:
    html = client.get(item_url(item_id), referer="https://www.ebay.de/")
    if not html:
        return None

    details = ItemDetails(item_id=item_id, fetched_at=utcnow())
    for pattern in _WATCHERS_PATTERNS:
        match = pattern.search(html)
        if match:
            details.watchers = _int(match.group(1))
            break
    match = _CATEGORY_RE.search(html)
    if match:
        details.category_path = match.group(1)[:200]

    if with_bid_history:
        history = client.get(bid_history_url(item_id), referer=item_url(item_id))
        if history:
            for pattern in _START_PATTERNS:
                match = pattern.search(history)
                if match:
                    details.start_time = _parse_german_dt(match.group(1))
                    break
    return details


def enrich_items(
    client: HttpClient, item_ids: Iterable[str], *, limit: int = 25, with_bid_history: bool = True
) -> list[ItemDetails]:
    out: list[ItemDetails] = []
    for idx, item_id in enumerate(item_ids):
        if idx >= limit:
            break
        details = fetch_details(client, item_id, with_bid_history=with_bid_history)
        if details:
            out.append(details)
            log.info("  %s: наблюдателей %s", item_id, details.watchers)
    return out
