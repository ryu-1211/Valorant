"""
登録プレイヤーの統計データを docs/stats.json に書き出す。
複数シーズン対応: season_list + seasons[season_id] 構造で出力。
"""

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import database as db

DOCS_DIR = Path(__file__).parent / "docs"
OUT_FILE = DOCS_DIR / "stats.json"


def _build_stats_out(raw_stats: dict) -> dict:
    """stats dict から value/displayValue のみを抽出（JSON サイズ削減）。"""
    return {
        key: {
            "value":        entry.get("value"),
            "displayValue": entry.get("displayValue", ""),
        }
        for key, entry in raw_stats.items()
    }


def _build_player_record(p: dict, data: dict) -> dict:
    return {
        "name":        p["name"],
        "tag":         p["tag"],
        "peak_rank":   data.get("peak_rank", "不明"),
        "clutch":      data.get("clutch", {}),
        # 後方互換フィールド
        "clutch_success_rate": data.get("clutch_success_rate", 0.0),
        "clutch_wins":         data.get("clutch_wins", 0),
        "clutch_attempts":     data.get("clutch_attempts", 0),
        "season":      data.get("season", {}),
        "stats":       _build_stats_out(data.get("stats", {})),
    }


# ── オールシーズン集計 ────────────────────────────────────────
# 単純合計すべきカウント系スタッツ
_SUM_KEYS = [
    "roundsPlayed", "roundsWon", "roundsLost",
    "matchesPlayed", "matchesWon", "matchesLost", "matchesTied",
    "kills", "deaths", "assists", "score", "damage",
    "dealtHeadshots", "dealtBodyshots", "dealtLegshots",
    "firstBloods", "firstDeaths", "aces", "mVPs", "flawless",
    "teamAces", "plants", "defuses",
    "kills1K", "kills2K", "kills3K", "kills4K", "kills5K",
    "attackScore", "attackRoundsPlayed", "attackKills", "attackDeaths",
    "attackFirstBloods", "attackFirstDeaths",
    "defenseScore", "defenseRoundsPlayed", "defenseKills", "defenseDeaths",
    "defenseFirstBloods", "defenseFirstDeaths",
    "clutches", "clutchesLost",
    "clutches1v1", "clutches1v2", "clutches1v3", "clutches1v4", "clutches1v5",
    "clutchesLost1v1", "clutchesLost1v2", "clutchesLost1v3", "clutchesLost1v4", "clutchesLost1v5",
]


def _sv(stats: dict, key: str) -> float:
    try:
        return float(stats.get(key, {}).get("value") or 0)
    except (TypeError, ValueError):
        return 0.0


def _entry(value, display: str) -> dict:
    return {"value": value, "displayValue": display}


def _aggregate_player_seasons(season_datas: list[dict]) -> dict:
    """1プレイヤーの複数シーズン分の生 data を合算し、率は再計算した data を返す。"""
    sums = {k: 0.0 for k in _SUM_KEYS}
    kast_rounds = 0.0
    for data in season_datas:
        st = data.get("stats", {})
        for k in _SUM_KEYS:
            sums[k] += _sv(st, k)
        kast_rounds += _sv(st, "kAST") / 100.0 * _sv(st, "roundsPlayed")

    rounds  = sums["roundsPlayed"] or 1
    matches = sums["matchesPlayed"] or 1
    deaths  = sums["deaths"] or 1
    shots   = (sums["dealtHeadshots"] + sums["dealtBodyshots"] + sums["dealtLegshots"]) or 1
    atk_r   = sums["attackRoundsPlayed"] or 1
    def_r   = sums["defenseRoundsPlayed"] or 1

    acs     = sums["score"] / rounds
    kd      = sums["kills"] / deaths
    kda     = (sums["kills"] + sums["assists"] / 2) / deaths
    kast    = kast_rounds / rounds * 100
    hs      = sums["dealtHeadshots"] / shots * 100
    adr     = sums["damage"] / rounds
    winpct  = sums["matchesWon"] / matches * 100
    atk_acs = sums["attackScore"] / atk_r
    def_acs = sums["defenseScore"] / def_r

    out: dict = {
        "scorePerRound":        _entry(acs, f"{acs:.1f}"),
        "kDRatio":              _entry(kd, f"{kd:.2f}"),
        "kDARatio":             _entry(kda, f"{kda:.2f}"),
        "kAST":                 _entry(kast, f"{kast:.1f}%"),
        "headshotsPercentage":  _entry(hs, f"{hs:.1f}%"),
        "damagePerRound":       _entry(adr, f"{adr:.1f}"),
        "matchesWinPct":        _entry(winpct, f"{winpct:.1f}%"),
        "attackScorePerRound":  _entry(atk_acs, f"{atk_acs:.1f}"),
        "defenseScorePerRound": _entry(def_acs, f"{def_acs:.1f}"),
    }
    for k in _SUM_KEYS:
        iv = int(round(sums[k]))
        out[k] = _entry(iv, f"{iv:,}")

    # クラッチ集計
    cw = int(sums["clutches"]); cl = int(sums["clutchesLost"]); ca = cw + cl
    crate = round(cw / ca * 100, 1) if ca > 0 else 0.0
    breakdown = {}
    for n in range(1, 6):
        w = int(sums[f"clutches1v{n}"]); l = int(sums[f"clutchesLost1v{n}"]); a = w + l
        breakdown[f"1v{n}"] = {
            "wins": w, "losses": l, "attempts": a,
            "rate": round(w / a * 100, 1) if a > 0 else 0.0,
        }
    clutch = {"success_rate": crate, "wins": cw, "losses": cl,
              "attempts": ca, "breakdown": breakdown}

    return {
        "peak_rank": "—",
        "clutch": clutch,
        "clutch_success_rate": crate,
        "clutch_wins": cw,
        "clutch_attempts": ca,
        "season": {"id": "all", "shortName": "ALL", "name": "オールシーズン",
                   "episodeName": "All", "actName": ""},
        "stats": out,
    }


