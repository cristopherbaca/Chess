import { Chess } from "../vendor/chess.js";
import { bindConnection } from "./ui/connection.js";
import { Board } from "./board.js";
import { CONFIG } from "./config.js";
import { getCristopherMove, cancelCristopherMove } from "./cristopher.js";
import {
  PIECE_NAMES,
  colorName,
  otherColor,
  toUci,
  pieceSource,
  gameStatus,
  materialSummary,
  undoTurn,
} from "./game.js";
import { avatarMarkup } from "./ui/icons.js";
import { loadSettings, bindSettings } from "./ui/settings.js";
import { ChessClock, formatTime } from "./ui/clock.js";
import { MoveList } from "./ui/moveList.js";
import {
  createTabs,
  positionPromotion,
  dismissOnBackdrop,
} from "./ui/panels.js";
import { soundNotes } from "./ui/sounds.js";

const $ = (id) => document.getElementById(id);
const state = {
  game: new Chess(),
  started: false,
  opponent: "ai",
  humanColor: "w",
  difficulty: "medium",
  orientation: "w",
  selected: null,
  resigned: null,
  pendingPromotion: null,
  busy: false,
  aiError: "",
  requestId: 0,
  muted: false,
  audio: null,
  engineInfo: null,
  aiNotice: "",
  cancelReady: false,
  renderedHistory: "",
  settings: loadSettings(),
  reviewPly: null,
  timeControl: 600,
  timeout: null,
  agreedDraw: false,
  clockHistory: [],
  resultShown: false,
  resultFocus: null,
};
state.muted = !state.settings.sound;
const board = new Board($("board"), {
  onSquare: clickSquare,
  onSelect: selectSquare,
  onDrop: attemptMove,
  canSelect,
  onInteract: unlockAudio,
});
const showTab = createTabs();
const moveList = new MoveList($("move-list"), $("move-scroll"), reviewPosition);
const clock = new ChessClock(renderClocks, expireGame);

function isOver() {
  return (
    Boolean(state.resigned || state.timeout || state.agreedDraw) ||
    state.game.isGameOver()
  );
}
function isAiTurn() {
  return state.opponent === "ai" && state.game.turn() !== state.humanColor;
}
function canPlay() {
  return (
    state.started &&
    !state.busy &&
    !isOver() &&
    !isAiTurn() &&
    !state.pendingPromotion &&
    state.reviewPly === null
  );
}
function canSelect(square) {
  return canPlay() && state.game.get(square)?.color === state.game.turn();
}
function selectSquare(square) {
  if (canSelect(square)) {
    state.selected = square;
    render();
  }
}

function clickSquare(square) {
  if (!canPlay()) return;
  if (square === state.selected) {
    state.selected = null;
    render();
    return;
  }
  if (canSelect(square)) {
    selectSquare(square);
    return;
  }
  if (state.selected) attemptMove(state.selected, square);
}

function attemptMove(from, to) {
  if (!canPlay() || state.game.get(from)?.color !== state.game.turn())
    return false;
  const moves = state.game
    .moves({ square: from, verbose: true })
    .filter((move) => move.to === to);
  if (!moves.length) return false;
  if (moves.some((move) => move.promotion)) {
    state.pendingPromotion = { from, to };
    const options = $("promotion-options");
    options.replaceChildren();
    for (const type of ["q", "r", "b", "n"]) {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-label", `Promote to ${PIECE_NAMES[type]}`);
      const image = document.createElement("img");
      image.src = pieceSource(state.game.turn(), type);
      image.alt = "";
      const label = document.createElement("span");
      label.textContent = PIECE_NAMES[type];
      button.append(image, label);
      button.addEventListener("click", () => {
        const pending = state.pendingPromotion;
        state.pendingPromotion = null;
        $("promotion-dialog").close();
        if (pending) commitMove({ ...pending, promotion: type });
      });
      options.append(button);
    }
    render();
    $("promotion-dialog").showModal();
    positionPromotion($("promotion-dialog"), board.squares.get(to));
    return true;
  }
  commitMove({ from, to });
  return true;
}

