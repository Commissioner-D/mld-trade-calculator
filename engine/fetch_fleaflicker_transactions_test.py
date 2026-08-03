"""
Test-Fetch: Fleaflicker-Liga-Transaktionen, mehrere Seiten zurueck -- Ziel: echte
FAAB-Gebote (Betrag + erworbener Spieler) finden, um einen echten "$-pro-Wert"-
Umrechnungskurs fuer diese Liga zu kalibrieren, statt eine geratene Zahl zu
verwenden. Aktuelle (August-)Transaktionen sind nur Trades/Drops -- echte
Waiver-Aktivitaet war waehrend der NFL-Saison (Sept-Jan), also weiter zurueck
blaettern noetig.

Schreibt Diagnose-Infos (Fehler, Zwischenstaende) DIREKT in die Ausgabedatei,
nicht nur per print() -- Workflow-Logs sind von aussen nicht zuverlaessig lesbar.
"""
import json
import os
import time
import urllib.request
import urllib.error

BASE = "https://www.fleaflicker.com/api/FetchLeagueTransactions?sport=NFL&league_id=294292"
MAX_PAGES = 15

if __name__ == "__main__":
    all_items = []
    types_seen = {}
    diagnostics = []
    offset = 0

    for page in range(MAX_PAGES):
        url = f"{BASE}&resultOffset={offset}" if offset else BASE
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mld-trade-calculator/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                data = json.loads(raw)
        except Exception as e:
            diagnostics.append(f"Seite {page} (offset={offset}): FEHLER {type(e).__name__}: {e}")
            break

        items = data.get("items", [])
        diagnostics.append(f"Seite {page} (offset={offset}): {len(items)} Eintraege, "
                            f"top_keys={list(data.keys())}, resultOffsetNext={data.get('resultOffsetNext')}")
        all_items.extend(items)
        for item in items:
            t = item.get("transaction", {}).get("type", "UNKNOWN")
            types_seen[t] = types_seen.get(t, 0) + 1

        next_offset = data.get("resultOffsetNext")
        if not next_offset or next_offset == offset or not items:
            diagnostics.append("Abbruch: keine weiteren Seiten.")
            break
        offset = next_offset
        time.sleep(1)

    os.makedirs("data", exist_ok=True)
    output = {"diagnostics": diagnostics, "types_seen": types_seen, "total_items": len(all_items), "items": all_items}
    with open("data/fleaflicker_transactions_test.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Gesamt: {len(all_items)} Eintraege. Typen: {types_seen}")
