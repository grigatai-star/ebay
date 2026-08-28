from ebaytrend.config import load_rules
from ebaytrend.filters import Rules, apply, is_bulky, reject_reason
from ebaytrend.models import Listing


def item(**kw):
    base = dict(item_id="1", title="Bosch Professional Akkuschrauber GSR 18V", price=150.0, bids=4)
    base.update(kw)
    return Listing(**base)


def test_good_item_passes():
    assert reject_reason(item(), Rules()) is None


def test_saturated_niche_rejected():
    reason = reject_reason(item(title="Apple iPhone 13 128GB gebraucht"), Rules())
    assert reason and "перегретая" in reason


def test_junk_keyword_rejected():
    assert reject_reason(item(title="Makita Bohrschrauber Ersatzteil defekt"), Rules())
    assert reject_reason(item(title="Nur Karton für Jura Kaffeevollautomat"), Rules())


def test_price_band():
    assert reject_reason(item(price=60.0), Rules())
    assert reject_reason(item(price=900.0), Rules())
    assert reject_reason(item(price=None), Rules())


def test_buy_it_now_rejected_when_auction_required():
    assert reject_reason(item(bids=None, is_auction=False), Rules())


def test_apply_counts_reasons():
    kept, rejected = apply(
        [item(), item(item_id="2", title="Apple iPhone 13 Pro"), item(item_id="3", price=10.0)],
        Rules(),
    )
    assert [k.item_id for k in kept] == ["1"]
    assert sum(rejected.values()) == 2


def test_config_extends_builtin_lists():
    rules = load_rules()
    assert "iphone" in rules.saturated          # встроенное
    assert "bitcoin" in rules.saturated         # из exclude.yaml
    assert "ohne akku" in rules.junk


def test_bulky_detection():
    assert is_bulky("Thule Dachbox 460 Liter")
    assert not is_bulky("Zeiss Fernglas 10x42")
