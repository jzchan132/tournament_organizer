from app.state_machine import resolve_phase2_match

BIG = 1  # big champ player id (db keeps 'big_king' naming)
SMALL = 2  # little champ player id
CHALLENGER = 3


def champ_challenge(winner_id, consecutive_bk_wins=0, queue_empty_after_pop=True):
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


def test_little_champ_beats_big_champ_swaps_titles():
    result = champ_challenge(winner_id=SMALL, consecutive_bk_wins=1)

    assert result["match_type"] == "bk_vs_sk"
    assert result["big_king_id"] == SMALL
    assert result["small_king_id"] == BIG
    assert result["title_changed"] is True
    # voiding happens against whoever holds Little Champ AFTER the challenge
    assert result["purge_against_small_king_id"] == BIG
    assert result["consecutive_bk_wins"] == 0
    assert result["record_history_pair"] is None  # champ challenges are exempt
    assert result["add_champ_challenges"] is False  # swap doesn't auto-queue
    assert result["phase_complete"] is False


def test_big_champ_defends_increments_streak_and_purges_no_requeue():
    result = champ_challenge(winner_id=BIG, consecutive_bk_wins=0, queue_empty_after_pop=False)

    assert result["title_changed"] is False
    assert result["big_king_id"] == BIG
    assert result["small_king_id"] == SMALL
    assert result["consecutive_bk_wins"] == 1
    # Little Champ kept the title -- purge those who already challenged them
    assert result["purge_against_small_king_id"] == SMALL
    # no automatic re-queue anymore
    assert result["add_champ_challenges"] is False
    assert result["phase_complete"] is False


def test_first_defense_with_empty_queue_does_not_end():
    result = champ_challenge(winner_id=BIG, consecutive_bk_wins=0, queue_empty_after_pop=True)

    assert result["consecutive_bk_wins"] == 1
    assert result["phase_complete"] is False
    assert result["ended_reason"] is None


def test_second_consecutive_defense_with_empty_queue_ends_tournament():
    result = champ_challenge(winner_id=BIG, consecutive_bk_wins=1, queue_empty_after_pop=True)

    assert result["consecutive_bk_wins"] == 2
    assert result["phase_complete"] is True
    assert result["ended_reason"] == "queue_exhausted"


def test_second_consecutive_defense_with_people_waiting_does_not_end():
    result = champ_challenge(winner_id=BIG, consecutive_bk_wins=1, queue_empty_after_pop=False)

    assert result["consecutive_bk_wins"] == 2
    assert result["phase_complete"] is False


def test_challenger_takes_title_queues_champ_challenges_without_purging():
    result = challenger_match(winner_id=CHALLENGER, consecutive_bk_wins=1)

    assert result["match_type"] == "challenger_vs_sk"
    assert result["title_changed"] is True
    assert result["small_king_id"] == CHALLENGER
    assert result["big_king_id"] == BIG  # unaffected
    # purge is deferred until the champ challenge resolves
    assert result["purge_against_small_king_id"] is None
    assert result["add_champ_challenges"] is True
    assert result["record_history_pair"] == (CHALLENGER, SMALL)
    assert result["consecutive_bk_wins"] == 0  # challenger match resets the streak
    assert result["phase_complete"] is False


def test_little_champ_beats_challenger_records_history_no_title_change():
    result = challenger_match(winner_id=SMALL, consecutive_bk_wins=1)

    assert result["match_type"] == "challenger_vs_sk"
    assert result["title_changed"] is False
    assert result["small_king_id"] == SMALL
    assert result["big_king_id"] == BIG
    assert result["record_history_pair"] == (CHALLENGER, SMALL)
    assert result["consecutive_bk_wins"] == 0
    assert result["purge_against_small_king_id"] is None
    assert result["add_champ_challenges"] is False
