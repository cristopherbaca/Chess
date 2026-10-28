> Historical architecture reference. For current fresh 30M defaults and public deployment, use [FULL_PIPELINE.md](FULL_PIPELINE.md) and [PUBLIC_DEPLOYMENT.md](PUBLIC_DEPLOYMENT.md).

# Chess engine implementation and operation

Implementation snapshot: October 27, 2026. **Updated October 28:** the default Colab workflow is now `full_pipeline`; follow [FULL_PIPELINE.md](FULL_PIPELINE.md) for current training and deployment instructions. The dense-mode instructions below describe the retained legacy mode. This document supersedes the search and promotion descriptions in the October 26 PDF. The PDF remains a historical explanation of the dense architecture and deployment pipeline.

## What changed for your existing model

The dense network remains **784 → 4608 → 2432 → 1, 14,828,801 parameters**. Its learned tensors, residual evaluation prior, evolution algorithm, run name and checkpoint signature are preserved. Existing champions remain usable even if they have not passed the new validation protocol.

Medium/hard deployment uses the new shared alpha-beta engine. Easy retains sampled one-ply play. Dense evolution still uses batched one-ply games for training fitness; independent search-based games now decide promotion. More search code does not retroactively train the tensors, and generation count is not an Elo rating.

1. Open the updated `vendor/train.ipynb` and keep your saved run settings. The current form retains `TRAINING_HOURS = 2.5`.
2. Run all. It resumes your checkpoints and republishes the incumbent with current engine code. It does not restart the network. If you only want to republish, run configuration, setup and engine preparation, then **Verify the saved champion**, skipping training.
3. Run all in the updated `vendor/deploy.ipynb`. It verifies the bundle hashes, loads the model, reports `shared-alpha-beta-v2` and validation status, starts the API and prints the tested HTTPS URL.
4. Paste the URL into game Settings, enable the server toggle and choose AI.

Rerunning deployment alone cannot upgrade source code inside an old immutable model bundle. Deployment loads one snapshot; rerun it after publishing another. Keep one writer per run and save folder. Different training runs share the default latest-model pointer; use separate Drive roots when experimenting with a different architecture so each run keeps its own selected deployment.

## Phase-by-phase implementation

| Requirement | Implementation | Evidence or boundary |
| --- | --- | --- |
| 1. Audit | `ARCHITECTURE_ASSESSMENT.md`, `MILESTONE_01.md` | Original system, bottlenecks and first regression fix documented before this implementation |
| 2. Rules/core | `chess_ai/board.py`, existing python-chess bitboards | Reuse legal generation; incremental Polyglot hash, legal-EP repetition identity, full history, make/unmake, special moves, draw rules; reference perft tests |
| 3. Search | `chess_ai/search.py` | Negamax, iterative deepening, quiescence, TT, PVS, aspiration, killers/history/countermoves, SEE, mate distance, budgets; optional null, LMR, futility, check extensions |
| 4. Evaluation | `chess_ai/evaluation.py` | Configurable middlegame/endgame weights, inspectable features and interchangeable evaluators; direction/symmetry tests |
| 5. Genetics | `chess_ai/training.py`, existing notebook GA/ES | Parameter crossover, mutation, elitism, tournament, diversity, checkpoint/RNG resume, multiple opponents; original dense and classic trainers retained |
| 6. Neural | `chess_ai/neural.py`, `tools/train_nnue.py`, `tools/label_positions.py` | Separate sparse king-bucket network, incremental CPU accumulators, quantization, labeled mini-batch training, grouped validation and checkpointing; no trained-strength claim |
| 7. Tactics/strategy | `tests/tactics.json`, benchmark tool | All 16 requested themes represented; 13 scored tactical targets and 3 strategic diagnostics without an asserted best-move oracle; some themes share positions |
| 8. Self-play | `chess_ai/matches.py`, notebook bridge | Paired colors/openings, clocks, PGNs, evaluation traces, resumable games, errors, independent promotion evidence |
| 9. Profiling | `tools/benchmark_engine.py` | Nodes, depth, time, TT hit rate, qnodes, evaluation calls, move generation/evaluation time and Python peak allocation; dense deployment reduced to one inference bank |
| 10. Interface | `chess_ai/runtime.py`, `uci.py`, both notebooks | API contract preserved; UCI start/ready/position/go/stop/quit, clocks and option switches; standalone exports tested |
| 11. Measurement | `tools/run_match.py`, benchmark reports | Versioned source fingerprints, W/D/L, paired score intervals, relative Elo intervals, optional external UCI opponents |
| 12. Iteration | Feature switches, ablations, promotion gates | Correctness and smoke evidence recorded; long controlled strength testing remains necessary |

The existing C++ backend remains a legacy classic-training option. New search/evaluation modules are Python and reuse python-chess; they are not a rewrite of the C++ engine. Single-threaded search is the current baseline. Multithreaded search and an optimized SIMD integer neural kernel are not required for this baseline and have not been added.

## Search and evaluation

