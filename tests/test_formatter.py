from decimal import Decimal

from longbridge2tg.formatter import format_portfolio_snapshot, visual_width
from longbridge2tg.models import AccountSummary, PortfolioSnapshot, PositionRow


def snapshot(
    positions: tuple[PositionRow, ...],
    names: dict[str, str] | None = None,
    quotes: dict[str, Decimal] | None = None,
) -> PortfolioSnapshot:
    default_quotes = {
        position.symbol: Decimal("100") for position in positions
    }
    return PortfolioSnapshot(
        positions=positions,
        securities=names or {},
        quotes=default_quotes if quotes is None else quotes,
        balance=AccountSummary(
            total_cash=Decimal("207000"),
            net_assets=Decimal("1000000"),
            currency="USD",
        ),
    )


def test_formats_aligned_portfolio_with_chinese_names_and_profit_status():
    positions = (
        PositionRow("AMD.US", "AMD", Decimal(1000), Decimal(300), "USD"),
        PositionRow("TSLA.US", "", Decimal(1000), Decimal(270), "USD"),
        PositionRow("COIN.US", "Coinbase", Decimal(100), Decimal(70), "USD"),
    )
    names = {
        "AMD.US": "超威半导体",
        "TSLA.US": "特斯拉",
        "COIN.US": "Coinbase",
    }
    quotes = {
        "AMD.US": Decimal(319),
        "TSLA.US": Decimal(260),
        "COIN.US": Decimal(60),
    }

    messages = format_portfolio_snapshot(snapshot(positions, names, quotes))

    assert len(messages) == 1
    assert "## 📊 账户仓位" in messages[0]
    assert "**持仓：58.5%**" in messages[0]
    assert "**现金：20.7%**" in messages[0]
    expected_table = (
        "| 名称 | 代码 | 占比 | 状态 |\n"
        "|:-----|:-----|-----:|:----:|\n"
        "| 超威半导体 | AMD | 31.9% | 🟢 盈利 |\n"
        "| 特斯拉 | TSLA | 26.0% | 🔴 亏损 |\n"
        "| Coinbase | COIN | 0.6% | 🔴 亏损 |"
    )
    assert expected_table in messages[0]
    assert messages[0].index("31.9%") < messages[0].index("26.0%")
    assert messages[0].index("26.0%") < messages[0].index("| Coinbase")


def test_removes_us_suffix_and_escapes_dynamic_text():
    positions = (
        PositionRow("AAPL.US", "Apple", Decimal(10), Decimal(90), "USD"),
    )
    names = {"AAPL.US": "<Apple & Co>"}

    messages = format_portfolio_snapshot(snapshot(positions, names))

    assert "AAPL" in messages[0]
    assert ".US" not in messages[0]
    assert "<Apple & Co>" in messages[0]
    assert "&lt;" not in messages[0]


def test_empty_positions_show_all_cash():
    messages = format_portfolio_snapshot(
        PortfolioSnapshot(
            positions=(),
            securities={},
            quotes={},
            balance=AccountSummary(Decimal("100"), Decimal("100"), "USD"),
        )
    )

    assert "**持仓：0.0%**" in messages[0]
    assert "**现金：100.0%**" in messages[0]
    assert messages[0].count("| 名称 | 代码 | 占比 | 状态 |") == 1


def test_missing_quote_fails_instead_of_making_numbers_up():
    positions = (PositionRow("AAPL.US", "Apple", Decimal(1), Decimal(1), "USD"),)
    report = snapshot(positions, quotes={})

    try:
        format_portfolio_snapshot(report)
    except ValueError as exc:
        assert "missing latest price" in str(exc)
    else:
        raise AssertionError("expected missing quote to fail")


def test_long_report_keeps_complete_markdown_table_in_each_chunk():
    positions = tuple(
        PositionRow(f"STOCK{i}.US", f"Very Long Test Company {i}", Decimal(i + 1), Decimal(50), "USD")
        for i in range(30)
    )

    messages = format_portfolio_snapshot(snapshot(positions), max_message_length=1200)

    assert len(messages) > 1
    for message in messages:
        assert message.count("| 名称 | 代码 | 占比 | 状态 |") == 1
        assert len(message.encode("utf-8")) <= 1200
    joined = "\n".join(messages)
    for i in range(30):
        assert f"STOCK{i}" in joined


def test_visual_width_pads_cjk_and_latin_consistently():
    assert visual_width("特斯拉") == 6
    assert visual_width("TSLA") == 4
