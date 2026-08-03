"""
Dynasty-Wert-Berechnung fuer Offense (QB/RB/WR/TE) und IDP (LB/CB/S/EDR/IL) --
ersetzt den alten Trailing-VORP-Fallback komplett. Trailing-Produktion fliesst
hier NICHT mehr ein (Dominiks ausdrueckliche Vorgabe: Trailing verzerrt zu
sehr, speziell bei Spielern mit wenigen Snaps/unklarer Rolle).

SCR (Scoring) = projizierte VORP aus FantasyPros-Rohkategorien durch unser
eigenes Scoring gerechnet. Drei Faelle pro Spieler:

  1. Hat er eine FantasyPros-Saison-Projektion? -> SCR = proj_vorp direkt.
  2. Keine Projektion, aber ein FantasyPros-Dynasty-Rang vorhanden?
     -> SCR wird aus einer EMPIRISCHEN Kurve (Rang-Perzentil -> rohe SCR,
     gebaut nur aus Spielern mit echten Daten) abgelesen. WICHTIG: die Kurve
     bildet rohe SCR ab, NICHT den fertigen (bereits alters-/draft-
     adjustierten) Endwert -- sonst wuerde das Alter doppelt bestraft
     (Fund bei Joe Mixon: Rang ist schon alters-/situationsbereinigt,
     nochmal durch unsere eigene Alterskurve teilen war ein Fehler).
  3. Weder Projektion noch Rang -> SCR = NaN. Kein Wert, kein Fallback auf
     Trailing. Im Calculator: Spieler bleibt auffindbar, aber NA/rot/nicht
     auswaehlbar.

Auf die SCR (Faelle 1+2) werden anschliessend Alter- und Draft-Kapital-
Modifikatoren angewendet -- EINMAL, nicht nochmal doppelt fuer Fall 2.

Formel (gegen FantasyPros Dynasty-ECR kalibriert):
  production = SCR * age_mult(age)      wenn SCR >= 0
             = SCR / age_mult(age)      wenn SCR <  0   (reziprok, keine Kante bei 0)
  draft_bonus = draft_scale * draft_capital_score * clip(1 - years_exp/draft_decay, 0, 1)
  dynasty_value = production + draft_bonus

age_mult(age) = clip(1 + (peak - age) * rate, 0.5, 1.6), peak/rate pro Gruppe fest.

IDP-Besonderheit: FantasyPros' Dynasty-Rang kennt nur LB/DB/DL (nicht CB/S
oder EDR/IL getrennt) -- deshalb ordnet IDP_GROUPS mehrere unserer Gruppen auf
denselben FP-Pool ab (CB+S -> "DB", EDR+IL -> "DL"). Peak-Alter pro Gruppe
kommt aus externer Aging-Curve-Recherche, bleibt eigenstaendig. Rate/Draft-
Parameter sind gegen FP kalibriert -- ausser bei CB und IL, wo die Stichprobe
mit FP-Rang zu klein war (n=4 bzw. n=14) fuer ein eigenstaendiges, verlaess-
liches Fitting: die uebernehmen die gefitteten Werte der naechstverwandten,
groesseren Gruppe (CB<-S, IL<-EDR), nur der eigene, extern recherchierte
Peak bleibt jeweils eigenstaendig.
"""
import json
import re
import numpy as np
import pandas as pd

MAX_DRAFT_OVERALL = 262

# Gruppe -> (unsere Positionslabels, FantasyPros-Positionscode fuer Rang-Abgleich)
OFFENSE_GROUPS = {
    "QB": (["QB"], "QB"),
    "RB": (["RB"], "RB"),
    "WR": (["WR"], "WR"),
    "TE": (["TE"], "TE"),
}
IDP_GROUPS = {
    "LB":  (["LB", "ILB", "OLB", "MLB"], "LB"),
    "S":   (["FS", "SS"], "DB"),
    "CB":  (["CB"], "DB"),
    "EDR": (["DE"], "DL"),
    "IL":  (["DT", "NT"], "DL"),
}

