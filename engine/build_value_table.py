"""
Baut die vollstaendige Trailing-Production-Value-Tabelle fuer alle Spieler
(IDP + Offense + Kicker) aus nflverse-Rohdaten.

Ablauf:
  1. Rosters laden (Position, Alter, Team) fuer aktuelle + vorherige Saison
  2. Defense/Offense/Kicking-Rohkategorien fuer beide Saisons aus PBP aggregieren
     (die offiziellen player_stats-Releases enden bei 2024 und werden nicht mehr gepflegt)
  3. Scoring-Config anwenden -> Fantasy-Punkte pro Saison
  4. Weighted PPG (65/35) -> Replacement-Level/VORP -> Age-Curve
  5. Output: output/value_table.csv + output/value_table.json
"""
import sys
import os
import re
import unicodedata
import json
import pandas as pd
import numpy as np

sys.path.insert(0, ".")
from engine.aggregate_defense import aggregate_defense_from_pbp, from_official_release as def_official
from engine.aggregate_offense import aggregate_offense_from_pbp, from_official_release as off_official
from engine.aggregate_kicking import aggregate_kicking_from_pbp
from engine.scoring import load_scoring_config, score_defense_row, score_offense_row, score_kicking_row
from engine.value_engine import weighted_ppg, replacement_level, compute_age, dynasty_trailing_value

from engine.fetch_data import current_season

DATA = "data"
# Saison automatisch (ab September = neue Saison). Vorher hart 2025/2024 -> der komplette
# 2026er Rookie-Jahrgang fehlte im Rechner (z.B. Anthony Hill Jr.), Teams waren veraltet.
CUR_SEASON = current_season()
PREV_SEASON = CUR_SEASON - 1

print(f"Lade Rosters ({CUR_SEASON} + {PREV_SEASON}) ...")
roster_cur = pd.read_csv(f"{DATA}/roster_{CUR_SEASON}.csv.gz")
roster_prev = pd.read_csv(f"{DATA}/roster_{PREV_SEASON}.csv.gz")
# neuestes Rosterbild pro Spieler (fuer aktuelle Position/Team/Alter) bevorzugt aus der
# aktuellen Saison, Fallback Vorsaison fuer Spieler, die aktuell nicht gerostert sind
roster = pd.concat([roster_cur, roster_prev]).sort_values("season", ascending=False)
roster = roster.drop_duplicates(subset=["gsis_id"], keep="first")
roster["fine_position"] = roster["depth_chart_position"].fillna(roster["position"])

cfg = load_scoring_config("scoring/scoring_config.json")
with open("scoring/roster_config.json") as f:
    roster_cfg = json.load(f)

print("Aggregiere Defense ...")
pbp_cur = pd.read_csv(f"{DATA}/pbp_{CUR_SEASON}.csv.gz", low_memory=False)
pbp_prev = pd.read_csv(f"{DATA}/pbp_{PREV_SEASON}.csv.gz", low_memory=False)
def_cur = aggregate_defense_from_pbp(pbp_cur, CUR_SEASON)
def_prev = aggregate_defense_from_pbp(pbp_prev, PREV_SEASON)

print("Aggregiere Offense ...")
off_cur = aggregate_offense_from_pbp(pbp_cur, CUR_SEASON)
off_prev = aggregate_offense_from_pbp(pbp_prev, PREV_SEASON)

print("Aggregiere Kicking ...")
kick_cur = aggregate_kicking_from_pbp(pbp_cur, CUR_SEASON)
kick_prev = aggregate_kicking_from_pbp(pbp_prev, PREV_SEASON)

del pbp_cur, pbp_prev  # Speicher freigeben

print("Scoring anwenden ...")
for df in (def_cur, def_prev):
    df["fantasy_points"] = df.apply(lambda r: score_defense_row(r, cfg), axis=1)
for df in (off_cur, off_prev):
    df["fantasy_points"] = df.apply(lambda r: score_offense_row(r, cfg), axis=1)
for df in (kick_cur, kick_prev):
    df["fantasy_points"] = df.apply(lambda r: score_kicking_row(r, cfg), axis=1)