A search operates on its own board copy and restores each move in a `finally` block. A bounded transposition table stores depth, bound type, move and generation. Keys include repetition context and the halfmove clock so positions with different draw rights do not share unsafe scores. Mate scores are normalized by ply when stored/retrieved. Quiescence examines captures and promotions and all legal evasions when checked. Search returns the last completed iteration on a deadline, stop request or node limit; if none completes, it returns a legal fallback with depth zero.

Defaults enable PVS, aspiration and ordering by TT moves, tactical scores/SEE, killers, history and countermoves. Integer centipawns make unit-width PVS windows meaningful. These are correctness-tested search/order features; their speed benefit depends on the position. SEE uses legal recaptures and is only an ordering estimate, never proof for capture pruning.

Selective features are individually switchable and **disabled by default**:

- Null move: non-PV nodes outside check, sufficient non-pawn material, rook/queen present, safe score window; verification for deeper searches and no fictitious repetition/fifty-move claims inside a null subtree.
- LMR: late quiet non-checking moves at non-PV nodes; re-search when the reduced result improves alpha.
- Futility: shallow quiet non-checking moves at non-PV nodes, after at least one move was searched.
- Check extension: at most two per line.

Tests exercise actual cutoffs/reductions, not just flag construction. Their ablations use PVS as a prerequisite baseline; other single-feature comparisons use plain alpha-beta. None is described as an established Elo gain.

The classical evaluator covers material and imbalance; tapered piece activity; pawn isolation, doubling, chains, connections, backward/candidate/passed pawns; mobility, development, center control, outposts, rook files/seventh rank and trapped pieces; pawn shelter, king-ring pressure, open files and attackers; weak squares/color complexes, space, coordination, blockades and king activity. `ClassicalEvaluator.explain(board)` returns contributions for inspection. Weights are named `(middlegame, endgame)` pairs and finite values are validated. They are starting hypotheses to tune, not expert-quality weights established by match results.

## Training and champion protection

Select `parameter_evolution` in the training notebook to evolve the new classical weights. It uses `parameters_v1` by default, separate from dense checkpoints. The default population is 8, with 2 elites, tournament selection, blended crossover, bounded mutations and a diversity adjustment. Fitness opponents include the fixed baseline, incumbent and a rotating peer; colors and openings are balanced. RNG/population state is saved, and per-game files let an interrupted match resume. Three parameter checkpoints are retained.

Classic and dense notebook trainers also use the new independent validation gate. A higher training score only nominates a challenger. Validation uses separate seeded openings, two colors per opening and the same search budget for both sides. By default it requires at least **32 complete pairs** and a conservative lower confidence bound above 50%. Capped/unfinished games and error games cannot qualify. A strict gate may reject many candidates; that is expected.

For pair score mean `m` over `n` independent opening pairs, the one-sided lower bound is:

```text
max(0, m - sqrt(log(1 / alpha_attempt) / (2*n)))
alpha_attempt = 0.05 / (attempt * (attempt + 1))
```

The attempt counter spends a bounded total false-positive budget across training promotions. The statistical interpretation assumes independent sampled openings; seeded reproducibility does not itself prove that a small opening distribution represents real play. Match reports describe this limitation, complete/error counts and relative rating uncertainty. Reports with fewer than 10 valid pairs omit Elo intervals; the promotion minimum is higher. Infinite rating interval endpoints are represented by `null`. Reported Elo is only relative to that opponent and control.

GPU checkpoints are saved after batches, normally around 60 seconds, at generation boundaries and recoverable exits. The incumbent export exists before training. Immutable bundles are published through an atomic latest pointer only after their files and hashes are complete. A hard runtime kill can lose work after the last completed Drive write; it cannot execute cleanup. Existing historical champions are not relabeled as verified merely by loading them.

Match manifests identify the candidate, incumbent, configuration, gate attempt and engine source hash. Resume refuses mismatched manifests. Notebook validation uses source-version directories, so updating engine code starts fresh validation without discarding trained weights. The engine bundle is generated from canonical modules with `python tools/sync_engine.py`; `--check` detects stale notebook code.

## Optional sparse neural experiment

This original implementation uses 16 king buckets × 12 piece planes × 64 squares, with a shared sparse feature layer and two perspective accumulators. Default hidden width is 64. A move adds/removes changed piece features; changing a perspective's king bucket refreshes that accumulator. Undo restores its saved accumulators. A clipped activation and output layer produce side-to-move centipawns. This is separate from the dense 14.8M champion.

Optional quantization stores first-layer weights as int16 and uses int32 accumulators, with a float output layer. It reduces first-layer storage; it is not a fully integer SIMD engine and no speedup is claimed. Incremental and full-refresh evaluation are tested against each other for ordinary moves, castling, en passant, promotion, king moves and undo.

The learning tool accepts JSONL records such as:

```json
{"game_id":"game-001","fen":"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1","cp_white":20,"result_white":0.5}
```

Provide `cp_white`, `result_white`, or both. Position scores use `tanh(cp/400)`; game results use `2*result-1`. When both exist their targets are averaged and converted to the side-to-move perspective. Games, not individual rows, determine the validation split. At least two distinct game IDs are required; a useful real dataset needs much more independent data and position variety. Duplicate positions across different games can still cross the split; data curation remains necessary.

