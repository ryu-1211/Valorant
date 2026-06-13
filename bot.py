import asyncio
import os
from typing import Literal

import discord
from discord import app_commands
from dotenv import load_dotenv

import database as db
import export as exporter
import tracker
from config import (
    CACHE_TTL_SECONDS,
    MEDAL_EMOJIS,
    PROFILE_SECTIONS,
    RANK_EMOJIS,
    STAT_MAP,
)

load_dotenv()

# ── Bot セットアップ ──────────────────────────────────────────

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


async def _auto_refresh_loop():
    """1時間ごとに全プレイヤーデータを更新して Web に反映する。"""
    await client.wait_until_ready()
    while not client.is_closed():
        await asyncio.sleep(3600)
        print("[bot] 定期更新開始")
        await _gather_all_stats(force=True)
        await asyncio.get_event_loop().run_in_executor(None, _export_and_push)
        print("[bot] 定期更新完了")


def _export_and_push():
    if exporter.export_stats():
        exporter.git_push("auto: update stats")


@client.event
async def on_ready():
    db.init_db()
    await tree.sync()
    print(f"[bot] ログイン完了: {client.user}")
    client.loop.create_task(_auto_refresh_loop())


# ── ユーティリティ ────────────────────────────────────────────

def _rank_emoji(rank_str: str) -> str:
    for name, emoji in RANK_EMOJIS.items():
        if name.lower() in rank_str.lower():
            return emoji
    return "🎮"


async def _fetch_with_cache(name: str, tag: str, force: bool = False,
                            seasons: int = 1) -> dict | None:
    """
    キャッシュを確認し、期限切れなら tracker.gg から取得してキャッシュを更新。
    seasons=1 なら最新シーズンのみ、2以上なら複数シーズンを取得。
    """
    pid = db.get_player_id(name, tag)
    if pid is None:
        return None

    if not force:
        cached = db.load_cache(pid, CACHE_TTL_SECONDS, "current")
        if cached:
            return cached

    if seasons > 1:
        def _fetch():
            return tracker.fetch_recent_seasons(name, tag, count=seasons)
        multi = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        if multi:
            for sid, record in multi["seasons"].items():
                db.save_cache(pid, record, sid)
            # "current" にも最新シーズンを保存（後方互換）
            current_id = multi["current_season_id"]
            if current_id in multi["seasons"]:
                db.save_cache(pid, multi["seasons"][current_id], "current")
            return multi["seasons"].get(current_id)
    else:
        data = await asyncio.get_event_loop().run_in_executor(
            None, tracker.fetch_stats, name, tag
        )
        if data:
            db.save_cache(pid, data, "current")
            return data

    return db.load_cache_force(pid, "current")


async def _gather_all_stats(force: bool = False, seasons: int = 1) -> list[dict]:
    """全登録プレイヤーのデータを並列取得。"""
    players = db.list_players()
    tasks = [_fetch_with_cache(p["name"], p["tag"], force, seasons) for p in players]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


# ── /add ─────────────────────────────────────────────────────

@tree.command(name="add", description="プレイヤーをランキングに追加します")
@app_commands.describe(name="Valorant 名前（# より前）", tag="タグ（# より後）")
async def cmd_add(interaction: discord.Interaction, name: str, tag: str):
    await interaction.response.defer()

    added = db.add_player(name, tag)
    if not added:
        await interaction.followup.send(f"⚠️ `{name}#{tag}` はすでに登録されています。")
        return

    data = await _fetch_with_cache(name, tag, force=True)
    if not data:
        db.remove_player(name, tag)
        await interaction.followup.send(
            f"❌ `{name}#{tag}` のデータを取得できませんでした。\n"
            "名前とタグを確認してください。"
        )
        return

    rank = data["stats"].get("rank", {}).get("displayValue") or data["peak_rank"]
    embed = discord.Embed(
        title=f"✅ {name}#{tag} を追加しました",
        color=discord.Color.green(),
    )
    embed.add_field(name="ランク", value=f"{_rank_emoji(rank)} {rank}", inline=True)
    embed.add_field(
        name="ACS",
        value=tracker.get_display(data["stats"], "scorePerRound"),
        inline=True,
    )
    embed.add_field(
        name="K/D",
        value=tracker.get_display(data["stats"], "kDRatio"),
        inline=True,
    )
    await interaction.followup.send(embed=embed)


# ── /remove ───────────────────────────────────────────────────

@tree.command(name="remove", description="プレイヤーをランキングから削除します")
@app_commands.describe(name="Valorant 名前", tag="タグ")
async def cmd_remove(interaction: discord.Interaction, name: str, tag: str):
    removed = db.remove_player(name, tag)
    if removed:
        await interaction.response.send_message(f"🗑️ `{name}#{tag}` を削除しました。")
    else:
        await interaction.response.send_message(f"⚠️ `{name}#{tag}` は登録されていません。")


# ── /list ─────────────────────────────────────────────────────