function commitMove(move) {
  clock.tick();
  if (isOver()) return;
  const result = state.game.move(move);
  state.selected = null;
  afterMove(result);
  showTab("game");
  render();
  void requestAiMove();
}

function afterMove(move) {
  clock.switchTurn(state.game.turn());
  if (isOver()) clock.stop();
  state.clockHistory[state.game.history().length] = clock.snapshot();
  playSound(move);
}

async function requestAiMove() {
  if (!state.started || !isAiTurn() || isOver() || state.busy) return;
  const requestId = ++state.requestId;
  const fen = state.game.fen();
  state.busy = true;
  state.aiError = "";
  state.aiNotice = "";
  state.cancelReady = false;
  const cancelTimer = setTimeout(() => {
    if (requestId === state.requestId && CONFIG.USE_API) {
      state.cancelReady = true;
      render();
    }
  }, 5000);
  render();
  try {
    const result = await getCristopherMove({
      fen,
      history: state.game.history({ verbose: true }).map(toUci),
      difficulty: state.difficulty,
    });
    // A new game, undo, resignation, or expired clock invalidates the in-flight reply.
    clock.tick();
    if (requestId !== state.requestId || fen !== state.game.fen() || isOver())
      return;
    const move = state.game.move({
      from: result.move.slice(0, 2),
      to: result.move.slice(2, 4),
      ...(result.move[4] ? { promotion: result.move[4] } : {}),
    });
    state.engineInfo = result.info;
    if (!result.info?.placeholder) connection.connected();
    if (result.info?.placeholder && result.info?.fallback) {
      state.aiNotice =
        "API unavailable — the local fallback bot played this move.";
      connection.disconnected();
    }
    afterMove(move);
  } catch (error) {
    if (requestId !== state.requestId) return;
    state.aiError =
      error.code === "cancelled"
        ? error.message
        : `Cristopher lost connection. ${error.message || "Please try again."}`;
    if (["network", "timeout"].includes(error.code)) connection.disconnected();
    else if (error.code !== "cancelled") void connection.refresh();
  } finally {
    clearTimeout(cancelTimer);
    if (requestId === state.requestId) {
      state.busy = false;
      render();
    }
  }
}

function invalidateRequest() {
  state.requestId++;
  cancelCristopherMove();
  state.engineInfo = null;
  state.aiNotice = "";
  state.cancelReady = false;
  state.busy = false;
  state.aiError = "";
  state.selected = null;
  board.cancelDrag();
}

function currentStatus() {
  if (!state.started)
    return {
      title: "Ready to play",
      detail:
        "Choose your opponent and press Play to start the game and clock.",
    };
  if (state.timeout)
    return {
      title: `${colorName(otherColor(state.timeout))} wins`,
      detail: `${colorName(state.timeout)} ran out of time.`,
      over: true,
    };
  if (state.agreedDraw)
    return { title: "Game drawn", detail: "Draw by agreement.", over: true };
  return gameStatus(state.game, state.resigned);
}

function reviewGame() {
  if (state.reviewPly === null) return state.game;
  const game = new Chess();
  for (const move of state.game
    .history({ verbose: true })
    .slice(0, state.reviewPly))
    game.move({
      from: move.from,
      to: move.to,
      ...(move.promotion ? { promotion: move.promotion } : {}),
    });
  return game;
}

