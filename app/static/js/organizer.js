// Drag-and-drop seeding for the bracket. The list order IS the seed order:
// item 1 plays item 2, item 3 plays item 4, etc. On submit, the current
// order is written into hidden "seed" inputs.
document.addEventListener("DOMContentLoaded", () => {
    const list = document.getElementById("seed-list");
    const form = document.getElementById("seed-form");
    if (!list || !form) return;

    let dragged = null;

    list.addEventListener("dragstart", (e) => {
        const li = e.target.closest("li[data-player-id]");
        if (!li) return;
        dragged = li;
        li.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
    });

    list.addEventListener("dragend", () => {
        if (dragged) dragged.classList.remove("dragging");
        dragged = null;
        renumber();
    });

    list.addEventListener("dragover", (e) => {
        if (!dragged) return;
        e.preventDefault();
        const over = e.target.closest("li[data-player-id]");
        if (!over || over === dragged) return;
        const rect = over.getBoundingClientRect();
        const before = e.clientY < rect.top + rect.height / 2;
        list.insertBefore(dragged, before ? over : over.nextSibling);
    });

    function renumber() {
        list.querySelectorAll("li[data-player-id] .seed-num").forEach((el, i) => {
            el.textContent = i + 1;
        });
    }

    form.addEventListener("submit", () => {
        form.querySelectorAll('input[name="seed"]').forEach((el) => el.remove());
        list.querySelectorAll("li[data-player-id]").forEach((li) => {
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = "seed";
            input.value = li.dataset.playerId;
            form.appendChild(input);
        });
    });
});
