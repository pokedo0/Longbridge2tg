from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from .config import LongbridgeConfig
from .leveraged_etf import LeveragedETFService
from .models import AccountSummary, PortfolioSnapshot, PositionRow


logger = logging.getLogger(__name__)
_QUOTE_BATCH_SIZE = 50


class PortfolioClient(Protocol):
    async def get_portfolio_snapshot(self) -> PortfolioSnapshot: ...


class LongbridgePositionsClient:
    """Adapter around the official SDK's read-only portfolio APIs."""

    def __init__(
        self,
        config: LongbridgeConfig,
        etf_service: LeveragedETFService | None = None,
    ) -> None:
        self._config = config
        self._etf_service = etf_service or LeveragedETFService()
        self._context: object | None = None
        self._quote_context: object | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._start_lock:
            if self._context is not None:
                return

            from longbridge.openapi import AsyncQuoteContext, AsyncTradeContext, Config, Language

            sdk_config = Config.from_apikey(
                self._config.app_key,
                self._config.app_secret,
                self._config.access_token,
                language=Language.ZH_CN,
                enable_overnight=True,
            )
            loop = asyncio.get_running_loop()
            self._context = AsyncTradeContext.create(sdk_config, loop_=loop)
            self._quote_context = AsyncQuoteContext.create(sdk_config, loop_=loop)
            logger.info("initialized Longbridge trade and quote contexts (enable_overnight=True)")

    async def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        await self.start()
        assert self._context is not None
        assert self._quote_context is not None

        logger.info("fetching stock positions")
        response = await self._context.stock_positions()  # type: ignore[attr-defined]
        raw_count = sum(len(channel.positions) for channel in response.channels)
        positions = _normalize_positions(response.channels, target_currency="USD")
        logger.info(
            "fetched stock positions: channels=%d raw_positions=%d active_usd_positions=%d",
            len(response.channels),
            raw_count,
            len(positions),
        )

        symbols = sorted({position.symbol for position in positions})
        static_names, quotes = await self._fetch_security_details(symbols)

        logger.info("fetching account balance for USD")
        balances = await self._context.account_balance(currency="USD")  # type: ignore[attr-defined]
        logger.info("fetched account balance: entries=%d", len(balances))
        balance = _select_balance(balances, positions, target_currency="USD")

        logger.info("resolving leverages for %d symbols", len(symbols))
        leverages = await self._etf_service.get_leverages(symbols)
        leveraged_items = {s: lev for s, lev in leverages.items() if lev != Decimal(1) and "." in s}
        if leveraged_items:
            logger.info("identified leveraged ETF positions: %s", leveraged_items)
        else:
            logger.info("no leveraged ETF positions found among current holdings")

        return PortfolioSnapshot(
            positions=tuple(positions),
            securities=static_names,
            quotes=quotes,
            balance=balance,
            leverages=leverages,
        )

    async def _fetch_security_details(
        self, symbols: list[str]
    ) -> tuple[dict[str, str], dict[str, Decimal]]:
        if not symbols:
            return {}, {}

        logger.info("fetching security details: symbols=%d", len(symbols))
        static_names: dict[str, str] = {}
        quotes: dict[str, Decimal] = {}
        session_counts: dict[str, int] = {}

        for offset in range(0, len(symbols), _QUOTE_BATCH_SIZE):
            batch = symbols[offset : offset + _QUOTE_BATCH_SIZE]
            static_response, quote_response = await asyncio.gather(
                self._quote_context.static_info(batch),  # type: ignore[attr-defined]
                self._quote_context.quote(batch),  # type: ignore[attr-defined]
            )
            for item in static_response:
                static_names[str(item.symbol)] = str(item.name_cn or item.name_en or "")
            for item in quote_response:
                symbol = str(item.symbol)
                price, session_name = _extract_realtime_price(item)
                quotes[symbol] = price
                session_counts[session_name] = session_counts.get(session_name, 0) + 1

        missing_static = {symbol for symbol in symbols if symbol not in static_names}
        missing_quotes = {symbol for symbol in symbols if symbol not in quotes}
        if missing_quotes:
            raise RuntimeError(
                "Longbridge returned incomplete security details "
                f"(missing quotes={sorted(missing_quotes)})"
            )
        if missing_static:
            logger.warning(
                "security static names unavailable, will use position names: %s",
                ", ".join(sorted(missing_static)),
            )

        logger.info(
            "resolved realtime quotes for %d symbols (session breakdown: %s)",
            len(quotes),
            ", ".join(f"{k}={v}" for k, v in sorted(session_counts.items())),
        )
        return static_names, quotes