# Peak-Alter aus externer Aging-Curve-Forschung (nicht gefittet) --
# Rate und Draft-Parameter GEGEN FantasyPros Dynasty-ECR kalibriert.
FINAL_PARAMS = {
    "QB": {"peak": 30, "rate": 0.0004, "draft_scale": 8.37, "draft_decay": 4.34},
    "RB": {"peak": 26, "rate": 0.0203, "draft_scale": 11.60, "draft_decay": 5.00},
    "WR": {"peak": 26, "rate": 0.0523, "draft_scale": 2.24, "draft_decay": 4.52},
    "TE": {"peak": 27, "rate": 0.0332, "draft_scale": 2.28, "draft_decay": 4.22},
    "LB":  {"peak": 26, "rate": 0.0159, "draft_scale": 0.00, "draft_decay": 4.49},
    "S":   {"peak": 27, "rate": 0.0413, "draft_scale": 3.50, "draft_decay": 2.50},
    "CB":  {"peak": 25, "rate": 0.0413, "draft_scale": 3.50, "draft_decay": 2.50},
    "EDR": {"peak": 26, "rate": 0.0325, "draft_scale": 1.51, "draft_decay": 1.00},
    "IL":  {"peak": 28, "rate": 0.0325, "draft_scale": 1.51, "draft_decay": 1.00},
}


def norm_name(n):
    return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", str(n).lower())).strip()


def age_mult(age, peak, rate):
    return np.clip(1 + (peak - age) * rate, 0.5, 1.6)


def apply_modifiers(scr, age, draft_capital_score, years_exp, p):
    m = age_mult(age, p["peak"], p["rate"])
    production = np.where(scr >= 0, scr * m, scr / m)
    bonus = p["draft_scale"] * draft_capital_score * np.clip(1 - years_exp / p["draft_decay"], 0, 1)
    return production + bonus


def compute_draft_capital(roster_df: pd.DataFrame, current_season: int) -> pd.DataFrame:
    """Draft-Kapital-Score (0-1, Pick 1 = 1.0) + Jahre-in-der-Liga aus Rosterdaten."""
    r = roster_df.sort_values("season", ascending=False).drop_duplicates("norm_name").copy()
    r["draft_capital_score"] = r["draft_number"].apply(
        lambda x: round(max(0.0, 1 - (x - 1) / MAX_DRAFT_OVERALL), 3) if pd.notna(x) else 0.0
    )
    r["years_exp"] = current_season - r["entry_year"]
    return r.set_index("norm_name")[["draft_capital_score", "years_exp"]]