@tree.command(name="list", description="登録中のプレイヤー一覧を表示します")
async def cmd_list(interaction: discord.Interaction):
    players = db.list_players()
    if not players:
        await interaction.response.send_message("登録されているプレイヤーはいません。`/add` で追加してください。")
        return

    lines = [f"`{i+1}.` {p['name']}#{p['tag']}" for i, p in enumerate(players)]
    embed = discord.Embed(
        title=f"📋 登録プレイヤー一覧（{len(players)} 人）",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=embed)


# ── /ranking ──────────────────────────────────────────────────

StatChoice = Literal[
    "acs", "kd", "kda", "kast", "hs", "winrate",
    "clutch", "adr", "fb", "aces", "kills", "matches"
]

@tree.command(name="ranking", description="指定スタッツでランキングを表示します（デフォルト: ACS）")
@app_commands.describe(stat="ランキングの基準スタッツ")
async def cmd_ranking(
    interaction: discord.Interaction,
    stat: StatChoice = "acs",
):
    await interaction.response.defer()

    all_stats = await _gather_all_stats()
    if not all_stats:
        await interaction.followup.send("登録プレイヤーがいないかデータ取得に失敗しました。")
        return

    stat_key, stat_label = STAT_MAP[stat]

    # クラッチ成功率は特別処理
    def sort_key(d: dict) -> float:
        if stat == "clutch":
            return d.get("clutch_success_rate", 0.0)
        return tracker.get_value(d["stats"], stat_key)

    ranked = sorted(all_stats, key=sort_key, reverse=True)

    lines = []
    for i, d in enumerate(ranked):
        medal = MEDAL_EMOJIS[i] if i < 3 else f"`{i+1}.`"
        if stat == "clutch":
            value_str = (
                f"{d['clutch_success_rate']}% "
                f"({d['clutch_wins']}/{d['clutch_attempts']})"
            )
        else:
            value_str = tracker.get_display(d["stats"], stat_key)
        lines.append(f"{medal} **{d['name']}#{d['tag']}** — {value_str}")

    embed = discord.Embed(
        title=f"🏆 {stat_label} ランキング",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="データは tracker.gg より取得（キャッシュ: 30分）")
    await interaction.followup.send(embed=embed)


# ── /profile ──────────────────────────────────────────────────

@tree.command(name="profile", description="プレイヤーの詳細スタッツを表示します")
@app_commands.describe(name="Valorant 名前", tag="タグ")
async def cmd_profile(interaction: discord.Interaction, name: str, tag: str):
    await interaction.response.defer()

    # 未登録でも検索できるよう一時取得
    pid = db.get_player_id(name, tag)
    if pid is not None:
        data = await _fetch_with_cache(name, tag)
    else:
        data = await asyncio.get_event_loop().run_in_executor(
            None, tracker.fetch_stats, name, tag
        )

    if not data:
        await interaction.followup.send(f"❌ `{name}#{tag}` のデータを取得できませんでした。")
        return

    stats = data["stats"]
    rank_val = stats.get("rank", {}).get("displayValue") or "不明"
    peak = data["peak_rank"]

    embed = discord.Embed(
        title=f"{_rank_emoji(rank_val)} {name}#{tag}",
        description=(
            f"**現在ランク:** {rank_val}　"
            f"**ピーク:** {_rank_emoji(peak)} {peak}"
        ),
        color=discord.Color.red(),
        url=f"https://tracker.gg/valorant/profile/riot/{name}%23{tag}/overview",
    )

    for section, fields in PROFILE_SECTIONS.items():
        values = []
        for key, label in fields:
            if key == "peakRank":
                val = peak
            elif key == "clutchesPercentage":
                val = (
                    f"{data['clutch_success_rate']}% "
                    f"({data['clutch_wins']}/{data['clutch_attempts']})"
                )
            else:
                val = tracker.get_display(stats, key)
            values.append(f"**{label}:** {val}")
        embed.add_field(name=f"─── {section} ───", value="\n".join(values), inline=True)

    embed.set_footer(text="tracker.gg より取得")
    await interaction.followup.send(embed=embed)


# ── /update ───────────────────────────────────────────────────

@tree.command(name="update", description="全プレイヤーのデータを更新します")
@app_commands.describe(seasons="取得するシーズン数（1=最新のみ / 3=直近3シーズン）")
async def cmd_update(interaction: discord.Interaction, seasons: int = 1):
    await interaction.response.defer()
    players = db.list_players()
    if not players:
        await interaction.followup.send("登録プレイヤーがいません。")
        return

    label = f"直近 {seasons} シーズン" if seasons > 1 else "最新シーズン"
    msg = await interaction.followup.send(
        f"⏳ {len(players)} 人の{label}データを更新中...", wait=True
    )
    results = await _gather_all_stats(force=True, seasons=seasons)
    await asyncio.get_event_loop().run_in_executor(None, _export_and_push)
    await msg.edit(
        content=f"✅ {len(results)}/{len(players)} 人の{label}データを更新してWebページに反映しました。"
    )


# ── 起動 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(".env に DISCORD_TOKEN が設定されていません。")
    client.run(token)
