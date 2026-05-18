"""Simulate _update_positions() logic to find WHERE the price update chain breaks."""
import asyncio

async def main():
    from src.api.polymarket_client import PolymarketClient
    from src.scanner.market_scanner import MarketScanner

    scanner = MarketScanner()
    
    # Simulate a scan to populate _last_events
    print("Fetching events (same as scanner does)...")
    events = await scanner.client.get_all_active_events(max_pages=5)
    scanner._last_events = events
    
    total_markets = sum(len(e.markets) for e in events)
    print(f"Fetched {len(events)} events, {total_markets} markets")
    
    # Build market_map (same as _update_positions)
    market_map = {}
    for event in events:
        for market in event.markets:
            market_map[market.condition_id] = market
    
    print(f"Market map has {len(market_map)} condition_ids")
    
    # Now simulate some position lookups
    # We need real condition_ids from actual trades. Let's find some multi-outcome events
    # that would generate LP arbitrage opportunities
    test_markets = []
    for event in events:
        if len(event.markets) >= 2:
            for m in event.markets[:2]:
                test_markets.append(m)
            if len(test_markets) >= 4:
                break
    
    print(f"\nTesting with {len(test_markets)} markets:")
    for m in test_markets:
        cid = m.condition_id
        found = cid in market_map
        print(f"\n  Market: {m.question[:50]}")
        print(f"  condition_id: {cid[:40]}...")
        print(f"  In market_map: {found}")
        print(f"  Tokens: {len(m.tokens)}")
        
        for tok in m.tokens:
            print(f"    {tok.outcome}: token_id={tok.token_id[:30] if tok.token_id else 'NONE'}... price={tok.price}")
            if tok.token_id:
                try:
                    mid = await scanner.client.get_midpoint(tok.token_id)
                    print(f"    CLOB midpoint: {mid:.4f} (delta from Gamma: {mid - tok.price:+.4f})")
                except Exception as e:
                    print(f"    CLOB midpoint ERROR: {e}")
    
    # Now check: do the LP arbitrage legs use the SAME condition_ids?
    print("\n\n=== Checking LP arbitrage leg format ===")
    from src.models.arbitrage import find_arbitrage_opportunities
    
    # Pick a multi-outcome event
    for event in events:
        if len(event.markets) >= 3:
            opps = find_arbitrage_opportunities([event])
            if opps:
                opp = opps[0]
                print(f"\nOpportunity: {opp.description[:60]}")
                print(f"Type: {opp.opportunity_type}")
                print(f"Legs: {len(opp.legs)}")
                for leg in opp.legs:
                    leg_market = leg.get("market", "?")
                    leg_side = leg.get("side", "?")
                    leg_price = leg.get("price", 0)
                    in_map = leg_market in market_map
                    print(f"  Leg market_id: {leg_market[:40]}...")
                    print(f"  Side: {leg_side}, Price: {leg_price}")
                    print(f"  In market_map: {in_map}")
                    if in_map:
                        mm = market_map[leg_market]
                        token_side = "YES" if "YES" in leg_side else "NO"
                        for tok in mm.tokens:
                            if tok.outcome.upper() == token_side:
                                print(f"  Token found: {tok.token_id[:30]}... price={tok.price}")
                                break
                        else:
                            print(f"  NO matching token for side {token_side}!")
                    print()
                break
    
    await scanner.client.close()

asyncio.run(main())
