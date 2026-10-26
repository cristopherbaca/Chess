export class MoveList {
  constructor(list, scroll, onReview) {
    this.list = list;
    this.scroll = scroll;
    this.key = null;
    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-ply]");
      if (button) onReview(Number(button.dataset.ply));
    });
  }

  render(history, reviewPly) {
    const key = `${history.map((move) => move.san).join(" ")}:${reviewPly}`;
    if (this.key === key) return;
    this.key = key;
    this.list.replaceChildren();
    const active = reviewPly ?? history.length;
    for (let index = 0; index < history.length; index += 2) {
      const row = document.createElement("tr");
      const number = document.createElement("th");
      number.scope = "row";
      number.textContent = `${index / 2 + 1}.`;
      row.append(number);
      for (const offset of [0, 1]) {
        const cell = document.createElement("td");
        const move = history[index + offset];
        if (move) {
          const button = document.createElement("button");
          button.textContent = move.san;
          button.dataset.ply = index + offset + 1;
          button.setAttribute(
            "aria-label",
            `Review move ${index / 2 + 1}, ${offset ? "Black" : "White"}: ${move.san}`,
          );
          if (index + offset + 1 === active) {
            button.className = "latest-move";
            button.setAttribute("aria-current", "step");
          }
          cell.append(button);
        }
        row.append(cell);
      }
      this.list.append(row);
    }
    if (reviewPly === null) this.scroll.scrollTop = this.scroll.scrollHeight;
    else
      this.list
        .querySelector(".latest-move")
        ?.scrollIntoView({ block: "nearest" });
  }
}
