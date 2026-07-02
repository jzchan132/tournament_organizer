import sqlite3

import pytest

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


def query(db_path, sql, args=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return rows


def setup_rr(c, db_path):
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO players (id, name, in_round_robin) VALUES (?, ?, 1)",
        [(i, f"P{i}") for i in range(1, 5)],
    )
    conn.commit()
    conn.close()
    c.post("/organizer/round_robin/build")
    return {
        (m["player1_id"], m["player2_id"]): m["id"]
        for m in query(db_path, "SELECT * FROM round_robin_matches")
    }


def record(c, match_id, winner_id):
    return c.post(f"/api/round_robin/match/{match_id}/result", data={"winner_id": winner_id})


def tiebreakers(db_path):
    return query(
        db_path, "SELECT * FROM round_robin_matches WHERE is_tiebreaker = 1 ORDER BY id"
    )


def rr_champion(db_path):
    from app.queries import round_robin_champion

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    champ = round_robin_champion(conn)
    conn.close()
    return champ


def test_two_way_tie_spawns_tiebreaker_and_resolves(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    # P1 and P2 finish 2-1; P3 and P4 finish 1-2
    record(c, m[(1, 2)], 1)
    record(c, m[(1, 3)], 1)
    record(c, m[(1, 4)], 4)
    record(c, m[(2, 3)], 2)
    record(c, m[(2, 4)], 2)
    assert tiebreakers(db_path) == []  # regular play not finished yet
    record(c, m[(3, 4)], 3)

    tbs = tiebreakers(db_path)
    assert len(tbs) == 1
    assert {tbs[0]["player1_id"], tbs[0]["player2_id"]} == {1, 2}
    assert rr_champion(db_path) is None  # tie not settled yet

    resp = record(c, tbs[0]["id"], 2)
    assert resp.status_code == 200
    assert rr_champion(db_path)["id"] == 2
    # tiebreaker win doesn't inflate the standings
    standings = query(
        db_path,
        "SELECT COUNT(*) AS wins FROM round_robin_matches "
        "WHERE winner_id = 2 AND is_tiebreaker = 0",
    )
    assert standings[0]["wins"] == 2


def test_three_way_tie_resolves_via_ladder(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    # cycle: P1 > P2 > P3 > P1, and everyone beats P4 -> three players at 2 wins
    record(c, m[(1, 2)], 1)
    record(c, m[(2, 3)], 2)
    record(c, m[(1, 3)], 3)
    record(c, m[(1, 4)], 1)
    record(c, m[(2, 4)], 2)
    record(c, m[(3, 4)], 3)

    tbs = tiebreakers(db_path)
    assert len(tbs) == 1
    first_pair = {tbs[0]["player1_id"], tbs[0]["player2_id"]}
    assert first_pair < {1, 2, 3}  # two of the three tied players

    winner1 = tbs[0]["player1_id"]
    record(c, tbs[0]["id"], winner1)

    tbs = tiebreakers(db_path)
    assert len(tbs) == 2  # ladder continues: winner vs the remaining player
    third = ({1, 2, 3} - first_pair).pop()
    assert {tbs[1]["player1_id"], tbs[1]["player2_id"]} == {winner1, third}
    assert rr_champion(db_path) is None

    record(c, tbs[1]["id"], third)
    assert rr_champion(db_path)["id"] == third


def test_undo_regular_match_discards_tiebreakers(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    record(c, m[(1, 2)], 1)
    record(c, m[(1, 3)], 1)
    record(c, m[(1, 4)], 4)
    record(c, m[(2, 3)], 2)
    record(c, m[(2, 4)], 2)
    record(c, m[(3, 4)], 3)
    assert len(tiebreakers(db_path)) == 1

    resp = c.post(f"/api/round_robin/match/{m[(3, 4)]}/undo")
    assert resp.status_code == 200
    assert tiebreakers(db_path) == []
    assert rr_champion(db_path) is None

    # replaying the final match regenerates the tiebreaker
    record(c, m[(3, 4)], 3)
    tbs = tiebreakers(db_path)
    assert len(tbs) == 1  # P1/P2 tied at 2 wins each again
    record(c, tbs[0]["id"], 1)
    assert rr_champion(db_path)["id"] == 1


def test_no_tie_means_no_tiebreaker(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    # P1 sweeps
    record(c, m[(1, 2)], 1)
    record(c, m[(1, 3)], 1)
    record(c, m[(1, 4)], 1)
    record(c, m[(2, 3)], 2)
    record(c, m[(2, 4)], 2)
    record(c, m[(3, 4)], 3)
    assert tiebreakers(db_path) == []
    assert rr_champion(db_path)["id"] == 1
