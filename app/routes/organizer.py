import sqlite3
from itertools import combinations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.db import get_db
from app.queries import (
    ROUND_NAMES,
    bracket_champion,
    get_bracket_rounds,
    get_players,
    get_round_robin_matches,
    get_round_robin_standings,
    phase2_elapsed_seconds,
    phase2_seconds_remaining,
    round_robin_champion,
)

bp = Blueprint("organizer", __name__, url_prefix="/organizer")


@bp.route("/")
def index():
    db = get_db()
    players = get_players(db)
    state = db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
    remaining = phase2_seconds_remaining(db, state)
    return render_template(
        "organizer.html",
        focus=request.args.get("focus"),
        bracket_players=[p for p in players if p["in_bracket"]],
        rr_players=[p for p in players if p["in_round_robin"]],
        state=state,
        bracket_rounds=get_bracket_rounds(db),
        round_names=ROUND_NAMES,
        rr_matches=get_round_robin_matches(db),
        rr_standings=get_round_robin_standings(db),
        bracket_champ=bracket_champion(db),
        rr_champ=round_robin_champion(db),
        duration_minutes=state["phase2_duration_seconds"] // 60,
        remaining_minutes=None if remaining is None else int(remaining // 60),
    )


@bp.route("/players/add", methods=["POST"])
def add_player():
    group = request.form.get("group")
    group_col = "in_round_robin" if group == "round_robin" else "in_bracket"
    # Accepts a single name or a comma-separated list ("Alex, Bailey, Casey")
    names = [n.strip() for n in request.form.get("name", "").split(",") if n.strip()]
    if names:
        db = get_db()
        taken = []
        for name in names:
            cur = db.execute(
                f"INSERT OR IGNORE INTO players (name, {group_col}) VALUES (?, 1)", (name,)
            )
            if cur.rowcount == 0:
                taken.append(name)
        db.commit()
        if taken:
            flash(f"Already taken: {', '.join(taken)}.")
    return redirect(url_for("organizer.index", focus=group))


@bp.route("/players/<int:player_id>/remove", methods=["POST"])
def remove_player(player_id):
    db = get_db()
    try:
        db.execute("DELETE FROM players WHERE id = ?", (player_id,))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash(
            "Can't remove this player -- they're already part of the bracket, "
            "round robin, or Gauntlet records. Re-seed the group without them instead."
        )
    return redirect(url_for("organizer.index"))


def _phase_is_setup(db):
    return (
        db.execute("SELECT phase FROM tournament_state WHERE id = 1").fetchone()["phase"]
        == "setup"
    )


MAX_TIMER_MINUTES = 24 * 60


def _timer_minutes(field="minutes", default=None):
    minutes = request.form.get(field, type=int)
    if minutes is None:
        minutes = default
    if minutes is None or not (1 <= minutes <= MAX_TIMER_MINUTES):
        return None
    return minutes


def _revive_if_timer_ended(db):
    """Adding/setting time can bring back a tournament the clock ended.

    Only applies to timer endings -- a queue-exhausted ending is a rules
    outcome and stays final.
    """
    state = db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
    if state["phase"] == "complete" and state["ended_reason"] == "timer":
        remaining = phase2_seconds_remaining(db, state)
        if remaining and remaining > 0:
            db.execute(
                "UPDATE tournament_state SET phase = 'phase2', ended_reason = NULL "
                "WHERE id = 1"
            )
            flash("The clock has time again -- the Gauntlet is back on!")


@bp.route("/gauntlet/champ_challenge", methods=["POST"])
def queue_champ_challenge():
    """Manual override: queue a champ challenge (Little Champ vs Big Champ).

    Normally these are queued automatically when a new Little Champ rises
    from the queue; this lets the organizer add one whenever needed.
    """
    db = get_db()
    state = db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
    if state["phase"] != "phase2":
        flash("The Gauntlet isn't running -- no champ challenge to queue.")
        return redirect(url_for("organizer.index"))
    if db.execute(
        "SELECT 1 FROM challenge_queue WHERE entry_type = 'rematch'"
    ).fetchone():
        flash("A champ challenge is already in the queue.")
        return redirect(url_for("organizer.index"))

    if request.form.get("position") == "front":
        pos = db.execute(
            "SELECT COALESCE(MIN(position), 1) - 1 AS p FROM challenge_queue"
        ).fetchone()["p"]
    else:
        pos = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM challenge_queue"
        ).fetchone()["p"]
    db.execute(
        "INSERT INTO challenge_queue (position, player_id, entry_type) VALUES (?, ?, 'rematch')",
        (pos, state["small_king_id"]),
    )
    db.commit()
    flash("Champ challenge queued.")
    return redirect(url_for("organizer.index"))


