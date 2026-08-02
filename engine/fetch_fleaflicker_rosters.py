"""
Laedt die kompletten Rosters aller 16 Teams dieser Liga (FetchLeagueRosters)
-- fuer echte Rostertiefe pro Position, statt "Start-Slots x Teams" zu schaetzen.

Warum: Aktuell nehmen wir fuer Replacement-Level einfach Rang = Start-Slots x
16 Teams an (z.B. K und QB beide Rang 16). Das ignoriert, dass QBs in der
Praxis viel tiefer gerostert werden als Kicker (mehr Bank-Stashing, weniger
Free-Agent-Tiefe pro Team gebraucht). Mit den echten Rosterdaten koennen wir
das durch tatsaechliche Zaehlung ersetzen.

Struktur laut API-Doku (FetchLeagueRosters) unklar bis zum ersten echten
Response -- Debug-Dump beim ersten Team, dann anhand dessen final anpassen
(gleiches Vorgehen wie bei fetch_fleaflicker_players.py, das hat sich bewaehrt).

Laeuft im GitHub-Workflow (voller Internetzugriff), nicht in Claudes Sandbox.
Kein API-Key noetig -- oeffentlicher Endpoint.
"""
import json
import os
import time
import urllib.request
import urllib.error

BASE = "https://www.fleaflicker.com/api/FetchLeagueRosters"
LEAGUE_ID = 294292
MAX_RETRIES = 3


def _get(d: dict, *keys):
    for k in keys:
        if k in d:
            return d[k]
    return None


def fetch_json(url: str) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mld-trade-calculator/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            if attempt == MAX_RETRIES:
                raise
            print(f"  Versuch {attempt}/{MAX_RETRIES} fehlgeschlagen ({e}), warte 10s ...")
            time.sleep(10)


def fetch_league_rosters() -> dict:
    url = f"{BASE}?sport=NFL&league_id={LEAGUE_ID}"
    print(f"Rufe ab: {url}")
    return fetch_json(url)


def parse_rosters(data: dict) -> list:
    """Gibt eine flache Liste [{team, player_name, position, group}] zurueck.
    group = START/BENCH/INJURED/TAXI, aus der Roster-Slot-Zuordnung."""
    out = []
    rosters = _get(data, "rosters") or []

    if not rosters:
        return out

    # Debug: Struktur des ersten Rosters zeigen, falls das erwartete Schema nicht passt
    print("--- DEBUG: Top-Level-Keys erstes Roster ---")
    print(list(rosters[0].keys()))

    for roster in rosters:
        team = _get(roster, "team") or {}
        team_name = _get(team, "name")
        groups = _get(roster, "groups") or []
        for group in groups:
            group_name = _get(group, "group")
            slots = _get(group, "slots") or []
            for slot in slots:
                league_player = _get(slot, "league_player", "leaguePlayer") or {}
                pro = _get(league_player, "pro_player", "proPlayer") or {}
                if not pro:
                    continue
                out.append({
                    "team": team_name,
                    "player_name": _get(pro, "name_full", "nameFull"),
                    "position": _get(pro, "position"),
                    "roster_group": group_name,
                })
    return out


if __name__ == "__main__":
    data = fetch_league_rosters()
    players = parse_rosters(data)
    os.makedirs("data", exist_ok=True)
    with open("data/fleaflicker_rosters.json", "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False, indent=2)
    print(f"\nFertig: {len(players)} Roster-Eintraege -> data/fleaflicker_rosters.json")
    if players:
        from collections import Counter
        print(Counter(p["position"] for p in players))
