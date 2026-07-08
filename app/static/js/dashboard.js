let previousCompleted = null;
let audioCtx = null;
let currentState = null;
let refreshNow = null;
let lastRenderSig = null;
let timerEndsAt = null; // ms epoch when the Phase 2 clock hits zero; ticks client-side
let lastPhase = null; // for announcing phase transitions

const BIG_TITLE = "Big Champ";
const SMALL_TITLE = "Little Champ";

const chime = new Audio("/static/sounds/notify.wav");

function playChime() {
    chime.currentTime = 0;
    chime.play().catch(() => {
        // Autoplay blocked or file unavailable -- fall back to a beep.
        try {
            audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
            const o = audioCtx.createOscillator();
            const g = audioCtx.createGain();
            o.connect(g);
            g.connect(audioCtx.destination);
            o.frequency.value = 880;
            g.gain.setValueAtTime(0.15, audioCtx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.4);
            o.start();
            o.stop(audioCtx.currentTime + 0.4);
        } catch (e) {
            // audio unavailable entirely -- not critical
        }
    });
}

function showToast(text, isError) {
    const el = document.createElement("div");
    el.className = "toast" + (isError ? " error" : "");
    el.textContent = text;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

async function postAction(url, body) {
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: body || "",
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || "Something went wrong.", true);
            return false;
        }
        return true;
    } catch (e) {
        showToast("Network error -- try again.", true);
        return false;
    }
}

function allCompletedEntries(state) {
    const entries = [];
    Object.values(state.bracket.rounds).forEach((round) =>
        round.forEach((m) => {
            if (m.winner_id) {
                const loser = m.winner_id === m.player1_id ? m.player2_name : m.player1_name;
                entries.push({ key: `bracket-${m.id}`, winner: m.winner_name, loser });
            }
        })
    );
    state.round_robin.matches.forEach((m) => {
        if (m.winner_id) {
            const loser = m.winner_id === m.player1_id ? m.player2_name : m.player1_name;
            entries.push({ key: `rr-${m.id}`, winner: m.winner_name, loser });
        }
    });
    if (state.phase2) {
        state.phase2.match_log.forEach((m) => {
            const otherId = m.match_type === "bk_vs_sk" ? m.big_king_id : m.challenger_id;
            const otherName = m.match_type === "bk_vs_sk" ? m.big_king_name : m.challenger_name;
            const loser = m.winner_id === otherId ? m.small_king_name : otherName;
            entries.push({ key: `phase2-${m.id}`, winner: m.winner_name, loser });
        });
    }
    return entries;
}

function checkForNewCompletions(state) {
    const entries = allCompletedEntries(state);
    const completed = new Set(entries.map((e) => e.key));
    if (previousCompleted !== null) {
        for (const e of entries) {
            if (!previousCompleted.has(e.key)) {
                playChime();
                showToast(`${e.winner} beat ${e.loser}!`);
            }
        }
    }
    previousCompleted = completed;
}

function checkForPhaseChange(state) {
    if (lastPhase !== null && state.phase !== lastPhase && state.phase2) {
        const bk = state.phase2.big_king.name;
        const sk = state.phase2.small_king.name;
        if (state.phase === "phase2") {
            playChime();
            showToast(`THE GAUNTLET BEGINS! ${bk} enters as ${BIG_TITLE} — ${sk} rises as ${SMALL_TITLE}!`);
        } else if (state.phase === "complete") {
            playChime();
            showToast(endingAnnouncement(state));
        }
    }
    lastPhase = state.phase;
}

function endingAnnouncement(state) {
    const bk = state.phase2.big_king.name;
    if (state.phase2.ended_reason === "timer") {
        return `THAT'S TIME! The final bell sounds — ${bk} walks away as the undisputed ${BIG_TITLE}!`;
    }
    return `IT'S OVER! ${bk} has beaten every champ challenge — the undisputed ${BIG_TITLE}!`;
}

function phase1MatchCard(m, label, kind) {
    if (!m) {
        return `<div class="hero-card empty"><div class="hero-label">${label}</div><div class="hero-players">--</div></div>`;
    }
    return `<div class="hero-card">
        <div class="hero-label">${label}</div>
        <div class="hero-players">${m.player1_name} <span class="vs">vs</span> ${m.player2_name}</div>
        <div class="card-actions">
            <button data-action="result" data-kind="${kind}" data-match="${m.id}" data-winner="${m.player1_id}">${m.player1_name} won</button>
            <button data-action="result" data-kind="${kind}" data-match="${m.id}" data-winner="${m.player2_id}">${m.player2_name} won</button>
        </div>
    </div>`;
}

