"""
Verarbeitet die von engine/fetch_projections.py geladenen FantasyPros-Rohkategorien
zu einer eigenen "Projektions-VORP"-Spalte -- getrennt von der Trailing Production
Value, nie vermischt (siehe Projekt-Prinzip: Job 1 = Vergangenheit/nflverse,
Job 2 = Zukunft/Projektion, zwei Spalten nebeneinander).

Methodik identisch zur Trailing-Value-Berechnung, nur mit projizierten statt
gemessenen Rohkategorien als Input:
  Rohkategorien -> unser Scoring-Kern -> projizierte Saison-Punkte -> /17 Spiele
  -> Projected PPG -> Replacement-Level (gleicher Rang wie bei Trailing) -> VORP

Nur Offense (QB/RB/WR/TE/K) -- FantasyPros liefert kein IDP. IDP-Spieler haben
also immer eine leere projected_vorp-Spalte, das ist by design so.
"""
import json
import sys
import pandas as pd

sys.path.insert(0, ".")
from engine.scoring import load_scoring_config, score_offense_row, score_kicking_row
from engine.value_engine import replacement_level

GAMES_ASSUMED = 17  # FantasyPros liefert Saison-Summen, keine Spiele-Anzahl -- volle Saison angenommen


def load_projections(path: str) -> pd.DataFrame:
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return pd.DataFrame(rows)


def compute_projected_ppg(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    is_kicker = df["position"] == "K"

    df["proj_season_pts"] = 0.0
    if (~is_kicker).any():
        df.loc[~is_kicker, "proj_season_pts"] = df.loc[~is_kicker].apply(
            lambda r: score_offense_row(r, cfg), axis=1
        )
    if is_kicker.any():
        # FantasyPros liefert fuer K keine FG-Distanz-Buckets, nur fg_made gesamt --
        # kein sauberer Match zu unserer distanzabhaengigen Scoring-Config moeglich.
        # Kicker bleiben deshalb ohne Projected-VORP (NaN), fallen auf Trailing-Value zurueck.
        df.loc[is_kicker, "proj_season_pts"] = float("nan")

    df["proj_ppg"] = df["proj_season_pts"] / GAMES_ASSUMED
    return df


def build_projected_vorp(fp_json_path: str, roster_cfg: dict) -> pd.DataFrame:
    """Gibt ein DataFrame mit [name, position, proj_ppg, proj_replacement, proj_vorp] zurueck."""
    cfg = load_scoring_config("scoring/scoring_config.json")
    proj = load_projections(fp_json_path)
    proj = compute_projected_ppg(proj, cfg)
    proj = proj.dropna(subset=["proj_ppg"])

    NUM_TEAMS = roster_cfg["num_teams"]
    slots = roster_cfg["starting_slots"]
    flex_share = roster_cfg["flex_share_offense"]
    ranks = {
        "QB": NUM_TEAMS * slots["QB"],
        "RB": round(NUM_TEAMS * (slots["RB"] + slots["FLEX_RB_WR_TE"] * flex_share["RB"])),
        "WR": round(NUM_TEAMS * (slots["WR"] + slots["FLEX_RB_WR_TE"] * flex_share["WR"])),
        "TE": round(NUM_TEAMS * (slots["TE"] + slots["FLEX_RB_WR_TE"] * flex_share["TE"])),
    }

    out_rows = []
    for pos, rank in ranks.items():
        sub = proj[proj["position"] == pos]
        if len(sub) == 0:
            continue
        repl = replacement_level(sub, "proj_ppg", rank)
        for _, r in sub.iterrows():
            out_rows.append({
                "name": r["name"], "position": pos,
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
    print(f"{len(result)} Spieler mit Projected VORP berechnet")
    print(result.sort_values("proj_vorp", ascending=False).head(10).to_string(index=False))
    result.to_csv("output/projected_vorp.csv", index=False)
