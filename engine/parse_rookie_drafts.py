"""Parst die zwischengespeicherten Rookie-Draft-Board-Rohdaten (data/rookie_draft_{season}_raw.txt)
in eine Liste von (season, round, slot, overall, position, player_name)."""
import re
import glob
import json

KNOWN_TEAMS = [
    "New Fernitz Dudemeisters", "Mühlviertl Raiders", "Liebenauer Sombreros",
    "St.Leonhard Sombreros", "Vienna BBB", "Purple Cobras", "T-Bagwells",
    "Grumpy Toads", "AlohaHe", "Pumpkin Seed Oilers", "Jöss Jolly Rogers",
    "Vienna Seahawks", "Graz Moeflers", "Tegetthoff Admirals",
    "Lend Football Team", "Lend Rovers", "Romo's Call", "Semmel Warriors",
    "Gries Goats", "Graz Trash Pandas", "Ragnitz Couchpotatos",
]
KNOWN_TEAMS_SORTED = sorted(KNOWN_TEAMS, key=len, reverse=True)

NUM_TEAMS = 16


def strip_md_links(text):
    return re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)


def clean_team_header(cell):
    cell = cell.strip()
    # Bild-mit-Link vollstaendig entfernen (2021-Format: "![Name Logo](url)[Name](url)")
    without_img_link = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', cell).strip()
    m = re.match(r'^\[([^\]]+)\]\([^)]*\)$', without_img_link)
    if m:
        return m.group(1).strip()
    # Reines Bild-Alt-Text-Format (2020: "![Name Logo]", keine separate Link-Zelle)
    m = re.match(r'^!\[([^\]]+)\]$', cell)
    if m:
        return re.sub(r'\s*Logo$', '', m.group(1)).strip()
    # Bereits Klartext (2022+)
    return cell


def parse_cell(cell):
    cell = strip_md_links(cell).strip()
    m = re.match(r'^(\d+)\.(\d+)\s+(.*)$', cell)
    if not m:
        return None
    rnd, slot, rest = int(m.group(1)), int(m.group(2)), m.group(3).strip()

    # Normal cell: 'POS – TEAM (bye)? Name...'
    m2 = re.match(r'^([A-Za-z/\.]+)\s+–\s+\S+(?:\s*\(\d+\))?\s+(.+)$', rest)
    if m2:
        return rnd, slot, m2.group(1), m2.group(2).strip()

    # Traded-pick cell: leading known team name, no position given
    for team in KNOWN_TEAMS_SORTED:
        if rest.startswith(team):
            name = rest[len(team):].strip()
            # sometimes '(trade)' suffix directly after team name
            name = re.sub(r'^\(trade\)\s*', '', name)
            return rnd, slot, None, name

    # Fallback: no dash, no known team prefix -> assume whole thing is name
    return rnd, slot, None, rest


LIST_ROW_RE = re.compile(
    r'^\|\s*(\d+)\.(\d+)\s*#(\d+)\s*\|\s*\[([^\]]+)\]\([^)]*\)\s*([A-Za-z/\.]*)\s*\S*\s*\|'
)


def parse_list_row(row):
    m = LIST_ROW_RE.match(row.strip())
    if not m:
        return None
    rnd, slot, overall_true = int(m.group(1)), int(m.group(2)), int(m.group(3))
    name, pos = m.group(4).strip(), m.group(5).strip() or None
    # dritte Zelle = Fantasy-Team (nicht Teil der Haupt-Regex, separat rausziehen)
    cells = [c.strip() for c in row.strip().strip('|').split('|')]
    team = strip_md_links(cells[2]).strip() if len(cells) > 2 else None
    return rnd, slot, overall_true, pos, name, team


def parse_file(path, season):
    text = open(path, encoding='utf-8').read()
    rows = [r for r in text.strip().split('\n') if r.strip().startswith('|')]

    # Format detection: list-format has one pick per row, matched by LIST_ROW_RE
    is_list_format = any(LIST_ROW_RE.match(r.strip()) for r in rows[:3])

    picks = []
    if is_list_format:
        for row in rows:
            parsed = parse_list_row(row)
            if not parsed:
                continue
            rnd, slot, overall, pos, name, team = parsed
            picks.append({
                "season": season, "round": rnd, "slot": slot,
                "overall": overall, "position": pos, "name": name, "team": team,
            })
        return picks

    # Board-Format: Spaltenposition (aus Header-Zeile) = Team, konstant ueber alle Runden
    header_cells = [c.strip() for c in rows[0].strip().strip('|').split('|')]
    teams_by_col = [clean_team_header(c) for c in header_cells]

    for row in rows[1:]:
        cells = [c.strip() for c in row.strip().strip('|').split('|')]
        for col_idx, cell in enumerate(cells):
            if not cell or cell.upper() == 'BLANK':
                continue
            parsed = parse_cell(cell)
            if not parsed:
                print(f"[{season}] NOMATCH: {cell!r}")
                continue
            rnd, slot, pos, name = parsed
            overall = (rnd - 1) * NUM_TEAMS + slot
            team = teams_by_col[col_idx] if col_idx < len(teams_by_col) else None
            picks.append({
                "season": season, "round": rnd, "slot": slot,
                "overall": overall, "position": pos, "name": name, "team": team,
            })
    return picks


if __name__ == "__main__":
    all_picks = []
    for path in sorted(glob.glob("data/rookie_draft_*_raw.txt")):
        season = int(re.search(r'rookie_draft_(\d+)_raw', path).group(1))
        picks = parse_file(path, season)
        print(f"{season}: {len(picks)} picks parsed")
        all_picks.extend(picks)
    with open("data/rookie_draft_picks_parsed.json", "w", encoding='utf-8') as f:
        json.dump(all_picks, f, ensure_ascii=False, indent=2)
    print(f"Total: {len(all_picks)} picks -> data/rookie_draft_picks_parsed.json")
