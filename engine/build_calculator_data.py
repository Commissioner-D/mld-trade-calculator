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
from engine.pick_curve import pick_value, fit_pick_curve

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

# --- Rosterplatz-Wert: was ein Team tatsaechlich verliert, wenn es fuer einen zusaetzlichen Spieler
# jemanden schneiden muss = seine schwaechsten aktiven Spieler. Pro Team der Schnitt der 3 schwaechsten
# aktiven (Start/Bank, ohne K, IR, Taxi), dann Schnitt ueber alle Teams, nach unten bei 0 gekappt.
# Vorher: Schnitt der 15 besten Free Agents -- das waren fast nur CBs mit Marktwert, die in der MLD
# genau deshalb frei sind, weil sie keiner will (1,7 statt real ~0).
# Kaderdaten mit Slots: league.json aus dem Free-Agent-Radar (im Workflow geladen).
CUT_CANDIDATES = 3
TAXI_WEIGHT = 5 / 28
roster_spot_value = None
league_path = "data/mld_league.json"
if os.path.exists(league_path):
    import re as _re

    def _norm(n):
        return _re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", _re.sub(r"[^a-z ]", "", __import__("unicodedata").normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower())).strip()

    _val = {}
    for _, r in df.dropna(subset=["primary_value"]).iterrows():
        k = _norm(r["full_name"])
        _val[k] = max(_val.get(k, -1e9), float(r["primary_value"]))
    with open(league_path, encoding="utf-8") as f:
        _league = json.load(f)
    per_team = []
    for t in _league.get("teams", []):
        act = sorted(_val.get(_norm(p["name"]), 0.0) for p in t.get("roster", [])
                     if p.get("slot") in ("Start", "Bank") and p.get("pos") != "K")
        if len(act) >= CUT_CANDIDATES:
            per_team.append(sum(act[:CUT_CANDIDATES]) / CUT_CANDIDATES)
    if per_team:
        roster_spot_value = round(max(0.0, sum(per_team) / len(per_team)), 3)
    print(f"Rosterplatz-Wert (Schnitt der {CUT_CANDIDATES} schwaechsten aktiven Spieler je Team, "
          f"{len(per_team)} Teams, min 0): {roster_spot_value}")
else:
    print(f"Keine Kaderdaten unter {league_path} -- Rosterplatz-Wert bleibt leer.")

with open("output/calculator_config.json", "w") as f:
    json.dump({"roster_spot_value": roster_spot_value, "taxi_weight": round(TAXI_WEIGHT, 4)}, f)

# Keine Kappung mehr: gerade Bank-/Throw-in-Spieler (z.B. Sweetener in Trades)
# muessen auffindbar bleiben. Nur eindeutige Nicht-Fantasy-Positionen raus.
VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K",
                    "CB", "FS", "SS", "DB", "S",
                    "DE", "DT", "NT", "EDR", "IL",
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
    for k, v in list(p.items()):          # NaN ist kein gueltiges JSON -> null
        if isinstance(v, float) and v != v:
            p[k] = None

# --- Pick-Kurve bei jedem Lauf neu fitten: ein Pick ist so viel wert wie der Spieler, den man an
# der Stelle im Schnitt bekommt -- gemessen an den HEUTIGEN Werten der letzten 4 Rookie-Jahrgaenge
# (aeltere sind ueber den Peak hinaus). Bust = 0 (wird geschnitten). So passen Picks und Spieler
# immer auf dieselbe Skala, auch wenn sich das Spielermodell aendert.
PICK_CLASSES = 4
_pick_params = None
_hist_path = "data/rookie_picks_with_values.json"
if os.path.exists(_hist_path):
    import re as _re2
    _n = lambda n: _re2.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", _re2.sub(r"[^a-z ]", "", __import__("unicodedata").normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower())).strip()
    _side = lambda pos: "O" if pos in ("QB", "RB", "WR", "TE", "K") else "D"
    _vals = {}
    for _, r in df.dropna(subset=["primary_value"]).iterrows():
        k = (_n(r["full_name"]), _side(r["position"]))
        _vals[k] = max(_vals.get(k, -1e9), float(r["primary_value"]))
    with open(_hist_path, encoding="utf-8") as f:
        _hist = json.load(f)
    _last = max(h["season"] for h in _hist)
    _hist = [h for h in _hist if h["season"] > _last - PICK_CLASSES]
    _pts = [{"overall": h["overall"], "value": _vals.get((_n(h["name"]), _side(h["position"])), 0.0)} for h in _hist]
    _pick_params = fit_pick_curve(_pts)
    print(f"Pick-Kurve neu gefittet ({len(_pts)} Picks, Jahrgaenge {_last - PICK_CLASSES + 1}-{_last}): {_pick_params}")

picks = []
for year in TRADEABLE_YEARS:
    for rnd in range(1, NUM_ROOKIE_ROUNDS + 1):
        for slot in range(1, NUM_TEAMS + 1):
            overall = (rnd - 1) * NUM_TEAMS + slot
            picks.append({
                "id": f"{year}-{rnd}.{slot:02d}",
                "label": f"{year} {rnd}.{slot:02d}", "year": year, "round": rnd, "slot": slot,
                "overall": overall, "value": pick_value(overall, _pick_params) if _pick_params else pick_value(overall),
            })

with open("output/calculator_players.json", "w") as f:
    json.dump(players, f, ensure_ascii=False, allow_nan=False)   # bricht lieber hier als im Browser
with open("output/calculator_picks.json", "w") as f:
    json.dump(picks, f, allow_nan=False)

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
