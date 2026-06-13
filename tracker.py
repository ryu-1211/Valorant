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


def _build_url(name: str, tag: str, season_id: str | None = None) -> str:
    encoded = quote(name, safe="")
    url = f"{_BASE_URL}/{encoded}%23{tag}"
    if season_id:
        url += f"?seasonId={season_id}"
    return url


def _get(url: str, retry: int = 2) -> dict | None:
    for attempt in range(retry + 1):
        try:
            r = cffi_requests.get(url, headers=_HEADERS, impersonate="chrome124", timeout=20)
            if r.status_code == 429:
                print("[tracker] レート制限 — 60秒待機")
                time.sleep(60)
                continue
            if r.status_code != 200:
                print(f"[tracker] HTTP {r.status_code}: {url}")
                return None
            return r.json()
        except Exception as e:
            print(f"[tracker] リクエスト失敗 attempt={attempt}: {e}")
            if attempt < retry:
                time.sleep(3)
    return None


def _parse_season_segment(segments: list) -> dict | None:
    for seg in segments:
        if (seg.get("type") == "season"
                and seg.get("attributes", {}).get("playlist") == "competitive"):
            return seg.get("stats", {})
    return None


def _parse_peak_rank(segments: list) -> str:
    for seg in segments:
        if (seg.get("type") == "peak-rating"
                and seg.get("attributes", {}).get("playlist") == "competitive"):
            return (
                seg.get("stats", {})
                   .get("peakRating", {})
                   .get("displayValue", "不明")
            )
    return "不明"


def _clutch_stats(stats: dict) -> dict:
    wins    = int(stats.get("clutches",     {}).get("value", 0) or 0)
    losses  = int(stats.get("clutchesLost", {}).get("value", 0) or 0)
    attempts = wins + losses
    rate = round(wins / attempts * 100, 1) if attempts > 0 else 0.0

    breakdown = {}
    for n in range(1, 6):
        w = int(stats.get(f"clutches1v{n}",     {}).get("value", 0) or 0)
        l = int(stats.get(f"clutchesLost1v{n}", {}).get("value", 0) or 0)
        a = w + l
        breakdown[f"1v{n}"] = {
            "wins": w, "losses": l, "attempts": a,
            "rate": round(w / a * 100, 1) if a > 0 else 0.0,
        }
    return {
        "success_rate": rate,
        "wins": wins,
        "losses": losses,
        "attempts": attempts,
        "breakdown": breakdown,
    }


def _build_player_record(name: str, tag: str, stats: dict, peak: str,
                          season_meta: dict | None = None) -> dict:
    clutch = _clutch_stats(stats)
    return {
        "name": name,
        "tag": tag,
        "peak_rank": peak,
        "clutch": clutch,
        # 後方互換
        "clutch_success_rate": clutch["success_rate"],
        "clutch_wins": clutch["wins"],
        "clutch_attempts": clutch["attempts"],
        "season": season_meta or {},
        "stats": stats,
    }


# ── 公開 API ──────────────────────────────────────────────────

def get_season_list(name: str, tag: str) -> list[dict]:
    """プレイヤーの利用可能シーズン一覧を返す。各要素: {id, shortName, name}"""
    data = _get(_build_url(name, tag))
    if not data:
        return []
    return data.get("data", {}).get("metadata", {}).get("seasons", [])


def fetch_stats(name: str, tag: str, season_id: str | None = None) -> dict | None:
    """指定シーズン（省略時=最新）の統計を返す。失敗時は None。"""
    data = _get(_build_url(name, tag, season_id))
    if not data:
        return None

    segments = data.get("data", {}).get("segments", [])
    meta_seasons = data.get("data", {}).get("metadata", {}).get("seasons", [])

    season_stats = _parse_season_segment(segments)
    if not season_stats:
        return None

    peak = _parse_peak_rank(segments)

    # シーズンメタ（名称など）
    season_meta: dict = {}
    if season_id:
        for s in meta_seasons:
            if s.get("id") == season_id:
                season_meta = s
                break
    elif meta_seasons:
        season_meta = meta_seasons[0]  # デフォルト=最新

    return _build_player_record(name, tag, season_stats, peak, season_meta)


def fetch_recent_seasons(name: str, tag: str, count: int = 3) -> dict | None:
    """
    最新 count 件のシーズンデータをまとめて返す。
    {
      season_list: [{id, shortName, name}, ...],   ← 全利用可能シーズン
      seasons: {season_id: player_record, ...},     ← 取得したシーズン分
      current_season_id: str,
    }
    """
    # まず最新シーズンを取得してシーズンリストも得る
    data = _get(_build_url(name, tag))
    if not data:
        return None

    segments = data.get("data", {}).get("segments", [])
    meta_seasons = data.get("data", {}).get("metadata", {}).get("seasons", [])

    season_stats = _parse_season_segment(segments)
    if not season_stats:
        return None

    peak = _parse_peak_rank(segments)
    current_id = meta_seasons[0]["id"] if meta_seasons else "current"

    result = {
        "season_list": meta_seasons,
        "current_season_id": current_id,
        "seasons": {},
    }

    # 最新シーズンを登録
    result["seasons"][current_id] = _build_player_record(
        name, tag, season_stats, peak, meta_seasons[0] if meta_seasons else {}
    )

    # 2番目以降のシーズンを取得
    for season in meta_seasons[1:count]:
        sid = season["id"]
        time.sleep(1.5)
        extra = _get(_build_url(name, tag, sid))
        if not extra:
            continue
        extra_segs = extra.get("data", {}).get("segments", [])
        extra_stats = _parse_season_segment(extra_segs)
        if not extra_stats:
            continue
        result["seasons"][sid] = _build_player_record(
            name, tag, extra_stats, peak, season
        )

    return result


# ── ヘルパー ──────────────────────────────────────────────────

def get_display(stats: dict, key: str) -> str:
    entry = stats.get(key, {})
    return entry.get("displayValue") or str(entry.get("value", "-"))


def get_value(stats: dict, key: str) -> float:
    entry = stats.get(key, {})
    v = entry.get("value")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
