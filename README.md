# Chess

A responsive chess frontend in plain HTML, CSS, and vanilla JavaScript ES modules. No framework, package installation, or build step. Offline mode chooses random legal moves after a 400–800 ms delay. `vendor/train.ipynb` trains and saves the champion; `vendor/deploy.ipynb` serves it through FastAPI and a public tunnel. Each notebook supports **Run all** independently.

## Run

From this directory:

```sh
python3 -m http.server 8080
```

Open **http://localhost:8080**. On systems where Python is named `python`, use `python -m http.server 8080`.

Use a static server because browsers block local ES module imports under `file://`. Double-clicking `index.html` displays a setup hint. Any static HTTP server works; Python is only one option.

The pinned chess.js **1.4.0** rules engine and all SVG pieces are vendored locally. The interface uses system fonts and original inline SVG icons. Gameplay and the entire interface work offline in placeholder mode.

## Play

- Click a piece and then a highlighted destination, or drag it with a mouse or touch. Empty legal destinations have dots; captures have rings. The last move and a king in check are highlighted.
- Keyboard: Tab to the board, use arrow keys to navigate, and Enter/Space to select and move. Escape clears selection or dismisses a dialog. Promotion requires choosing Queen, Rook, Bishop, or Knight; canceling leaves the pawn in place.
- **New Game tab:** White, Random, or Black; AI opponent or Local 2 players; Easy, Medium, or Hard; No clock, 3+0, 5+0, or 10+0. Press **Play** to start the game and clock; both stay paused before that. Black starts at the bottom when selected. Difficulty is passed to the unchanged AI module but does not affect the random placeholder.
- **Undo:** in AI mode, removes your last move and the AI reply, or just your move if a reply is pending. A human playing Black keeps the AI's opening move. In local mode, removes one half-move. Recorded clock times are restored to the position being restored. Undo is available after checkmate or a rules-based draw; resignation, agreed draw, and timeout are final.
- **Flip board:** changes perspective without changing sides. Local play keeps this perspective between turns.
- **Resign:** asks for confirmation. In AI mode, the human resigns; in local mode, the side to move resigns.
- **Settings:** use the single **Settings** button below the board on desktop or mobile. Choose Green, Brown, or Blue board colors; toggle sound, coordinates, legal destinations, or move highlights. Settings persist in localStorage when available. The Cburnett piece set remains the single local set; check indicators remain visible when move highlights are off.
- **Sounds:** distinct WebAudio sequences for moves, captures, checks, castling, promotions, and game end. Audio starts after an interaction, subject to browser autoplay restrictions.
- **Game tab:** clickable SAN history and first/previous/next/last controls. Reviewing uses a separate chess.js position; it cannot alter the live game. **Back to live** restores play. AI replies and clocks continue during review and while settings are open.
- Player bars use White/Black labels instead of player names and show captured pieces by the capturing side and material advantage. Pawn = 1, knight/bishop = 3, rook = 5, queen = 9; promotions count toward the material balance. During review, captures reflect the reviewed position.
- **Clocks:** 10 minutes by default, with no increment. The active side counts down; reaching zero ends the game as a loss on time. The timer uses elapsed time rather than counting interval callbacks, so background tab throttling does not grant extra time. Clocks continue during promotion and API retries. No clock mode disables timeouts.
- **Game over:** a result card appears over the board, with New Game, Rematch, and close controls. Rematch reuses the current color, opponent, difficulty, and time control. Local players can offer and accept a draw; draw offers are disabled against Cristopher.

All legality comes from the unchanged chess.js integration, including castling, en passant, promotion, check, and checkmate. Stalemate, threefold repetition, insufficient material, and the 50-move rule end the game automatically, with a specific draw reason. Board input is locked during the AI turn, history review, or after the game ends. Pending replies cannot change a board after New Game, Undo, Resign, or timeout.

