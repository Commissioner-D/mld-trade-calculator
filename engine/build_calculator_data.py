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

df = pd.read_csv("output/value_table.csv")

# Keine Kappung mehr: gerade Bank-/Throw-in-Spieler (z.B. Sweetener in Trades)
# muessen auffindbar bleiben. Nur eindeutige Nicht-Fantasy-Positionen raus.
VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K",
                    "CB", "FS", "SS", "DB",
                    "DE", "DT", "NT",
                    "OLB", "ILB", "MLB", "LB"}

trimmed = df[df["position"].isin(VALID_POSITIONS)].copy()
# NaN-Werte ans Ende sortieren (nicht ausgewaehlt/nicht auswaehlbar), Rest nach Wert
trimmed = trimmed.sort_values("primary_value", ascending=False, na_position="last")
trimmed = trimmed[["full_name", "position", "team", "age", "weighted_ppg",
                    "primary_value", "primary_value_source", "dynasty_trailing_value"]].copy()
trimmed.columns = ["name", "pos", "team", "age", "ppg", "value", "src", "trailing"]
trimmed["ppg"] = trimmed["ppg"].round(2)
trimmed["value"] = trimmed["value"].round(2)
trimmed["age"] = trimmed["age"].round(1)
trimmed["trailing"] = trimmed["trailing"].round(2)
# selectable=False fuer Spieler ganz ohne Wert (weder Projektion noch Dynasty-Rang) --
# bleiben im Calculator sichtbar/suchbar, koennen aber nicht zu einem Trade
# hinzugefuegt werden (Dominiks Vorgabe: NA statt eines geratenen Werts).
trimmed["selectable"] = trimmed["value"].notna()

players = trimmed.to_dict("records")
for p in players:
    if pd.isna(p["trailing"]):
        p["trailing"] = None
    if pd.isna(p["value"]):
        p["value"] = None
        p["src"] = "none"

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
if not os.path.exists("index.html"):
    raise FileNotFoundError(
        "index.html fehlt an der Repo-Wurzel. Das ist die einzige Kopie der "
        "Oberflaeche (kein separates web/-Verzeichnis mehr) -- muss manuell "
        "wiederhergestellt werden, es gibt keine automatische Fallback-Quelle."
    )

print(f"{len(players)} Spieler, {len(picks)} Picks -> output/calculator_players.json / calculator_picks.json aktualisiert.")
print("index.html unveraendert (laedt Daten live per fetch()).")
