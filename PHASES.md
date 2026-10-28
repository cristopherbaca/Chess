# ROLE: Senior Chess Engine Architect and AI Research Engineer

You are an expert chess engine developer specializing in high-performance search algorithms, computational game theory, evolutionary optimization, neural networks, and Stockfish-inspired engine design.

You are working inside my existing chess AI repository.

## PRIMARY OBJECTIVE

Transform my existing genetically trained chess AI into a substantially stronger engine using architectural principles inspired by Stockfish.

My current AI uses genetic training to evolve and improve its gameplay, but I suspect it lacks tactical depth, positional understanding, long-term planning, efficient search, and sophisticated chess evaluation.

Your job is NOT to discard my existing work or simply integrate Stockfish as the move generator.

Instead, analyze the codebase, identify its weaknesses, and implement a modular chess engine combining:

- Genetic and evolutionary training
- High-performance game-tree search
- Sophisticated position evaluation
- Chess-specific tactical and strategic knowledge
- Neural evaluation as an optional advanced component
- Self-play and automated performance testing
- Efficient memory management and computational optimization

The end goal is an independently functioning chess AI that can improve through training and measurable algorithmic improvements.

Do not claim Stockfish-level strength unless independently verified.

---

# PHASE 1 — AUDIT THE EXISTING PROJECT

Before modifying any code:

1. Inspect the entire repository.
2. Identify the programming language, frameworks, and dependencies.
3. Locate the chessboard representation, legal move generation, evaluation function, genetic algorithm, fitness function, and training loop.
4. Determine how moves are currently selected.
5. Identify existing tests and performance measurements.
6. Find architectural bottlenecks and correctness problems.
7. Determine which components can be reused.

Produce an initial architecture assessment explaining:

- What currently works.
- What is missing.
- What limits playing strength.
- What should be preserved.
- What should be redesigned.
- What should be implemented first.

Do not rewrite working components without a concrete justification.

Adapt the architecture to the existing language and project conventions.

# PHASE 2 — CHESS ENGINE CORE

Build a reliable chess engine foundation.

Implement or improve:

- Efficient board representation, preferably bitboards if appropriate.
- Complete legal move generation.
- Make/unmake move functionality.
- Check, checkmate, and stalemate detection.
- Castling and en passant.
- All pawn promotion choices.
- Repetition and fifty-move rule detection.
- Insufficient-material draw detection where applicable.
- Zobrist hashing.
- Efficient incremental board-state updates.

Provide perft tests using known chess positions and reference node counts.

Correctness is mandatory: a fast engine that generates illegal moves is unacceptable.

# PHASE 3 — ADVANCED SEARCH ARCHITECTURE

Implement a modular search system inspired by strong alpha-beta chess engines.

Begin with:

1. Negamax with alpha-beta pruning.
2. Iterative deepening.
3. Quiescence search.
4. Transposition tables with appropriate replacement policies.
5. Principal Variation Search.
6. Move ordering using transposition-table moves, tactical move scoring, killer moves, and history heuristics.
7. Aspiration windows.
8. Checkmate-distance scoring.
9. Time management.

After establishing correctness and baseline performance, progressively introduce:

- Null-move pruning with appropriate safeguards.
- Late Move Reductions.
- Futility pruning.
- Selective search extensions.
- Static Exchange Evaluation.
- Countermove heuristics.
- Additional pruning techniques supported by testing.

Each optimization must be introduced individually and evaluated against the previous version.

Do not blindly copy complex pruning formulas from Stockfish. Establish a correct baseline, then tune the engine empirically.

# PHASE 4 — CHESS POSITION EVALUATION

Develop a sophisticated evaluation interface that can support multiple interchangeable evaluators.

Initially implement a classical evaluator that considers:

## Material
- Relative piece values.
- Bishop pair.
- Material imbalances.
- Phase-dependent piece values.

## Pawn structure
- Passed pawns.
- Isolated pawns.
- Doubled pawns.
- Backward pawns.
- Connected pawns.
- Pawn chains.
- Candidate passed pawns.

