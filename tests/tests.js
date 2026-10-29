import { Chess } from "../vendor/chess.js";
import { CONFIG, normalizeApiUrl, hasMixedContent } from "../js/config.js?v=engine-ui-3";
import {
  getCristopherMove,
  checkCristopherHealth,
  checkHealth,
  cancelCristopherMove,
  CristopherError,
} from "../js/cristopher.js?v=engine-ui-3";
import { gameStatus, materialSummary, toUci, undoTurn } from "../js/game.js";
import { ChessClock, formatTime } from "../js/ui/clock.js";

const suiteConfig = { ...CONFIG };
Object.assign(CONFIG, {
  ENGINE: "cristopher",
  USE_API: false,
  API_URL: "http://localhost:8000",
  AUTO_FALLBACK: false,
});
const results = [];
const assert = (condition, message = "Assertion failed") => {
  if (!condition) throw new Error(message);
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function test(name, run) {
  const item = document.createElement("li");
  try {
    await run();
    item.className = "pass";
    item.textContent = `PASS — ${name}`;
    results.push({ name, pass: true });
  } catch (error) {
    item.className = "fail";
    item.textContent = `FAIL — ${name}: ${error.message}`;
    results.push({ name, pass: false, error: error.message });
  }
  document.getElementById("results").append(item);
}
async function rejects(run, message) {
  try {
    await run();
  } catch (error) {
    assert(error.message.includes(message), error.message);
    return;
  }
  throw new Error("Expected rejection");
}
async function until(predicate, description) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await sleep(25);
  }
  throw new Error(`Timed out: ${description}`);
}

await test("Scholar’s mate and winner", () => {
  const game = new Chess();
  ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"].forEach((move) =>
    game.move(move),
  );
  assert(game.isCheckmate());
  assert(gameStatus(game).title === "White wins");
});
await test("Both colors can castle on either side", () => {
  for (const color of ["w", "b"])
    for (const move of ["O-O", "O-O-O"]) {
      const game = new Chess(`r3k2r/8/8/8/8/8/8/R3K2R ${color} KQkq - 0 1`);
      const result = game.move(move);
      const rank = color === "w" ? "1" : "8";
      assert(game.get(`${move === "O-O" ? "g" : "c"}${rank}`).type === "k");
      assert(game.get(`${move === "O-O" ? "f" : "d"}${rank}`).type === "r");
      assert(result.isKingsideCastle() || result.isQueensideCastle());
    }
});
await test("Castling through check is forbidden", () => {
  const game = new Chess("4kr2/8/8/8/8/8/8/4K2R w K - 0 1");
  assert(!game.moves().includes("O-O"));
});
await test("En passant removes and counts the captured pawn", () => {
  const game = new Chess();
  ["e4", "a6", "e5", "d5", "exd6"].forEach((move) => game.move(move));
  assert(!game.get("d5") && game.get("d6").color === "w");
  assert(materialSummary(game).captured.w.join("") === "p");
  assert(materialSummary(game).balance === 1);
});
await test("All four promotions and promotion UCI", () => {
  for (const type of ["q", "r", "b", "n"]) {
    const game = new Chess("7k/P7/8/8/8/8/8/7K w - - 0 1");
    const move = game.move({ from: "a7", to: "a8", promotion: type });
    assert(game.get("a8").type === type && toUci(move) === `a7a8${type}`);
  }
});
await test("Stalemate, repetition, insufficient material, and 50-move draws", () => {
  assert(
    gameStatus(new Chess("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")).detail ===
      "Stalemate",
  );
  assert(
    gameStatus(new Chess("7k/8/6K1/8/8/8/8/8 w - - 0 1")).detail ===
      "Insufficient material",
  );
  assert(
    gameStatus(new Chess("7k/8/6K1/8/8/8/R7/8 w - - 100 51")).detail ===
      "50-move rule",
  );
  const game = new Chess();
  ["Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8"].forEach((move) =>
    game.move(move),
  );
  assert(gameStatus(game).detail === "Threefold repetition");
});
await test("Undo a completed AI round, an unanswered move, and a Black human round", () => {
  const game = new Chess();
  game.move("e4");
  game.move("e5");
  undoTurn(game, "ai", "w");
  assert(game.history().length === 0);
  game.move("e4");
  undoTurn(game, "ai", "w");
  assert(game.history().length === 0);
  game.move("e4");
  game.move("e5");
  game.move("Nf3");
  undoTurn(game, "ai", "b");
  assert(game.history().length === 1 && game.turn() === "b");
});
await test("Placeholder returns a legal UCI move after its delay", async () => {
  const game = new Chess();
  const started = performance.now();
  const result = await getCristopherMove({
    fen: game.fen(),
    history: [],
    difficulty: "hard",
  });
  assert(game.moves({ verbose: true }).map(toUci).includes(result.move));
  assert(performance.now() - started >= 390);
});