def _timestamp_to_epoch(ts: object) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        return ts.timestamp()
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _extract_realtime_price(quote_item: object) -> tuple[Decimal, str]:
    """
    Extract the most recent traded price across regular, pre-market,
    post-market, and overnight sessions.

    Returns (price, session_name).
    """
    symbol = str(getattr(quote_item, "symbol", ""))
    candidates: list[tuple[float, int, Decimal, str]] = []

    last_done = getattr(quote_item, "last_done", None)
    if last_done is not None:
        try:
            val = _decimal(last_done)
            if val > 0:
                ts = _timestamp_to_epoch(getattr(quote_item, "timestamp", None))
                candidates.append((ts, 0, val, "regular"))
        except (ValueError, TypeError):
            pass

    session_defs = (
        ("pre_market_quote", 1),
        ("post_market_quote", 2),
        ("overnight_quote", 3),
    )
    for attr_name, priority in session_defs:
        sub_quote = getattr(quote_item, attr_name, None)
        if sub_quote is None:
            continue
        sub_last = getattr(sub_quote, "last_done", None)
        if sub_last is None:
            continue
        try:
            sub_val = _decimal(sub_last)
            if sub_val > 0:
                sub_ts = _timestamp_to_epoch(getattr(sub_quote, "timestamp", None))
                candidates.append((sub_ts, priority, sub_val, attr_name))
        except (ValueError, TypeError):
            pass

    if not candidates:
        fallback = _decimal(last_done) if last_done is not None else Decimal(0)
        return fallback, "regular"

    candidates.sort(key=lambda item: (item[0], item[1]))
    selected_ts, _, selected_price, selected_session = candidates[-1]

    if selected_session != "regular":
        logger.debug(
            "symbol %s selected %s price %s (ts=%s) over regular last_done %s",
            symbol,
            selected_session,
            selected_price,
            selected_ts,
            last_done,
        )

    return selected_price, selected_session


def _normalize_positions(
    channels: list[object],
    target_currency: str | None = "USD",
) -> list[PositionRow]:
    aggregated: dict[str, dict[str, Decimal | str]] = {}

    for channel in channels:
        for position in channel.positions:
            symbol = str(position.symbol)
            quantity = _decimal(position.quantity)
            if quantity == 0:
                continue

            currency = str(position.currency or "").upper()
            if target_currency is not None and currency != target_currency.upper():
                logger.info(
                    "ignoring non-%s position: symbol=%s currency=%s quantity=%s",
                    target_currency,
                    symbol,
                    currency,
                    quantity,
                )
                continue

            existing = aggregated.get(symbol)
            if existing is None:
                aggregated[symbol] = {
                    "name": str(position.symbol_name or ""),
                    "quantity": quantity,
                    "cost_basis": quantity * _decimal(position.cost_price),
                    "currency": currency,
                }
                continue

            if str(existing["currency"]) != currency:
                raise RuntimeError(
                    f"position {symbol} has inconsistent currencies: "
                    f"{existing['currency']} and {currency}"
                )
            existing["quantity"] = Decimal(str(existing["quantity"])) + quantity
            existing["cost_basis"] = Decimal(str(existing["cost_basis"])) + (
                quantity * _decimal(position.cost_price)
            )
            existing["name"] = str(existing["name"]) or str(position.symbol_name or "")

    rows: list[PositionRow] = []
    for symbol in sorted(aggregated):
        item = aggregated[symbol]
        quantity = Decimal(str(item["quantity"]))
        cost_basis = Decimal(str(item["cost_basis"]))
        rows.append(
            PositionRow(
                symbol=symbol,
                name=str(item["name"]),
                quantity=quantity,
                cost_price=cost_basis / quantity if cost_basis > 0 else Decimal(0),
                currency=str(item["currency"]),
            )
        )
    return rows


def _select_balance(
    balances: list[object],
    positions: list[object],
    target_currency: str = "USD",
) -> AccountSummary | None:
    if not balances:
        raise RuntimeError(f"no account balance returned from Longbridge API for {target_currency}")

    normalized_target = target_currency.upper()
    matches = [
        balance
        for balance in balances
        if str(getattr(balance, "currency", "")).upper() == normalized_target
    ]
    if len(matches) == 1:
        return _account_summary(matches[0])

    if len(balances) == 1:
        actual_currency = str(getattr(balances[0], "currency", "")).upper()
        logger.warning(
            "no exact %s balance match; using single returned balance (currency=%s)",
            normalized_target,
            actual_currency,
        )
        return _account_summary(balances[0])

    raise RuntimeError(
        f"expected exactly one {normalized_target} account balance, got {len(matches)} matches from {len(balances)} entries"
    )


def _account_summary(balance: object) -> AccountSummary:
    total_cash = _decimal(getattr(balance, "total_cash"))
    net_assets = _decimal(getattr(balance, "net_assets"))
    currency = str(getattr(balance, "currency", "")).upper()
    if net_assets <= 0:
        raise RuntimeError(f"invalid account net_assets for {currency}: {net_assets}")
    if total_cash < 0:
        raise RuntimeError(f"invalid account total_cash for {currency}: {total_cash}")
    logger.info(
        "selected %s account balance: net_assets=%s total_cash=%s",
        currency,
        net_assets,
        total_cash,
    )
    return AccountSummary(total_cash=total_cash, net_assets=net_assets, currency=currency)


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
