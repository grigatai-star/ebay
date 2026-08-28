from ebaytrend.scoring import aggregate_cluster, item_heat, percentile_ranks, score_clusters
from ebaytrend.velocity import ItemMetrics


def make_items(n, *, bids, hours_left, price=200.0, bph=1.0):
    return [
        ItemMetrics(item_id=f"i{k}", price=price, bids=bids, hours_left=hours_left,
                    bids_per_hour_est=bph)
        for k in range(n)
    ]


def test_percentile_ranks_handles_none():
    ranks = percentile_ranks([1, 5, None, 3])
    assert ranks[2] == 0.5
    assert ranks[1] > ranks[0]


def test_bid_rate_counts_only_late_lots():
    items = make_items(4, bids=5, hours_left=3) + make_items(6, bids=0, hours_left=100)
    cluster = aggregate_cluster("k", items)
    assert cluster.n_late == 4
    assert cluster.bid_rate_late == 1.0        # свежие лоты без ставок не портят метрику


def test_hot_cluster_scores_above_cold_one():
    hot = aggregate_cluster("hot", make_items(20, bids=12, hours_left=5, bph=3.0), total_results=5000)
    cold = aggregate_cluster("cold", make_items(20, bids=0, hours_left=5, bph=0.0), total_results=50)
    ranked = score_clusters([cold, hot])
    assert ranked[0].key == "hot"
    assert ranked[0].demand_score > ranked[1].demand_score


def test_bulky_and_thin_samples_are_penalised():
    a = aggregate_cluster("a", make_items(20, bids=5, hours_left=5, bph=2.0))
    b = aggregate_cluster("b", make_items(20, bids=5, hours_left=5, bph=2.0), tags=["bulky"])
    c = aggregate_cluster("c", make_items(3, bids=5, hours_left=5, bph=2.0))
    score_clusters([a, b, c])
    assert b.demand_score < a.demand_score
    assert c.demand_score < a.demand_score


def test_sell_through_from_completed_rows():
    rows = [{"was_sold": 1, "price": 200.0}, {"was_sold": 1, "price": 240.0}, {"was_sold": 0, "price": None}]
    cluster = aggregate_cluster("k", make_items(5, bids=2, hours_left=5), sold_rows=rows)
    assert cluster.sell_through == 0.667
    assert cluster.median_sold_price == 220.0


def test_target_buy_price_uses_sold_median():
    cluster = aggregate_cluster(
        "k", make_items(5, bids=2, hours_left=5), buy_ratio=0.4,
        sold_rows=[{"was_sold": 1, "price": 300.0}],
    )
    assert cluster.target_buy_price == 120.0


def test_heat_discounts_last_hour_sniping():
    sniping = ItemMetrics(item_id="a", bids_per_hour_delta=10.0, hours_left=0.2)
    early = ItemMetrics(item_id="b", bids_per_hour_delta=4.0, hours_left=48)
    assert item_heat(early) > item_heat(sniping)
