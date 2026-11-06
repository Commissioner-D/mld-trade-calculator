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
    "S":   (["FS", "SS", "S"], "DB"),
    "CB":  (["CB"], "DB"),
    "EDR": (["DE", "EDR"], "DL"),
    "IL":  (["DT", "NT", "IL"], "DL"),
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
    return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", __import__("unicodedata").normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower())).strip()


def age_mult(age, peak, rate):
    return np.clip(1 + (peak - age) * rate, 0.5, 1.6)


# ---- Mehrjahres-Dynasty-Wert --------------------------------------------------------------
# Wert = Summe der erwarteten Produktion ueber die naechsten Saisons statt einer einzigen Saison.
# Pro Jahr: SCR x Alterskurve(Alter in dem Jahr) x Abzinsung. Rest der laufenden Saison anteilig.
# Normiert auf "Saison-Aequivalente" (geteilt durch die Summe der Gewichte), damit die Zahlen auf
# der gewohnten Skala bleiben: ein Spieler am Peak mit stabiler Zukunft behaelt ~seinen SCR.
HORIZON = 5            # Saisons nach der laufenden
DISCOUNT = 0.85        # pro Jahr: Gegenwart zaehlt mehr als Zukunft
# Jahr fuer Jahr relativ zur aktuellen Projektion (die das heutige Alter schon enthaelt):
# vor dem Peak +GROWTH, ab Peak -DECLINE, ab CLIFF zusaetzlich Karriereende-Risiko (nur RETAIN bleibt).
DECLINE = {"QB": 0.06, "RB": 0.14, "WR": 0.09, "TE": 0.09,
           "LB": 0.11, "S": 0.11, "CB": 0.13, "EDR": 0.10, "IL": 0.09}
CLIFF = {"QB": 38, "RB": 30, "WR": 32, "TE": 33, "LB": 32, "S": 31, "CB": 31, "EDR": 32, "IL": 32}
GROWTH = 0.04
RETAIN = 0.4


def season_fraction_left(today=None):
    import datetime as _dt
    today = today or _dt.date.today()
    start = _dt.date(today.year if today.month >= 9 else today.year - 1, 9, 8)
    week = max(0, min(17, (today - start).days // 7))
    return (17 - week) / 17


def multi_year_factor(age, peak, group, frac_now):
    age = np.asarray(age, dtype=float)
    d, cliff = DECLINE.get(group, 0.1), CLIFF.get(group, 32)
    weights = [frac_now] + [DISCOUNT ** t for t in range(1, HORIZON + 1)]
    level = np.ones_like(age)
    acc = weights[0] * level
    for t in range(1, HORIZON + 1):
        a = age + t
        step = np.where(a <= peak, 1 + GROWTH, 1 - d) * np.where(a >= cliff, RETAIN, 1.0)
        level = level * np.clip(step, 0, None)
        acc = acc + weights[t] * level
    return acc / sum(weights)


def components(scr, age, draft_capital_score, years_exp, p, group=None, games_left=None):
    """Teilt den Wert in (laufende Saison, Zukunft) -- beide schon durch die Gewichtssumme normiert.
    Laufende Saison = reine Projektion in unserem Scoring. Zukunft = Modell (Alterskurve + Draft-Bonus);
    wird spaeter durch den FantasyPros-Dynasty-Rang ersetzt, wo einer existiert."""
    frac = season_fraction_left()
    age = np.where(np.isnan(np.asarray(age, dtype=float)), p["peak"], age)
    weights = [frac] + [DISCOUNT ** t for t in range(1, HORIZON + 1)]
    total = sum(weights)
    f_all = multi_year_factor(age, p["peak"], group, frac)          # inkl. laufender Saison
    f_fut = f_all - frac / total
    # Laufende Saison: nur verbleibende Spiele MIT Projektion (Sleeper). Ohne Projektion = 0 --
    # bewusst kein Rueckfall auf eine andere Quelle.
    if games_left is None:
        f_now = frac / total
    else:
        f_now = np.nan_to_num(np.asarray(games_left, dtype=float), nan=0.0) / 17 / total
    bonus = p["draft_scale"] * draft_capital_score * np.clip(1 - years_exp / p["draft_decay"], 0, 1)
    now = np.where(np.asarray(f_now) > 0, scr * f_now, 0.0)
    fut = np.where(scr >= 0, scr * f_fut, 0.0) + bonus * f_fut   # unter Replacement: keine Zukunft aus der Projektion
    return now, fut


def apply_modifiers(scr, age, draft_capital_score, years_exp, p, group=None):
    now, fut = components(scr, age, draft_capital_score, years_exp, p, group)
    return now + fut


def rank_future(vt, dyn_df, fp_pos, pos_mask):
    """Zukunftsteil aus dem Markt, je EIGENER Position (S, CB, EDR, IL, LB, QB ...): die Spieler der
    Position werden nach ihrem FantasyPros-Rang geordnet, der k-te bekommt den k-hoechsten Modell-
    Zukunftsteil dieser Position in unserem Scoring. Der Rang bestimmt die Reihenfolge (Vertrag, Rolle,
    Alter ...), unsere Skala den Wert. Je eigener Position statt je FP-Topf, weil FantasyPros S+CB und
    EDR+IL gemeinsam rankt -- in dieser Liga sind CBs aber deutlich weniger wert als Safeties."""
    sub = dyn_df[dyn_df["position"] == fp_pos].copy()
    sub["prank"] = sub["pos_rank"].str.extract(r"(\d+)").astype(float)
    sub = sub.sort_values("prank").drop_duplicates("norm_name")
    scale = np.sort(vt.loc[pos_mask, "future_model"].dropna().values)[::-1]
    if not len(scale):
        return
    pr = vt.loc[pos_mask, "norm_name"].map(sub.set_index("norm_name")["prank"])
    ranked = pr.dropna().sort_values(kind="stable")
    k = np.arange(len(ranked))                         # 0 = bester dieser Position laut FP
    vt.loc[ranked.index, "future_rank"] = scale[np.clip(k, 0, len(scale) - 1)]
    vt.loc[ranked.index, "fp_pos_rank"] = ranked.values


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
    vt["now_value"] = np.nan
    vt["future_model"] = np.nan

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
        now, fut = components(
            vt.loc[scr_valid, "SCR"].values, vt.loc[scr_valid, "age"].values,
            vt.loc[scr_valid, "draft_capital_score"].values, vt.loc[scr_valid, "years_exp"].values, p, group,
            vt.loc[scr_valid, "proj_games"].values if "proj_games" in vt.columns else None
        )
        # Rang-Imputation (keine Projektion): laufende Saison = 0
        imp = scr_valid & (vt["scr_source"] == "rank_imputed")
        vt.loc[scr_valid, "now_value"] = now
        vt.loc[imp, "now_value"] = 0.0
        vt.loc[scr_valid, "future_model"] = fut

    # Zukunft aus dem Dynasty-Rang (je FantasyPros-Pool, z.B. S+CB = DB), sonst Modell
    vt["future_rank"] = np.nan
    vt["fp_pos_rank"] = np.nan
    for group, (ours, fp_pos) in group_defs.items():
        rank_future(vt, dyn_df, fp_pos, vt["position"].isin(ours))
    vt["future_value"] = vt["future_rank"].where(vt["future_rank"].notna(), vt["future_model"])
    ok = vt["now_value"].notna()
    vt.loc[ok, "dynasty_value"] = vt.loc[ok, "now_value"] + vt.loc[ok, "future_value"]

    return vt.drop(columns=["norm_name", "fp_pct", "future_model", "future_rank"], errors="ignore")


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
