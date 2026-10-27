from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class PositionRow:
    symbol: str
    name: str
    quantity: Decimal
    cost_price: Decimal
    currency: str


@dataclass(frozen=True)
class AccountSummary:
    total_cash: Decimal
    net_assets: Decimal
    currency: str


@dataclass(frozen=True)
class PortfolioSnapshot:
    positions: tuple[PositionRow, ...]
    securities: Mapping[str, str]
    quotes: Mapping[str, Decimal]
    balance: AccountSummary | None
    leverages: Mapping[str, Decimal] = field(default_factory=dict)

