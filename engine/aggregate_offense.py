"""
Aggregiert Offense-Rohkategorien (Passing/Rushing/Receiving/Fumbles) aus
nflverse play-by-play Daten, fuer Saisons, die im offiziellen
`player_stats` Release noch nicht enthalten sind.

Output-Schema (pro Spieler, pro Saison):
    player_id, player_name, season, games_played,
    pass_yards, pass_td, pass_int, pass_2pt,
    rush_yards, rush_td, rush_2pt,
    receptions, rec_yards, rec_td,
    fumbles, fumbles_lost
"""
import pandas as pd


def aggregate_offense_from_pbp(pbp: pd.DataFrame, season: int) -> pd.DataFrame:
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

    pass_plays = pbp[pbp["play_type"] == "pass"]
    for _, r in pass_plays.iterrows():
        pid, name, gid = r["passer_player_id"], r["passer_player_name"], r["game_id"]
        if pd.isna(pid):
            continue
        yards = r["yards_gained"] if pd.notna(r["yards_gained"]) else 0
        bump(pid, name, gid,
             pass_yards=yards if r.get("complete_pass") == 1 else 0,
             pass_td=1 if r.get("pass_touchdown") == 1 else 0,
             pass_int=1 if r.get("interception") == 1 else 0,
             pass_2pt=1 if (r.get("two_point_attempt") == 1 and r.get("two_point_conv_result") == "success") else 0)

    rush_plays = pbp[pbp["play_type"] == "run"]
    for _, r in rush_plays.iterrows():
        pid, name, gid = r["rusher_player_id"], r["rusher_player_name"], r["game_id"]
        if pd.isna(pid):
            continue
        yards = r["yards_gained"] if pd.notna(r["yards_gained"]) else 0
        bump(pid, name, gid,
             rush_yards=yards,
             rush_td=1 if r.get("rush_touchdown") == 1 else 0,
             rush_2pt=1 if (r.get("two_point_attempt") == 1 and r.get("two_point_conv_result") == "success") else 0)

    rec_plays = pbp[pbp["play_type"] == "pass"]
    for _, r in rec_plays.iterrows():
        pid, name, gid = r["receiver_player_id"], r["receiver_player_name"], r["game_id"]
        if pd.isna(pid):
            continue
        yards = r["yards_gained"] if pd.notna(r["yards_gained"]) else 0
        bump(pid, name, gid,
             receptions=1 if r.get("complete_pass") == 1 else 0,
             rec_yards=yards if r.get("complete_pass") == 1 else 0,
             rec_td=1 if r.get("pass_touchdown") == 1 and r.get("complete_pass") == 1 else 0)

    fumble_plays = pbp[pbp["fumble"] == 1]
    for _, r in fumble_plays.iterrows():
        pid, name, gid = r.get("fumbled_1_player_id"), r.get("fumbled_1_player_name"), r["game_id"]
        if pd.isna(pid):
            continue
        bump(pid, name, gid,
             fumbles=1,
             fumbles_lost=1 if r.get("fumble_lost") == 1 else 0)

    df = pd.DataFrame(list(acc.values())).fillna(0)
    df["season"] = season
    df["games_played"] = df["player_id"].map(lambda p: len(games.get(p, set())))

    for col in ["pass_yards", "pass_td", "pass_int", "pass_2pt",
                "rush_yards", "rush_td", "rush_2pt",
                "receptions", "rec_yards", "rec_td", "fumbles", "fumbles_lost"]:
        if col not in df.columns:
            df[col] = 0.0

    return df[["player_id", "player_name", "season", "games_played",
               "pass_yards", "pass_td", "pass_int", "pass_2pt",
               "rush_yards", "rush_td", "rush_2pt",
               "receptions", "rec_yards", "rec_td", "fumbles", "fumbles_lost"]]


def from_official_release(df_release: pd.DataFrame, season: int) -> pd.DataFrame:
    """Mappt das offizielle player_stats-Release (falls Saison enthalten) auf dasselbe Schema."""
    sub = df_release[df_release["season"] == season]
    g = sub.groupby(["player_id", "player_name"], as_index=False).agg(
        games_played=("week", "nunique"),
        pass_yards=("passing_yards", "sum"),
        pass_td=("passing_tds", "sum"),
        pass_int=("interceptions", "sum"),
        pass_2pt=("passing_2pt_conversions", "sum"),
        rush_yards=("rushing_yards", "sum"),
        rush_td=("rushing_tds", "sum"),
        rush_2pt=("rushing_2pt_conversions", "sum"),
        receptions=("receptions", "sum"),
        rec_yards=("receiving_yards", "sum"),
        rec_td=("receiving_tds", "sum"),
    )
    fumbles = sub.groupby("player_id").apply(
        lambda x: (x["sack_fumbles"] + x["rushing_fumbles"] + x["receiving_fumbles"]).sum()
    ).rename("fumbles")
    fumbles_lost = sub.groupby("player_id").apply(
        lambda x: (x["sack_fumbles_lost"] + x["rushing_fumbles_lost"] + x["receiving_fumbles_lost"]).sum()
    ).rename("fumbles_lost")
    g = g.merge(fumbles, on="player_id", how="left").merge(fumbles_lost, on="player_id", how="left")
    g["fumbles"] = g["fumbles"].fillna(0)
    g["fumbles_lost"] = g["fumbles_lost"].fillna(0)
    g["season"] = season
    return g
