import sqlite3
from itertools import combinations

import pytest
from werkzeug.datastructures import MultiDict

from app import create_app
from app import db as db_module
from app.queries import round_robin_schedule


# --- round robin scheduling (pure) ---


@pytest.mark.parametrize("count", [3, 4, 5, 6])
def test_schedule_covers_all_pairs_exactly_once(count):
    ids = list(range(1, count + 1))
    schedule = round_robin_schedule(ids)
    assert len(schedule) == count * (count - 1) // 2
    assert {frozenset(p) for p in schedule} == {
        frozenset(p) for p in combinations(ids, 2)
    }


@pytest.mark.parametrize("count", [3, 4, 5, 6])
def test_nobody_plays_three_matches_in_a_row(count):
    schedule = round_robin_schedule(list(range(1, count + 1)))
    for i in range(len(schedule) - 2):
        window = set(schedule[i]) & set(schedule[i + 1]) & set(schedule[i + 2])
        assert not window, f"player(s) {window} appear in three consecutive matches at {i}"


def test_four_player_schedule_never_repeats_within_a_round():
    # rounds of disjoint pairs: matches 0-1, 2-3, 4-5 share no players
    schedule = round_robin_schedule([1, 2, 3, 4])
    for a, b in ((0, 1), (2, 3), (4, 5)):
        assert not set(schedule[a]) & set(schedule[b])


# --- reset buttons + queue insertion (routes) ---


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


def execute(db_path, sql, args=()):
    conn = sqlite3.connect(db_path)
    conn.execute(sql, args)
    conn.commit()
    conn.close()


def test_reset_clears_matches_but_keeps_players(client):
    c, db_path = client
    for i in range(1, 9):
        c.post("/organizer/players/add", data={"name": f"P{i}", "group": "bracket"})
    c.post("/organizer/bracket/seed", data=MultiDict([("seed", str(i)) for i in range(1, 9)]))
    for i in range(9, 13):
        c.post("/organizer/players/add", data={"name": f"P{i}", "group": "round_robin"})
    c.post("/organizer/round_robin/build")

    assert query(db_path, "SELECT COUNT(*) AS c FROM bracket_matches")[0]["c"] == 7
    assert query(db_path, "SELECT COUNT(*) AS c FROM round_robin_matches")[0]["c"] == 6

    c.post("/organizer/bracket/reset")
    c.post("/organizer/round_robin/reset")

    assert query(db_path, "SELECT COUNT(*) AS c FROM bracket_matches")[0]["c"] == 0
    assert query(db_path, "SELECT COUNT(*) AS c FROM round_robin_matches")[0]["c"] == 0
    assert query(db_path, "SELECT COUNT(*) AS c FROM players")[0]["c"] == 12


def test_reset_blocked_once_gauntlet_started(client):
    c, db_path = client
    for i in range(1, 9):
        c.post("/organizer/players/add", data={"name": f"P{i}", "group": "bracket"})
    c.post("/organizer/bracket/seed", data=MultiDict([("seed", str(i)) for i in range(1, 9)]))
    execute(db_path, "UPDATE tournament_state SET phase = 'phase2' WHERE id = 1")

    resp = c.post("/organizer/bracket/reset", follow_redirects=True)
    assert b"locked" in resp.data
    assert query(db_path, "SELECT COUNT(*) AS c FROM bracket_matches")[0]["c"] == 7


def seed_gauntlet(db_path, big=1, small=2, extras=(3, 4, 5)):
    conn = sqlite3.connect(db_path)
    for pid in {big, small, *extras}:
        conn.execute("INSERT INTO players (id, name) VALUES (?, ?)", (pid, f"P{pid}"))
    conn.execute(
        "UPDATE tournament_state SET phase = 'phase2', big_king_id = ?, small_king_id = ?, "
        "phase2_started_at = datetime('now') WHERE id = 1",
        (big, small),
    )
    conn.commit()
    conn.close()


def test_challenger_joins_above_bottom_champ_challenge(client):
    c, db_path = client
    seed_gauntlet(db_path)
    execute(
        db_path,
        "INSERT INTO challenge_queue (position, player_id, entry_type) VALUES (0, 2, 'rematch')",
    )
    execute(
        db_path,
        "INSERT INTO challenge_queue (position, player_id, entry_type) VALUES (1, 2, 'rematch')",
    )

    assert c.post("/api/queue/join", data={"player_id": 3}).status_code == 200
    queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")
    assert [q["entry_type"] for q in queue] == ["rematch", "challenger", "rematch"]

    # a second challenger also stays above the bottom champ challenge
    assert c.post("/api/queue/join", data={"player_id": 4}).status_code == 200
    queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")
    assert [q["entry_type"] for q in queue] == [
        "rematch", "challenger", "challenger", "rematch",
    ]
    assert [q["player_id"] for q in queue[1:3]] == [3, 4]


def seed_champ_challenge_pair(db_path):
    execute(
        db_path,
        "INSERT INTO challenge_queue (position, player_id, entry_type) VALUES (0, 2, 'rematch')",
    )
    execute(
        db_path,
        "INSERT INTO challenge_queue (position, player_id, entry_type) VALUES (1, 2, 'rematch')",
    )


