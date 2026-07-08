import sqlite3

import pytest

from app import create_app
from app import db as db_module

BIG, SMALL, CHALLENGER, OTHER = 1, 2, 3, 4


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    app = create_app()
    app.testing = True
    with app.test_client() as c:
        yield c, db_path


def seed(db_path, big_king_id=BIG, small_king_id=SMALL, consecutive_bk_wins=0):
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO players (id, name) VALUES (?, ?)",
        [(BIG, "BigKing"), (SMALL, "SmallKing"), (CHALLENGER, "Challenger"), (OTHER, "Other")],
    )
    conn.execute(
        "UPDATE tournament_state SET phase='phase2', big_king_id=?, small_king_id=?, "
        "consecutive_bk_wins=? WHERE id=1",
        (big_king_id, small_king_id, consecutive_bk_wins),
    )
    conn.commit()
    conn.close()


def add_queue_entry(db_path, player_id, entry_type, position=0):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO challenge_queue (position, player_id, entry_type) VALUES (?, ?, ?)",
        (position, player_id, entry_type),
    )
    conn.commit()
    conn.close()


def get_state(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tournament_state WHERE id=1").fetchone()
    conn.close()
    return dict(row)


def get_queue(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM challenge_queue ORDER BY position").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def has_history(db_path, challenger_id, small_king_id):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT 1 FROM challenger_history WHERE challenger_id=? AND small_king_id=?",
        (challenger_id, small_king_id),
    ).fetchone()
    conn.close()
    return row is not None


def add_history(db_path, challenger_id, small_king_id):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO challenger_history (challenger_id, small_king_id) VALUES (?, ?)",
        (challenger_id, small_king_id),
    )
    conn.commit()
    conn.close()


def test_challenger_takeover_queues_champ_challenges_top_and_bottom(client):
    c, db_path = client
    seed(db_path)
    add_queue_entry(db_path, CHALLENGER, "challenger")
    add_queue_entry(db_path, OTHER, "challenger", position=1)

    resp = c.post("/api/phase2/result", data={"winner_id": CHALLENGER})
    assert resp.status_code == 200

    state = get_state(db_path)
    assert state["small_king_id"] == CHALLENGER
    assert state["big_king_id"] == BIG
    assert has_history(db_path, CHALLENGER, SMALL)
    # champ challenges bracket the queue; the waiting challenger sits between
    queue = get_queue(db_path)
    assert [q["entry_type"] for q in queue] == ["rematch", "challenger", "rematch"]
    assert queue[1]["player_id"] == OTHER


def test_purge_is_deferred_until_champ_challenge_resolves(client):
    c, db_path = client
    seed(db_path)
    # OTHER already used their one shot against CHALLENGER in a past reign
    add_history(db_path, OTHER, CHALLENGER)
    add_queue_entry(db_path, CHALLENGER, "challenger")
    add_queue_entry(db_path, OTHER, "challenger", position=1)

    # CHALLENGER takes the Little Champ title -- OTHER must NOT be purged yet,
    # because the champ challenge could swap the titles again
    c.post("/api/phase2/result", data={"winner_id": CHALLENGER})
    queue = get_queue(db_path)
    assert [q["entry_type"] for q in queue] == ["rematch", "challenger", "rematch"]

    # Big Champ defends the champ challenge -> CHALLENGER stays Little Champ,
    # and NOW invalid challengers are voided
    resp = c.post("/api/phase2/result", data={"winner_id": BIG})
    assert resp.status_code == 200
    queue = get_queue(db_path)
    assert [q["entry_type"] for q in queue] == ["rematch"]  # OTHER voided
    assert get_state(db_path)["consecutive_bk_wins"] == 1