## Piece activity
- Mobility.
- Development.
- Central control.
- Knight outposts.
- Open files for rooks.
- Seventh-rank activity.
- Trapped pieces.

## King safety
- Pawn shelter.
- Open lines near the king.
- Attacking pieces.
- Threats to the king.
- Endgame king activity.

## Positional strategy
- Weak squares.
- Space advantage.
- Strong and weak color complexes.
- Piece coordination.
- Blockades.
- Endgame activity.

## Game phase

Implement phase-aware evaluation so the engine can value positions differently during opening, middlegame, and endgame.

Make evaluation weights configurable and accessible to the genetic training system.

Avoid duplicated or contradictory evaluation terms.

Create targeted position tests verifying that evaluation changes in sensible directions.

# PHASE 5 — PRESERVE AND IMPROVE GENETIC TRAINING

My genetic algorithm is a core part of the project.

Do not remove it.

Instead, redesign it where necessary to evolve meaningful engine parameters.

Potential genes include:

- Piece values.
- Piece-square table parameters.
- Pawn structure weights.
- King safety coefficients.
- Mobility weights.
- Game-phase interpolation weights.
- Search heuristic parameters where appropriate.

Implement:

1. Configurable populations.
2. Mutation.
3. Crossover.
4. Elitism.
5. Tournament selection.
6. Reproducible random seeds.
7. Population diversity tracking.
8. Genetic checkpointing.
9. Best-model preservation.
10. Training statistics and experiment logs.

Use a robust fitness evaluation system.

Evaluate candidates against multiple opponents and positions rather than relying exclusively on games between related population members.

Control for playing color, openings, time budget, and randomness.

Prevent overfitting to a narrow set of positions or opponents.

Track strength improvements through actual match outcomes.

Use genetic optimization where it is appropriate; do not assume it is the best optimization method for neural-network weights.

# PHASE 6 — NEURAL EVALUATION

After the search engine and classical evaluator are stable, introduce an optional neural evaluation backend inspired by NNUE.

Research the architectural principles of efficient incremental neural evaluation.

Build an abstraction that supports:

- Classical evaluator.
- Neural evaluator.
- Experimental hybrid evaluator.

For the neural implementation, consider:

- Sparse chess-position features.
- Piece-square and king-relative representations.
- Incremental accumulator updates.
- Efficient CPU inference.
- Quantization where justified.
- Batch-based training.
- Checkpoint saving and loading.

Design the training pipeline so evaluation networks can learn from high-quality labeled chess positions and game outcomes.

Do not assume that a neural network automatically improves playing strength.

Benchmark the neural evaluator against the classical baseline using the same search budget.

If data, hardware, or project constraints make NNUE impractical, retain the modular interface and document the remaining implementation work.

# PHASE 7 — STRATEGY AND TACTICS

The engine must learn to select strong moves, not merely recognize superficial material advantages.

Build targeted tactical and strategic test suites covering:

- Pins.
- Forks.
- Skewers.
- Discovered attacks.
- Double attacks.
- Mating combinations.
- Defensive resources.
- Sacrifices.
- Zwischenzugs.
- Quiet tactical moves.
- Prophylaxis.
- Pawn breakthroughs.
- Passed-pawn conversion.
- King and pawn endgames.
- Opposition.
- Zugzwang.

Use these positions to evaluate search and position assessment.

Do not hardcode arbitrary responses to tactical patterns.

The engine should generally discover tactics through search and assess strategic ideas through evaluation.

# PHASE 8 — SELF-PLAY AND CONTINUOUS IMPROVEMENT

Create a reproducible self-play framework.

It should support:

- Playing against previous engine versions.
- Playing against independently configured opponents.
- Color-balanced matches.
- Diverse opening positions.
- Configurable time controls.
- PGN recording.
- Evaluation history.
- Error and crash reporting.
- Candidate promotion after successful tests.

Preserve the strongest verified model.

