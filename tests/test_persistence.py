import os
import sqlite3

import pytest

from app import create_app
from app import db as db_module
from app import persistence


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(persistence, "SAVES_DIR", str(tmp_path / "saves"))
    app = create_app()
    app.testing = True
    with app.test_client() as c:
        yield c, db_path


def player_names(db_path):
    conn = sqlite3.connect(db_path)
    names = [r[0] for r in conn.execute("SELECT name FROM players ORDER BY name")]
    conn.close()
    return names


def test_autosave_written_after_state_change(client):
    c, db_path = client
    c.post("/organizer/players/add", data={"name": "Alex"})

    autosave_path = os.path.join(persistence.SAVES_DIR, "autosave.db")
    assert os.path.isfile(autosave_path)
    assert player_names(autosave_path) == ["Alex"]


def test_save_and_load_roundtrip(client):
    c, db_path = client
    c.post("/organizer/players/add", data={"name": "Alex"})
    resp = c.post("/tournament/save", data={"name": "checkpoint"})
    assert resp.status_code == 302

    c.post("/organizer/players/add", data={"name": "Bailey"})
    assert player_names(db_path) == ["Alex", "Bailey"]

    resp = c.post("/tournament/load", data={"filename": "checkpoint.db"})
    assert resp.status_code == 302
    assert player_names(db_path) == ["Alex"]

    # the pre-load state was archived, not lost
    replaced = [f for f in os.listdir(persistence.SAVES_DIR) if f.startswith("replaced-")]
    assert len(replaced) == 1
    assert player_names(os.path.join(persistence.SAVES_DIR, replaced[0])) == ["Alex", "Bailey"]


def test_load_rejects_bad_filenames(client):
    c, db_path = client
    resp = c.post("/tournament/load", data={"filename": "nope.db"}, follow_redirects=True)
    assert b"not found" in resp.data

    # path traversal is neutralized to a basename lookup
    resp = c.post(
        "/tournament/load", data={"filename": "..\\..\\evil.db"}, follow_redirects=True
    )
    assert b"not found" in resp.data


def test_delete_save(client):
    c, db_path = client
    c.post("/organizer/players/add", data={"name": "Alex"})
    c.post("/tournament/save", data={"name": "doomed"})
    assert os.path.isfile(os.path.join(persistence.SAVES_DIR, "doomed.db"))

    resp = c.post("/tournament/delete", data={"filename": "doomed.db"})
    assert resp.status_code == 302
    assert not os.path.isfile(os.path.join(persistence.SAVES_DIR, "doomed.db"))

    resp = c.post("/tournament/delete", data={"filename": "doomed.db"}, follow_redirects=True)
    assert b"not found" in resp.data


def test_new_tournament_resets_and_archives(client):
    c, db_path = client
    c.post("/organizer/players/add", data={"name": "Alex"})

    resp = c.post("/tournament/new")
    assert resp.status_code == 302
    assert player_names(db_path) == []

    conn = sqlite3.connect(db_path)
    phase = conn.execute("SELECT phase FROM tournament_state WHERE id = 1").fetchone()[0]
    conn.close()
    assert phase == "setup"

    archives = [f for f in os.listdir(persistence.SAVES_DIR) if f.startswith("archive-")]
    assert len(archives) == 1
    assert player_names(os.path.join(persistence.SAVES_DIR, archives[0])) == ["Alex"]
