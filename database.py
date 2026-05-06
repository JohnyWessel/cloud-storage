import sqlite3
import hashlib
import os
from pathlib import Path

# Import here to avoid circular imports — settings loaded first
_DB_PATH: str | None = None


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        from settings import DB_PATH
        _DB_PATH = DB_PATH
    return _DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_db() -> None:
    """Create tables and seed default users if they don't exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    conn.commit()

    # Seed two hard-coded accounts (idempotent)
    default_users = [
        ("admin", "admin123"),
        ("user",  "user123"),
    ]
    for username, password in default_users:
        pw_hash = _hash_password(password)
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, pw_hash),
            )
        except sqlite3.IntegrityError:
            pass  # already exists

    conn.commit()
    conn.close()


def authenticate(username: str, password: str) -> bool:
    """Return True if credentials are valid."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if row is None:
        return False
    return row["password_hash"] == _hash_password(password)