# --- pro Spieler: aktuelle + vorherige Saison zusammenfuehren ---
def build_player_value(pts_cur_df, pts_prev_df, roster_df, group_col_check):
    cur = pts_cur_df.set_index("player_id")[["fantasy_points", "games_played"]]
    prev = pts_prev_df.set_index("player_id")[["fantasy_points", "games_played"]]
    all_ids = set(cur.index) | set(prev.index)
    rows = []
    for pid in all_ids:
        cpts, cg = (cur.loc[pid, "fantasy_points"], cur.loc[pid, "games_played"]) if pid in cur.index else (0, 0)
        ppts, pg = (prev.loc[pid, "fantasy_points"], prev.loc[pid, "games_played"]) if pid in prev.index else (0, 0)
        wppg = weighted_ppg(cpts, cg, ppts, pg)
        if wppg is None:
            continue
        rows.append({"player_id": pid, "weighted_ppg": wppg,
                     "cur_season_pts": cpts, "cur_season_games": cg,
                     "prev_season_pts": ppts, "prev_season_games": pg})
    out = pd.DataFrame(rows)
    out = out.merge(roster_df[["gsis_id", "full_name", "team", "fine_position", "birth_date"]],
                     left_on="player_id", right_on="gsis_id", how="left")
    out = out.dropna(subset=["full_name"])
    out["age"] = out["birth_date"].apply(compute_age)
    return out

idp = build_player_value(def_cur, def_prev, roster, "fine_position")
off = build_player_value(off_cur, off_prev, roster, "fine_position")

# Spieler ohne einen einzigen Stat in beiden Saisons (Rookies ohne Snaps, lange Verletzte wie
# Aiyuk) fielen bisher komplett raus. Aufnehmen, wenn sie relevant sind: FantasyPros-Projektion,
# FantasyPros-Dynasty-Rang oder in einem MLD-Kader. Ohne Produktion -> weighted_ppg leer;
# der Wert kommt dann aus Projektion bzw. Dynasty-Rang (oder NA).
def _norm(n):
    n = unicodedata.normalize("NFKD", str(n)).encode("ascii", "ignore").decode()
    return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", __import__("unicodedata").normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower())).strip()

_relevant = set()
for _path, _key in (("data/fantasypros_projections_2026.json", "name"),
                    ("data/fantasypros_dynasty_rankings_2026.json", "name"),
                    ("data/fleaflicker_rosters.json", "player_name")):
    if os.path.exists(_path):
        with open(_path, encoding="utf-8") as f:
            _relevant |= {_norm(x.get(_key)) for x in json.load(f) if x.get(_key)}
_known = set(idp["player_id"]) | set(off["player_id"]) | set(kick_cur["player_id"]) | set(kick_prev["player_id"])
_extra = roster_cur.drop_duplicates("gsis_id")
_extra = _extra[~_extra["gsis_id"].isin(_known) & _extra["full_name"].apply(_norm).isin(_relevant)].copy()
_extra["fine_position"] = _extra["depth_chart_position"].fillna(_extra["position"])
_extra = pd.DataFrame({"player_id": _extra["gsis_id"], "weighted_ppg": np.nan,
                       "cur_season_pts": 0, "cur_season_games": 0, "prev_season_pts": 0, "prev_season_games": 0,
                       "gsis_id": _extra["gsis_id"], "full_name": _extra["full_name"], "team": _extra["team"],
                       "fine_position": _extra["fine_position"], "birth_date": _extra["birth_date"]})
_extra["age"] = _extra["birth_date"].apply(compute_age)
_off_pos = {"QB", "RB", "WR", "TE", "FB", "HB"}
_is_off = _extra["fine_position"].isin(_off_pos)
off = pd.concat([off, _extra[_is_off]], ignore_index=True)
idp = pd.concat([idp, _extra[~_is_off & ~_extra["fine_position"].isin({"K", "P", "LS"})]], ignore_index=True)
print(f"Ohne Stats, aber relevant (Projektion/Rang/MLD-Kader) ergaenzt: {len(_extra)} Spieler")
kick = build_player_value(kick_cur, kick_prev, roster, "fine_position")