MIN_EPISODE = 6  # これ以降のシーズンのみ表示（Episode 6 〜。それより古いものは除外）


def _season_sort_key(s: dict) -> tuple[int, int]:
    ep = re.search(r"(\d+)", s.get("episodeName", "") or "")
    ac = re.search(r"(\d+)", s.get("actName", "") or "")
    # shortName "E26: A3" からのフォールバック
    if not ep or not ac:
        m = re.search(r"E(\d+).*?A(\d+)", s.get("shortName", "") or "")
        if m:
            return (int(m.group(1)), int(m.group(2)))
    return (int(ep.group(1)) if ep else 0, int(ac.group(1)) if ac else 0)


def _keep_season(s: dict) -> bool:
    """Episode/Season 番号が MIN_EPISODE 以上なら表示対象。"""
    return _season_sort_key(s)[0] >= MIN_EPISODE


def export_stats() -> bool:
    players = db.list_players()
    if not players:
        return False

    # 全シーズン ID の収集（全プレイヤーの union）
    all_season_ids: set[str] = set()
    player_season_data: dict[str, dict] = {}  # "name#tag" -> {season_id: record}
    player_raw_seasons: dict[str, dict] = {}  # "name#tag" -> {season_id: 生data}（集計用）
    season_list_master: list[dict] = []

    for p in players:
        pid = db.get_player_id(p["name"], p["tag"])
        if pid is None:
            continue
        cached_seasons = db.load_all_cached_seasons(pid)
        if not cached_seasons:
            continue

        key = f"{p['name']}#{p['tag']}"
        player_season_data[key] = {}
        player_raw_seasons[key] = {}

        for sid, data in cached_seasons.items():
            if sid.startswith(("agents:", "maps:", "combos:")):
                continue  # エージェント/マップ/組み合わせ別データは別処理
            all_season_ids.add(sid)
            player_season_data[key][sid] = _build_player_record(p, data)
            if sid != "current":
                player_raw_seasons[key][sid] = data

            # season_list をマスターリストに追加（重複排除・Episode 6 以降のみ）
            s_meta = data.get("season", {})
            if s_meta and s_meta.get("id") and _keep_season(s_meta) and not any(
                x.get("id") == s_meta["id"] for x in season_list_master
            ):
                season_list_master.append(s_meta)

    if not player_season_data:
        return False

    # season_list を新しい順（エピソード→アクトの降順）に並べる。
    season_list_master.sort(key=_season_sort_key, reverse=True)

    # 表示対象シーズン ID の集合
    kept_ids = {s["id"] for s in season_list_master}

    # "current" キーを先頭シーズン ID（=最新）に統合
    current_id = season_list_master[0]["id"] if season_list_master else "current"

    # シーズン別プレイヤーリストを構築（Episode 6 以降のみ）
    seasons_out: dict[str, list] = {}
    for season_id in all_season_ids:
        if season_id == "current" or season_id not in kept_ids:
            continue
        records = []
        for p in players:
            key = f"{p['name']}#{p['tag']}"
            if key in player_season_data and season_id in player_season_data[key]:
                records.append(player_season_data[key][season_id])
        if records:
            seasons_out[season_id] = records

    # "current" キャッシュのプレイヤーを current_id にマージ（未登録プレイヤーのみ追加）
    if "current" in all_season_ids:
        current_records = []
        for p in players:
            key = f"{p['name']}#{p['tag']}"
            if key in player_season_data and "current" in player_season_data[key]:
                current_records.append(player_season_data[key]["current"])
        if current_records:
            existing = {(r["name"], r["tag"]) for r in seasons_out.get(current_id, [])}
            for rec in current_records:
                if (rec["name"], rec["tag"]) not in existing:
                    seasons_out.setdefault(current_id, []).append(rec)
                    existing.add((rec["name"], rec["tag"]))

    # current_id に誰もいない場合は "current" を独立キーとして残す
    if current_id not in seasons_out or not seasons_out[current_id]:
        current_id = "current"
        seasons_out["current"] = []
        for p in players:
            key = f"{p['name']}#{p['tag']}"
            if key in player_season_data and "current" in player_season_data[key]:
                seasons_out["current"].append(player_season_data[key]["current"])

    # ── オールシーズン集計（Episode 6 以降のみ対象）──
    all_records = []
    for p in players:
        key = f"{p['name']}#{p['tag']}"
        raws = [d for d in player_raw_seasons.get(key, {}).values()
                if _keep_season(d.get("season", {}))]
        if not raws:
            continue
        agg = _aggregate_player_seasons(raws)
        all_records.append(_build_player_record(p, agg))
    if all_records:
        seasons_out["all"] = all_records
        # season_list の先頭に ALL ボタンを追加
        season_list_master.insert(0, {
            "id": "all", "shortName": "ALL", "name": "オールシーズン",
            "episodeName": "All", "actName": "",
        })

    # ── エージェント別 / マップ別 / 組み合わせデータ（現行 / 全期間）──
    agents_out: dict[str, dict] = {}
    maps_out: dict[str, dict] = {}
    combos_out: dict[str, dict] = {}
    for p in players:
        pid = db.get_player_id(p["name"], p["tag"])
        if pid is None:
            continue
        key = f"{p['name']}#{p['tag']}"
        a_cur = db.load_cache_force(pid, "agents:current")
        a_all = db.load_cache_force(pid, "agents:all")
        a_entry = {}
        if a_cur and a_cur.get("agents"):
            a_entry["current"] = a_cur["agents"]
        if a_all and a_all.get("agents"):
            a_entry["all"] = a_all["agents"]
        if a_entry:
            agents_out[key] = a_entry

        m_cur = db.load_cache_force(pid, "maps:current")
        m_all = db.load_cache_force(pid, "maps:all")
        m_entry = {}
        if m_cur and m_cur.get("maps"):
            m_entry["current"] = m_cur["maps"]
        if m_all and m_all.get("maps"):
            m_entry["all"] = m_all["maps"]
        if m_entry:
            maps_out[key] = m_entry

        c_cur = db.load_cache_force(pid, "combos:current")
        c_all = db.load_cache_force(pid, "combos:all")
        c_entry = {}
        if c_cur and c_cur.get("combos"):
            c_entry["current"] = c_cur["combos"]
        if c_all and c_all.get("combos"):
            c_entry["all"] = c_all["combos"]
        if c_entry:
            combos_out[key] = c_entry

    payload = {
        "updated_at":       datetime.now(timezone.utc).isoformat(),
        "current_season_id": current_id,
        "season_list":      season_list_master,
        "seasons":          seasons_out,
        "players": seasons_out.get(current_id, []),
        "agents":           agents_out,
        "maps":             maps_out,
        "combos":           combos_out,
    }

    DOCS_DIR.mkdir(exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    total = sum(len(v) for v in seasons_out.values())
    print(f"[export] {total} 件（{len(seasons_out)} シーズン）を {OUT_FILE} に書き出しました")
    return True


def git_push(commit_msg: str = "update stats") -> bool:
    repo = Path(__file__).parent
    try:
        subprocess.run(["git", "add", "docs/stats.json"], cwd=repo, check=True,
                       capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=repo, capture_output=True
        )
        if result.returncode == 0:
            print("[export] 変更なし — push スキップ")
            return True
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo, check=True,
                       capture_output=True)
        subprocess.run(["git", "push"], cwd=repo, check=True, capture_output=True)
        print("[export] git push 完了")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[export] git push 失敗: {e.stderr.decode(errors='ignore')}")
        return False


if __name__ == "__main__":
    db.init_db()
    if export_stats():
        git_push()
