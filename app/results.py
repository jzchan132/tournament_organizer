"""Result recording, undo, and phase transition logic.

Every function takes an open db connection, applies the change, commits, and
returns None on success or a human-readable error string on rejection.
"""

import json

from app.queries import (
    bracket_champion,
    queue_front,
    renumber_queue,
    resolve_rr_champion,
    round_robin_champion,
)
from app.state_machine import resolve_phase2_match


def _phase(db):
    return db.execute("SELECT phase FROM tournament_state WHERE id = 1").fetchone()["phase"]


def record_bracket_result(db, match_id, winner_id):
    if _phase(db) != "setup":
        return "Phase 1 is over -- bracket results are locked."
    match = db.execute("SELECT * FROM bracket_matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        return "Match not found."
    if match["winner_id"]:
        return "This match already has a result. Undo it first if it's wrong."
    if not winner_id or winner_id not in (match["player1_id"], match["player2_id"]):
        return "Invalid winner for this match."

    db.execute("UPDATE bracket_matches SET winner_id = ? WHERE id = ?", (winner_id, match_id))
    if match["next_match_id"]:
        slot_col = "player1_id" if match["next_match_slot"] == 1 else "player2_id"
        db.execute(
            f"UPDATE bracket_matches SET {slot_col} = ? WHERE id = ?",
            (winner_id, match["next_match_id"]),
        )
    db.commit()
    return None


def undo_bracket_result(db, match_id):
    if _phase(db) != "setup":
        return "Phase 2 has already started -- Phase 1 results are locked."
    match = db.execute("SELECT * FROM bracket_matches WHERE id = ?", (match_id,)).fetchone()
    if not match or not match["winner_id"]:
        return "No result to undo."
    if match["next_match_id"]:
        nxt = db.execute(
            "SELECT * FROM bracket_matches WHERE id = ?", (match["next_match_id"],)
        ).fetchone()
        if nxt["winner_id"]:
            return "The following match was already played -- undo that one first."
        slot_col = "player1_id" if match["next_match_slot"] == 1 else "player2_id"
        db.execute(
            f"UPDATE bracket_matches SET {slot_col} = NULL WHERE id = ?",
            (match["next_match_id"],),
        )
    db.execute("UPDATE bracket_matches SET winner_id = NULL WHERE id = ?", (match_id,))
    db.commit()
    return None


def _ensure_rr_tiebreaker(db):
    """Create the next tiebreaker match if regular play just ended in a tie."""
    needed = resolve_rr_champion(db)["needed_tiebreaker"]
    if needed:
        db.execute(
            "INSERT INTO round_robin_matches (player1_id, player2_id, is_tiebreaker) "
            "VALUES (?, ?, 1)",
            needed,
        )


def record_round_robin_result(db, match_id, winner_id):
    if _phase(db) != "setup":
        return "Phase 1 is over -- round robin results are locked."
    match = db.execute("SELECT * FROM round_robin_matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        return "Match not found."
    if match["winner_id"]:
        return "This match already has a result. Undo it first if it's wrong."
    if not winner_id or winner_id not in (match["player1_id"], match["player2_id"]):
        return "Invalid winner for this match."
    db.execute(
        "UPDATE round_robin_matches SET winner_id = ? WHERE id = ?", (winner_id, match_id)
    )
    _ensure_rr_tiebreaker(db)
    db.commit()
    return None


def undo_round_robin_result(db, match_id):
    if _phase(db) != "setup":
        return "Phase 2 has already started -- Phase 1 results are locked."
    match = db.execute("SELECT * FROM round_robin_matches WHERE id = ?", (match_id,)).fetchone()
    if not match or not match["winner_id"]:
        return "No result to undo."
    # Any tiebreakers generated after this result are no longer valid.
    db.execute(
        "DELETE FROM round_robin_matches WHERE is_tiebreaker = 1 AND id > ?", (match_id,)
    )
    db.execute("UPDATE round_robin_matches SET winner_id = NULL WHERE id = ?", (match_id,))
    db.commit()
    return None


def start_phase2(db):
    if _phase(db) != "setup":
        return "Phase 2 has already started."
    champ = bracket_champion(db)
    rr_champ = round_robin_champion(db)
    if not champ or not rr_champ:
        return "Both the bracket and round robin must be complete before starting Phase 2."
    db.execute(
        "UPDATE tournament_state SET phase = 'phase2', big_king_id = ?, small_king_id = ?, "
        "phase2_started_at = datetime('now') WHERE id = 1",
        (champ["id"], rr_champ["id"]),
    )
    db.commit()
    return None


def _save_phase2_snapshot(db):
    state = dict(db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone())
    queue = [dict(r) for r in db.execute("SELECT * FROM challenge_queue ORDER BY position")]
    history = [
        [r["challenger_id"], r["small_king_id"]]
        for r in db.execute("SELECT challenger_id, small_king_id FROM challenger_history")
    ]
    max_match_id = db.execute(
        "SELECT COALESCE(MAX(id), 0) AS m FROM phase2_matches"
    ).fetchone()["m"]
    snapshot = json.dumps(
        {"state": state, "queue": queue, "history": history, "max_match_id": max_match_id}
    )
    db.execute(
        "INSERT INTO phase2_undo (id, snapshot) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET snapshot = excluded.snapshot",
        (snapshot,),
    )


def phase2_can_undo(db):
    return db.execute("SELECT 1 FROM phase2_undo WHERE id = 1").fetchone() is not None


def undo_phase2_match(db):
    row = db.execute("SELECT snapshot FROM phase2_undo WHERE id = 1").fetchone()
    if not row:
        return "Nothing to undo."
    snap = json.loads(row["snapshot"])
    state = snap["state"]
    db.execute(
        "UPDATE tournament_state SET phase = ?, big_king_id = ?, small_king_id = ?, "
        "phase2_started_at = ?, consecutive_bk_wins = ?, queue_empty_warning = ?, "
        "ended_reason = ? WHERE id = 1",
        (
            state["phase"],
            state["big_king_id"],
            state["small_king_id"],
            state["phase2_started_at"],
            state["consecutive_bk_wins"],
            state["queue_empty_warning"],
            state["ended_reason"],
        ),
    )
    db.execute("DELETE FROM challenge_queue")
    for q in snap["queue"]:
        db.execute(
            "INSERT INTO challenge_queue (id, position, player_id, entry_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (q["id"], q["position"], q["player_id"], q["entry_type"], q["created_at"]),
        )
    db.execute("DELETE FROM challenger_history")
    for challenger_id, small_king_id in snap["history"]:
        db.execute(
            "INSERT INTO challenger_history (challenger_id, small_king_id) VALUES (?, ?)",
            (challenger_id, small_king_id),
        )
    db.execute("DELETE FROM phase2_matches WHERE id > ?", (snap["max_match_id"],))
    db.execute("DELETE FROM phase2_undo")
    db.commit()
    return None


def record_phase2_result(db, winner_id):
    state = db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
    if state["phase"] != "phase2":
        return "Phase 2 is not active."

    front = queue_front(db)
    if not front:
        return "The challenge queue is empty -- nothing to record."

    valid_winners = (
        (state["small_king_id"], state["big_king_id"])
        if front["entry_type"] == "rematch"
        else (front["player_id"], state["small_king_id"])
    )
    if winner_id not in valid_winners:
        return "Invalid winner for this match."

    _save_phase2_snapshot(db)

    db.execute("DELETE FROM challenge_queue WHERE id = ?", (front["id"],))
    remaining = db.execute("SELECT COUNT(*) AS c FROM challenge_queue").fetchone()["c"]
    queue_empty_after_pop = remaining == 0

    outcome = resolve_phase2_match(
        big_king_id=state["big_king_id"],
        small_king_id=state["small_king_id"],
        consecutive_bk_wins=state["consecutive_bk_wins"],
        front_entry_type=front["entry_type"],
        front_entry_player_id=front["player_id"],
        winner_id=winner_id,
        queue_empty_after_pop=queue_empty_after_pop,
    )

    db.execute(
        "INSERT INTO phase2_matches (match_type, big_king_id, small_king_id, challenger_id, winner_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            outcome["match_type"],
            state["big_king_id"],
            state["small_king_id"],
            front["player_id"] if front["entry_type"] == "challenger" else None,
            winner_id,
        ),
    )

    if outcome["record_history_pair"]:
        challenger_id, sk_id = outcome["record_history_pair"]
        db.execute(
            "INSERT OR IGNORE INTO challenger_history (challenger_id, small_king_id) VALUES (?, ?)",
            (challenger_id, sk_id),
        )

    if outcome["purge_against_small_king_id"] is not None:
        target = outcome["purge_against_small_king_id"]
        db.execute(
            "DELETE FROM challenge_queue WHERE entry_type = 'challenger' AND player_id IN "
            "(SELECT challenger_id FROM challenger_history WHERE small_king_id = ?)",
            (target,),
        )
        # A leftover rematch entry belonged to whoever was small king when it was
        # queued -- once the title has moved to someone else, that entry no longer
        # represents "the current small king's challenge" and is no longer valid.
        db.execute(
            "DELETE FROM challenge_queue WHERE entry_type = 'rematch' AND player_id != ?",
            (target,),
        )
        renumber_queue(db)

    if outcome["requeue_rematch_for"] is not None:
        next_pos = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM challenge_queue"
        ).fetchone()["p"]
        db.execute(
            "INSERT INTO challenge_queue (position, player_id, entry_type) VALUES (?, ?, 'rematch')",
            (next_pos, outcome["requeue_rematch_for"]),
        )

    new_phase = "complete" if outcome["phase_complete"] else state["phase"]
    db.execute(
        "UPDATE tournament_state SET big_king_id = ?, small_king_id = ?, consecutive_bk_wins = ?, "
        "queue_empty_warning = ?, phase = ?, ended_reason = ? WHERE id = 1",
        (
            outcome["big_king_id"],
            outcome["small_king_id"],
            outcome["consecutive_bk_wins"],
            1 if outcome["queue_empty_warning"] else 0,
            new_phase,
            outcome["ended_reason"],
        ),
    )

    db.commit()
    return None