# --- IDP: Replacement-Level je Gruppe (DB / EDR-IL / LB). Rang = Durchschnitt
# aus (a) tatsaechlicher Anzahl gerosterter Spieler (kann Spekulations-Horten
# mit einschliessen, tendenziell zu grosszuegig) und (b) Start-Slots + Wildcard-
# Anteil nach flex_share_idp (reine Heuristik, kennt kein echtes Horten, aber
# auch keine echte Nutzung). Mittelwert aus beiden als Kompromiss zwischen den
# beiden Extremen. +1 fuer den Replacement-Referenzpunkt.
from engine.roster_counts import compute_rostered_counts
groups = roster_cfg["position_groups"]
NUM_TEAMS_IDP = roster_cfg["num_teams"]
flex_share_idp = roster_cfg.get("flex_share_idp", {})
_rostered = compute_rostered_counts("data/fleaflicker_rosters.json")
RANK_IDP_BY_GROUP = {}
for g in ["DB", "EDR_IL", "LB"]:
    heuristic_rank = round(NUM_TEAMS_IDP * 2 + NUM_TEAMS_IDP * 1 * flex_share_idp.get(g, 0))
    if _rostered:
        empirical_rank = _rostered.get(g, heuristic_rank)
        RANK_IDP_BY_GROUP[g] = round((empirical_rank + heuristic_rank) / 2) + 1
    else:
        RANK_IDP_BY_GROUP[g] = heuristic_rank  # Fallback, falls Rosterdaten fehlen
print("Tatsaechlich gerosterte Spieler je Gruppe:", _rostered)
print("IDP-Raenge (Durchschnitt aus Rosterzahl + Heuristik, +1):", RANK_IDP_BY_GROUP)

def assign_group(pos, groups):
    for g, positions in groups.items():
        if pos in positions:
            return g
    return None

# Fleaflicker-eigene Positions-Zuordnung ist AUTORITATIV fuer die Gruppierung (nicht
# nflverse depth_chart_position) -- massgeblich ist, welchen Slot ein Spieler in DIESER
# Liga belegen darf, das entscheidet ausschliesslich Fleaflicker (Dominiks Vorgabe).
# Fleaflicker-Labels: CB/S/DB -> DB, EDR/IL/EDR-IL -> EDR_IL, LB -> LB.
# Fallback auf nflverse depth_chart_position, wenn kein Fleaflicker-Match existiert
# (z.B. Namens-Mismatch, oder Spieler nicht im Fleaflicker-Pool).
FLEA_TO_GROUP = {
    "CB": "DB", "S": "DB", "DB": "DB",
    "EDR": "EDR_IL", "IL": "EDR_IL", "EDR/IL": "EDR_IL",
    "LB": "LB",
}

def norm_name(n):
    return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", __import__("unicodedata").normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower())).strip()

flea_group_by_name = {}
flea_path = "data/fleaflicker_players.json"
if os.path.exists(flea_path):
    with open(flea_path, encoding="utf-8") as f:
        flea_players = json.load(f)
    # FetchPlayerListing liefert nur einen Teil des Pools (z.B. fehlt Tuli Tuipulotu, der bei
    # Vienna Seahawks als EDR gerostert ist -> nflverse-Fallback "OLB" -> falsch als LB bewertet).
    # Die Kader-Datei hat Fleaflickers Position fuer jeden gerosterten Spieler -> ergaenzen.
    # Reihenfolge: Roster-Eintraege zuletzt, damit sie bei Namensgleichheit gewinnen.
    _roster_pos_path = "data/fleaflicker_rosters.json"
    if os.path.exists(_roster_pos_path):
        with open(_roster_pos_path, encoding="utf-8") as f:
            _roster_entries = json.load(f)
        flea_players = flea_players + [
            {"name": r["player_name"], "position": r.get("position")}
            for r in _roster_entries if r.get("player_name")
        ]
        print(f"Fleaflicker-Positionen: {len(_roster_entries)} Kader-Eintraege zusaetzlich zur Spielerliste")
    for p in flea_players:
        if not p.get("name"):
            continue
        # Hybrid-Labels (z.B. "WR/CB", "S/EDR"): ersten IDP-relevanten Teil nehmen
        parts = (p.get("position") or "").split("/")
        group = next((FLEA_TO_GROUP[part] for part in parts if part in FLEA_TO_GROUP), None)
        if group:
            flea_group_by_name[norm_name(p["name"])] = group
    print(f"Fleaflicker-Positionsdaten geladen: {len(flea_group_by_name)} IDP-Spieler-Zuordnungen")
