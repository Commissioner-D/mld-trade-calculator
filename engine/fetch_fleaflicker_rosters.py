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
    """Gibt eine flache Liste [{team, player_name, position, group}] zurueck."""
    out = []
    rosters = _get(data, "rosters") or []

    if not rosters:
        return out

    print("--- DEBUG: Top-Level-Keys erstes Roster ---")
    print(list(rosters[0].keys()))
    first_players = _get(rosters[0], "players") or []
    if first_players:
        print("--- DEBUG: erster Spieler-Eintrag komplett ---")
        print(json.dumps(first_players[0], indent=2, ensure_ascii=False)[:2000])

    for roster in rosters:
        team = _get(roster, "team") or {}
        team_name = _get(team, "name")
        players = _get(roster, "players") or []
        for entry in players:
            # Unklar ob 'entry' direkt der Spieler ist oder ein Slot-Wrapper --
            # beides versuchen: erst verschachtelt (league_player/pro_player),
            # sonst direkt als pro_player-artiges Objekt behandeln.
            league_player = _get(entry, "league_player", "leaguePlayer")
            pro = _get(league_player, "pro_player", "proPlayer") if league_player else None
            if not pro:
                pro = _get(entry, "pro_player", "proPlayer") or entry
            if not pro or not _get(pro, "name_full", "nameFull"):
                continue
            out.append({
                "team": team_name,
                "player_name": _get(pro, "name_full", "nameFull"),
                "position": _get(pro, "position"),
                "roster_group": _get(entry, "group") or _get(entry, "position", "positionLabel"),
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
