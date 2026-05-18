"""Diagnose WHY money is leaking — check real CLOB prices vs entry prices."""
import asyncio
import json
import sys

async def main():
    from src.api.polymarket_client import PolymarketClient
    
    # Load the last saved state
    try:
        state = json.load(open("state_v3.json"))
    except:
        print("No state_v3.json found")
        return
    
    positions = state.get("positions", [])
    if not positions:
        print("No positions found in state")
        return
    
    client = PolymarketClient()
    
    # Get events to find token_ids
    events = await client.get_all_active_events(max_pages=1)
    market_map = {}
    for e in events:
        for m in e.markets:
            market_map[m.condition_id] = m
    
    print("=" * 80)
    print("  PRICE DIAGNOSTIC: Entry vs Real CLOB midpoint")
    print("=" * 80)
    
    total_pnl_if_real = 0
    total_fees = 0
    
    for p in positions:
        mid = p.get("market_id", "")
        side = p.get("side", "YES")
        entry = p.get("avg_entry_price", 0)
        current = p.get("current_price", 0)
        size = p.get("size", 0)
        q = p.get("market_question", "?")[:50]
        
        # Find token_id
        market = market_map.get(mid)
        real_mid = None
        token_id = None
        if market:
            for tok in market.tokens:
                if tok.outcome.upper() == side:
                    token_id = tok.token_id
                    break
            if token_id:
                try:
                    real_mid = await client.get_midpoint(token_id)
                except Exception as e:
                    real_mid = f"ERROR: {e}"
        
        # Also get the Gamma price for comparison
        gamma_price = None
        if market:
            if side == "YES":
                gamma_price = market.yes_price
            else:
                gamma_price = market.no_price
        
        # Calculate real PnL
        if isinstance(real_mid, float) and real_mid > 0:
            real_pnl = (real_mid - entry) * size
            fee_cost = entry * size * 0.02 + real_mid * size * 0.02  # round-trip
            total_pnl_if_real += real_pnl
            total_fees += fee_cost
            real_str = f"{real_mid:.4f}"
            pnl_str = f"${real_pnl:+.2f}"
        else:
            real_str = str(real_mid) if real_mid else "N/A"
            pnl_str = "?"
        
        print(f"\n  {side} | {q}")
        print(f"    Entry:     {entry:.4f}")
        print(f"    Saved:     {current:.4f} (what engine sees)")
        print(f"    Gamma:     {gamma_price:.4f}" if gamma_price else "    Gamma:     N/A")
        print(f"    CLOB mid:  {real_str} (real orderbook)")
        print(f"    Token ID:  {token_id or 'NOT FOUND'}")
        print(f"    Size:      {size:.1f} contracts")
        print(f"    Real PnL:  {pnl_str}")
    
    print(f"\n{'='*80}")
    print(f"  SUMMARY")
    print(f"  Total unrealized PnL (real CLOB): ${total_pnl_if_real:+.2f}")
    print(f"  Estimated round-trip fees:        ${total_fees:.2f}")
    print(f"  Net after fees:                   ${total_pnl_if_real - total_fees:+.2f}")
    print(f"{'='*80}")
    
    await client.close()

asyncio.run(main())