function render() {
  const history = state.game.history({ verbose: true });
  const status = currentStatus();
  const displayed = reviewGame();
  const shownHistory =
    state.reviewPly === null ? history : history.slice(0, state.reviewPly);
  board.render({
    game: displayed,
    orientation: state.orientation,
    selected: state.selected,
    lastMove: shownHistory.at(-1),
    enabled: canPlay(),
  });
  $("game-status").textContent = status.title;
  $("status-detail").textContent = state.busy
    ? "Cristopher is thinking…"
    : state.aiError
      ? state.aiError.startsWith("Move request cancelled")
        ? "Request cancelled — retry when you’re ready."
        : "Cristopher lost connection — retry or reconnect."
      : status.detail;
  $("status-icon").textContent = status.over
    ? "⚑"
    : state.game.turn() === "w"
      ? "♔"
      : "♚";
  $("thinking").hidden = !state.busy;
  $("cancel-ai").hidden = !state.busy || !state.cancelReady;
  $("ai-notice").hidden = !state.aiNotice;
  $("ai-notice").textContent = state.aiNotice;
  $("ai-error").hidden = !state.aiError;
  $("error-text").textContent = state.aiError;
  $("undo-button").disabled =
    !history.length ||
    Boolean(state.resigned || state.timeout || state.agreedDraw) ||
    state.reviewPly !== null ||
    (state.opponent === "ai" &&
      state.humanColor === "b" &&
      history.length === 1);
  $("resign-button").disabled =
    !state.started || status.over || state.reviewPly !== null;
  $("draw-button").disabled =
    !state.started ||
    status.over ||
    state.reviewPly !== null ||
    state.opponent === "ai";
  $("draw-button").title =
    state.opponent === "ai"
      ? "Draw offers are available in local games"
      : "Offer a draw";
  $("difficulty-label").textContent =
    state.opponent === "local"
      ? "Local · 2 players"
      : `${state.difficulty[0].toUpperCase()}${state.difficulty.slice(1)}`;
  $("board-mode").textContent =
    `${state.timeControl ? `${state.timeControl / 60} min` : "No clock"} · Casual game`;
  renderPlayer("top-player", otherColor(state.orientation));
  renderPlayer("bottom-player", state.orientation);
  connection.paint();
  renderClocks(clock.value());
  renderHistory(history);
  renderMaterial(displayed);
  for (const button of document.querySelectorAll("[data-action]"))
    button.disabled = $(button.dataset.action).disabled;
  if (status.over) {
    clock.stop();
    if (!state.resultShown) showResult(status);
  } else {
    state.resultShown = false;
    $("result-layer").hidden = true;
  }
}

