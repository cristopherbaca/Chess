import { PUBLIC_API_URL } from "./public-config.js?v=engine-ui-3";

const saved = (key, fallback) => {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
};

export function normalizeApiUrl(value) {
  let url;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error("Enter a valid http:// or https:// server URL.");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw new Error(
      "Use an http:// or https:// server URL without credentials, query, or fragment.",
    );
  return url.href.replace(/\/+$/, "");
}
let apiUrl = PUBLIC_API_URL || "http://localhost:8000";
try {
  apiUrl = normalizeApiUrl(saved("chess.apiUrl", apiUrl));
} catch {
  /* Ignore invalid saved URLs. */
}
export const CONFIG = {
  ENGINE: ["random", "cristopher", "stockfish"].includes(saved("chess.engine", ""))
    ? saved("chess.engine", "")
    : "cristopher",
  USE_API: saved("chess.useApi", PUBLIC_API_URL ? "true" : "false") === "true",
  API_URL: apiUrl,
  REQUEST_TIMEOUT_MS: 15000,
  HARD_REQUEST_TIMEOUT_MS: 30000,
  HEALTH_TIMEOUT_MS: 4000,
  EXTRA_HEADERS: { "ngrok-skip-browser-warning": "true" },
  AUTO_FALLBACK: saved("chess.autoFallback", "false") === "true",
  SHOW_ENGINE_INFO: saved("chess.showEngineInfo", "false") === "true",
};

export function saveApiSettings(values) {
  const next = { ...values };
  if ("ENGINE" in next && !["random", "cristopher", "stockfish"].includes(next.ENGINE))
    throw new Error("Choose a supported AI engine.");
  if ("API_URL" in next) next.API_URL = normalizeApiUrl(next.API_URL);
  Object.assign(CONFIG, next);
  for (const [name, key] of Object.entries({
    ENGINE: "engine",
    API_URL: "apiUrl",
    USE_API: "useApi",
    AUTO_FALLBACK: "autoFallback",
    SHOW_ENGINE_INFO: "showEngineInfo",
  })) {
    try {
      localStorage.setItem(`chess.${key}`, String(CONFIG[name]));
    } catch {
      /* Storage is optional. */
    }
  }
}

export const activeEngine = () => CONFIG.ENGINE === "cristopher" && !CONFIG.USE_API
  ? "random" : CONFIG.ENGINE;
export const usesRemoteEngine = () => activeEngine() !== "random";
export const engineName = () => ({ random: "Random bot", cristopher: "Cristopher", stockfish: "Cristopher V2" })[activeEngine()];
export const STOCKFISH_API_URL = "https://chess-api.com/v1";

export function hasMixedContent(
  url = CONFIG.API_URL,
  protocol = location.protocol,
) {
  const target = new URL(url);
  return (
    protocol === "https:" &&
    target.protocol === "http:" &&
    !["localhost", "127.0.0.1", "[::1]"].includes(target.hostname)
  );
}
