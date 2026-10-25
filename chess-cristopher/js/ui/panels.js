export function createTabs() {
  const tabs = [
    document.getElementById("new-game-button"),
    document.getElementById("game-tab"),
  ];
  const showTab = (name) => {
    for (const tab of tabs) {
      const active =
        tab.id === (name === "new" ? "new-game-button" : "game-tab");
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      document.getElementById(tab.getAttribute("aria-controls")).hidden =
        !active;
    }
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => showTab(index ? "game" : "new"));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      const next =
        event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - index;
      showTab(next ? "game" : "new");
      tabs[next].focus();
    });
  });
  return showTab;
}

export function positionPromotion(dialog, square) {
  const rect = square.getBoundingClientRect();
  const board = square.parentElement.getBoundingClientRect();
  const height = rect.height * 4 + (innerWidth < 600 ? 44 : 28);
  const top =
    rect.top < board.top + board.height / 2 ? rect.top : rect.bottom - height;
  dialog.style.setProperty("--promotion-size", `${rect.width}px`);
  dialog.style.left = `${Math.min(innerWidth - rect.width, Math.max(0, rect.left))}px`;
  dialog.style.top = `${Math.max(4, Math.min(innerHeight - height - 4, top))}px`;
}

export function dismissOnBackdrop(dialog, close) {
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (
      event.clientX < rect.left ||
      event.clientX > rect.right ||
      event.clientY < rect.top ||
      event.clientY > rect.bottom
    )
      close();
  });
}