def test_purge_after_swap_targets_the_new_little_champ(client):
    c, db_path = client
    seed(db_path)
    # OTHER already challenged BIG back when BIG previously held Little Champ
    add_history(db_path, OTHER, BIG)
    add_queue_entry(db_path, SMALL, "rematch")
    add_queue_entry(db_path, OTHER, "challenger", position=1)

    # Little Champ wins the champ challenge: titles swap, BIG is now Little
    # Champ -- OTHER already had their shot at BIG, so they're voided
    resp = c.post("/api/phase2/result", data={"winner_id": SMALL})
    assert resp.status_code == 200

    state = get_state(db_path)
    assert state["big_king_id"] == SMALL
    assert state["small_king_id"] == BIG
    assert state["consecutive_bk_wins"] == 0
    # a champ swap queues a fresh champ challenge at the bottom
    queue = get_queue(db_path)
    assert [q["entry_type"] for q in queue] == ["rematch"]
    # champ challenges never record history
    assert not has_history(db_path, SMALL, BIG)
    assert not has_history(db_path, BIG, SMALL)


def test_no_auto_requeue_and_double_defense_ends_tournament(client):
    c, db_path = client
    seed(db_path, consecutive_bk_wins=0)
    # the auto-queued pair from a takeover: champ challenge at top and bottom
    add_queue_entry(db_path, SMALL, "rematch", position=0)
    add_queue_entry(db_path, SMALL, "rematch", position=1)

    resp = c.post("/api/phase2/result", data={"winner_id": BIG})
    assert resp.status_code == 200
    state = get_state(db_path)
    assert state["consecutive_bk_wins"] == 1
    assert state["queue_empty_warning"] == 1  # no challengers left -- next win ends it
    assert state["phase"] == "phase2"
    assert [q["entry_type"] for q in get_queue(db_path)] == ["rematch"]  # no requeue

    resp = c.post("/api/phase2/result", data={"winner_id": BIG})
    assert resp.status_code == 200
    state = get_state(db_path)
    assert state["consecutive_bk_wins"] == 2
    assert state["phase"] == "complete"
    assert state["ended_reason"] == "queue_exhausted"
    assert get_queue(db_path) == []


def test_rejects_invalid_winner(client):
    c, db_path = client
    seed(db_path)
    add_queue_entry(db_path, CHALLENGER, "challenger")

    resp = c.post("/api/phase2/result", data={"winner_id": OTHER})
    assert resp.status_code == 400

    # nothing changed -- the queue entry is still there, untouched
    queue = get_queue(db_path)
    assert len(queue) == 1
    assert queue[0]["player_id"] == CHALLENGER


def test_undo_restores_previous_phase2_state(client):
    c, db_path = client
    seed(db_path)
    add_queue_entry(db_path, CHALLENGER, "challenger")

    resp = c.post("/api/phase2/result", data={"winner_id": CHALLENGER})
    assert resp.status_code == 200
    assert get_state(db_path)["small_king_id"] == CHALLENGER

    resp = c.post("/api/phase2/undo")
    assert resp.status_code == 200

    state = get_state(db_path)
    assert state["small_king_id"] == SMALL
    assert state["big_king_id"] == BIG
    # queue entry restored, history wiped, match log empty again
    queue = get_queue(db_path)
    assert len(queue) == 1
    assert queue[0]["player_id"] == CHALLENGER
    assert not has_history(db_path, CHALLENGER, SMALL)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM phase2_matches").fetchone()[0] == 0
    conn.close()

    # only one level of undo -- a second undo is rejected
    resp = c.post("/api/phase2/undo")
    assert resp.status_code == 400


def test_undo_reverts_tournament_completion(client):
    c, db_path = client
    seed(db_path, consecutive_bk_wins=1)
    add_queue_entry(db_path, SMALL, "rematch")

    resp = c.post("/api/phase2/result", data={"winner_id": BIG})
    assert resp.status_code == 200
    assert get_state(db_path)["phase"] == "complete"

    resp = c.post("/api/phase2/undo")
    assert resp.status_code == 200
    state = get_state(db_path)
    assert state["phase"] == "phase2"
    assert state["consecutive_bk_wins"] == 1
