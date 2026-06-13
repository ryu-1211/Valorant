STAT_MAP = {
    "acs":     ("scorePerRound",        "ACS"),
    "kd":      ("kDRatio",              "K/D"),
    "kda":     ("kDARatio",             "KDA"),
    "kast":    ("kAST",                 "KAST%"),
    "hs":      ("headshotsPercentage",  "HS%"),
    "winrate": ("matchesWinPct",        "勝率"),
    "clutch":  ("clutchesPercentage",   "Clutch%"),
    "adr":     ("damagePerRound",       "ADR"),
    "fb":      ("firstBloods",          "FB数"),
    "aces":    ("aces",                 "エース数"),
    "kills":   ("killsPerMatch",        "キル/試合"),
    "matches": ("matchesPlayed",        "試合数"),
}

RANKING_CHOICES = list(STAT_MAP.keys())

PROFILE_SECTIONS = {
    "基本": [
        ("matchesPlayed",   "試合数"),
        ("matchesWon",      "勝利"),
        ("matchesLost",     "敗北"),
        ("matchesWinPct",   "勝率"),
        ("timePlayed",      "プレイ時間"),
        ("peakRank",        "ピークランク"),
    ],
    "戦闘": [
        ("scorePerRound",       "ACS"),
        ("kDRatio",             "K/D"),
        ("kDARatio",            "KDA"),
        ("kAST",                "KAST"),
        ("damagePerRound",      "ADR"),
        ("headshotsPercentage", "HS%"),
        ("killsPerMatch",       "キル/試合"),
        ("deathsPerMatch",      "デス/試合"),
        ("assistsPerMatch",     "アシスト/試合"),
    ],
    "クラッチ": [
        ("clutchesPercentage", "Clutch%"),
        ("clutches",           "クラッチ勝利"),
        ("clutchesLost",       "クラッチ敗北"),
        ("clutches1v1",        "1v1"),
        ("clutches1v2",        "1v2"),
        ("clutches1v3",        "1v3"),
        ("clutches1v4",        "1v4"),
        ("clutches1v5",        "1v5"),
    ],
    "ハイライト": [
        ("aces",             "エース"),
        ("firstBloods",      "FB数"),
        ("firstDeaths",      "FD数"),
        ("flawless",         "フローレス"),
        ("mostKillsInMatch", "最大キル(1試合)"),
        ("kills2K",          "2K"),
        ("kills3K",          "3K"),
        ("kills4K",          "4K"),
        ("kills5K",          "5K"),
    ],
}

RANK_EMOJIS = {
    "Iron":     "🔩",
    "Bronze":   "🥉",
    "Silver":   "⚪",
    "Gold":     "🥇",
    "Platinum": "💎",
    "Diamond":  "💠",
    "Ascendant":"🟢",
    "Immortal": "🔴",
    "Radiant":  "🌟",
}

MEDAL_EMOJIS = ["🥇", "🥈", "🥉"]

CACHE_TTL_SECONDS = 1800  # 30分
