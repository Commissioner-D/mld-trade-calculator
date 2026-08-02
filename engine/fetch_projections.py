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
import time
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

# Defense-Rohkategorie -> unser Schema (siehe engine/aggregate_defense.py).
# FantasyPros liefert def_tackle getrennt von def_assist -> def_tackle = Solo Tackles.
# KEINE Sack-Yards im Response -- mit ~7 Yards/Sack angenaehert (ungefaehrer
# NFL-Schnitt), da unsere Scoring-Config 0.25 Pkt/Sack-Yard vergibt und wir
# sonst diesen Anteil komplett unterschlagen wuerden.
DEF_STAT_MAP = {
    "def_tackle": "solo_tackle",
    "def_assist": "assisted_tackle",
    "def_tlost": "tackle_for_loss",
    "def_sack": "sack",
    "def_int": "interception",
    "def_pd": "pass_defended",
    "def_ff": "forced_fumble",
    "def_fr": "fumble_recovered",
    "def_safety": "safety",
    "def_td": "def_td",
}
ASSUMED_YARDS_PER_SACK = 7.0


def fetch_projections(season: int, week: int = 0, api_key: str = None,
                       positions=("QB", "RB", "WR", "TE", "K",
                                  "LB", "DB", "DL")) -> dict:
    """week=0 -> Season-Projektion (kein einzelner Spieltag).

    Ruft pro Position einzeln ab und fuegt zusammen -- ein Call ohne
    position-Parameter liefert offenbar nur eine Default-Position (beobachtet:
    ausschliesslich RB), nicht alle Positionen wie in der 2017er Doku-Beispiel-
    Response angedeutet.

    IDP-Seite bewusst nur DL/LB/DB (nicht zusaetzlich DE/DT/CB/S): FantasyPros
    fasst IDP nur in diesen drei groben Buckets, DE/DT sind bereits Teil von
    DL und CB/S bereits Teil von DB -- separate Calls dafuer waren nur
    redundant und haben unnoetig das Rate-Limit belastet (Fund von Dominik).

    WICHTIG: bei Throttling liefert die API manchmal keinen sauberen 429-Fehler,
    sondern einen 200er mit verdaechtig wenigen Spielern (beobachtet: DB nur 4
    statt ~200). Deshalb zusaetzlich zum 429-Retry ein Retry, wenn die Antwort
    weniger als MIN_EXPECTED_PLAYERS Spieler enthaelt -- kein einziger unserer
    Positions-Codes liefert legitim so wenige."""
    MIN_EXPECTED_PLAYERS = 15  # niedrigster echter Wert bisher war K mit 43

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
                    print(f"  {pos}: nur {len(players)} Spieler erhalten (verdaechtig wenig, "
                          f"vermutlich Throttling), warte {wait}s und versuche erneut "
                          f"({attempt}/4) ...")
                    time.sleep(wait)
                    continue
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 4:
                    wait = 30 * attempt
                    print(f"  {pos}: Rate Limit (429), warte {wait}s und versuche erneut "
                          f"({attempt}/4) ...")
                    time.sleep(wait)
                    continue
                print(f"  {pos}: FEHLER {e.code} ({e.read().decode()[:200]}) -- ueberspringe, kein Abbruch")
                players = []
                break

        print(f"  {pos}: {len(players)} Spieler")
        all_players.extend(players)
        time.sleep(5)  # groessere Pause zwischen Positionen, um das Rate Limit gar nicht erst zu reissen
    return {"season": str(season), "players": all_players}


def to_raw_categories(api_response: dict) -> list:
    """Mappt die API-Response auf unser Rohkategorien-Schema, ein dict pro Spieler.
    Bekannte Offense- UND Defense-Felder werden auf unser Schema gemappt; ALLE rohen
    stats-Felder werden zusaetzlich unter raw_stats_* durchgereicht (Sicherheitsnetz)."""
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
        for src_key, dest_key in DEF_STAT_MAP.items():
            row[dest_key] = stats.get(src_key, 0)
        if row.get("sack"):
            row["sack_yards"] = row["sack"] * ASSUMED_YARDS_PER_SACK
        else:
            row["sack_yards"] = 0
        for k, v in stats.items():
            row[f"raw_stats_{k}"] = v
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
