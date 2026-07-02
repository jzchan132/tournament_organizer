from app.state_machine import resolve_phase2_match

BIG = 1  # big king player id
SMALL = 2  # small king player id
CHALLENGER = 3


def rematch(winner_id, consecutive_bk_wins=0, queue_empty_after_pop=True):
    return resolve_phase2_match(
        big_king_id=BIG,
        small_king_id=SMALL,
        consecutive_bk_wins=consecutive_bk_wins,
        front_entry_type="rematch",
        front_entry_player_id=SMALL,
        winner_id=winner_id,
        queue_empty_after_pop=queue_empty_after_pop,
    )


def challenger_match(winner_id, consecutive_bk_wins=0):
    return resolve_phase2_match(
        big_king_id=BIG,
        small_king_id=SMALL,
        consecutive_bk_wins=consecutive_bk_wins,
        front_entry_type="challenger",
        front_entry_player_id=CHALLENGER,
        winner_id=winner_id,
        queue_empty_after_pop=False,
    )


def test_small_king_beats_big_king_swaps_titles():
    result = rematch(winner_id=SMALL, consecutive_bk_wins=1)

    assert result["match_type"] == "bk_vs_sk"
    assert result["big_king_id"] == SMALL
    assert result["small_king_id"] == BIG
    assert result["title_changed"] is True
    assert result["purge_against_small_king_id"] == BIG
    assert result["consecutive_bk_wins"] == 0
    assert result["queue_empty_warning"] is False
    assert result["record_history_pair"] is None  # BK-vs-SK matches are exempt
    assert result["requeue_rematch_for"] is None
    assert result["phase_complete"] is False


def test_big_king_defends_requeues_rematch_and_streak_increments():
    result = rematch(winner_id=BIG, consecutive_bk_wins=0, queue_empty_after_pop=False)

    assert result["match_type"] == "bk_vs_sk"
    assert result["title_changed"] is False
    assert result["big_king_id"] == BIG
    assert result["small_king_id"] == SMALL
    assert result["consecutive_bk_wins"] == 1
    assert result["requeue_rematch_for"] == SMALL
    # queue had other people waiting, so no warning and no end condition
    assert result["queue_empty_warning"] is False
    assert result["phase_complete"] is False


def test_big_king_defends_with_empty_queue_sets_warning_but_not_end_condition_on_first_win():
    result = rematch(winner_id=BIG, consecutive_bk_wins=0, queue_empty_after_pop=True)

    assert result["consecutive_bk_wins"] == 1
    assert result["queue_empty_warning"] is True
    assert result["phase_complete"] is False
    assert result["ended_reason"] is None


def test_big_king_defends_twice_in_a_row_with_empty_queue_ends_tournament():
    # second consecutive defense, streak already at 1 coming in
    result = rematch(winner_id=BIG, consecutive_bk_wins=1, queue_empty_after_pop=True)

    assert result["consecutive_bk_wins"] == 2
    assert result["queue_empty_warning"] is True
    assert result["phase_complete"] is True
    assert result["ended_reason"] == "queue_exhausted"


def test_challenger_beats_small_king_swaps_up():
    result = challenger_match(winner_id=CHALLENGER, consecutive_bk_wins=1)

    assert result["match_type"] == "challenger_vs_sk"
    assert result["title_changed"] is True
    assert result["small_king_id"] == CHALLENGER
    assert result["big_king_id"] == BIG  # unaffected
    assert result["purge_against_small_king_id"] == CHALLENGER
    assert result["record_history_pair"] == (CHALLENGER, SMALL)
    assert result["consecutive_bk_wins"] == 0  # any challenger match resets the BK streak
    assert result["requeue_rematch_for"] is None
    assert result["phase_complete"] is False


def test_small_king_beats_challenger_records_history_no_title_change():
    result = challenger_match(winner_id=SMALL, consecutive_bk_wins=1)

    assert result["match_type"] == "challenger_vs_sk"
    assert result["title_changed"] is False
    assert result["small_king_id"] == SMALL
    assert result["big_king_id"] == BIG
    assert result["record_history_pair"] == (CHALLENGER, SMALL)
    assert result["consecutive_bk_wins"] == 0
    assert result["purge_against_small_king_id"] is None
