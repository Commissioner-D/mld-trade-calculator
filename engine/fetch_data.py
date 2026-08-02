"""Laedt alle benoetigten nflverse-Rohdaten nach data/. Erneut ausfuehren,
sobald eine neue Saison aktuell wird (aktuell hart auf 2025/2024 gesetzt --
Saison-Auto-Detection ist noch offen, siehe README)."""
import urllib.request
import urllib.error
import os
import time

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
FILES = {
    f"{BASE}/rosters/roster_2025.csv.gz": "data/roster_2025.csv.gz",
    f"{BASE}/rosters/roster_2024.csv.gz": "data/roster_2024.csv.gz",
    f"{BASE}/pbp/play_by_play_2025.csv.gz": "data/pbp_2025.csv.gz",
    f"{BASE}/pbp/play_by_play_2024.csv.gz": "data/pbp_2024.csv.gz",
    f"{BASE}/player_stats/player_stats_def.csv.gz": "data/player_stats_def_2025.csv.gz",
    f"{BASE}/player_stats/player_stats.csv.gz": "data/player_stats_offense.csv.gz",
    f"{BASE}/contracts/historical_contracts.csv.gz": "data/historical_contracts.csv.gz",
}

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 10


def fetch_with_retry(url, dest, attempts=MAX_RETRIES):
    for attempt in range(1, attempts + 1):
        try:
            urllib.request.urlretrieve(url, dest)
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if attempt == attempts:
                raise
            print(f"  Versuch {attempt}/{attempts} fehlgeschlagen ({e}), "
                  f"warte {RETRY_DELAY_SECONDS}s und versuche erneut ...")
            time.sleep(RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    for url, dest in FILES.items():
        print(f"Lade {dest} ...")
        fetch_with_retry(url, dest)
    print("Fertig.")
