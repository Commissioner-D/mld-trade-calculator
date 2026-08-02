# idp-dynasty-values

Custom Dynasty-Trade-Value-Tool für **Major League Dynasty** (Fleaflicker Liga 294292,
16 Teams, Full-IDP). Gebaut, weil externe Charts (FantasyPros, KeepTradeCut, DynastyCalc)
entweder nur 12-Team, nur Offense, oder generisches IDP-Scoring nutzen, das die
liga-eigenen Punktwerte nicht trifft.

## Was drin ist

```
data/          nflverse-Rohdaten (Rosters, PBP, offizielle Stat-Releases)
scoring/        Fleaflicker-Scoring & Roster-Struktur als JSON-Config (nicht hart codiert)
engine/         Aggregation -> Scoring -> Weighted PPG -> VORP -> Age-Curve -> Pick-Kurve
output/         value_table.csv/json (alle Spieler) + Calculator-Datensätze
web/index.html  Trade Desk — die gehostete Oberfläche. Läuft NIE ohne
                Neuschreiben, laedt Werte zur Laufzeit per fetch() aus
                output/calculator_players.json + calculator_picks.json.
                Muss darum über http(s) laufen (GitHub Pages o.ä.) --
                lokal per Doppelklick geoeffnet (file://) blockieren
                Browser den fetch() aus Sicherheitsgruenden.
```

## Ausführen

```bash
pip install pandas numpy scipy
python engine/build_value_table.py
```

Lädt Rosters (2025/2024), aggregiert IDP-Defense + Offense + Kicking aus PBP
(für die aktuelle Saison, weil die offiziellen nflverse `player_stats`-Releases
eine Saison hinterherhinken), wendet die Scoring-Config an, berechnet
Weighted PPG (65% aktuell / 35% Vorsaison), Replacement-Level/VORP je Positions-
gruppe und die Age-Curve. Output: `output/value_table.csv` + `.json`.

Um `output/calculator_players.json` + `calculator_picks.json` mit einem
frischen Datenstand neu zu bauen:

```bash
python engine/build_calculator_data.py   # trimmt value_table + generiert Pick-Werte
```

**Update-Workflow (index.html bleibt dabei unangetastet):**
Bei neuen Werten (frische nflverse-Woche, neue Projektionsquelle eingepflegt
o.ä.) reicht es, `output/calculator_players.json` und `calculator_picks.json`
auf GitHub zu überschreiben — die Seite selbst laedt die Werte beim Aufruf
live nach, kein erneutes Hochladen von index.html noetig.

## Wichtig — was das hier NICHT ist

**Trailing Production Value ≠ Projektion.** nflverse liefert ausschließlich
Vergangenheit. Der berechnete Wert ist eine gewichtete Historie, keine
Zukunftserwartung. Das trifft Rookies mit wenig Snaps besonders hart (siehe
Jalon Walker im aktuellen Datensatz: großer Erstrunden-Pick, aber niedriger
Trailing-Value, weil Rookie-Jahr mit wenig Spielzeit). Sobald eine echte
Projektionsquelle (Woellert/IDP Guru, beide $-pflichtig) eingepflegt wird,
soll die als **eigene, separate Spalte** erscheinen, nicht mit diesem Wert
verschmolzen.

**Pick-Werte sind jetzt echt kalibriert.** `engine/pick_curve.py` ist gegen
alle 6 Rookie-Drafts dieser Liga (2020–2025, 480 gezogene Spieler, aus den
Fleaflicker-Draftboards) gefittet: value(pick) = a/(pick+b) + c. Kernbefund:
im Schnitt liegt nur Pick 1–3 eines Jahrgangs heute über Replacement-Level,
ab ca. Pick 5 kippt der Erwartungswert ins Negative und pendelt sich ab
Runde 2 bei ca. -2,7 bis -3,1 ein (Bank-/Rotationsspieler oder komplett aus
der Liga raus). R² der Regression ist mit ~0,08 niedrig — erwartbar, weil
einzelne Pick-Outcomes stark streuen (Hit-or-Miss), nur der gemittelte Trend
über viele Picks ist stabil. Re-Kalibrieren via `fit_pick_curve()`, sobald
neue Jahrgänge dazukommen (Skript: `engine/parse_rookie_drafts.py` +
manuelles Cross-Referencing gegen `output/value_table.csv`, siehe Code).

**Bugfix in der Age-Curve gefunden bei der Kalibrierung:** der Multiplikator
wurde vorher auch auf negativen VORP angewendet — bei jungen Spielern
(Multiplikator > 1) hat das den negativen Wert verstärkt, sodass ein
Bankspieler ohne Rolle schlechter aussah als ein Spieler, der komplett aus
der Liga ist. Jetzt: Multiplikator nur auf positiven VORP, negativer VORP
bleibt unverändert (siehe `engine/value_engine.py::dynasty_trailing_value`).

**Age-Curve-Konstanten sind Heuristik** (Peak 27.25, Decay 0.03, gecappt
0.7–1.3), nicht empirisch gefittet — schwächster Teil der Formel, bei
Gelegenheit gegen echte Liga-Trades kalibrieren.

**Offense-Replacement-Level nutzt eine Flex-Split-Heuristik** (RB/WR/TE-Flex
verzerrt alle drei Positionen gleichzeitig — "Stolperstein A", noch nicht
sauber als Gleichungssystem gelöst). Aktuell: fixer prozentualer Split
(40/45/15) in `scoring/roster_config.json`.

## Automatischer Rebuild (GitHub Action)

`.github/workflows/update-values.yml` laeuft woechentlich (Mittwoch, manuell
auch jederzeit ueber den "Run workflow"-Button im Actions-Tab) komplett auf
GitHub's Servern -- kein lokales Python noetig:

1. Laedt frische nflverse-Rohdaten
2. Laedt FantasyPros-Offense-Projektionen (sobald `FANTASYPROS_API_KEY` als
   Repository-Secret gesetzt ist -- Settings > Secrets and variables > Actions
   > New repository secret. Key anfordern: `secure.fantasypros.com/api-keys/request`,
   kostenlos fuer persoenliche Nutzung, siehe `engine/fetch_projections.py`)
3. Baut Value-Tabelle + Calculator-Daten neu
4. Committet die aktualisierten `output/*.json` automatisch zurueck ins Repo

Der Calculator selbst muss dafuer nie angefasst werden (laedt per fetch()
ohnehin live).

**Offener Schritt:** `engine/fetch_projections.py` holt die FantasyPros-Rohdaten
und speichert sie, aber `build_value_table.py` verarbeitet sie noch nicht zu
einer eigenen "Projektions-Wert"-Spalte -- das ist der naechste Coding-Schritt,
am besten sobald ein echter API-Response zum Gegenchecken der Feldnamen vorliegt
(die Doku zeigt ein 2017er Beispiel, 2026 koennte leicht abweichen).

## Naechste Schritte

- ~~Entscheiden: GitHub Action für Auto-Updates~~ -> erledigt, s.o.
- FantasyPros-Projektionen in die Value-Engine integrieren (separate Spalte,
  s.o.), sobald API-Key vorhanden und Response-Format verifiziert ist
- Pick-Kurve bei mehr Draft-Jahrgaengen neu fitten
- Fantasy-Rosterdaten aller 16 Teams (optional, nur fuer Team-Value/Trade-Finder)
