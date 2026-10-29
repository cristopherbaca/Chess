import { Chess } from "../vendor/chess.js";
import { CONFIG, activeEngine, STOCKFISH_API_URL } from "./config.js?v=engine-ui-6";

export class CristopherError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "CristopherError";
    this.code = code;
  }
}
const activeMoves = new Set();
export function cancelCristopherMove() {
  for (const controller of activeMoves) controller.abort();
}

async function request(
  path,
  options = {},
  timeoutMs = CONFIG.REQUEST_TIMEOUT_MS,
  controller = new AbortController(),
  engine = "cristopher",
) {
  const stockfish = engine === "stockfish";
  const name = stockfish ? "Cristopher V1" : "Cristopher V2";
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetch(
      stockfish ? STOCKFISH_API_URL : `${CONFIG.API_URL.replace(/\/+$/, "")}${path}`,
      {
        ...options,
        headers: {
          ...options.headers,
          ...(!stockfish ? { ...CONFIG.EXTRA_HEADERS, "ngrok-skip-browser-warning": "true" } : {}),
        },
        signal: controller.signal,
        credentials: "omit",
        redirect: "error",
        referrerPolicy: "no-referrer",
      },
    );
    if (!response.ok)
      throw new CristopherError(
        "http",
        response.status === 429
          ? `Too many requests. Please wait ${response.headers?.get?.("Retry-After") || "a few"} seconds before retrying.`
          : response.status === 503
            ? "The AI is busy. Please wait a moment and retry."
            : response.status === 403
              ? (stockfish ? "The Cristopher V1 service refused this request. Please try again later." : "This website is not allowed by the API. Check WEBSITE_ORIGINS in deployment.")
              : `The AI server returned HTTP ${response.status}. Please try again.`,
      );
    return await response.json();
  } catch (error) {
    if (controller.signal.aborted)
      throw new CristopherError(
        timedOut ? "timeout" : "cancelled",
        timedOut
          ? `${name} took too long to respond. Please try again.`
          : "Move request cancelled. Retry when you’re ready.",
      );
    if (error instanceof CristopherError) throw error;
    if (error instanceof SyntaxError)
      throw new CristopherError(
        "json",
        `${name} sent an unreadable response. Please try again.`,
      );
    throw new CristopherError(
      "network",
      `We couldn't reach ${name}. Check the connection and try again.`,
    );
  } finally {
    clearTimeout(timeout);
  }
}

export async function getCristopherMove({ fen, history, difficulty }) {
  const engine = activeEngine();
  const game = new Chess(fen);
  const legalMoves = game.moves({ verbose: true });
  if (game.isGameOver() || !legalMoves.length)
    throw new CristopherError(
      "illegal",
      "This position has no available move.",
    );
  const localMove = () => {
    const move = legalMoves[Math.floor(Math.random() * legalMoves.length)];
    return `${move.from}${move.to}${move.promotion || ""}`;
  };
  if (engine === "random") {
    await new Promise((resolve) =>
      setTimeout(resolve, 400 + Math.random() * 400),
    );
    return { move: localMove(), info: { placeholder: true } };
  }
  const controller = new AbortController();
  activeMoves.add(controller);
  try {
    const result = await request(
      "/move",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(engine === "stockfish"
          ? { fen, variants: 1, depth: 18, maxThinkingTime: 100 }
          : { fen, history, difficulty }),
      },
      engine === "stockfish" || difficulty === "hard"
        ? CONFIG.HARD_REQUEST_TIMEOUT_MS
        : CONFIG.REQUEST_TIMEOUT_MS,
      controller,
      engine,
    );
    if (
      typeof result?.move !== "string" ||
      !/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(result.move) ||
      !legalMoves.some(
        (move) =>
          `${move.from}${move.to}${move.promotion || ""}` === result.move,
      )
    )
      throw new CristopherError(
        "illegal",
        `${engine === "stockfish" ? "Cristopher V1" : "Cristopher V2"} returned an invalid move. Your board is safe. Please try again.`,
      );
    return { move: result.move, info: engine === "stockfish" ? {
      engine: "Cristopher V1",
      eval: Number.isFinite(result.eval) ? result.eval : undefined,
      depth: Number.isFinite(result.depth) ? result.depth : undefined,
      time_ms: Number.isFinite(result.time) ? result.time : undefined,
    } : result.info };
  } catch (error) {
    if (CONFIG.AUTO_FALLBACK && error.code !== "cancelled")
      return {
        move: localMove(),
        info: { placeholder: true, fallback: true, error: error.message },
      };
    throw error;
  } finally {
    activeMoves.delete(controller);
  }
}

export async function checkHealth({ signal } = {}) {
  const started = performance.now();
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  try {
    const result = await request(
      "/health",
      { cache: "no-store" },
      CONFIG.HEALTH_TIMEOUT_MS,
      controller,
    );
    if (result?.status !== "ok")
      throw new CristopherError("http", "Cristopher V2 is not ready yet.");
    return {
      ok: true,
      latency_ms: Math.round(performance.now() - started),
      engine: result.engine || "cristopher",
      version: result.version || "",
      error: null,
    };
  } catch (error) {
    return {
      ok: false,
      latency_ms: Math.round(performance.now() - started),
      engine: null,
      version: "",
      error: error.message,
    };
  } finally {
    signal?.removeEventListener("abort", abort);
  }
}

// Preserve the existing health helper for integrations using its boolean contract.
export async function checkCristopherHealth() {
  if (!CONFIG.USE_API) return true;
  const result = await checkHealth();
  if (!result.ok) throw new CristopherError("network", result.error);
  return true;
}
