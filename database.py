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
                player_id   INTEGER PRIMARY KEY REFERENCES players(id),
                data        TEXT    NOT NULL,
                updated_at  INTEGER NOT NULL
            );
        """)


# ── プレイヤー管理 ────────────────────────────────────────────


def add_player(name: str, tag: str) -> bool:
    """登録済みなら False、新規追加なら True を返す。"""
    with _conn() as con:
        try:
            con.execute(
                "INSERT INTO players (name, tag) VALUES (?, ?)", (name, tag)
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_player(name: str, tag: str) -> bool:
    """削除できたら True、存在しなければ False を返す。"""
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM players WHERE name=? AND tag=?", (name, tag)
        )
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


def save_cache(player_id: int, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    with _conn() as con:
        con.execute(
            """
            INSERT INTO cache (player_id, data, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE
            SET data=excluded.data, updated_at=excluded.updated_at
            """,
            (player_id, payload, int(time.time())),
        )


def load_cache(player_id: int, ttl: int) -> dict | None:
    """TTL 秒以内のキャッシュがあれば返す。なければ None。"""
    with _conn() as con:
        row = con.execute(
            "SELECT data, updated_at FROM cache WHERE player_id=?", (player_id,)
        ).fetchone()
    if not row:
        return None
    if time.time() - row["updated_at"] > ttl:
        return None
    return json.loads(row["data"])


def load_cache_force(player_id: int) -> dict | None:
    """TTL に関わらずキャッシュを返す（失敗時フォールバック用）。"""
    with _conn() as con:
        row = con.execute(
            "SELECT data FROM cache WHERE player_id=?", (player_id,)
        ).fetchone()
    return json.loads(row["data"]) if row else None
