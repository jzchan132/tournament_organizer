def resolve_phase2_match(
    *,
    big_king_id,
    small_king_id,
    consecutive_bk_wins,
    front_entry_type,
    front_entry_player_id,
    winner_id,
):
    """Pure decision logic for a single Gauntlet match outcome.

    Naming note: db/internal names keep the original king terminology
    (big_king = Big Champ, small_king = Little Champ, entry_type
    'rematch' = a champ challenge) so existing saves stay loadable.

    front_entry_type: 'rematch' (a champ challenge -- whoever is CURRENTLY
        Little Champ challenges the Big Champ; entries are role-based, so a
        title swap never invalidates one) or 'challenger' (someone from the
        queue challenging the Little Champ).

    consecutive_bk_wins counts the Big Champ's champ-challenge wins against
    the same reigning Little Champ. Only a champ swap resets it -- a Little
    Champ successfully defending against a queue challenger does not. Two
    such wins end the tournament.

    Returns a dict describing what the DB layer should persist. This touches
    no database -- it only decides outcomes from plain inputs, which is what
    makes the champ-swap/queue/streak rules testable in isolation.
    """
    result = {
        "match_type": "bk_vs_sk" if front_entry_type == "rematch" else "challenger_vs_sk",
        "big_king_id": big_king_id,
        "small_king_id": small_king_id,
        "consecutive_bk_wins": consecutive_bk_wins,
        "title_changed": False,
        "record_history_pair": None,
        # Voiding is deferred until a champ challenge resolves, because the
        # champ challenge right after a new Little Champ is crowned can swap
        # the titles again -- only then is it known who challengers face.
        "purge_against_small_king_id": None,
        # On a challenger takeover, champ challenges are queued at both the
        # top (immediate title shot) and bottom (one more after the queue).
        "add_champ_challenges": False,
        # On a champ swap, the demoted champ's next shot is queued at the
        # bottom only.
        "add_champ_challenge_bottom": False,
        "phase_complete": False,
        "ended_reason": None,
    }

    if front_entry_type == "rematch":
        if winner_id == small_king_id:
            # Little Champ beats Big Champ: titles swap. Exempt from the
            # one-time-challenge history entirely. A fresh champ challenge
            # goes to the bottom of the queue for the demoted champ.
            result["big_king_id"] = small_king_id
            result["small_king_id"] = big_king_id
            result["consecutive_bk_wins"] = 0
            result["title_changed"] = True
            result["purge_against_small_king_id"] = big_king_id
            result["add_champ_challenge_bottom"] = True
        else:
            # Big Champ defends: second champ-challenge win against the same
            # reigning Little Champ ends the tournament.
            result["consecutive_bk_wins"] = consecutive_bk_wins + 1
            result["purge_against_small_king_id"] = small_king_id
            if result["consecutive_bk_wins"] >= 2:
                result["phase_complete"] = True
                result["ended_reason"] = "queue_exhausted"
    else:
        challenger_id = front_entry_player_id
        result["record_history_pair"] = (challenger_id, small_king_id)
        if winner_id == challenger_id:
            # Challenger takes the Little Champ title (a champ swap -- the
            # Big Champ's defense streak resets). The champ challenge follows
            # immediately (and again at the end of the queue); the queue
            # purge waits until that challenge resolves.
            result["small_king_id"] = challenger_id
            result["consecutive_bk_wins"] = 0
            result["title_changed"] = True
            result["add_champ_challenges"] = True
        # A successful defense by the Little Champ leaves the streak intact:
        # the same champ still reigns and no swap took place.

    return result
