ROUND_NAMES = {1: "Quarterfinals", 2: "Semifinals", 3: "Final"}
PHASE2_DURATION_SECONDS = 2 * 60 * 60


def check_phase2_timer(db):
    """Lazily end Phase 2 if the 2-hour timer has expired.

    Called on every /api/state poll rather than via a background scheduler,
    since a poll-time check is simplest for this scale of app.
    """
    state = db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
    if state["phase"] != "phase2" or not state["phase2_started_at"]:
        return state
    elapsed = db.execute(
        "SELECT (julianday('now') - julianday(?)) * 86400 AS secs",
        (state["phase2_started_at"],),
    ).fetchone()["secs"]
    if elapsed >= PHASE2_DURATION_SECONDS:
        db.execute(
            "UPDATE tournament_state SET phase = 'complete', ended_reason = 'timer' WHERE id = 1"
        )
        db.commit()
        state = db.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
    return state


def phase2_seconds_remaining(db, state):
    if not state["phase2_started_at"]:
        return None
    elapsed = db.execute(
        "SELECT (julianday('now') - julianday(?)) * 86400 AS secs",
        (state["phase2_started_at"],),
    ).fetchone()["secs"]
    return max(0, PHASE2_DURATION_SECONDS - elapsed)


def get_players(db):
    return db.execute("SELECT * FROM players ORDER BY name").fetchall()


def get_bracket_rounds(db):
    rows = db.execute(
        """SELECT bm.*, p1.name AS player1_name, p2.name AS player2_name, w.name AS winner_name
           FROM bracket_matches bm
           LEFT JOIN players p1 ON p1.id = bm.player1_id
           LEFT JOIN players p2 ON p2.id = bm.player2_id
           LEFT JOIN players w ON w.id = bm.winner_id
           ORDER BY bm.round, bm.position"""
    ).fetchall()
    rounds = {}
    for r in rows:
        rounds.setdefault(r["round"], []).append(r)
    return rounds


def bracket_champion(db):
    row = db.execute(
        "SELECT p.id, p.name FROM bracket_matches bm JOIN players p ON p.id = bm.winner_id "
        "WHERE bm.round = 3"
    ).fetchone()
    return row


def get_round_robin_matches(db):
    return db.execute(
        """SELECT rm.*, p1.name AS player1_name, p2.name AS player2_name, w.name AS winner_name
           FROM round_robin_matches rm
           JOIN players p1 ON p1.id = rm.player1_id
           JOIN players p2 ON p2.id = rm.player2_id
           LEFT JOIN players w ON w.id = rm.winner_id
           ORDER BY rm.id"""
    ).fetchall()


def get_round_robin_standings(db):
    # Tiebreaker wins count toward the standings, so the table keeps moving
    # while ties are being played off.
    rows = db.execute(
        """SELECT p.id, p.name, COUNT(rm.id) AS wins
           FROM players p
           JOIN round_robin_matches rm ON rm.winner_id = p.id
           WHERE p.in_round_robin = 1
           GROUP BY p.id
           UNION ALL
           SELECT p.id, p.name, 0 AS wins
           FROM players p
           WHERE p.in_round_robin = 1 AND p.id NOT IN (
               SELECT DISTINCT winner_id FROM round_robin_matches
               WHERE winner_id IS NOT NULL
           )
           ORDER BY wins DESC"""
    ).fetchall()
    return rows


def resolve_rr_champion(db):
    """Work out the round robin champion, accounting for tiebreaker matches.

    When every existing match is decided but several players share the most
    wins, a full round of tiebreakers (every tied pair plays) is owed. Those
    wins count toward the standings, and if a round ends still tied (a win
    cycle), another round is owed -- rounds keep coming until one player
    stands alone at the top.

    Returns {"champion": {id, name} or None,
             "needed_tiebreakers": [(player1_id, player2_id), ...]}
    where needed_tiebreakers are matches that should exist but haven't been
    created yet (empty when waiting on results or when a champion exists).
    """
    from itertools import combinations

    standings = get_round_robin_standings(db)
    matches = get_round_robin_matches(db)

    if not standings or not matches or any(m["winner_id"] is None for m in matches):
        return {"champion": None, "needed_tiebreakers": []}

    top_wins = standings[0]["wins"]
    leaders = [s for s in standings if s["wins"] == top_wins]
    if len(leaders) == 1:
        return {
            "champion": {"id": leaders[0]["id"], "name": leaders[0]["name"]},
            "needed_tiebreakers": [],
        }
    return {
        "champion": None,
        "needed_tiebreakers": list(combinations([s["id"] for s in leaders], 2)),
    }


def round_robin_champion(db):
    return resolve_rr_champion(db)["champion"]


def round_robin_next_match(db):
    row = db.execute(
        """SELECT rm.*, p1.name AS player1_name, p2.name AS player2_name
           FROM round_robin_matches rm
           JOIN players p1 ON p1.id = rm.player1_id
           JOIN players p2 ON p2.id = rm.player2_id
           WHERE rm.winner_id IS NULL
           ORDER BY rm.id LIMIT 1"""
    ).fetchone()
    return row


def get_queue(db):
    return db.execute(
        """SELECT cq.*, p.name AS player_name
           FROM challenge_queue cq
           JOIN players p ON p.id = cq.player_id
           ORDER BY cq.position"""
    ).fetchall()


def queue_front(db):
    return db.execute(
        """SELECT cq.*, p.name AS player_name
           FROM challenge_queue cq
           JOIN players p ON p.id = cq.player_id
           ORDER BY cq.position LIMIT 1"""
    ).fetchone()


def renumber_queue(db):
    rows = db.execute("SELECT id FROM challenge_queue ORDER BY position").fetchall()
    for i, row in enumerate(rows):
        db.execute("UPDATE challenge_queue SET position = ? WHERE id = ?", (i, row["id"]))


def has_challenged(db, challenger_id, small_king_id):
    row = db.execute(
        "SELECT 1 FROM challenger_history WHERE challenger_id = ? AND small_king_id = ?",
        (challenger_id, small_king_id),
    ).fetchone()
    return row is not None


def get_phase2_match_log(db):
    return db.execute(
        """SELECT pm.*, w.name AS winner_name,
                  bk.name AS big_king_name, sk.name AS small_king_name,
                  c.name AS challenger_name
           FROM phase2_matches pm
           JOIN players w ON w.id = pm.winner_id
           JOIN players bk ON bk.id = pm.big_king_id
           JOIN players sk ON sk.id = pm.small_king_id
           LEFT JOIN players c ON c.id = pm.challenger_id
           ORDER BY pm.id DESC"""
    ).fetchall()


def bracket_next_match(db):
    row = db.execute(
        """SELECT bm.*, p1.name AS player1_name, p2.name AS player2_name
           FROM bracket_matches bm
           JOIN players p1 ON p1.id = bm.player1_id
           JOIN players p2 ON p2.id = bm.player2_id
           WHERE bm.winner_id IS NULL AND bm.player1_id IS NOT NULL AND bm.player2_id IS NOT NULL
           ORDER BY bm.round, bm.position LIMIT 1"""
    ).fetchone()
    return row
