"""
登録プレイヤーの統計データを docs/stats.json に書き出す。
複数シーズン対応: season_list + seasons[season_id] 構造で出力。
"""

import json
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


def export_stats() -> bool:
    players = db.list_players()
    if not players:
        return False

    # 全シーズン ID の収集（全プレイヤーの union）
    all_season_ids: set[str] = set()
    player_season_data: dict[str, dict] = {}  # "name#tag" -> {season_id: record}
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

        for sid, data in cached_seasons.items():
            all_season_ids.add(sid)
            player_season_data[key][sid] = _build_player_record(p, data)

            # season_list をマスターリストに追加（重複排除）
            s_meta = data.get("season", {})
            if s_meta and s_meta.get("id") and not any(
                x.get("id") == s_meta["id"] for x in season_list_master
            ):
                season_list_master.append(s_meta)

    if not player_season_data:
        return False

    # season_list を新しい順（API順 = 最新が先頭）に保つ
    # UUID辞書順ではなく、API が返した順序（episodeName/actName）を尊重するためソートしない
    # ただし重複がないことは保証済みなのでそのまま使う

    # "current" キーを先頭シーズン ID に統合
    current_id = season_list_master[0]["id"] if season_list_master else "current"

    # シーズン別プレイヤーリストを構築
    seasons_out: dict[str, list] = {}
    for season_id in all_season_ids:
        if season_id == "current":
            continue  # 後でマージ
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

    payload = {
        "updated_at":       datetime.now(timezone.utc).isoformat(),
        "current_season_id": current_id,
        "season_list":      season_list_master,
        "seasons":          seasons_out,
        "players": seasons_out.get(current_id, []),
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
