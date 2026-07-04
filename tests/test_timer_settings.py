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


def get_state(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    state = dict(conn.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone())
    conn.close()
    return state


def start_phase2(db_path, minutes_ago=0):
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO players (id, name) VALUES (?, ?)", [(1, "Big"), (2, "Small")]
    )
    conn.execute(
        "UPDATE tournament_state SET phase = 'phase2', big_king_id = 1, small_king_id = 2, "
        "phase2_started_at = datetime('now', ?) WHERE id = 1",
        (f"-{minutes_ago} minutes",),
    )
    conn.commit()
    conn.close()


def seconds_remaining(client_):
    resp = client_.get("/api/state").get_json()
    return resp["phase2"]["seconds_remaining"], resp["phase"]


def test_default_duration_is_two_hours(client):
    c, db_path = client
    assert get_state(db_path)["phase2_duration_seconds"] == 7200


def test_set_length_before_phase2(client):
    c, db_path = client
    resp = c.post("/organizer/timer/duration", data={"minutes": 90})
    assert resp.status_code == 302
    assert get_state(db_path)["phase2_duration_seconds"] == 90 * 60

    start_phase2(db_path)
    remaining, phase = seconds_remaining(c)
    assert phase == "phase2"
    assert 89 * 60 < remaining <= 90 * 60


def test_add_time_defaults_to_30_minutes(client):
    c, db_path = client
    start_phase2(db_path)
    c.post("/organizer/timer/add", data={})
    assert get_state(db_path)["phase2_duration_seconds"] == 7200 + 30 * 60

    c.post("/organizer/timer/add", data={"minutes": 10})
    assert get_state(db_path)["phase2_duration_seconds"] == 7200 + 40 * 60


def test_set_remaining_during_phase2(client):
    c, db_path = client
    start_phase2(db_path, minutes_ago=60)  # one hour in
    c.post("/organizer/timer/set", data={"minutes": 45})
    remaining, phase = seconds_remaining(c)
    assert phase == "phase2"
    assert 44 * 60 < remaining <= 45 * 60


def test_add_time_revives_timer_ended_tournament(client):
    c, db_path = client
    start_phase2(db_path, minutes_ago=121)  # past the 2h default
    _, phase = seconds_remaining(c)  # lazy check flips to complete
    assert phase == "complete"
    assert get_state(db_path)["ended_reason"] == "timer"

    c.post("/organizer/timer/add", data={"minutes": 30})
    state = get_state(db_path)
    assert state["phase"] == "phase2"
    assert state["ended_reason"] is None
    remaining, phase = seconds_remaining(c)
    assert phase == "phase2"
    assert remaining > 0


def test_queue_exhausted_ending_is_not_revived(client):
    c, db_path = client
    start_phase2(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE tournament_state SET phase = 'complete', ended_reason = 'queue_exhausted' "
        "WHERE id = 1"
    )
    conn.commit()
    conn.close()

    c.post("/organizer/timer/add", data={"minutes": 30})
    state = get_state(db_path)
    assert state["phase"] == "complete"
    assert state["ended_reason"] == "queue_exhausted"


def test_rejects_invalid_minutes(client):
    c, db_path = client
    for bad in (0, -5, 100000):
        c.post("/organizer/timer/duration", data={"minutes": bad})
        assert get_state(db_path)["phase2_duration_seconds"] == 7200
    resp = c.post("/organizer/timer/set", data={"minutes": "abc"}, follow_redirects=True)
    assert b"Enter a time" in resp.data
