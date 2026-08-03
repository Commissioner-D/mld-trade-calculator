"""
Laedt die Liga-Regeln (FetchLeagueRules) -- vor allem num_bench/max_roster_size,
die wir bisher nirgends abgerufen hatten. Noetig, um den "Wert eines Rosterplatzes"
zu berechnen: VORP des Spielers an Rang (16 Teams x Gesamt-Rosterplaetze).

Laeuft im GitHub-Workflow (voller Internetzugriff), nicht in Claudes Sandbox.
"""
import json
import os
import urllib.request
import urllib.error

URL = "https://www.fleaflicker.com/api/FetchLeagueRules?sport=NFL&league_id=294292"


def _get(d: dict, *keys):
    for k in keys:
        if k in d:
            return d[k]
    return None


if __name__ == "__main__":
    req = urllib.request.Request(URL, headers={"User-Agent": "mld-trade-calculator/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"FetchLeagueRules Fehler {e.code}: {e.read().decode()[:300]}") from e

    result = {
        "num_starters": _get(data, "num_starters", "numStarters"),
        "num_bench": _get(data, "num_bench", "numBench"),
        "max_active": _get(data, "max_active", "maxActive"),
        "max_roster_size": _get(data, "max_roster_size", "maxRosterSize"),
    }
    os.makedirs("data", exist_ok=True)
    with open("data/fleaflicker_league_rules.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print("Liga-Regeln:", result)
    print("-> data/fleaflicker_league_rules.json")

    # Komplettes Roh-Response separat speichern -- fuer Felder, die wir noch
    # nicht kennen (z.B. wie viele Jahre im Voraus Picks tradebar sind)
    with open("data/fleaflicker_league_rules_raw.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("Rohdaten -> data/fleaflicker_league_rules_raw.json")
