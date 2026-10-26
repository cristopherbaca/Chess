import { CONFIG, saveApiSettings, hasMixedContent } from "../config.js";
import { checkHealth } from "../cristopher.js";

const $ = (id) => document.getElementById(id);
export function bindConnection(onChange, { isEnabled, idleLabel }) {
  let timer,
    healthController,
    generation = 0;
  let status = { state: "local", label: idleLabel() };
  const paint = () => {
    $("connection").className = `connection ${status.state}`;
    $("connection").querySelector("span").textContent = status.label;
    $("api-status").className = `api-status ${status.state}`;
    $("api-status").textContent = status.label;
    for (const chip of document.querySelectorAll(".ai-connection")) {
      chip.className = `ai-connection ${status.state}`;
      chip.textContent = status.label;
    }
    $("mixed-content-warning").hidden = !hasMixedContent();
    $("difficulty-note").textContent =
      CONFIG.USE_API
        ? "Uses your API server. Start it in Colab and set its URL in Settings."
        : "Random legal moves on your device. No API or Colab runtime is used.";
  };
  const cancelHealth = () => {
    generation++;
    healthController?.abort();
    healthController = null;
  };
  async function refresh(manual = false) {
    if ((!isEnabled() || document.hidden) && !manual) return;
    cancelHealth();
    const id = generation;
    healthController = new AbortController();
    // Keep a confirmed connection visible during background refreshes.
    if (status.state !== "online")
      status = { state: "checking", label: "Connecting…" };
    paint();
    const result = await checkHealth({ signal: healthController.signal });
    if (id !== generation) return;
    healthController = null;
    status = {
      state: result.ok ? "online" : "offline",
      label: result.ok ? `Connected (${result.latency_ms} ms)` : "Disconnected",
    };
    $("api-health-detail").textContent = result.ok
      ? `${result.engine}${result.version ? ` · ${result.version}` : ""}${isEnabled() ? "" : " · Server reachable; not used by the current game."}`
      : result.error;
    paint();
  }
  function schedule() {
    clearInterval(timer);
    cancelHealth();
    if (isEnabled()) {
      if (!document.hidden) {
        void refresh();
        timer = setInterval(() => void refresh(), 20000);
      }
    } else {
      status = { state: "local", label: idleLabel() };
      $("api-health-detail").textContent = "";
      paint();
    }
  }
  function saveUrl() {
    try {
      const previous = CONFIG.API_URL;
      saveApiSettings({ API_URL: $("api-url").value });
      $("api-url").value = CONFIG.API_URL;
      $("api-url").setCustomValidity("");
      if (CONFIG.API_URL !== previous) {
        status = { state: "local", label: idleLabel() };
        $("api-health-detail").textContent = "";
        onChange();
        schedule();
      }
      paint();
      return true;
    } catch (error) {
      $("api-url").setCustomValidity(error.message);
      $("api-url").reportValidity();
      return false;
    }
  }
  $("api-url").value = CONFIG.API_URL;
  $("api-url").addEventListener("input", () =>
    $("api-url").setCustomValidity(""),
  );
  $("api-url").addEventListener("change", saveUrl);
  for (const [id, key] of Object.entries({
    "use-api": "USE_API",
    "api-fallback": "AUTO_FALLBACK",
    "engine-info-toggle": "SHOW_ENGINE_INFO",
  })) {
    $(id).checked = CONFIG[key];
    $(id).addEventListener("change", () => {
      saveApiSettings({ [key]: $(id).checked });
      onChange(key);
      if (key === "USE_API") schedule();
    });
  }
  $("test-api").addEventListener("click", () => {
    if (saveUrl()) void refresh(true);
  });
  $("paste-api-url").addEventListener("click", async () => {
    try {
      $("api-url").value = await navigator.clipboard.readText();
      if (saveUrl()) void refresh(true);
    } catch {
      $("api-url").focus();
      $("api-url").select();
      $("api-health-detail").textContent =
        "Paste the URL here with Ctrl+V / ⌘V (or touch and hold).";
    }
  });
  document.addEventListener("visibilitychange", schedule);
  window.addEventListener("pagehide", () => {
    clearInterval(timer);
    cancelHealth();
  });
  paint();
  schedule();
  return {
    refresh,
    paint,
    sync: schedule,
    connected() {
      if (!isEnabled()) return;
      if (status.state !== "online")
        status = { state: "online", label: "Connected" };
      paint();
    },
    disconnected() {
      cancelHealth();
      status = { state: "offline", label: "Disconnected" };
      paint();
    },
  };
}
