"""Edge-case audit: unusual-but-possible sequences at a live event."""

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


def execute(db_path, sql, args=()):
    conn = sqlite3.connect(db_path)
    conn.execute(sql, args)
    conn.commit()
    conn.close()


def query(db_path, sql, args=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return rows


def seed_phase2(db_path, big=1, small=2, extras=(3, 4, 5)):
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


def seed_bracket_players(c, count=8):
    for i in range(1, count + 1):
        c.post("/organizer/players/add", data={"name": f"P{i}", "group": "bracket"})


# --- queue join validation ---


def test_join_with_nonexistent_player_is_rejected_not_500(client):
    c, db_path = client
    seed_phase2(db_path)
    resp = c.post("/api/queue/join", data={"player_id": 999})
    assert resp.status_code == 400
    assert b"Unknown player" in resp.data


def test_kings_cannot_join_queue(client):
    c, db_path = client
    seed_phase2(db_path)
    for king in (1, 2):
        resp = c.post("/api/queue/join", data={"player_id": king})
        assert resp.status_code == 400


def test_double_join_is_rejected(client):
    c, db_path = client
    seed_phase2(db_path)
    assert c.post("/api/queue/join", data={"player_id": 3}).status_code == 200
    assert c.post("/api/queue/join", data={"player_id": 3}).status_code == 400


def test_join_after_tournament_complete_is_rejected(client):
    c, db_path = client
    seed_phase2(db_path)
    execute(db_path, "UPDATE tournament_state SET phase = 'complete' WHERE id = 1")
    assert c.post("/api/queue/join", data={"player_id": 3}).status_code == 400


def test_manual_champ_challenge_override(client):
    c, db_path = client
    seed_phase2(db_path)
    # organizer queues one at the back, then a duplicate is rejected
    resp = c.post(
        "/organizer/gauntlet/champ_challenge", data={"position": "back"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")
    assert [q["entry_type"] for q in queue] == ["rematch"]

    resp = c.post(
        "/organizer/gauntlet/champ_challenge", data={"position": "back"},
        follow_redirects=True,
    )
    assert b"already in the queue" in resp.data
    assert len(query(db_path, "SELECT * FROM challenge_queue")) == 1


def test_manual_champ_challenge_front_goes_first(client):
    c, db_path = client
    seed_phase2(db_path)
    c.post("/api/queue/join", data={"player_id": 3})
    c.post("/organizer/gauntlet/champ_challenge", data={"position": "front"})
    queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")
    assert [q["entry_type"] for q in queue] == ["rematch", "challenger"]


# --- phase 2 result guards ---


def test_result_with_empty_queue_is_rejected(client):
    c, db_path = client
    seed_phase2(db_path)
    resp = c.post("/api/phase2/result", data={"winner_id": 1})
    assert resp.status_code == 400


def test_timer_expiry_blocks_results_and_joins(client):
    c, db_path = client
    seed_phase2(db_path)
    c.post("/api/queue/join", data={"player_id": 3})
    execute(
        db_path,
        "UPDATE tournament_state SET phase2_started_at = datetime('now', '-3 hours') WHERE id = 1",
    )
    # the lazy timer check runs on both endpoints
    assert c.post("/api/phase2/result", data={"winner_id": 3}).status_code == 400
    assert c.post("/api/queue/join", data={"player_id": 4}).status_code == 400
    state = query(db_path, "SELECT phase, ended_reason FROM tournament_state")[0]
    assert state["phase"] == "complete"
    assert state["ended_reason"] == "timer"


def test_takeover_replaces_existing_champ_challenges_with_fresh_pair(client):
    c, db_path = client
    seed_phase2(db_path)
    # queue: challenger P3, then an organizer-queued champ challenge
    c.post("/api/queue/join", data={"player_id": 3})
    c.post("/organizer/gauntlet/champ_challenge", data={"position": "back"})
    # P3 dethrones P2: the old champ challenge is replaced by the automatic
    # top-and-bottom pair (role-based, so never stale)
    assert c.post("/api/phase2/result", data={"winner_id": 3}).status_code == 200
    queue = query(db_path, "SELECT * FROM challenge_queue ORDER BY position")
    assert [q["entry_type"] for q in queue] == ["rematch", "rematch"]
    state = query(db_path, "SELECT small_king_id FROM tournament_state")[0]
    assert state["small_king_id"] == 3
    # the dethroned champ may re-enter as a regular challenger
    assert c.post("/api/queue/join", data={"player_id": 2}).status_code == 200


# --- phase 1 guards ---


def test_bracket_result_requires_both_players(client):
    c, db_path = client
    seed_bracket_players(c)
    c.post("/organizer/bracket/seed", data=MultiDict([("seed", str(i)) for i in range(1, 9)]))
    # play only QF 1, then try to record the semifinal (one slot still empty)
    qfs = query(db_path, "SELECT * FROM bracket_matches WHERE round = 1 ORDER BY position")
    c.post(f"/api/bracket/match/{qfs[0]['id']}/result", data={"winner_id": qfs[0]["player1_id"]})
    sf_id = qfs[0]["next_match_id"]
    resp = c.post(f"/api/bracket/match/{sf_id}/result", data={"winner_id": qfs[0]["player1_id"]})
    assert resp.status_code == 400
    assert b"Both players" in resp.data


def test_reseeding_locked_after_phase2_starts(client):
    c, db_path = client
    seed_bracket_players(c)
    c.post("/organizer/bracket/seed", data=MultiDict([("seed", str(i)) for i in range(1, 9)]))
    matches_before = query(db_path, "SELECT COUNT(*) AS c FROM bracket_matches")[0]["c"]
    execute(db_path, "UPDATE tournament_state SET phase = 'phase2' WHERE id = 1")

    c.post("/organizer/bracket/seed", data=MultiDict([("seed", str(i)) for i in range(1, 9)]))
    assert query(db_path, "SELECT COUNT(*) AS c FROM bracket_matches")[0]["c"] == matches_before

    c.post("/organizer/round_robin/build")
    assert query(db_path, "SELECT COUNT(*) AS c FROM round_robin_matches")[0]["c"] == 0


def test_phase2_start_blocked_by_pending_tiebreaker(client):
    c, db_path = client
    # bracket fully decided
    seed_bracket_players(c)
    c.post("/organizer/bracket/seed", data=MultiDict([("seed", str(i)) for i in range(1, 9)]))
    for _ in range(7):
        m = query(
            db_path,
            "SELECT * FROM bracket_matches WHERE winner_id IS NULL "
            "AND player1_id IS NOT NULL AND player2_id IS NOT NULL ORDER BY round LIMIT 1",
        )[0]
        c.post(f"/api/bracket/match/{m['id']}/result", data={"winner_id": m["player1_id"]})
    # round robin ends tied
    for i in range(9, 13):
        c.post("/organizer/players/add", data={"name": f"P{i}", "group": "round_robin"})
    c.post("/organizer/round_robin/build")
    rr = query(db_path, "SELECT * FROM round_robin_matches WHERE is_tiebreaker = 0")
    ids = sorted({m["player1_id"] for m in rr} | {m["player2_id"] for m in rr})
    a, b, x, y = ids
    winners = {
        (a, b): a, (a, x): a, (a, y): y,
        (b, x): b, (b, y): b, (x, y): x,
    }
    for m in rr:
        c.post(
            f"/api/round_robin/match/{m['id']}/result",
            data={"winner_id": winners[(m["player1_id"], m["player2_id"])]},
        )

    resp = c.post("/api/phase2/start")
    assert resp.status_code == 400  # tiebreaker still pending

    tb = query(db_path, "SELECT * FROM round_robin_matches WHERE is_tiebreaker = 1")[0]
    c.post(f"/api/round_robin/match/{tb['id']}/result", data={"winner_id": tb["player1_id"]})
    assert c.post("/api/phase2/start").status_code == 200
    # double-start is rejected
    assert c.post("/api/phase2/start").status_code == 400
