"""Aggregiert Kicker-Rohkategorien aus PBP: FGs pro Distanz-Bucket + XPs."""
import pandas as pd


def _fg_bucket(distance):
    if distance < 40:
        return "0-39"
    if distance < 50:
        return "40-49"
    if distance < 60:
        return "50-59"
    if distance < 70:
        return "60-69"
    return "70+"


def aggregate_kicking_from_pbp(pbp: pd.DataFrame, season: int) -> pd.DataFrame:
    acc: dict = {}
    games: dict = {}

    def bump(pid, name, gid, **kwargs):
        if pd.isna(pid):
            return
        if pid not in acc:
            acc[pid] = {"player_id": pid, "player_name": name}
        for k, v in kwargs.items():
            acc[pid][k] = acc[pid].get(k, 0) + v
        games.setdefault(pid, set()).add(gid)

    fg = pbp[(pbp["field_goal_attempt"] == 1) & (pbp["field_goal_result"] == "made")]
    for _, r in fg.iterrows():
        bucket = _fg_bucket(r["kick_distance"]) if pd.notna(r["kick_distance"]) else "0-39"
        bump(r["kicker_player_id"], r["kicker_player_name"], r["game_id"], **{f"fg_made_{bucket}": 1})

    xp = pbp[(pbp["extra_point_attempt"] == 1) & (pbp["extra_point_result"] == "good")]
    for _, r in xp.iterrows():
        bump(r["kicker_player_id"], r["kicker_player_name"], r["game_id"], xp_made=1)

    df = pd.DataFrame(list(acc.values())).fillna(0)
    df["season"] = season
    df["games_played"] = df["player_id"].map(lambda p: len(games.get(p, set())))
    for col in ["fg_made_0-39", "fg_made_40-49", "fg_made_50-59", "fg_made_60-69", "fg_made_70+", "xp_made"]:
        if col not in df.columns:
            df[col] = 0.0
    return df
