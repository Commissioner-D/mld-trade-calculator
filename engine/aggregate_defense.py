"""
Aggregiert IDP-Defense-Rohkategorien aus nflverse play-by-play Daten.

Notwendig, weil das offizielle nflverse `player_stats_def` Release-File
regelmaessig hinter der aktuellen Saison zurueckliegt. Dieses Modul baut
dieselben Rohkategorien direkt aus dem Play-by-Play, damit die aktuelle
Saison trotzdem verfuegbar ist.

Output-Schema (pro Spieler, pro Saison, aufsummiert):
    player_id, player_name, season, games_played,
    solo_tackle, assisted_tackle, tackle_for_loss, sack, sack_yards,
    interception, pass_defended, forced_fumble, fumble_recovered,
    safety, def_td
"""
import pandas as pd
import numpy as np


def _add_counts(acc: dict, player_id, name, category, amount=1):
    if pd.isna(player_id):
        return
    key = player_id
    if key not in acc:
        acc[key] = {"player_id": key, "player_name": name}
    acc[key][category] = acc[key].get(category, 0) + amount


def aggregate_defense_from_pbp(pbp: pd.DataFrame, season: int) -> pd.DataFrame:
    acc: dict = {}
    games_played: dict = {}

    def track_game(pid, name, game_id):
        if pd.isna(pid):
            return
        games_played.setdefault(pid, {"player_name": name, "games": set()})
        games_played[pid]["games"].add(game_id)

    # --- Solo tackles (up to 2 credited players per play) ---
    for i in (1, 2):
        col_id, col_name = f"solo_tackle_{i}_player_id", f"solo_tackle_{i}_player_name"
        if col_id in pbp.columns:
            sub = pbp.dropna(subset=[col_id])
            for pid, name, gid in zip(sub[col_id], sub[col_name], sub["game_id"]):
                _add_counts(acc, pid, name, "solo_tackle")
                track_game(pid, name, gid)

    # --- Assisted tackles (up to 4 credited players per play) ---
    for i in (1, 2, 3, 4):
        col_id, col_name = f"assist_tackle_{i}_player_id", f"assist_tackle_{i}_player_name"
        if col_id in pbp.columns:
            sub = pbp.dropna(subset=[col_id])
            for pid, name, gid in zip(sub[col_id], sub[col_name], sub["game_id"]):
                _add_counts(acc, pid, name, "assisted_tackle")
                track_game(pid, name, gid)

    # --- Tackle for loss ---
    for i in (1, 2):
        col_id, col_name = f"tackle_for_loss_{i}_player_id", f"tackle_for_loss_{i}_player_name"
        if col_id in pbp.columns:
            sub = pbp.dropna(subset=[col_id])
            for pid, name, gid in zip(sub[col_id], sub[col_name], sub["game_id"]):
                _add_counts(acc, pid, name, "tackle_for_loss")
                track_game(pid, name, gid)

    # --- Sacks: full sack = 1.0, half sacks = 0.5 each; yards from yards_gained (negative on sack plays) ---
    if "sack_player_id" in pbp.columns:
        sub = pbp.dropna(subset=["sack_player_id"])
        for pid, name, yards, gid in zip(sub["sack_player_id"], sub["sack_player_name"], sub["yards_gained"], sub["game_id"]):
            _add_counts(acc, pid, name, "sack", 1.0)
            _add_counts(acc, pid, name, "sack_yards", abs(yards) if pd.notna(yards) else 0)
            track_game(pid, name, gid)
    for i in (1, 2):
        col_id, col_name = f"half_sack_{i}_player_id", f"half_sack_{i}_player_name"
        if col_id in pbp.columns:
            sub = pbp.dropna(subset=[col_id])
            for pid, name, yards, gid in zip(sub[col_id], sub[col_name], sub["yards_gained"], sub["game_id"]):
                _add_counts(acc, pid, name, "sack", 0.5)
                _add_counts(acc, pid, name, "sack_yards", abs(yards) / 2 if pd.notna(yards) else 0)
                track_game(pid, name, gid)

    # --- Interceptions ---
    if "interception_player_id" in pbp.columns:
        sub = pbp.dropna(subset=["interception_player_id"])
        for pid, name, gid in zip(sub["interception_player_id"], sub["interception_player_name"], sub["game_id"]):
            _add_counts(acc, pid, name, "interception")
            track_game(pid, name, gid)

    # --- Pass defended ---
    for i in (1, 2):
        col_id, col_name = f"pass_defense_{i}_player_id", f"pass_defense_{i}_player_name"
        if col_id in pbp.columns:
            sub = pbp.dropna(subset=[col_id])
            for pid, name, gid in zip(sub[col_id], sub[col_name], sub["game_id"]):
                _add_counts(acc, pid, name, "pass_defended")
                track_game(pid, name, gid)

    # --- Forced fumbles ---
    for i in (1, 2):
        col_id, col_name = f"forced_fumble_player_{i}_player_id", f"forced_fumble_player_{i}_player_name"
        if col_id in pbp.columns:
            sub = pbp.dropna(subset=[col_id])
            for pid, name, gid in zip(sub[col_id], sub[col_name], sub["game_id"]):
                _add_counts(acc, pid, name, "forced_fumble")
                track_game(pid, name, gid)

    # --- Fumble recoveries (any recoverer; filtered to IDP positions downstream) ---
    for i in (1, 2):
        col_id, col_name = f"fumble_recovery_{i}_player_id", f"fumble_recovery_{i}_player_name"
        if col_id in pbp.columns:
            sub = pbp.dropna(subset=[col_id])
            for pid, name, gid in zip(sub[col_id], sub[col_name], sub["game_id"]):
                _add_counts(acc, pid, name, "fumble_recovered")
                track_game(pid, name, gid)

    # --- Safeties ---
    if "safety_player_id" in pbp.columns:
        sub = pbp.dropna(subset=["safety_player_id"])
        for pid, name, gid in zip(sub["safety_player_id"], sub["safety_player_name"], sub["game_id"]):
            _add_counts(acc, pid, name, "safety")
            track_game(pid, name, gid)

    # --- Defensive TDs: td_player scored a TD while their team was on defense ---
    if "td_player_id" in pbp.columns:
        sub = pbp[(pbp["touchdown"] == 1) & (pbp["td_team"] == pbp["defteam"])].dropna(subset=["td_player_id"])
        for pid, name, gid in zip(sub["td_player_id"], sub["td_player_name"], sub["game_id"]):
            _add_counts(acc, pid, name, "def_td")
            track_game(pid, name, gid)

    df = pd.DataFrame(list(acc.values())).fillna(0)
    df["season"] = season
    games_df = pd.DataFrame(
        [{"player_id": pid, "games_played": len(v["games"])} for pid, v in games_played.items()]
    )
    df = df.merge(games_df, on="player_id", how="left")
    df["games_played"] = df["games_played"].fillna(0).astype(int)

    for col in ["solo_tackle", "assisted_tackle", "tackle_for_loss", "sack", "sack_yards",
                "interception", "pass_defended", "forced_fumble", "fumble_recovered",
                "safety", "def_td"]:
        if col not in df.columns:
            df[col] = 0.0

    return df[["player_id", "player_name", "season", "games_played",
               "solo_tackle", "assisted_tackle", "tackle_for_loss", "sack", "sack_yards",
               "interception", "pass_defended", "forced_fumble", "fumble_recovered",
               "safety", "def_td"]]


