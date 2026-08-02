"""
Baut aus output/value_table.csv einen kompakten Datensatz fuers Trade-Desk-UI
und backt ihn zusammen mit den Pick-Werten in web/index.html ein.
"""
import sys
import os
import json
import pandas as pd

sys.path.insert(0, ".")
from engine.pick_curve import pick_value

NUM_ROOKIE_ROUNDS = 4
NUM_TEAMS = 16

df = pd.read_csv("output/value_table.csv").dropna(subset=["dynasty_trailing_value"])

# Keine Kappung mehr: gerade Bank-/Throw-in-Spieler (z.B. Sweetener in Trades)
# muessen auffindbar bleiben. Nur eindeutige Nicht-Fantasy-Positionen raus.
VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K",
                    "CB", "FS", "SS", "DB",
                    "DE", "DT", "NT",
                    "OLB", "ILB", "MLB", "LB"}

trimmed = df[df["position"].isin(VALID_POSITIONS)].sort_values("dynasty_trailing_value", ascending=False)
trimmed = trimmed[["full_name", "position", "team", "age", "weighted_ppg", "dynasty_trailing_value"]].copy()
trimmed.columns = ["name", "pos", "team", "age", "ppg", "value"]
trimmed["ppg"] = trimmed["ppg"].round(2)
trimmed["value"] = trimmed["value"].round(2)
trimmed["age"] = trimmed["age"].round(1)

players = trimmed.to_dict("records")

picks = []
for rnd in range(1, NUM_ROOKIE_ROUNDS + 1):
    for slot in range(1, NUM_TEAMS + 1):
        overall = (rnd - 1) * NUM_TEAMS + slot
        picks.append({
            "label": f"{rnd}.{slot:02d}", "round": rnd, "slot": slot,
            "overall": overall, "value": pick_value(overall),
        })

with open("output/calculator_players.json", "w") as f:
    json.dump(players, f, ensure_ascii=False)
with open("output/calculator_picks.json", "w") as f:
    json.dump(picks, f)

# index.html laedt die Werte jetzt zur Laufzeit per fetch() aus output/*.json --
# die Datei selbst muss bei einem reinen Werte-Update NICHT mehr angefasst werden.
if not os.path.exists("web/index.html"):
    import shutil
    shutil.copy("web/template.html", "web/index.html")

print(f"{len(players)} Spieler, {len(picks)} Picks -> output/calculator_players.json / calculator_picks.json aktualisiert.")
print("web/index.html unveraendert (laedt Daten live per fetch()).")
