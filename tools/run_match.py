"""Run/resume a controlled match between independent engine configurations."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chess_ai.runtime import load_engine
from chess_ai.matches import MatchConfig, run_match, fingerprint, UciOpponent
from chess_ai.search import SearchOptions

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', help='Evaluation JSON, sparse NPZ or exported champion metadata')
    parser.add_argument('--incumbent')
    parser.add_argument('--candidate-evaluator', choices=['classical', 'neural', 'hybrid'], default='neural')
    parser.add_argument('--incumbent-evaluator', choices=['classical', 'neural', 'hybrid'], default='neural')
    parser.add_argument('--candidate-uci', help='Optional external benchmark executable')
    parser.add_argument('--incumbent-uci', help='Optional external benchmark executable')
    parser.add_argument('--output', required=True)
    parser.add_argument('--pairs', type=int, default=32)
    parser.add_argument('--seconds', type=float, default=.05)
    parser.add_argument('--nodes', type=int, default=3000)
    parser.add_argument('--max-plies', type=int, default=256)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--openings', default='', help='JSON opening book from prepare_validation.py')
    parser.add_argument('--attempt', type=int, default=1, help='Predeclared experiment index for alpha spending')
    parser.add_argument('--candidate-feature', choices=['pvs', 'aspiration', 'see', 'countermove', 'null_move', 'lmr', 'futility', 'check_extensions'])
    args = parser.parse_args()
    if args.candidate and args.candidate_uci or args.incumbent and args.incumbent_uci:
        parser.error('Choose either a saved model or a UCI executable for each side')
    base = SearchOptions() if not args.candidate_feature else SearchOptions(pvs=False, aspiration=False, see=False, countermove=False)
    if args.candidate_feature in ('null_move', 'lmr', 'futility'):
        base.pvs = True
    candidate = SearchOptions(**asdict(base))
    if args.candidate_feature:
        setattr(candidate, args.candidate_feature, True)
    cfg = MatchConfig(pairs=args.pairs, seed=args.seed, move_seconds=args.seconds, nodes=args.nodes,
                      max_plies=args.max_plies, opening_file=args.openings)
    def model_id(path, options, evaluator):
        import hashlib
        return {'model_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else 'default-classical', 'search': asdict(options), 'evaluator': evaluator}
    print(json.dumps(run_match(lambda: UciOpponent([args.candidate_uci]) if args.candidate_uci else load_engine(args.candidate, args.candidate_evaluator, options=candidate),
                              lambda: UciOpponent([args.incumbent_uci]) if args.incumbent_uci else load_engine(args.incumbent, args.incumbent_evaluator, options=base), cfg, args.output,
                              model_id(args.candidate or args.candidate_uci, candidate, args.candidate_evaluator),
                              model_id(args.incumbent or args.incumbent_uci, base, args.incumbent_evaluator),
                              attempt=args.attempt,
                              progress=lambda n, total: print(f'{n}/{total} games', flush=True) if n % 8 == 0 else None), indent=2))
