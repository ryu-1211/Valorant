"""
登録プレイヤーの最新キャッシュを docs/stats.json に書き出す。
Bot から呼び出されるほか、単体でも実行可能。
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import database as db

DOCS_DIR = Path(__file__).parent / "docs"
OUT_FILE = DOCS_DIR / "stats.json"


def export_stats() -> bool:
    players = db.list_players()
    if not players:
        return False

    records = []
    for p in players:
        pid = db.get_player_id(p["name"], p["tag"])
        data = db.load_cache_force(pid)
        if not data:
            continue

        # stats の value のみを JSON に含める（displayValue も保持）
        stats_out = {}
        for key, entry in data.get("stats", {}).items():
            stats_out[key] = {
                "value":        entry.get("value"),
                "displayValue": entry.get("displayValue", ""),
            }

        records.append({
            "name":                p["name"],
            "tag":                 p["tag"],
            "peak_rank":           data.get("peak_rank", "不明"),
            "clutch_success_rate": data.get("clutch_success_rate", 0.0),
            "clutch_wins":         data.get("clutch_wins", 0),
            "clutch_attempts":     data.get("clutch_attempts", 0),
            "stats":               stats_out,
        })

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "players":    records,
    }

    DOCS_DIR.mkdir(exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[export] {len(records)} 人分を {OUT_FILE} に書き出しました")
    return True


def git_push(commit_msg: str = "update stats") -> bool:
    """docs/stats.json を git commit して push する。失敗しても例外を投げない。"""
    repo = Path(__file__).parent
    try:
        subprocess.run(["git", "add", "docs/stats.json"], cwd=repo, check=True,
                       capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=repo, capture_output=True
        )
        if result.returncode == 0:
            print("[export] 変更なし — push スキップ")
            return True  # 差分なし

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
