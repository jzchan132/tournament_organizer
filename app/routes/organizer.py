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
    round_robin_champion,
)

bp = Blueprint("organizer", __name__, url_prefix="/organizer")


@bp.route("/")
def index():
    db = get_db()
    players = get_players(db)
    state = db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
    return render_template(
        "organizer.html",
        bracket_players=[p for p in players if p["in_bracket"]],
        rr_players=[p for p in players if p["in_round_robin"]],
        state=state,
        bracket_rounds=get_bracket_rounds(db),
        round_names=ROUND_NAMES,
        rr_matches=get_round_robin_matches(db),
        rr_standings=get_round_robin_standings(db),
        bracket_champ=bracket_champion(db),
        rr_champ=round_robin_champion(db),
    )


@bp.route("/players/add", methods=["POST"])
def add_player():
    name = request.form.get("name", "").strip()
    group_col = "in_round_robin" if request.form.get("group") == "round_robin" else "in_bracket"
    if name:
        db = get_db()
        cur = db.execute(
            f"INSERT OR IGNORE INTO players (name, {group_col}) VALUES (?, 1)", (name,)
        )
        if cur.rowcount == 0:
            flash(f"There's already a player named {name}.")
        db.commit()
    return redirect(url_for("organizer.index"))


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
            "round robin, or Phase 2 records. Re-seed the group without them instead."
        )
    return redirect(url_for("organizer.index"))


def _phase_is_setup(db):
    return (
        db.execute("SELECT phase FROM tournament_state WHERE id = 1").fetchone()["phase"]
        == "setup"
    )


@bp.route("/bracket/seed", methods=["POST"])
def seed_bracket():
    db = get_db()
    if not _phase_is_setup(db):
        flash("Phase 2 has already started -- the bracket is locked.")
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
        flash("Phase 2 has already started -- the round robin is locked.")
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
