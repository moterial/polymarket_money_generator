"""
AI Market Analyzer

Uses LLMs to:
1. Detect logical relationships between markets (implication, exclusion, correlation)
2. Analyze whether cross-market pricing is consistent
3. Generate natural-language summaries of arbitrage opportunities
4. Assess news impact on market clusters

This is the "system integration" layer that the articles describe as the
real competitive moat — combining mathematical models with AI reasoning.
"""

from __future__ import annotations

import json
from typing import Optional

from src.utils.data_models import ArbitrageOpportunity, Event, Market
from src.utils.logger import setup_logger

logger = setup_logger("ai.analyzer")


SYSTEM_PROMPT = """You are an expert quantitative analyst specializing in prediction markets.
Your job is to analyze relationships between prediction market contracts and identify
logical inconsistencies in pricing.

Key principles:
1. If event A implies event B, then P(A) <= P(B). Violation = arbitrage.
2. If events are mutually exclusive, sum of P(event_i) <= 1.0.
3. If events are collectively exhaustive, sum of P(event_i) >= 1.0.
4. Related events share common risk factors — price movements should be correlated.

When analyzing markets, consider:
- Logical implication chains (e.g., "win state X by >5%" implies "win state X")
- Temporal relationships (event A must happen before event B)
- Subset relationships (event A is a special case of event B)
- Complementary events that should sum to ~1.0

Output your analysis as structured JSON."""


class AIMarketAnalyzer:
    """Use LLMs to detect logical relationships and pricing inconsistencies."""

    def __init__(self, api_key: str = "", model: str = "gpt-4o", base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise ValueError("LLM API key not configured")
            from openai import OpenAI
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    async def analyze_event_relationships(
        self,
        events: list[Event],
    ) -> list[dict]:
        """
        Use LLM to identify logical relationships between markets.

        Returns list of relationship dicts:
        {
            "type": "implication" | "exclusion" | "complement" | "correlation",
            "market_a": condition_id,
            "market_b": condition_id,
            "description": str,
            "constraint": str,  # e.g., "P(A) <= P(B)"
            "violated": bool,
            "edge_estimate_pct": float,
        }
        """
        if not self.api_key:
            logger.warning("No OpenAI API key — skipping AI analysis")
            return []

        # Prepare market summaries for LLM
        market_summaries = []
        for ev in events[:20]:  # Limit to avoid token overflow
            for m in ev.markets:
                if m.active and not m.closed and m.yes_price > 0:
                    market_summaries.append({
                        "event": ev.title[:100],
                        "question": m.question[:150],
                        "condition_id": m.condition_id,
                        "yes_price": round(m.yes_price, 4),
                        "no_price": round(m.no_price, 4),
                        "tags": m.tags[:5],
                    })

        if len(market_summaries) < 2:
            return []

        prompt = f"""Analyze these prediction market contracts for logical relationships and pricing inconsistencies.

Markets:
{json.dumps(market_summaries, indent=2, ensure_ascii=False)}

For each pair of related markets, determine:
1. The logical relationship (implication, mutual exclusion, complement, correlation)
2. The mathematical constraint this implies (e.g., P(A) <= P(B))
3. Whether current prices violate that constraint
4. Estimated edge if violated (as percentage)

Return a JSON array of relationships found. Only include relationships where you are
reasonably confident in the logical connection. Focus on clear violations.

Response format:
[
  {{
    "type": "implication|exclusion|complement|correlation",
    "market_a_id": "condition_id",
    "market_a_question": "question",
    "market_b_id": "condition_id",
    "market_b_question": "question",
    "constraint": "P(A) <= P(B)",
    "current_prices": "P(A)=0.XX, P(B)=0.YY",
    "violated": true/false,
    "edge_estimate_pct": 0.0,
    "reasoning": "brief explanation"
  }}
]"""

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            result = json.loads(content)

            relationships = result if isinstance(result, list) else result.get("relationships", [])
            logger.info("AI found %d market relationships", len(relationships))
            return relationships

        except Exception as e:
            logger.error("AI analysis failed: %s", e)
            return []

    async def assess_opportunity(
        self,
        opportunity: ArbitrageOpportunity,
    ) -> dict:
        """
        Use LLM to assess whether an arbitrage opportunity is real.

        Returns confidence assessment and risk factors.
        """
        if not self.api_key:
            return {"confidence": opportunity.confidence, "assessment": "AI unavailable"}

        prompt = f"""Assess this prediction market arbitrage opportunity:

Type: {opportunity.opportunity_type}
Description: {opportunity.description}
Edge: {opportunity.edge_pct:.2f}%
Required capital: ${opportunity.required_capital:.2f}

Markets involved:
{json.dumps([{
    "question": m.question[:100],
    "yes_price": m.yes_price,
    "no_price": m.no_price,
    "volume": m.volume,
    "liquidity": m.liquidity,
} for m in opportunity.markets], indent=2, ensure_ascii=False)}

Trade legs:
{json.dumps(opportunity.legs, indent=2, ensure_ascii=False)}

Analyze:
1. Is this a genuine arbitrage or could there be a reason for the pricing discrepancy?
2. What are the risks (liquidity, execution, resolution ambiguity)?
3. Confidence score 0-1 that this is exploitable.

Return JSON:
{{
  "is_genuine": true/false,
  "confidence": 0.0-1.0,
  "risks": ["risk1", "risk2"],
  "recommendation": "execute|monitor|skip",
  "reasoning": "brief explanation"
}}"""

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            logger.error("AI assessment failed: %s", e)
            return {"confidence": opportunity.confidence, "assessment": f"Error: {e}"}

    async def generate_market_brief(
        self,
        events: list[Event],
        opportunities: list[ArbitrageOpportunity],
    ) -> str:
        """Generate a natural-language market briefing."""
        if not self.api_key:
            return self._generate_offline_brief(events, opportunities)

        summary = {
            "total_events": len(events),
            "total_markets": sum(len(e.markets) for e in events),
            "opportunities_found": len(opportunities),
            "top_opportunities": [
                {
                    "type": o.opportunity_type,
                    "edge": f"{o.edge_pct:.2f}%",
                    "description": o.description[:100],
                }
                for o in opportunities[:5]
            ],
        }

        prompt = f"""Generate a concise market briefing for a prediction market trader.

Data:
{json.dumps(summary, indent=2, ensure_ascii=False)}

Write 3-5 paragraphs covering:
1. Market overview (activity level, notable trends)
2. Top arbitrage opportunities found
3. Risk warnings or unusual patterns
4. Actionable recommendations

Keep it professional and data-driven. Use specific numbers."""

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            return response.choices[0].message.content

        except Exception as e:
            logger.error("AI briefing failed: %s", e)
            return self._generate_offline_brief(events, opportunities)

    @staticmethod
    def _generate_offline_brief(
        events: list[Event],
        opportunities: list[ArbitrageOpportunity],
    ) -> str:
        """Generate basic briefing without AI."""
        lines = [
            f"=== Market Brief ===",
            f"Events scanned: {len(events)}",
            f"Markets: {sum(len(e.markets) for e in events)}",
            f"Opportunities found: {len(opportunities)}",
            "",
        ]
        for i, opp in enumerate(opportunities[:10], 1):
            lines.append(f"{i}. [{opp.opportunity_type}] {opp.edge_pct:.2f}% edge")
            lines.append(f"   {opp.description[:100]}")
            lines.append("")

        return "\n".join(lines)
