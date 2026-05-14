"""
Arbitrage Detector

Uses linear programming and logical constraints to find arbitrage opportunities
across Polymarket prediction markets.

Key strategies:
1. Single-event arbitrage: YES + NO prices sum ≠ 1.0
2. Multi-outcome arbitrage: Mutually exclusive outcomes should sum to 1.0
3. Cross-market logical constraints: Related events with implied probability bounds
4. Neg-risk event arbitrage: Multi-outcome events using neg-risk framework

Mathematical foundation:
- LP formulation: minimize cost subject to non-negative payoff in all states
- If optimal cost < 0, an arbitrage exists
- Uses scipy.optimize.linprog (free) or Gurobi (commercial) for solving
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import linprog

from src.utils.data_models import ArbitrageOpportunity, Event, Market
from src.utils.logger import setup_logger

logger = setup_logger("models.arbitrage")


class ArbitrageDetector:
    """Detect arbitrage opportunities using LP-based constraint scanning."""

    def __init__(self, min_edge_pct: float = 1.0, min_liquidity: float = 500.0):
        self.min_edge_pct = min_edge_pct
        self.min_liquidity = min_liquidity

    def scan_all(self, events: list[Event]) -> list[ArbitrageOpportunity]:
        """Run all arbitrage detection strategies."""
        opportunities: list[ArbitrageOpportunity] = []

        # 1. Single-market spread arbitrage
        for ev in events:
            for m in ev.markets:
                opp = self._check_single_market(m)
                if opp:
                    opportunities.append(opp)

        # 2. Multi-outcome event arbitrage (neg-risk / mutually exclusive)
        for ev in events:
            if len(ev.markets) >= 2:
                opps = self._check_multi_outcome_event(ev)
                opportunities.extend(opps)

        # 3. Cross-event logical constraint arbitrage (disabled — too many false
        #    positives without NLP to verify logical relationships between markets)
        # cross_opps = self._check_cross_event_constraints(events)
        # opportunities.extend(cross_opps)

        # Filter by minimum edge
        opportunities = [
            o for o in opportunities
            if o.edge_pct >= self.min_edge_pct
        ]

        opportunities.sort(key=lambda x: x.edge_pct, reverse=True)
        logger.info("Found %d arbitrage opportunities", len(opportunities))
        return opportunities

    def _check_single_market(self, market: Market) -> Optional[ArbitrageOpportunity]:
        """
        Check if YES + NO prices deviate from 1.0.

        If YES_ask + NO_ask < 1.0 → buy both, guaranteed profit
        If YES_bid + NO_bid > 1.0 → sell both, guaranteed profit
        """
        yes_price = market.yes_price
        no_price = market.no_price

        if yes_price <= 0 or no_price <= 0:
            return None

        total = yes_price + no_price

        # Buy-both arbitrage: total cost < 1.0
        if total < 1.0:
            edge = (1.0 - total) / total * 100
            if edge >= self.min_edge_pct:
                return ArbitrageOpportunity(
                    opportunity_type="single_market_buy",
                    description=(
                        f"Buy YES@{yes_price:.4f} + NO@{no_price:.4f} = {total:.4f} < 1.0 "
                        f"on '{market.question[:80]}'"
                    ),
                    markets=[market],
                    edge_pct=edge,
                    required_capital=total * 100,  # $100 notional
                    legs=[
                        {"market": market.condition_id, "side": "BUY_YES", "price": yes_price},
                        {"market": market.condition_id, "side": "BUY_NO", "price": no_price},
                    ],
                    confidence=0.95,
                )

        # Sell-both arbitrage: total > 1.0
        if total > 1.0:
            edge = (total - 1.0) / 1.0 * 100
            if edge >= self.min_edge_pct:
                return ArbitrageOpportunity(
                    opportunity_type="single_market_sell",
                    description=(
                        f"Sell YES@{yes_price:.4f} + NO@{no_price:.4f} = {total:.4f} > 1.0 "
                        f"on '{market.question[:80]}'"
                    ),
                    markets=[market],
                    edge_pct=edge,
                    required_capital=100.0,
                    legs=[
                        {"market": market.condition_id, "side": "SELL_YES", "price": yes_price},
                        {"market": market.condition_id, "side": "SELL_NO", "price": no_price},
                    ],
                    confidence=0.95,
                )

        return None

    def _check_multi_outcome_event(self, event: Event) -> list[ArbitrageOpportunity]:
        """
        For multi-outcome events (e.g., "Who will win the election?"),
        the sum of YES prices for all outcomes should equal 1.0.

        If sum < 1.0 → buy all YES tokens
        If sum > 1.0 → buy all NO tokens (in neg-risk framework)

        This uses LP formulation:
            minimize c'x subject to Ax >= 0, x >= 0
        where x = position sizes, A = payoff matrix, c = cost vector
        """
        opportunities: list[ArbitrageOpportunity] = []
        markets = [m for m in event.markets if m.active and not m.closed]

        if len(markets) < 2:
            return opportunities

        # Collect YES prices — skip markets without real prices
        yes_prices = [m.yes_price for m in markets]
        no_prices = [m.no_price for m in markets]

        if any(p <= 0 for p in yes_prices):
            return opportunities

        # Require all markets to have meaningful prices (not just dust)
        if sum(1 for p in yes_prices if p > 0.001) < len(markets):
            return opportunities

        # ── Strategy 1: Buy all YES (overround check) ──
        total_yes = sum(yes_prices)

        # Require reasonable total — if sum is very low, prices are likely stale/missing
        if 0.5 < total_yes < 1.0:
            edge = (1.0 - total_yes) / total_yes * 100
            if edge >= self.min_edge_pct and edge < 50:
                legs = [
                    {"market": m.condition_id, "side": "BUY_YES", "price": p,
                     "question": m.question[:60]}
                    for m, p in zip(markets, yes_prices)
                ]
                opportunities.append(ArbitrageOpportunity(
                    opportunity_type="multi_outcome_buy_all_yes",
                    description=(
                        f"Event '{event.title[:60]}': sum(YES)={total_yes:.4f} < 1.0, "
                        f"buy all YES for {edge:.2f}% edge"
                    ),
                    markets=markets,
                    edge_pct=edge,
                    required_capital=total_yes * 100,
                    legs=legs,
                    confidence=0.90,
                ))

        # ── Strategy 2: LP-based optimal arbitrage ──
        lp_opp = self._solve_lp_arbitrage(event, markets)
        if lp_opp:
            opportunities.append(lp_opp)

        return opportunities

    def _solve_lp_arbitrage(
        self,
        event: Event,
        markets: list[Market],
    ) -> Optional[ArbitrageOpportunity]:
        """
        Solve LP to find optimal arbitrage portfolio.

        For N mutually exclusive outcomes:
        - States of the world: outcome_1, outcome_2, ..., outcome_N
        - For each market i, we can buy YES_i or NO_i
        - Decision variables: x = [buy_yes_1, buy_no_1, buy_yes_2, buy_no_2, ...]

        Cost vector: c[2i] = yes_price_i, c[2i+1] = no_price_i
        Payoff in state j:
            - YES_i pays 1 if i==j, 0 otherwise
            - NO_i pays 1 if i!=j, 0 otherwise

        Minimize cost subject to: payoff >= 0 in all states
        If optimal < 0, arbitrage exists.
        """
        n = len(markets)
        if n < 2 or n > 50:  # Cap to keep LP manageable
            return None

        # Skip if any market has zero/invalid prices
        if any(m.yes_price <= 0.001 or m.no_price <= 0.001 for m in markets):
            return None

        # 2N decision variables: [buy_yes_0, buy_no_0, buy_yes_1, buy_no_1, ...]
        num_vars = 2 * n

        # Cost vector
        c = np.zeros(num_vars)
        for i, m in enumerate(markets):
            c[2 * i] = m.yes_price      # cost of buying YES_i
            c[2 * i + 1] = m.no_price   # cost of buying NO_i

        # Payoff constraints: -payoff <= 0 (i.e., payoff >= 0)
        # For each state j (outcome j wins):
        A_ub = np.zeros((n, num_vars))
        b_ub = np.zeros(n)

        for j in range(n):  # state j: outcome j wins
            for i in range(n):
                # YES_i pays 1 if i == j
                A_ub[j, 2 * i] = -1.0 if i == j else 0.0
                # NO_i pays 1 if i != j
                A_ub[j, 2 * i + 1] = 0.0 if i == j else -1.0

        # We need the total payoff minus cost to be non-negative
        # payoff_j - cost >= 0 for all j
        # But we separate: we minimize cost, subject to payoff >= 1 in all states
        # (normalize so that guaranteed payoff is at least $1)
        A_ub_full = A_ub
        b_ub_full = -np.ones(n)  # payoff >= 1 in each state

        # Bounds: all positions >= 0
        bounds = [(0, None)] * num_vars

        try:
            result = linprog(
                c, A_ub=A_ub_full, b_ub=b_ub_full,
                bounds=bounds, method="highs",
            )

            if result.success and result.fun < 1.0:
                # Cost < 1.0 to guarantee payoff >= 1.0 → arbitrage!
                edge = (1.0 - result.fun) / result.fun * 100
                # Skip unrealistic edges (usually stale/missing prices)
                if edge >= self.min_edge_pct and edge < 50 and result.fun > 0.5:
                    legs = []
                    for i, m in enumerate(markets):
                        if result.x[2 * i] > 1e-6:
                            legs.append({
                                "market": m.condition_id,
                                "side": "BUY_YES",
                                "size": float(result.x[2 * i]),
                                "price": m.yes_price,
                                "question": m.question[:60],
                            })
                        if result.x[2 * i + 1] > 1e-6:
                            legs.append({
                                "market": m.condition_id,
                                "side": "BUY_NO",
                                "size": float(result.x[2 * i + 1]),
                                "price": m.no_price,
                                "question": m.question[:60],
                            })

                    return ArbitrageOpportunity(
                        opportunity_type="lp_optimal",
                        description=(
                            f"LP arbitrage on '{event.title[:60]}': "
                            f"cost={result.fun:.4f} for guaranteed $1 payoff "
                            f"({edge:.2f}% edge, {len(legs)} legs)"
                        ),
                        markets=markets,
                        edge_pct=edge,
                        required_capital=result.fun * 100,
                        legs=legs,
                        confidence=0.85,
                    )
        except Exception as e:
            logger.debug("LP solver failed for '%s': %s", event.title[:40], e)

        return None

    def _check_cross_event_constraints(
        self,
        events: list[Event],
    ) -> list[ArbitrageOpportunity]:
        """
        Find cross-event logical constraints.

        Example: "Will Trump win PA?" and "Will GOP win PA by >5%?"
        The second implies the first, so P(GOP >5%) <= P(Trump wins PA).

        We group events by tags and look for implication relationships
        where the pricing violates logical bounds.
        """
        opportunities: list[ArbitrageOpportunity] = []

        # Group markets by tag for related-market scanning
        tag_groups: dict[str, list[Market]] = {}
        for ev in events:
            for m in ev.markets:
                if not m.active or m.closed:
                    continue
                for tag in m.tags:
                    tag_groups.setdefault(tag, []).append(m)

        # Within each tag group, check for over-/under-pricing
        for tag, markets in tag_groups.items():
            if len(markets) < 2 or len(markets) > 100:
                continue

            # Simple constraint: sum of YES prices for related markets
            # should be bounded by logical relationships
            yes_prices = [m.yes_price for m in markets if m.yes_price > 0]
            if not yes_prices:
                continue

            # Check if independent sub-events sum exceeds their logical maximum
            total = sum(yes_prices)
            n = len(yes_prices)

            # For n independent binary events, the expected number of YES
            # outcomes should be reasonable. If total > n, something is wrong.
            # More precisely: for mutually exclusive events, sum should be <= 1
            # We flag when the sum looks anomalous.

            # Pairwise check: for any two markets in the same tag group,
            # if one logically implies the other, check consistency
            for m1, m2 in itertools.combinations(markets[:20], 2):
                opp = self._check_implication_pair(m1, m2)
                if opp:
                    opportunities.append(opp)

        return opportunities

    def _check_implication_pair(
        self,
        m1: Market,
        m2: Market,
    ) -> Optional[ArbitrageOpportunity]:
        """
        Check if two related markets have inconsistent pricing.

        If market A ⊂ market B (A implies B), then P(A) <= P(B).
        Violation: P(A) > P(B) → sell A, buy B.

        Also checks complementary relationships:
        If A and B are complementary, P(A) + P(B) should ~ 1.0
        """
        p1 = m1.yes_price
        p2 = m2.yes_price

        if p1 <= 0 or p2 <= 0:
            return None

        # Sum check for related binary events that look complementary
        total = p1 + p2
        if abs(total - 1.0) > 0.05:
            # They might not be complementary. Check if over-priced pair
            # (both too high = market thinks both likely but they may be exclusive)
            if total > 1.0 + self.min_edge_pct / 100:
                edge = (total - 1.0) * 100
                if edge >= self.min_edge_pct:
                    return ArbitrageOpportunity(
                        opportunity_type="cross_market_overpriced",
                        description=(
                            f"Related pair overpriced: "
                            f"'{m1.question[:40]}' YES={p1:.3f} + "
                            f"'{m2.question[:40]}' YES={p2:.3f} = {total:.3f} > 1.0"
                        ),
                        markets=[m1, m2],
                        edge_pct=edge,
                        required_capital=200.0,
                        legs=[
                            {"market": m1.condition_id, "side": "BUY_NO", "price": m1.no_price},
                            {"market": m2.condition_id, "side": "BUY_NO", "price": m2.no_price},
                        ],
                        confidence=0.60,  # Lower confidence — requires AI verification
                    )

        return None

    # ── Utility: Exhaustive state-space analysis ──

    @staticmethod
    def compute_state_space_arbitrage(
        markets: list[Market],
        max_states: int = 10000,
    ) -> Optional[dict]:
        """
        For small sets of related markets, enumerate all possible outcome
        combinations and check if any portfolio guarantees profit.

        For N binary markets, there are 2^N states.
        Practical for N <= 13 (~8192 states).

        Returns dict with edge info if arbitrage found.
        """
        n = len(markets)
        if n > 13:  # 2^13 = 8192
            return None

        num_states = 2 ** n

        # Payoff matrix: rows = states, cols = 2*n (buy_yes_i, buy_no_i)
        payoff = np.zeros((num_states, 2 * n))
        cost = np.zeros(2 * n)

        for i, m in enumerate(markets):
            cost[2 * i] = m.yes_price
            cost[2 * i + 1] = m.no_price

        for state in range(num_states):
            for i in range(n):
                outcome_i = (state >> i) & 1  # 1 = YES wins, 0 = NO wins
                payoff[state, 2 * i] = 1.0 if outcome_i == 1 else 0.0
                payoff[state, 2 * i + 1] = 1.0 if outcome_i == 0 else 0.0

        # LP: minimize cost'x subject to payoff*x >= 1 for all states
        A_ub = -payoff
        b_ub = -np.ones(num_states)

        try:
            result = linprog(
                cost, A_ub=A_ub, b_ub=b_ub,
                bounds=[(0, None)] * (2 * n),
                method="highs",
            )
            if result.success and result.fun < 1.0:
                edge = (1.0 - result.fun) / result.fun * 100
                return {
                    "edge_pct": edge,
                    "cost": result.fun,
                    "positions": result.x.tolist(),
                    "n_states": num_states,
                }
        except Exception:
            pass

        return None
