function startPolling(url, onData, intervalMs) {
    async function tick() {
        try {
            const res = await fetch(url, { cache: "no-store" });
            if (res.ok) {
                onData(await res.json());
            }
        } catch (e) {
            // network hiccup on the LAN -- just try again next tick
        }
    }
    tick();
    setInterval(tick, intervalMs || 3000);
    return tick; // callers can invoke this for an immediate refresh after an action
}
