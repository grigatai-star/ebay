"""Бэкенд поверх публичной выдачи ebay.de (HTML).

Работает без ключей, но eBay может показать капчу — тогда SearchResult.blocked=True.
Для регулярного сбора лучше использовать бэкенд `api` (официальный Browse API).
"""

from __future__ import annotations

import logging
from typing import Optional

from ..html_parser import looks_blocked, parse_result_count, parse_search_page
from ..http import HttpClient
from ..urls import build_search_url
from .base import SearchResult

log = logging.getLogger(__name__)


class HtmlBackend:
    name = "html"

    def __init__(self, *, client: Optional[HttpClient] = None, **client_kwargs) -> None:
        self.client = client or HttpClient(**client_kwargs)

    def search(
        self,
        query: str,
        *,
        seed: str = "",
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        pages: int = 1,
        sold: bool = False,
        category_id: Optional[str] = None,
        exclude_words: Optional[list[str]] = None,
        sort: Optional[str] = None,
        auction_only: bool = True,
        include_promoted: bool = False,
        per_page: int = 240,
        **_ignored,
    ) -> SearchResult:
        result = SearchResult()
        seen: set[str] = set()
        sort = sort or ("ended_recently" if sold else "ending_soonest")

        for page in range(1, max(1, pages) + 1):
            url = build_search_url(
                query,
                price_min=price_min,
                price_max=price_max,
                auction_only=auction_only and not sold,
                sold=sold,
                category_id=category_id,
                page=page,
                per_page=per_page,
                sort=sort,
                exclude_words=exclude_words,
            )
            result.url = result.url or url
            html = self.client.get(url, referer="https://www.ebay.de/")
            if html is None:
                result.error = "не удалось загрузить страницу"
                break
            if looks_blocked(html):
                result.blocked = True
                result.error = "eBay показал капчу/блокировку вместо выдачи"
                break
            if result.total_results is None:
                result.total_results = parse_result_count(html)

            batch = parse_search_page(
                html, seed=seed, query=query, include_promoted=include_promoted
            )
            fresh = [x for x in batch if x.item_id not in seen]
            for item in fresh:
                seen.add(item.item_id)
                if sold:
                    item.sold = True if item.sold is None else item.sold
            result.listings.extend(fresh)
            log.info("  стр.%d: %d карточек (новых %d) — %s", page, len(batch), len(fresh), query)
            if len(batch) < 5:      # выдача кончилась
                break
        return result

    def close(self) -> None:
        self.client.close()
