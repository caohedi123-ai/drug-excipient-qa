import httpx, asyncio, json

async def test():
    print("=== Testing External API Access ===\n")
    
    # Test PubChem
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            r = await c.get('https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/aspirin/cids/JSON')
            print(f"PubChem: {r.status_code}")
            if r.status_code == 200:
                j = r.json()
                cids = j.get('IdentifierList', {}).get('CID', [])
                print(f"  CIDs: {cids}")
            else:
                print(f"  Body: {r.text[:200]}")
    except Exception as e:
        print(f"PubChem ERROR: {e}")

    # Test Wikipedia
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            r = await c.get('https://en.wikipedia.org/w/api.php', params={
                'action': 'query', 'list': 'search',
                'srsearch': 'aspirin molecular weight', 'format': 'json'
            })
            print(f"\nWikipedia: {r.status_code}")
            if r.status_code == 200:
                j = r.json()
                hits = j.get('query', {}).get('search', [])
                print(f"  Results: {len(hits)}")
                for h in hits[:2]:
                    print(f"  - {h.get('title')}")
    except Exception as e:
        print(f"Wikipedia ERROR: {e}")

    # Test DrugBank
    try:
        import urllib.parse
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            r = await c.get(
                'https://go.drugbank.com/unearth/q',
                params={'searcher': 'concepts', 'query': 'aspirin'}
            )
            print(f"\nDrugBank: {r.status_code}")
            if r.status_code == 200:
                print(f"  Body: {r.text[:200]}")
    except Exception as e:
        print(f"DrugBank ERROR: {e}")

    # Test DailyMed
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            r = await c.get(
                'https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json',
                params={'search_text': 'aspirin', 'limit': 3}
            )
            print(f"\nDailyMed: {r.status_code}")
            if r.status_code == 200:
                j = r.json()
                total = j.get('metadata', {}).get('total', 0)
                print(f"  Total results: {total}")
    except Exception as e:
        print(f"DailyMed ERROR: {e}")

    print("\n=== Done ===")

asyncio.run(test())
