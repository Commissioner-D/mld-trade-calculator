"""
Laedt Rest-of-Season-Projektionen von Sleeper (Quelle: Rotowire), Offense UND IDP.

Sleeper liefert Projektionen pro Woche, auch fuer kommende Wochen. Die Summe ueber alle
verbleibenden Wochen der Fantasy-Saison ist die Rest-of-Season-Projektion -- Byes und
Ausfaelle sind darin schon enthalten (keine Projektion = kein Spiel).

Ausgabe: data/sleeper_ros_{season}.json, eine Zeile pro Spieler im selben Rohkategorien-
Schema wie die FantasyPros-Datei (solo_tackle, pass_yards, ...) plus "games" (verbleibende
Spiele mit Projektion). Gerechnet wird spaeter mit UNSEREM Scoring (engine/scoring.py).

Inoffizielle Schnittstelle (keine Doku, kein Key). Schlaegt der Abruf fehl, bricht das Skript
mit Fehler ab -> der Workflow baut dann nichts neu, die letzten Werte bleiben stehen.
Bewusst KEIN Rueckfall auf eine andere Quelle (Dominiks Vorgabe).
"""
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

BASE = "https://api.sleeper.app"
LAST_FANTASY_WEEK = 17                   # MLD: Playoffs Woche 15-17
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DL", "DE", "DT", "LB", "DB", "CB", "S"]
POS_TO_FP = {"DE": "DL", "DT": "DL", "DL": "DL", "CB": "DB", "S": "DB", "DB": "DB"}

OFF_MAP = {
    "pass_yd": "pass_yards", "pass_td": "pass_td", "pass_int": "pass_int", "pass_2pt": "pass_2pt",
    "rush_yd": "rush_yards", "rush_td": "rush_td", "rush_2pt": "rush_2pt", "rec_2pt": "rush_2pt",
    "rec": "receptions", "rec_yd": "rec_yards", "rec_td": "rec_td",
    "fum": "fumbles", "fum_lost": "fumbles_lost",
}
IDP_MAP = {
    "idp_tkl_solo": "solo_tackle", "idp_tkl_ast": "assisted_tackle", "idp_tkl_loss": "tackle_for_loss",
    "idp_sack": "sack", "idp_sack_yd": "sack_yards", "idp_int": "interception",
    "idp_pass_def": "pass_defended", "idp_ff": "forced_fumble", "idp_fum_rec": "fumble_recovered",
    "idp_safe": "safety",
}


def get(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mld-trade-calculator/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(5 * (i + 1))


def main():
    state = get(f"{BASE}/v1/state/nfl")
    season = int(state["season"])
    start = int(state.get("week") or 1) if state.get("season_type") == "regular" else 1
    weeks = list(range(max(start, 1), LAST_FANTASY_WEEK + 1))
    print(f"Saison {season}, verbleibende Wochen {weeks[0] if weeks else '-'}-{LAST_FANTASY_WEEK}")

    acc = defaultdict(lambda: defaultdict(float))
    meta = {}
    games = defaultdict(int)
    pos_q = "&".join(f"position[]={p}" for p in POSITIONS)
    for w in weeks:
        rows = get(f"{BASE}/projections/nfl/{season}/{w}?season_type=regular&{pos_q}")
        if not isinstance(rows, list) or not rows:
            raise SystemExit(f"Woche {w}: leere/ungueltige Antwort von Sleeper -- Abbruch, alte Werte bleiben")
        for x in rows:
            st = x.get("stats") or {}
            p = x.get("player") or {}
            pid = x.get("player_id")
            pos = p.get("position")
            if not pid or pos not in POSITIONS or not st.get("gp"):
                continue                        # Bye, verletzt, ohne Rolle -> kein Spiel
            meta[pid] = {"name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                         "position": POS_TO_FP.get(pos, pos), "team": x.get("team")}
            games[pid] += 1
            for k, v in st.items():
                if not isinstance(v, (int, float)):
                    continue
                if k in OFF_MAP:
                    acc[pid][OFF_MAP[k]] += v
                elif k in IDP_MAP:
                    acc[pid][IDP_MAP[k]] += v
                elif k.startswith("idp_") and k.endswith("_td"):
                    acc[pid]["def_td"] += v
        print(f"  Woche {w}: {len(rows)} Eintraege")
        time.sleep(1)

    out = []
    for pid, m in meta.items():
        out.append({**m, "source": "sleeper_rotowire_ros", "season": str(season), "games": games[pid],
                    **{k: round(v, 3) for k, v in acc[pid].items()}})
    if len(out) < 500:
        raise SystemExit(f"Nur {len(out)} Spieler mit Projektion -- unplausibel, Abbruch")
    os.makedirs("data", exist_ok=True)
    path = f"data/sleeper_ros_{season}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open("data/sleeper_ros_meta.json", "w") as f:
        json.dump({"season": season, "first_week": weeks[0] if weeks else None, "last_week": LAST_FANTASY_WEEK,
                   "weeks_left": len(weeks), "players": len(out)}, f)
    print(f"{len(out)} Spieler -> {path}")


if __name__ == "__main__":
    sys.exit(main())
