"""Einmal-Test: liefert Sleeper IDP-Projektionen mit aktueller Rolle (Woche 10/11 + Saison)?"""
import json, os, time, urllib.request
TEST = ["Anthony Hill", "Josiah Trotter", "Jack Campbell", "Kendal Daniels", "Demario Davis",
        "Trenton Simpson", "Payton Wilson", "Kyle Hamilton", "Kam Curl", "Aidan Hutchinson"]
URLS = {
    "w10_LB": "https://api.sleeper.app/projections/nfl/2026/10?season_type=regular&position[]=LB",
    "w10_DB": "https://api.sleeper.app/projections/nfl/2026/10?season_type=regular&position[]=DB&position[]=S&position[]=CB",
    "w11_LB": "https://api.sleeper.app/projections/nfl/2026/11?season_type=regular&position[]=LB",
    "season_LB": "https://api.sleeper.app/projections/nfl/2026?season_type=regular&position[]=LB",
    "stats_w8_LB": "https://api.sleeper.app/stats/nfl/2026/8?season_type=regular&position[]=LB",
}
out = {}
for k, u in URLS.items():
    time.sleep(2)
    r = {"url": u}
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "mld-probe/1.0"}), timeout=60) as resp:
            d = json.loads(resp.read())
        r["type"] = str(type(d)); r["n"] = len(d)
        if isinstance(d, list) and d:
            r["sample_keys"] = list(d[0].keys())
            r["sample_stat_keys"] = sorted((d[0].get("stats") or {}).keys())
        hits = {}
        for x in d if isinstance(d, list) else []:
            p = x.get("player") or {}
            nm = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
            if any(t.lower() in nm.lower() for t in TEST):
                st = x.get("stats") or {}
                hits[nm] = {kk: st.get(kk) for kk in sorted(st) if kk.startswith("idp_") or kk in ("gp", "pts_idp")}
                hits[nm]["_team"] = x.get("team"); hits[nm]["_company"] = x.get("company")
        r["test_players"] = hits
    except Exception as e:
        r["error"] = f"{type(e).__name__}: {e}"[:300]
    out[k] = r
os.makedirs("probe", exist_ok=True)
open("probe/sleeper_probe.json", "w").write(json.dumps(out, indent=1, ensure_ascii=False))
