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


def seed_players(db_path, count=8, group_col="in_bracket"):
    conn = sqlite3.connect(db_path)
    conn.executemany(
        f"INSERT INTO players (id, name, {group_col}) VALUES (?, ?, 1)",
        [(i, f"P{i}") for i in range(1, count + 1)],
    )
    conn.commit()
    conn.close()


def query(db_path, sql, args=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return rows


def build_bracket(c):
    data = MultiDict([("seed", str(i)) for i in range(1, 9)])
    return c.post("/organizer/bracket/seed", data=data)


def test_bracket_result_and_undo(client):
    c, db_path = client
    seed_players(db_path)
    build_bracket(c)

    qf = query(db_path, "SELECT * FROM bracket_matches WHERE round = 1 ORDER BY position")[0]
    resp = c.post(f"/api/bracket/match/{qf['id']}/result", data={"winner_id": qf["player1_id"]})
    assert resp.status_code == 200

    # winner advanced into the semifinal slot
    sf = query(db_path, "SELECT * FROM bracket_matches WHERE id = ?", (qf["next_match_id"],))[0]
    slot_col = "player1_id" if qf["next_match_slot"] == 1 else "player2_id"
    assert sf[slot_col] == qf["player1_id"]

    # double-record is rejected
    resp = c.post(f"/api/bracket/match/{qf['id']}/result", data={"winner_id": qf["player2_id"]})
    assert resp.status_code == 400

    # undo clears the result and the advanced slot
    resp = c.post(f"/api/bracket/match/{qf['id']}/undo")
    assert resp.status_code == 200
    m = query(db_path, "SELECT * FROM bracket_matches WHERE id = ?", (qf["id"],))[0]
    assert m["winner_id"] is None
    sf = query(db_path, "SELECT * FROM bracket_matches WHERE id = ?", (qf["next_match_id"],))[0]
    assert sf[slot_col] is None


def test_bracket_undo_blocked_when_next_match_played(client):
    c, db_path = client
    seed_players(db_path)
    build_bracket(c)

    qfs = query(db_path, "SELECT * FROM bracket_matches WHERE round = 1 ORDER BY position")
    # play out QF 0 and QF 1 (both feed semifinal 0), then the semifinal
    c.post(f"/api/bracket/match/{qfs[0]['id']}/result", data={"winner_id": qfs[0]["player1_id"]})
    c.post(f"/api/bracket/match/{qfs[1]['id']}/result", data={"winner_id": qfs[1]["player1_id"]})
    sf_id = qfs[0]["next_match_id"]
    c.post(f"/api/bracket/match/{sf_id}/result", data={"winner_id": qfs[0]["player1_id"]})

    # QF result is now locked behind the played semifinal
    resp = c.post(f"/api/bracket/match/{qfs[0]['id']}/undo")
    assert resp.status_code == 400

    # undoing the semifinal first unlocks it
    resp = c.post(f"/api/bracket/match/{sf_id}/undo")
    assert resp.status_code == 200
    resp = c.post(f"/api/bracket/match/{qfs[0]['id']}/undo")
    assert resp.status_code == 200


def test_round_robin_result_and_undo(client):
    c, db_path = client
    seed_players(db_path, count=4, group_col="in_round_robin")
    c.post("/organizer/round_robin/build")

    m = query(db_path, "SELECT * FROM round_robin_matches ORDER BY id")[0]
    resp = c.post(f"/api/round_robin/match/{m['id']}/result", data={"winner_id": m["player1_id"]})
    assert resp.status_code == 200

    resp = c.post(f"/api/round_robin/match/{m['id']}/undo")
    assert resp.status_code == 200
    row = query(db_path, "SELECT * FROM round_robin_matches WHERE id = ?", (m["id"],))[0]
    assert row["winner_id"] is None


def test_phase1_results_locked_after_phase2_starts(client):
    c, db_path = client
    seed_players(db_path)
    build_bracket(c)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE tournament_state SET phase = 'phase2' WHERE id = 1")
    conn.commit()
    conn.close()

    qf = query(db_path, "SELECT * FROM bracket_matches WHERE round = 1 ORDER BY position")[0]
    resp = c.post(f"/api/bracket/match/{qf['id']}/result", data={"winner_id": qf["player1_id"]})
    assert resp.status_code == 400
    resp = c.post(f"/api/bracket/match/{qf['id']}/undo")
    assert resp.status_code == 400
