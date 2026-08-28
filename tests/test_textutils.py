import pytest

from ebaytrend.textutils import (
    looks_sold, parse_bids, parse_condition, parse_item_id,
    parse_price, parse_shipping, parse_time_left,
)


@pytest.mark.parametrize("text,expected", [
    ("EUR 123,45", 123.45),
    ("1.234,56 €", 1234.56),
    ("EUR 80,00 bis EUR 120,00", 80.0),
    ("US $99.00", 99.0),
    ("Sofort-Kaufen", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("+EUR 5,49 Versand", 5.49),
    ("Kostenloser Versand", 0.0),
    ("Versandkostenfrei", 0.0),
    ("Nur Abholung", None),
])
def test_parse_shipping(text, expected):
    assert parse_shipping(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("1 Gebot", 1),
    ("12 Gebote", 12),
    ("0 Gebote", 0),
    ("EUR 132,50 14 Gebote", 14),        # цена не должна склеиваться со ставками
    ("EUR 1.234,00 7 Gebote", 7),
    ("Sofort-Kaufen", None),
])
def test_parse_bids(text, expected):
    assert parse_bids(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Noch 1T 04Std", 100800),
    ("Noch 23Std 14Min", 83640),
    ("Noch 5Min", 300),
    ("3 Tage Rückgabe", None),            # срок возврата — не остаток аукциона
])
def test_parse_time_left(text, expected):
    assert parse_time_left(text) == expected


def test_parse_condition():
    assert parse_condition("Als Ersatzteil / defekt") == "defekt"
    assert parse_condition("Brandneu") == "neu"
    assert parse_condition("Gebraucht") == "gebraucht"


def test_parse_item_id():
    assert parse_item_id("https://www.ebay.de/itm/bosch/123456789012?x=1") == "123456789012"
    assert parse_item_id("https://www.ebay.de/sch/i.html") is None


def test_looks_sold():
    assert looks_sold("Verkauft 12. Aug 2026") is True
    assert looks_sold("Nicht verkauft") is False
    assert looks_sold("Noch 2T") is None
