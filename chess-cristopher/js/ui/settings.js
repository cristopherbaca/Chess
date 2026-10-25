const STORAGE_KEY = "cristopher.settings.v1";
const defaults = {
  theme: "green",
  sound: true,
  coordinates: true,
  legalMoves: true,
  highlights: true,
};

export function loadSettings() {
  const settings = { ...defaults };
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (["green", "brown", "blue"].includes(saved?.theme))
      settings.theme = saved.theme;
    for (const key of ["sound", "coordinates", "legalMoves", "highlights"]) {
      if (typeof saved?.[key] === "boolean") settings[key] = saved[key];
    }
  } catch {
    /* Private browsing or restricted storage still gets usable defaults. */
  }
  return settings;
}

export function applySettings(settings) {
  const root = document.documentElement;
  root.dataset.boardTheme = settings.theme;
  root.classList.toggle("no-coordinates", !settings.coordinates);
  root.classList.toggle("no-legal-moves", !settings.legalMoves);
  root.classList.toggle("no-highlights", !settings.highlights);
}

export function bindSettings(settings, onChange) {
  const update = () => {
    applySettings(settings);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      /* Storage is optional. */
    }
    onChange(settings);
  };
  for (const radio of document.querySelectorAll('[name="board-theme"]')) {
    radio.checked = radio.value === settings.theme;
    radio.addEventListener("change", () => {
      settings.theme = radio.value;
      update();
    });
  }
  for (const [id, key] of Object.entries({
    "sound-toggle": "sound",
    "coordinates-toggle": "coordinates",
    "legal-toggle": "legalMoves",
    "highlights-toggle": "highlights",
  })) {
    const input = document.getElementById(id);
    input.checked = settings[key];
    input.addEventListener("change", () => {
      settings[key] = input.checked;
      update();
    });
  }
  applySettings(settings);
}
