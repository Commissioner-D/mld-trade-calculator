"""
Zaehlt, wie viele Spieler jeder Position/Gruppe TATSAECHLICH auf den 16 echten
Rostern dieser Liga stehen -- aus den aktuellen Fleaflicker-Rosterdaten (werden
bei jedem Pipeline-Lauf frisch abgerufen, siehe fetch_fleaflicker_rosters.py).

Ersetzt die bisherigen Heuristiken (flex_share_offense, IDP-Wildcard-Anteil):
statt zu SCHAETZEN, wie sich ein geteilter Flex-/Wildcard-Slot auf die
Positionen verteilt, zaehlen wir direkt nach, wie viele Spieler jeder Position
die 16 Manager tatsaechlich rostern. Der (Anzahl+1)-te Spieler ist der wahre
Replacement-Referenzpunkt -- der beste Spieler, der bei KEINEM Team mehr auf
dem Roster ist. Gilt fuer Offense UND IDP gleichermassen (Dominiks Vorgabe:
"das sollen wir bei allen Positionen machen").
"""
import json
import re

OFFENSE_POSITIONS = ["QB", "RB", "WR", "TE"]

# Fleaflickers eigene Rosterdaten-Labels -> unsere IDP-Gruppen (DB/EDR_IL/LB).
# fleaflicker_rosters.json nutzt Fleaflickers Feinlabels direkt (CB/S/EDR/IL/LB),
# nicht nflverse-Konventionen -- siehe fetch_fleaflicker_rosters.py.
IDP_GROUP_OF_FLEA_POS = {
    "CB": "DB", "S": "DB", "DB": "DB",
    "EDR": "EDR_IL", "IL": "EDR_IL", "EDR/IL": "EDR_IL",
    "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
}


def norm_name(n):
    return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", re.sub(r"[^a-z ]", "", str(n).lower())).strip()


def compute_rostered_counts(rosters_path: str = "data/fleaflicker_rosters.json") -> dict:
    """Gibt {position_oder_gruppe: tatsaechlich_gerosterte_anzahl} zurueck.
    Bei fehlenden Rosterdaten: leeres dict (Aufrufer muss auf Fallback-Werte
    zurueckfallen, siehe Docstrings der Aufrufstellen)."""
    try:
        with open(rosters_path, encoding="utf-8") as f:
            rosters = json.load(f)
    except FileNotFoundError:
        return {}

    counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "DB": 0, "EDR_IL": 0, "LB": 0}
    for r in rosters:
        pos = r.get("position")
        if not pos:
            continue
        # Hybrid-Labels (z.B. "WR/CB"): ersten bekannten Teil nehmen
        for part in pos.split("/") if "/" in pos and pos not in IDP_GROUP_OF_FLEA_POS else [pos]:
            if part in OFFENSE_POSITIONS:
                counts[part] += 1
                break
            if part in IDP_GROUP_OF_FLEA_POS:
                counts[IDP_GROUP_OF_FLEA_POS[part]] += 1
                break
    return counts


if __name__ == "__main__":
    counts = compute_rostered_counts()
    print("Tatsaechlich gerosterte Spieler je Position/Gruppe:", counts)
    print("Daraus abgeleitete Replacement-Raenge (Anzahl+1):", {k: v + 1 for k, v in counts.items()})
