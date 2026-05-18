"""
Simulated Trading Account

Tracks a virtual account with starting capital.
Every decision the system makes affects this balance in real-time.
Records full order history, position tracking, and P&L.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    SELL_YES = "SELL_YES"
    SELL_NO = "SELL_NO"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass
class Order:
    id: str
    timestamp: datetime
    market_id: str
    market_question: str
    side: OrderSide
    price: float
    size: float          # number of contracts
    cost: float          # total USD cost
    status: OrderStatus
    fill_price: Optional[float] = None
    pnl: Optional[float] = None
    reason: str = ""     # why this trade was made

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "market_id": self.market_id,
            "market_question": self.market_question,
            "side": self.side.value,
            "price": round(self.price, 4),
            "size": round(self.size, 2),
            "cost": round(self.cost, 2),
            "status": self.status.value,
            "fill_price": round(self.fill_price, 4) if self.fill_price else None,
            "pnl": round(self.pnl, 2) if self.pnl is not None else None,
            "reason": self.reason,
        }


@dataclass
class Position:
    market_id: str
    market_question: str
    side: str            # "YES" or "NO"
    size: float          # number of contracts
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    opened_at: float = 0.0  # time.time() when position was opened

    @property
    def market_value(self) -> float:
        return self.size * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.size * self.avg_entry_price

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "market_question": self.market_question,
            "side": self.side,
            "size": round(self.size, 2),
            "avg_entry_price": round(self.avg_entry_price, 4),
            "current_price": round(self.current_price, 4),
            "market_value": round(self.market_value, 2),
            "cost_basis": round(self.cost_basis, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "pnl_pct": round(self.unrealized_pnl / self.cost_basis * 100, 2) if self.cost_basis > 0 else 0,
        }


@dataclass
class AccountSnapshot:
    timestamp: datetime
    balance: float
    equity: float
    unrealized_pnl: float
    realized_pnl: float


class SimulatedAccount:
    """
    Virtual trading account starting with a configurable balance.
    Thread-safe for concurrent scanner + UI access.
    """

    def __init__(self, starting_balance: float = 1000.0):
        self._lock = threading.RLock()
        self.starting_balance = starting_balance
        self.cash_balance = starting_balance
        self.realized_pnl = 0.0
        self.total_fees_paid = 0.0

        self.orders: list[Order] = []
        self.positions: dict[str, Position] = {}  # key = market_id + side
        self.equity_history: list[AccountSnapshot] = []
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self._record_snapshot()

    # ── Public API ──

    def place_order(
        self,
        market_id: str,
        market_question: str,
        side: OrderSide,
        price: float,
        size: float,
        reason: str = "",
        fee_rate: float = 0.01,
    ) -> Order:
        """Place a simulated order. Immediately fills at the given price."""
        with self._lock:
            is_buy = side in (OrderSide.BUY_YES, OrderSide.BUY_NO)
            token_side = "YES" if side in (OrderSide.BUY_YES, OrderSide.SELL_YES) else "NO"
            pos_key = f"{market_id}_{token_side}"

            if is_buy:
                cost = price * size
                fee = cost * fee_rate

                # Check if we have enough cash
                if cost + fee > self.cash_balance:
                    max_affordable = self.cash_balance / (price * (1 + fee_rate))
                    if max_affordable < 0.5:
                        order = Order(
                            id=self._gen_id(),
                            timestamp=datetime.now(),
                            market_id=market_id,
                            market_question=market_question,
                            side=side,
                            price=price,
                            size=size,
                            cost=cost,
                            status=OrderStatus.FAILED,
                            reason=f"Insufficient funds (need ${cost + fee:.2f}, have ${self.cash_balance:.2f})",
                        )
                        self.orders.append(order)
                        return order
                    size = max_affordable
                    cost = price * size
                    fee = cost * fee_rate

                # Deduct cash for buy
                self.cash_balance -= (cost + fee)
                self.total_fees_paid += fee
                self.trade_count += 1

                order = Order(
                    id=self._gen_id(),
                    timestamp=datetime.now(),
                    market_id=market_id,
                    market_question=market_question,
                    side=side,
                    price=price,
                    size=size,
                    cost=cost,
                    status=OrderStatus.FILLED,
                    fill_price=price,
                    reason=reason,
                )
                self.orders.append(order)

                # Update or create position
                if pos_key in self.positions:
                    pos = self.positions[pos_key]
                    total_size = pos.size + size
                    pos.avg_entry_price = (pos.avg_entry_price * pos.size + price * size) / total_size
                    pos.size = total_size
                    pos.current_price = price
                else:
                    self.positions[pos_key] = Position(
                        market_id=market_id,
                        market_question=market_question,
                        side=token_side,
                        size=size,
                        avg_entry_price=price,
                        current_price=price,
                        opened_at=time.time(),
                    )

            else:
                # SELL order — close (or reduce) existing position
                if pos_key not in self.positions:
                    order = Order(
                        id=self._gen_id(),
                        timestamp=datetime.now(),
                        market_id=market_id,
                        market_question=market_question,
                        side=side,
                        price=price,
                        size=size,
                        cost=0,
                        status=OrderStatus.FAILED,
                        reason="No position to sell",
                    )
                    self.orders.append(order)
                    return order

                pos = self.positions[pos_key]
                sell_size = min(size, pos.size)
                proceeds = price * sell_size
                fee = proceeds * fee_rate
                pnl = (price - pos.avg_entry_price) * sell_size

                # Credit proceeds minus fee
                self.cash_balance += (proceeds - fee)
                self.total_fees_paid += fee
                self.realized_pnl += pnl
                self.trade_count += 1

                if pnl > 0:
                    self.win_count += 1
                elif pnl < 0:
                    self.loss_count += 1
                # pnl == 0 (breakeven) not counted as win or loss

                order = Order(
                    id=self._gen_id(),
                    timestamp=datetime.now(),
                    market_id=market_id,
                    market_question=market_question,
                    side=side,
                    price=price,
                    size=sell_size,
                    cost=pos.avg_entry_price * sell_size,
                    status=OrderStatus.FILLED,
                    fill_price=price,
                    pnl=pnl,
                    reason=reason,
                )
                self.orders.append(order)

                pos.size -= sell_size
                if pos.size <= 0.01:
                    del self.positions[pos_key]

            self._record_snapshot()
            return order

    def update_position_prices(self, price_updates: dict[str, float]):
        """Update current prices for positions. key = pos_key ({market_id}_{YES/NO})."""
        with self._lock:
            for pos_key, pos in self.positions.items():
                if pos_key in price_updates:
                    new_price = price_updates[pos_key]
                    if new_price > 0:
                        pos.current_price = new_price
                        pos.unrealized_pnl = (pos.current_price - pos.avg_entry_price) * pos.size

    def close_position(self, pos_key: str, current_price: float, reason: str = "Position closed") -> Optional[Order]:
        """Close an existing position at current market price."""
        with self._lock:
            if pos_key not in self.positions:
                return None
            pos = self.positions[pos_key]
            side = OrderSide.SELL_YES if pos.side == "YES" else OrderSide.SELL_NO

        # place_order handles the rest (uses its own lock)
        return self.place_order(
            market_id=pos.market_id,
            market_question=pos.market_question,
            side=side,
            price=current_price,
            size=pos.size,
            reason=reason,
        )

    # ── Getters ──

    @property
    def equity(self) -> float:
        with self._lock:
            positions_value = sum(p.market_value for p in self.positions.values())
            return self.cash_balance + positions_value

    @property
    def total_pnl(self) -> float:
        return self.equity - self.starting_balance

    @property
    def total_pnl_pct(self) -> float:
        return (self.total_pnl / self.starting_balance) * 100 if self.starting_balance > 0 else 0

    @property
    def unrealized_pnl(self) -> float:
        with self._lock:
            return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def win_rate(self) -> float:
        total = self.win_count + self.loss_count
        return (self.win_count / total * 100) if total > 0 else 0

    def get_state(self) -> dict:
        """Full account state for the UI."""
        with self._lock:
            return {
                "balance": round(self.cash_balance, 2),
                "equity": round(self.equity, 2),
                "starting_balance": self.starting_balance,
                "total_pnl": round(self.total_pnl, 2),
                "total_pnl_pct": round(self.total_pnl_pct, 2),
                "realized_pnl": round(self.realized_pnl, 2),
                "unrealized_pnl": round(self.unrealized_pnl, 2),
                "total_fees": round(self.total_fees_paid, 2),
                "trade_count": self.trade_count,
                "win_count": self.win_count,
                "loss_count": self.loss_count,
                "win_rate": round(self.win_rate, 1),
                "positions": [p.to_dict() for p in self.positions.values()],
                "recent_orders": [o.to_dict() for o in reversed(self.orders[-50:])],
                "equity_history": [
                    {"t": s.timestamp.isoformat(), "v": round(s.equity, 2)}
                    for s in self.equity_history[-200:]
                ],
            }

    # ── Private ──

    def _record_snapshot(self):
        self.equity_history.append(AccountSnapshot(
            timestamp=datetime.now(),
            balance=self.cash_balance,
            equity=self.equity,
            unrealized_pnl=self.unrealized_pnl,
            realized_pnl=self.realized_pnl,
        ))

    @staticmethod
    def _gen_id() -> str:
        return uuid.uuid4().hex[:12]
