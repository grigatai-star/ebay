"""Сквозной прогон без сети: HtmlBackend поверх подменённого HTTP-клиента."""

from pathlib import Path

from ebaytrend.backends import HtmlBackend
from ebaytrend.config import Seed
from ebaytrend.filters import Rules
from ebaytrend.pipeline import build_clusters, scan_seeds
from ebaytrend.report import render_clusters, render_items, render_markdown_report
from ebaytrend.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Отдаёт фикстуру и на втором проходе поднимает ставки — как живой аукцион."""

    def __init__(self):
        self.calls = 0
        self.round = 0

    def get(self, url, referer=None):
        self.calls += 1
        html = (FIXTURES / "search_classic.html").read_text(encoding="utf-8")
        if self.round > 0:
            html = html.replace("14 Gebote", "26 Gebote").replace("EUR 132,50", "EUR 188,00")
        return html

    def close(self):
        pass


def make_seed():
    return Seed(
        key="profi_akkuwerkzeug",
        label="Профинструмент",
        queries=["Bosch Professional Akkuschrauber"],
        price_min=80,
        price_max=500,
        pages=1,
    )


def test_scan_filters_and_stores(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    client = FakeClient()
    backend = HtmlBackend(client=client)

    stats = scan_seeds(backend, store, [make_seed()], Rules())
    # из 4 карточек остаются 2: дефектная Hilti и Sofort-Kaufen Festool отсеяны
    assert stats.raw == 4
    assert stats.kept == 2
    assert store.stats()["items"] == 2
    store.close()


def test_second_scan_produces_delta_velocity(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    client = FakeClient()
    backend = HtmlBackend(client=client)
    seeds = [make_seed()]

    scan_seeds(backend, store, seeds, Rules())
    client.round = 1
    # второе наблюдение с другой меткой времени
    import datetime as dt

    import ebaytrend.models as models

    real_utcnow = models.utcnow
    later = real_utcnow() + dt.timedelta(hours=2)
    models.utcnow = lambda: later
    try:
        import ebaytrend.html_parser as hp

        hp.utcnow = lambda: later
        scan_seeds(backend, store, seeds, Rules())
    finally:
        models.utcnow = real_utcnow
        import ebaytrend.html_parser as hp

        hp.utcnow = real_utcnow

    clusters, items = build_clusters(store, seeds)
    bosch = next(i for i in items if i.item_id == "256789012345")
    assert bosch.observations == 2
    assert bosch.bids_delta == 12
    assert bosch.bids_per_hour_delta == 6.0        # 12 ставок за 2 часа
    assert bosch.price_growth == 55.5
    assert bosch.method == "delta"

    assert clusters and clusters[0].key == "profi_akkuwerkzeug"
    assert clusters[0].n_items == 2
    store.close()


def test_report_renders(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    backend = HtmlBackend(client=FakeClient())
    seeds = [make_seed()]
    scan_seeds(backend, store, seeds, Rules())
    clusters, items = build_clusters(store, seeds)

    assert "Профинструмент" in render_clusters(clusters)
    assert "Bosch" in render_items(items)
    md = render_markdown_report(clusters, items)
    assert md.startswith("# eBay.de")
    assert "| # |" in md
    store.close()
