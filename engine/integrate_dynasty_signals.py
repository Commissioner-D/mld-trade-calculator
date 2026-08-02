"""
Verarbeitet die (ephemeren, nicht persistierten) OverTheCap-Vertragsdaten zu
zwei Signalen fuer die Dynasty-Formel:

  1. draft_capital_score: wie hoch gedraftet, 0-1 normalisiert (Pick 1 = 1.0,
     abfallend). Kommt direkt aus den Vertragsdaten (draft_round/draft_overall),
     keine separate Roster-Extraktion noetig.
  2. contract_security: verbleibende Vertragsjahre + garantierter Geldanteil,
     0-1 normalisiert. Nur beim AKTIVEN Vertrag relevant -- bei Rookies wenig
     aussagekraeftig (alle auf der gleichen 4-Jahres-Rookievertragsstruktur),
     erst ab Zweitvertrag differenzierend (siehe Projekt-Notizen).

Beide Signale sind bewusst ROH gehalten (keine Gewichtung/Multiplikator hier)
-- die eigentliche Gewichtung passiert erst in der Formel-Kalibrierung gegen
FantasyPros Dynasty-Rankings (separates Skript).
"""
import pandas as pd
import numpy as np

CURRENT_SEASON = 2026
MAX_DRAFT_OVERALL = 262  # Standard-NFL-Draft-Groesse (7 Runden x ~32 Teams + Comp Picks)


def load_contract_signals(contracts_path: str) -> pd.DataFrame:
    df = pd.read_csv(contracts_path)
    active = df[df["is_active"] == True].copy()

    # Draft-Kapital: 1.0 fuer Pick 1, linear abfallend, 0 fuer UDFA/nicht gedraftet
    active["draft_capital_score"] = active["draft_overall"].apply(
        lambda x: round(max(0.0, 1 - (x - 1) / MAX_DRAFT_OVERALL), 3) if pd.notna(x) else 0.0
    )

    # Vertragssicherheit: verbleibende Jahre (gedeckelt bei 4, laenger bringt
    # kaum mehr Sicherheits-Signal) + garantierter Anteil, gemittelt
    active["contract_end_year"] = active["year_signed"] + active["years"]
    active["years_remaining"] = (active["contract_end_year"] - CURRENT_SEASON).clip(lower=0, upper=4) / 4
    active["guaranteed_pct"] = np.where(
        active["value"] > 0, (active["guaranteed"] / active["value"]).clip(0, 1), 0.0
    )
    active["contract_security"] = (
        (active["years_remaining"].fillna(0) + active["guaranteed_pct"].fillna(0)) / 2
    ).round(3)

    active["norm_name"] = active["player"].apply(
        lambda n: __import__("re").sub(r"\b(jr|sr|ii|iii|iv)\b", "",
                                        __import__("re").sub(r"[^a-z ]", "", str(n).lower())).strip()
    )
    # Ein Spieler kann mehrere "aktive" Eintraege haben (Datenqualitaet) -- neuesten behalten
    active = active.sort_values("year_signed", ascending=False).drop_duplicates(subset=["norm_name"], keep="first")

    return active[["norm_name", "draft_capital_score", "contract_security",
                   "years_remaining", "guaranteed_pct"]]


if __name__ == "__main__":
    result = load_contract_signals("data/historical_contracts.csv.gz")
    print(f"{len(result)} Spieler mit Vertragssignalen")
    print(result.sort_values("contract_security", ascending=False).head(10).to_string(index=False))
