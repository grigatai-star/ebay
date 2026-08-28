from pathlib import Path

import pytest

from ebaytrend.html_parser import looks_blocked, parse_result_count, parse_search_page

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_classic_layout():
    listings = {l.item_id: l for l in parse_search_page(load("search_classic.html"))}
    assert "111000111000" not in listings          # реклама («Anzeige») отсеяна
    assert len(listings) == 4

    bosch = listings["256789012345"]
    assert bosch.price == 132.5
    assert bosch.shipping == 5.49
    assert bosch.bids == 14
    assert bosch.seconds_left == 100800
    assert bosch.condition == "gebraucht"
    assert bosch.location == "Deutschland"
    assert bosch.is_auction and not bosch.buy_it_now
    assert bosch.total_price == 137.99

    makita = listings["195544332211"]
    assert makita.title.startswith("Makita")       # префикс «Neues Angebot» убран
    assert makita.shipping == 0.0

    festool = listings["166112233445"]
    assert festool.buy_it_now and not festool.is_auction


def test_modern_layout():
    listings = {l.item_id: l for l in parse_search_page(load("search_modern.html"))}
    assert len(listings) == 2
    zeiss = listings["335566778899"]
    assert zeiss.price == 465.0
    assert zeiss.bids == 23
    assert zeiss.seconds_left == 21600
    assert "Zeiss Conquest" in zeiss.title
    assert listings["224411556677"].bids == 0


def test_promoted_included_on_demand():
    listings = parse_search_page(load("search_classic.html"), include_promoted=True)
    assert len(listings) == 5


@pytest.mark.parametrize("name,expected", [
    ("search_classic.html", 1284),
    ("search_modern.html", 412),
])
def test_result_count(name, expected):
    assert parse_result_count(load(name)) == expected


def test_looks_blocked():
    assert looks_blocked("<html><body>Pardon Our Interruption</body></html>" + " " * 3000)
    assert looks_blocked("<html>too short</html>")
    assert not looks_blocked(load("search_classic.html"))