const originalConfig = { ...CONFIG };
const originalFetch = globalThis.fetch;
CONFIG.USE_API = true;
CONFIG.EXTRA_HEADERS = { "ngrok-skip-browser-warning": "true" };
const input = { fen: new Chess().fen(), history: [], difficulty: "medium" };
await test("API sends the contract and optional headers; health returns OK", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(
      JSON.stringify(
        url.endsWith("/health")
          ? { status: "ok" }
          : { move: "e2e4", info: { eval: 0.3, time_ms: 120 } },
      ),
    );
  };
  const result = await getCristopherMove(input);
  assert(result.move === "e2e4" && result.info.eval === 0.3);
  assert(
    calls[0].options.method === "POST" &&
      calls[0].url === "http://localhost:8000/move",
  );
  assert(
    JSON.stringify(JSON.parse(calls[0].options.body)) === JSON.stringify(input),
  );
  assert(calls[0].options.headers["ngrok-skip-browser-warning"] === "true");
  await checkCristopherHealth();
  assert(
    calls[1].url.endsWith("/health") &&
      calls[1].options.headers["ngrok-skip-browser-warning"] === "true",
  );
});
await test("Illegal moves and omitted promotion letters are rejected", async () => {
  for (const move of ["e2e5", "nope", "e2e4q"]) {
    globalThis.fetch = async () => new Response(JSON.stringify({ move }));
    await rejects(() => getCristopherMove(input), "invalid move");
  }
  globalThis.fetch = async () => new Response(JSON.stringify({ move: "a7a8" }));
  await rejects(
    () => getCristopherMove({ ...input, fen: "7k/P7/8/8/8/8/8/7K w - - 0 1" }),
    "invalid move",
  );
});
await test("Network, HTTP, malformed JSON, and timeout failures are friendly", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("Failed to fetch");
  };
  await rejects(() => getCristopherMove(input), "couldn't reach");
  globalThis.fetch = async () => new Response("", { status: 503 });
  await rejects(() => getCristopherMove(input), "AI is busy");
  globalThis.fetch = async () => new Response("", { status: 429, headers: { "Retry-After": "12" } });
  await rejects(() => getCristopherMove(input), "12 seconds");
  globalThis.fetch = async () => new Response("{");
  await rejects(() => getCristopherMove(input), "unreadable");
  CONFIG.REQUEST_TIMEOUT_MS = 20;
  globalThis.fetch = (_url, { signal }) =>
    new Promise((_resolve, reject) =>
      signal.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      ),
    );
  await rejects(() => getCristopherMove(input), "too long");
});
await test("Hard has its own timeout, cancellation is typed, and fallback is opt-in", async () => {
  const saved = { ...CONFIG };
  try {
    CONFIG.AUTO_FALLBACK = false;
    CONFIG.REQUEST_TIMEOUT_MS = 2;
    CONFIG.HARD_REQUEST_TIMEOUT_MS = 40;
    globalThis.fetch = (_url, { signal }) =>
      new Promise((_resolve, reject) =>
        signal.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        ),
      );
    let start = performance.now();
    try {
      await getCristopherMove({ ...input, difficulty: "hard" });
      throw new Error("Expected timeout");
    } catch (error) {
      assert(error instanceof CristopherError && error.code === "timeout");
    }
    assert(
      performance.now() - start >= 30,
      "Hard must use its separate timeout",
    );
    const pending = getCristopherMove({ ...input, difficulty: "hard" });
    cancelCristopherMove();
    try {
      await pending;
      throw new Error("Expected cancel");
    } catch (error) {
      assert(error.code === "cancelled");
    }
    CONFIG.AUTO_FALLBACK = true;
    globalThis.fetch = async () => {
      throw new TypeError("offline");
    };
    const result = await getCristopherMove(input);
    assert(result.info.placeholder && result.info.fallback);
    assert(
      new Chess()
        .moves({ verbose: true })
        .some((m) => toUci(m) === result.move),
    );
  } finally {
    Object.assign(CONFIG, saved);
  }
});
await test("Health identity, error results, URL normalization, and mixed content", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        status: "ok",
        engine: "cristopher",
        version: "test-v1",
      }),
    );
  const health = await checkHealth();
  assert(
    health.ok &&
      health.engine === "cristopher" &&
      health.version === "test-v1" &&
      health.latency_ms >= 0,
  );
  globalThis.fetch = async () => new Response("{bad");
  assert(!(await checkHealth()).ok);
  assert(
    normalizeApiUrl("  https://example.com/// ") === "https://example.com",
  );
  for (const url of [
    "ftp://example.com",
    "javascript:alert(1)",
    "hello",
    "https://user:secret@example.com",
  ]) {
    let rejected = false;
    try {
      normalizeApiUrl(url);
    } catch {
      rejected = true;
    }
    assert(rejected, url);
  }
  assert(hasMixedContent("http://example.com", "https:"));
  assert(!hasMixedContent("http://localhost:8000", "https:"));
  assert(!hasMixedContent("https://example.com", "https:"));
});
await test("Stockfish uses the free endpoint without model headers and validates its moves", async () => {
  const saved = { ...CONFIG };
  try {
    CONFIG.ENGINE = "stockfish";
    CONFIG.USE_API = false;
    CONFIG.AUTO_FALLBACK = false;
    CONFIG.EXTRA_HEADERS = { Authorization: "private-model-key" };
    for (const [difficulty, depth] of [["easy", 8], ["medium", 12], ["hard", 18]]) {
      globalThis.fetch = async (url, options) => {
        assert(url === "https://chess-api.com/v1");
        const body = JSON.parse(options.body);
        assert(body.fen === input.fen && body.depth === depth && body.variants === 1);
        assert(!("history" in body));
        assert(Object.keys(options.headers).join() === "Content-Type", "Model headers must not leak to Stockfish");
        assert(options.credentials === "omit");
        return new Response(JSON.stringify({ move: "e2e4", eval: -0.2, depth }));
      };
      const result = await getCristopherMove({ ...input, difficulty });
      assert(result.move === "e2e4" && result.info.eval === -0.2 && result.info.depth === depth);
    }
    globalThis.fetch = async () => new Response(JSON.stringify({ move: "e2e5" }));
    await rejects(() => getCristopherMove(input), "Cristopher V2 returned an invalid move");
    globalThis.fetch = async () => new Response(JSON.stringify({ move: "a7a8q" }));
    assert((await getCristopherMove({ ...input, fen: "7k/P7/8/8/8/8/8/7K w - - 0 1" })).move === "a7a8q");
    globalThis.fetch = async () => new Response("", { status: 429 });
    await rejects(() => getCristopherMove(input), "Too many requests");
    globalThis.fetch = async () => new Response("{");
    await rejects(() => getCristopherMove(input), "Cristopher V2 sent an unreadable response");
    globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    });
    CONFIG.REQUEST_TIMEOUT_MS = 10;
    await rejects(() => getCristopherMove(input), "Cristopher V2 took too long");
    const pending = getCristopherMove(input);
    cancelCristopherMove();
    await rejects(() => pending, "cancelled");
    CONFIG.ENGINE = "random";
    CONFIG.USE_API = true;
    globalThis.fetch = () => { throw new Error("Random engine must not fetch"); };
    assert((await getCristopherMove(input)).info.placeholder);
  } finally {
    Object.assign(CONFIG, saved);
  }
});
Object.assign(CONFIG, originalConfig);
globalThis.fetch = originalFetch;

