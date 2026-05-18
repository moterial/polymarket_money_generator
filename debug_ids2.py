"""Check full condition_ids — are they truncated or different?"""
import asyncio
import json

async def main():
    from src.api.polymarket_client import PolymarketClient
    
    state = json.load(open("state_v3.json"))
    positions = state.get("positions", [])
    
    client = PolymarketClient()
    events = await client.get_all_active_events(max_pages=1)
    
    market_map = {}
    for e in events:
        for m in e.markets:
            market_map[m.condition_id] = m
    
    for p in positions:
        mid = p["market_id"]
        q = p["market_question"][:60]
        found = mid in market_map
        print(f"Position ID  : {mid}")
        
        # Search by question in market_map
        for cid, m in market_map.items():
            if q[:40] in m.question:
                print(f"Gamma match  : {cid}")
                print(f"Same?        : {cid == mid}")
                break
        print(f"Question     : {q}")
        print()
    
    await client.close()

asyncio.run(main())
