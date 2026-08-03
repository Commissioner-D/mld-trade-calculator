"""
Test-Fetch: Fleaflicker-Liga-Transaktionen -- Ziel: echte FAAB-Gebote (Betrag +
erworbener Spieler) finden, um einen echten "$-pro-Wert"-Umrechnungskurs fuer
diese Liga zu kalibrieren, statt eine geratene Zahl zu verwenden.

Endpoint-Name geraten nach demselben Muster wie FetchLeagueRules/FetchLeagueRosters/
FetchPlayerListing: FetchLeagueTransactions. Noch nicht bestaetigt, ob das der
richtige Name ist -- reiner Test.
"""
import json
import os
import urllib.request
import urllib.error

URL = "https://www.fleaflicker.com/api/FetchLeagueTransactions?sport=NFL&league_id=294292"

if __name__ == "__main__":
    req = urllib.request.Request(URL, headers={"User-Agent": "mld-trade-calculator/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"FEHLER {e.code}: {e.read().decode()[:500]}")
        raise SystemExit(1)

    os.makedirs("data", exist_ok=True)
    with open("data/fleaflicker_transactions_test.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("Top-Level-Keys:", list(data.keys()) if isinstance(data, dict) else type(data))
    print("-> data/fleaflicker_transactions_test.json")
