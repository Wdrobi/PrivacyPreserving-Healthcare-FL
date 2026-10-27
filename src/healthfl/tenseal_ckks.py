from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from collections.abc import Sequence

try:
    import tenseal as ts
except ImportError:  # pragma: no cover - exercised by dependency-free installs
    ts = None


@dataclass(frozen=True)
class CKKSParameters:
    profile: str = "seal-default-8192"
    poly_modulus_degree: int = 8192
    coeff_mod_bit_sizes: tuple[int, ...] = (60, 40, 40, 60)
    global_scale_bits: int = 40

    def __post_init__(self) -> None:
        if self.poly_modulus_degree < 4096 or (
            self.poly_modulus_degree & (self.poly_modulus_degree - 1)
        ):
            raise ValueError("poly_modulus_degree must be a power of two >= 4096")
        if len(self.coeff_mod_bit_sizes) < 3:
            raise ValueError("CKKS requires at least three coefficient moduli here")
        if not 20 <= self.global_scale_bits <= 60:
            raise ValueError("global_scale_bits must be between 20 and 60")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TenSEALCiphertext:
    serialized: bytes
    length: int

    @property
    def size_bytes(self) -> int:
        return len(self.serialized)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.serialized).hexdigest()


class TenSEALCKKSPublicBackend:
    """Public-key-only CKKS encryption and aggregation service.

    The serialized context intentionally excludes the secret key. This service
    can encrypt updates and perform the addition/plain-scalar multiplication
    required by weighted FedAvg, but it cannot decrypt any ciphertext.
    """

    backend_name = "tenseal-ckks-real"

    def __init__(self, public_context: bytes, parameters: CKKSParameters) -> None:
        if ts is None:
            raise ImportError("TenSEAL is required; install requirements-scientific.txt")
        self.parameters = parameters
        self.public_context_bytes = public_context
        self._context = ts.context_from(public_context)
        if self._context.has_secret_key():
            raise ValueError("aggregation context must not contain a secret key")
        if not self._context.has_public_key():
            raise ValueError("aggregation context requires a public key")

    @property
    def has_secret_key(self) -> bool:
        return bool(self._context.has_secret_key())

    @property
    def slot_capacity(self) -> int:
        return self.parameters.poly_modulus_degree // 2

    @property
    def context_fingerprint(self) -> str:
        return hashlib.sha256(self.public_context_bytes).hexdigest()

    def encrypt(self, values: Sequence[float]) -> TenSEALCiphertext:
        if not values:
            raise ValueError("cannot encrypt an empty vector")
        vector = ts.ckks_vector(self._context, list(values))
        return TenSEALCiphertext(vector.serialize(), len(values))

    def add(
        self, left: TenSEALCiphertext, right: TenSEALCiphertext
    ) -> TenSEALCiphertext:
        self._check_lengths(left, right)
        left_vector = ts.ckks_vector_from(self._context, left.serialized)
        right_vector = ts.ckks_vector_from(self._context, right.serialized)
        result = left_vector + right_vector
        return TenSEALCiphertext(result.serialize(), left.length)

    def multiply_plain(
        self, ciphertext: TenSEALCiphertext, scalar: float
    ) -> TenSEALCiphertext:
        vector = ts.ckks_vector_from(self._context, ciphertext.serialized)
        result = vector * float(scalar)
        return TenSEALCiphertext(result.serialize(), ciphertext.length)

    def weighted_sum(
        self, items: Sequence[tuple[TenSEALCiphertext, float]]
    ) -> TenSEALCiphertext:
        if not items:
            raise ValueError("cannot aggregate an empty ciphertext collection")
        total: TenSEALCiphertext | None = None
        for ciphertext, weight in items:
            weighted = self.multiply_plain(ciphertext, weight)
            total = weighted if total is None else self.add(total, weighted)
        assert total is not None
        return total

    @staticmethod
    def _check_lengths(left: TenSEALCiphertext, right: TenSEALCiphertext) -> None:
        if left.length != right.length:
            raise ValueError("ciphertext vector lengths do not match")


class TenSEALCKKSDecryptor:
    """Secret-key authority kept outside the aggregation service."""

    def __init__(self, private_context: object, parameters: CKKSParameters) -> None:
        if ts is None:
            raise ImportError("TenSEAL is required; install requirements-scientific.txt")
        if not private_context.has_secret_key():
            raise ValueError("decryptor requires a secret key")
        self.parameters = parameters
        self._context = private_context

    @property
    def has_secret_key(self) -> bool:
        return bool(self._context.has_secret_key())

    def decrypt(self, ciphertext: TenSEALCiphertext) -> list[float]:
        vector = ts.ckks_vector_from(self._context, ciphertext.serialized)
        return list(vector.decrypt())[: ciphertext.length]


@dataclass(frozen=True)
class TenSEALCKKSSystem:
    public_backend: TenSEALCKKSPublicBackend
    decryptor: TenSEALCKKSDecryptor
    parameters: CKKSParameters


@dataclass(frozen=True)
class CKKSKeyMaterial:
    public_context: bytes
    authority_context: bytes
    parameters: CKKSParameters


def generate_ckks_key_material(
    parameters: CKKSParameters | None = None,
) -> CKKSKeyMaterial:
    """Generate serializable public and secret authority contexts.

    The authority context is sensitive key material and must never be mounted
    into the coordinator or hospital containers.
    """

    if ts is None:
        raise ImportError("TenSEAL is required; install requirements-scientific.txt")
    selected = parameters or CKKSParameters()
    private_context = ts.context(
        ts.SCHEME_TYPE.CKKS,
        selected.poly_modulus_degree,
        -1,
        list(selected.coeff_mod_bit_sizes),
    )
    private_context.global_scale = 2**selected.global_scale_bits
    public_context = private_context.serialize(
        save_public_key=True,
        save_secret_key=False,
        save_galois_keys=False,
        save_relin_keys=False,
    )
    authority_context = private_context.serialize(
        save_public_key=True,
        save_secret_key=True,
        save_galois_keys=False,
        save_relin_keys=False,
    )
    return CKKSKeyMaterial(public_context, authority_context, selected)


def load_public_backend(
    public_context: bytes, parameters: CKKSParameters | None = None
) -> TenSEALCKKSPublicBackend:
    return TenSEALCKKSPublicBackend(public_context, parameters or CKKSParameters())


def load_authority_decryptor(
    authority_context: bytes, parameters: CKKSParameters | None = None
) -> TenSEALCKKSDecryptor:
    if ts is None:
        raise ImportError("TenSEAL is required; install requirements-scientific.txt")
    selected = parameters or CKKSParameters()
    context = ts.context_from(authority_context)
    return TenSEALCKKSDecryptor(context, selected)


def create_ckks_system(
    parameters: CKKSParameters | None = None,
) -> TenSEALCKKSSystem:
    """Generate one real CKKS keypair with separated public/secret roles.

    TenSEAL currently provides a single-key CKKS context, not distributed key
    generation or t-of-n threshold decryption. The caller must protect the
    returned decryptor as a centralized research key authority.
    """

    material = generate_ckks_key_material(parameters)
    return TenSEALCKKSSystem(
        public_backend=load_public_backend(material.public_context, material.parameters),
        decryptor=load_authority_decryptor(
            material.authority_context, material.parameters
        ),
        parameters=material.parameters,
    )