function renderPlayer(id, color) {
  const element = $(id);
  const ai = state.opponent === "ai" && color !== state.humanColor;
  element.dataset.color = color;
  let chip = element.querySelector(".ai-connection");
  if (!chip) {
    chip = document.createElement("span");
    chip.className = "ai-connection";
    element.querySelector(".player-heading").append(chip);
    const details = document.createElement("details");
    details.className = "engine-info";
    const summary = document.createElement("summary");
    summary.textContent = "Engine info";
    details.append(summary, document.createElement("span"));
    element.querySelector(".player-description").after(details);
  }
  chip.hidden = !ai;
  const details = element.querySelector(".engine-info");
  const info = state.engineInfo;
  details.hidden = !ai || !CONFIG.SHOW_ENGINE_INFO || !info || info.placeholder;
  details.querySelector("span").textContent = info
    ? [
        Number.isFinite(info.eval)
          ? `White: ${info.eval >= 0 ? "+" : ""}${info.eval.toFixed(2)}`
          : null,
        Number.isFinite(info.depth) ? `Depth ${info.depth}` : null,
        Number.isFinite(info.time_ms) ? `${info.time_ms} ms` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  const description = element.querySelector(".player-description");
  description.textContent = ai && state.busy ? "Thinking…" : "";
  if (ai && state.busy) {
    const dots = document.createElement("span");
    dots.className = "thinking";
    dots.setAttribute("aria-hidden", "true");
    dots.innerHTML = "<i></i><i></i><i></i>";
    description.append(dots);
  }
  element.querySelector(".player-color").textContent = colorName(color);
  const avatar = element.querySelector(".avatar");
  avatar.innerHTML = avatarMarkup(ai);
  avatar.classList.toggle("human-avatar", !ai);
  const prefix = color === "w" ? "white" : "black";
  element.querySelector(".captured-pieces").id = `${prefix}-captures`;
  element.querySelector(".material-advantage").id = `${prefix}-material`;
  element.classList.toggle(
    "active-player",
    state.started && state.game.turn() === color && !isOver(),
  );
}

function renderHistory(history) {
  moveList.render(history, state.reviewPly);
  $("empty-moves").hidden = history.length > 0;
  $("move-count").textContent = `${history.length} played`;
  $("tab-move-count").textContent = history.length || "";
  const current = state.reviewPly ?? history.length;
  $("history-first").disabled = $("history-back").disabled = current === 0;
  $("history-next").disabled = $("history-last").disabled =
    current === history.length;
  $("review-indicator").hidden = state.reviewPly === null;
  $("review-indicator").querySelector("span").textContent =
    `Reviewing ${current === 0 ? "starting position" : `move ${Math.ceil(current / 2)} · ${current % 2 ? "White" : "Black"}`}`;
}

function reviewPosition(ply) {
  if (state.pendingPromotion) return;
  $("result-layer").hidden = true;
  const length = state.game.history().length;
  const next = Math.max(0, Math.min(length, ply));
  state.reviewPly = next === length ? null : next;
  state.selected = null;
  board.cancelDrag();
  render();
}

function renderMaterial(game = state.game) {
  const { captured, balance } = materialSummary(game);
  for (const color of ["w", "b"]) {
    const prefix = color === "w" ? "white" : "black";
    const container = $(`${prefix}-captures`);
    container.replaceChildren();
    for (const type of captured[color]) {
      const image = document.createElement("img");
      image.src = pieceSource(otherColor(color), type);
      image.alt = `${colorName(otherColor(color))} ${PIECE_NAMES[type]}`;
      container.append(image);
    }
    const advantage = color === "w" ? balance : -balance;
    container.parentElement.hidden = !captured[color].length && advantage <= 0;
    if (!captured[color].length) container.textContent = "—";
    $(`${prefix}-material`).textContent = advantage > 0 ? `+${advantage}` : "";
    $(`${prefix}-material`).setAttribute(
      "aria-label",
      advantage > 0
        ? `${colorName(color)} is ahead by ${advantage} material points`
        : "",
    );
  }
}

function renderClocks(value) {
  for (const id of ["top-player", "bottom-player"]) {
    const element = $(id);
    const color =
      element.dataset.color ||
      (id === "top-player" ? otherColor(state.orientation) : state.orientation);
    const timer = element.querySelector(".player-clock");
    timer.querySelector("span").textContent = value.seconds
      ? formatTime(value.remaining[color])
      : "∞";
    timer.classList.toggle("running", value.active === color);
    timer.classList.toggle(
      "low-time",
      Boolean(value.seconds && value.remaining[color] < 20000),
    );
    timer.classList.toggle("no-clock", !value.seconds);
    timer.setAttribute(
      "aria-label",
      `${colorName(color)} clock: ${value.seconds ? formatTime(value.remaining[color]) : "No clock"}`,
    );
  }
}

function expireGame(color) {
  if (isOver()) return;
  state.timeout = color;
  state.pendingPromotion = null;
  $("promotion-dialog").close();
  invalidateRequest();
  playSound({});
  showTab("game");
  render();
}

function showResult(status) {
  state.resultShown = true;
  $("resign-dialog").close();
  $("draw-dialog").close();
  state.resultFocus = document.activeElement;
  $("result-title").textContent = status.title.replace("wins", "won");
  $("result-detail").textContent = status.detail;
  const winner = status.title.startsWith("White")
    ? "w"
    : status.title.startsWith("Black")
      ? "b"
      : null;
  $("result-score").textContent =
    winner === "w" ? "1–0" : winner === "b" ? "0–1" : "½–½";
  document.querySelector(".result-emblem").textContent = winner ? "♚" : "½";
  for (const color of ["w", "b"]) {
    const prefix = color === "w" ? "white" : "black";
    const ai = state.opponent === "ai" && color !== state.humanColor;
    $(`result-${prefix}-avatar`).innerHTML = avatarMarkup(ai);
    $(`result-${prefix}-avatar`).classList.toggle("human-avatar", !ai);
    $(`result-${prefix}-name`).textContent = colorName(color);
  }
  $("result-layer").hidden = false;
  $("close-result").focus({ preventScroll: true });
}

function closeResult() {
  $("result-layer").hidden = true;
  if (state.resultFocus?.isConnected)
    state.resultFocus.focus({ preventScroll: true });
}

function unlockAudio() {
  if (state.muted) return;
  try {
    state.audio ||= new (window.AudioContext || window.webkitAudioContext)();
    if (state.audio.state === "suspended")
      void state.audio.resume().catch(() => {});
  } catch {
    /* Audio is optional when the browser cannot provide it. */
  }
}

function playSound(move) {
  if (state.muted || !state.audio || state.audio.state !== "running") return;
  const frequencies = soundNotes(move, {
    over: isOver(),
    check: state.game.isCheck(),
  });
  const start = state.audio.currentTime;
  frequencies.forEach((frequency, index) => {
    const oscillator = state.audio.createOscillator();
    const gain = state.audio.createGain();
    const time = start + index * 0.085;
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, time);
    gain.gain.exponentialRampToValueAtTime(0.1, time + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.12);
    oscillator.connect(gain);
    gain.connect(state.audio.destination);
    oscillator.start(time);
    oscillator.stop(time + 0.13);
    oscillator.onended = () => {
      oscillator.disconnect();
      gain.disconnect();
    };
  });
}