const frame = document.getElementById("app");
await until(
  () => frame.contentDocument.querySelectorAll(".square").length === 64,
  "application to load",
);
const doc = frame.contentDocument;
// Load a same-origin external module into the frame without unsafe-eval.
// This helper lives only in tests/ and is excluded from the Pages artifact.
await new Promise((resolve, reject) => {
  const bridge = doc.createElement("script");
  bridge.type = "module";
  bridge.src = new URL("./frame_bridge.js", import.meta.url).href;
  bridge.onload = resolve;
  bridge.onerror = reject;
  doc.head.append(bridge);
});
const frameConfig = frame.contentWindow.__chessTestConfig;
await test("Public CSP blocks eval and inline scripts", async () => {
  let denied = false;
  try { frame.contentWindow.eval("1 + 1"); } catch { denied = true; }
  assert(denied, "unsafe-eval must remain disabled");
  const inline = doc.createElement("script");
  inline.textContent = "window.__inlineSecurityProbe = true";
  doc.head.append(inline);
  await sleep(20);
  assert(!frame.contentWindow.__inlineSecurityProbe, "inline scripts must remain blocked");
  inline.remove();
});
const frameOriginalConfig = { ...frameConfig };
Object.assign(frameConfig, {
  ENGINE: "cristopher",
  USE_API: false,
  API_URL: "http://localhost:8000",
  AUTO_FALLBACK: false,
});
doc.getElementById("use-api").checked = false;
doc.getElementById("api-fallback").checked = false;
doc.getElementById("api-url").value = frameConfig.API_URL;
const click = (id) => doc.getElementById(id).click();
const square = (name) => doc.querySelector(`[data-square="${name}"]`);
const move = (from, to) => {
  square(from).click();
  square(to).click();
};
function newGame(opponent = "local", color = "w") {
  click("new-game-button");
  doc.querySelector(`[name=color][value=${color}]`).checked = true;
  doc.getElementById("opponent").value = opponent;
  doc.getElementById("opponent").dispatchEvent(new Event("change"));
  doc.getElementById("new-game-form").requestSubmit();
}

