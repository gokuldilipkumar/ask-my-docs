import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS daily_cost (
    day TEXT PRIMARY KEY,
    total_usd REAL NOT NULL
)
"""


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_CREATE_TABLE)
    return conn


def record_cost(db_path: Path, cost_usd: float, day: str | None = None) -> float:
    day = day or _today()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT total_usd FROM daily_cost WHERE day = ?", (day,)).fetchone()
        new_total = (row[0] if row else 0.0) + cost_usd
        conn.execute(
            "INSERT OR REPLACE INTO daily_cost (day, total_usd) VALUES (?, ?)", (day, new_total)
        )
    return new_total


def get_daily_total(db_path: Path, day: str | None = None) -> float:
    day = day or _today()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT total_usd FROM daily_cost WHERE day = ?", (day,)).fetchone()
    return row[0] if row else 0.0


def check_budget(db_path: Path, cap_usd: float, day: str | None = None) -> bool:
    """True once today's running total exceeds cap_usd. Caller decides what to do (warn, never block)."""
    return get_daily_total(db_path, day) > cap_usd
