"""CLI: python -m ebaytrend <команда>."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
from pathlib import Path

from .backends import get_backend
from .config import current_month, load_rules, load_seeds, season_window, select_seeds
from .http import HttpClient
from .pipeline import build_clusters, scan_seeds
from .report import (
    render_clusters,
    render_items,
    render_markdown_report,
    write_clusters_csv,
    write_items_csv,
)
from .scoring import item_heat
from .storage import Store

DEFAULT_DB = "data/ebay.sqlite3"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )


def _pick_seeds(args) -> list:
    seeds = load_seeds(args.seeds_file)
    months = None
    if getattr(args, "all_seasons", False):
        months = None
    elif getattr(args, "month", None):
        months = season_window(args.month, args.lookahead)
    else:
        months = season_window(current_month(), args.lookahead)
    selected = select_seeds(
        seeds,
        keys=args.seeds or None,
        season_month=months,
        tags=args.tags or None,
        skip_bulky=getattr(args, "no_bulky", False),
    )
    return seeds, selected


def _make_backend(args):
    if args.backend == "html":
        client = HttpClient(delay=args.delay, jitter=args.jitter, cookie=args.cookie)
        return get_backend("html", client=client)
    return get_backend(args.backend)


# --- команды ------------------------------------------------------------------

def cmd_seeds(args) -> int:
    all_seeds, selected = _pick_seeds(args)
    keys = {s.key for s in selected}
    print(f"Ниш всего: {len(all_seeds)}, в выборке: {len(selected)}\n")
    for seed in all_seeds:
        mark = "→" if seed.key in keys else " "
        season = ",".join(str(m) for m in seed.season) or "круглый год"
        tags = ",".join(seed.tags) or "—"
        print(f"{mark} {seed.key:24} {seed.label}")
        print(f"    сезон: {season} | метки: {tags} | закуп {seed.buy_ratio:.0%} от цены")
        print(f"    запросы: {'; '.join(seed.queries)}")
        if seed.note:
            print(f"    {seed.note}")
    return 0


def cmd_scan(args) -> int:
    _, selected = _pick_seeds(args)
    if not selected:
        print("Под выбранные фильтры не попала ни одна ниша.", file=sys.stderr)
        return 1
    rules = load_rules(args.exclude_file)
    store = Store(args.db)
    backend = _make_backend(args)
    try:
        print(
            f"Скан: ниш {len(selected)}, запросов "
            f"{sum(len(s.queries) for s in selected)}, режим {args.mode}, "
            f"бэкенд {backend.name}",
            file=sys.stderr,
        )
        stats = scan_seeds(
            backend, store, selected, rules,
            mode=args.mode, pages=args.pages, dry_run=args.dry_run,
        )
    finally:
        backend.close()

    print(
        f"\nЗапросов: {stats.queries} | карточек: {stats.raw} | "
        f"после фильтров: {stats.kept}"
    )
    if stats.rejected:
        print("Отсеяно:")
        for reason, count in sorted(stats.rejected.items(), key=lambda kv: -kv[1]):
            print(f"  {count:5}  {reason}")
    if stats.blocked:
        print(
            f"\n!!! eBay заблокировал {stats.blocked} запрос(ов) — увеличьте --delay, "
            "подставьте --cookie из браузера или перейдите на --backend api",
            file=sys.stderr,
        )
    for err in stats.errors[:10]:
        print(f"  ошибка: {err}", file=sys.stderr)
    print(f"\nБД: {args.db} | {store.stats()}")
    store.close()
    return 0


def cmd_watch(args) -> int:
    """Повторные сканы: только так считается честная скорость ставок."""
    for round_no in range(1, args.rounds + 1):
        print(
            f"\n=== проход {round_no}/{args.rounds} "
            f"({dt.datetime.now().strftime('%H:%M:%S')}) ===",
            file=sys.stderr,
        )
        cmd_scan(args)
        if round_no < args.rounds:
            print(f"пауза {args.interval} мин…", file=sys.stderr)
            time.sleep(args.interval * 60)
    return 0


def cmd_report(args) -> int:
    seeds, _ = _pick_seeds(args)
    store = Store(args.db)
    clusters, items = build_clusters(
        store, seeds,
        since_hours=args.since_hours,
        min_hours_left=args.min_hours_left,
        max_hours_left=args.max_hours_left,
    )
    if args.seeds:
        wanted = {k.lower() for k in args.seeds}
        clusters = [c for c in clusters if c.key.lower() in wanted]
        items = [i for i in items if i.seed.lower() in wanted]
    if not clusters:
        print("Данных нет — сначала запустите scan.", file=sys.stderr)
        store.close()
        return 1

    print("\nНИШИ ПО СПРОСУ\n")
    print(render_clusters(clusters, limit=args.top_clusters))
    print("\nГОРЯЧИЕ ЛОТЫ\n")
    print(render_items(items, limit=args.top_items))

    delta_items = [i for i in items if i.method == "delta"]
    print(
        f"\nЛотов с честной дельтой (2+ скана): {len(delta_items)} из {len(items)}."
        + ("" if delta_items else " Запустите `watch`, чтобы считать ставки в час по факту.")
    )

    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(
            render_markdown_report(
                clusters, items,
                cluster_limit=args.top_clusters, item_limit=args.top_items,
            ),
            encoding="utf-8",
        )
        print(f"Markdown-отчёт: {args.md}")
    if args.csv_dir:
        items_path = write_items_csv(items, Path(args.csv_dir) / "items.csv")
        clusters_path = write_clusters_csv(clusters, Path(args.csv_dir) / "clusters.csv")
        print(f"CSV: {items_path}, {clusters_path}")
    store.close()
    return 0


def cmd_enrich(args) -> int:
    from .enrich import enrich_items

    seeds, _ = _pick_seeds(args)
    store = Store(args.db)
    clusters, items = build_clusters(store, seeds)
    top = sorted(items, key=item_heat, reverse=True)[: args.limit]
    if not top:
        print("Нечего обогащать — сначала scan.", file=sys.stderr)
        store.close()
        return 1
    client = HttpClient(delay=args.delay, jitter=args.jitter, cookie=args.cookie)
    try:
        details = enrich_items(
            client, [i.item_id for i in top],
            limit=args.limit, with_bid_history=not args.no_bid_history,
        )
    finally:
        client.close()
    saved = store.save_details(details)
    print(f"Обогащено лотов: {saved}")
    for d in details:
        print(f"  {d.item_id}: наблюдателей={d.watchers} старт={d.start_time}")
    store.close()
    return 0


def cmd_parse_file(args) -> int:
    """Отладка парсера на сохранённой странице (Ctrl+S из браузера)."""
    from .html_parser import looks_blocked, parse_result_count, parse_search_page

    html = Path(args.path).read_text(encoding="utf-8", errors="ignore")
    if looks_blocked(html):
        print("Похоже на капчу/блокировку, а не на выдачу.", file=sys.stderr)
    listings = parse_search_page(html, include_promoted=args.include_promoted)
    print(f"Всего результатов по данным eBay: {parse_result_count(html)}")
    print(f"Карточек разобрано: {len(listings)}")
    fields = {
        "цена": sum(1 for x in listings if x.price is not None),
        "ставки": sum(1 for x in listings if x.bids is not None),
        "остаток времени": sum(1 for x in listings if x.seconds_left is not None),
        "доставка": sum(1 for x in listings if x.shipping is not None),
        "состояние": sum(1 for x in listings if x.condition),
    }
    for name, count in fields.items():
        print(f"  {name}: {count}/{len(listings)}")
    for item in listings[: args.limit]:
        print(
            f"  {item.item_id} | {item.price} € | {item.bids} ст. | "
            f"{item.seconds_left} с | {item.title[:60]}"
        )
    return 0


def cmd_doctor(args) -> int:
    store = Store(args.db)
    stats = store.stats()
    print(f"БД: {args.db}")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    rows = store.conn.execute(
        "SELECT seed, COUNT(*) n, SUM(blocked) blocked FROM scans GROUP BY seed "
        "ORDER BY n DESC LIMIT 20"
    ).fetchall()
    if rows:
        print("\nСканы по нишам:")
        for row in rows:
            flag = f" (блокировок: {row['blocked']})" if row["blocked"] else ""
            print(f"  {row['seed']:24} {row['n']}{flag}")
    multi = store.conn.execute(
        "SELECT COUNT(*) FROM (SELECT item_id FROM observations "
        "GROUP BY item_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    print(f"\nЛотов с 2+ наблюдениями (годятся для дельты): {multi}")
    store.close()
    return 0


# --- парсер аргументов --------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ebaytrend",
        description="Поиск ходовых товаров на ebay.de по скорости прироста ставок",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p, *, with_net: bool = False):
        p.add_argument("--db", default=DEFAULT_DB, help="файл SQLite")
        p.add_argument("--seeds-file", default=None, help="путь к seeds.yaml")
        p.add_argument("--exclude-file", default=None, help="путь к exclude.yaml")
        p.add_argument("--seeds", nargs="*", help="ключи ниш (по умолчанию все сезонные)")
        p.add_argument("--tags", nargs="*", help="фильтр по меткам: vinted, bulky, …")
        p.add_argument("--month", type=int, help="месяц сезона 1-12 (по умолчанию текущий)")
        p.add_argument("--lookahead", type=int, default=1, help="на сколько месяцев вперёд брать сезон")
        p.add_argument("--all-seasons", action="store_true", help="игнорировать сезонность")
        p.add_argument("--no-bulky", action="store_true", help="убрать крупногабарит")
        if with_net:
            p.add_argument("--backend", default="html", choices=["html", "api"])
            p.add_argument("--delay", type=float, default=3.5, help="пауза между запросами, с")
            p.add_argument("--jitter", type=float, default=1.5)
            p.add_argument("--cookie", default=None, help="Cookie из браузера при капче")

    p_seeds = sub.add_parser("seeds", help="показать ниши")
    add_common(p_seeds)
    p_seeds.set_defaults(func=cmd_seeds)

    p_scan = sub.add_parser("scan", help="один проход сканирования")
    add_common(p_scan, with_net=True)
    p_scan.add_argument("--mode", default="auction", choices=["auction", "sold"])
    p_scan.add_argument("--pages", type=int, default=None, help="страниц выдачи на запрос")
    p_scan.add_argument("--dry-run", action="store_true", help="не писать в БД")
    p_scan.set_defaults(func=cmd_scan)

    p_watch = sub.add_parser("watch", help="повторные сканы для честной дельты ставок")
    add_common(p_watch, with_net=True)
    p_watch.add_argument("--mode", default="auction", choices=["auction", "sold"])
    p_watch.add_argument("--pages", type=int, default=None)
    p_watch.add_argument("--dry-run", action="store_true")
    p_watch.add_argument("--interval", type=float, default=45, help="пауза между проходами, мин")
    p_watch.add_argument("--rounds", type=int, default=6, help="сколько проходов")
    p_watch.set_defaults(func=cmd_watch)

    p_report = sub.add_parser("report", help="отчёт по нишам и лотам")
    add_common(p_report)
    p_report.add_argument("--top-clusters", type=int, default=25)
    p_report.add_argument("--top-items", type=int, default=40)
    p_report.add_argument("--since-hours", type=float, default=None, help="только свежие наблюдения")
    p_report.add_argument("--min-hours-left", type=float, default=None,
                          help="убрать лоты, которым осталось меньше N часов (снайпинг)")
    p_report.add_argument("--max-hours-left", type=float, default=None)
    p_report.add_argument("--md", default=None, help="сохранить Markdown-отчёт")
    p_report.add_argument("--csv-dir", default=None, help="каталог для CSV")
    p_report.set_defaults(func=cmd_report)

    p_enrich = sub.add_parser("enrich", help="дотянуть наблюдателей и время старта для топа")
    add_common(p_enrich, with_net=True)
    p_enrich.add_argument("--limit", type=int, default=25)
    p_enrich.add_argument("--no-bid-history", action="store_true")
    p_enrich.set_defaults(func=cmd_enrich)

    p_parse = sub.add_parser("parse-file", help="отладить парсер на сохранённом HTML")
    p_parse.add_argument("path")
    p_parse.add_argument("--limit", type=int, default=10)
    p_parse.add_argument("--include-promoted", action="store_true")
    p_parse.set_defaults(func=cmd_parse_file)

    p_doctor = sub.add_parser("doctor", help="состояние БД и сканов")
    p_doctor.add_argument("--db", default=DEFAULT_DB)
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose if hasattr(args, "verbose") else False)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
