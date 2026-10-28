# Architecture assessment — 2026-10-27

This is the initial inspection requested by [PHASES.md](../PHASES.md), written before engine changes. The first milestone is a bounded correctness improvement and a reproducible baseline, not completion of all twelve phases. The user's existing trained weights, experiment identity and evolution pipeline must remain usable.

## Existing architecture

| Component | Implementation and role |
| --- | --- |
| Application | Plain HTML/CSS and JavaScript ES modules. `js/main.js` owns game flow; `js/board.js` renders the board. No frontend framework or build step. |
| Browser rules | Vendored chess.js 1.4.0 handles legal moves and game outcomes. `js/game.js` exposes application helpers. |
| Browser AI boundary | `js/cristopher.js` runs a random legal-move placeholder or calls the HTTP API and validates returned UCI moves. It does not load neural weights. |
| Training orchestration | `vendor/train.ipynb`: settings, Colab/Drive setup, generated standalone worker modules, training/resume and export verification. Most engine code lives in named source strings inside `train-engine`. |
| Python board/rules | `python-chess`: bitboards, legal move generation, push/pop, terminal and history checks. `CORE_SOURCE` supplies validated FEN/history reconstruction. |
| Native rules/preparation | Pinned Disservin chess-library header. `CPP_SOURCE` implements classical evaluation/search; `GPU_NATIVE_SOURCE` prepares neural input features and legal successors. Both are compiled optionally. |
| Classical evaluation | `EVAL_SOURCE`: 787 configurable genes; material, phase-interpolated PSTs, attack mobility, bishop pair, rook files, doubled/isolated/passed pawns, king shield and tempo. |
| Classical search | `SEARCH_SOURCE` and `CPP_SOURCE`: negamax alpha-beta, iterative deepening, quiescence, TT, mate-distance scores, MVV/LVA-style ordering, killers, history and time/node limits. |
| Classical genetics | `GA_SOURCE`: seeded populations, mutation, BLX/uniform crossover, elitism, tournament selection, diversity/novelty, paired matches, PGN/result logging and resumable checkpoints. |
| Neural evaluation | `GPU_SOURCE`: 784→4608→2432→1 dense MLP, 14,828,801 parameters. Fixed material/PST prior plus bounded neural residual; FP16 CUDA inference, FP32 state. This is not NNUE. |
| Neural optimization | Mirrored evolution strategies, 64 perturbed candidates, center and reference opponents; one-ply game decisions. Updates use ranked game rewards. |
| Neural deployment search | `GpuCristopherEngine`: all root moves, then material/PST-selected beam width 4/8 for medium/hard, maximum depth 2/3. Easy samples one-ply evaluations. No alpha-beta or quiescence in this path. |
| Persistence | Atomic checkpoints, last-three retention, immutable exported bundles, SHA-256 manifests and a last-written `latest_champion.json` pointer. |
| Deployment | `vendor/deploy.ipynb`: FastAPI/Pydantic, Uvicorn, one locked engine instance, HTTP validation/deadlines/logging, Cloudflare or ngrok tunnel, local/public self-tests. No production move selection delegated to Stockfish. |

Dependencies are Python, NumPy, python-chess, PyTorch for the GPU path, optional C++17 compiler/header, Stockfish as a training opponent, and FastAPI/Uvicorn/nest_asyncio/requests for serving. Tests additionally use httpx and nbformat. Training setup also installs tqdm and matplotlib. The notebook uses Python source generation to remain portable in Colab; a package extraction must preserve standalone Run all and exported-model loading.

## What already works and should be preserved

- Reuse the existing board libraries and make/unmake operations. Writing another rules engine has no demonstrated benefit here.
- Preserve the independent classical engine, its configurable genome and genetic operators.
- Preserve the trained neural architecture and weights, the 22-generation experiment reported by the user, and its recovery identity. A search change should not reset training.
- Preserve API/FEN/UCI contracts, frontend legal validation, collapsed notebooks, runtime separation and snapshot verification.
- Retain paired colors/openings, reproducible seeds and PGN/result artifacts. These are useful foundations for controlled comparisons.
- Keep Stockfish limited to benchmarking, optional future labels and training opposition.

## Strength limitations and correctness risks

