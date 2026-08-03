"""
Verarbeitet die von engine/fetch_projections.py geladenen FantasyPros-Rohkategorien
zu einer eigenen "Projektions-VORP"-Spalte -- fuer OFFENSE UND DEFENSE nach exakt
derselben Formel, damit beide Seiten ehrlich vergleichbar sind:

  Rohkategorien -> unser Scoring-Kern -> projizierte Saison-Punkte -> /17 Spiele
  -> Projected PPG -> Replacement-Level AUS DEM PROJEKTIONS-POOL SELBST -> VORP

WICHTIGER METHODIK-ENTSCHEID (Dominiks Vorgabe): Replacement-Level wird NICHT aus
Trailing-Daten uebernommen, sondern direkt aus der projizierten PPG-Verteilung des
jeweiligen Positions-Pools berechnet. Grund: ein Rookie ohne jede Trailing-Historie
hat trotzdem einen echten, projektionsbasierten Wert -- die alte Fallback-auf-
Trailing-Logik haette ihn faelschlich auf ~0 gesetzt. Trailing Value dient nur noch
zwei Zwecken: (1) Kalibrierungs-Check (korreliert Projected sinnvoll mit dem, was
tatsaechlich passiert ist?), (2) Notfall-Fallback fuer Spieler ohne jede FantasyPros-
Projektion (tiefste Bank), damit sie nicht komplett aus dem Calculator verschwinden.

Nicht abgedeckt: Kicker (keine FG-Distanz-Buckets in der FantasyPros-Response,
kein sauberer Match zu unserer distanzabhaengigen Scoring-Config moeglich).
"""
import json
import re
import sys
import pandas as pd

sys.path.insert(0, ".")
from engine.scoring import load_scoring_config, score_offense_row, score_defense_row
from engine.value_engine import replacement_level

GAMES_ASSUMED = 17  # FantasyPros liefert Saison-Summen, keine Spiele-Anzahl -- volle Saison angenommen

# FantasyPros-Abfrage-Position -> unsere IDP-Gruppe (siehe scoring/roster_config.json)
FP_DEFENSE_TO_GROUP = {"LB": "LB", "DB": "DB", "DL": "EDR_IL"}
OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE"}


def load_projections(path: str) -> pd.DataFrame:
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    df = pd.DataFrame(rows)
    # FantasyPros liefert vereinzelt echte Duplikate (~7% der Eintraege, gleicher
    # Name+Position, identische Werte) -- vor der Replacement-Level-Berechnung
    # entfernen, sonst zaehlen diese Spieler doppelt in der Baseline.
    before = len(df)
    df = df.drop_duplicates(subset=["name", "position"], keep="first")
    if len(df) < before:
        print(f"  {before - len(df)} Duplikate aus FantasyPros-Rohdaten entfernt "
              f"({before} -> {len(df)})")
    return df


