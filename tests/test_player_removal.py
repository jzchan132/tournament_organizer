import sqlite3

import pytest
from werkzeug.datastructures import MultiDict

from app import create_app
from app import db as db_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    app = create_app()
    app.testing = True
    with app.test_client() as c:
        yield c, db_path


def test_remove_unreferenced_player_works(client):
    c, db_path = client
    c.post("/organizer/players/add", data={"name": "Alex"})
    conn = sqlite3.connect(db_path)
    pid = conn.execute("SELECT id FROM players").fetchone()[0]
    conn.close()

    resp = c.post(f"/organizer/players/{pid}/remove")
    assert resp.status_code == 302
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0
    conn.close()


def test_remove_seeded_player_flashes_instead_of_crashing(client):
    c, db_path = client
    for i in range(1, 9):
        c.post("/organizer/players/add", data={"name": f"P{i}"})
    c.post("/organizer/bracket/seed", data=MultiDict([("seed", str(i)) for i in range(1, 9)]))

    resp = c.post("/organizer/players/1/remove", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Can&#39;t remove this player" in resp.data or b"Can't remove this player" in resp.data

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 8
    conn.close()
