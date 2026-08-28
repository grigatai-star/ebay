from ebaytrend.velocity import compute_item_metrics, estimate_elapsed_hours


def test_estimate_elapsed_hours_uses_standard_durations():
    assert estimate_elapsed_hours(20) == 4        # суточный аукцион
    assert estimate_elapsed_hours(100) == 20      # пятидневный
    assert estimate_elapsed_hours(200) == 40      # десятидневный
    assert estimate_elapsed_hours(None) is None


def record(obs):
    return {"item_id": "1", "title": "A", "observations": obs}


def test_delta_velocity():
    m = compute_item_metrics(record([
        {"observed_at": "2026-08-28T00:00:00+00:00", "price": 100.0, "bids": 3, "seconds_left": 7200},
        {"observed_at": "2026-08-28T01:00:00+00:00", "price": 140.0, "bids": 9, "seconds_left": 3600},
    ]))
    assert m.bids_delta == 6
    assert m.bids_per_hour_delta == 6.0
    assert m.price_per_hour_delta == 40.0
    assert m.method == "delta"


def test_single_observation_falls_back_to_estimate():
    m = compute_item_metrics(record([
        {"observed_at": "2026-08-28T00:00:00+00:00", "price": 100.0, "bids": 10, "seconds_left": 72000},
    ]))
    assert m.bids_per_hour_delta is None
    assert m.method == "est"
    assert m.bids_per_hour_est == round(10 / estimate_elapsed_hours(20.0), 3)


def test_too_short_gap_is_not_used():
    m = compute_item_metrics(record([
        {"observed_at": "2026-08-28T00:00:00+00:00", "price": 100.0, "bids": 3, "seconds_left": 7200},
        {"observed_at": "2026-08-28T00:05:00+00:00", "price": 100.0, "bids": 3, "seconds_left": 6900},
    ]))
    assert m.bids_per_hour_delta is None