Desktop uses a board and tabbed game panel, without a navigation sidebar. At 600–999px the panel moves below the board. Under 600px the board fills the screen width and a fixed action bar provides Undo, Flip, and Resign. Piece movement and snap-back animations respect reduced-motion preferences. Promotion opens a vertical picker on its destination file; clicking outside or pressing Escape cancels.

## Project structure

```text
Chess/
  index.html
  css/variables.css     Design tokens, themes, base styles
  css/layout.css        Desktop/tablet/mobile layout and player bars
  css/board.css         Board, highlights, promotion, result overlay
  css/components.css    Controls, settings, move list, dialogs
  js/main.js             UI, central game state, game flow, audio
  js/board.js            Rendering, click/touch/drag, keyboard navigation
  js/game.js             Status, UCI formatting, material display, undo helpers
  js/cristopher.js       Random placeholder, API requests, response validation
  js/config.js          API configuration
  js/ui/clock.js        Elapsed-time clock and formatting
  js/ui/settings.js     Saved appearance and sound preferences
  js/ui/moveList.js     Clickable move history
  js/ui/panels.js       Tabs and popup positioning
  js/ui/icons.js        Original avatar SVG helpers
  js/ui/sounds.js       WebAudio note sequences
  assets/pieces/        Local SVG pieces, attribution, license
  vendor/chess.js       chess.js 1.4.0, browser ES module
  vendor/LICENSE-chess.md
  vendor/train.ipynb    Training, automatic champion saving, resume
  vendor/deploy.ipynb   Deployment only; Run all returns the public URL
  tests/index.html      Browser regression runner
  tests/tests.js
  tests/test_api.py     API regression checks
  tests/test_notebooks.py  Persistence and recovery checks
  tests/test_deployment_flow.py  Local deployment Run-all integration
  PHASE2_README.md      AI training documentation
  LICENSES.md           Asset sources and licenses
  README.md
```

## Connect to Cristopher

1. **Train:** open [vendor/train.ipynb](vendor/train.ipynb) in Colab (or VS Code with a Colab kernel), select a GPU runtime, and choose **Run all**. Allow Drive access. The default budget is three hours; the same run name resumes saved progress.
2. **Deploy:** open [vendor/deploy.ipynb](vendor/deploy.ipynb) in another Colab runtime and choose **Run all**. It loads the saved champion, starts FastAPI, opens a tunnel, tests both endpoints, and finishes by printing the verified **HTTPS URL**. It does not train or run an infinite heartbeat, and it leaves the API running. CPU inference is supported.
3. Paste that URL into **Settings → Connect to Cristopher → Server URL**, enable **Use AI server**, and press **Test connection**. Select AI, choose a difficulty, and press Play.
4. Keep the deployment runtime connected. To stop it, disconnect the runtime or call `shutdown_api()` in a new notebook cell. Cloudflare is the default; the deployment form also supports ngrok using the `NGROK_TOKEN` Colab secret or a hidden prompt.

### Automatic champion saving

GPU training writes resumable checkpoints about every **60 seconds**, after the current batch, at generation boundaries, and on recoverable exit. It retains the last three checkpoints, including the current population and in-progress games. Each new selected champion is exported during training, not just at the end; the initial baseline is also exported before training starts. Generation `-1` means no challenger has passed the existing promotion gate yet.

Snapshots are complete, immutable folders under `MyDrive/cristopher_evo/models/deployments/`. Only after all files are written does an atomic `models/latest_champion.json` pointer select the new bundle. Deployment checks its file hashes before loading it. An interrupted write leaves the previous published champion usable. Older bundles remain available; unchanged champions do not produce duplicate exports. Legacy flat exports are still accepted when no pointer exists. Classic mode retains its existing generation-winner selection and saves it after each completed generation.

A killed runtime cannot execute a final save: the last completed Drive save survives, while unsaved work since then may be lost. Run all in the training notebook again to recover, with the same Drive account, run name and experiment settings. Keep one training runtime per run name. Drive must remain mounted and writable.