else:
    print(f"Keine Fleaflicker-Positionsdatei unter {flea_path} gefunden -- Fallback auf nflverse-Positionen.")

# Feingranulare Fleaflicker-Position (nicht nur die grobe Gruppe) separat erfassen --
# noetig fuer die 5er-Aufteilung (CB/S/EDR/IL/LB) in engine/dynasty_value.py. Ohne das
# wuerde z.B. T.J. Watt (Fleaflicker: "EDR", nflverse fine_position: "OLB") faelschlich
# als off-ball-Linebacker eingestuft -- mit Tackle-lastiger statt Sack-lastiger
# Erwartung bewertet.
FLEA_FINE_POSITIONS = {"CB", "S", "DB", "EDR", "IL", "LB"}
flea_fine_by_name = {}
if os.path.exists(flea_path):
    for p in flea_players:
        if not p.get("name"):
            continue
        parts = (p.get("position") or "").split("/")
        fine = next((part for part in parts if part in FLEA_FINE_POSITIONS), None)
        if fine:
            flea_fine_by_name[norm_name(p["name"])] = fine

idp["norm_name"] = idp["full_name"].apply(norm_name)
idp["idp_group"] = idp["norm_name"].map(flea_group_by_name)
fallback_mask = idp["idp_group"].isna()
idp.loc[fallback_mask, "idp_group"] = idp.loc[fallback_mask, "fine_position"].apply(lambda p: assign_group(p, groups))
print(f"IDP-Gruppierung: {(~fallback_mask).sum()} von {len(idp)} ueber Fleaflicker, "
      f"{fallback_mask.sum()} ueber nflverse-Fallback")
idp["flea_fine_position"] = idp["norm_name"].map(flea_fine_by_name)
idp = idp.drop(columns=["norm_name"])
idp = idp.dropna(subset=["idp_group"])

repl_levels = {}
for g in ["DB", "EDR_IL", "LB"]:
    sub = idp[idp["idp_group"] == g]
    repl_levels[g] = replacement_level(sub, "weighted_ppg", RANK_IDP_BY_GROUP[g])
print("Replacement-Level (IDP):", repl_levels)

idp["replacement_level"] = idp["idp_group"].map(repl_levels)
idp["vorp"] = idp["weighted_ppg"] - idp["replacement_level"]
idp["dynasty_trailing_value"] = idp.apply(lambda r: dynasty_trailing_value(r["vorp"], r["age"]), axis=1)
# Fleaflickers feingranulare Position hat Vorrang -- nur bei fehlendem Fleaflicker-
# Match auf nflverse fine_position zurueckfallen (z.B. bei Namens-Mismatch).
idp["position"] = idp["flea_fine_position"].where(idp["flea_fine_position"].notna(), idp["fine_position"])
idp = idp.drop(columns=["flea_fine_position"])

# --- Offense: Replacement-Level je Position. Rang = Durchschnitt aus (a) echter
# Rosterzahl und (b) Start-Slots + Flex-Anteil nach flex_share_offense (Heuristik),
# gleiches Prinzip wie bei IDP -- Kompromiss zwischen "zaehlt Horten mit" und
# "kennt keine echte Nutzung". Siehe engine/roster_counts.py.
NUM_TEAMS = roster_cfg["num_teams"]
slots = roster_cfg["starting_slots"]
flex_share = roster_cfg["flex_share_offense"]
off_ranks = {}
for pos in ["QB", "RB", "WR", "TE"]:
    if pos == "QB":
        heuristic_rank = NUM_TEAMS * slots["QB"]
    else:
        heuristic_rank = round(NUM_TEAMS * (slots[pos] + slots["FLEX_RB_WR_TE"] * flex_share[pos]))
    if _rostered:
        empirical_rank = _rostered.get(pos, heuristic_rank)
        off_ranks[pos] = round((empirical_rank + heuristic_rank) / 2) + 1
    else:
        off_ranks[pos] = heuristic_rank  # Fallback, falls Rosterdaten fehlen
