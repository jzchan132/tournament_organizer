from flask import Blueprint, jsonify, render_template, request

from app.db import get_db
from app.queries import (
    ROUND_NAMES,
    bracket_champion,
    bracket_next_match,
    check_phase2_timer,
    get_bracket_rounds,
    get_phase2_match_log,
    get_players,
    get_queue,
    get_round_robin_matches,
    get_round_robin_standings,
    has_challenged,
    phase2_seconds_remaining,
    queue_front,
    round_robin_champion,
    round_robin_next_match,
)
from app.results import (
    phase2_can_undo,
    record_bracket_result,
    record_phase2_result,
    record_round_robin_result,
    start_phase2,
    undo_bracket_result,
    undo_phase2_match,
    undo_round_robin_result,
)

bp = Blueprint("dashboard", __name__)


def _action_response(error):
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"ok": True})


def _row(r):
    return dict(r) if r is not None else None


def _rows(rs):
    return [dict(r) for r in rs]


@bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@bp.route("/api/state")
def api_state():
    db = get_db()
    state = check_phase2_timer(db)

    bracket_rounds = get_bracket_rounds(db)
    champ = bracket_champion(db)
    bracket_payload = {
        "rounds": {str(k): _rows(v) for k, v in bracket_rounds.items()},
        "round_names": {str(k): v for k, v in ROUND_NAMES.items()},
        "next_match": _row(bracket_next_match(db)),
        "champion": _row(champ),
    }

    round_robin_payload = {
        "matches": _rows(get_round_robin_matches(db)),
        "standings": _rows(get_round_robin_standings(db)),
        "next_match": _row(round_robin_next_match(db)),
        "champion": round_robin_champion(db),
    }

    phase2_payload = None
    if state["phase"] in ("phase2", "complete") and state["big_king_id"]:
        players_by_id = {p["id"]: p["name"] for p in get_players(db)}
        front = queue_front(db)
        phase2_payload = {
            "big_king": {"id": state["big_king_id"], "name": players_by_id.get(state["big_king_id"])},
            "small_king": {
                "id": state["small_king_id"],
                "name": players_by_id.get(state["small_king_id"]),
            },
            "queue": _rows(get_queue(db)),
            "next_match": _row(front),
            "queue_empty_warning": bool(state["queue_empty_warning"]),
            "seconds_remaining": phase2_seconds_remaining(db, state),
            "match_log": _rows(get_phase2_match_log(db)),
            "ended_reason": state["ended_reason"],
            "can_undo": phase2_can_undo(db),
        }

    return jsonify(
        {
            "phase": state["phase"],
            "players": _rows(get_players(db)),
            "bracket": bracket_payload,
            "round_robin": round_robin_payload,
            "phase2": phase2_payload,
        }
    )


@bp.route("/api/bracket/match/<int:match_id>/result", methods=["POST"])
def bracket_result(match_id):
    winner_id = request.form.get("winner_id", type=int)
    return _action_response(record_bracket_result(get_db(), match_id, winner_id))


@bp.route("/api/bracket/match/<int:match_id>/undo", methods=["POST"])
def bracket_undo(match_id):
    return _action_response(undo_bracket_result(get_db(), match_id))


@bp.route("/api/round_robin/match/<int:match_id>/result", methods=["POST"])
def round_robin_result(match_id):
    winner_id = request.form.get("winner_id", type=int)
    return _action_response(record_round_robin_result(get_db(), match_id, winner_id))


@bp.route("/api/round_robin/match/<int:match_id>/undo", methods=["POST"])
def round_robin_undo(match_id):
    return _action_response(undo_round_robin_result(get_db(), match_id))


@bp.route("/api/phase2/start", methods=["POST"])
def phase2_start():
    return _action_response(start_phase2(get_db()))


@bp.route("/api/phase2/result", methods=["POST"])
def phase2_result():
    winner_id = request.form.get("winner_id", type=int)
    db = get_db()
    check_phase2_timer(db)
    return _action_response(record_phase2_result(db, winner_id))


@bp.route("/api/phase2/undo", methods=["POST"])
def phase2_undo():
    return _action_response(undo_phase2_match(get_db()))


@bp.route("/api/queue/join", methods=["POST"])
def queue_join():
    player_id = request.form.get("player_id", type=int)
    db = get_db()
    state = check_phase2_timer(db)

    if state["phase"] != "phase2":
        return jsonify({"error": "The Gauntlet is not active."}), 400
    if not player_id:
        return jsonify({"error": "Missing player."}), 400
    if not db.execute("SELECT 1 FROM players WHERE id = ?", (player_id,)).fetchone():
        return jsonify({"error": "Unknown player."}), 400
    if player_id in (state["big_king_id"], state["small_king_id"]):
        return jsonify({"error": "Reigning champs can't join the challenge queue."}), 400
    if has_challenged(db, player_id, state["small_king_id"]):
        return jsonify({"error": "You've already challenged this Little Champ."}), 400

    already_queued = db.execute(
        "SELECT 1 FROM challenge_queue WHERE player_id = ? AND entry_type = 'challenger'",
        (player_id,),
    ).fetchone()
    if already_queued:
        return jsonify({"error": "You're already in the queue."}), 400

    # New challengers slot in ABOVE a trailing champ challenge, so the bottom
    # champ challenge always stays last. This also guarantees the double-
    # defense ending can only happen when nobody joins between the two champ
    # challenges (or everyone eligible has already used their shot).
    last = db.execute(
        "SELECT id, position, entry_type FROM challenge_queue "
        "ORDER BY position DESC LIMIT 1"
    ).fetchone()
    if last and last["entry_type"] == "rematch":
        new_pos = last["position"]
        db.execute(
            "UPDATE challenge_queue SET position = position + 1 WHERE id = ?",
            (last["id"],),
        )
    else:
        new_pos = last["position"] + 1 if last else 0
    db.execute(
        "INSERT INTO challenge_queue (position, player_id, entry_type) VALUES (?, ?, 'challenger')",
        (new_pos, player_id),
    )
    db.commit()
    return jsonify({"ok": True})
