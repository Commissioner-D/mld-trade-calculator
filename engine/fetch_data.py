"""Laedt alle benoetigten nflverse-Rohdaten nach data/. Erneut ausfuehren,
sobald eine neue Saison aktuell wird (aktuell hart auf 2025/2024 gesetzt --
Saison-Auto-Detection ist noch offen, siehe README)."""
import urllib.request
import os

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
FILES = {
    f"{BASE}/rosters/roster_2025.csv.gz": "data/roster_2025.csv.gz",
    f"{BASE}/rosters/roster_2024.csv.gz": "data/roster_2024.csv.gz",
    f"{BASE}/pbp/play_by_play_2025.csv.gz": "data/pbp_2025.csv.gz",
    f"{BASE}/pbp/play_by_play_2024.csv.gz": "data/pbp_2024.csv.gz",
    f"{BASE}/player_stats/player_stats_def.csv.gz": "data/player_stats_def_2025.csv.gz",
    f"{BASE}/player_stats/player_stats.csv.gz": "data/player_stats_offense.csv.gz",
}

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    for url, dest in FILES.items():
        print(f"Lade {dest} ...")
        urllib.request.urlretrieve(url, dest)
    print("Fertig.")
