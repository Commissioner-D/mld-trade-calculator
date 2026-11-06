"""
Laedt Dynasty-Marktwerte von Stats Guy Fantasy (https://statsguyfantasy.com) -- errechnet aus
echten Dynasty-Trades, taeglich neu. Ersetzt die FantasyPros-Dynasty-Rankings (bei IDP wochenlang
veraltet: Anthony Hill Jr. dort LB58, hier LB16).

Einstellungen passend zur MLD:
  format=non_sf_dynasty   1-QB-Dynasty
  idp=std                 5-9 IDP-Starter (MLD: 2 DB + 2 EDR/IL + 2 LB + 1 Wildcard = 7)
  idpScoring=tackle       Verhaeltnis (Solo + Sack + TFL + QB-Hit + INT + PD) / Solo < 8
                          (MLD: (1,5 + 2 + 1 + 0 + 4 + 1,5) / 1,5 = 6,7)

Genutzt wird nur die REIHENFOLGE innerhalb jeder Position -- der Wert kommt aus unserem Scoring.
Ausgabe im selben Schema wie bisher die FantasyPros-Datei (name, position, team, rank_ecr, pos_rank),
Positionen in den Toepfen QB/RB/WR/TE/LB/DB/DL.

Free API ohne Key. Attribution "Data from Stats Guy Fantasy" muss auf der Seite sichtbar sein.
Schlaegt der Abruf fehl oder ist er unplausibel: Abbruch -> die letzten Werte bleiben stehen.
"""
import json
import os
import sys
import time
import urllib.request
from collections import Counter

BASE = "https://api.statsguyfantasy.com/api/v1"
PARAMS = "format=non_sf_dynasty&idp=std&idpScoring=tackle"
UA = {"User-Agent": "mld-trade-calculator/1.0 (+https://commissioner-d.github.io/mld-trade-calculator)"}
POS_MAP = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "LB": "LB", "ILB": "LB", "OLB": "LB",
           "DB": "DB", "CB": "DB", "S": "DB", "SS": "DB", "FS": "DB", "DL": "DL", "DE": "DL", "DT": "DL", "NT": "DL", "EDGE": "DL"}


def get(url, retries=4):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", "30")) + 1)
                continue
            if i == retries - 1:
                raise
            time.sleep(5)
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(5)


def rows_of(d):
    if isinstance(d, list):
        return d
    for k in ("rankings", "players", "data", "results", "items"):
        if isinstance(d.get(k), list):
            return d[k]
    return []


def main():
    out, raw_sample, meta = [], None, {}
    for pos in ["QB", "RB", "WR", "TE", "LB", "DB", "DL"]:
        offset = 0
        while True:
            d = get(f"{BASE}/rankings?{PARAMS}&position={pos}&limit=1000&offset={offset}")
            if raw_sample is None:
                raw_sample = d if isinstance(d, list) else {k: (v[:3] if isinstance(v, list) else v) for k, v in d.items()}
            if isinstance(d, dict):
                meta = {k: d.get(k) for k in ("asOf", "valuesAsOf", "idpAsOf", "format", "idp", "idpScoring") if k in d} or meta
            rows = rows_of(d)
            for r in rows:
                p = POS_MAP.get(str(r.get("position") or "").upper(), pos)
                prank = r.get("positionRank")
                if isinstance(prank, (int, float)):
                    prank = f"{pos}{int(prank)}"
                out.append({"name": r.get("name"), "position": pos if pos in ("LB", "DB", "DL") else p,
                            "team": r.get("team"), "rank_ecr": r.get("rank"), "pos_rank": prank,
                            "value": r.get("value"), "sleeper_id": r.get("id"), "age": r.get("age")})
            if len(rows) < 1000:
                break
            offset += 1000
        time.sleep(2)

    c = Counter(x["position"] for x in out)
    print("Positionen:", dict(c), "Stand:", meta)
    if len(out) < 500 or sum(c[p] for p in ("LB", "DB", "DL")) < 100:
        raise SystemExit(f"Unplausible Antwort ({dict(c)}) -- Abbruch, alte Werte bleiben")
    # pos_rank absichern: falls die API keinen liefert, aus der Reihenfolge ableiten
    by = {}
    for x in out:
        if not x["pos_rank"] or not str(x["pos_rank"])[-1].isdigit():
            by.setdefault(x["position"], 0)
            by[x["position"]] += 1
            x["pos_rank"] = f"{x['position']}{by[x['position']]}"
    os.makedirs("data", exist_ok=True)
    with open("data/statsguy_dynasty.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open("data/statsguy_meta.json", "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "counts": dict(c), "raw_sample": raw_sample}, f, ensure_ascii=False, indent=1)
    print(f"{len(out)} Spieler -> data/statsguy_dynasty.json")


if __name__ == "__main__":
    sys.exit(main())
