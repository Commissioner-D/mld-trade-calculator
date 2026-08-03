import json
import os
import urllib.request

url = "https://www.fleaflicker.com/api/FetchLeagueRosters?sport=NFL&league_id=294292"
req = urllib.request.Request(url, headers={"User-Agent": "mld-trade-calculator/1.0"})
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read())

rosters = data.get("rosters", [])
first_players = rosters[0].get("players", [])

os.makedirs("data", exist_ok=True)
with open("data/roster_entry_dump_test.json", "w", encoding="utf-8") as f:
    json.dump({
        "top_level_keys": list(first_players[0].keys()),
        "full_entry": first_players[0],
        "entry_2": first_players[1] if len(first_players) > 1 else None,
    }, f, indent=2)
print("Top-Level-Keys:", list(first_players[0].keys()))
