"""
Draft-Pick-Wert-Kurve.

Methodik: parametrische Kurve statt Rang-fuer-Rang-Lookup, weil einzelne
Pick-Slots (1.12 vs 1.14) mit nur 6 Rookie-Draft-Jahrgaengen nie robust
genug sind (Stolperstein C, siehe Briefing).

KALIBRIERT gegen die echte Liga-Historie: alle 6 Rookie-Drafts dieser Liga
(2020-2025, Fleaflicker-Draftboards, 480 gezogene Spieler) wurden mit ihrem
AKTUELLEN Trailing-VORP (Stand: Zeitpunkt der Kalibrierung) verknuepft --
also nicht mit vorgerechneten Punkten, sondern damit, wie produktiv jeder
gezogene Spieler seither tatsaechlich war. Nicht mehr im aktuellen
nflverse-Datensatz auffindbare Spieler (aus der NFL raus / ohne Rolle,
~14% der 480) wurden mit einem Floor-Wert 0.0 imputiert statt gedroppt --
sonst waere die Bust-Quote spaeter Picks systematisch unterschaetzt.

Funktionsform: value(pick) = a / (pick + b) + c
Der zusaetzliche Offset `c` ist noetig (anders als eine reine a/(pick+b)-
Kurve), weil die reale mittlere Outcome-Kurve dieser Liga nicht gegen 0,
sondern gegen einen NEGATIVEN Floor konvergiert: die meisten Picks ab
Runde 1 Ende / Runde 2 liefern im Schnitt einen Spieler, der aktuell UNTER
Replacement-Level liegt (Bank-/Rotationsspieler oder komplett aus der Liga).
Nur die ersten ~8 Picks eines Jahrgangs zeigen im Schnitt positiven VORP.

EHRLICHKEIT ZUR FIT-QUALITAET: R^2 der Regression liegt bei ~0.08 -- das
ist erwartbar und kein Fehler: einzelne Pick-Outcomes streuen extrem
(Treffer vs. Bust ist pro Slot fast eine Muenzwurf-Verteilung), nur der
GEMITTELTE Trend ueber viele Picks ist stabil genug fuer eine Kurve. Das
deckt sich mit "grober Wegweiser, keine Feinunterscheidung" aus dem Briefing.

Ceiling/Hit-Rate-Blend (DynastyProcess-Methodik) wurde NICHT separat
umgesetzt -- dafuer braucht es pro Pick-Slot sowohl den Top-Outcome als
auch den Median-Outcome getrennt, was mehr Jahrgaenge voraussetzt als die
6 aktuell vorliegenden. Die hier gefittete Kurve ist bereits ein
Hit-Rate-Style-Mittelwert (kein optimistischer Ceiling-Wert).
"""
import json
import numpy as np
from scipy.optimize import curve_fit


# Gefittet gegen 480 echte Rookie-Picks dieser Liga (2020-2025), diesmal gegen
# das SCR-basierte Dynasty-Value-System (Offense) statt der alten Trailing-Werte --
# noetig geworden, weil die Spieler-Bewertungsmethodik sich komplett geaendert hat
# (kein Trailing-Fallback mehr, siehe engine/dynasty_value.py). Alte Kurve
# unterschaetzte fruehe Picks massiv (Pick 1 nur 2.38 statt jetzt 5.74).
FITTED_PARAMS = {"a": 94.965, "b": 5.310, "c": 0.0}

# Neu kalibriert 2026-11: (1) gegen die AKTUELLEN Spielerwerte inkl. 2026er Rookie-Jahrgang (vorher fehlte
# er ganz -> fruehe Picks massiv unterschaetzt); (2) jedes Outcome nach unten bei 0 gekappt: ein Bust wird
# geschnitten (Taxi-Platz, kein aktiver Rosterplatz), er kostet also nichts -- vorher zogen negative Werte
# von Busts spaete Picks unter 0, ein spaeter 1st war "weniger wert als nichts"; (3) nur die Jahrgaenge
# 2023-2026: aeltere Jahrgaenge sind heute 5-6 Jahre ueber den Peak hinaus und unterschaetzen, was ein
# Pick beim Draft wert ist. R^2 ~0.41.


def pick_value(pick_overall: float, params=FITTED_PARAMS) -> float:
    """Gibt den Pick-Wert auf derselben Skala wie Dynasty Trailing Value zurueck
    (VORP, ggf. age-adjustiert), damit Spieler und Picks im Calculator direkt
    vergleichbar sind."""
    a, b, c = params["a"], params["b"], params["c"]
    return round(a / (pick_overall + b) + c, 3)


def fit_pick_curve(historical_picks: list) -> dict:
    """
    Re-Kalibriert die Kurve, sobald neue Draft-Jahrgaenge dazukommen.

    historical_picks: Liste von dicts, z.B.
        [{"overall": 3, "value": 4.8}, ...]
    value = aktueller Dynasty Trailing Value (VORP-basiert) des gezogenen
    Spielers zum Kalibrierungszeitpunkt. Nicht mehr auffindbare Spieler
    sollten vorher mit einem Floor-Wert (z.B. 0.0) imputiert werden, nicht
    gedroppt -- sonst wird die Bust-Quote unterschaetzt.
    """
    picks = np.array([p["overall"] for p in historical_picks], dtype=float)
    outcomes = np.maximum(np.array([p["value"] for p in historical_picks], dtype=float), 0.0)   # Bust = schneiden = 0

    def model(x, a, b, c):
        return a / (x + b) + c

    popt, _ = curve_fit(model, picks, outcomes, p0=[60.0, 5.0, 0.5], bounds=([0, 0, 0], [1e4, 100, 5]), maxfev=20000)
    return {"a": float(popt[0]), "b": float(popt[1]), "c": float(popt[2])}


if __name__ == "__main__":
    with open("data/rookie_picks_with_values.json", encoding="utf-8") as f:
        historical = [p for p in json.load(f) if p["season"] >= 2023]
    fitted = fit_pick_curve(historical)
    print("Neu gefittete Parameter:", fitted)
