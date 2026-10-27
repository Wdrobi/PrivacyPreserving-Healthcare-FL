from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import Tensor


@dataclass(frozen=True)
class CAABCCommunicationBound:
    dimension: int
    block_size: int
    blocks: int
    selected_coordinates: int
    ckks_slots: int
    clients: int
    refresh_interval: int
    rounds: int
    dense_update_ciphertexts: int
    packed_update_ciphertexts: int
    score_ciphertexts_per_refresh: int
    score_refreshes: int
    dense_client_ciphertext_transmissions: int
    caabc_client_ciphertext_transmissions: int
    ciphertext_count_reduction: float

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


def communication_bound(
    *,
    dimension: int,
    block_size: int,
    selected_coordinates: int,
    ckks_slots: int,
    clients: int,
    refresh_interval: int,
    rounds: int,
) -> CAABCCommunicationBound:
    values = (
        dimension,
        block_size,
        selected_coordinates,
        ckks_slots,
        clients,
        refresh_interval,
        rounds,
    )
    if any(value < 1 for value in values):
        raise ValueError("communication parameters must be positive")
    if selected_coordinates > dimension:
        raise ValueError("selected coordinates cannot exceed model dimension")
    blocks = math.ceil(dimension / block_size)
    dense = math.ceil(dimension / ckks_slots)
    packed = math.ceil(selected_coordinates / ckks_slots)
    score = math.ceil(blocks / ckks_slots)
    refreshes = math.ceil(rounds / refresh_interval)
    dense_total = clients * rounds * dense
    caabc_total = clients * (rounds * packed + refreshes * score)
    return CAABCCommunicationBound(
        dimension=dimension,
        block_size=block_size,
        blocks=blocks,
        selected_coordinates=selected_coordinates,
        ckks_slots=ckks_slots,
        clients=clients,
        refresh_interval=refresh_interval,
        rounds=rounds,
        dense_update_ciphertexts=dense,
        packed_update_ciphertexts=packed,
        score_ciphertexts_per_refresh=score,
        score_refreshes=refreshes,
        dense_client_ciphertext_transmissions=dense_total,
        caabc_client_ciphertext_transmissions=caabc_total,
        ciphertext_count_reduction=1.0 - caabc_total / dense_total,
    )


def error_feedback_conservation_error(
    update: Tensor,
    previous_residual: Tensor,
    released: Tensor,
    next_residual: Tensor,
) -> float:
    """Return ||g_t+r_t-C(g_t+r_t)-r_{t+1}||_2.

    A correct error-feedback implementation returns zero up to floating-point
    error, which makes the compression error telescope across rounds.
    """

    tensors = [value.detach().cpu().float().flatten() for value in (
        update, previous_residual, released, next_residual
    )]
    if len({value.numel() for value in tensors}) != 1:
        raise ValueError("error-feedback vectors must have equal dimensions")
    return float(torch.linalg.vector_norm(tensors[0] + tensors[1] - tensors[2] - tensors[3]))


def dp_postprocessing_statement() -> dict[str, object]:
    return {
        "condition": (
            "Block scores and support must be deterministic or randomized functions only "
            "of already clipped-and-DP-sanitized client updates."
        ),
        "result": (
            "Publishing the common support and CKKS aggregation of selected coordinates "
            "is DP post-processing and does not consume an additional privacy budget."
        ),
        "exclusions": (
            "The statement does not apply if scores use pre-noise gradients, if side-channel "
            "metadata depends on raw records, or if the DP accountant assumptions are violated."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the executable CAABC communication/privacy contract")
    parser.add_argument("--dimension", type=int, default=18049)
    parser.add_argument("--block-size", type=int, default=256)
    parser.add_argument("--selected-coordinates", type=int, default=8192)
    parser.add_argument("--ckks-slots", type=int, default=4096)
    parser.add_argument("--clients", type=int, default=2)
    parser.add_argument("--refresh-interval", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--output", default="results/q1-extension-v1/caabc_formal_contract.json")
    args = parser.parse_args()
    bound = communication_bound(
        dimension=args.dimension,
        block_size=args.block_size,
        selected_coordinates=args.selected_coordinates,
        ckks_slots=args.ckks_slots,
        clients=args.clients,
        refresh_interval=args.refresh_interval,
        rounds=args.rounds,
    )
    report = {
        "status": "executable CAABC analytical contract",
        "communication_bound": bound.to_dict(),
        "error_feedback_identity": "r_(t+1) = g_t + r_t - C(g_t + r_t)",
        "privacy_postprocessing": dp_postprocessing_statement(),
        "boundary": (
            "The count bound describes ciphertext transmissions under fixed CKKS slot "
            "packing; empirical serialized-byte and clinical-utility results remain required."
        ),
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"formal_contract={destination.resolve()}")


if __name__ == "__main__":
    main()
