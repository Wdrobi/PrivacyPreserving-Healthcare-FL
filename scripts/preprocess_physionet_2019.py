from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from healthfl.scientific.physionet2019 import (  # noqa: E402
    build_physionet_federated_data,
    save_processed,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preprocess PhysioNet 2019 by patient")
    parser.add_argument("--source", default="data/raw/physionet-2019")
    parser.add_argument("--destination", default="data/processed/physionet-2019-seed101")
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--history-hours", type=int, default=24)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = build_physionet_federated_data(
        args.source, seed=args.seed, history_hours=args.history_hours
    )
    manifest = save_processed(dataset, args.destination)
    print(json.dumps(dataset.manifest["sites"], indent=2))
    print(f"features={len(dataset.feature_names)}")
    print(f"manifest={manifest.resolve()}")


if __name__ == "__main__":
    main()
