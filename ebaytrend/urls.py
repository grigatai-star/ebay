"""Сборка URL поиска ebay.de."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

SEARCH_BASE = "https://www.ebay.de/sch/i.html"

# _sop — сортировка выдачи
SORT = {
    "ending_soonest": 1,     # заканчиваются раньше всего
    "newly_listed": 10,      # новые
    "best_match": 12,        # релевантность
    "price_high": 15,
    "price_low": 16,
    "ended_recently": 13,    # для завершённых/проданных
}

# LH_ItemCondition
CONDITION = {"new": "1000", "used": "3000", "refurbished": "2000|2500", "parts": "7000"}


def build_search_url(
    query: str,
    *,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    auction_only: bool = True,
    bin_only: bool = False,
    sold: bool = False,
    completed: bool = False,
    germany_only: bool = True,
    condition: Optional[str] = None,
    category_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 240,
    sort: str = "ending_soonest",
    exclude_words: Optional[list[str]] = None,
) -> str:
    """Собирает ссылку на выдачу ebay.de с нужными фильтрами."""
    nkw = query.strip()
    for word in exclude_words or []:
        word = word.strip()
        if word and word.lower() not in nkw.lower():
            nkw += f" -{word}" if " " not in word else f' -"{word}"'

    params: dict[str, str | int] = {"_nkw": nkw, "_ipg": per_page, "_pgn": max(1, page)}

    if auction_only:
        params["LH_Auction"] = 1
    if bin_only:
        params["LH_BIN"] = 1
    if sold:
        params["LH_Sold"] = 1
        params["LH_Complete"] = 1
    elif completed:
        params["LH_Complete"] = 1
    if price_min is not None:
        params["_udlo"] = f"{price_min:g}"
    if price_max is not None:
        params["_udhi"] = f"{price_max:g}"
    if germany_only:
        params["LH_PrefLoc"] = 1          # только товары из Германии
    if condition:
        code = CONDITION.get(condition, condition)
        params["LH_ItemCondition"] = code
    if category_id:
        params["_sacat"] = category_id

    params["_sop"] = SORT.get(sort, SORT["ending_soonest"])
    params["rt"] = "nc"
    return f"{SEARCH_BASE}?{urlencode(params, safe='|')}"


def item_url(item_id: str) -> str:
    return f"https://www.ebay.de/itm/{item_id}"


def bid_history_url(item_id: str) -> str:
    """Страница истории ставок (там же видно время старта аукциона)."""
    return f"https://www.ebay.de/bfl/viewbids/{item_id}?item={item_id}"
