"""Data models used across the system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Token:
    token_id: str
    outcome: str  # "Yes" or "No"
    price: float
    winner: Optional[bool] = None


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    tokens: list[Token] = field(default_factory=list)
    end_date: Optional[str] = None
    active: bool = True
    closed: bool = False
    volume: float = 0.0
    liquidity: float = 0.0
    neg_risk: bool = False
    event_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    @property
    def yes_price(self) -> float:
        for t in self.tokens:
            if t.outcome.lower() == "yes":
                return t.price
        return 0.0

    @property
    def no_price(self) -> float:
        for t in self.tokens:
            if t.outcome.lower() == "no":
                return t.price
        return 0.0

    @property
    def spread(self) -> float:
        return abs(1.0 - (self.yes_price + self.no_price))


@dataclass
class Event:
    event_id: str
    title: str
    slug: str
    markets: list[Market] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    token_id: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 1.0

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def bid_depth(self) -> float:
        return sum(l.price * l.size for l in self.bids)

    @property
    def ask_depth(self) -> float:
        return sum(l.price * l.size for l in self.asks)


@dataclass
class ArbitrageOpportunity:
    opportunity_type: str  # "cross_market", "multi_outcome", "logical_constraint"
    description: str
    markets: list[Market]
    edge_pct: float  # expected edge in percentage
    required_capital: float
    legs: list[dict] = field(default_factory=list)  # {market, side, price, size}
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def expected_profit(self) -> float:
        return self.required_capital * self.edge_pct / 100.0


@dataclass
class PriceHistory:
    token_id: str
    timestamps: list[datetime] = field(default_factory=list)
    prices: list[float] = field(default_factory=list)


@dataclass
class RiskMetrics:
    var_99: float = 0.0
    var_95: float = 0.0
    expected_shortfall: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0
    correlation_concentration: float = 0.0  # how concentrated risk is in top factors
    n_effective_bets: float = 0.0  # effective independent positions after PCA
