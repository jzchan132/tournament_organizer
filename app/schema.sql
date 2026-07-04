CREATE TABLE IF NOT EXISTS tournament_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    phase TEXT NOT NULL DEFAULT 'setup',
    big_king_id INTEGER REFERENCES players(id),
    small_king_id INTEGER REFERENCES players(id),
    phase2_started_at TEXT,
    consecutive_bk_wins INTEGER NOT NULL DEFAULT 0,
    queue_empty_warning INTEGER NOT NULL DEFAULT 0,
    ended_reason TEXT,
    -- Total Phase 2 length; organizer-adjustable (add time / set remaining).
    phase2_duration_seconds INTEGER NOT NULL DEFAULT 7200
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    in_bracket INTEGER NOT NULL DEFAULT 0,
    in_round_robin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bracket_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round INTEGER NOT NULL,
    position INTEGER NOT NULL,
    player1_id INTEGER REFERENCES players(id),
    player2_id INTEGER REFERENCES players(id),
    winner_id INTEGER REFERENCES players(id),
    next_match_id INTEGER REFERENCES bracket_matches(id),
    next_match_slot INTEGER,
    UNIQUE(round, position)
);

CREATE TABLE IF NOT EXISTS round_robin_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player1_id INTEGER NOT NULL REFERENCES players(id),
    player2_id INTEGER NOT NULL REFERENCES players(id),
    winner_id INTEGER REFERENCES players(id),
    -- Tiebreaker matches are generated when regular play ends tied for first;
    -- they decide the champion but don't count toward the standings.
    is_tiebreaker INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS challenge_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position INTEGER NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('challenger', 'rematch')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS phase2_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at TEXT NOT NULL DEFAULT (datetime('now')),
    match_type TEXT NOT NULL CHECK (match_type IN ('bk_vs_sk', 'challenger_vs_sk')),
    big_king_id INTEGER NOT NULL REFERENCES players(id),
    small_king_id INTEGER NOT NULL REFERENCES players(id),
    challenger_id INTEGER REFERENCES players(id),
    winner_id INTEGER NOT NULL REFERENCES players(id)
);

CREATE TABLE IF NOT EXISTS challenger_history (
    challenger_id INTEGER NOT NULL REFERENCES players(id),
    small_king_id INTEGER NOT NULL REFERENCES players(id),
    PRIMARY KEY (challenger_id, small_king_id)
);

-- Single-slot snapshot of Phase 2 state taken just before each match is
-- resolved, so a mis-clicked result can be undone (one level of undo).
CREATE TABLE IF NOT EXISTS phase2_undo (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    snapshot TEXT NOT NULL
);

INSERT OR IGNORE INTO tournament_state (id, phase) VALUES (1, 'setup');
