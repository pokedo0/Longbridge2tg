from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping
from .models import PortfolioSnapshot


logger = logging.getLogger(__name__)

MESSAGE_LENGTH = 30000
_TZ_CN = timezone(timedelta(hours=8))
_PERCENT = Decimal("0.1")
_TABLE_HEADER = "| 名称 | 代码 | 占比 | 状态 |\n|:-----|:-----|-----:|:----:|\n"


@dataclass(frozen=True)
class _DisplayPosition:
    name: str
    code: str
    percentage: Decimal
    market_value: Decimal
    profitable: int


def _resolve_leverage(leverages: Mapping[str, Decimal | float] | None, code: str) -> Decimal:
    if not leverages:
        return Decimal(1)
    val = leverages.get(code)
    if val is None:
        val = leverages.get(f"{code}.US")
    if val is None:
        return Decimal(1)
    try:
        dec = Decimal(str(val))
        return dec if dec > 0 else Decimal(1)
    except Exception:
        return Decimal(1)


def format_portfolio_snapshot(
    snapshot: PortfolioSnapshot,
    reported_at: datetime | None = None,
    max_message_length: int = MESSAGE_LENGTH,
) -> list[str]:
    if snapshot.balance is None:
        raise ValueError("account balance is required to calculate portfolio percentages")
    if snapshot.balance.net_assets <= 0:
        raise ValueError("account net_assets must be positive")

    positions = _display_positions(snapshot)
    total_market_value = sum((position.market_value for position in positions), Decimal(0))
    holding_percentage = _percentage(total_market_value, snapshot.balance.net_assets)
    cash_percentage = _percentage(snapshot.balance.total_cash, snapshot.balance.net_assets)

    gross_exposure = Decimal(0)
    for position in positions:
        lev = _resolve_leverage(snapshot.leverages, position.code)
        gross_exposure += position.market_value * lev

    leverage_percentage = _percentage(gross_exposure, snapshot.balance.net_assets)
    logger.info(
        "calculated portfolio leverage: gross_exposure=%s net_assets=%s leverage=%s",
        gross_exposure,
        snapshot.balance.net_assets,
        _percent_text(leverage_percentage),
    )

    summary = (
        "## 📊 账户仓位\n"
        f"**持仓：{_percent_text(holding_percentage)}**\n"
        f"**现金：{_percent_text(cash_percentage)}**\n"
        f"**总杠杆：{_percent_text(leverage_percentage)}**"
    )
    table_rows = _table_rows(positions)
    return _messages(summary, table_rows, reported_at, max_message_length)


def _display_positions(snapshot: PortfolioSnapshot) -> list[_DisplayPosition]:
    assert snapshot.balance is not None
    rows: list[_DisplayPosition] = []

    for position in snapshot.positions:
        quote = snapshot.quotes.get(position.symbol)
        if quote is None:
            raise ValueError(f"missing latest price for {position.symbol}")
        if quote <= 0:
            raise ValueError(f"invalid latest price for {position.symbol}: {quote}")

        market_value = position.quantity * quote
        static_name = snapshot.securities.get(position.symbol, "")
        name = static_name or position.name or _display_code(position.symbol)
        if position.cost_price > 0:
            status = 1 if quote > position.cost_price else -1 if quote < position.cost_price else 0
        else:
            status = 2
        rows.append(
            _DisplayPosition(
                name=name,
                code=_display_code(position.symbol),
                percentage=_percentage(market_value, snapshot.balance.net_assets),
                market_value=market_value,
                profitable=status,
            )
        )

    rows.sort(key=lambda row: (-row.market_value, row.code))
    return rows


def _table_rows(positions: list[_DisplayPosition]) -> list[str]:
    rendered: list[str] = []
    for position in positions:
        name = _escape_markdown(_fit_visual(position.name, 12))
        percentage = _percent_text(position.percentage)
        status = _escape_markdown(_status_text(position.profitable))
        rendered.append(f"| {name} | {position.code} | {percentage} | {status} |")
    return rendered


def _messages(
    summary: str,
    rows: list[str],
    reported_at: datetime | None,
    max_message_length: int,
) -> list[str]:
    first_prefix = f"{summary}\n\n## 📈 持仓排序\n\n"
    continuation_prefix = "## 📈 持仓排序（续）\n\n"
    timestamp = (reported_at or datetime.now(tz=_TZ_CN)).astimezone(_TZ_CN)
    footer = f"\n时间：{timestamp.strftime('%Y-%m-%d %H:%M')} (UTC+8)"

    messages: list[list[str]] = []
    current_rows: list[str] = []
    current_is_first = True
    for row in rows:
        candidate_length = _message_size(
            first_prefix if current_is_first else continuation_prefix,
            current_rows + [row],
            current_is_first and len(messages) == 0,
        )
        if current_rows and candidate_length > max_message_length:
            messages.append(current_rows)
            current_rows = []
            current_is_first = False
        current_rows.append(row)
    messages.append(current_rows)

    result: list[str] = []
    for index, message_rows in enumerate(messages):
        prefix = first_prefix if index == 0 else continuation_prefix
        body = "\n".join(message_rows)
        message = f"{prefix}{_TABLE_HEADER}{body}"
        if index == 0:
            message += footer
        result.append(message)
    return result


def _message_size(prefix: str, rows: list[str], include_footer: bool) -> int:
    body = _TABLE_HEADER + "\n".join(rows)
    size = len((prefix + body).encode("utf-8"))
    if include_footer:
        size += len("\n时间：2026-08-26 00:00 (UTC+8)".encode("utf-8"))
    return size


def _status_text(status: int) -> str:
    if status == 1:
        return "🟢 盈利"
    if status == -1:
        return "🔴 亏损"
    if status == 2:
        return "⚪ 未知"
    return "⚪ 持平"


def _display_code(symbol: str) -> str:
    code = symbol.strip()
    if code.upper().endswith(".US"):
        code = code[:-3]
    return code


def _percentage(value: Decimal, total: Decimal) -> Decimal:
    if total <= 0:
        raise ValueError(f"invalid percentage denominator: {total}")
    return value * Decimal(100) / total


def _percent_text(value: Decimal) -> str:
    rounded = value.quantize(_PERCENT, rounding=ROUND_HALF_UP)
    return f"{rounded:.1f}%"


def visual_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _fit_visual(text: str, width: int) -> str:
    if visual_width(text) <= width:
        return text

    fitted = ""
    fitted_width = 0
    for char in text:
        char_width = visual_width(char)
        if fitted_width + char_width > width - 1:
            break
        fitted += char
        fitted_width += char_width
    return fitted + "…"


def _escape_markdown(text: str) -> str:
    escaped = text.replace("\\", "\\\\")
    for char in ("|", "*", "_", "[", "]", "`"):
        escaped = escaped.replace(char, f"\\{char}")
    return escaped
