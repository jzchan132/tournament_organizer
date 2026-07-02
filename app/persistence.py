"""Save-file management and rolling autosave.

The live database already persists every change instantly (each action
commits before the response goes out), so a crash or accidental close never
loses state. On top of that this module keeps copies in data/saves/:

- autosave.db, refreshed after every state-changing request, protects
  against the live db file itself being deleted or corrupted.
- Named saves let the organizer checkpoint or switch tournaments.

All copies go through SQLite's backup API rather than file copies, so they
are safe to take while dashboard clients are polling the live db.
"""

import os
import re
import sqlite3
from datetime import datetime

from flask import request

from app import db as db_module
from app.config import get_data_dir

SAVES_DIR = os.path.join(get_data_dir(), "saves")
AUTOSAVE_NAME = "autosave.db"


def _saves_dir():
    os.makedirs(SAVES_DIR, exist_ok=True)
    return SAVES_DIR


def _backup(src_path, dst_path):
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.execute("PRAGMA busy_timeout = 3000")
        dst.execute("PRAGMA busy_timeout = 3000")
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def _timestamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _sanitize_name(name):
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", name or "").strip("-")
    return cleaned or f"save-{_timestamp()}"


def autosave():
    _backup(db_module.DB_PATH, os.path.join(_saves_dir(), AUTOSAVE_NAME))


def autosave_after_request(response):
    # Any successful POST is a state change worth snapshotting. Save-file
    # management routes are excluded so loading a save doesn't immediately
    # overwrite the autosave it might be recovering from.
    if (
        request.method == "POST"
        and response.status_code < 400
        and not request.path.startswith("/tournament/")
    ):
        try:
            autosave()
        except Exception:
            pass  # autosave is best-effort; never break the actual action
    return response


def list_saves():
    saves = []
    for filename in os.listdir(_saves_dir()):
        if not filename.endswith(".db"):
            continue
        path = os.path.join(_saves_dir(), filename)
        saves.append(
            {
                "filename": filename,
                "modified": datetime.fromtimestamp(os.path.getmtime(path)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    saves.sort(key=lambda s: s["modified"], reverse=True)
    return saves


def save_current(name):
    filename = _sanitize_name(name) + ".db"
    _backup(db_module.DB_PATH, os.path.join(_saves_dir(), filename))
    return filename


def _is_valid_save(path):
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute("SELECT phase FROM tournament_state WHERE id = 1").fetchone()
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False


def load_save(filename):
    """Replace the live tournament with a save. Returns an error string or None."""
    base = os.path.basename(filename or "")
    path = os.path.join(_saves_dir(), base)
    if not base.endswith(".db") or not os.path.isfile(path):
        return "Save file not found."
    if not _is_valid_save(path):
        return "That file isn't a valid tournament save."
    # The state being replaced is archived first so a mis-click can't lose it.
    save_current(f"replaced-{_timestamp()}")
    _backup(path, db_module.DB_PATH)
    # An older save restores its older schema wholesale; bring it current.
    db_module.init_db()
    return None


def delete_save(filename):
    """Delete a save file. Returns an error string or None."""
    base = os.path.basename(filename or "")
    path = os.path.join(_saves_dir(), base)
    if not base.endswith(".db") or not os.path.isfile(path):
        return "Save file not found."
    os.remove(path)
    return None


def new_tournament():
    """Archive the current state and reset to a blank tournament.

    Returns the archive filename.
    """
    archive_name = save_current(f"archive-{_timestamp()}")

    conn = sqlite3.connect(db_module.DB_PATH)
    try:
        conn.execute("PRAGMA busy_timeout = 3000")
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        with open(db_module.SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()
    return archive_name
