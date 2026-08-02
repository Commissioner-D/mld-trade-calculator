"""
Laedt Season-Projektionen (Rohkategorien, keine vorgerechneten Punkte) von der
offiziellen FantasyPros Public API -- kostenlos fuer persoenliche, nicht-
kommerzielle Nutzung.

WICHTIG: Wir nutzen NUR die Rohkategorien aus `stats` (rush_yds, rec_tds, etc.),
nie das mitgelieferte `points`-Feld -- das waere FantasyPros' eigene Standard-
Scoring-Annahme, nicht unsere Liga-Config. Siehe Projekt-Prinzip: jede Quelle
liefert Rohkategorien, der zentrale Scoring-Kern (engine/scoring.py) rechnet
sie einheitlich mit UNSEREM Regelwerk um.

API-Doku: https://api.fantasypros.com/v2/docs
Terms: https://api.fantasypros.com/public/v2/terms-of-use
  -> bei Veroeffentlichung von Analysen: FantasyPros als Quelle nennen.

Key anfordern: https://secure.fantasypros.com/api-keys/request
Key wird NIE in den Code oder ins Repo geschrieben -- kommt als Umgebungs-
variable FANTASYPROS_API_KEY (lokal: eigene .env / Shell-Export; in der
GitHub Action: als Repository-Secret, siehe .github/workflows/update-values.yml).
"""
import os
import json
import urllib.request
import urllib.error

API_BASE = "https://api.fantasypros.com/public/v2/json/nfl"

# FantasyPros-Rohkategorie -> unser Schema (siehe engine/aggregate_offense.py)
STAT_MAP = {
    "pass_att": "pass_att", "pass_cmp": "pass_cmp", "pass_yds": "pass_yards",
    "pass_tds": "pass_td", "pass_ints": "pass_int",
    "rush_att": "rush_att", "rush_yds": "rush_yards", "rush_tds": "rush_td",
    "rec_rec": "receptions", "rec_yds": "rec_yards", "rec_tds": "rec_td",
    "fumbles": "fumbles",
    "2pt_tds": "pass_2pt",  # Naeherung; FantasyPros trennt Pass/Rush-2PT nicht getrennt aus
}


def fetch_projections(season: int, week: int = 0, api_key: str = None,
                       positions=("QB", "RB", "WR", "TE", "K")) -> dict:
    """week=0 -> Season-Projektion (kein einzelner Spieltag).

    Ruft pro Position einzeln ab und fuegt zusammen -- ein Call ohne
    position-Parameter liefert offenbar nur eine Default-Position (beobachtet:
    ausschliesslich RB), nicht alle Positionen wie in der 2017er Doku-Beispiel-
    Response angedeutet."""
    api_key = api_key or os.environ.get("FANTASYPROS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Kein API-Key gefunden. Erwartet in Umgebungsvariable FANTASYPROS_API_KEY "
            "(lokal per `export FANTASYPROS_API_KEY=...`, in der GitHub Action als Secret)."
        )
    all_players = []
    for pos in positions:
        url = f"{API_BASE}/{season}/projections?week={week}&position={pos}"
        print(f"Rufe ab: {url}")
        req = urllib.request.Request(url, headers={"x-api-key": api_key})
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"FantasyPros API Fehler {e.code}: {e.read().decode()}") from e
        players = data.get("players", [])
        print(f"  {pos}: {len(players)} Spieler")
        all_players.extend(players)
    return {"season": str(season), "players": all_players}


def to_raw_categories(api_response: dict) -> list:
    """Mappt die API-Response auf unser Rohkategorien-Schema, ein dict pro Spieler."""
    out = []
    for p in api_response.get("players", []):
        row = {
            "name": p.get("name"),
            "position": p.get("position_id"),
            "team": p.get("team_id"),
            "source": "fantasypros_projection",
            "season": api_response.get("season"),
        }
        stats = p.get("stats", {})
        for src_key, dest_key in STAT_MAP.items():
            row[dest_key] = stats.get(src_key, 0)
        out.append(row)
    return out


if __name__ == "__main__":
    import sys
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    resp = fetch_projections(season)
    rows = to_raw_categories(resp)
    out_path = f"data/fantasypros_projections_{season}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"{len(rows)} Spieler-Projektionen -> {out_path}")
