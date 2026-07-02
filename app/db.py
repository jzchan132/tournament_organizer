import sqlite3

from flask import g

from app.config import DB_PATH, SCHEMA_PATH


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    """Bring databases created by older versions up to the current schema.

    CREATE TABLE IF NOT EXISTS doesn't add new columns to existing tables,
    and loading an old save file restores its old schema wholesale.
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(round_robin_matches)")]
    if "is_tiebreaker" not in cols:
        conn.execute(
            "ALTER TABLE round_robin_matches "
            "ADD COLUMN is_tiebreaker INTEGER NOT NULL DEFAULT 0"
        )


def register(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
