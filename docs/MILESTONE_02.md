# Milestone 02 — Modular engine and training integration

October 27, 2026. Requirements: [PHASES.md](../PHASES.md). Detailed operation and phase mapping: [ENGINE_GUIDE.md](ENGINE_GUIDE.md).

## Delivered

- `chess_ai/`: incremental rules state/hash adapter, shared bounded alpha-beta/PVS search, tapered evaluation, optional sparse neural/hybrid evaluation, controlled matches, genetic parameter optimization, UCI, export and notebook adapters.
- `tools/`: source bundling, benchmark/ablation runner, matched games, labeled PGN preparation, sparse training and validated deployment export.
- `vendor/train.ipynb`: generated self-contained engine package; existing dense/classic checkpoints preserved; independent promotion gates; new parameter-evolution mode; one-network dense deployment bank. User outputs and the 2.5-hour setting preserved.
- `vendor/deploy.ipynb`: loads all supported bundles, reports search/verification status, avoids installing Torch for sparse NumPy weights; API contract retained.
- `tests/`: rules/perft, search, evaluation, neural, genetics, match statistics, UCI, persistence and actual notebook-cell/API workflows. Original tactical/strategic fixtures and versioned reports included.
- README and engine guide updated. Initial audit, first milestone and October 26 PDF retained as historical documents.

## Verification

**67 automated tests passed in 18.492 seconds** on local macOS ARM/Python 3.9.6, including a real temporary local HTTP server. [Raw test output](benchmarks/engine_v2_measured/tests.txt). The UCI command-line integration runs in its own process because the deployment notebook applies Colab's global `nest_asyncio` patch. The initial combined test attempt exposed that test-isolation issue; the corrected suite completes and cleans up its services.

The dense and new parameter training cells were executed in sequence with tiny CPU configurations, followed by fresh-process export verification and resume. Classical and sparse exports also pass the actual deployment load/app cells. Full-size dense smoke uses initialized 14,828,801-parameter weights, one inference bank, and legal moves at all three difficulties; it is not the user's trained champion. [Raw dense report](benchmarks/engine_v2_final/dense_cpu_smoke.json).

`python tools/sync_engine.py --check` passes. The final profile's source SHA matches the delivered Python modules. Notebook outputs were compared with the pre-implementation snapshot and preserved.

## Measured search comparison

Each configuration searched the same 16 valid positions with at most 0.25 seconds, 3,000 nodes and depth 4. Tracemalloc was active; times/NPS therefore include instrumentation overhead. Means below cover all 16 positions. [Raw profiles and matches](benchmarks/engine_v2_measured/profile.json).

| Configuration | Comparison baseline | Scored targets | Mean completed depth | Mean nodes/s |
| --- | --- | --- | --- | --- |
| baseline | baseline | 12/13 | 2.75 | 1869 |
| default | baseline | 12/13 | 2.62 | 1831 |
| pvs | baseline | 12/13 | 2.75 | 1961 |
| aspiration | baseline | 12/13 | 2.75 | 1796 |
| see | baseline | 12/13 | 2.62 | 1733 |
| countermove | baseline | 12/13 | 2.75 | 1845 |
| null_move | pvs | 12/13 | 2.69 | 1803 |
| lmr | pvs | 12/13 | 2.69 | 1817 |
| futility | pvs | 12/13 | 2.81 | 1873 |
| check_extensions | baseline | 12/13 | 2.38 | 1763 |

All configurations miss the pawn-breakthrough target (`b5b6`); all choose `f1e2` at this budget. Three strategic diagnostics are excluded from accuracy because they have no validated best-move oracle. Theme coverage is small and some positions are reused. Default search is slightly shallower in this instrumented sample; there is no blanket performance or strength win to claim.

Each non-baseline configuration also completed two smoke games against its stated baseline. These games test the match machinery only; no candidate was promoted and no meaningful Elo conclusion follows. Earlier shorter/contended profiles are preserved under `engine_v2` and `engine_v2_final`; the isolated 0.25-second run above is the final comparison.

## Decisions and limitations

Reuse python-chess rules and original trained weights. Keep new engine code canonical in ordinary Python files and bundle it into the standalone notebook, preventing drift between local and Colab implementations. Preserve legacy C++ training as an option rather than rewriting it. Keep selective pruning disabled until longer matched evidence supports it. Sparse neural training is a separate experiment, not a conversion of the large dense network.

Promotion now uses independent color-paired openings, conservative confidence bounds, repeated-test alpha spending, source/config identities and resume. Existing historical champions remain incumbents but are not declared verified automatically. Validation can consume multiple sessions; a strict gate may reject every challenger.

Actual CUDA/Drive/tunnel execution, the user's 22-generation weights, strong labeled training data and statistically meaningful matches remain unverified here. Absolute Elo and Stockfish-level strength are not claimed. The next strength experiment is an equal-time paired match of the user's saved champion with its old versus shared search, followed by independent pruning and evaluator trials.
