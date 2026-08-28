from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..models import Listing


@dataclass
class SearchResult:
    listings: list[Listing] = field(default_factory=list)
    total_results: Optional[int] = None
    blocked: bool = False
    error: str = ""
    url: str = ""


class Backend(Protocol):
    name: str

    def search(
        self,
        query: str,
        *,
        seed: str = "",
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        pages: int = 1,
        sold: bool = False,
        **kwargs,
    ) -> SearchResult: ...

    def close(self) -> None: ...
