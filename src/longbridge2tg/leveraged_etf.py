from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Iterable

import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_LEVERAGED_ETF_CSV_URL = (
    "https://raw.githubusercontent.com/pokedo0/Leveraged-ETF-Data-Scraper/"
    "refs/heads/main/leveraged_etf_filled.csv"
)
DEFAULT_CACHE_TTL_SECONDS = 86400.0  # 24 hours


def parse_leverage(leverage_str: str) -> Decimal:
    """Parse leverage string to Decimal. E.g. '2x' -> Decimal('2.0'), '1.5x' -> Decimal('1.5')."""
    cleaned = leverage_str.strip().lower().replace("x", "")
    try:
        val = Decimal(cleaned)
        if val > 0:
            return val
    except (InvalidOperation, ValueError):
        pass
    return Decimal("1.0")


def parse_leveraged_etf_csv(csv_text: str) -> dict[str, Decimal]:
    """Parse CSV text into a ticker -> leverage mapping. Skip variable leverage ETFs."""
    reader = csv.DictReader(io.StringIO(csv_text))
    mapping: dict[str, Decimal] = {}
    for row in reader:
        ticker = str(row.get("ticker", "")).strip().upper()
        leverage_raw = str(row.get("leverage", "")).strip().lower()

        if not ticker or not leverage_raw:
            continue
        if leverage_raw == "variable":
            continue

        mapping[ticker] = parse_leverage(leverage_raw)
    return mapping


class LeveragedETFService:
    """
    Fetches and caches Leveraged ETF mappings from CSV in memory.
    Safe for concurrent calls in an asyncio event loop.
    """

    def __init__(
        self,
        csv_url: str = DEFAULT_LEVERAGED_ETF_CSV_URL,
        cache_ttl: float = DEFAULT_CACHE_TTL_SECONDS,
        timeout: float = 15.0,
    ) -> None:
        self._csv_url = csv_url
        self._cache_ttl = cache_ttl
        self._timeout = timeout
        self._cache: dict[str, Decimal] = {}
        self._last_fetched: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    async def get_leverage_map(self, force_refresh: bool = False) -> dict[str, Decimal]:
        async with self._lock:
            now = time.monotonic()
            if (
                not force_refresh
                and self._cache
                and (now - self._last_fetched < self._cache_ttl)
            ):
                logger.debug(
                    "using cached leveraged ETF registry (%d records, age=%.1fs)",
                    len(self._cache),
                    now - self._last_fetched,
                )
                return self._cache

            await self._refresh_locked()
            return self._cache

    async def _refresh_locked(self) -> None:
        start_time = time.monotonic()
        logger.info("fetching leveraged ETF data from %s", self._csv_url)
        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self._csv_url) as response:
                    response.raise_for_status()
                    text = await response.text()

            mapping = parse_leveraged_etf_csv(text)
            self._cache = mapping
            self._last_fetched = time.monotonic()
            elapsed = self._last_fetched - start_time
            logger.info(
                "successfully fetched and parsed %d leveraged ETF records (took %.2fs)",
                len(mapping),
                elapsed,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start_time
            logger.error(
                "failed to fetch leveraged ETF data from %s after %.2fs: %s (fallback to %d cached records)",
                self._csv_url,
                elapsed,
                exc,
                len(self._cache),
            )
            if not self._cache:
                logger.warning("leveraged ETF cache is empty, all assets will default to 1.0x")

    async def get_leverages(self, symbols: Iterable[str]) -> dict[str, Decimal]:
        """
        Return leverage multiplier for each symbol in symbols.
        Result dict contains both normalized ticker (e.g. 'TSLL') and original symbol (e.g. 'TSLL.US').
        """
        leverage_map = await self.get_leverage_map()
        result: dict[str, Decimal] = {}
        for symbol in symbols:
            norm = symbol.strip().upper()
            ticker = norm.split(".")[0]
            lev = leverage_map.get(ticker, Decimal("1.0"))
            result[norm] = lev
            result[ticker] = lev
            result[symbol] = lev
        return result
