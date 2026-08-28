from ebaytrend.report import _fmt, _hours_label, render_table


def test_fmt_keeps_significant_zeros():
    assert _fmt(150.0, 0) == "150"        # регрессия: было "15"
    assert _fmt(80.0, 0) == "80"
    assert _fmt(1.50, 2) == "1.5"
    assert _fmt(0.0, 0) == "0"
    assert _fmt(None) == "—"


def test_hours_label():
    assert _hours_label(0.5) == "30м"
    assert _hours_label(6) == "6.0ч"
    assert _hours_label(72) == "3.0д"
    assert _hours_label(None) == "—"


def test_render_table_markdown():
    out = render_table(["a", "b"], [["1", "2"]], markdown=True)
    assert out.splitlines()[0].startswith("| a")
    assert set(out.splitlines()[1]) <= {"|", "-"}


def test_render_table_empty():
    assert render_table(["a"], []) == "(пусто)"
