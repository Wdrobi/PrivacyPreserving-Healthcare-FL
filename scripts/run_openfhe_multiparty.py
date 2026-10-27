from __future__ import annotations

import argparse
import json

from healthfl.openfhe_multiparty import run_native_multiparty_ckks, write_result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run native OpenFHE multiparty CKKS verification"
    )
    parser.add_argument(
        "--output", default="results/openfhe-multiparty/summary.json"
    )
    args = parser.parse_args()
    result = run_native_multiparty_ckks()
    destination = write_result(result, args.output)
    print(json.dumps(result, indent=2))
    print(f"openfhe_multiparty_report={destination}")


if __name__ == "__main__":
    main()
