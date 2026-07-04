// Landing-page lobby: lists other sessions discovered on the LAN and joins
// one via a real form POST so the server can stop advertising before the
// browser navigates to the host's dashboard.
document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("lan-sessions");
    if (!root) return;

    function joinSession(url) {
        const form = document.createElement("form");
        form.method = "post";
        form.action = "/session/join";
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "url";
        input.value = url;
        form.appendChild(input);
        document.body.appendChild(form);
        form.submit();
    }

    function render(sessions) {
        if (!sessions.length) {
            root.innerHTML = '<p class="hint">No other sessions found yet.</p>';
            return;
        }
        let html = '<table class="saves-table"><tr><th>Session</th><th>Status</th><th></th></tr>';
        sessions.forEach((s) => {
            html += `<tr>
                <td>${s.name}</td>
                <td>${s.phase} — ${s.players} players</td>
                <td><button class="btn-ember" data-join="${s.url}">Join</button></td>
            </tr>`;
        });
        html += "</table>";
        root.innerHTML = html;
    }

    root.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-join]");
        if (!btn) return;
        if (confirm("Join this session? This laptop will switch to the host's dashboard.")) {
            joinSession(btn.dataset.join);
        }
    });

    async function poll() {
        try {
            const res = await fetch("/api/sessions", { cache: "no-store" });
            if (res.ok) render(await res.json());
        } catch (e) {
            // transient; keep polling
        }
    }

    poll();
    setInterval(poll, 4000);
});