function undoButton(kind, matchId) {
    return `<button class="undo-btn" data-action="undo" data-kind="${kind}" data-match="${matchId}">Undo</button>`;
}

function renderBracket(state) {
    const names = state.bracket.round_names;
    let html = '<div class="bracket">';
    Object.keys(state.bracket.rounds)
        .sort()
        .forEach((roundNum) => {
            html += `<div class="bracket-round"><h4>${names[roundNum]}</h4>`;
            state.bracket.rounds[roundNum].forEach((m) => {
                html += `<div class="bracket-match${m.winner_id ? " decided" : ""}">`;
                html += `<div class="${m.winner_id && m.winner_id === m.player1_id ? "winner" : ""}">${m.player1_name || "TBD"}</div>`;
                html += `<div class="${m.winner_id && m.winner_id === m.player2_id ? "winner" : ""}">${m.player2_name || "TBD"}</div>`;
                if (m.winner_id && state.phase === "setup") {
                    html += undoButton("bracket", m.id);
                }
                html += "</div>";
            });
            html += "</div>";
        });
    html += "</div>";
    return html;
}

function renderRoundRobin(state) {
    let html =
        '<div class="rr"><div class="rr-standings"><h4>Round Robin Standings</h4><table><tr><th>Player</th><th>Wins</th></tr>';
    state.round_robin.standings.forEach((s) => {
        html += `<tr><td>${s.name}</td><td>${s.wins}</td></tr>`;
    });
    html += "</table></div>";
    html += '<div class="rr-matches"><h4>Round Robin Matches</h4>';
    state.round_robin.matches.forEach((m) => {
        html += `<div class="rr-match${m.winner_id ? " decided" : ""}${m.is_tiebreaker ? " tiebreaker" : ""}">`;
        if (m.is_tiebreaker) html += '<span class="tb-label">Tiebreaker</span> ';
        html += `<span class="${m.winner_id && m.winner_id === m.player1_id ? "winner" : ""}">${m.player1_name}</span> vs `;
        html += `<span class="${m.winner_id && m.winner_id === m.player2_id ? "winner" : ""}">${m.player2_name}</span>`;
        if (m.winner_id && state.phase === "setup") {
            html += " " + undoButton("round_robin", m.id);
        }
        html += "</div>";
    });
    html += "</div></div>";
    return html;
}

function phase1OnDeck(state) {
    // Bracket: the undecided match after the current one, in play order
    // (may still show TBD slots waiting on earlier results).
    const undecided = [];
    Object.keys(state.bracket.rounds)
        .sort()
        .forEach((rn) => {
            state.bracket.rounds[rn].forEach((m) => {
                if (!m.winner_id) undecided.push(m);
            });
        });
    const bCur = state.bracket.next_match;
    let bNext = null;
    if (bCur) {
        const idx = undecided.findIndex((m) => m.id === bCur.id);
        bNext = idx >= 0 ? undecided[idx + 1] : null;
    }

    const rrUndecided = state.round_robin.matches.filter((m) => !m.winner_id);
    const rNext = rrUndecided[1];

    let cards = "";
    if (bNext) {
        cards += onDeckCard(
            "Next on — Bracket",
            `${bNext.player1_name || "TBD"} vs ${bNext.player2_name || "TBD"}`
        );
    }
    if (rNext) {
        cards += onDeckCard(
            rNext.is_tiebreaker ? "Next on — Round Robin (tiebreaker)" : "Next on — Round Robin",
            `${rNext.player1_name} vs ${rNext.player2_name}`
        );
    }
    return cards ? `<div class="ondeck-row">${cards}</div>` : "";
}

function renderStartPhase2(state) {
    if (state.phase !== "setup") return "";
    if (!state.bracket.champion || !state.round_robin.champion) return "";
    return `<div class="phase2-start">
        <p>Phase 1 is complete! Bracket champion: <strong>${state.bracket.champion.name}</strong>,
        round robin champion: <strong>${state.round_robin.champion.name}</strong>.</p>
        <button data-action="start-phase2">Start the Gauntlet</button>
    </div>`;
}