function startGame({ color, opponent, difficulty, time }) {
  invalidateRequest();
  state.game.reset();
  state.started = true;
  state.humanColor =
    color === "random" ? (Math.random() < 0.5 ? "w" : "b") : color;
  state.orientation = state.humanColor;
  state.opponent = opponent;
  connection.sync();
  state.difficulty = difficulty;
  state.timeControl = Number(time);
  state.resigned = null;
  state.timeout = null;
  state.agreedDraw = false;
  state.pendingPromotion = null;
  state.reviewPly = null;
  state.resultShown = false;
  $("result-layer").hidden = true;
  $("promotion-dialog").close();
  clock.start(state.timeControl);
  state.clockHistory = [clock.snapshot()];
  unlockAudio();
  showTab("game");
  render();
  void requestAiMove();
}

$("new-game-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  startGame({
    color: data.get("color"),
    opponent: data.get("opponent"),
    difficulty: $("difficulty").value,
    time: data.get("time"),
  });
});
$("opponent").addEventListener("change", () => {
  const local = $("opponent").value === "local";
  $("difficulty").disabled = local;
  $("difficulty-note").hidden = local;
  document.querySelectorAll("[data-difficulty]").forEach((button) => {
    button.disabled = local;
  });
  document.querySelector(".opponent-field .avatar").innerHTML =
    avatarMarkup(!local);
  connection.sync();
});
for (const button of document.querySelectorAll("[data-difficulty]")) {
  button.addEventListener("click", () => {
    $("difficulty").value = button.dataset.difficulty;
    document
      .querySelectorAll("[data-difficulty]")
      .forEach((item) =>
        item.setAttribute("aria-pressed", String(item === button)),
      );
  });
}
$("undo-button").addEventListener("click", () => {
  if ($("undo-button").disabled) return;
  invalidateRequest();
  undoTurn(state.game, state.opponent, state.humanColor);
  const ply = state.game.history().length;
  clock.restore(
    state.clockHistory[ply] || state.clockHistory[0],
    state.game.turn(),
  );
  state.clockHistory.length = ply + 1;
  state.reviewPly = null;
  state.resultShown = false;
  render();
  void requestAiMove();
});
$("flip-button").addEventListener("click", () => {
  state.orientation = otherColor(state.orientation);
  render();
});
$("resign-button").addEventListener("click", () => {
  const color = state.opponent === "ai" ? state.humanColor : state.game.turn();
  $("resign-description").textContent =
    `${colorName(color)} resigns and ${colorName(otherColor(color))} wins this game.`;
  $("resign-dialog").showModal();
});
$("confirm-resign").addEventListener("click", () => {
  $("resign-dialog").close();
  if (!isOver()) {
    state.resigned =
      state.opponent === "ai" ? state.humanColor : state.game.turn();
    invalidateRequest();
    clock.stop();
    playSound({});
    render();
  }
});
$("draw-button").addEventListener("click", () => $("draw-dialog").showModal());
$("confirm-draw").addEventListener("click", () => {
  $("draw-dialog").close();
  if (state.opponent === "local" && !isOver()) {
    state.agreedDraw = true;
    clock.stop();
    playSound({});
    render();
  }
});
$("retry-button").addEventListener("click", () => {
  void connection.refresh();
  void requestAiMove();
});
$("history-first").addEventListener("click", () => reviewPosition(0));
$("history-back").addEventListener("click", () =>
  reviewPosition((state.reviewPly ?? state.game.history().length) - 1),
);
$("history-next").addEventListener("click", () =>
  reviewPosition((state.reviewPly ?? state.game.history().length) + 1),
);
$("history-last").addEventListener("click", () =>
  reviewPosition(state.game.history().length),
);
$("back-to-live").addEventListener("click", () =>
  reviewPosition(state.game.history().length),
);
$("close-result").addEventListener("click", closeResult);
$("result-new-game").addEventListener("click", () => {
  closeResult();
  showTab("new");
  $("new-game-button").focus();
  document.querySelector(".game-panel").scrollIntoView({ block: "nearest" });
});
$("rematch-button").addEventListener("click", () =>
  startGame({
    color: state.humanColor,
    opponent: state.opponent,
    difficulty: state.difficulty,
    time: state.timeControl,
  }),
);
for (const id of ["settings-button", "reconnect-button"])
  $(id).addEventListener("click", () => $("settings-dialog").showModal());
