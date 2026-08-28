"""Отчёты: таблицы для терминала, Markdown и CSV."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .scoring import ClusterMetrics, item_heat
from .velocity import ItemMetrics


def _fmt(value: Any, digits: int = 2, dash: str = "—") -> str:
    if value is None:
        return dash
    if isinstance(value, float):
        text = f"{value:.{digits}f}"
        # хвостовые нули режем только после запятой: иначе 150 превращается в 15
        return (text.rstrip("0").rstrip(".") or "0") if "." in text else text
    return str(value)


def _truncate(text: str, width: int) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]], *, markdown: bool = False) -> str:
    if not rows:
        return "(пусто)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    sep = " | " if markdown else "  "
    lines = []
    head = sep.join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    lines.append(f"| {head} |" if markdown else head)
    if markdown:
        lines.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    else:
        lines.append("-" * len(head))
    for row in rows:
        body = sep.join(str(c).ljust(widths[i]) for i, c in enumerate(row))
        lines.append(f"| {body} |" if markdown else body)
    return "\n".join(lines)


# --- ниши --------------------------------------------------------------------

CLUSTER_HEADERS = [
    "#", "ниша", "скор", "лотов", "со ставками", "медиана €",
    "ставок/ч p75", "продаж %", "закуп до €", "метки",
]


def cluster_rows(clusters: Sequence[ClusterMetrics], limit: int = 30) -> list[list[str]]:
    rows = []
    for idx, c in enumerate(clusters[:limit], 1):
        rows.append([
            str(idx),
            _truncate(c.label, 46),
            _fmt(c.demand_score, 1),
            str(c.n_items),
            f"{_fmt((c.bid_rate_late or 0) * 100, 0)}%" if c.bid_rate_late is not None else "—",
            _fmt(c.median_price, 0),
            _fmt(c.bids_per_hour_p75, 2),
            f"{_fmt((c.sell_through or 0) * 100, 0)}%" if c.sell_through is not None else "—",
            _fmt(c.target_buy_price, 0),
            ",".join(c.tags) or "—",
        ])
    return rows


def render_clusters(clusters: Sequence[ClusterMetrics], *, limit: int = 30, markdown: bool = False) -> str:
    return render_table(CLUSTER_HEADERS, cluster_rows(clusters, limit), markdown=markdown)


# --- лоты --------------------------------------------------------------------

ITEM_HEADERS = ["#", "лот", "€", "ставок", "ставок/ч", "heat", "осталось", "метод", "ниша"]


def _hours_label(hours: Optional[float]) -> str:
    if hours is None:
        return "—"
    if hours < 1:
        return f"{int(hours * 60)}м"
    if hours < 48:
        return f"{hours:.1f}ч"
    return f"{hours / 24:.1f}д"


def item_rows(items: Sequence[ItemMetrics], limit: int = 40) -> list[list[str]]:
    ranked = sorted(items, key=item_heat, reverse=True)[:limit]
    rows = []
    for idx, i in enumerate(ranked, 1):
        rows.append([
            str(idx),
            _truncate(i.title, 58),
            _fmt(i.price, 0),
            _fmt(i.bids, 0),
            _fmt(i.bids_per_hour, 2),
            _fmt(item_heat(i), 2),
            _hours_label(i.hours_left),
            i.method,
            _truncate(i.seed, 22),
        ])
    return rows


def render_items(items: Sequence[ItemMetrics], *, limit: int = 40, markdown: bool = False) -> str:
    return render_table(ITEM_HEADERS, item_rows(items, limit), markdown=markdown)


# --- сводный markdown --------------------------------------------------------

def render_markdown_report(
    clusters: Sequence[ClusterMetrics],
    items: Sequence[ItemMetrics],
    *,
    cluster_limit: int = 25,
    item_limit: int = 40,
    generated_at: Optional[dt.datetime] = None,
) -> str:
    now = generated_at or dt.datetime.now(dt.timezone.utc)
    parts = [
        "# eBay.de — что сейчас разбирают",
        "",
        f"Сформировано: {now.strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"Ниш в выборке: {len(clusters)} · лотов: {len(items)}",
        "",
        "## Ниши по спросу",
        "",
        render_clusters(clusters, limit=cluster_limit, markdown=True),
        "",
        "## Самые горячие лоты",
        "",
        "`heat` = ставок в час с поправкой на фазу аукциона (снайпинг в последний час "
        "занижается, ранние ставки весят больше). `метод`: delta — по разнице между "
        "сканами, est — оценка по одному скану.",
        "",
        render_items(items, limit=item_limit, markdown=True),
        "",
        "## Что с этим делать",
        "",
    ]
    for c in clusters[:8]:
        buy = f"до **{_fmt(c.target_buy_price, 0)} €**" if c.target_buy_price else "—"
        flags = " · крупногабарит (только самовывоз)" if c.bulky else ""
        parts.append(
            f"- **{c.label}** — скор {_fmt(c.demand_score, 1)}, медиана "
            f"{_fmt(c.median_price, 0)} €, брать в закуп {buy}.{flags}"
        )
        if c.note:
            parts.append(f"  {c.note}")
    return "\n".join(parts) + "\n"


# --- CSV ---------------------------------------------------------------------

def write_items_csv(items: Iterable[ItemMetrics], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "item_id", "title", "seed", "query", "condition", "price", "price_start",
        "bids", "bids_delta", "bids_per_hour_delta", "bids_per_hour_est",
        "price_per_hour_delta", "hours_left", "elapsed_hours", "phase",
        "observations", "span_hours", "heat", "method", "url",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for i in items:
            row = i.__dict__.copy()
            row["heat"] = item_heat(i)
            row["method"] = i.method
            writer.writerow(row)
    return path


def write_clusters_csv(clusters: Iterable[ClusterMetrics], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "key", "label", "demand_score", "n_items", "n_late", "n_with_bids",
        "bid_rate_late", "median_price", "median_bids_late", "bids_per_hour_p75",
        "sell_through", "median_sold_price", "target_buy_price", "total_results",
        "tags", "note",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for c in clusters:
            row = {f: getattr(c, f, None) for f in fields}
            row["tags"] = ",".join(c.tags)
            row["target_buy_price"] = c.target_buy_price
            writer.writerow(row)
    return path