def compute_projected_ppg(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    is_offense = df["position"].isin(OFFENSE_POSITIONS)
    is_defense = df["position"].isin(FP_DEFENSE_TO_GROUP.keys())

    df["proj_season_pts"] = float("nan")
    if is_offense.any():
        df.loc[is_offense, "proj_season_pts"] = df.loc[is_offense].apply(
            lambda r: score_offense_row(r, cfg), axis=1
        )
    if is_defense.any():
        df.loc[is_defense, "proj_season_pts"] = df.loc[is_defense].apply(
            lambda r: score_defense_row(r, cfg), axis=1
        )
    # Kicker (K) bleiben aussen vor -> proj_season_pts bleibt NaN, faellt beim
    # dropna() in build_projected_vorp raus, kein Projected-VORP fuer K.

    df["proj_ppg"] = df["proj_season_pts"] / GAMES_ASSUMED
    return df


def build_projected_vorp(fp_json_path: str, roster_cfg: dict, flea_group_by_name: dict = None) -> pd.DataFrame:
    """Gibt ein DataFrame mit [name, position, group, proj_ppg, proj_replacement,
    proj_vorp] zurueck -- Offense UND Defense, identische Formel.

    flea_group_by_name (optional): {normalisierter Name: Fleaflicker-Gruppe (DB/EDR_IL/LB)}.
    Ueberschreibt FantasyPros' EIGENE Positions-Klassifikation fuer Defense-Spieler,
    BEVOR Replacement-Level berechnet wird -- noetig, weil FantasyPros z.B. T.J. Watt
    (Fleaflicker: "EDR", primaer Pass-Rush) selbst als "LB" fuehrt und ihn damit gegen
    tackle-lastige Linebacker-Erwartung statt sack-lastige Edge-Rusher-Erwartung
    bewerten wuerde. Ohne Override greift FantasyPros' eigenes Label.
    """
    cfg = load_scoring_config("scoring/scoring_config.json")
    proj = load_projections(fp_json_path)
    proj = compute_projected_ppg(proj, cfg)
    proj = proj.dropna(subset=["proj_ppg"])

    if flea_group_by_name:
        GROUP_TO_FP_POS = {v: k for k, v in FP_DEFENSE_TO_GROUP.items()}  # DB/EDR_IL/LB -> DB/DL/LB
        def _norm(n):
            return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", str(n).lower())).strip()
        is_def = proj["position"].isin(FP_DEFENSE_TO_GROUP.keys())
        overridden = 0
        for idx in proj[is_def].index:
            flea_group = flea_group_by_name.get(_norm(proj.at[idx, "name"]))
            if flea_group and flea_group in GROUP_TO_FP_POS:
                new_pos = GROUP_TO_FP_POS[flea_group]
                if new_pos != proj.at[idx, "position"]:
                    proj.at[idx, "position"] = new_pos
                    overridden += 1
        if overridden:
            print(f"  {overridden} Defense-Spieler: FantasyPros-Position durch "
                  f"Fleaflicker-autoritative Gruppe ueberschrieben (z.B. Edge-Rusher, "
                  f"die FP als 'LB' fuehrt).")

    NUM_TEAMS = roster_cfg["num_teams"]
    slots = roster_cfg["starting_slots"]

    # Ranks (Offense UND Defense): tatsaechliche Anzahl gerosterter Spieler
    # (aus den echten Fleaflicker-Rosterdaten) + 1 -- ersetzt die bisherigen
    # Flex-/Wildcard-Anteil-Heuristiken durch echte Zahlen. Siehe engine/roster_counts.py.
    from engine.roster_counts import compute_rostered_counts
    _rostered = compute_rostered_counts("data/fleaflicker_rosters.json")

    if _rostered:
        off_ranks = {pos: _rostered.get(pos, NUM_TEAMS * slots[pos]) + 1 for pos in ["QB", "RB", "WR", "TE"]}
        def_rank_by_group = {g: _rostered.get(g, NUM_TEAMS * 2) + 1 for g in ["DB", "EDR_IL", "LB"]}
    else:
        flex_share = roster_cfg["flex_share_offense"]
        off_ranks = {
            "QB": NUM_TEAMS * slots["QB"],
            "RB": round(NUM_TEAMS * (slots["RB"] + slots["FLEX_RB_WR_TE"] * flex_share["RB"])),
            "WR": round(NUM_TEAMS * (slots["WR"] + slots["FLEX_RB_WR_TE"] * flex_share["WR"])),
            "TE": round(NUM_TEAMS * (slots["TE"] + slots["FLEX_RB_WR_TE"] * flex_share["TE"])),
        }
        flex_share_idp = roster_cfg.get("flex_share_idp", {})
        def_rank_by_group = {
            g: round(NUM_TEAMS * 2 + NUM_TEAMS * 1 * flex_share_idp.get(g, 0))
            for g in ["DB", "EDR_IL", "LB"]
        }
    print(f"  Ranks (echte Rosterzahl + 1): Offense={off_ranks}, Defense={def_rank_by_group}")

    out_rows = []

    for pos, rank in off_ranks.items():
        sub = proj[proj["position"] == pos]
        if len(sub) == 0:
            continue
        repl = replacement_level(sub, "proj_ppg", rank)
        for _, r in sub.iterrows():
            out_rows.append({
                "name": r["name"], "position": pos, "group": pos,
                "proj_ppg": round(r["proj_ppg"], 3),
                "proj_replacement": round(repl, 3),
                "proj_vorp": round(r["proj_ppg"] - repl, 3),
            })

    for fp_pos, group in FP_DEFENSE_TO_GROUP.items():
        sub = proj[proj["position"] == fp_pos]
        if len(sub) == 0:
            continue
        repl = replacement_level(sub, "proj_ppg", def_rank_by_group[group])
        for _, r in sub.iterrows():
            out_rows.append({
                "name": r["name"], "position": fp_pos, "group": group,
                "proj_ppg": round(r["proj_ppg"], 3),
                "proj_replacement": round(repl, 3),
                "proj_vorp": round(r["proj_ppg"] - repl, 3),
            })

    return pd.DataFrame(out_rows)


if __name__ == "__main__":
    import json as _json
    with open("scoring/roster_config.json") as f:
        roster_cfg = _json.load(f)
    result = build_projected_vorp("data/fantasypros_projections_2026.json", roster_cfg)
    print(f"{len(result)} Spieler mit Projected VORP berechnet (Offense + Defense)")
    print(result.groupby("group")["proj_vorp"].agg(["count", "mean", "max"]).round(2))
    print()
    print(result.sort_values("proj_vorp", ascending=False).head(10).to_string(index=False))
    result.to_csv("output/projected_vorp.csv", index=False)
