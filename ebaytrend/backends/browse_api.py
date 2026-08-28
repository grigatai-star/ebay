"""Официальный eBay Browse API — легальная альтернатива скрейпингу.

Нужны ключи приложения (https://developer.ebay.com):
    export EBAY_CLIENT_ID=...      # App ID (Client ID)
    export EBAY_CLIENT_SECRET=...  # Cert ID (Client Secret)

Плюсы: не блокируют, стабильная схема, есть bidCount и itemEndDate.
Минусы: нет проданных/завершённых лотов (это Marketplace Insights API, доступ
по заявке), поэтому режим `--sold` работает только на бэкенде `html`.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import os
import time
from typing import Any, Optional

import requests

from ..models import Listing, utcnow
from .base import SearchResult

log = logging.getLogger(__name__)

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
SANDBOX_SEARCH_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"
MAX_LIMIT = 200


def _num(raw: Any) -> Optional[float]:
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def _parse_dt(raw: Optional[str]) -> Optional[dt.datetime]:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _legacy_id(item_id: str) -> str:
    """'v1|123456789012|0' -> '123456789012'."""
    parts = (item_id or "").split("|")
    return parts[1] if len(parts) > 1 else item_id


class BrowseApiBackend:
    name = "api"

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        marketplace: str = "EBAY_DE",
        sandbox: bool = False,
        timeout: float = 30.0,
        **_ignored,
    ) -> None:
        self.client_id = client_id or os.getenv("EBAY_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("EBAY_CLIENT_SECRET", "")
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "нужны EBAY_CLIENT_ID и EBAY_CLIENT_SECRET (developer.ebay.com) "
                "или используйте --backend html"
            )
        self.marketplace = marketplace
        self.timeout = timeout
        self.token_url = SANDBOX_TOKEN_URL if sandbox else TOKEN_URL
        self.search_url = SANDBOX_SEARCH_URL if sandbox else SEARCH_URL
        self.session = requests.Session()
        self._token = ""
        self._token_expires = 0.0

    # ---- auth ---------------------------------------------------------------

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = self.session.post(
            self.token_url,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires = time.time() + int(payload.get("expires_in", 7200))
        return self._token

    # ---- search -------------------------------------------------------------

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
        auction_only: bool = True,
        per_page: int = MAX_LIMIT,
        **_ignored,
    ) -> SearchResult:
        result = SearchResult()
        if sold:
            result.error = (
                "Browse API не отдаёт проданные лоты — используйте --backend html "
                "для режима sold"
            )
            return result

        filters = ["itemLocationCountry:DE"]
        if auction_only:
            filters.append("buyingOptions:{AUCTION}")
        if price_min is not None or price_max is not None:
            lo = f"{price_min:g}" if price_min is not None else ""
            hi = f"{price_max:g}" if price_max is not None else ""
            filters.append(f"price:[{lo}..{hi}]")
            filters.append("priceCurrency:EUR")

        limit = min(per_page, MAX_LIMIT)
        observed_at = utcnow()
        for page in range(max(1, pages)):
            params = {
                "q": query,
                "limit": limit,
                "offset": page * limit,
                "filter": ",".join(filters),
                "sort": "endingSoonest",
            }
            if category_id:
                params["category_ids"] = category_id
            try:
                resp = self.session.get(
                    self.search_url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._access_token()}",
                        "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
                        "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DDE",
                        "Accept": "application/json",
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                result.error = f"сеть: {exc}"
                break
            result.url = result.url or resp.url
            if resp.status_code != 200:
                result.error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                break

            payload = resp.json()
            result.total_results = payload.get("total", result.total_results)
            summaries = payload.get("itemSummaries") or []
            for raw in summaries:
                result.listings.append(
                    self._to_listing(raw, seed=seed, query=query, observed_at=observed_at)
                )
            if len(summaries) < limit:
                break
        return result

    @staticmethod
    def _to_listing(
        raw: dict, *, seed: str, query: str, observed_at: dt.datetime
    ) -> Listing:
        price = _num((raw.get("currentBidPrice") or raw.get("price") or {}).get("value"))
        shipping = None
        options = raw.get("shippingOptions") or []
        if options:
            shipping = _num((options[0].get("shippingCost") or {}).get("value"))
        end_time = _parse_dt(raw.get("itemEndDate"))
        seconds_left = (
            max(0, int((end_time - observed_at).total_seconds())) if end_time else None
        )
        buying = raw.get("buyingOptions") or []
        categories = raw.get("categories") or []
        return Listing(
            item_id=_legacy_id(raw.get("itemId", "")),
            title=raw.get("title", ""),
            url=raw.get("itemWebUrl", ""),
            price=price,
            shipping=shipping,
            bids=raw.get("bidCount"),
            is_auction="AUCTION" in buying,
            buy_it_now="FIXED_PRICE" in buying,
            seconds_left=seconds_left,
            end_time=end_time,
            condition=(raw.get("condition") or "").lower(),
            location=((raw.get("itemLocation") or {}).get("postalCode") or "") ,
            seller=(raw.get("seller") or {}).get("username", ""),
            image=((raw.get("image") or {}).get("imageUrl") or ""),
            category_id=str(categories[0].get("categoryId")) if categories else "",
            seed=seed,
            query=query,
            observed_at=observed_at,
        )

    def close(self) -> None:
        self.session.close()
