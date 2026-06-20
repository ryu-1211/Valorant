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
    """プロフィール（現行シーズン）エンドポイント。"""
    encoded = quote(name, safe="")
    return f"{_BASE_URL}/{encoded}%23{tag}"


def _build_season_url(name: str, tag: str, season_id: str) -> str:
    """指定シーズンのフルスタッツを返す segments/season エンドポイント。
    profile?seasonId= は無効（常に現行シーズンを返す）ため、こちらを使う。"""
    encoded = quote(name, safe="")
    return f"{_BASE_URL}/{encoded}%23{tag}/segments/season?seasonId={season_id}"


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


def _parse_season_segment(segments: list, season_id: str | None = None) -> dict | None:
    for seg in segments:
        a = seg.get("attributes", {})
        if seg.get("type") == "season" and a.get("playlist") == "competitive":
            if season_id is None or a.get("seasonId") == season_id:
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


# ── エージェント別 ────────────────────────────────────────────

# UI で表示するエージェント別スタッツ（カウント系 + 率系）
_AGENT_STAT_KEYS = [
    "matchesPlayed", "matchesWon", "roundsPlayed", "kills", "deaths", "assists",
    "matchesWinPct", "kDRatio", "kDARatio", "scorePerRound", "headshotsPercentage",
    "damagePerRound", "kAST", "firstBloods", "firstDeaths", "aces",
    "kills2K", "kills3K", "kills4K", "kills5K",
    "clutches", "clutchesLost",
]


def _parse_agents(segments: list) -> list[dict]:
    """agent セグメントから {name, role, color, image, stats(subset), clutch} のリストを返す。"""
    out = []
    for seg in segments:
        if seg.get("type") != "agent":
            continue
        if seg.get("attributes", {}).get("playlist") not in (None, "competitive"):
            continue
        meta = seg.get("metadata", {})
        st = seg.get("stats", {})
        stats_subset = {
            k: {
                "value": st.get(k, {}).get("value"),
                "displayValue": st.get(k, {}).get("displayValue", ""),
            }
            for k in _AGENT_STAT_KEYS if k in st
        }
        clutch = _clutch_stats(st)
        out.append({
            "name": meta.get("name", "?"),
            "role": meta.get("role", ""),
            "color": meta.get("color", ""),
            "image": meta.get("imageUrl", ""),
            "stats": stats_subset,
            "clutch": clutch,
        })
    # 試合数の多い順
    out.sort(key=lambda a: a["stats"].get("matchesPlayed", {}).get("value") or 0, reverse=True)
    return out


def fetch_agents(name: str, tag: str, season_id: str | None = None) -> list[dict]:
    """エージェント別スタッツを返す。season_id 省略時は全期間（キャリア通算）。"""
    enc = quote(name, safe="")
    url = f"{_BASE_URL}/{enc}%23{tag}/segments/agent"
    if season_id:
        url += f"?seasonId={season_id}"
    data = _get(url)
    if not data:
        return []
    segs = data.get("data", [])
    if not isinstance(segs, list):
        return []
    return _parse_agents(segs)


# ── マップ別 ──────────────────────────────────────────────────

_MAP_STAT_KEYS = [
    "matchesPlayed", "matchesWon", "roundsPlayed", "kills", "deaths",
    "matchesWinPct", "roundsWinPct", "attackRoundsWinPct", "defenseRoundsWinPct",
    "kDRatio", "scorePerRound", "headshotsPercentage", "damagePerRound", "kAST",
    "firstBloods", "aces",
]


def _parse_maps(segments: list) -> list[dict]:
    """map セグメントから {name, image, stats(subset), clutch} のリストを返す。"""
    out = []
    for seg in segments:
        if seg.get("type") != "map":
            continue
        if seg.get("attributes", {}).get("playlist") not in (None, "competitive"):
            continue
        meta = seg.get("metadata", {})
        st = seg.get("stats", {})
        stats_subset = {
            k: {
                "value": st.get(k, {}).get("value"),
                "displayValue": st.get(k, {}).get("displayValue", ""),
            }
            for k in _MAP_STAT_KEYS if k in st
        }
        out.append({
            "name": meta.get("name", "?"),
            "image": meta.get("imageUrl", ""),
            "stats": stats_subset,
            "clutch": _clutch_stats(st),
        })
    out.sort(key=lambda m: m["stats"].get("matchesPlayed", {}).get("value") or 0, reverse=True)
    return out


def fetch_maps(name: str, tag: str, season_id: str | None = None) -> list[dict]:
    """マップ別スタッツを返す。season_id 省略時は全期間。"""
    enc = quote(name, safe="")
    url = f"{_BASE_URL}/{enc}%23{tag}/segments/map"
    if season_id:
        url += f"?seasonId={season_id}"
    data = _get(url)
    if not data:
        return []
    segs = data.get("data", [])
    if not isinstance(segs, list):
        return []
    return _parse_maps(segs)