def from_official_release(df_release: pd.DataFrame, season: int) -> pd.DataFrame:
    """Falls das offizielle player_stats_def-Release die Saison bereits enthaelt,
    hier auf dasselbe Schema mappen statt aus PBP neu zu aggregieren."""
    g = df_release[df_release["season"] == season].groupby(
        ["player_id", "player_name"], as_index=False
    ).agg(
        games_played=("week", "nunique"),
        solo_tackle=("def_tackles_solo", "sum"),
        assisted_tackle=("def_tackle_assists", "sum"),
        tackle_for_loss=("def_tackles_for_loss", "sum"),
        sack=("def_sacks", "sum"),
        sack_yards=("def_sack_yards", "sum"),
        interception=("def_interceptions", "sum"),
        pass_defended=("def_pass_defended", "sum"),
        forced_fumble=("def_fumbles_forced", "sum"),
        fumble_recovered=("def_fumble_recovery_own", "sum"),
        safety=("def_safety", "sum"),
        def_td=("def_tds", "sum"),
    )
    g["fumble_recovered"] = g["fumble_recovered"] + df_release[df_release["season"] == season].groupby(
        ["player_id"]
    )["def_fumble_recovery_opp"].sum().reindex(g["player_id"]).fillna(0).values
    g["season"] = season
    return g