Do not replace the champion simply because a new generation has a higher internal fitness score.

Require statistically meaningful match evidence before promoting a candidate.

If Stockfish is installed, optionally use it for benchmarking or generating evaluation labels, but do not delegate production move selection to Stockfish.

# PHASE 9 — PERFORMANCE ENGINEERING

Profile the engine before optimizing.

Measure:

- Nodes searched per second.
- Effective search depth.
- Search time.
- Transposition-table hit rate.
- Quiescence node counts.
- Evaluation calls.
- Memory consumption.
- Time spent generating legal moves.
- Time spent evaluating positions.

Consider optimization methods such as:

- Incremental evaluation.
- Efficient move encoding.
- Precomputed attack tables.
- Better cache locality.
- Reduced allocations inside search.
- Compact transposition-table entries.
- Multithreaded search, only after single-threaded correctness is established.

Prioritize actual playing strength at fixed time controls rather than nodes per second alone.

# PHASE 10 — ENGINE INTERFACE AND TESTING

Implement or preserve compatibility with the existing application.

Where appropriate, support the Universal Chess Interface (UCI) protocol.

Support common commands such as:

- uci
- isready
- position
- go
- stop
- quit

Add automated tests for:

- Move legality.
- Perft.
- Hash consistency.
- Make/unmake correctness.
- Search termination.
- Mate detection.
- Repetition and draw handling.
- Time limits.
- Model serialization.
- Genetic training reproducibility.

Include regression tests for any discovered engine bugs.

# PHASE 11 — BENCHMARKING AND ELO IMPROVEMENT

Create a reliable evaluation framework that measures whether the engine is improving.

Implement:

- Fixed-position tactical tests.
- Search-depth benchmarks.
- Time-controlled engine matches.
- Paired opening tests.
- Win/draw/loss statistics.
- Estimated Elo differences with uncertainty.
- Training-generation comparisons.
- Versioned performance reports.

If possible, evaluate against multiple UCI engines with known relative strengths.

Do not invent Elo ratings or use incompatible rating pools as direct comparisons.

A feature is not considered successful merely because it sounds strategically sophisticated.

Its benefit must be demonstrated through tests.

# PHASE 12 — DEVELOPMENT ORDER

Follow this order:

1. Audit existing project.
2. Validate legal move generation.
3. Establish baseline benchmarks.
4. Implement alpha-beta search.
5. Add quiescence and move ordering.
6. Add transposition tables.
7. Improve classical evaluation.
8. Integrate evolutionary parameter optimization.
9. Introduce advanced search heuristics.
10. Add self-play validation and reliable Elo estimation.
11. Experiment with neural evaluation.
12. Optimize performance.
13. Repeat controlled strength testing.

Do not attempt a massive rewrite in one step.

Implement small, testable improvements that preserve existing functionality.

# ENGINEERING RULES

- Make real code changes, not just recommendations.
- Preserve the existing genetic training pipeline where possible.
- Prefer simple, verified solutions before advanced heuristics.
- Keep architecture modular and maintainable.
- Do not claim that an untested feature improves Elo.
- Do not fabricate test results or benchmarks.
- Run the applicable tests after each major change.
- Document assumptions and unresolved issues.
- Avoid introducing unnecessary dependencies.
- Use existing project conventions whenever practical.
- Clearly distinguish implemented features from planned features.
- Never replace my independent engine with a wrapper around Stockfish.

# FIRST EXECUTION

Begin by inspecting the repository and creating an architecture assessment.

Then implement the highest-priority improvement that offers a practical increase in correctness, search quality, or playing strength.

Run tests and report the results.

After each implementation milestone, provide:

1. Files changed.
2. Architectural decisions.
3. Algorithms added or improved.
4. Tests executed and their results.
5. Performance before and after, where measured.
6. Known limitations.
7. The next highest-priority improvement.

The objective is to build a scientifically tested, continuously improving chess engine whose performance comes from efficient search, strong evaluation, and effective training rather than superficial chess rules or unverified complexity.