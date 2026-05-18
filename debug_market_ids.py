"""Debug market ID matching issue."""
import asyncio
import json

async def main():
    from src.api.polymarket_client import PolymarketClient
    
    state = json.load(open("state_v3.json"))
    positions = state.get("positions", [])
    
    client = PolymarketClient()
    events = await client.get_all_active_events(max_pages=1)
    
    # Build market map
    market_map = {}
    for e in events:
        for m in e.markets:
            market_map[m.condition_id] = m
    
    print(f"Total markets in Gamma: {len(market_map)}")
    print(f"Total positions: {len(positions)}")
    print()
    
    for p in positions:
        mid = p["market_id"]
        q = p["market_question"][:50]
        found = mid in market_map
        print(f"  {'OK' if found else 'MISSING'} | {mid[:40]}...")
        print(f"    Question: {q}")
        if found:
            m = market_map[mid]
            print(f"    Tokens: {len(m.tokens)}")
            for t in m.tokens:
                print(f"      {t.outcome}: token_id={t.token_id[:20] if t.token_id else 'NONE'}... price={t.price}")
        else:
            # Try partial match
            partial = [k for k in market_map if mid[:20] in k]
            if partial:
                print(f"    Partial matches: {partial}")
            else:
                # Search by question
                q_matches = [k for k, m in market_map.items() if q[:30] in m.question]
                if q_matches:
                    print(f"    Question match: {q_matches[0][:40]}...")
                    mm = market_map[q_matches[0]]
                    print(f"    Its condition_id: {mm.condition_id[:40]}...")
                else:
                    print(f"    No match by ID or question!")
    
    await client.close()

asyncio.run(main())