def build_dynasty_values(value_table: pd.DataFrame, dynasty_rankings: list, roster_df: pd.DataFrame,
                          group_defs: dict, params: dict, current_season: int = 2026) -> pd.DataFrame:
    """
    Generisch fuer Offense- oder IDP-Gruppen nutzbar.
    value_table: muss 'full_name', 'position', 'age', 'proj_vorp' enthalten (proj_vorp
                 darf NaN sein -- kommt aus der FantasyPros-Projektions-Integration).
    dynasty_rankings: rohe Liste von dicts mit 'name', 'position', 'rank_ecr'.
    group_defs: {gruppe: (unsere_positionen, fp_position)}
    params: {gruppe: {peak, rate, draft_scale, draft_decay}}
    Gibt value_table zurueck, ergaenzt um: SCR, scr_source, dynasty_value.
    """
    vt = value_table.copy()
    vt["norm_name"] = vt["full_name"].apply(norm_name)

    dyn_df = pd.DataFrame(dynasty_rankings)
    dyn_df["norm_name"] = dyn_df["name"].apply(norm_name)

    draft_lookup = compute_draft_capital(roster_df.assign(norm_name=roster_df["full_name"].apply(norm_name)),
                                          current_season)
    vt["draft_capital_score"] = vt["norm_name"].map(draft_lookup["draft_capital_score"]).fillna(0)
    vt["years_exp"] = vt["norm_name"].map(draft_lookup["years_exp"]).fillna(10)

    vt["SCR"] = np.nan
    vt["scr_source"] = "none"
    vt["dynasty_value"] = np.nan

    for group, (our_positions, fp_pos) in group_defs.items():
        p = params[group]
        pos_mask = vt["position"].isin(our_positions)
        sub_dyn = dyn_df[dyn_df["position"] == fp_pos]

        merged = vt.loc[pos_mask, ["norm_name"]].merge(
            sub_dyn[["norm_name", "rank_ecr"]], on="norm_name", how="left"
        )
        n_ranked = merged["rank_ecr"].notna().sum()
        fp_pct = pd.Series(np.nan, index=merged.index)
        if n_ranked > 1:
            ranked_mask = merged["rank_ecr"].notna()
            fp_pct.loc[ranked_mask] = (
                1 - (merged.loc[ranked_mask, "rank_ecr"].rank(ascending=True) - 1) / (n_ranked - 1)
            ) * 100
        vt.loc[pos_mask, "fp_pct"] = fp_pct.values

        # Empirische Kurve: Perzentil -> ROHE SCR, nur aus Spielern mit proj_vorp UND Rang
        curve_src = vt.loc[pos_mask].dropna(subset=["proj_vorp", "fp_pct"]).sort_values("fp_pct")
        curve_x, curve_y = curve_src["fp_pct"].values, curve_src["proj_vorp"].values

        idx = vt.loc[pos_mask].index
        has_proj = vt.loc[idx, "proj_vorp"].notna()
        has_rank_only = (~has_proj) & vt.loc[idx, "fp_pct"].notna() & (len(curve_x) >= 5)

        vt.loc[idx[has_proj], "SCR"] = vt.loc[idx[has_proj], "proj_vorp"]
        vt.loc[idx[has_proj], "scr_source"] = "projected"

        if has_rank_only.any():
            imputed = np.interp(vt.loc[idx[has_rank_only], "fp_pct"], curve_x, curve_y)
            vt.loc[idx[has_rank_only], "SCR"] = imputed
            vt.loc[idx[has_rank_only], "scr_source"] = "rank_imputed"

        scr_valid = pos_mask & vt["SCR"].notna()
        vt.loc[scr_valid, "dynasty_value"] = apply_modifiers(
            vt.loc[scr_valid, "SCR"].values, vt.loc[scr_valid, "age"].values,
            vt.loc[scr_valid, "draft_capital_score"].values, vt.loc[scr_valid, "years_exp"].values, p
        )

    return vt.drop(columns=["norm_name", "fp_pct"], errors="ignore")


def build_offense_dynasty_values(value_table, dynasty_rankings, roster_df, current_season=2026):
    return build_dynasty_values(value_table, dynasty_rankings, roster_df, OFFENSE_GROUPS, FINAL_PARAMS, current_season)


def build_idp_dynasty_values(value_table, dynasty_rankings, roster_df, current_season=2026):
    return build_dynasty_values(value_table, dynasty_rankings, roster_df, IDP_GROUPS, FINAL_PARAMS, current_season)


if __name__ == "__main__":
    with open("data/fantasypros_dynasty_rankings_2026.json", encoding="utf-8") as f:
        dynasty_rankings = json.load(f)
    vt = pd.read_csv("output/value_table.csv")
    roster = pd.read_csv("data/roster_2025.csv.gz")

    off_result = build_offense_dynasty_values(vt, dynasty_rankings, roster)
    off_positions = [p for grp in OFFENSE_GROUPS.values() for p in grp[0]]
    print("Offense:", off_result[off_result["position"].isin(off_positions)]["scr_source"].value_counts().to_dict())

    idp_result = build_idp_dynasty_values(vt, dynasty_rankings, roster)
    idp_positions = [p for grp in IDP_GROUPS.values() for p in grp[0]]
    print("IDP:", idp_result[idp_result["position"].isin(idp_positions)]["scr_source"].value_counts().to_dict())
