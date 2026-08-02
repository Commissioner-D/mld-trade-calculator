"""
Laedt die komplette Fleaflicker-Spielerliste (FetchPlayerListing, paginiert)
und speichert Fleaflickers EIGENE Positions-Zuordnung pro Spieler.

Warum: nflverse und FantasyPros haben beide leicht unterschiedliche Positions-
Taxonomien fuer IDP (z.B. CB/S vs. DB, DE/DT vs. DL). Was tatsaechlich zaehlt,
ist aber, welchen Slot ein Spieler in DIESER Liga belegen darf -- das
entscheidet ausschliesslich Fleaflicker. Dieses Skript holt genau das.

Laeuft im GitHub-Workflow (voller Internetzugriff), nicht in Claudes Sandbox
(dort ist fleaflicker.com nicht in der Netzwerk-Whitelist).

Kein API-Key noetig -- FetchPlayerListing ist ein oeffentlicher Endpoint.
"""
import json
import os
import time
import urllib.request
import urllib.error

BASE = "https://www.fleaflicker.com/api/FetchPlayerListing"
LEAGUE_ID = 294292
MAX_RETRIES = 3


def fetch_page(offset: int) -> dict:
    url = f"{BASE}?sport=NFL&league_id={LEAGUE_ID}&result_offset={offset}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mld-trade-calculator/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            if attempt == MAX_RETRIES:
                raise
            print(f"  Offset {offset}: Versuch {attempt}/{MAX_RETRIES} fehlgeschlagen ({e}), "
                  f"warte 10s ...")
            time.sleep(10)


def fetch_all_players() -> list:
    all_players = []
    offset = 0
    seen_offsets = set()

    while True:
        print(f"Lade FetchPlayerListing offset={offset} ...")
        data = fetch_page(offset)
        players = data.get("players", [])
        total = data.get("result_total", 0)

        for p in players:
            pro = p.get("pro_player", {})
            all_players.append({
                "fleaflicker_id": pro.get("id"),
                "name": pro.get("name_full"),
                "position": pro.get("position"),
                "team": pro.get("pro_team_abbreviation"),
                "is_rookie": pro.get("is_rookie", False),
            })

        print(f"  {len(players)} Spieler geladen ({len(all_players)}/{total} gesamt)")

        next_offset = data.get("result_offset_next")
        if not next_offset or next_offset in seen_offsets or len(all_players) >= total:
            break
        seen_offsets.add(next_offset)
        offset = next_offset
        time.sleep(1)  # kleine Pause zwischen Seiten, kein Rate-Limit reissen

    return all_players


if __name__ == "__main__":
    players = fetch_all_players()
    os.makedirs("data", exist_ok=True)
    with open("data/fleaflicker_players.json", "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False, indent=2)
    print(f"\nFertig: {len(players)} Spieler -> data/fleaflicker_players.json")
