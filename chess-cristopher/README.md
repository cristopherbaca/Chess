# Cristopher Chess — Phase 1

A responsive chess frontend in plain HTML, CSS, and vanilla JavaScript ES modules. No framework, package installation, or build step. Cristopher currently chooses random legal moves after a 400–800 ms delay. No Python AI or API server is included.

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
- **New Game tab:** White, Random, or Black; Cristopher (AI) or Local 2 players; Easy, Medium, or Hard; No clock, 3+0, 5+0, or 10+0. Press **Play** to start. Black starts at the bottom when selected. Difficulty is passed to the unchanged AI module but does not affect the random placeholder.
- **Undo:** in AI mode, removes your last move and the AI reply, or just your move if a reply is pending. A human playing Black keeps the AI's opening move. In local mode, removes one half-move. Recorded clock times are restored to the position being restored. Undo is available after checkmate or a rules-based draw; resignation, agreed draw, and timeout are final.
- **Flip board:** changes perspective without changing sides. Local play keeps this perspective between turns.
- **Resign:** asks for confirmation. In AI mode, the human resigns; in local mode, the side to move resigns.
- **Settings:** open the gear icon or mobile **Menu**. Choose Green, Brown, or Blue board colors; toggle sound, coordinates, legal destinations, or move highlights. Settings persist in localStorage when available. The Cburnett piece set remains the single local set; check indicators remain visible when move highlights are off.
- **Sounds:** distinct WebAudio sequences for moves, captures, checks, castling, promotions, and game end. Audio starts after an interaction, subject to browser autoplay restrictions.
- **Game tab:** clickable SAN history and first/previous/next/last controls. Reviewing uses a separate chess.js position; it cannot alter the live game. **Back to live** restores play. AI replies and clocks continue during review and while settings are open.
- Player bars show captured pieces by the capturing side and material advantage. Pawn = 1, knight/bishop = 3, rook = 5, queen = 9; promotions count toward the material balance. During review, captures reflect the reviewed position.
- **Clocks:** 10 minutes by default, with no increment. The active side counts down; reaching zero ends the game as a loss on time. The timer uses elapsed time rather than counting interval callbacks, so background tab throttling does not grant extra time. Clocks continue during promotion and API retries. No clock mode disables timeouts.
- **Game over:** a result card appears over the board, with New Game, Rematch, and close controls. Rematch reuses the current color, opponent, difficulty, and time control. Local players can offer and accept a draw; draw offers are disabled against Cristopher.

All legality comes from the unchanged chess.js integration, including castling, en passant, promotion, check, and checkmate. Stalemate, threefold repetition, insufficient material, and the 50-move rule end the game automatically, with a specific draw reason. Board input is locked during the AI turn, history review, or after the game ends. Pending replies cannot change a board after New Game, Undo, Resign, or timeout.

Desktop uses a slim navigation rail, board, and tabbed side panel. At 600–999px the panel moves below the board. Under 600px the board fills the screen width and a fixed action bar provides Undo, Flip, Resign, and Menu. Piece movement and snap-back animations respect reduced-motion preferences. Promotion opens a vertical picker on its destination file; clicking outside or pressing Escape cancels.

## Project structure

```text
chess-cristopher/
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
  vendor/LICENSE-chess.js
  tests/index.html      Browser regression runner
  tests/tests.js
  LICENSES.md           Asset sources and licenses
  README.md
```

## Switch to the real API

1. Implement and run the API separately using the contract below.
2. Edit `js/config.js`, set `USE_API: true`, and set `API_URL` to the server's base URL (without `/move`).
3. If necessary, add headers to `EXTRA_HEADERS`. For ngrok, use `{ "ngrok-skip-browser-warning": "true" }`.
4. Configure the API's CORS policy to allow the frontend's origin, `GET`, `POST`, `OPTIONS`, `Content-Type`, and any extra headers. Use an HTTPS API when hosting the frontend on HTTPS.
5. Reload the page. The Connection indicator pings `/health` immediately and every 30 seconds while the page is visible. A failed move leaves the position intact and displays a **Retry move** button.

```js
export const CONFIG = {
  USE_API: false, // Change to true to enable fetch requests.
  API_URL: "http://localhost:8000",
  REQUEST_TIMEOUT_MS: 15000,
  EXTRA_HEADERS: {},
};
```

This is browser-visible configuration: do not place private API secrets in it. Extra headers apply to both health and move requests. Each request has a 15-second timeout, including reading the response body. Network failures, non-success HTTP responses, invalid JSON, malformed UCI, and illegal moves produce recoverable errors. A failed health check changes the indicator; it does not itself stop a move request.

### JavaScript interface

```js
import { getCristopherMove } from "./js/cristopher.js";

const { move, info } = await getCristopherMove({
  fen: "...",
  history: ["e2e4", "e7e5"],
  difficulty: "medium",
});
// move: "g1f3" or a promotion such as "e7e8q"
// info: optional object supplied by the API; currently not displayed
```

`history` contains the full current game's moves in UCI, not SAN. Difficulty is `easy`, `medium`, or `hard`. Move strings must use lowercase squares and a lowercase `q`, `r`, `b`, or `n` promotion suffix where required. A fresh chess.js instance validates each API reply before it reaches the UI; the active game then applies it with chess.js again.

### HTTP contract

**POST `{API_URL}/move`**

Request (`Content-Type: application/json`):

```json
{
  "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
  "history": ["e2e4"],
  "difficulty": "medium"
}
```

Successful response:

```json
{
  "move": "e7e5",
  "info": { "eval": 0.3, "time_ms": 120 }
}
```

**GET `{API_URL}/health`**

```json
{ "status": "ok" }
```

## Verification

With the static server running, open **http://localhost:8080/tests/**. This dependency-free browser runner checks rule scenarios, real UI interactions in an iframe, and mocked API requests. It does not connect to a real AI server. Each check reports pass/fail.

Validated in Chrome: all 25 browser checks pass. Separate browser checks passed for mouse dragging, illegal snap-back, move/castling animations (both king and rook), actual stalemate and clock-timeout result overlays, and touch dragging at 390px width. Desktop and mobile screenshots were inspected; the page, vertical promotion picker, and Settings dialog fit without horizontal overflow. Other browsers and physical mobile devices have not been tested.

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

The actual Python API is outside Phase 1; API behavior is verified with browser-side mock responses, including failures.

## Third-party credits

- [chess.js 1.4.0](https://github.com/jhlywa/chess.js/tree/v1.4.0), Jeff Hlywa and contributors, BSD-2-Clause; local license in `vendor/LICENSE-chess.js`.
- Cburnett SVG chess pieces by Colin M. Burnett, GPL-2.0-or-later, sourced unchanged from Lichess; attribution and full license in `assets/pieces/`.
- All UI icons and avatars are original inline SVG; sounds are generated with WebAudio and fonts are system fonts. See [LICENSES.md](LICENSES.md). No Chess.com proprietary assets are used.
