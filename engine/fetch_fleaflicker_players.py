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


def _get(d: dict, *keys):
    """Versucht mehrere moegliche Key-Varianten (camelCase vs. snake_case) --
    die Doku zeigt snake_case, aber protobuf-JSON-Serialisierung mapped
    Feldnamen standardmaessig auf lowerCamelCase. Sicherheitshalber beides."""
    for k in keys:
        if k in d:
            return d[k]
    return None


def fetch_all_players() -> list:
    all_players = []
    offset = 0
    seen_offsets = set()
    first_page = True

    while True:
        print(f"Lade FetchPlayerListing offset={offset} ...")
        data = fetch_page(offset)

        if first_page:
            print("--- DEBUG: echte Rohstruktur der ersten Antwort (Top-Level-Keys) ---")
            print(list(data.keys()))
            if data.get("players"):
                print("--- DEBUG: erster Spieler-Eintrag komplett ---")
                print(json.dumps(data["players"][0], indent=2, ensure_ascii=False)[:3000])
            first_page = False

        players = data.get("players", [])
        total = _get(data, "result_total", "resultTotal") or 0

        for p in players:
            pro = _get(p, "pro_player", "proPlayer") or {}
            all_players.append({
                "fleaflicker_id": _get(pro, "id"),
                "name": _get(pro, "name_full", "nameFull"),
                "position": _get(pro, "position"),
                "team": _get(pro, "pro_team_abbreviation", "proTeamAbbreviation"),
                "is_rookie": _get(pro, "is_rookie", "isRookie") or False,
            })

        print(f"  {len(players)} Spieler geladen ({len(all_players)}/{total} gesamt)")

        next_offset = _get(data, "result_offset_next", "resultOffsetNext")
        if not next_offset or next_offset in seen_offsets or (total and len(all_players) >= total):
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