print("Replacement-Ranks (Offense, Durchschnitt Rosterzahl+Heuristik, +1):", off_ranks)

off["position"] = off["fine_position"].where(off["fine_position"].isin(["QB", "RB", "WR", "TE"]), off["fine_position"])
off = off[off["position"].isin(["QB", "RB", "WR", "TE"])]

repl_off = {}
for pos, rank in off_ranks.items():
    sub = off[off["position"] == pos]
    repl_off[pos] = replacement_level(sub, "weighted_ppg", rank)
print("Replacement-Level (Offense):", repl_off)

off["replacement_level"] = off["position"].map(repl_off)
off["vorp"] = off["weighted_ppg"] - off["replacement_level"]
off["dynasty_trailing_value"] = off.apply(lambda r: dynasty_trailing_value(r["vorp"], r["age"]), axis=1)

# --- Kicker: eigener Rang (16 Teams x 1 Slot), Sonderbehandlung siehe Stolperstein B ---
kick["position"] = "K"
repl_k = replacement_level(kick, "weighted_ppg", NUM_TEAMS)
kick["replacement_level"] = repl_k
kick["vorp"] = kick["weighted_ppg"] - repl_k
# Kicker-Sonderfall: Markt behandelt K praktisch als wertlos -> VORP stark gedaempft statt
# der vollen Formel folgen (kaum Alterskurve/Varianz, s. Stolperstein B)
kick["dynasty_trailing_value"] = (kick["vorp"] * 0.15).round(3)

value_table = pd.concat([
    idp[["player_id", "full_name", "position", "team", "age", "weighted_ppg",
         "replacement_level", "vorp", "dynasty_trailing_value"]],
    off[["player_id", "full_name", "position", "team", "age", "weighted_ppg",
         "replacement_level", "vorp", "dynasty_trailing_value"]],
    kick[["player_id", "full_name", "position", "team", "age", "weighted_ppg",
          "replacement_level", "vorp", "dynasty_trailing_value"]],
], ignore_index=True)

