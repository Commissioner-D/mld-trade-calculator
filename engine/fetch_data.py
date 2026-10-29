"""Laedt alle benoetigten nflverse-Rohdaten nach data/: Rosters und Play-by-Play fuer
die aktuelle und die vorherige Saison. Die Saison wird automatisch bestimmt
(ab September gilt das neue Jahr als aktuelle Saison)."""
import urllib.request
import urllib.error
import os
import time
from datetime import date

BASE = "https://github.com/nflverse/nflverse-data/releases/download"


def current_season(today: date = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 9 else today.year - 1


def files_for(season: int) -> dict:
    out = {}
    for s in (season, season - 1):
        out[f"{BASE}/rosters/roster_{s}.csv.gz"] = f"data/roster_{s}.csv.gz"
        out[f"{BASE}/pbp/play_by_play_{s}.csv.gz"] = f"data/pbp_{s}.csv.gz"
    return out

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
    season = current_season()
    print(f"Aktuelle Saison: {season}")
    for url, dest in files_for(season).items():
        print(f"Lade {dest} ...")
        fetch_with_retry(url, dest)
    print("Fertig.")