@bp.route("/timer/duration", methods=["POST"])
def timer_duration():
    minutes = _timer_minutes()
    if minutes is None:
        flash(f"Enter a length between 1 and {MAX_TIMER_MINUTES} minutes.")
        return redirect(url_for("organizer.index"))
    db = get_db()
    db.execute(
        "UPDATE tournament_state SET phase2_duration_seconds = ? WHERE id = 1",
        (minutes * 60,),
    )
    _revive_if_timer_ended(db)
    db.commit()
    flash(f"Gauntlet length set to {minutes} minutes.")
    return redirect(url_for("organizer.index"))


@bp.route("/timer/add", methods=["POST"])
def timer_add():
    minutes = _timer_minutes(default=30)
    if minutes is None:
        flash(f"Enter between 1 and {MAX_TIMER_MINUTES} minutes to add.")
        return redirect(url_for("organizer.index"))
    db = get_db()
    db.execute(
        "UPDATE tournament_state SET phase2_duration_seconds = "
        "MIN(phase2_duration_seconds + ?, ?) WHERE id = 1",
        (minutes * 60, MAX_TIMER_MINUTES * 60 * 2),
    )
    _revive_if_timer_ended(db)
    db.commit()
    flash(f"Added {minutes} minutes to the Gauntlet timer.")
    return redirect(url_for("organizer.index"))


@bp.route("/timer/set", methods=["POST"])
def timer_set():
    minutes = _timer_minutes()
    if minutes is None:
        flash(f"Enter a time between 1 and {MAX_TIMER_MINUTES} minutes.")
        return redirect(url_for("organizer.index"))
    db = get_db()
    state = db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
    elapsed = phase2_elapsed_seconds(db, state)
    if elapsed is None:
        # Phase 2 hasn't started; setting the remaining time = setting the length.
        new_duration = minutes * 60
    else:
        new_duration = int(elapsed) + minutes * 60
    db.execute(
        "UPDATE tournament_state SET phase2_duration_seconds = ? WHERE id = 1",
        (new_duration,),
    )
    _revive_if_timer_ended(db)
    db.commit()
    flash(f"Gauntlet timer set to {minutes} minutes remaining.")
    return redirect(url_for("organizer.index"))


@bp.route("/bracket/seed", methods=["POST"])
def seed_bracket():
    db = get_db()
    if not _phase_is_setup(db):
        flash("The Gauntlet has already started -- the bracket is locked.")
        return redirect(url_for("organizer.index"))
    raw_ids = request.form.getlist("seed")
    ids = [int(x) for x in raw_ids if x]
    bracket_ids = {
        r["id"] for r in db.execute("SELECT id FROM players WHERE in_bracket = 1")
    }
    if len(ids) != 8 or len(set(ids)) != 8 or set(ids) != bracket_ids:
        flash("The bracket needs exactly 8 players -- add or remove players first.")
        return redirect(url_for("organizer.index"))
    db.execute("DELETE FROM bracket_matches")

    final_id = db.execute(
        "INSERT INTO bracket_matches (round, position) VALUES (3, 0)"
    ).lastrowid

    sf_ids = []
    for pos in (0, 1):
        slot = pos + 1
        sf_id = db.execute(
            "INSERT INTO bracket_matches (round, position, next_match_id, next_match_slot) "
            "VALUES (2, ?, ?, ?)",
            (pos, final_id, slot),
        ).lastrowid
        sf_ids.append(sf_id)

    for pos in range(4):
        sf_target = sf_ids[pos // 2]
        slot = (pos % 2) + 1
        p1, p2 = ids[pos * 2], ids[pos * 2 + 1]
        db.execute(
            "INSERT INTO bracket_matches "
            "(round, position, player1_id, player2_id, next_match_id, next_match_slot) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (pos, p1, p2, sf_target, slot),
        )

    placeholders = ",".join("?" * len(ids))
    db.execute(f"UPDATE players SET in_bracket = 1 WHERE id IN ({placeholders})", ids)
    db.commit()
    return redirect(url_for("organizer.index"))


@bp.route("/round_robin/build", methods=["POST"])
def build_round_robin():
    db = get_db()
    if not _phase_is_setup(db):
        flash("The Gauntlet has already started -- the round robin is locked.")
        return redirect(url_for("organizer.index"))
    ids = [r["id"] for r in db.execute("SELECT id FROM players WHERE in_round_robin = 1")]
    if len(ids) < 2:
        flash("Add at least 2 players to the round robin first (4 is the standard format).")
        return redirect(url_for("organizer.index"))

    db.execute("DELETE FROM round_robin_matches")
    for p1, p2 in combinations(ids, 2):
        db.execute(
            "INSERT INTO round_robin_matches (player1_id, player2_id) VALUES (?, ?)",
            (p1, p2),
        )
    db.commit()
    return redirect(url_for("organizer.index"))