# --- Projected VORP (FantasyPros, nur Offense) als eigene Spalte dazumergen ---
# Getrennt von dynasty_trailing_value gehalten (Job 1 = Vergangenheit, Job 2 = Zukunft,
# nie verschmolzen). Fehlt die Projektionsdatei (z.B. kein API-Key gesetzt), bleibt die
# Spalte einfach leer -- kein Blocker fuer den Rest der Pipeline.
value_table["proj_ppg"] = None
value_table["proj_vorp"] = None
fp_path = "data/fantasypros_projections_2026.json"
if os.path.exists(fp_path):
    from engine.integrate_projections import build_projected_vorp
    proj = build_projected_vorp(fp_path, roster_cfg, flea_group_by_name=flea_group_by_name)
    proj["norm_name"] = proj["name"].apply(lambda n: re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", __import__("unicodedata").normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower())).strip())
    value_table["norm_name"] = value_table["full_name"].apply(lambda n: re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", __import__("unicodedata").normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower())).strip())
    # Nach norm_name deduplizieren (kann trotz vorherigem Dedup noch Kollisionen
    # geben, z.B. Spieler, die FantasyPros unter zwei Positionen fuehrt) --
    # hoechster proj_vorp gewinnt, sonst crasht der Lookup unten.
    dupe_names = proj[proj.duplicated("norm_name", keep=False)]
    if len(dupe_names):
        print(f"  {dupe_names['norm_name'].nunique()} Namens-Kollisionen im Projektions-Datensatz "
              f"(z.B. Spieler unter mehreren Positionen) -- behalte jeweils den hoechsten proj_vorp")
    proj = proj.sort_values("proj_vorp", ascending=False).drop_duplicates(subset=["norm_name"], keep="first")
    proj_lookup = proj.set_index("norm_name")[["proj_ppg", "proj_vorp"]]
    value_table["proj_ppg"] = value_table["norm_name"].map(proj_lookup["proj_ppg"])
    value_table["proj_vorp"] = value_table["norm_name"].map(proj_lookup["proj_vorp"])
    value_table = value_table.drop(columns=["norm_name"])
    print(f"Projected VORP gemergt: {value_table['proj_vorp'].notna().sum()} von {len(value_table)} Spielern haben eine FantasyPros-Projektion")
else:
    print(f"Keine Projektionsdatei unter {fp_path} gefunden -- proj_vorp bleibt leer (kein Blocker).")

# --- Dynasty-Wert: Offense UND IDP jetzt auf dem gleichen SCR-System (SCR + Alter +
# Draft-Kapital, KEIN Trailing-Fallback mehr -- Dominiks ausdrueckliche Vorgabe).
# Nur noch K bleibt auf dem alten Trailing-Mechanismus (keine FantasyPros-Projektion
# fuer Kicker vorhanden, kein Dynasty-Rang-Konzept fuer die Position sinnvoll).
from engine.dynasty_value import OFFENSE_GROUPS, IDP_GROUPS
OFFENSE_POSITIONS = [p for grp in OFFENSE_GROUPS.values() for p in grp[0]]
IDP_POSITIONS = [p for grp in IDP_GROUPS.values() for p in grp[0]]
SCR_POSITIONS = OFFENSE_POSITIONS + IDP_POSITIONS
dynasty_path = "data/fantasypros_dynasty_rankings_2026.json"

value_table["SCR"] = None
value_table["scr_source"] = "none"
value_table["years_exp"] = None
value_table["dynasty_value"] = None

if os.path.exists(dynasty_path):
    from engine.dynasty_value import build_offense_dynasty_values, build_idp_dynasty_values
    with open(dynasty_path, encoding="utf-8") as f:
        dynasty_rankings = json.load(f)

    off_result = build_offense_dynasty_values(value_table, dynasty_rankings, roster, CUR_SEASON)
    off_mask = value_table["position"].isin(OFFENSE_POSITIONS)
    for col in ["SCR", "scr_source", "dynasty_value", "years_exp"]:
        value_table.loc[off_mask, col] = off_result.loc[off_mask, col]
    print(f"Offense Dynasty-Value gebaut: "
          f"{(value_table.loc[off_mask,'scr_source']=='projected').sum()} projected, "
          f"{(value_table.loc[off_mask,'scr_source']=='rank_imputed').sum()} rank_imputed, "
          f"{(value_table.loc[off_mask,'scr_source']=='none').sum()} ohne jeden Wert (NA)")

    idp_result = build_idp_dynasty_values(value_table, dynasty_rankings, roster, CUR_SEASON)
    idp_mask = value_table["position"].isin(IDP_POSITIONS)
    for col in ["SCR", "scr_source", "dynasty_value", "years_exp"]:
        value_table.loc[idp_mask, col] = idp_result.loc[idp_mask, col]
    print(f"IDP Dynasty-Value gebaut: "
          f"{(value_table.loc[idp_mask,'scr_source']=='projected').sum()} projected, "
          f"{(value_table.loc[idp_mask,'scr_source']=='rank_imputed').sum()} rank_imputed, "
          f"{(value_table.loc[idp_mask,'scr_source']=='none').sum()} ohne jeden Wert (NA)")
else:
    print(f"Keine Dynasty-Rankings-Datei unter {dynasty_path} -- Dynasty-Value bleibt leer.")

# primary_value: Offense+IDP = dynasty_value (neues System, oder NaN falls scr_source='none').
# Nur K = weiterhin dynasty_trailing_value (altes System).
non_scr_mask = ~value_table["position"].isin(SCR_POSITIONS)
value_table["primary_value"] = value_table["dynasty_value"]
value_table.loc[non_scr_mask, "primary_value"] = value_table.loc[non_scr_mask, "dynasty_trailing_value"]
value_table["primary_value_source"] = value_table["scr_source"]
value_table.loc[non_scr_mask, "primary_value_source"] = "trailing"

value_table = value_table.sort_values("primary_value", ascending=False)
value_table.to_csv("output/value_table.csv", index=False)
value_table.to_json("output/value_table.json", orient="records", indent=2)
print(f"\nFertig: {len(value_table)} Spieler in output/value_table.csv / .json")
print(value_table.head(20).to_string(index=False))