Both notebooks use short Markdown instructions plus collapsed executable code cells: [Colab forms](https://colab.research.google.com/notebooks/forms.ipynb) and [Jupyter hidden-source metadata](https://nbformat.readthedocs.io/en/5.2.0/format_description.html#cell-metadata). Expand a cell to inspect its code; Markdown itself is not used to execute Python.

The URL changes when the tunnel restarts. Paste the new URL, test it, close Settings, and press **Retry** to continue a pending turn. A failed move leaves the board intact with Retry, Reconnect / change URL, and Undo. While waiting, board input is locked; **Cancel request** appears after five seconds. The existing game clock continues through connection failures and retries.

Offline mode is the default: `chess.useApi=false`. The URL defaults to `http://localhost:8000`; Settings saves it as `chess.apiUrl`. URLs are trimmed, trailing slashes removed, and only HTTP/HTTPS accepted. The `ngrok-skip-browser-warning: true` header accompanies every request. Automatic health checks run every 20 seconds only when the server toggle is on, the selected opponent is AI (or the current game is against AI), and the tab is visible. Local two-player games and hidden tabs stop automatic checks. A confirmed Connected status stays visible during background checks and changes only when a check fails or the mode changes. **Test connection** is an explicit manual probe and can check a URL in any mode without enabling API gameplay; its result explains when the reachable server is not used by the current game.

**If the API fails, use the local fallback bot** is optional and off by default. When enabled, a failed request produces a legal local move and a notice; explicit cancellation never triggers fallback. **Show engine info** is also off by default; enabling it reveals a collapsible evaluation/depth/time line beneath Cristopher. Evaluation is in pawns from White's perspective (`+0.35` favors White).

### Why the game worked without Colab

With **Use AI server** switched off, the browser runs a random legal-move bot entirely in JavaScript. It does not load your trained model or start an API. The status explicitly says **Offline mode · random bot (no API)**. A grey status dot means the API is inactive, not connected.

During development, a temporary **local test API** ran on `localhost:8000` using default test weights to verify the integration. That was a separate process on this computer, not your Colab session or trained champion, and it was shut down after the tests. Serving this website with `python3 -m http.server 8080` starts only the web page, never the AI API.

To use your own model, run **train.ipynb → Run all** first, then **deploy.ipynb → Run all**. Copy the HTTPS URL into Settings, enable the server toggle and select AI. The same instructions are under **How to start the API** in Settings.

### JavaScript interface

```js
const { move, info } = await getCristopherMove({ fen, history, difficulty });
const { ok, latency_ms, engine, version, error } = await checkHealth();
```

The move interface is unchanged. `history` is the full current game's UCI history from the starting position; omit it for a standalone FEN. A fresh chess.js instance verifies the returned UCI move against the request FEN, and the active board verifies it again on application. Stale replies after Undo, New Game, resignation, timeout, or a connection change cannot alter the board. `CristopherError.code` distinguishes `timeout`, `network`, `http`, `json`, `illegal`, and `cancelled`.

Client timeouts are configurable in `js/config.js`: `REQUEST_TIMEOUT_MS=15000`, `HARD_REQUEST_TIMEOUT_MS=30000`, and `HEALTH_TIMEOUT_MS=4000`. The server caps easy/medium/hard requests at 3/10/25 seconds, including lock wait. A timeout returns 504. The engine runs in a thread pool under a lock; native NumPy/Torch work may finish its current operation after the HTTP deadline, retaining the lock until it exits. Browser cancellation does not forcibly terminate server computation.

### API contract

**GET `/health`**

```json
{
  "status": "ok",
  "engine": "cristopher",
  "version": "cristopher-evo-1",
  "uptime_s": 42
}
```

**POST `/move`**, with `Content-Type: application/json`:

```json
{
  "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
  "history": ["e2e4"],
  "difficulty": "medium"
}
```

Example response:

```json
{
  "move": "e7e5",
  "info": { "eval": 0.35, "depth": 3, "nodes": 1800, "time_ms": 120 }
}
```

The API converts the export's side-to-move centipawn score to White-perspective pawns. If an engine returns an illegal move, a depth-1 search scores all legal successors, chooses the best, and adds `"fallback": true`. This server safeguard differs from the optional random browser fallback.

Errors use `{"error":"..."}`: invalid FEN, finished game, or mismatched history → **400**; invalid field types or difficulty → **422**; time cap → **504**; engine failure → **500**. **GET `/stats`** returns counters and the last 50 move requests, including errors, timestamps, FEN, difficulty, move, and elapsed time.

### Troubleshooting

- **CORS:** rerun the app and background-server cells. The notebook permits all origins, methods, and headers, including Content-Type and ngrok-skip-browser-warning. Use the base URL without `/move`.
- **URL changed:** copy the newly printed tunnel URL into Settings and test again. An old URL does not reconnect to a new Colab session.
- **Tunnel down:** check the notebook's local self-test, then rerun the tunnel cell and wait for its public health/move tests to print OK. If Cloudflare detects an existing config file, use a clean Colab runtime or move that config temporarily.
- **Mixed content:** an HTTPS webpage cannot call an ordinary HTTP server. Use an HTTPS tunnel URL; localhost is the development exception. Settings warns about this mismatch.
- **Missing files / runtime disconnected:** run the training notebook first, then reconnect Colab and Run all in the deployment notebook. Keep each snapshot’s engine, metadata and weights together. Deployment cannot prevent Colab runtime limits.
- **Timeout:** Retry after the engine finishes its previous request, choose a lower difficulty, or inspect `/stats`. Undo remains available under the existing game rules.

Implementation references: [Starlette thread pool](https://www.starlette.io/threadpool/) and [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Verification

With the static server running, open **http://localhost:8080/tests/**. This dependency-free browser runner checks rule scenarios, real UI interactions in an iframe, and mocked API requests. It does not connect to a real AI server. Each check reports pass/fail.

Validated in Chrome: all **31 browser checks pass**. Separate browser checks passed for mouse dragging, illegal snap-back, move/castling animations (both king and rook), actual stalemate and clock-timeout result overlays, and touch dragging at 390px width. Desktop and mobile screenshots were inspected; the page, vertical promotion picker, and Settings dialog fit without horizontal overflow. Other browsers and physical mobile devices have not been tested.

Coverage includes Scholar's mate; castling both ways for both colors and rejection through check; en passant; all promotion choices and cancellation; stalemate, repetition, insufficient material, and 50-move draws; SAN and capture rendering; keyboard navigation; automatic Black orientation; completed and pending AI undo; stale replies after New Game and resignation; API contract, headers, illegal replies, HTTP/network/JSON errors, timeouts, health, and Retry. The redesign adds checks for history review/live restoration, saved themes and display preferences, clock switching/restoration/timeout, no-clock mode, result cards, rematches, and local draw agreement.

Useful manual scenarios (choose **Local 2 players**):

| Scenario           | Moves / expected result                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scholar's mate     | `1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#`; White wins, Black king highlighted, input locked.                                                                  |
| Kingside castling  | `1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O Nf6`; drag e1 to g1 for the castle, verify rook on f1.                                                                 |
| Queenside castling | `1. d4 d5 2. Nc3 Nc6 3. Bf4 Bf5 4. Qd2 Qd7 5. O-O-O O-O-O`; kings on c1/c8, rooks on d1/d8.                                                                   |
| En passant         | `1. e4 a6 2. e5 d5 3. exd6`; d5 pawn disappears, capture/material update; Undo restores it.                                                                   |
| Promotion          | `1. a4 h5 2. a5 h4 3. a6 h3 4. axb7 hxg2 5. bxa8`; picker opens. Cancel, retry, and choose each piece using Undo between attempts.                            |
| Stalemate          | The browser runner verifies `7k/5Q2/6K1/8/8/8/8/8 b - - 0 1` reports “Game drawn / Stalemate.”                                                                |
| AI undo            | Make a move, wait for Cristopher, then Undo; both moves disappear. Repeat and Undo while “thinking…” is visible; no delayed move should appear.               |
| History            | After a few moves, click an earlier SAN move; the board is read-only and the live move count is unchanged. Use the arrows and Back to live.                   |
| Clock              | Select 3+0, verify that only the moving side counts down, and leave it to expire; the opponent wins on time. No clock shows ∞ and never flags.                |
| Mobile / keyboard  | At 390px width, check no horizontal overflow, tap and touch-drag moves, open the promotion picker and cancel outside; Tab to board and use arrows plus Enter. |

API regression tests run directly from the deployment notebook cells with default classic test weights (no training or Drive needed):

```sh
python -m pip install fastapi uvicorn nest_asyncio python-chess numpy httpx requests
python tests/test_api.py
# Optional local fixture for real frontend HTTP tests:
python tests/test_api.py --serve
```

All **9 API tests pass**. They cover all difficulties, invalid FEN, game-over and history errors, CORS, legal depth-1 fallback, evaluation perspective, concurrency, deadlines, lock retention after native-call timeouts, and the 50-entry log.

Additional local integration checks passed:

- The actual notebook background-server/self-test cell, including invalid FEN and finished-game HTTP 400 responses; rerunning replaces the server, and shutdown closes its thread.
- A complete **172-ply game** through the browser UI against the real local API, ending in a draw. Default classic test weights were used; every API move was checked for legality before application.
- Stopping the server mid-game: friendly error, Retry preserving the position, Undo, then changing the URL and reconnecting to resume the same game.
- Hard difficulty timeout handling over real HTTP with an injected 1 ms client deadline; the normal 30-second deadline was restored afterward. Delayed Cancel was checked with a deliberately pending transport, and offline placeholder play passed.
- GPU export loading and all three difficulties on CPU, including neural depth-1 fallback, using an existing small local test model. This does not establish GPU runtime performance or champion strength.
- The mobile Settings panel fits at 390px without horizontal overflow. Browser tests also verify the 20-second polling interval and hidden-tab cancellation with simulated visibility events.

**Not verified here:** Colab Drive mounting, live Cloudflare/ngrok tunnel creation and public URL tests, the user's actual exported champion, or long-term Colab connectivity. The tunnel cell includes public health and legal-move tests with retries to run in the connected Colab runtime. The existing evolution and promotion rules and vendored chess.js are preserved; checkpoint publication and notebook execution are updated for separate Run-all workflows.

## Third-party credits

- [chess.js 1.4.0](https://github.com/jhlywa/chess.js/tree/v1.4.0), Jeff Hlywa and contributors, BSD-2-Clause; local license in `vendor/LICENSE-chess.md`.
- Cburnett SVG chess pieces by Colin M. Burnett, GPL-2.0-or-later, sourced unchanged from Lichess; attribution and full license in `assets/pieces/`.
- All UI icons and avatars are original inline SVG; sounds are generated with WebAudio and fonts are system fonts. See [LICENSES.md](LICENSES.md). No Chess.com proprietary assets are used.

## Notebook workflow checks

```sh
python -m pip install torch nbformat
python -m unittest discover -s tests -p 'test_notebooks.py' -v
# Separate integration check: binds localhost:8000; Colab and tunnel provider are mocked.
python tests/test_deployment_flow.py
```

Local tests cover interrupted checkpoint writes, corrupted-checkpoint recovery, failed champion publication, deduplication, resume, and loading the saved champion without training. The training cells were executed sequentially with a tiny CPU configuration and local setup in place of Colab mounting/installations. Deployment Run all was executed twice against real local HTTP with simulated Colab and tunnel services, checking URL output, continued service, rerun cleanup, and explicit shutdown. These checks do not verify a three-hour CUDA session, actual Drive synchronization, the rendered Colab form UI, or a live public tunnel.
