def resolve_phase2_match(
    *,
    big_king_id,
    small_king_id,
    consecutive_bk_wins,
    front_entry_type,
    front_entry_player_id,
    winner_id,
    queue_empty_after_pop,
):
    """Pure decision logic for a single Phase 2 (King of the Hill) match outcome.

    front_entry_type: 'rematch' (the Small King's own challenge against the Big
        King) or 'challenger' (someone else challenging the Small King).
    front_entry_player_id: for 'rematch' this equals small_king_id; for
        'challenger' this is the challenger's player id.
    queue_empty_after_pop: whether the queue is empty once the entry that was
        just played has been removed, before any automatic rematch re-add.

    Returns a dict describing what the DB layer should persist. This function
    touches no database -- it only decides outcomes from plain inputs, which
    is what makes the tricky king-swap/queue/streak rules here testable in
    isolation.
    """
    result = {
        "match_type": "bk_vs_sk" if front_entry_type == "rematch" else "challenger_vs_sk",
        "big_king_id": big_king_id,
        "small_king_id": small_king_id,
        "consecutive_bk_wins": consecutive_bk_wins,
        "queue_empty_warning": False,
        "title_changed": False,
        "record_history_pair": None,
        "purge_against_small_king_id": None,
        "requeue_rematch_for": None,
        "phase_complete": False,
        "ended_reason": None,
    }

    if front_entry_type == "rematch":
        if winner_id == small_king_id:
            # Small King beats Big King: titles swap. Exempt from the
            # one-time-challenge history/limit entirely.
            result["big_king_id"] = small_king_id
            result["small_king_id"] = big_king_id
            result["consecutive_bk_wins"] = 0
            result["title_changed"] = True
            result["purge_against_small_king_id"] = big_king_id
        else:
            # Big King defends: no title change, Small King's rematch
            # automatically goes to the back of the queue.
            result["consecutive_bk_wins"] = consecutive_bk_wins + 1
            result["requeue_rematch_for"] = small_king_id
            if queue_empty_after_pop:
                result["queue_empty_warning"] = True
                if result["consecutive_bk_wins"] >= 2:
                    result["phase_complete"] = True
                    result["ended_reason"] = "queue_exhausted"
    else:
        challenger_id = front_entry_player_id
        # Any challenger match breaks a Big-King-defense streak, since the
        # end condition requires the losses to be back-to-back.
        result["consecutive_bk_wins"] = 0
        result["record_history_pair"] = (challenger_id, small_king_id)
        if winner_id == challenger_id:
            # Challenger beats Small King: swap-up.
            result["small_king_id"] = challenger_id
            result["title_changed"] = True
            result["purge_against_small_king_id"] = challenger_id

    return result