function formatDuration(seconds) {
    if (seconds == null) return "--";
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function onDeckCard(label, text) {
    return `<div class="ondeck-card"><span class="ondeck-label">${label}</span><span class="who">${text}</span></div>`;
}

function phase2HeroCard(state) {
    const p2 = state.phase2;
    if (!p2.next_match) {
        return '<div class="hero-card empty"><div class="hero-label">Current Match</div><div class="hero-players">Queue is empty</div></div>';
    }
    const isRematch = p2.next_match.entry_type === "rematch";
    const challenger = isRematch
        ? { id: p2.small_king.id, name: p2.small_king.name }
        : { id: p2.next_match.player_id, name: p2.next_match.player_name };
    const defender = isRematch
        ? { id: p2.big_king.id, name: p2.big_king.name }
        : { id: p2.small_king.id, name: p2.small_king.name };
    const label = isRematch ? `CURRENT MATCH — CHAMP CHALLENGE` : "Current Match";
    let html = `<div class="hero-card">
        <div class="hero-label">${label}</div>
        <div class="hero-players">${challenger.name} <span class="vs">vs</span> ${defender.name}</div>`;
    if (state.phase === "phase2") {
        html += `<div class="card-actions">
            <button data-action="phase2-result" data-winner="${challenger.id}">${challenger.name} won</button>
            <button data-action="phase2-result" data-winner="${defender.id}">${defender.name} won</button>
        </div>`;
    }
    html += "</div>";
    return html;
}

function phase2OnDeck(state) {
    // Second entry in the queue. Uses titles rather than names for champ
    // challenges, since the current match may change who holds them.
    const next = state.phase2.queue[1];
    if (!next) return "";
    const text = next.entry_type === "rematch"
        ? `Champ Challenge — ${SMALL_TITLE} vs ${BIG_TITLE}`
        : `${next.player_name} challenges the ${SMALL_TITLE}`;
    return `<div class="ondeck-row">${onDeckCard("Next on", text)}</div>`;
}

function renderPhase2(state) {
    const p2 = state.phase2;
    let html = '<div class="hero-cards">';
    html += phase2HeroCard(state);
    html += "</div>";
    html += phase2OnDeck(state);

    if (state.phase === "phase2" && p2.match_log.length === 0) {
        html += `<div class="warning-banner intro">THE GAUNTLET BEGINS! Bracket champion <strong>${p2.big_king.name}</strong> enters as the ${BIG_TITLE} — round robin champion <strong>${p2.small_king.name}</strong> rises as the ${SMALL_TITLE}. Who dares to challenge?</div>`;
    }
    if (p2.queue_empty_warning && state.phase === "phase2") {
        html += `<div class="warning-banner">One champ challenge left — if the ${BIG_TITLE} wins it, the tournament is over!</div>`;
    }
    if (state.phase === "complete") {
        html += `<div class="warning-banner complete">${endingAnnouncement(state)}</div>`;
    }

    html += `<div class="king-status">
        <div class="king-badge big">${BIG_TITLE}<br><strong>${p2.big_king.name}</strong></div>
        <div class="king-badge small">${SMALL_TITLE}<br><strong>${p2.small_king.name}</strong></div>
        <div class="king-badge timer">Time Remaining<br><strong id="p2-timer">${formatDuration(p2.seconds_remaining)}</strong></div>
    </div>`;

    if (p2.can_undo) {
        html += `<div class="undo-row"><button class="undo-btn" data-action="phase2-undo">Undo last Gauntlet result</button></div>`;
    }

    if (state.phase === "phase2") {
        const playerOptions = state.players
            .filter((p) => p.id !== p2.big_king.id && p.id !== p2.small_king.id)
            .map((p) => `<option value="${p.id}">${p.name}</option>`)
            .join("");
        html += `<div class="queue-actions">
            <form id="join-queue-form">
                <select name="player_id">${playerOptions}</select>
                <button type="submit">Join Challenge Queue</button>
            </form>
        </div>`;
    }

    html += '<h4>Challenge Queue</h4><ol class="queue-list">';
    p2.queue.forEach((q) => {
        // Champ challenges are role-based: always the current champs, no
        // matter who held the title when the entry was queued.
        html += q.entry_type === "rematch"
            ? `<li>Champ Challenge — ${p2.small_king.name} vs ${p2.big_king.name}</li>`
            : `<li>${q.player_name}</li>`;
    });
    if (p2.queue.length === 0) html += "<li>Empty</li>";
    html += "</ol>";

    html += renderRoster(state);

    return html;
}

function renderRoster(state) {
    // player id -> map of defeated-name -> count, built from the phase 2 log
    const defeated = new Map(state.players.map((p) => [p.id, new Map()]));
    state.phase2.match_log.forEach((m) => {
        const otherId = m.match_type === "bk_vs_sk" ? m.big_king_id : m.challenger_id;
        const otherName = m.match_type === "bk_vs_sk" ? m.big_king_name : m.challenger_name;
        const loserName = m.winner_id === m.small_king_id ? otherName : m.small_king_name;
        const wins = defeated.get(m.winner_id);
        if (wins) wins.set(loserName, (wins.get(loserName) || 0) + 1);
    });

    let html = '<h4>Gauntlet Roster (who beat who)</h4><table class="roster-table">';
    html += "<tr><th>Player</th><th>Has defeated</th></tr>";
    state.players.forEach((p) => {
        const wins = defeated.get(p.id);
        const names = [...wins.entries()]
            .map(([name, count]) => (count > 1 ? `${name} ×${count}` : name))
            .join(", ");
        html += `<tr><td>${p.name}</td><td>${names || "—"}</td></tr>`;
    });
    html += "</table>";
    return html;
}

function wireQueueForms() {
    const joinForm = document.getElementById("join-queue-form");
    if (joinForm) {
        joinForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const playerId = joinForm.querySelector('select[name="player_id"]').value;
            if (await postAction("/api/queue/join", `player_id=${playerId}`)) refreshNow();
        });
    }
}

