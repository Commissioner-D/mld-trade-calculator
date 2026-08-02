"""
Laedt FantasyPros' Dynasty-Consensus-Rankings (ranking_type=DYNASTY) --
dient NUR als Kalibrierungs-Ziel fuer die FORM unserer eigenen Formel
(Rangkorrelation), nicht als Wert-Input. FantasyPros' Rankings kennen
unsere 16-Team-Liga-Tiefe nicht -- absolute Werte waeren nicht vergleichbar,
die Reihenfolge/Sortierung aber schon.

Endpoint: GET /{sport}/{season}/consensus-rankings?position=X&type=DYNASTY
Kein API-Key-Kostenpflicht-Problem hier (gleicher HOF-Zugang wie Projections).
"""
import os
import json
import time
import urllib.request
import urllib.error

API_BASE = "https://api.fantasypros.com/public/v2/json/nfl"
MIN_EXPECTED_PLAYERS = 10


def fetch_dynasty_rankings(season: int, api_key: str = None,
                            positions=("QB", "RB", "WR", "TE", "LB", "DB", "DL")) -> list:
    api_key = api_key or os.environ.get("FANTASYPROS_API_KEY")
    if not api_key:
        raise RuntimeError("Kein API-Key gefunden (FANTASYPROS_API_KEY).")

    all_rows = []
    for pos in positions:
        url = f"{API_BASE}/{season}/consensus-rankings?position={pos}&type=DYNASTY"
        print(f"Rufe ab: {url}")

        players = []
        for attempt in range(1, 5):
            req = urllib.request.Request(url, headers={"x-api-key": api_key})
            try:
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read())
                players = data.get("players", [])
                if len(players) >= MIN_EXPECTED_PLAYERS:
                    break
                if attempt < 4:
                    wait = 30 * attempt
                    print(f"  {pos}: nur {len(players)} Spieler (verdaechtig wenig), "
                          f"warte {wait}s, Versuch {attempt}/4 ...")
                    time.sleep(wait)
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 4:
                    wait = 30 * attempt
                    print(f"  {pos}: Rate Limit, warte {wait}s ({attempt}/4) ...")
                    time.sleep(wait)
                    continue
                print(f"  {pos}: FEHLER {e.code} ({e.read().decode()[:200]}) -- ueberspringe")
                players = []
                break

        print(f"  {pos}: {len(players)} Spieler")
        for p in players:
            all_rows.append({
                "name": p.get("player_name"),
                "position": pos,
                "team": p.get("player_team_id"),
                "rank_ecr": p.get("rank_ecr"),
                "pos_rank": p.get("pos_rank"),
                "tier": p.get("tier"),
            })
        time.sleep(5)
    return all_rows


if __name__ == "__main__":
    import sys
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    rows = fetch_dynasty_rankings(season)
    os.makedirs("data", exist_ok=True)
    out_path = f"data/fantasypros_dynasty_rankings_{season}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"{len(rows)} Dynasty-Rankings -> {out_path}")
