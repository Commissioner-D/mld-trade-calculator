"""
Baut aus output/value_table.csv einen kompakten Datensatz fuers Trade-Desk-UI
und backt ihn zusammen mit den Pick-Werten in web/index.html ein.
"""
import sys
import os
import json
import datetime
import pandas as pd

sys.path.insert(0, ".")
from engine.pick_curve import pick_value

NUM_ROOKIE_ROUNDS = 4
NUM_TEAMS = 16

# Naechster noch nicht stattgefundener Rookie-Draft: Deadline laut Liga-Regelwerk
# ist der 30. August. Vor diesem Datum zaehlt das laufende Jahr noch als Pick,
# danach ist es bereits verbraucht (Spieler sind gezogen) -- automatischer
# Rollover, damit das nicht jedes Jahr manuell nachgezogen werden muss.
_today = datetime.date.today()
_draft_deadline = datetime.date(_today.year, 8, 30)
NEXT_DRAFT_YEAR = _today.year if _today <= _draft_deadline else _today.year + 1
# Laut Liga-Regelwerk: "not allowed to trade for picks further in the future
# than two seasons" -> zwei Jahrgaenge insgesamt (naechster Draft + 1 Jahr voraus).
TRADEABLE_YEARS = [NEXT_DRAFT_YEAR, NEXT_DRAFT_YEAR + 1]

df = pd.read_csv("output/value_table.csv")

# --- Rosterplatz-Wert: dynamisch aus den 15 besten aktuell NICHT gerosterten
# Spielern berechnet (nicht fest einprogrammiert) -- passt sich automatisch an,
# falls z.B. ein ungewoehnlich guter Free Agent gerade verfuegbar ist. Dient im
# Frontend als Abschlag fuer Trades mit ungleicher Spieleranzahl (nur die Seite,
# die netto mehr Koerper aufnimmt, bekommt den Abschlag -- kein Bonus fuers
# Verschlanken). Taxi-eligible Spieler (Jahr 1-2) zaehlen nur mit 5/28 Gewicht,
# da Taxi-Slots zusaetzlich zu den 28 aktiven Plaetzen existieren.
ROSTER_SPOT_BEST_N = 15
TAXI_WEIGHT = 5 / 28
roster_spot_value = None
rosters_path = "data/fleaflicker_rosters.json"
if os.path.exists(rosters_path):
    with open(rosters_path, encoding="utf-8") as f:
        rosters = json.load(f)
    import re as _re

    def _norm(n):
        return _re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", _re.sub(r"[^a-z ]", "", str(n).lower())).strip()

    rostered_names = {_norm(r["player_name"]) for r in rosters if r.get("player_name")}
    df_valid = df.dropna(subset=["primary_value"]).copy()
    df_valid["norm_name"] = df_valid["full_name"].apply(_norm)
    unrostered = df_valid[~df_valid["norm_name"].isin(rostered_names)].sort_values("primary_value", ascending=False)
    best_fa = unrostered.head(ROSTER_SPOT_BEST_N)
    roster_spot_value = round(float(best_fa["primary_value"].mean()), 3)
    print(f"Rosterplatz-Wert (Schnitt der {ROSTER_SPOT_BEST_N} besten Free Agents): {roster_spot_value}")
else:
    print(f"Keine Rosterdaten unter {rosters_path} -- Rosterplatz-Wert bleibt leer.")

with open("output/calculator_config.json", "w") as f:
    json.dump({"roster_spot_value": roster_spot_value, "taxi_weight": round(TAXI_WEIGHT, 4)}, f)

# Keine Kappung mehr: gerade Bank-/Throw-in-Spieler (z.B. Sweetener in Trades)
# muessen auffindbar bleiben. Nur eindeutige Nicht-Fantasy-Positionen raus.
VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K",
                    "CB", "FS", "SS", "DB",
                    "DE", "DT", "NT",
                    "OLB", "ILB", "MLB", "LB"}

trimmed = df[df["position"].isin(VALID_POSITIONS)].copy()
# Taxi-eligible (1./2. Jahr in der Liga) fuer die Rosterplatz-Differential-Logik im
# Frontend -- solche Spieler zaehlen dort nur mit 5/28 Gewicht (Taxi-Slots sind
# zusaetzlich zu den 28 aktiven Plaetzen vorhanden, kein normaler Verdraengungseffekt).
trimmed["is_taxi"] = trimmed["years_exp"].fillna(99) <= 2
# NaN-Werte ans Ende sortieren (nicht ausgewaehlt/nicht auswaehlbar), Rest nach Wert
trimmed = trimmed.sort_values("primary_value", ascending=False, na_position="last")
trimmed = trimmed[["full_name", "position", "team", "age", "weighted_ppg",
                    "primary_value", "primary_value_source", "dynasty_trailing_value", "is_taxi"]].copy()
trimmed.columns = ["name", "pos", "team", "age", "ppg", "value", "src", "trailing", "is_taxi"]
trimmed["ppg"] = trimmed["ppg"].round(2)
trimmed["value"] = trimmed["value"].round(2)
trimmed["age"] = trimmed["age"].round(1)
trimmed["trailing"] = trimmed["trailing"].round(2)
# selectable=False fuer Spieler ganz ohne Wert (weder Projektion noch Dynasty-Rang) --
# bleiben im Calculator sichtbar/suchbar, koennen aber nicht zu einem Trade
# hinzugefuegt werden (Dominiks Vorgabe: NA statt eines geratenen Werts).
trimmed["selectable"] = trimmed["value"].notna()

players = trimmed.to_dict("records")
for i, p in enumerate(players):
    p["id"] = f"player-{i}"
    if pd.isna(p["trailing"]):
        p["trailing"] = None
    if pd.isna(p["value"]):
        p["value"] = None
        p["src"] = "none"

picks = []
for year in TRADEABLE_YEARS:
    for rnd in range(1, NUM_ROOKIE_ROUNDS + 1):
        for slot in range(1, NUM_TEAMS + 1):
            overall = (rnd - 1) * NUM_TEAMS + slot
            picks.append({
                "id": f"{year}-{rnd}.{slot:02d}",
                "label": f"{year} {rnd}.{slot:02d}", "year": year, "round": rnd, "slot": slot,
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