# ── エージェント×マップ（組み合わせ）──────────────────────────

_COMBO_STAT_KEYS = ["matchesPlayed", "matchesWon", "matchesWinPct",
                    "scorePerRound", "kDRatio", "headshotsPercentage"]


def _parse_agent_map_combos(segments: list) -> list[dict]:
    """agent-top-map セグメント（エージェント×マップ）を返す。
    metadata.name=エージェント名 / attributes.mapKey=マップ。"""
    out = []
    for seg in segments:
        if seg.get("type") != "agent-top-map":
            continue
        a = seg.get("attributes", {})
        if a.get("playlist") not in (None, "competitive"):
            continue
        meta = seg.get("metadata", {})
        st = seg.get("stats", {})
        mapkey = a.get("mapKey", "")
        out.append({
            "agent": meta.get("name", "?"),
            "color": meta.get("color", ""),
            "mapKey": mapkey,
            "map": mapkey.capitalize() if mapkey else "?",
            "stats": {
                k: {"value": st.get(k, {}).get("value"),
                    "displayValue": st.get(k, {}).get("displayValue", "")}
                for k in _COMBO_STAT_KEYS if k in st
            },
        })
    return out


def fetch_combos(name: str, tag: str, season_id: str | None = None) -> list[dict]:
    """エージェント×マップの組み合わせ別スタッツ。/segments/agent から agent-top-map を抽出。"""
    enc = quote(name, safe="")
    url = f"{_BASE_URL}/{enc}%23{tag}/segments/agent"
    if season_id:
        url += f"?seasonId={season_id}"
    data = _get(url)
    if not data:
        return []
    segs = data.get("data", [])
    if not isinstance(segs, list):
        return []
    return _parse_agent_map_combos(segs)


# ── 公開 API ──────────────────────────────────────────────────

def get_season_list(name: str, tag: str) -> list[dict]:
    """プレイヤーの利用可能シーズン一覧を返す。各要素: {id, shortName, name}"""
    data = _get(_build_url(name, tag))
    if not data:
        return []
    return data.get("data", {}).get("metadata", {}).get("seasons", [])


def _fetch_season_stats(name: str, tag: str, season_id: str) -> dict | None:
    """segments/season エンドポイントから指定シーズンの competitive スタッツを返す。"""
    data = _get(_build_season_url(name, tag, season_id))
    if not data:
        return None
    segs = data.get("data", [])
    if not isinstance(segs, list):
        return None
    return _parse_season_segment(segs, season_id)


def fetch_stats(name: str, tag: str, season_id: str | None = None) -> dict | None:
    """指定シーズン（省略時=最新）の統計を返す。失敗時は None。"""
    # 最新シーズン取得 + シーズンリスト + ピークランクのためにまず profile を叩く
    data = _get(_build_url(name, tag))
    if not data:
        return None
    segments = data.get("data", {}).get("segments", [])
    meta_seasons = data.get("data", {}).get("metadata", {}).get("seasons", [])
    peak = _parse_peak_rank(segments)
    current_id = meta_seasons[0]["id"] if meta_seasons else None

    # 最新シーズン（または season_id 未指定）は profile の season セグメントを使う
    if season_id is None or season_id == current_id:
        season_stats = _parse_season_segment(segments)
        season_meta = meta_seasons[0] if meta_seasons else {}
    else:
        season_stats = _fetch_season_stats(name, tag, season_id)
        season_meta = next((s for s in meta_seasons if s.get("id") == season_id), {})

    if not season_stats:
        return None
    return _build_player_record(name, tag, season_stats, peak, season_meta)


def fetch_recent_seasons(name: str, tag: str, count: int = 99) -> dict | None:
    """
    利用可能な全シーズン（count 件まで）のデータをまとめて返す。
    {
      season_list: [{id, shortName, name}, ...],   ← 全利用可能シーズン
      seasons: {season_id: player_record, ...},     ← 取得したシーズン分
      current_season_id: str,
    }
    各過去シーズンは segments/season エンドポイントから個別取得する
    （profile?seasonId= は無効で常に現行シーズンを返すため）。
    """
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

    # 最新シーズンは profile から取得済み
    result["seasons"][current_id] = _build_player_record(
        name, tag, season_stats, peak, meta_seasons[0] if meta_seasons else {}
    )

    # 2番目以降のシーズンは segments/season から個別取得
    for season in meta_seasons[1:count]:
        sid = season["id"]
        time.sleep(4.0)
        extra_stats = _fetch_season_stats(name, tag, sid)
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
