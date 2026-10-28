# Fresh 30M training in Colab

## Run all

Upload the latest `vendor/train.ipynb`, select a GPU runtime, authorize Drive and choose **Runtime → Run all**. Defaults:

```python
TRAINING_MODE = 'full_pipeline'
SOURCE_RUN = ''
RUN_NAME = ''  # Defaults to fresh_30m_v1.
TRAINING_HOURS = 2.5
TRAIN_SPARSE_EVALUATOR = True
```

The new dense architecture is **784 → 6400 → 3904 → 1**, with **30,017,409 parameters**. Hidden weights initialize from a seeded random distribution, and the output layer starts at zero over the built-in material/PST prior. `SOURCE_RUN` and `gpu_seed_classic_run` are blank: **no previously trained weights or saved classical prior are used**. The dense population has 32 members to offset increased model memory.

The root is **`MyDrive/chess_30m/`**, separate from the previous `cristopher_evo` folder. The first session initializes the new experiment; later sessions resume its checkpoints. Keep the same `RUN_NAME` and settings to resume. `TRAINING_HOURS` may change; other experiment changes require a new run name. To start over deliberately, choose a new run name. Old models in Drive are neither imported nor deleted.

No local model/data files are required for Colab: canonical engine modules and diagnostic cases are embedded in the notebook. Sparse training downloads and caches its labeled dataset on Drive. Code is collapsed into runnable forms.

## Stages

| Stage | Work | Saved progress |
| --- | --- | --- |
| Dense evolution | Mirrored evolutionary population, shared alpha-beta/PVS/quiescence search, full history and legal moves, multiple opponents | Mean/champion/initial weights, RNG, perturbations, in-progress games and move traces |
| Classical evolution | Phase-aware material, pawn, activity, king-safety and positional parameters; mutation, crossover, tournament, elites and diversity | Population, RNG, games and independent validation |
| Sparse neural training | New incremental king-bucket network; labeled minibatches and separate train/validation/test splits | Dataset/checksum, optimizer/RNG, best validation weights, held-out report |
| Evaluator comparison | Dense, classical, dense/classical hybrid, sparse and sparse/classical hybrid challengers under equal search budgets | Paired openings/colors, PGNs, per-ply state, source/model hashes and confidence bounds |
| Search comparison | Individual comparisons for null move, LMR, futility, check extensions, SEE, countermoves, PVS and aspiration | Independent match evidence and accepted search configuration |
| Diagnostics | Published puzzle solutions and discriminating tablebase endgames; nodes, depth, TT hits, evaluation/move-generation time and memory | Resumable versioned position reports |
| Publication | Selected engine source, configuration, necessary weights and checksums | Immutable complete deployment folder plus atomic latest-champion pointer |

This is one coordinated workflow, not a guarantee that every stage finishes in 2.5 hours. Validation alone can take multiple sessions. Run all resumes the next incomplete stage or starts the next cycle after completing one.

The sparse evaluator is a separate, freshly initialized candidate, not part of the 30M dense parameter count. Deployment serves the selected evaluator; classical or sparse challengers may replace the dense incumbent only after passing independent matches. Experimental search flags are not forced on: PHASES.md requires their individual evaluation. Genetic training is preserved; no production moves are delegated to Stockfish.

Search-based dense fitness is slower than the retained legacy one-ply mode because recursive alpha-beta is CPU-controlled and makes smaller GPU inference batches. Actual GPU throughput and memory depend on the Colab runtime. More parameters, generations or lower neural prediction error do not guarantee better chess.

## Champion preservation and recovery

Training fitness selects candidates. Promotion requires at least **32 complete color-balanced opening pairs** and a conservative score lower bound above 50%, with alpha spending across attempts. Error/capped games cannot qualify. The current incumbent remains selected when a challenger fails. The initial baseline is exported before lengthy stages so deployment can function while training proceeds; that initial baseline is not a verified strength improvement.

Dense evolution saves about every 60 seconds after the current move, at generation boundaries and on recoverable exit. Sparse training saves optimizer/RNG state and its best validation network every epoch; deadlines are checked between epochs. Parameter and pipeline stages save their own state. Match files save after each move. The last three pipeline/dense checkpoints provide corrupt-latest fallback. A hard runtime kill cannot execute a final save and may lose the latest unsaved work. Keep Drive mounted/writable and one writer per experiment.

```text
MyDrive/chess_30m/
  experiments/fresh_30m_v1/
    state/                         Pipeline cursor and selected incumbent
    checkpoints/dense/             Dense model, population seeds and games
    models/deployments/             Private dense snapshots
    parameters/                    Classical population and validation
    data/                          Public labeled-position cache
    sparse/                        Optimizer, best weights and held-out report
    validation/                    Evaluator/search comparisons
    reports/                       Tactical/endgame profiles
    logs/ and pgn/                 Training traces and games
  models/deployments/               Published self-contained engine bundles
  models/latest_champion.json      Selected deployment pointer
```

The source-code identity and saved model identity are included in validation evidence. Updating implementation code invalidates incompatible match evidence without discarding learned weights. A new architecture requires a different experiment; explicit source import/widening remains an optional compatibility facility, disabled by the fresh defaults.

## Deploy

Run the updated `vendor/deploy.ipynb` separately. It requires a valid manifest in **`MyDrive/chess_30m/models/`** and never falls back to old folders. It loads the selected evaluator/search configuration, starts the API and returns its verified HTTPS URL. Rerun deployment to load newer weights. Public-site protections, GitHub Pages publishing and limitations are documented in [PUBLIC_DEPLOYMENT.md](PUBLIC_DEPLOYMENT.md).

## Data and verification

The optional sparse stage caches 20,000 qualifying positions by default from the [CC0 Lichess evaluation database](https://database.lichess.org/#evals), with depth >=20 and >=100k-node labels. Extreme scores are excluded, exact/color-mirrored positions share a split, and diagnostic fixtures are excluded from training. The fixed test split is for reporting, not checkpoint selection. It is a prefix sample and lacks original game IDs, so related-position/source bias remains.

Local integration tests execute the full workflow with tiny real networks, check fresh initialization and recovery, run notebook cells, load standalone exports and exercise real local HTTP deployment. Security tests cover request limits, origin checks, private stats, spoofed forwarding headers and native-timeout admission. Those tests establish behavior, not the strength of the new model or sustained CUDA/public-tunnel performance. Historical audit and measurement files remain in `docs/`; earlier model measurements do not describe this fresh model.
