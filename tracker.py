import time
from urllib.parse import quote
from curl_cffi import requests as cffi_requests

_BASE_URL = "https://api.tracker.gg/api/v2/valorant/standard/profile/riot"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://tracker.gg/",
    "Origin": "https://tracker.gg",
}


def fetch_stats(name: str, tag: str) -> dict | None:
    """
    tracker.gg から指定プレイヤーの最新コンペティティブシーズン統計を返す。
    取得失敗時は None を返す。
    """
    encoded_name = quote(name, safe="")
    url = f"{_BASE_URL}/{encoded_name}%23{tag}"

    try:
        r = cffi_requests.get(
            url,
            headers=_HEADERS,
            impersonate="chrome124",
            timeout=20,
        )
    except Exception as e:
        print(f"[tracker] リクエスト失敗 {name}#{tag}: {e}")
        return None

    if r.status_code == 429:
        print(f"[tracker] レート制限 {name}#{tag} — 60秒待機")
        time.sleep(60)
        return fetch_stats(name, tag)

    if r.status_code != 200:
        print(f"[tracker] HTTP {r.status_code} {name}#{tag}")
        return None

    try:
        data = r.json()
    except Exception:
        print(f"[tracker] JSON パース失敗 {name}#{tag}")
        return None

    segments = data.get("data", {}).get("segments", [])

    season_stats: dict | None = None
    peak_rank_value: str = "不明"

    for seg in segments:
        seg_type = seg.get("type", "")
        playlist = seg.get("attributes", {}).get("playlist", "")

        if seg_type == "season" and playlist == "competitive" and season_stats is None:
            season_stats = seg.get("stats", {})

        if seg_type == "peak-rating" and playlist == "competitive":
            peak_rank_value = (
                seg.get("stats", {})
                .get("peakRating", {})
                .get("displayValue", "不明")
            )

    if not season_stats:
        return None

    # クラッチ成功率を計算（wins / attempts）
    clutch_wins = season_stats.get("clutches", {}).get("value", 0) or 0
    clutch_losses = season_stats.get("clutchesLost", {}).get("value", 0) or 0
    clutch_attempts = clutch_wins + clutch_losses
    clutch_success_rate = (
        round(clutch_wins / clutch_attempts * 100, 1) if clutch_attempts > 0 else 0.0
    )

    return {
        "name": name,
        "tag": tag,
        "peak_rank": peak_rank_value,
        "clutch_success_rate": clutch_success_rate,
        "clutch_wins": int(clutch_wins),
        "clutch_attempts": clutch_attempts,
        "stats": season_stats,
    }


def get_display(stats: dict, key: str) -> str:
    """stats dict から displayValue を取得。なければ '-' を返す。"""
    entry = stats.get(key, {})
    return entry.get("displayValue") or str(entry.get("value", "-"))


def get_value(stats: dict, key: str) -> float:
    """stats dict から数値を取得。なければ 0.0 を返す。"""
    entry = stats.get(key, {})
    v = entry.get("value")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
