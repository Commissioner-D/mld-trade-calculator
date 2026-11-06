"""Einmal-Test: welche FantasyPros-Projektionsvarianten liefern IDP mit aktueller Rolle?
Schreibt nur Statuscodes, Response-Struktur und Werte einiger Testspieler -- niemals den Key."""
import json, os, urllib.request, urllib.error

KEY = os.environ.get("FANTASYPROS_API_KEY", "")
BASE = "https://api.fantasypros.com/public/v2/json/nfl/2026"
TEST = ["Anthony Hill", "Josiah Trotter", "Jack Campbell", "Kendal Daniels", "Demario Davis", "Trenton Simpson", "Payton Wilson", "Kyle Hamilton", "Kam Curl"]
VARIANTS = [
    "projections?position=LB&week=9",
]
out = {"key_set": bool(KEY), "results": []}
import time
for v in VARIANTS:
    time.sleep(8)
    r = {"variant": v}
    try:
        req = urllib.request.Request(f"{BASE}/{v}", headers={"x-api-key": KEY})
        with urllib.request.urlopen(req, timeout=60) as resp:
            d = json.loads(resp.read())
        r["status"] = 200
        r["top_keys"] = list(d.keys())[:15] if isinstance(d, dict) else str(type(d))
        r["meta"] = {k: d.get(k) for k in ("season", "week", "scoring", "type", "projection_type", "last_updated", "position_id") if isinstance(d, dict) and k in d}
        players = d.get("players", []) if isinstance(d, dict) else []
        r["n_players"] = len(players)
        r["sample_player_keys"] = list(players[0].keys()) if players else None
        hits = {}
        for p in players:
            nm = p.get("name") or p.get("player_name") or ""
            if any(t.lower() in nm.lower() for t in TEST):
                hits[nm] = p.get("stats")
        r["test_players"] = hits
    except urllib.error.HTTPError as e:
        r["status"] = e.code
        try:
            r["body"] = e.read().decode()[:300]
        except Exception:
            pass
    except Exception as e:
        r["status"] = f"{type(e).__name__}: {e}"[:200]
    out["results"].append(r)
txt = json.dumps(out, indent=1, ensure_ascii=False)
if KEY:
    txt = txt.replace(KEY, "***")
os.makedirs("probe", exist_ok=True)
open("probe/fp_probe.json", "w").write(txt)
print(txt[:3000])