await test("Before Play, the clock stays paused and the interface has one Settings button", async () => {
  assert(doc.getElementById("game-status").textContent === "Ready to play");
  assert(!doc.querySelector(".side-nav, .player-name, .brand-label"));
  assert(doc.querySelectorAll('[aria-label="Open settings"]').length === 1);
  assert(!doc.querySelector(".player-clock.running"));
  const before = [...doc.querySelectorAll(".player-clock span")].map(el => el.textContent).join();
  move("e2", "e4");
  await sleep(1150);
  assert(doc.getElementById("move-count").textContent === "0 played");
  assert([...doc.querySelectorAll(".player-clock span")].map(el => el.textContent).join() === before);
  doc.getElementById("time-control").value = "180";
  doc.getElementById("time-control").dispatchEvent(new frame.contentWindow.Event("change"));
  assert([...doc.querySelectorAll(".player-clock span")].every(el => el.textContent === "3:00"));
  assert(!doc.querySelector(".player-clock.running"));
  doc.getElementById("time-control").value = "600";
});

await test("UI click selection, legal dots, illegal destination, and last move", () => {
  newGame();
  square("e2").click();
  assert(square("e2").classList.contains("selected"));
  assert(
    square("e3").classList.contains("legal-move") &&
      square("e4").classList.contains("legal-move"),
  );
  square("e5").click();
  assert(doc.getElementById("move-count").textContent === "0 played");
  square("e4").click();
  assert(
    square("e4").querySelector("img") &&
      square("e2").classList.contains("last-move"),
  );
  assert(doc.getElementById("game-status").textContent === "Black to move");
});
await test("UI Scholar’s mate, capture rings, check king, SAN, and game lock", () => {
  newGame();
  [
    ["e2", "e4"],
    ["e7", "e5"],
    ["f1", "c4"],
    ["b8", "c6"],
    ["d1", "h5"],
    ["g8", "f6"],
  ].forEach(([from, to]) => move(from, to));
  square("h5").click();
  assert(square("f7").classList.contains("legal-capture"));
  square("f7").click();
  assert(doc.getElementById("game-status").textContent === "White wins");
  assert(square("e8").classList.contains("in-check"));
  assert(doc.getElementById("move-list").textContent.includes("Qxf7#"));
  assert(
    doc.getElementById("white-captures").querySelectorAll("img").length === 1,
  );
  assert(doc.getElementById("board").classList.contains("input-locked"));
});
await test("UI en passant and Undo restore captured pieces", () => {
  newGame();
  [
    ["e2", "e4"],
    ["a7", "a6"],
    ["e4", "e5"],
    ["d7", "d5"],
    ["e5", "d6"],
  ].forEach(([from, to]) => move(from, to));
  assert(!square("d5").querySelector("img"));
  assert(doc.getElementById("white-material").textContent === "+1");
  click("undo-button");
  assert(
    square("d5").querySelector("img") &&
      doc.getElementById("white-captures").textContent === "—",
  );
});
await test("UI castling moves the king and rook on both sides", () => {
  const games = [
    {
      moves: [
        ["e2", "e4"],
        ["e7", "e5"],
        ["g1", "f3"],
        ["b8", "c6"],
        ["f1", "c4"],
        ["f8", "c5"],
        ["e1", "g1"],
        ["g8", "f6"],
        ["d2", "d3"],
        ["e8", "g8"],
      ],
      king: "g",
      rook: "f",
    },
    {
      moves: [
        ["d2", "d4"],
        ["d7", "d5"],
        ["b1", "c3"],
        ["b8", "c6"],
        ["c1", "f4"],
        ["c8", "f5"],
        ["d1", "d2"],
        ["d8", "d7"],
        ["e1", "c1"],
        ["e8", "c8"],
      ],
      king: "c",
      rook: "d",
    },
  ];
  for (const game of games) {
    newGame();
    game.moves.forEach(([from, to]) => move(from, to));
    for (const [color, rank] of [
      ["w", "1"],
      ["b", "8"],
    ]) {
      assert(
        square(`${game.king}${rank}`)
          .querySelector("img")
          ?.src.endsWith(`${color}K.svg`),
      );
      assert(
        square(`${game.rook}${rank}`)
          .querySelector("img")
          ?.src.endsWith(`${color}R.svg`),
      );
    }
    assert(doc.getElementById("move-count").textContent === "10 played");
  }
});
await test("UI promotion offers four choices; cancel preserves board; every choice works", () => {
  newGame();
  [
    ["a2", "a4"],
    ["h7", "h5"],
    ["a4", "a5"],
    ["h5", "h4"],
    ["a5", "a6"],
    ["h4", "h3"],
    ["a6", "b7"],
    ["h3", "g2"],
  ].forEach(([from, to]) => move(from, to));
  move("b7", "a8");
  assert(doc.getElementById("promotion-dialog").open);
  assert(doc.querySelectorAll("#promotion-options button").length === 4);
  click("cancel-promotion");
  assert(square("b7").querySelector("img"));
  for (const [type, name] of [
    ["q", "queen"],
    ["r", "rook"],
    ["b", "bishop"],
    ["n", "knight"],
  ]) {
    square("a8").click();
    assert(doc.getElementById("promotion-dialog").open);
    doc.querySelector(`[aria-label="Promote to ${name}"]`).click();
    assert(
      square("a8")
        .querySelector("img")
        .src.endsWith(`w${type.toUpperCase()}.svg`),
    );
    click("undo-button");
    square("b7").click();
  }
});
await test("UI keyboard navigation and flipped coordinates", () => {
  newGame();
  square("e2").focus();
  square("e2").dispatchEvent(
    new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }),
  );
  assert(doc.activeElement.dataset.square === "e3");
  click("flip-button");
  assert(doc.getElementById("board").firstElementChild.dataset.square === "h1");
  assert(square("a8").querySelector(".file-coordinate").textContent === "a");
});
await test("AI input lock, completed-round Undo, and stale response after Undo", async () => {
  newGame("ai");
  move("e2", "e4");
  assert(doc.getElementById("board").classList.contains("input-locked"));
  assert(!doc.getElementById("thinking").hidden);
  await until(
    () => doc.getElementById("move-count").textContent === "2 played",
    "AI reply",
  );
  click("undo-button");
  assert(doc.getElementById("move-count").textContent === "0 played");
  move("e2", "e4");
  click("undo-button");
  await sleep(900);
  assert(doc.getElementById("move-count").textContent === "0 played");
});
await test("New Game invalidates an in-flight response; Black auto-flips and AI opens", async () => {
  newGame("ai");
  move("e2", "e4");
  newGame("local");
  await sleep(900);
  assert(doc.getElementById("move-count").textContent === "0 played");
  newGame("ai", "b");
  assert(doc.getElementById("board").firstElementChild.dataset.square === "h1");
  await until(
    () => doc.getElementById("move-count").textContent === "1 played",
    "AI opening",
  );
  assert(doc.getElementById("game-status").textContent === "Black to move");
  assert(doc.getElementById("undo-button").disabled);
});
await test("UI API failure preserves board, Retry succeeds, resignation invalidates pending move", async () => {
  const config = frameConfig;
  const savedFetch = frame.contentWindow.fetch;
  try {
    config.USE_API = true;
    frame.contentWindow.fetch = async () =>
      new Response(JSON.stringify({ move: "a1a8" }));
    newGame("ai");
    move("e2", "e4");
    await until(() => !doc.getElementById("ai-error").hidden, "error message");
    assert(doc.getElementById("move-count").textContent === "1 played");
    frame.contentWindow.fetch = async (url) =>
      new Response(
        JSON.stringify(
          url.endsWith("/health") ? { status: "ok" } : { move: "e7e5" },
        ),
      );
    click("retry-button");
    await until(
      () => doc.getElementById("move-count").textContent === "2 played",
      "retry",
    );
    assert(doc.getElementById("ai-error").hidden);
    assert(doc.getElementById("connection").textContent.includes("Connected"));
  } finally {
    config.USE_API = false;
    frame.contentWindow.fetch = savedFetch;
  }
  newGame("ai");
  move("e2", "e4");
  click("resign-button");
  click("confirm-resign");
  await sleep(900);
  assert(doc.getElementById("game-status").textContent === "Black wins");
  assert(doc.getElementById("move-count").textContent === "1 played");
});
await test("History review is read-only, preserves the live position, and returns to live", () => {
  newGame("local");
  [
    ["e2", "e4"],
    ["e7", "e5"],
    ["g1", "f3"],
    ["b8", "c6"],
  ].forEach(([from, to]) => move(from, to));
  doc.querySelector('[data-ply="1"]').click();
  assert(!doc.getElementById("review-indicator").hidden);
  assert(
    square("e7").querySelector("img") && !square("e5").querySelector("img"),
  );
  assert(doc.getElementById("board").classList.contains("input-locked"));
  move("d7", "d5");
  assert(doc.getElementById("move-count").textContent === "4 played");
  click("history-first");
  assert(square("e2").querySelector("img"));
  click("history-next");
  assert(square("e4").querySelector("img"));
  click("back-to-live");
  assert(
    square("c6").querySelector("img") && square("f3").querySelector("img"),
  );
  assert(doc.getElementById("review-indicator").hidden);
  assert(!doc.getElementById("board").classList.contains("input-locked"));
});
await test("Settings apply board themes and display preferences and persist them", async () => {
  const originalStorage = frame.contentWindow.localStorage.getItem(
    "cristopher.settings.v1",
  );
  const originalTheme = doc.documentElement.dataset.boardTheme;
  const ids = ["coordinates-toggle", "legal-toggle", "highlights-toggle"];
  const originalValues = ids.map((id) => doc.getElementById(id).checked);
  click("settings-button");
  try {
    doc.querySelector('[name="board-theme"][value="blue"]').click();
    assert(doc.documentElement.dataset.boardTheme === "blue");
    ids.forEach((id) => {
      if (doc.getElementById(id).checked) doc.getElementById(id).click();
    });
    assert(doc.documentElement.classList.contains("no-coordinates"));
    assert(doc.documentElement.classList.contains("no-legal-moves"));
    assert(doc.documentElement.classList.contains("no-highlights"));
    const saved = JSON.parse(
      frame.contentWindow.localStorage.getItem("cristopher.settings.v1"),
    );
    assert(
      saved.theme === "blue" &&
        !saved.coordinates &&
        !saved.legalMoves &&
        !saved.highlights,
    );
  } finally {
    doc.querySelector(`[name="board-theme"][value="${originalTheme}"]`).click();
    ids.forEach((id, index) => {
      if (doc.getElementById(id).checked !== originalValues[index])
        doc.getElementById(id).click();
    });
    if (originalStorage === null)
      frame.contentWindow.localStorage.removeItem("cristopher.settings.v1");
    else
      frame.contentWindow.localStorage.setItem(
        "cristopher.settings.v1",
        originalStorage,
      );
    doc.querySelector('[data-close="settings-dialog"]').click();
  }
});
await test("Clock deducts elapsed time, switches turns, restores undo, and flags only once", () => {
  let now = 0;
  const flagged = [];
  const timer = new ChessClock(
    () => {},
    (color) => flagged.push(color),
    () => now,
  );
  try {
    timer.start(180);
    now = 1234;
    timer.tick();
    assert(
      timer.value().remaining.w === 178766 &&
        timer.value().remaining.b === 180000,
    );
    timer.switchTurn("b");
    const snapshot = timer.snapshot();
    now = 3234;
    timer.tick();
    assert(timer.value().remaining.b === 178000);
    timer.restore(snapshot, "b");
    assert(timer.value().remaining.b === 180000);
    now += 200000;
    timer.tick();
    timer.tick();
    assert(flagged.join("") === "b" && timer.value().remaining.b === 0);
    assert(formatTime(1) === "0:01" && formatTime(600000) === "10:00");
    timer.start(0);
    now += 900000;
    timer.tick();
    assert(timer.value().active === null);
  } finally {
    timer.destroy();
  }
});
await test("Game result closes, rematches with the same settings, and local draw is agreed", () => {
  newGame("local");
  [
    ["e2", "e4"],
    ["e7", "e5"],
    ["f1", "c4"],
    ["b8", "c6"],
    ["d1", "h5"],
    ["g8", "f6"],
    ["h5", "f7"],
  ].forEach(([from, to]) => move(from, to));
  assert(!doc.getElementById("result-layer").hidden);
  assert(doc.getElementById("result-title").textContent === "White won");
  assert(doc.getElementById("result-detail").textContent.includes("Checkmate"));
  click("close-result");
  assert(doc.getElementById("result-layer").hidden);
  click("undo-button");
  assert(!doc.getElementById("board").classList.contains("input-locked"));
  move("h5", "f7");
  click("rematch-button");
  assert(doc.getElementById("move-count").textContent === "0 played");
  assert(doc.getElementById("result-layer").hidden);
  click("draw-button");
  click("confirm-draw");
  assert(doc.getElementById("game-status").textContent === "Game drawn");
  assert(
    doc.getElementById("result-detail").textContent === "Draw by agreement.",
  );
});
await test("No clock mode and actual clock displays track the moving side", () => {
  doc.getElementById("time-control").value = "0";
  newGame("local");
  assert(
    [...doc.querySelectorAll(".player-clock span")].every(
      (element) => element.textContent === "∞",
    ),
  );
  assert(!doc.querySelector(".player-clock.running"));
  doc.getElementById("time-control").value = "180";
  newGame("local");
  assert(
    doc
      .querySelector("#bottom-player .player-clock")
      .classList.contains("running"),
  );
  move("e2", "e4");
  assert(
    doc
      .querySelector("#top-player .player-clock")
      .classList.contains("running"),
  );
  assert(
    !doc
      .querySelector("#bottom-player .player-clock")
      .classList.contains("running"),
  );
  doc.getElementById("time-control").value = "600";
});
await test("Connection Settings save URL, show identity and engine info, recover and stay offline", async () => {
  const config = frameConfig;
  const saved = { ...config },
    savedFetch = frame.contentWindow.fetch;
  const storage = ["apiUrl", "useApi", "autoFallback", "showEngineInfo"].map(
    (key) => [key, frame.contentWindow.localStorage.getItem(`chess.${key}`)],
  );
  try {
    newGame("ai");
    click("settings-button");
    frame.contentWindow.fetch = async (url) =>
      new Response(
        JSON.stringify(
          url.endsWith("/health")
            ? { status: "ok", engine: "cristopher", version: "test-v2" }
            : { move: "e7e5", info: { eval: -0.35, depth: 3, time_ms: 120 } },
        ),
      );
    const url = doc.getElementById("api-url");
    url.value = "  https://example.com/// ";
    url.dispatchEvent(new frame.contentWindow.Event("change"));
    if (!doc.getElementById("use-api").checked) click("use-api");
    click("test-api");
    await until(
      () => doc.getElementById("api-status").textContent.includes("Connected"),
      "connection test",
    );
    assert(config.API_URL === "https://example.com");
    assert(
      frame.contentWindow.localStorage.getItem("chess.apiUrl") ===
        "https://example.com",
    );
    assert(
      doc.getElementById("api-health-detail").textContent.includes("test-v2"),
    );
    if (!doc.getElementById("engine-info-toggle").checked)
      click("engine-info-toggle");
    doc.getElementById("settings-dialog").close();
    move("e2", "e4");
    await until(
      () => doc.getElementById("move-count").textContent === "2 played",
      "API move",
    );
    assert(!doc.querySelector("#top-player .engine-info").hidden);
    assert(
      doc
        .querySelector("#top-player .engine-info")
        .textContent.includes("-0.35"),
    );
    click("undo-button");
    frame.contentWindow.fetch = async () => {
      throw new TypeError("server stopped");
    };
    move("e2", "e4");
    await until(() => !doc.getElementById("ai-error").hidden, "friendly error");
    assert(
      doc
        .getElementById("error-text")
        .textContent.includes("Cristopher lost connection"),
    );
    assert(!doc.getElementById("undo-button").disabled);
    click("reconnect-button");
    assert(doc.getElementById("settings-dialog").open);
    click("use-api");
    doc.getElementById("settings-dialog").close();
    click("retry-button");
    await until(
      () => doc.getElementById("move-count").textContent === "2 played",
      "offline retry",
    );
    assert(
      doc.getElementById("api-status").textContent.includes("Offline mode"),
    );
  } finally {
    Object.assign(config, saved);
    frame.contentWindow.fetch = savedFetch;
    doc.getElementById("settings-dialog").close();
    for (const [key, value] of storage) {
      if (value === null)
        frame.contentWindow.localStorage.removeItem(`chess.${key}`);
      else frame.contentWindow.localStorage.setItem(`chess.${key}`, value);
    }
  }
});
await test("Health polling uses 20 seconds and stops while the tab is hidden", async () => {
  const w = frame.contentWindow;
  const savedFetch = w.fetch,
    savedSet = w.setInterval,
    savedClear = w.clearInterval;
  const originalUse = frameConfig.USE_API;
  const scheduled = new Map();
  let calls = 0;
  try {
    frameConfig.USE_API = true;
    newGame("ai");
    w.fetch = async () => {
      calls++;
      return new Response(JSON.stringify({ status: "ok" }));
    };
    w.setInterval = (fn, ms) => {
      const id = savedSet.call(w, fn, ms);
      scheduled.set(id, ms);
      return id;
    };
    w.clearInterval = (id) => {
      scheduled.delete(id);
      savedClear.call(w, id);
    };
    Object.defineProperty(doc, "hidden", { configurable: true, value: false });
    doc.dispatchEvent(new w.Event("visibilitychange"));
    await until(() => calls > 0, "visible health ping");
    assert([...scheduled.values()].includes(20000));
    Object.defineProperty(doc, "hidden", { configurable: true, value: true });
    doc.dispatchEvent(new w.Event("visibilitychange"));
    assert(scheduled.size === 0, "Hidden tab must clear its health timer");
    const before = calls;
    await sleep(50);
    assert(calls === before);
    Object.defineProperty(doc, "hidden", { configurable: true, value: false });
    doc.dispatchEvent(new w.Event("visibilitychange"));
    await until(() => calls > before, "visible tab resumes immediately");
  } finally {
    frameConfig.USE_API = false;
    doc.dispatchEvent(new w.Event("visibilitychange"));
    delete doc.hidden;
    frameConfig.USE_API = originalUse;
    w.fetch = savedFetch;
    w.setInterval = savedSet;
    w.clearInterval = savedClear;
  }
});
await test("Local games stop API checks; confirmed connection stays visible during refresh", async () => {
  const w = frame.contentWindow, savedFetch = w.fetch;
  let calls = 0, resolveHealth;
  try {
    frameConfig.USE_API = true;
    w.fetch = async () => { calls++; return new Response(JSON.stringify({ status: "ok", engine: "test" })); };
    newGame("local");
    const before = calls;
    doc.dispatchEvent(new w.Event("visibilitychange"));
    await sleep(60);
    assert(calls === before, "Local game must not ping even with server toggle on");
    assert(doc.getElementById("connection").textContent.includes("API inactive"));
    newGame("ai");
    await until(() => doc.getElementById("connection").textContent.includes("Connected"), "AI connection");
    w.fetch = () => new Promise(resolve => { resolveHealth = resolve; });
    doc.dispatchEvent(new w.Event("visibilitychange"));
    assert(doc.getElementById("connection").textContent.includes("Connected"), "Background checks must not replace Connected with Connecting");
    resolveHealth(new Response(JSON.stringify({ status: "ok" })));
    await sleep(50);
    newGame("local");
    assert(doc.getElementById("connection").textContent.includes("API inactive"));
  } finally {
    frameConfig.USE_API = false;
    newGame("local");
    w.fetch = savedFetch;
  }
});
await test("Engine selector persists, routes Stockfish, and cancels stale moves without local-game requests", async () => {
  const w = frame.contentWindow, savedFetch = w.fetch, saved = { ...frameConfig };
  const stored = new Map(Array.from({ length: w.localStorage.length }, (_, i) => {
    const key = w.localStorage.key(i); return [key, w.localStorage.getItem(key)];
  }));
  const select = (value) => {
    doc.getElementById("ai-engine").value = value;
    doc.getElementById("ai-engine").dispatchEvent(new w.Event("change"));
  };
  let calls = 0;
  try {
    newGame("local");
    w.fetch = async (url) => {
      calls++;
      assert(url === "https://chess-api.com/v1");
      return new Response(JSON.stringify({ move: "e7e5", eval: 0.1, depth: 12 }));
    };
    // A selection must survive an unrelated render before the native change
    // event, then activate on input even if change is delayed until blur.
    const engineSelect = doc.getElementById("ai-engine");
    engineSelect.value = "stockfish";
    click("engine-info-toggle");
    assert(engineSelect.value === "stockfish", "Rendering must not reset the user's pending selection");
    engineSelect.dispatchEvent(new w.Event("input"));
    assert(frameConfig.ENGINE === "stockfish", "Input must activate the selected engine immediately");
    click("engine-info-toggle");
    engineSelect.dispatchEvent(new w.Event("change"));
    assert(w.localStorage.getItem("chess.engine") === "stockfish");
    assert(doc.getElementById("cristopher-settings").hidden);
    assert(!doc.getElementById("stockfish-help").hidden);
    doc.dispatchEvent(new w.Event("visibilitychange"));
    await sleep(30);
    assert(calls === 0 && doc.getElementById("connection").textContent.includes("API inactive"));
    newGame("ai");
    assert(calls === 0 && doc.getElementById("connection").textContent.includes("ready to connect"));
    move("e2", "e4");
    await until(() => doc.getElementById("move-count").textContent === "2 played", "Stockfish move");
    assert(calls === 1 && doc.getElementById("connection").textContent.includes("Connected"));
    assert(doc.getElementById("api-health-detail").textContent.includes("Cristopher V2 · Depth 12"));
    click("undo-button");
    w.fetch = async () => new Response("", { status: 429 });
    move("e2", "e4");
    await until(() => !doc.getElementById("ai-error").hidden, "Stockfish rejection");
    assert(doc.getElementById("connection").textContent.includes("Disconnected"));
    click("undo-button");
    let resolveMove, moveSignal;
    w.fetch = (_url, { signal }) => {
      moveSignal = signal;
      return new Promise(resolve => { resolveMove = resolve; });
    };
    move("e2", "e4");
    await until(() => Boolean(resolveMove), "pending Stockfish request");
    select("random");
    assert(moveSignal.aborted, "Switching engines must abort the previous request");
    resolveMove(new Response(JSON.stringify({ move: "e7e5" })));
    await sleep(30);
    assert(doc.getElementById("move-count").textContent === "1 played", "Stale reply must not move pieces");
    w.fetch = () => { throw new Error("Random engine must not fetch"); };
    click("retry-button");
    await until(() => doc.getElementById("move-count").textContent === "2 played", "random retry");
    newGame("local");
    select("cristopher");
    assert(!doc.getElementById("cristopher-settings").hidden && frameConfig.USE_API);
    assert(frameConfig.API_URL === saved.API_URL, "Switching engines must preserve the model URL");
  } finally {
    Object.assign(frameConfig, saved);
    newGame("local");
    w.fetch = savedFetch;
    for (const key of Object.keys(w.localStorage)) if (key.startsWith("chess.")) w.localStorage.removeItem(key);
    for (const [key, value] of stored) w.localStorage.setItem(key, value);
  }
});
Object.assign(CONFIG, suiteConfig);
Object.assign(frameConfig, frameOriginalConfig);
const passed = results.filter((result) => result.pass).length;
document.getElementById("summary").textContent =
  `${passed}/${results.length} checks passed`;
document.body.dataset.complete = "true";
document.body.dataset.failed = results.length - passed;
