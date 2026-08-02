"""
Baut die vollstaendige Trailing-Production-Value-Tabelle fuer alle Spieler
(IDP + Offense + Kicker) aus nflverse-Rohdaten.

Ablauf:
  1. Rosters laden (Position, Alter, Team) fuer 2025 + 2024
  2. Defense/Offense/Kicking-Rohkategorien aggregieren (PBP fuer 2025,
     offizielles Release fuer 2024 -- Release-Files hinken einer Saison hinterher)
  3. Scoring-Config anwenden -> Fantasy-Punkte pro Saison
  4. Weighted PPG (65/35) -> Replacement-Level/VORP -> Age-Curve
  5. Output: output/value_table.csv + output/value_table.json
"""
import sys
import os
import re
import json
import pandas as pd
import numpy as np

sys.path.insert(0, ".")
from engine.aggregate_defense import aggregate_defense_from_pbp, from_official_release as def_official
from engine.aggregate_offense import aggregate_offense_from_pbp, from_official_release as off_official
from engine.aggregate_kicking import aggregate_kicking_from_pbp
from engine.scoring import load_scoring_config, score_defense_row, score_offense_row, score_kicking_row
from engine.value_engine import weighted_ppg, replacement_level, compute_age, dynasty_trailing_value

DATA = "data"
CUR_SEASON, PREV_SEASON = 2025, 2024

print("Lade Rosters ...")
roster_cur = pd.read_csv(f"{DATA}/roster_2025.csv.gz")
roster_prev = pd.read_csv(f"{DATA}/roster_2024.csv.gz")
# neuestes Rosterbild pro Spieler (fuer aktuelle Position/Team/Alter) bevorzugt aus 2025,
# Fallback 2024 fuer Spieler, die 2025 nicht mehr aktiv gerostert waren
roster = pd.concat([roster_cur, roster_prev]).sort_values("season", ascending=False)
roster = roster.drop_duplicates(subset=["gsis_id"], keep="first")
roster["fine_position"] = roster["depth_chart_position"].fillna(roster["position"])

cfg = load_scoring_config("scoring/scoring_config.json")
with open("scoring/roster_config.json") as f:
    roster_cfg = json.load(f)

print("Aggregiere Defense ...")
pbp_cur = pd.read_csv(f"{DATA}/pbp_2025.csv.gz", low_memory=False)
def_cur = aggregate_defense_from_pbp(pbp_cur, CUR_SEASON)
def_prev_release = pd.read_csv(f"{DATA}/player_stats_def_2025.csv.gz")
def_prev = def_official(def_prev_release, PREV_SEASON)

print("Aggregiere Offense ...")
off_cur = aggregate_offense_from_pbp(pbp_cur, CUR_SEASON)
off_prev_release = pd.read_csv(f"{DATA}/player_stats_offense.csv.gz")
off_prev = off_official(off_prev_release, PREV_SEASON)

print("Aggregiere Kicking ...")
pbp_prev = pd.read_csv(f"{DATA}/pbp_2024.csv.gz", low_memory=False)
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
kick = build_player_value(kick_cur, kick_prev, roster, "fine_position")

# --- IDP: Replacement-Level je Gruppe (DB / EDR-IL / LB), Rang 32 (2 Slots x 16 Teams) ---
groups = roster_cfg["position_groups"]
RANK_IDP = roster_cfg["num_teams"] * 2  # 2 Start-Slots je Gruppe

def assign_group(pos, groups):
    for g, positions in groups.items():
        if pos in positions:
            return g
    return None

idp["idp_group"] = idp["fine_position"].apply(lambda p: assign_group(p, groups))
idp = idp.dropna(subset=["idp_group"])

repl_levels = {}
for g in ["DB", "EDR_IL", "LB"]:
    sub = idp[idp["idp_group"] == g]
    repl_levels[g] = replacement_level(sub, "weighted_ppg", RANK_IDP)
print("Replacement-Level (IDP):", repl_levels)

idp["replacement_level"] = idp["idp_group"].map(repl_levels)
idp["vorp"] = idp["weighted_ppg"] - idp["replacement_level"]
idp["dynasty_trailing_value"] = idp.apply(lambda r: dynasty_trailing_value(r["vorp"], r["age"]), axis=1)
idp["position"] = idp["fine_position"]

# --- Offense: Replacement-Level je Position, Flex-Slot heuristisch verteilt (Stolperstein A) ---
NUM_TEAMS = roster_cfg["num_teams"]
slots = roster_cfg["starting_slots"]
flex_share = roster_cfg["flex_share_offense"]

off_ranks = {
    "QB": NUM_TEAMS * slots["QB"],
    "RB": round(NUM_TEAMS * (slots["RB"] + slots["FLEX_RB_WR_TE"] * flex_share["RB"])),
    "WR": round(NUM_TEAMS * (slots["WR"] + slots["FLEX_RB_WR_TE"] * flex_share["WR"])),
    "TE": round(NUM_TEAMS * (slots["TE"] + slots["FLEX_RB_WR_TE"] * flex_share["TE"])),
}
print("Replacement-Ranks (Offense, inkl. Flex-Heuristik):", off_ranks)

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
    proj = build_projected_vorp(fp_path, roster_cfg)
    proj["norm_name"] = proj["name"].apply(lambda n: re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", n.lower())).strip())
    value_table["norm_name"] = value_table["full_name"].apply(lambda n: re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", n.lower())).strip())
    proj_lookup = proj.set_index("norm_name")[["proj_ppg", "proj_vorp"]]
    value_table["proj_ppg"] = value_table["norm_name"].map(proj_lookup["proj_ppg"])
    value_table["proj_vorp"] = value_table["norm_name"].map(proj_lookup["proj_vorp"])
    value_table = value_table.drop(columns=["norm_name"])
    print(f"Projected VORP gemergt: {value_table['proj_vorp'].notna().sum()} von {len(value_table)} Spielern haben eine FantasyPros-Projektion")
else:
    print(f"Keine Projektionsdatei unter {fp_path} gefunden -- proj_vorp bleibt leer (kein Blocker).")

value_table = value_table.sort_values("dynasty_trailing_value", ascending=False)
value_table.to_csv("output/value_table.csv", index=False)
value_table.to_json("output/value_table.json", orient="records", indent=2)
print(f"\nFertig: {len(value_table)} Spieler in output/value_table.csv / .json")
print(value_table.head(20).to_string(index=False))
