from app.state_machine import resolve_phase2_match

BIG = 1  # big champ player id (db keeps 'big_king' naming)
SMALL = 2  # little champ player id
CHALLENGER = 3


def champ_challenge(winner_id, remaining_champ_challenges=1):
    return resolve_phase2_match(
        big_king_id=BIG,
        small_king_id=SMALL,
        front_entry_type="rematch",
        front_entry_player_id=SMALL,
        winner_id=winner_id,
        remaining_champ_challenges=remaining_champ_challenges,
    )


def challenger_match(winner_id):
    return resolve_phase2_match(
        big_king_id=BIG,
        small_king_id=SMALL,
        front_entry_type="challenger",
        front_entry_player_id=CHALLENGER,
        winner_id=winner_id,
        remaining_champ_challenges=1,
    )


def test_little_champ_beats_big_champ_swaps_titles_and_queues_bottom_challenge():
    result = champ_challenge(winner_id=SMALL)

    assert result["match_type"] == "bk_vs_sk"
    assert result["big_king_id"] == SMALL
    assert result["small_king_id"] == BIG
    assert result["title_changed"] is True
    # voiding happens against whoever holds Little Champ AFTER the challenge
    assert result["purge_against_small_king_id"] == BIG
    assert result["record_history_pair"] is None  # champ challenges are exempt
    # the demoted champ's rematch goes to the back of the line
    assert result["add_champ_challenge_bottom"] is True
    assert result["add_champ_challenges"] is False
    assert result["phase_complete"] is False


def test_big_champ_defense_with_challenges_left_continues():
    result = champ_challenge(winner_id=BIG, remaining_champ_challenges=1)

    assert result["title_changed"] is False
    assert result["big_king_id"] == BIG
    assert result["small_king_id"] == SMALL
    # Little Champ kept the title -- purge those who already challenged them
    assert result["purge_against_small_king_id"] == SMALL
    assert result["add_champ_challenge_bottom"] is False  # no re-queue on defense
    assert result["phase_complete"] is False


def test_big_champ_defending_the_last_challenge_ends_tournament():
    result = champ_challenge(winner_id=BIG, remaining_champ_challenges=0)

    assert result["phase_complete"] is True
    assert result["ended_reason"] == "queue_exhausted"


def test_challenger_takeover_queues_fresh_champ_challenge_pair():
    result = challenger_match(winner_id=CHALLENGER)

    assert result["match_type"] == "challenger_vs_sk"
    assert result["title_changed"] is True
    assert result["small_king_id"] == CHALLENGER
    assert result["big_king_id"] == BIG  # unaffected
    # purge is deferred until the champ challenge resolves
    assert result["purge_against_small_king_id"] is None
    assert result["add_champ_challenges"] is True
    assert result["record_history_pair"] == (CHALLENGER, SMALL)
    assert result["phase_complete"] is False


def test_little_champ_defending_a_challenger_changes_nothing_structural():
    result = challenger_match(winner_id=SMALL)

    assert result["match_type"] == "challenger_vs_sk"
    assert result["title_changed"] is False
    assert result["small_king_id"] == SMALL
    assert result["big_king_id"] == BIG
    assert result["record_history_pair"] == (CHALLENGER, SMALL)
    assert result["purge_against_small_king_id"] is None
    assert result["add_champ_challenges"] is False
    assert result["add_champ_challenge_bottom"] is False
    assert result["phase_complete"] is False
