# Chess

A browser chess game with an independent Python AI. The website uses local HTML, CSS, JavaScript and chess.js. Two standalone Colab notebooks handle **all training** and **deployment** separately.

## Train the new 30M model from scratch

Upload the latest [vendor/train.ipynb](vendor/train.ipynb) to Google Colab, select a GPU runtime, and choose **Runtime → Run all** with the defaults:

```python
TRAINING_MODE = 'full_pipeline'
SOURCE_RUN = ''
RUN_NAME = ''  # Uses fresh_30m_v1.
TRAINING_HOURS = 2.5
TRAIN_SPARSE_EVALUATOR = True
MEASURE_ELO = True
ELO_MINUTES = 5.0
```

The dense model has **30,017,409 parameters**, with architecture **784 → 6400 → 3904 → 1** and a **32-member** evolutionary population. No previously trained dense model or saved classical prior is loaded. Hidden weights initialize randomly; the output head starts at zero over the built-in material/piece-square baseline.

All new artifacts are isolated under **`MyDrive/chess_30m/`**. Older Drive models are untouched and are not used. Subsequent Run-all sessions resume **this new experiment**. To deliberately restart again, choose a different `RUN_NAME`.

The complete workflow runs search-based neural evolution, classical genetic parameter training, optional sparse neural training, independent evaluator/search comparisons, tactical/endgame diagnostics, profiling and champion export. A full cycle can span multiple sessions. Checkpoints preserve completed progress; an abrupt runtime kill can lose work since the last Drive write. More parameters or lower prediction loss do not establish stronger play. See [FULL_PIPELINE.md](docs/FULL_PIPELINE.md).

