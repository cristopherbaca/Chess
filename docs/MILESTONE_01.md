# Milestone 1 — protect terminal replies in neural search

Completed locally on 2026-10-27, following the first-execution instruction in [PHASES.md](../PHASES.md). The [initial architecture assessment](ARCHITECTURE_ASSESSMENT.md) was written before changing engine code. Later phases remain planned.

## Problem and implementation

The deployed neural engine sorted interior moves by material/PST value before taking the first four/eight continuations. It checked terminal outcomes only for retained nodes. This could remove an immediate mating reply from the search tree.

For example, after `f8g8` in `5r1k/6pp/7N/8/8/8/8/KQ6 b - - 0 1`, White has `h6f7#`. The fixed prior ranked that reply tenth. The two-ply search evaluated Black's branch at −969 centipawns instead of a forced mate. A separate quiet queen mate, `f1f8#`, was ranked twenty-sixth in its reply position and omitted even with beam width eight.

`GpuCristopherEngine.beam_children()` now separates protected children from other candidates:

- Keep every immediately terminal child, including draws and checkmates.
- Keep every legal evasion when the parent is in check.
- Apply the existing prior ranking and beam limit to the remaining nonterminal children outside check.
- Check the deadline during child generation. An interrupted expansion is discarded, preserving the last completed iteration and the caller's board state.

This is a generic rule, with no position-specific move instructions. The retained tree may exceed the beam width. It remains selective beam search, not full-width alpha-beta or quiescence.

The exported metadata records `search_version: terminal-aware-beam-1`. `GPU_VERSION` remains unchanged because the weight format is unchanged. The generated source contributes to the publication fingerprint, so the corrected module is published in a new immutable bundle even if the champion's weights have not changed.

## Files changed in this milestone

| File | Change |
| --- | --- |
| `PHASES.md` | Saved the user's attached specification; this file was empty on disk at inspection. |
| `docs/ARCHITECTURE_ASSESSMENT.md` | Component inventory, reusable foundations, correctness risks and prioritized development plan. |
| `vendor/train.ipynb` | Neural deployment child selection, interruption handling and search-version metadata. |
| `tools/notebook_engine.py` | Loads definitions without running Colab, setup, training or deployment; supplies deterministic benchmark fixtures and perft traversal. |
| `tools/benchmark_search.py` | Reproducible fixed-position comparison using an archived/current notebook, source hashes and JSON reports. |
| `tests/engine_positions.json` | Referenced perft positions and independently checkable tactical regression positions. |
| `tests/test_engine.py` | Rule traversal, make/unmake/hash, draw/terminal, classical baseline and neural search regressions. |
| `tests/test_notebooks.py` | Checks that an exported module contains the fix; permits valid user execution outputs. |
| `docs/benchmarks/*.json` | Raw before/after measurements and full-size CPU compatibility result. |
| `README.md`, this report | Current status, test commands and instructions for using the corrected export. |

Existing uncommitted work was preserved. In particular, the user-deleted `PHASE2_README.md` was not restored; README links now point to the surviving documentation. The dated technical PDF is a description of the earlier implementation, not this milestone's test report.

## Tests and results

The mate regression was executed **before** the fix and failed in all four subcases: two positions and their color mirrors. It passes after the fix.

| Suite | Result |
| --- | --- |
| `test_engine.py` | 13 tests passed |
| `test_notebooks.py` | 9 tests passed |
| `test_api.py` | 9 tests passed |
| `test_deployment_flow.py` | 1 test passed; real local HTTP, simulated Colab and tunnel |
| Full-size CPU compatibility smoke | 14,828,801 parameters exported/reloaded; legal easy/medium/hard moves; mate branch recognized |
| Preservation comparison | Same notebook outputs/execution counters, configuration, training algorithms and checkpoint signature as before the search edit |

The full-size smoke used newly initialized weights with PyTorch 2.8.0 on CPU, **not the user's trained champion**. Its raw result is [full_size_smoke.json](benchmarks/full_size_smoke.json). Deployment's integration check executes all cells twice, verifies the printed URL, verifies continued service, then stops the server and tunnel fixture.

The initial persistence run had one existing failure: a test demanded that all notebook output lists be empty. The user's notebook contained Colab logs. That assertion was removed; notebook schema validation, code syntax, collapsed-cell metadata and workflow separation checks remain. No user outputs were deleted to make the test pass.

