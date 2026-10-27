from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from longbridge2tg.leveraged_etf import (
    LeveragedETFService,
    parse_leverage,
    parse_leveraged_etf_csv,
)


def test_parse_leverage():
    assert parse_leverage("2x") == Decimal("2.0")
    assert parse_leverage("1.5X") == Decimal("1.5")
    assert parse_leverage("3x") == Decimal("3.0")
    assert parse_leverage("1x") == Decimal("1.0")
    assert parse_leverage("invalid") == Decimal("1.0")
    assert parse_leverage("") == Decimal("1.0")
    assert parse_leverage("-2x") == Decimal("1.0")


def test_parse_leveraged_etf_csv():
    sample_csv = """ticker,underlying_ticker,leverage,direction
TSLL,TSLA,2x,long
TQQQ,QQQ,3x,long
SQQQ,QQQ,3x,short
VAR,AAPL,variable,long
,MSFT,2x,long
INVALID_LEV,NVDA,abc,long
"""
    mapping = parse_leveraged_etf_csv(sample_csv)
    assert mapping["TSLL"] == Decimal("2.0")
    assert mapping["TQQQ"] == Decimal("3.0")
    assert mapping["SQQQ"] == Decimal("3.0")
    assert mapping["INVALID_LEV"] == Decimal("1.0")
    assert "VAR" not in mapping
    assert "" not in mapping


def test_leveraged_etf_service_caching_and_fallback():
    async def _test():
        sample_csv = "ticker,leverage\nTSLL,2x\n"
        service = LeveragedETFService(cache_ttl=100.0)

        # 1. Successful fetch
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = AsyncMock(return_value=sample_csv)
            mock_get.return_value.__aenter__.return_value = mock_resp

            leverages = await service.get_leverages(["TSLL.US", "AAPL.US"])
            assert leverages["TSLL"] == Decimal("2.0")
            assert leverages["TSLL.US"] == Decimal("2.0")
            assert leverages["AAPL.US"] == Decimal("1.0")
            assert service.cache_size == 1
            assert mock_get.call_count == 1

            # 2. Second call should hit cache (no additional HTTP request)
            leverages2 = await service.get_leverages(["TSLL.US"])
            assert leverages2["TSLL.US"] == Decimal("2.0")
            assert mock_get.call_count == 1

        # 3. Force refresh failure should fallback to cached data
        with patch("aiohttp.ClientSession.get", side_effect=RuntimeError("connection failed")):
            leverages3 = await service.get_leverage_map(force_refresh=True)
            assert leverages3["TSLL"] == Decimal("2.0")
            assert service.cache_size == 1

    asyncio.run(_test())