for (const button of document.querySelectorAll("[data-action]"))
  button.addEventListener("click", () => $(button.dataset.action).click());
document
  .querySelectorAll("[data-close]")
  .forEach((button) =>
    button.addEventListener("click", () => $(button.dataset.close).close()),
  );
bindSettings(state.settings, (settings) => {
  state.muted = !settings.sound;
  if (settings.sound) unlockAudio();
});
function cancelPromotion() {
  state.pendingPromotion = null;
  $("promotion-dialog").close();
  render();
}
$("cancel-promotion").addEventListener("click", cancelPromotion);
$("promotion-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  cancelPromotion();
});
dismissOnBackdrop($("promotion-dialog"), cancelPromotion);
dismissOnBackdrop($("settings-dialog"), () => $("settings-dialog").close());
window.addEventListener("resize", () => {
  if (state.pendingPromotion)
    positionPromotion(
      $("promotion-dialog"),
      board.squares.get(state.pendingPromotion.to),
    );
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || document.querySelector("dialog[open]")) return;
  if (!$("result-layer").hidden) closeResult();
  else {
    state.selected = null;
    board.cancelDrag();
    render();
  }
});
const connection = bindConnection(
  (key) => {
    if (!key || key === "USE_API") {
      const pending = state.busy || Boolean(state.aiError);
      invalidateRequest();
      if (pending && isAiTurn() && !isOver())
        state.aiError = "Connection settings changed. Retry when you’re ready.";
    }
    render();
  },
  {
    isEnabled: () => CONFIG.USE_API && (state.started ? state.opponent : $("opponent").value) === "ai",
    idleLabel: () => (state.started ? state.opponent : $("opponent").value) === "local"
      ? "Local two-player · API inactive"
      : "Offline mode · random bot (no API)",
  },
);
$("cancel-ai").addEventListener("click", cancelCristopherMove);
$("time-control").addEventListener("change", () => {
  if (state.started) return;
  state.timeControl = Number($("time-control").value);
  clock.start(state.timeControl, null);
  state.clockHistory = [clock.snapshot()];
  render();
});
clock.start(state.timeControl, null);
state.clockHistory = [clock.snapshot()];
render();
connection.paint();
