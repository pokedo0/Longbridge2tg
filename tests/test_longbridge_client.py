from decimal import Decimal
from types import SimpleNamespace

from longbridge2tg.longbridge_client import _normalize_positions


def test_normalizes_and_aggregates_positions_across_channels():
    channels = [
        SimpleNamespace(
            positions=[
                SimpleNamespace(
                    symbol="AAPL.US",
                    symbol_name="Apple",
                    quantity=Decimal(10),
                    cost_price=Decimal(100),
                    currency="USD",
                )
            ]
        ),
        SimpleNamespace(
            positions=[
                SimpleNamespace(
                    symbol="AAPL.US",
                    symbol_name="Apple Inc.",
                    quantity=Decimal(5),
                    cost_price=Decimal(200),
                    currency="USD",
                ),
                SimpleNamespace(
                    symbol="700.HK",
                    symbol_name="腾讯控股",
                    quantity=Decimal(0),
                    cost_price=Decimal(350),
                    currency="HKD",
                ),
            ]
        ),
    ]

    rows = _normalize_positions(channels)

    assert len(rows) == 1
    assert rows[0].symbol == "AAPL.US"
    assert rows[0].name == "Apple"
    assert rows[0].quantity == Decimal(15)
    assert rows[0].cost_price == Decimal(2000) / Decimal(15)
    assert rows[0].currency == "USD"


def test_rejects_inconsistent_currency_for_same_symbol():
    channels = [
        SimpleNamespace(
            positions=[
                SimpleNamespace(
                    symbol="AAPL.US", symbol_name="", quantity=Decimal(1), cost_price=Decimal(1), currency="USD"
                )
            ]
        ),
        SimpleNamespace(
            positions=[
                SimpleNamespace(
                    symbol="AAPL.US", symbol_name="", quantity=Decimal(1), cost_price=Decimal(1), currency="HKD"
                )
            ]
        ),
    ]

    try:
        _normalize_positions(channels, target_currency=None)
    except RuntimeError as exc:
        assert "inconsistent currencies" in str(exc)
    else:
        raise AssertionError("expected inconsistent currency to fail")


def test_filters_out_non_target_currency_positions():
    channels = [
        SimpleNamespace(
            positions=[
                SimpleNamespace(
                    symbol="AAPL.US",
                    symbol_name="Apple",
                    quantity=Decimal(10),
                    cost_price=Decimal(150),
                    currency="USD",
                ),
                SimpleNamespace(
                    symbol="700.HK",
                    symbol_name="腾讯控股",
                    quantity=Decimal(100),
                    cost_price=Decimal(380),
                    currency="HKD",
                ),
            ]
        )
    ]

    rows = _normalize_positions(channels, target_currency="USD")
    assert len(rows) == 1
    assert rows[0].symbol == "AAPL.US"
    assert rows[0].currency == "USD"


def test_select_balance_picks_usd_balance():
    from longbridge2tg.longbridge_client import _select_balance

    balances = [
        SimpleNamespace(currency="HKD", total_cash=Decimal("1000"), net_assets=Decimal("50000")),
        SimpleNamespace(currency="USD", total_cash=Decimal("200"), net_assets=Decimal("10000")),
    ]
    summary = _select_balance(balances, [], target_currency="USD")
    assert summary is not None
    assert summary.currency == "USD"
    assert summary.net_assets == Decimal("10000")
    assert summary.total_cash == Decimal("200")


def test_select_balance_fallback_single_balance():
    from longbridge2tg.longbridge_client import _select_balance

    balances = [
        SimpleNamespace(currency="USD", total_cash=Decimal("500"), net_assets=Decimal("20000")),
    ]
    summary = _select_balance(balances, [], target_currency="USD")
    assert summary is not None
    assert summary.currency == "USD"
    assert summary.net_assets == Decimal("20000")


def test_extract_realtime_price_picks_overnight_when_newer():
    from datetime import datetime, timedelta
    from longbridge2tg.longbridge_client import _extract_realtime_price

    now = datetime.now()
    quote = SimpleNamespace(
        symbol="AAPL.US",
        last_done=Decimal("100"),
        timestamp=now - timedelta(hours=8),
        overnight_quote=SimpleNamespace(last_done=Decimal("105"), timestamp=now),
        pre_market_quote=None,
        post_market_quote=None,
    )
    price, session = _extract_realtime_price(quote)
    assert price == Decimal("105")
    assert session == "overnight_quote"


def test_extract_realtime_price_picks_regular_when_overnight_stale():
    from datetime import datetime, timedelta
    from longbridge2tg.longbridge_client import _extract_realtime_price

    now = datetime.now()
    quote = SimpleNamespace(
        symbol="AAPL.US",
        last_done=Decimal("100"),
        timestamp=now,
        overnight_quote=SimpleNamespace(last_done=Decimal("95"), timestamp=now - timedelta(hours=8)),
        pre_market_quote=None,
        post_market_quote=None,
    )
    price, session = _extract_realtime_price(quote)
    assert price == Decimal("100")
    assert session == "regular"


def test_extract_realtime_price_ignores_zero_or_none_last_done():
    from datetime import datetime, timedelta
    from longbridge2tg.longbridge_client import _extract_realtime_price

    now = datetime.now()
    quote = SimpleNamespace(
        symbol="AAPL.US",
        last_done=Decimal("100"),
        timestamp=now - timedelta(hours=8),
        overnight_quote=SimpleNamespace(last_done=Decimal("0"), timestamp=now),
        pre_market_quote=SimpleNamespace(last_done=None, timestamp=now),
        post_market_quote=None,
    )
    price, session = _extract_realtime_price(quote)
    assert price == Decimal("100")
    assert session == "regular"


def test_extract_realtime_price_pre_market_and_post_market():
    from datetime import datetime, timedelta
    from longbridge2tg.longbridge_client import _extract_realtime_price

    now = datetime.now()
    quote = SimpleNamespace(
        symbol="TSLA.US",
        last_done=Decimal("200"),
        timestamp=now - timedelta(hours=4),
        pre_market_quote=SimpleNamespace(last_done=Decimal("205"), timestamp=now),
        post_market_quote=SimpleNamespace(last_done=Decimal("202"), timestamp=now - timedelta(hours=2)),
        overnight_quote=None,
    )
    price, session = _extract_realtime_price(quote)
    assert price == Decimal("205")
    assert session == "pre_market_quote"

