"""Export a modular classical/sparse model for deploy.ipynb after validation."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chess_ai.artifacts import publish_model
from sync_engine import bundle_source

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--models-dir', required=True)
    parser.add_argument('--validation', help='Directory containing accepted match.json/report.json')
    parser.add_argument('--initial', action='store_true', help='Explicitly initialize an empty model directory without a strength claim')
    parser.add_argument('--hybrid', action='store_true')
    args = parser.parse_args()
    print(publish_model(args.model, args.models_dir, bundle_source(), args.validation, args.initial, args.hybrid))
