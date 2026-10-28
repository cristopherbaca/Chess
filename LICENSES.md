# Asset licenses

- **Chess pieces:** Cburnett SVG set by Colin M. Burnett, downloaded unchanged from [Lichess lila / public/piece/cburnett](https://github.com/lichess-org/lila/tree/master/public/piece/cburnett). GNU GPL **version 2 or later**, as recorded in [Lichess COPYING.md](https://github.com/lichess-org/lila/blob/master/COPYING.md). The editable SVG sources are in `assets/pieces/`; full license: [`assets/pieces/LICENSE`](assets/pieces/LICENSE).
- **Rules engine:** chess.js 1.4.0, Jeff Hlywa and contributors, BSD-2-Clause. Full license: [`vendor/LICENSE-chess.md`](vendor/LICENSE-chess.md).
- **Navigation icons and avatars:** original inline SVG geometry created for this project. No Chess.com assets are included.
- **Sounds:** generated locally using WebAudio oscillators. No sampled audio or third-party sound files.
- **Fonts:** system fonts only; no downloaded fonts.
- **Research fixtures:** curated puzzle solutions and opening lines under `tests/validation/` come from the [Lichess open database](https://database.lichess.org/) and [Lichess opening database](https://github.com/lichess-org/chess-openings), released under CC0. Individual puzzle URLs, opening-source hashes and selection rules are recorded with the fixtures. Downloaded evaluation labels in the ignored `research_runs/` directory use the same CC0 database.
- **Endgame reference answers:** cached factual WDL results from the [Lichess tablebase API](https://github.com/lichess-org/lila-tablebase); no tablebase-server code is copied into the engine.
- **External research opponent:** official Stockfish 19 was downloaded to a temporary directory for independent benchmarking/label checks. Its executable and neural weights are not included in this repository or used for production move generation. Stockfish is GPL-3.0; the downloaded release includes its license/source references.

The interface uses the requested visual style and color palette. It does not include Chess.com's logos, icons, pieces, or sounds and is not affiliated with Chess.com.
