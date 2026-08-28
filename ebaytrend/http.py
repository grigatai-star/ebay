"""HTTP-клиент: вежливый rate limit, ретраи, браузерные заголовки."""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class RateLimiter:
    """Не чаще одного запроса в `delay` секунд (+ джиттер)."""

    def __init__(self, delay: float = 3.5, jitter: float = 1.5) -> None:
        self.delay = delay
        self.jitter = jitter
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            target = self._last + self.delay + random.uniform(0, self.jitter)
            if now < target:
                time.sleep(target - now)
            self._last = time.monotonic()


class HttpClient:
    def __init__(
        self,
        *,
        delay: float = 3.5,
        jitter: float = 1.5,
        timeout: float = 30.0,
        max_retries: int = 4,
        user_agent: Optional[str] = None,
        proxy: Optional[str] = None,
        cookie: Optional[str] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = RateLimiter(delay, jitter)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent or os.getenv("EBAYTREND_UA") or DEFAULT_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
                "Cache-Control": "no-cache",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            }
        )
        cookie = cookie or os.getenv("EBAYTREND_COOKIE")
        if cookie:
            self.session.headers["Cookie"] = cookie
        proxy = proxy or os.getenv("EBAYTREND_PROXY")
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

    def get(self, url: str, *, referer: Optional[str] = None) -> Optional[str]:
        """GET с ретраями. Возвращает текст или None, если так и не получилось."""
        headers = {"Referer": referer} if referer else {}
        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            self.limiter.wait()
            try:
                resp = self.session.get(url, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                log.warning("сеть: %s (попытка %d/%d)", exc, attempt, self.max_retries)
            else:
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in (429, 500, 502, 503, 504):
                    log.warning(
                        "HTTP %s от eBay (попытка %d/%d), пауза %.0fs",
                        resp.status_code, attempt, self.max_retries, backoff,
                    )
                else:
                    log.error("HTTP %s: %s", resp.status_code, url)
                    return None
            time.sleep(backoff)
            backoff *= 2
        return None

    def close(self) -> None:
        self.session.close()
