from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from healthfl.scientific.physionet2019 import LandmarkPreprocessor, stratified_patient_split


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the locked PhysioNet training-only preprocessing state"
    )
    parser.add_argument("--raw", default="data/raw/physionet-2019")
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--history-hours", type=int, default=24)
    parser.add_argument(
        "--output",
        default="results/q1-external-readiness/development_preprocessor_state.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = Path(args.raw)
    site_paths = {
        site.name: tuple(sorted(site.glob("*.psv")))
        for site in sorted(source.glob("hospital-*"))
        if site.is_dir()
    }
    if set(site_paths) != {"hospital-a", "hospital-b"}:
        raise ValueError("expected PhysioNet hospital-a and hospital-b directories")
    splits = {
        site: stratified_patient_split(paths, seed=args.seed + index * 4099)
        for index, (site, paths) in enumerate(site_paths.items())
    }
    training = tuple(path for split in splits.values() for path in split.train)
    preprocessor = LandmarkPreprocessor(seed=args.seed, history_hours=args.history_hours)
    preprocessor.fit(training)
    payload = {
        "status": "training-only preprocessing state exported for external validation",
        "source": "PhysioNet 2019 development cohort",
        "split_seed": args.seed,
        "training_patients": len(training),
        "preprocessor_state": preprocessor.state_dict(),
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"training_patients={len(training)} output={destination.resolve()}")


if __name__ == "__main__":
    main()