def test_big_champ_wins_both_challenges_after_rotation_ends_tournament(client):
    c, db_path = client
    seed_gauntlet(db_path)
    seed_champ_challenge_pair(db_path)
    c.post("/api/queue/join", data={"player_id": 3})

    # Big Champ defends the top challenge; P3 sits above the bottom one
    c.post("/api/phase2/result", data={"winner_id": 1})
    # P3 TAKES the Little Champ title -- a rotation: fresh pair queued
    c.post("/api/phase2/result", data={"winner_id": 3})
    queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")
    assert [q["entry_type"] for q in queue] == ["rematch", "rematch"]

    # Big Champ wins BOTH champ challenges of the new pair -> tournament over
    c.post("/api/phase2/result", data={"winner_id": 1})
    state = query(db_path, "SELECT * FROM tournament_state")[0]
    assert state["phase"] == "phase2"  # one challenge still pending
    assert state["queue_empty_warning"] == 1
    c.post("/api/phase2/result", data={"winner_id": 1})
    state = query(db_path, "SELECT * FROM tournament_state")[0]
    assert state["phase"] == "complete"
    assert state["ended_reason"] == "queue_exhausted"


def test_big_champ_wins_the_post_swap_challenge_ends_tournament(client):
    c, db_path = client
    seed_gauntlet(db_path)
    seed_champ_challenge_pair(db_path)

    # Little Champ WINS the top champ challenge: champ swap. The pair is
    # replaced by a single champ challenge at the bottom.
    c.post("/api/phase2/result", data={"winner_id": 2})
    state = query(db_path, "SELECT * FROM tournament_state")[0]
    assert state["big_king_id"] == 2
    assert state["small_king_id"] == 1
    queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")
    assert [q["entry_type"] for q in queue] == ["rematch"]
    assert state["queue_empty_warning"] == 1  # single pending challenge

    # the new Big Champ wins that champ challenge -> all challenges beaten
    c.post("/api/phase2/result", data={"winner_id": 2})
    state = query(db_path, "SELECT * FROM tournament_state")[0]
    assert state["phase"] == "complete"
    assert state["ended_reason"] == "queue_exhausted"


def test_defended_challenger_matches_do_not_affect_the_win_condition(client):
    c, db_path = client
    seed_gauntlet(db_path)
    seed_champ_challenge_pair(db_path)

    c.post("/api/phase2/result", data={"winner_id": 1})  # defense 1 of 2
    # challengers join and are defended -- the pending challenge count
    # (and therefore the win condition) is untouched
    c.post("/api/queue/join", data={"player_id": 3})
    c.post("/api/phase2/result", data={"winner_id": 2})
    c.post("/api/queue/join", data={"player_id": 4})
    c.post("/api/phase2/result", data={"winner_id": 2})

    c.post("/api/phase2/result", data={"winner_id": 1})  # last challenge beaten
    state = query(db_path, "SELECT * FROM tournament_state")[0]
    assert state["phase"] == "complete"
    assert state["ended_reason"] == "queue_exhausted"


def test_champ_movement_is_never_impossible(client):
    """Property test: play many random Gauntlets and assert that while the
    tournament runs there is ALWAYS a pending champ challenge (the path to
    the title never disappears) and always a playable match."""
    import random

    c, db_path = client
    seed_gauntlet(db_path, extras=(3, 4, 5, 6))
    seed_champ_challenge_pair(db_path)  # as created at Gauntlet start

    for seed_value in range(5):
        rng = random.Random(seed_value)
        # reset to a fresh Gauntlet
        execute(db_path, "DELETE FROM challenge_queue")
        execute(db_path, "DELETE FROM challenger_history")
        execute(db_path, "DELETE FROM phase2_matches")
        execute(
            db_path,
            "UPDATE tournament_state SET phase = 'phase2', big_king_id = 1, "
            "small_king_id = 2, ended_reason = NULL, queue_empty_warning = 0 WHERE id = 1",
        )
        seed_champ_challenge_pair(db_path)

        for _ in range(120):
            state = query(db_path, "SELECT * FROM tournament_state")[0]
            if state["phase"] != "phase2":
                break

            queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")
            # THE invariant: a champ challenge is always pending, so the
            # Little Champ always has a path to the top title
            assert any(q["entry_type"] == "rematch" for q in queue), (
                f"no champ challenge pending (seed {seed_value})"
            )
            assert queue, f"no playable match (seed {seed_value})"

            # sometimes a random eligible player joins the queue
            if rng.random() < 0.4:
                candidate = rng.choice([3, 4, 5, 6])
                c.post("/api/queue/join", data={"player_id": candidate})
                queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")

            # play the front match with a random winner
            front = queue[0]
            if front["entry_type"] == "rematch":
                contenders = (state["small_king_id"], state["big_king_id"])
            else:
                contenders = (front["player_id"], state["small_king_id"])
            winner = rng.choice(contenders)
            resp = c.post("/api/phase2/result", data={"winner_id": winner})
            assert resp.status_code == 200, resp.get_json()