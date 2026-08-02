"""
Kern-Wertengine: Weighted PPG -> Replacement-Level/VORP -> Age-Curve.

Wichtig (siehe Projekt-Briefing): Das hier ist ein TRAILING PRODUCTION
VALUE, keine Projektion. nflverse liefert nur Vergangenheit. Sobald eine
echte Projektionsquelle (Woellert/IDP Guru) eingepflegt wird, soll die
als eigene, separate Spalte erscheinen -- nicht mit diesem Wert verschmolzen.
"""
import pandas as pd
import numpy as np
from datetime import date

PEAK_AGE = 27.25   # Mitte der in der Recherche bestaetigten Spanne 27-27.5
AGE_DECAY_RATE = 0.03
AGE_MULT_MIN = 0.7
AGE_MULT_MAX = 1.3


def weighted_ppg(current_pts, current_games, prev_pts, prev_games,
                  w_current=0.65, w_prev=0.35):
    """65% aktuelle Saison-PPG + 35% Vorsaison-PPG. Faellt sauber zurueck,
    falls eine der beiden Saisons fehlt (Rookie / Spieler ohne Vorsaison-Snap)."""
    cur_ppg = current_pts / current_games if current_games and current_games > 0 else None
    prev_ppg = prev_pts / prev_games if prev_games and prev_games > 0 else None

    if cur_ppg is not None and prev_ppg is not None:
        return w_current * cur_ppg + w_prev * prev_ppg
    if cur_ppg is not None:
        return cur_ppg
    if prev_ppg is not None:
        return prev_ppg
    return None


def replacement_level(df: pd.DataFrame, ppg_col: str, rank: int) -> float:
    """PPG am Rang `rank` einer Spielerpopulation (Job 1 -- immer aus Trailing-Altdaten,
    unabhaengig davon ob fuer Job 2 eine Projektion vorliegt)."""
    sorted_vals = df[ppg_col].dropna().sort_values(ascending=False).reset_index(drop=True)
    if len(sorted_vals) == 0:
        return 0.0
    idx = min(rank - 1, len(sorted_vals) - 1)
    return float(sorted_vals.iloc[idx])


def age_multiplier(age: float) -> float:
    if age is None or pd.isna(age):
        return 1.0
    mult = 1 + (PEAK_AGE - age) * AGE_DECAY_RATE
    return float(np.clip(mult, AGE_MULT_MIN, AGE_MULT_MAX))


def compute_age(birth_date_str, as_of: date = None) -> float:
    if pd.isna(birth_date_str):
        return None
    as_of = as_of or date.today()
    bd = pd.to_datetime(birth_date_str).date()
    days = (as_of - bd).days
    return round(days / 365.25, 1)


def dynasty_trailing_value(vorp: float, age: float) -> float:
    """VORP * Age-Multiplikator. Schwaechster Teil der Formel (Age-Curve-Konstanten
    sind Heuristik, nicht gefittet) -- bei Gelegenheit gegen echte Liga-Trades kalibrieren.

    WICHTIG -- Bugfix (gefunden bei der Pick-Curve-Kalibrierung mit echten Rookie-Draft-Daten):
    Der Multiplikator darf NUR auf positiven VORP angewendet werden. Bei negativem VORP wuerde
    er den Wert eines jungen Spielers (Multiplikator > 1) noch weiter ins Negative amplifizieren --
    ein junger Bankspieler ohne klare Rolle erschien dadurch schlechter als ein Spieler, der
    komplett aus der Liga raus ist. Negativer VORP bleibt deshalb unveraendert (kein Age-Adjustment
    auf "Miss"-Produktion; die Alterskurve soll nur echtes Aufwaerts-/Abwaerts-Potenzial bei
    tatsaechlicher Produktion abbilden, nicht Busts verstaerken)."""
    if vorp is None:
        return None
    if vorp >= 0:
        return round(vorp * age_multiplier(age), 3)
    return round(vorp, 3)
