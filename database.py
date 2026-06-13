import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "valorant.db"


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS players (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT    NOT NULL,
                tag     TEXT    NOT NULL,
                UNIQUE(name, tag)
            );
            CREATE TABLE IF NOT EXISTS cache (
                player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                season_id   TEXT    NOT NULL DEFAULT 'current',
                data        TEXT    NOT NULL,
                updated_at  INTEGER NOT NULL,
                PRIMARY KEY (player_id, season_id)
            );
        """)
        # マイグレーション: 旧スキーマに season_id カラムがない場合は再作成
        cols = [r[1] for r in con.execute("PRAGMA table_info(cache)").fetchall()]
        if "season_id" not in cols:
            con.executescript("""
                ALTER TABLE cache RENAME TO cache_old;
                CREATE TABLE cache (
                    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                    season_id   TEXT    NOT NULL DEFAULT 'current',
                    data        TEXT    NOT NULL,
                    updated_at  INTEGER NOT NULL,
                    PRIMARY KEY (player_id, season_id)
                );
                INSERT INTO cache (player_id, season_id, data, updated_at)
                SELECT player_id, 'current', data, updated_at FROM cache_old;
                DROP TABLE cache_old;
            """)


# ── プレイヤー管理 ────────────────────────────────────────────

def add_player(name: str, tag: str) -> bool:
    with _conn() as con:
        try:
            con.execute("INSERT INTO players (name, tag) VALUES (?, ?)", (name, tag))
            return True
        except sqlite3.IntegrityError:
            return False


def remove_player(name: str, tag: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM players WHERE name=? AND tag=?", (name, tag))
        return cur.rowcount > 0


def list_players() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT name, tag FROM players ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_player_id(name: str, tag: str) -> int | None:
    with _conn() as con:
        row = con.execute(
            "SELECT id FROM players WHERE name=? AND tag=?", (name, tag)
        ).fetchone()
    return row["id"] if row else None


# ── キャッシュ管理 ────────────────────────────────────────────

def save_cache(player_id: int, data: dict, season_id: str = "current") -> None:
    payload = json.dumps(data, ensure_ascii=False)
    with _conn() as con:
        con.execute(
            """
            INSERT INTO cache (player_id, season_id, data, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id, season_id) DO UPDATE
            SET data=excluded.data, updated_at=excluded.updated_at
            """,
            (player_id, season_id, payload, int(time.time())),
        )


def load_cache(player_id: int, ttl: int, season_id: str = "current") -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT data, updated_at FROM cache WHERE player_id=? AND season_id=?",
            (player_id, season_id),
        ).fetchone()
    if not row:
        return None
    if time.time() - row["updated_at"] > ttl:
        return None
    return json.loads(row["data"])


def load_cache_force(player_id: int, season_id: str = "current") -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT data FROM cache WHERE player_id=? AND season_id=?",
            (player_id, season_id),
        ).fetchone()
    return json.loads(row["data"]) if row else None


def load_all_cached_seasons(player_id: int) -> dict[str, dict]:
    """プレイヤーの全シーズンキャッシュを {season_id: data} で返す。"""
    with _conn() as con:
        rows = con.execute(
            "SELECT season_id, data FROM cache WHERE player_id=?", (player_id,)
        ).fetchall()
    return {r["season_id"]: json.loads(r["data"]) for r in rows}