1. **The active neural search discards replies before checking their terminal value.** It ranks interior children only by the fixed material/PST prior. A mating move can fall outside the beam even though terminal scores are handled correctly for retained leaves. Checked positions also lose legal evasions to the width limit. Immediate tactical consequences should precede heuristic pruning.
2. **The two search paths are disconnected.** The classical path already has many Phase 3 foundations, but the deployed neural model does not use them. Dense 14.8M evaluation per leaf makes a direct scalar alpha-beta substitution potentially slow; this needs measured evaluation/search separation rather than an untested replacement.
3. **Training and serving search different trees.** Evolution scores one-ply decisions; deployment uses two/three-ply beams. Optimizing one does not establish strength for the other.
4. **Champion evidence is weak.** Neural promotion uses a small set of completed training games against the incumbent with mean score >0.5. It reuses selection games and is not an independent significance test. Classic mode publishes each generation's best, not a statistically verified all-time champion. Neither meets the stronger promotion requirements in PHASES.md yet.
5. **No tactical/strategic baseline or durable perft suite.** Existing tests concentrate on application, API and persistence. Some evaluation symmetry, legal moves and native/Python equivalence checks live inside notebook cells, but there is no standalone, versioned search benchmark with fixed positions and before/after artifacts.
6. **Potential search costs need profiling.** Python TT keys sort the entire repetition-count map per node; the native key also mixes that history. Tables are cleared wholesale at a threshold. Neural search copies boards with history, rebuilds features and recomputes shallower expansions. TT replacement, incremental state and reduced allocation are follow-up work, not measured bottlenecks yet.
7. **Large-network memory is more than one weight file.** Candidates, mirrored noise, FP32 state, activation batches and construction temporaries all contribute. Adaptive evaluation chunking cannot fix every population-construction OOM.
8. **Draw policy needs explicit cross-path tests.** Classic training uses claimable draws; GPU/application paths generally use actual repetition/fifty-move state. Tests must distinguish those policies before changing semantics. Do not silently alter the game's rules.
9. **Operational limitations remain.** Deployment loads an immutable snapshot once; code updates in the repo do not patch already-exported engines. The API is temporary, unauthenticated and single-engine serialized. There is no engine UCI command loop.

Missing planned components include PVS, aspiration windows, SEE, safeguarded null-move/LMR/futility, a reusable evaluator/search interface, NNUE accumulators or quantization, independent promotion matches, statistically grounded relative Elo reports, and a broad tactical/endgame suite. These should be introduced and compared individually.

## First implementation milestone

**Priority: prevent the neural beam from pruning immediate terminal outcomes and legal check evasions, and establish rule/search regression tests.** This directly addresses the currently deployed model without changing its weights, training decisions or checkpoint signature. Preserve the existing beam search outside the protected cases; do not bundle unrelated pruning or evaluation changes.

Before changing the engine, reproduce the failure with a legal FEN and the existing material/PST evaluator. Add known-count perft cases, make/unmake and hash restoration checks, draw/terminal cases, and search deadline coverage. Record deterministic fixed-depth/fixed-evaluator results before and after; distinguish correctness evidence from speed and Elo claims. Existing API and checkpoint tests must continue to pass.

Updating the generated source only affects newly published bundles. Document the re-export path explicitly; do not mutate immutable deployed bundles or imply that rerunning an unchanged deployment can repair an old exported module.

## Following milestones

1. Establish a modular search/evaluation boundary and instrument node types, evaluations, TT hits and phase timings; compare classical and neural evaluators at fixed budgets.
2. Extend the classical search incrementally (PVS first, then aspiration windows), comparing each change against the unchanged baseline and maintaining Python/native parity.
3. Introduce independent, color-paired champion validation with an explicit statistical acceptance rule and immutable incumbent retention.
4. Expand tactical/endgame fixtures and targeted evaluation-direction tests; add evaluation terms only when nonredundant and supported by evidence.
5. Evaluate NNUE-style sparse/incremental inference after the search baseline is stable. Retain the current dense model as a supported backend and comparison baseline.

## Evidence available at inspection

The repository contains 31 browser checks, 9 API tests, 9 notebook/persistence tests and one deployment-flow test, plus inline notebook checks. Previous documented results used local fixtures and small CPU networks. No fresh test results, new CUDA measurements or Elo estimates are asserted by this initial assessment. First-milestone measurements and executed tests will be recorded separately.

Reference positions for rule validation should be traced to primary project test data, such as the [chess-library repository](https://github.com/Disservin/chess-library) and [emacs-chess perft tests](https://github.com/jwiegley/emacs-chess/blob/master/chess-perft.el). Reference perft counts validate rule traversal, not playing strength.
