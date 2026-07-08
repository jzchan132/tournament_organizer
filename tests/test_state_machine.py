from app.state_machine import resolve_phase2_match

BIG = 1  # big champ player id (db keeps 'big_king' naming)
SMALL = 2  # little champ player id
CHALLENGER = 3


def champ_challenge(winner_id, consecutive_bk_wins=0):
    return resolve_phase2_match(
        big_king_id=BIG,
        small_king_id=SMALL,
        consecutive_bk_wins=consecutive_bk_wins,
        front_entry_type="rematch",
        front_entry_player_id=SMALL,
        winner_id=winner_id,
    )


def challenger_match(winner_id, consecutive_bk_wins=0):
    return resolve_phase2_match(
        big_king_id=BIG,
        small_king_id=SMALL,
        consecutive_bk_wins=consecutive_bk_wins,
        front_entry_type="challenger",
        front_entry_player_id=CHALLENGER,
        winner_id=winner_id,
    )


def test_little_champ_beats_big_champ_swaps_titles_and_queues_bottom_challenge():
    result = champ_challenge(winner_id=SMALL, consecutive_bk_wins=1)

    assert result["match_type"] == "bk_vs_sk"
    assert result["big_king_id"] == SMALL
    assert result["small_king_id"] == BIG
    assert result["title_changed"] is True
    # voiding happens against whoever holds Little Champ AFTER the challenge
    assert result["purge_against_small_king_id"] == BIG
    assert result["consecutive_bk_wins"] == 0  # champ swap resets the streak
    assert result["record_history_pair"] is None  # champ challenges are exempt
    # the demoted champ's rematch goes to the back of the line
    assert result["add_champ_challenge_bottom"] is True
    assert result["add_champ_challenges"] is False
    assert result["phase_complete"] is False


def test_big_champ_first_defense_starts_streak():
    result = champ_challenge(winner_id=BIG, consecutive_bk_wins=0)

    assert result["title_changed"] is False
    assert result["big_king_id"] == BIG
    assert result["small_king_id"] == SMALL
    assert result["consecutive_bk_wins"] == 1
    # Little Champ kept the title -- purge those who already challenged them
    assert result["purge_against_small_king_id"] == SMALL
    assert result["add_champ_challenge_bottom"] is False  # no auto re-queue on defense
    assert result["phase_complete"] is False


def test_second_defense_against_same_reigning_champ_ends_tournament():
    result = champ_challenge(winner_id=BIG, consecutive_bk_wins=1)

    assert result["consecutive_bk_wins"] == 2
    assert result["phase_complete"] is True
    assert result["ended_reason"] == "queue_exhausted"


def test_challenger_takeover_queues_champ_challenges_and_resets_streak():
    result = challenger_match(winner_id=CHALLENGER, consecutive_bk_wins=1)

    assert result["match_type"] == "challenger_vs_sk"
    assert result["title_changed"] is True
    assert result["small_king_id"] == CHALLENGER
    assert result["big_king_id"] == BIG  # unaffected
    # purge is deferred until the champ challenge resolves
    assert result["purge_against_small_king_id"] is None
    assert result["add_champ_challenges"] is True
    assert result["record_history_pair"] == (CHALLENGER, SMALL)
    # a takeover is a champ swap -- the defense streak resets
    assert result["consecutive_bk_wins"] == 0
    assert result["phase_complete"] is False


def test_little_champ_defending_a_challenger_keeps_the_streak():
    result = challenger_match(winner_id=SMALL, consecutive_bk_wins=1)

    assert result["match_type"] == "challenger_vs_sk"
    assert result["title_changed"] is False
    assert result["small_king_id"] == SMALL
    assert result["big_king_id"] == BIG
    assert result["record_history_pair"] == (CHALLENGER, SMALL)
    # same champ still reigns, no swap -- the Big Champ's streak survives
    assert result["consecutive_bk_wins"] == 1
    assert result["purge_against_small_king_id"] is None
    assert result["add_champ_challenges"] is False
    assert result["add_champ_challenge_bottom"] is False