Unchanged dense tensors now share lossless checkpoint files instead of being rewritten at every save. Three recovery states and their required weights are retained, old exports are pruned conservatively, and visible Drive usage is printed. Existing checkpoints still resume. Keep the entire checkpoint folder, including `tensors/`, when backing it up. Existing Drive Trash still consumes quota and needs separate review; see the [storage guide](docs/FULL_PIPELINE.md#drive-storage-and-existing-quota).

Training also reports **relative Elo against a fixed classical baseline**, with uncertainty, from independent paired games. It displays “pending” until enough games finish. This is not an online or FIDE rating. Details and controls are in the [strength guide](docs/FULL_PIPELINE.md#relative-elo-during-training).

## Deploy the API

1. Upload the latest [vendor/deploy.ipynb](vendor/deploy.ipynb) to a separate Colab runtime.
2. Leave `WEBSITE_ORIGINS = '*'` to accept requests from any website. An exact comma-separated origin list is optional if you later want restrictions.
3. Choose **Run all**. It loads only the new `MyDrive/chess_30m/models/` champion, verifies its manifest, starts the API, tests it and returns the HTTPS URL. It does not train.
4. Paste the URL into the game's **Settings → AI engine → My model — Cristopher → Server URL**, enable **Use AI server**, and select an AI opponent. The API is used only when AI is selected and the toggle is enabled.

Public connection checks retry every three seconds without an attempt limit until they pass. Interrupt the Colab cell to stop retries and close the tunnel.

Keep the runtime connected; call `shutdown_api()` or disconnect to stop it. Rerun deployment to load a newly selected champion. A restarted temporary tunnel can have a different URL.

Deployment's `API_DEVICE` setting defaults to `auto`: one neural network loads on CUDA when available, with CPU fallback if GPU memory runs out. Set it to `cpu` to force CPU inference. The updated deployment notebook also fixes older exports that fail with “GPU model population does not fit with the requested headroom”; no retraining or model-size change is needed. See the [recovery instructions](docs/PUBLIC_DEPLOYMENT.md#gpu-populationheadroom-error-while-loading-a-champion).

The API has bounded request bodies, strict input validation, per-client and global rate limits, two admitted searches, search deadlines, configurable browser origins, private diagnostics and response security headers. It binds to loopback behind the tunnel, disables interactive API documentation and checks a pinned Cloudflare binary checksum. Public `/move` remains anonymous; no shared admin secret is embedded in the frontend. Read [PUBLIC_DEPLOYMENT.md](docs/PUBLIC_DEPLOYMENT.md) for exact limits and remaining risks.

## Publish on GitHub Pages

The prepared workflow publishes **only browser assets**, not notebooks, Python files, tests or model weights. It runs manually; creating these files does not publish a site.

1. Push the reviewed changes to GitHub.
2. In repository **Settings → Pages**, select **GitHub Actions** as the publishing source and enable HTTPS when available.
3. Run **Actions → Publish Chess website → Run workflow**, supplying the HTTPS API URL from Colab.
4. For the current repository, the expected project URL is **https://cristopherbaca.github.io/Chess/**, subject to your Pages/domain settings.

The artifact configures the public API URL and restricts browser connections to that API origin and the Stockfish provider at `https://chess-api.com`. Rerun the publishing workflow when the tunnel URL changes. The URL is public configuration, not a password. A public source repository remains readable separately from its Pages artifact; never commit secrets or model checkpoints.

You can build/inspect the same artifact locally:

```sh
python3 tools/build_site.py --api-url https://your-tunnel.trycloudflare.com
python3 -m http.server 8080 --bind 127.0.0.1 --directory _site
```

The `_site/` directory is generated and ignored by Git. GitHub Pages hosts the interface; Colab hosts the AI. Neither application limits nor a temporary tunnel guarantee protection against distributed denial of service or uninterrupted public hosting.

## Choose the AI engine

In **Settings → AI engine**, select **Random moves** for offline play, **My model — Cristopher** to enter your Colab server URL (keep **Use AI server** enabled), or **Cristopher V2** (Stockfish 18) through the free [Chess-API.com service](https://chess-api.com/). Stockfish needs no key or Colab runtime; the provider receives the current board position when it plays. Cristopher V2 always requests the free service's maximum depth of 18 and maximum thinking time of 100 ms, with one principal variation. Its difficulty controls are hidden; the custom Cristopher model keeps its own difficulty settings. The displayed 2750 Elo is the provider's approximate estimate, not a measured rating for this app. Engine info shows the actual returned depth, which can be lower than requested. The service controls its hosted version and availability. Stockfish shows “Connected” after a successful move response; local two-player games make no automatic API requests. Changing engines cancels a pending move; use Retry to continue.

## Run locally and play

```sh
python3 -m http.server 8080 --bind 127.0.0.1
```

Open **http://localhost:8080**. For the browser regression runner, open `/tests/`. Keep this repository server local; use the frontend-only artifact for public hosting.

- Click or drag pieces, or use keyboard navigation. Promotions offer all four pieces.
- Select AI or local two-player mode, color, difficulty and time control; **Play** starts the game and clock.
- Settings control board appearance, sound and API connection. The server toggle is retained.
- Undo, board flip, move-history review, resignation and game-over controls preserve the existing chess rules.
- With the AI server disabled, the local placeholder chooses random legal moves; it is not the trained model.
- Failed AI requests leave the board unchanged and offer retry. Busy/rate-limit responses explain when to wait.

## Project layout

| Path | Purpose |
| --- | --- |
| `index.html`, `css/`, `js/`, `assets/`, `vendor/chess.js` | Browser game and local assets |
| `vendor/train.ipynb`, `vendor/deploy.ipynb` | Standalone Colab training and API deployment |
| `chess_ai/` | Rules adapter, search, evaluation, training, model export, UCI and API protections |
| `tools/` | Notebook synchronization, frontend build and reproducible research tools |
| `tests/` | Engine, training, deployment, API security and browser regression tests |
| `docs/FULL_PIPELINE.md`, `docs/PUBLIC_DEPLOYMENT.md` | Current operating instructions |
| `docs/ARCHITECTURE_ASSESSMENT.md`, `docs/MILESTONE_*.md`, `docs/benchmarks/` | Historical audit and measured evidence |
| `PHASES.md`, `LICENSES.md` | Engine requirements and asset/data licenses |

Generated local research models, datasets, incomplete experiment games, caches and the obsolete technical PDF/HTML builder were removed for the fresh start. Tests, curated validation data and measured evidence remain useful; starting a new model does not make those files obsolete. The earlier engine guide describes historical configurations; use the two current guides above for defaults.

## Verification

```sh
python -m pip install numpy python-chess torch nbformat fastapi uvicorn nest_asyncio httpx requests tqdm zstandard
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/sync_engine.py --check
python -m chess_ai  # Optional local UCI interface.
```

`tools/sync_engine.py` embeds the canonical engine modules in the training notebook and the API security module in deployment. Run it after modifying those sources. Local tests establish correctness and integration, not an Elo gain or sustained Colab CUDA performance. Genuine strength claims require controlled matches with the newly trained champion.

Latest local verification: **108 Python tests passed** ([output](docs/benchmarks/storage_20261028/tests.txt)) and **32/32 browser checks passed** ([results](docs/benchmarks/fresh_public_20261028/browser.json)), including real browser enforcement of the script policy. Notebook synchronization also passes. Colab CUDA, the live public tunnel and GitHub Pages publication remain to be exercised in your accounts.
