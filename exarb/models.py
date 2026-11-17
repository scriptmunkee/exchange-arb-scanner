"""Normalised data model shared by every exchange source."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Price:
    """Best price on one side of one selection on one exchange.

    `size` is always the backer's stake in GBP available at `odds`.
    """

    odds: float
    size: float


@dataclass
class Selection:
    key: str  # "home" | "draw" | "away"
    name: str
    back: Price | None = None  # best price we can back at
    lay: Price | None = None  # best price we can lay at


@dataclass
class Market:
    exchange: str
    sport: str  # "football" | "tennis"
    event_id: str
    event_name: str
    home: str
    away: str
    start: datetime
    market_id: str
    selections: dict[str, Selection] = field(default_factory=dict)
    url: str = ""


def prob_to_decimal(bp: int) -> float:
    """Smarkets quotes probability in basis points (5000 = 50% = 2.0)."""
    return round(10000 / bp, 4)
