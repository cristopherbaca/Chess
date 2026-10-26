# Chess — Phase 2: CUDA neuroevolution

The default in [train.ipynb](vendor/train.ipynb) is now **GPU-based neuroevolution for a three-hour session**. PyTorch evaluates populations of neural chess evaluators on CUDA and performs Evolution Strategy updates from played-game rewards. CPU workers handle chess rules and prepare successor positions, preferably through compiled C++. Deployment is independent in [deploy.ipynb](vendor/deploy.ipynb); Run all there loads the saved champion and returns a URL.

## Run the GPU trainer

1. Open **train.ipynb** in Colab or select a Colab kernel in VS Code.
2. Select a **GPU runtime** and choose **Run all**. Allow access to your Drive.
3. The collapsed settings form defaults to GPU neuroevolution, the existing `gpu_es_v1` run, and a three-hour budget. Expand code only if you want advanced configuration.
4. Setup, engine definitions, training, champion export and a fresh-process legality test run in order. Progress reports CUDA usage and each newly saved champion. The same Run all resumes an interrupted run.

`gpu_require_cuda=True` prevents an accidental CPU-only training session. If CUDA is unavailable, select a GPU runtime; do not disable that check to make the error disappear. CPU test mode exists for local software verification, not as the default training path.

The three-hour timer covers the training invocation, including generation initialization. Setup and optional final benchmarks are separate. Completed generations, in-progress games, and model state are saved when the budget expires. Final benchmarks are disabled by default, so Run All does not append another long tournament.

## What uses the GPU

- A population of 64 positive/negative neural perturbations, plus the ES center, selected champion, fixed initialization and Hall-of-Fame opponents.
- Candidate-grouped, batched `torch.bmm` forward passes, using FP16 on CUDA and FP32 for ES updates.
- Mirrored Evolution Strategy perturbations and updates from rank-normalized match rewards. Tied fitness receives tied utility, so draws alone do not create arbitrary weight updates.
- Batches bucketed by actual position counts, avoiding padding every candidate to the size of a heavily queried shared opponent.

