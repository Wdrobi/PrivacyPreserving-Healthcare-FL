from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from healthfl.reproducibility import build_reproducibility_package


def main() -> None:
    parser = argparse.ArgumentParser(description="Build thesis evidence artifacts")
    parser.add_argument("--output", default="results/thesis")
    args = parser.parse_args()
    outputs = build_reproducibility_package(REPOSITORY, args.output)
    for name, path in outputs.items():
        print(f"{name}={path.resolve()}")


if __name__ == "__main__":
    main()
