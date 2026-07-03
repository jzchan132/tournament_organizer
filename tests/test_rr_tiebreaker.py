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


def wins(db_path, player_id):
    return query(
        db_path,
        "SELECT COUNT(*) AS w FROM round_robin_matches WHERE winner_id = ?",
        (player_id,),
    )[0]["w"]


def play_two_way_tie(c, m):
    # P1 and P2 finish 2-1; P3 and P4 finish 1-2
    record(c, m[(1, 2)], 1)
    record(c, m[(1, 3)], 1)
    record(c, m[(1, 4)], 4)
    record(c, m[(2, 3)], 2)
    record(c, m[(2, 4)], 2)
    record(c, m[(3, 4)], 3)


def test_two_way_tie_spawns_tiebreaker_and_resolves(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    play_two_way_tie(c, m)

    tbs = tiebreakers(db_path)
    assert len(tbs) == 1
    assert {tbs[0]["player1_id"], tbs[0]["player2_id"]} == {1, 2}
    assert rr_champion(db_path) is None  # tie not settled yet

    resp = record(c, tbs[0]["id"], 2)
    assert resp.status_code == 200
    assert rr_champion(db_path)["id"] == 2
    # the tiebreaker win counts: P2 now leads the standings outright at 3
    assert wins(db_path, 2) == 3
    assert wins(db_path, 1) == 2


def play_three_way_cycle(c, m):
    # cycle: P1 > P2 > P3 > P1, and everyone beats P4 -> three players at 2 wins
    record(c, m[(1, 2)], 1)
    record(c, m[(2, 3)], 2)
    record(c, m[(1, 3)], 3)
    record(c, m[(1, 4)], 1)
    record(c, m[(2, 4)], 2)
    record(c, m[(3, 4)], 3)


def test_three_way_tie_generates_full_round(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    play_three_way_cycle(c, m)

    tbs = tiebreakers(db_path)
    assert len(tbs) == 3  # every tied pair plays
    pairs = {frozenset((tb["player1_id"], tb["player2_id"])) for tb in tbs}
    assert pairs == {frozenset((1, 2)), frozenset((1, 3)), frozenset((2, 3))}
    assert rr_champion(db_path) is None

    # decisive round: P1 sweeps, P2 takes the other
    by_pair = {frozenset((tb["player1_id"], tb["player2_id"])): tb["id"] for tb in tbs}
    assert record(c, by_pair[frozenset((1, 2))], 1).status_code == 200
    assert record(c, by_pair[frozenset((1, 3))], 1).status_code == 200
    assert rr_champion(db_path) is None  # round not finished yet
    assert record(c, by_pair[frozenset((2, 3))], 2).status_code == 200

    assert rr_champion(db_path)["id"] == 1
    assert wins(db_path, 1) == 4  # 2 regular + 2 tiebreaker


def test_tied_tiebreaker_round_generates_another_round(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    play_three_way_cycle(c, m)

    # tiebreaker round ALSO ends in a cycle: 1>2, 2>3, 3>1 -> tied again at 3
    tbs = tiebreakers(db_path)
    by_pair = {frozenset((tb["player1_id"], tb["player2_id"])): tb["id"] for tb in tbs}
    record(c, by_pair[frozenset((1, 2))], 1)
    record(c, by_pair[frozenset((2, 3))], 2)
    record(c, by_pair[frozenset((1, 3))], 3)

    assert rr_champion(db_path) is None
    tbs = tiebreakers(db_path)
    assert len(tbs) == 6  # a second full round was generated

    # second round is decisive
    new_round = tbs[3:]
    by_pair = {frozenset((tb["player1_id"], tb["player2_id"])): tb["id"] for tb in new_round}
    record(c, by_pair[frozenset((1, 2))], 1)
    record(c, by_pair[frozenset((1, 3))], 1)
    record(c, by_pair[frozenset((2, 3))], 2)

    assert rr_champion(db_path)["id"] == 1
    assert wins(db_path, 1) == 5  # 2 regular + 1 first round + 2 second round


def test_undo_regular_match_discards_tiebreakers(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    play_two_way_tie(c, m)
    assert len(tiebreakers(db_path)) == 1

    resp = c.post(f"/api/round_robin/match/{m[(3, 4)]}/undo")
    assert resp.status_code == 200
    assert tiebreakers(db_path) == []
    assert rr_champion(db_path) is None

    # replaying the final match regenerates the tiebreaker
    record(c, m[(3, 4)], 3)
    tbs = tiebreakers(db_path)
    assert len(tbs) == 1
    record(c, tbs[0]["id"], 1)
    assert rr_champion(db_path)["id"] == 1


def test_undo_tiebreaker_result_allows_replay(client):
    c, db_path = client
    m = setup_rr(c, db_path)
    play_two_way_tie(c, m)
    tb = tiebreakers(db_path)[0]
    record(c, tb["id"], 1)
    assert rr_champion(db_path)["id"] == 1

    resp = c.post(f"/api/round_robin/match/{tb['id']}/undo")
    assert resp.status_code == 200
    assert rr_champion(db_path) is None
    assert len(tiebreakers(db_path)) == 1  # same match, back to undecided

    record(c, tb["id"], 2)
    assert rr_champion(db_path)["id"] == 2


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