function updateTimerDisplay() {
    const el = document.getElementById("p2-timer");
    if (!el || timerEndsAt === null) return;
    el.textContent = formatDuration((timerEndsAt - Date.now()) / 1000);
}

function render(state) {
    currentState = state;
    checkForNewCompletions(state);
    checkForPhaseChange(state);

    // Re-sync the client-side clock on every poll; it ticks locally between polls.
    if (state.phase2 && state.phase2.seconds_remaining != null) {
        timerEndsAt = Date.now() + state.phase2.seconds_remaining * 1000;
    } else {
        timerEndsAt = null;
    }

    // Skip the DOM rebuild when nothing but the clock changed -- this keeps
    // dropdown selections and scroll position stable across polls.
    const sig = JSON.stringify(state, (k, v) => (k === "seconds_remaining" ? undefined : v));
    if (sig === lastRenderSig) {
        updateTimerDisplay();
        return;
    }
    lastRenderSig = sig;

    const root = document.getElementById("dashboard-root");
    const prevSelect = root.querySelector('#join-queue-form select');
    const prevSelectValue = prevSelect ? prevSelect.value : null;
    let html = "";

    if (state.phase === "setup" || state.phase === "phase1") {
        html += renderStartPhase2(state);
        const rrNext = state.round_robin.next_match;
        html += '<div class="hero-cards">';
        html += phase1MatchCard(state.bracket.next_match, "Current Match — Bracket", "bracket");
        html += phase1MatchCard(
            rrNext,
            rrNext && rrNext.is_tiebreaker
                ? "Current Match — Round Robin TIEBREAKER"
                : "Current Match — Round Robin",
            "round_robin"
        );
        html += "</div>";
        html += phase1OnDeck(state);
        html += renderBracket(state);
        html += renderRoundRobin(state);
    } else if (state.phase2) {
        html += renderPhase2(state);
    } else {
        html += `<p>Phase: ${state.phase}</p>`;
    }

    root.innerHTML = html;
    wireQueueForms();
    updateTimerDisplay();

    // Restore the challenger dropdown choice the rebuild just wiped out.
    if (prevSelectValue !== null) {
        const sel = root.querySelector('#join-queue-form select');
        if (sel && [...sel.options].some((o) => o.value === prevSelectValue)) {
            sel.value = prevSelectValue;
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    refreshNow = startPolling("/api/state", render, 3000);
    setInterval(updateTimerDisplay, 1000);

    document.getElementById("dashboard-root").addEventListener("click", async (e) => {
        const btn = e.target.closest("button[data-action]");
        if (!btn) return;
        const action = btn.dataset.action;
        let ok = false;

        if (action === "result") {
            ok = await postAction(
                `/api/${btn.dataset.kind}/match/${btn.dataset.match}/result`,
                `winner_id=${btn.dataset.winner}`
            );
        } else if (action === "undo") {
            ok = await postAction(`/api/${btn.dataset.kind}/match/${btn.dataset.match}/undo`);
        } else if (action === "phase2-result") {
            ok = await postAction("/api/phase2/result", `winner_id=${btn.dataset.winner}`);
        } else if (action === "phase2-undo") {
            if (confirm("Undo the last Gauntlet result?")) {
                ok = await postAction("/api/phase2/undo");
            }
        } else if (action === "start-phase2") {
            if (confirm("Start the Gauntlet? Phase 1 results will be locked.")) {
                ok = await postAction("/api/phase2/start");
            }
        }

        if (ok) refreshNow();
    });
});