CPU workers prepare another, disjoint group of games while the GPU evaluates the current group. They do not initialize CUDA. The pinned MIT-licensed [Disservin chess-library](https://github.com/Disservin/chess-library), revision `2a608d58f44776909bb6e2c09505e97ba1451319`, accelerates legal move generation and feature encoding. If compilation fails, Python preparation remains available while neural evaluation still runs on CUDA. Each worker uses one BLAS thread; worker selection respects detected CPU quotas and an estimated RAM budget.

The memory settings are:

```python
CFG['gpu_target_vram_gb'] = 10.0
CFG['gpu_headroom_gb'] = 3.0
CFG['gpu_batch_rows'] = 4096
```

These are a **soft working-memory budget and chunk limit**, not a requirement to occupy 10 GB. Actual allocation depends on population, architecture, and available positions. The trainer reduces chunks on CUDA out-of-memory errors or an exceeded working budget. It does not allocate dummy tensors to fill VRAM. CPU preparation, transfer speed, and GPU kernel shape can still limit utilization; allocated VRAM is not a throughput measurement. Actual Colab GPU speed and memory use must be measured there.

## What evolves

The neural evaluator is a **784→512→256→1 ReLU MLP**. Its inputs contain 781 chess features plus three zero padding entries for tensor-core alignment:

- 768 side-to-move-oriented piece-square indicators;
- four own/opponent castling rights;
- eight legal en-passant file indicators;
- one normalized halfmove clock.

Its bounded residual, up to 600 centipawns in magnitude, augments a fixed material/PST prior. If `checkpoints/full_v1/best_champion.json` exists, its material and averaged piece-square terms seed that prior; otherwise handcrafted defaults do. This is not a conversion of old neural weights or the whole classic evaluation function. No Stockfish labels or supervised fitting are used in the default GPU trainer.

Training uses all legal successor positions in a fixed **one-ply** decision body. Terminal mate scores override neural scores; early-move temperature provides exploration. This deliberately prioritizes played games per hour over deep search during training. The exported player adds bounded batched beam lookahead for medium/hard play.

The gauntlet pairs colors on shared, seeded random 4–6 ply openings against JSBot, a separate random sample, default initialization, rotating population peers, a frozen champion, Hall of Fame and periodic low-Elo Stockfish anchors. Stockfish is an opponent only. Capped unfinished games receive neutral fitness and are marked unfinished; they are excluded from Elo and improvement evidence.

A candidate replaces the selected champion only if it wins its completed paired games against the frozen champion. This is a conservative short selection gate, **not statistical proof**. The ES center can keep evolving while the selected champion remains the default. Progress and export identify the selected champion's generation; `-1` means it has not been replaced. A meaningful improvement claim requires a separate, sufficiently large evaluation.

## JavaScript baseline

The existing `js/cristopher.js` selects uniformly among legal moves after a 400–800 ms delay. It has no hardcoded openings, evaluation heuristics, or saved move sequences. `JSBotPlayer` matches that distribution and terminal behavior; the UI delay is disabled during matches. Python and JavaScript do not share the same RNG sequence or move enumeration order.

The JS-derived opening book is empty. JSBot and the random baseline are the same strategy with different random samples, not different levels of strength. `vendor/chess.js` is the rules engine, not an AI model.

## Checkpoints and disconnect recovery

All persistent project files are under `/content/drive/MyDrive/cristopher_evo/`:

```text
checkpoints/gpu_es_v1/gpu_XXXXXXXX.pt       # last three snapshots
logs/gpu_es_v1/gpu_gXXXXXX/game_XXXXX.json # completed game records
pgn/gpu_es_v1/gpu_gXXXXXX/game_XXXXX.pgn
logs/gpu_es_v1/gpu_history.json
models/cristopher_gpu_worker.py
models/cristopher_gpu_children.cpp
models/cristopher_gpu_children.so          # runtime/platform-specific optional helper
models/chess.hpp                          # pinned header, including MIT license
models/latest_champion.json               # atomic pointer to a complete snapshot
models/deployments/<id>/manifest.json     # per-file checksums
models/deployments/<id>/cristopher_engine.py
models/deployments/<id>/cristopher_genome.json
models/deployments/<id>/weights.pt        # immutable selected neural champion
```

Checkpoints contain the ES center, initial and selected models, Hall of Fame, mutation sigma, perturbation seeds, RNG state, prior, generation, settings, and every in-progress move history. They are written about every 60 seconds after the current batch, after each generation, and on a recoverable stop/error. The selected champion is published before training and after every promotion using immutable bundles plus an atomic pointer; older bundles remain available. A hard runtime kill cannot trigger a final save, so only completed Drive writes are recoverable. Completed result files and PGNs are also written per game. A sudden runtime loss can lose recent unsaved moves, but finished game records are recovered.

To resume:

1. Reconnect to a GPU runtime and mount the same Drive.
2. Open **train.ipynb** with the same run name, architecture and experiment settings.
3. Choose **Run all**. It restores the population and unfinished games automatically.

Use one runtime per run name. Press Stop once to save early; pending CPU preparation may need a moment to finish. Closing VS Code does not guarantee a graceful shutdown. Keep the same CUDA/CPU device family for perturbation generation when resuming; CPU-only tests are separate experiments. Changing architecture/population/reward settings requires a new run name. Session duration, workers and inference chunk sizes can change without invalidating the checkpoint, although floating-point execution and throughput can differ.

Previous classic and neural checkpoints remain in their original directories. The new default GPU run is separate. Its own checkpoints cannot be resumed by the classic trainer.

## Two compact notebooks

**train.ipynb:** settings → Drive/runtime setup → engine definitions → train/resume → verify saved champion. Code is collapsed using Colab forms and Jupyter/VS Code metadata. It never starts the API. The default Run all does not run optional lengthy benchmarks or interactive quick play.

**deploy.ipynb:** load saved champion → build API → start/self-test server → start/test tunnel and print URL. It does not train, wait in a heartbeat loop, or shut itself down. It verifies the selected snapshot’s hashes; old flat exports are supported if no snapshot pointer exists. Keep its runtime connected and use the URL in the web game's Settings. To stop, call `shutdown_api()` or disconnect the runtime.

`QUICK_TEST=True` remains an advanced small-run configuration inside the training settings cell. CUDA is still required by default. Existing evaluation routines remain available in the generated worker module for separately requested benchmarks; they are not part of Run all.

## Export contract

The exported module needs `torch`, `numpy`, and `python-chess`. CUDA accelerates inference; CPU inference is supported.

```python
engine = CristopherEngine('/path/to/cristopher_genome.json')
result = engine.get_move(fen, history=None, difficulty='medium')
# {"move": "e2e4", "info": {"eval": 24.0, "depth": 2, "nodes": 120, "time_ms": 80}}
```

Scores are centipawns from the moving side's perspective. History must contain legal UCI moves from the standard starting position and reach the supplied FEN; custom positions may use `None`. Mate-in-one takes priority, repetition is avoided when ahead where an alternative exists, and promotions include their UCI suffix. Positions with no legal moves raise a game-over error.

GPU-mode easy samples top moves with occasional inaccuracies; medium/hard use bounded 2/3-ply beam lookahead, with configured time budgets. This differs from classic alpha-beta. Deadlines are checked between expansions; completing a batched evaluation can slightly exceed them. The separate deployment notebook wraps this export in the HTTP API.

## Classic mode

Set `TRAINING_MODE='classic'` in the training settings form to use the previous CPU-only, 787-gene genetic algorithm. It retains material, tapered PSTs, mobility, pawn structure, king shield/tempo, alpha-beta, crossover/mutation, and its original checkpoint signature. Its optional NumPy stage-2 definitions remain CPU-only and are not run by the default notebook workflow. Choosing classic mode will not use CUDA. The current default is the new GPU mode.

## What was verified locally

The local environment has **no CUDA device**. Verification therefore used explicitly enabled CPU test mode with a small network, exercising the same batched tensor and ES code, multiprocessing, interruption during a game, checkpoint reload, two complete generations, and exported inference on five special FENs. Grouped inference was compared against individual-network forward passes; tied rewards leave the ES center unchanged; non-tied rewards update it. The CUDA-required guard was checked to reject CPU-only production training.

The native feature preparer compiled locally and matched Python move lists, features and terminal values on 55 positions, including castling, en passant, promotion and history. Colab authentication/mounting, Linux compilation, real CUDA kernels, FP16 numerical behavior, VRAM/OOM recovery and GPU throughput remain unverified on actual Colab hardware. No playing-strength improvement or Elo is claimed from these software checks.