```sh
# Outcome labels from finished PGNs; optionally add --engine /absolute/path/to/engine.
python tools/label_positions.py --pgn /path/games.pgn --output /tmp/chess-labels.jsonl
python tools/train_nnue.py --data /tmp/chess-labels.jsonl --output /tmp/chess-nnue --epochs 20
# Reuse the same arguments/output to resume. Increasing epochs extends training.
python -m chess_ai --model /tmp/chess-nnue/best_validation.npz
# Optional blended evaluator:
python -m chess_ai --model /tmp/chess-nnue/best_validation.npz --evaluator hybrid
```

The trainer uses Adam mini-batches and saves best validation weights plus optimizer/RNG state each epoch. Validation loss alone does not publish a champion. For a quantized candidate, save `SparseEvaluator.load(path).quantized().save(new_path)` and validate that exact file.

The incremental feature/accumulator and quantization principles were researched from the [official NNUE developer documentation](https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html). No Stockfish source or network is embedded in the production move selector. The [Stockfish developer guidance](https://official-stockfish.github.io/docs/stockfish-wiki/Developers.html) also motivates incremental, measured changes; resemblance of architecture does not establish comparable strength.

## Matches, UCI and deployment exports

```sh
# Same saved models, colors and openings, fixed budgets; interrupted games resume.
python tools/run_match.py --candidate /path/candidate.npz --incumbent /path/incumbent.npz \
  --output /tmp/chess-match --pairs 64 --seconds .25 --nodes 10000 --max-plies 400
# One selective feature versus its PVS prerequisite baseline:
python tools/run_match.py --candidate-feature lmr --output /tmp/lmr-match --pairs 32
# Optional independent external benchmark opponent (never production move generation):
python tools/run_match.py --incumbent-uci /absolute/path/to/engine --output /tmp/external-match
```

For a hybrid match, specify `--candidate-evaluator hybrid` (and incumbent evaluator as appropriate). Default saved `.npz` loads its neural evaluator; classical JSON selects its own evaluator. Dense exported metadata also loads its matching evaluator with unchanged weights. UCI handles `uci`, `isready`, `ucinewgame`, `position startpos/fen ... moves ...`, `go depth/nodes/movetime/wtime/btime/...`, `stop`, `setoption`, and `quit`. Chess960, ponder and MultiPV are not supported.

To deploy a modular `.npz` or classical weights JSON, create a bundle compatible with the same deployment notebook:

```sh
# Explicitly initialize an EMPTY experimental model directory; not a strength claim.
python tools/export_model.py --model /path/incumbent.npz --models-dir /tmp/experiment/models --initial
# Once a challenger has accepted evidence against that incumbent:
python tools/export_model.py --model /path/candidate.npz --models-dir /tmp/experiment/models \
  --validation /tmp/chess-match
```

`--initial` refuses to replace an existing pointer. Normal publication requires complete accepted evidence matching the candidate file, incumbent, current implementation and deployed settings. Add `--hybrid` only when validation used the hybrid. Copy the complete models directory into your chosen Drive deployment root (or set `MODEL_ROOT` in the deployment cell); keep metadata, source, weights and manifest together. Classical and sparse inference need NumPy/python-chess; Torch is installed only for dense `.pt` exports. Automatic training exports still use the existing Drive root.

## Evidence and practical limits

The tests cover reference perft (initial depth 4 = 197,281; Kiwipete depth 3 = 97,862), legal special moves, incremental hashes and repetition, make/unmake, bounded search and mate scoring, evaluator directions, sparse accumulator/quantization parity, serialization, real tiny neural/genetic runs, checkpoints/resume, promotion rejection, UCI, standalone exports and API integration. Sequential training-cell tests use tiny CPU configurations and local directories; deployment tests simulate Colab/tunnel services and exercise real local HTTP with cleanup.

The full-size CPU smoke report uses freshly initialized **14,828,801-parameter weights**, not your Drive champion. It confirms a single inference network and legal easy/medium/hard moves. In that run medium completed depth 2 around 0.50 seconds and hard depth 3 around 2.50 seconds. Most measured search time was dense evaluation. Changing the search architecture cannot remove that evaluator cost.

`docs/benchmarks/engine_v2_measured/profile.json` contains the isolated final diagnostic run; `engine_v2_final` also preserves the earlier shorter run and dense smoke. Tracemalloc adds overhead and tracks Python allocations, not total native Torch/NumPy memory. The benchmark explicitly records failed tactical targets. Three strategic cases have no claimed oracle, so they are not counted as solved. Single-pair smoke matches validate mechanics only and cannot promote anything or establish Elo.

Not demonstrated here: improvement against your 22-generation champion; long CUDA training; actual Drive synchronization; a live public tunnel; robust performance across a large external tactical suite; statistically significant rating gains; strength against a rated engine pool. Selective pruning remains optional, the sparse model remains experimental, and neither the dense size nor implemented feature count proves strong chess. The next experiment is a long paired comparison of your actual champion with old versus shared search, followed by individual pruning/evaluator comparisons at equal time controls.
