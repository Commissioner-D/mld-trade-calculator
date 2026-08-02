"""
Zentraler Scoring-Kern: nimmt Rohkategorien (egal ob aus nflverse-Trailing-
Daten oder spaeter aus einer Projektions-Datei wie Woellert/IDP Guru) und
wendet die Liga-Scoring-Config an. Nie vorgerechnete Punkte einer fremden
Quelle uebernehmen -- immer auf Rohkategorien-Ebene ansetzen.
"""
import json


def load_scoring_config(path="scoring/scoring_config.json"):
    with open(path) as f:
        return json.load(f)


def score_defense_row(row, cfg) -> float:
    d = cfg["defense"]
    pts = 0.0
    pts += row.get("solo_tackle", 0) * d["solo_tackle"]
    pts += row.get("assisted_tackle", 0) * d["assisted_tackle"]
    pts += row.get("tackle_for_loss", 0) * d["tackle_for_loss"]
    pts += row.get("sack", 0) * d["sack"]
    pts += row.get("sack_yards", 0) * d["sack_yard"]
    pts += row.get("interception", 0) * d["interception"]
    pts += row.get("pass_defended", 0) * d["pass_defended"]
    pts += row.get("forced_fumble", 0) * d["forced_fumble"]
    pts += row.get("fumble_recovered", 0) * d["fumble_recovered"]
    pts += row.get("safety", 0) * d["safety"]
    pts += row.get("def_td", 0) * d["defensive_td"]
    return pts


def score_offense_row(row, cfg) -> float:
    o = cfg["offense"]
    pts = 0.0
    pts += row.get("pass_yards", 0) * o["pass_yard"]
    pts += row.get("pass_td", 0) * o["pass_td"]
    pts += row.get("pass_int", 0) * o["interception_thrown"]
    pts += row.get("pass_2pt", 0) * o["pass_2pc"]
    pts += row.get("rush_yards", 0) * o["rush_yard"]
    pts += row.get("rush_td", 0) * o["rush_td"]
    pts += row.get("rush_2pt", 0) * o["rush_2pc"]
    pts += row.get("receptions", 0) * o["reception"]
    pts += row.get("rec_yards", 0) * o["rec_yard"]
    pts += row.get("rec_td", 0) * o["rec_td"]
    pts += row.get("fumbles", 0) * o["fumble"]
    pts += row.get("fumbles_lost", 0) * o["fumble_lost"]
    return pts


def score_kicking_row(row, cfg) -> float:
    k = cfg["kicking"]
    pts = 0.0
    pts += row.get("fg_made_0-39", 0) * k["fg_base"]
    pts += row.get("fg_made_40-49", 0) * (k["fg_base"] + k["fg_distance_bonus"]["40-49"])
    pts += row.get("fg_made_50-59", 0) * (k["fg_base"] + k["fg_distance_bonus"]["50-59"])
    pts += row.get("fg_made_60-69", 0) * (k["fg_base"] + k["fg_distance_bonus"]["60-69"])
    pts += row.get("fg_made_70+", 0) * (k["fg_base"] + k["fg_distance_bonus"]["70+"])
    pts += row.get("xp_made", 0) * k["xp"]
    return pts