Perft traverses legal moves to fixed depth, regardless of adjudication rules. It matches initial-position counts **20 / 400 / 8,902 / 197,281** and Kiwipete **48 / 2,039 / 97,862**, with board and hash restoration. The counts are referenced to [emacs-chess's perft tests](https://github.com/jwiegley/emacs-chess/blob/master/chess-perft.el). Separate cases exercise all promotion pieces, both castles for both colors, en passant and its pinned-pawn restriction, castling through check, repetition history, fifty-move state, insufficient material, mate, stalemate and budget interruption.

## Before/after measurements

Same fixed positions and deterministic material/PST-plus-terminal evaluator; three repetitions per position, median elapsed time. Python 3.9.6, NumPy 2.0.2, python-chess 1.11.2, macOS ARM64. These numbers measure CPU beam traversal with a cheap fixture evaluator, **not neural or CUDA throughput**. Times vary with host load.

| Position | Depth / beam | Before → after, ms | Evaluated positions | Forced-mate branch score |
| --- | --- | --- | --- | --- |
| Smothered-mate reply | 2 / 4 | 8.25 → 12.28 | 78 → 80 | −969 → −30,000 |
| Quiet queen-mate reply | 2 / 8 | 29.17 → 41.99 | 294 → 298 | −371.5 → −30,000 |
| Initial position | 2 / 4 | 18.13 → 22.72 | 100 → 100 | Not applicable |
| Kiwipete | 3 / 8 | 951.51 → 1,163.97 | 3,494 → 3,494 | Not applicable |

The targeted branch errors fall from **2 to 0**. Best root moves remain unchanged in these four positions, so this does not demonstrate a better match result. Additional terminal checks cost roughly **22–49%** in these measurements. That cost is explicit rather than hidden behind an unverified strength claim. At a fixed wall-clock limit, extra work can reduce completed depth.

Raw inputs, source/fixture hashes, samples and results: [before](benchmarks/beam_before.json), [after](benchmarks/beam_after.json). Perft timing is also recorded there; it is a rule-traversal baseline, not an optimized engine NPS benchmark.

## Reproduce locally

Use a supported Python environment with the project's dependencies:

```sh
python -m pip install numpy python-chess
python -m unittest discover -s tests -p 'test_engine.py' -v
python tools/benchmark_search.py --output /tmp/beam_current.json
# Compare a previously saved notebook using the same fixture/evaluator:
python tools/benchmark_search.py --notebook /path/to/previous/train.ipynb --output /tmp/beam_previous.json

python -m pip install torch nbformat fastapi uvicorn nest_asyncio httpx requests
python -m unittest discover -s tests -p 'test_notebooks.py' -v
python tests/test_api.py
python tests/test_deployment_flow.py
```

The deployment-flow test binds `localhost:8000` and needs that port to be available. It does not open a public tunnel. The benchmark does not require Torch, download files, or run training.

## Apply to the existing trained champion

1. Use the updated `vendor/train.ipynb` with the **same Drive, run name, network dimensions and experiment settings** as the saved run. Keep one trainer per run name.
2. Resume it. Startup loads the existing checkpoint and republishes its selected champion with the corrected source; training continues from the saved state. There is no need to train from scratch. The normal session budget may be shortened without changing the checkpoint signature.
3. Then run all of `vendor/deploy.ipynb` again to load that newly published bundle and get its URL. The bundle's `cristopher_genome.json` contains `search_version: terminal-aware-beam-1`.

Rerunning deployment **alone**, while Drive still points to an old export, loads the old search. Existing immutable bundles and running engines are not patched in place. The deployment notebook itself needs no loader change for this metadata or search revision.

## Known limits and next step

No CUDA session, live public tunnel, user champion match, NNUE inference, native C++ perft, or new browser regression run was performed in this milestone. Production rules, browser code, API implementation, neural architecture and evolution updates were not changed. Quiet nonterminal tactics can still be pruned; medium/hard remain limited to two/three plies. Interior neural mate scores still lack distance normalization. Champion promotion still lacks an independent statistically meaningful match gate.

The next highest-priority improvement is a reusable search/evaluation boundary with instrumented alpha-beta/quiescence baselines, comparing the existing classical and neural evaluators at fixed budgets. Preserve this regression suite while introducing one search change at a time. Independent champion validation should follow before claiming that additional generations produce verified strength gains.
