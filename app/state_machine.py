def resolve_phase2_match(
    *,
    big_king_id,
    small_king_id,
    front_entry_type,
    front_entry_player_id,
    winner_id,
    remaining_champ_challenges,
):
    """Pure decision logic for a single Gauntlet match outcome.

    Naming note: db/internal names keep the original king terminology
    (big_king = Big Champ, small_king = Little Champ, entry_type
    'rematch' = a champ challenge) so existing saves stay loadable.

    front_entry_type: 'rematch' (a champ challenge -- whoever is CURRENTLY
        Little Champ challenges the Big Champ; entries are role-based, so a
        title swap never invalidates one) or 'challenger' (someone from the
        queue challenging the Little Champ).
    remaining_champ_challenges: how many champ-challenge entries are still
        queued after the entry being resolved was removed.

    Win condition: the Big Champ wins by defending ALL pending champ
    challenges -- i.e. winning a champ challenge when it's the last one
    queued. Champ challenges are created in pairs (top + bottom) when the
    Gauntlet starts and whenever a challenger takes the Little Champ title,
    and singly at the bottom on a champ swap, so one is always pending
    until the tournament ends.

    Returns a dict describing what the DB layer should persist. This touches
    no database -- it only decides outcomes from plain inputs, which is what
    makes the champ-swap/queue rules testable in isolation.
    """
    result = {
        "match_type": "bk_vs_sk" if front_entry_type == "rematch" else "challenger_vs_sk",
        "big_king_id": big_king_id,
        "small_king_id": small_king_id,
        "title_changed": False,
        "record_history_pair": None,
        # Voiding is deferred until a champ challenge resolves, because the
        # champ challenge right after a new Little Champ is crowned can swap
        # the titles again -- only then is it known who challengers face.
        "purge_against_small_king_id": None,
        # Challenger takeover: champ challenges are queued at the top
        # (immediate title shot) and bottom (one more after the queue).
        "add_champ_challenges": False,
        # Champ swap: the demoted champ's next shot goes to the bottom only.
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
            result["title_changed"] = True
            result["purge_against_small_king_id"] = big_king_id
            result["add_champ_challenge_bottom"] = True
        else:
            # Big Champ defends. If that was the last pending champ
            # challenge, every challenge has been beaten -- tournament over.
            result["purge_against_small_king_id"] = small_king_id
            if remaining_champ_challenges == 0:
                result["phase_complete"] = True
                result["ended_reason"] = "queue_exhausted"
    else:
        challenger_id = front_entry_player_id
        result["record_history_pair"] = (challenger_id, small_king_id)
        if winner_id == challenger_id:
            # Challenger takes the Little Champ title. A fresh champ
            # challenge pair follows (top + bottom); the queue purge waits
            # until the top challenge resolves.
            result["small_king_id"] = challenger_id
            result["title_changed"] = True
            result["add_champ_challenges"] = True

    return result
