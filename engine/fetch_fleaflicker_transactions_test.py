"""
Test-Fetch: Fleaflicker-Liga-Transaktionen, mehrere Seiten zurueck -- Ziel: echte
FAAB-Gebote (Betrag + erworbener Spieler) finden, um einen echten "$-pro-Wert"-
Umrechnungskurs fuer diese Liga zu kalibrieren, statt eine geratene Zahl zu
verwenden. Aktuelle (August-)Transaktionen sind nur Trades/Drops -- echte
Waiver-Aktivitaet war waehrend der NFL-Saison (Sept-Jan), also weiter zurueck
blaettern noetig.
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
    offset = 0
    for page in range(MAX_PAGES):
        url = f"{BASE}&resultOffset={offset}" if offset else BASE
        req = urllib.request.Request(url, headers={"User-Agent": "mld-trade-calculator/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            print(f"Seite {page} (offset={offset}): FEHLER {e.code}")
            break

        items = data.get("items", [])
        all_items.extend(items)
        for item in items:
            t = item.get("transaction", {}).get("type", "UNKNOWN")
            types_seen[t] = types_seen.get(t, 0) + 1
        print(f"Seite {page} (offset={offset}): {len(items)} Eintraege, Typen bisher: {types_seen}")

        next_offset = data.get("resultOffsetNext")
        if not next_offset or next_offset == offset or not items:
            print("Keine weiteren Seiten.")
            break
        offset = next_offset
        time.sleep(1)

    os.makedirs("data", exist_ok=True)
    with open("data/fleaflicker_transactions_test.json", "w", encoding="utf-8") as f:
        json.dump(all_items, f, indent=2)
    print(f"\nGesamt: {len(all_items)} Eintraege ueber {page+1} Seiten -> data/fleaflicker_transactions_test.json")
    print("Alle Typen:", types_seen)
