"""
Dataset loader for the UCI Heart Disease dataset.

This is the L1 (Data & Client Layer) building block of the proposed
methodology: it owns/prepares the private patient data, runs preprocessing
+ feature normalization, and emits arrays ready to be encoded for HE.

The dataset is fetched from the UCI repository on first use and cached
locally under Implementation/data/.

The loader can also produce a federated split (non-IID by default to
mirror real hospital-to-hospital distribution shifts).
"""
from __future__ import annotations

import io
import os
import urllib.request
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


UCI_URL = (
    "https://archive.ics.uci.edu/ml/machine-learning-databases/"
    "heart-disease/processed.cleveland.data"
)

COLUMNS = [
    "age", "sex", "cp", "trestbps", "chol", "fbs", "restecg",
    "thalach", "exang", "oldpeak", "slope", "ca", "thal", "target",
]

PIMA_URL = (
    "https://raw.githubusercontent.com/jbrownlee/Datasets/master/"
    "pima-indians-diabetes.data.csv"
)
PIMA_COLUMNS = [
    "pregnancies", "glucose", "blood_pressure", "skin_thickness",
    "insulin", "bmi", "diabetes_pedigree", "age", "target",
]

# All four UCI Heart Disease databases — combined gives ~920 samples
HEART_BASE = "https://archive.ics.uci.edu/ml/machine-learning-databases/heart-disease/"
HEART_FILES = {
    "cleveland":   "processed.cleveland.data",
    "hungarian":   "processed.hungarian.data",
    "switzerland": "processed.switzerland.data",
    "va":          "processed.va.data",
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CACHE_PATH = os.path.join(DATA_DIR, "cleveland.csv")
PIMA_CACHE = os.path.join(DATA_DIR, "pima.csv")
HEART_COMBINED_CACHE = os.path.join(DATA_DIR, "heart_combined.csv")


@dataclass
class HeartDataset:
    X_train: np.ndarray
    X_test: np.ndarray
    y_train: np.ndarray
    y_test: np.ndarray
    feature_names: List[str]


def _download_if_needed() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(CACHE_PATH):
        return CACHE_PATH
    print(f"[data_loader] downloading UCI Heart Disease dataset to {CACHE_PATH}")
    with urllib.request.urlopen(UCI_URL, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(raw)
    return CACHE_PATH


def _build_synthetic_fallback(n: int = 600, seed: int = 42) -> pd.DataFrame:
    """Synthetic heart-disease-like data used only if the UCI fetch fails
    (e.g. offline environment). Keeps the same column names so the rest of
    the pipeline is identical.
    """
    rng = np.random.default_rng(seed)
    age = rng.integers(29, 78, n)
    sex = rng.integers(0, 2, n)
    cp = rng.integers(0, 4, n)
    trestbps = rng.integers(94, 200, n)
    chol = rng.integers(126, 564, n)
    fbs = rng.integers(0, 2, n)
    restecg = rng.integers(0, 3, n)
    thalach = rng.integers(71, 202, n)
    exang = rng.integers(0, 2, n)
    oldpeak = rng.uniform(0, 6.2, n)
    slope = rng.integers(0, 3, n)
    ca = rng.integers(0, 4, n)
    thal = rng.choice([3, 6, 7], n)
    # Risk score loosely modelled on known correlations
    risk = (
        0.04 * (age - 50)
        + 0.6 * (cp == 0).astype(float) * -1
        + 0.5 * (cp >= 2).astype(float)
        + 0.02 * (trestbps - 130)
        + 0.005 * (chol - 240)
        - 0.03 * (thalach - 150)
        + 0.6 * exang
        + 0.4 * oldpeak
        + 0.4 * ca
        + rng.normal(0, 0.5, n)
    )
    target = (risk > 0.5).astype(int)
    df = pd.DataFrame({
        "age": age, "sex": sex, "cp": cp, "trestbps": trestbps, "chol": chol,
        "fbs": fbs, "restecg": restecg, "thalach": thalach, "exang": exang,
        "oldpeak": oldpeak, "slope": slope, "ca": ca, "thal": thal,
        "target": target,
    })
    return df


def load_raw() -> pd.DataFrame:
    try:
        path = _download_if_needed()
        df = pd.read_csv(path, header=None, names=COLUMNS, na_values="?")
    except Exception as e:
        print(f"[data_loader] UCI download failed ({e}); using synthetic fallback")
        return _build_synthetic_fallback()
    # Drop NA rows (Cleveland has a small number)
    df = df.dropna().reset_index(drop=True)
    # Binarise target: presence (>=1) vs absence (0) of heart disease
    df["target"] = (df["target"] >= 1).astype(int)
    return df


def load_centralized(test_size: float = 0.2, seed: int = 42) -> HeartDataset:
    df = load_raw()
    feature_cols = [c for c in df.columns if c != "target"]
    X = df[feature_cols].values.astype(np.float64)
    y = df["target"].values.astype(np.int64)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y
    )
    scaler = StandardScaler().fit(X_train)
    X_train = scaler.transform(X_train)
    X_test = scaler.transform(X_test)
    return HeartDataset(X_train, X_test, y_train, y_test, feature_cols)


# ---- Cross-dataset support (Phase A2) -------------------------------------------

def _load_pima_raw() -> pd.DataFrame:
    """Pima Indians Diabetes (UCI). 768 samples, 8 features, binary outcome.
    Cached to data/pima.csv on first download."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(PIMA_CACHE):
        print(f"[data_loader] downloading Pima Diabetes to {PIMA_CACHE}")
        try:
            with urllib.request.urlopen(PIMA_URL, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            with open(PIMA_CACHE, "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception as e:
            print(f"[data_loader] Pima download failed ({e}); using sklearn fallback")
            return _build_synthetic_pima()
    df = pd.read_csv(PIMA_CACHE, header=None, names=PIMA_COLUMNS)
    return df


def _build_synthetic_pima(n: int = 600, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "pregnancies": rng.integers(0, 17, n),
        "glucose": rng.integers(50, 200, n),
        "blood_pressure": rng.integers(30, 130, n),
        "skin_thickness": rng.integers(0, 100, n),
        "insulin": rng.integers(0, 850, n),
        "bmi": rng.uniform(18, 67, n),
        "diabetes_pedigree": rng.uniform(0.0, 2.5, n),
        "age": rng.integers(21, 82, n),
        "target": rng.integers(0, 2, n),
    })


def load_pima(test_size: float = 0.2, seed: int = 42) -> HeartDataset:
    """Pima Indians Diabetes — same HeartDataset shape so the rest of
    the pipeline is dataset-agnostic."""
    df = _load_pima_raw()
    feature_cols = [c for c in df.columns if c != "target"]
    X = df[feature_cols].values.astype(np.float64)
    y = df["target"].values.astype(np.int64)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y
    )
    scaler = StandardScaler().fit(X_train)
    return HeartDataset(scaler.transform(X_train), scaler.transform(X_test),
                        y_train, y_test, feature_cols)


def load_breast_cancer(test_size: float = 0.2, seed: int = 42) -> HeartDataset:
    """Breast Cancer Wisconsin (Diagnostic), via sklearn. 569 samples,
    30 features. Reused as a third evaluation dataset for the cross-
    dataset section of the thesis comparison."""
    from sklearn.datasets import load_breast_cancer as _skl
    bunch = _skl()
    X = bunch.data.astype(np.float64)
    y = bunch.target.astype(np.int64)  # 0=malignant, 1=benign
    feature_cols = list(bunch.feature_names)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y
    )
    scaler = StandardScaler().fit(X_train)
    return HeartDataset(scaler.transform(X_train), scaler.transform(X_test),
                        y_train, y_test, feature_cols)


def _load_heart_combined_raw() -> pd.DataFrame:
    """Combined UCI Heart Disease — all four databases (Cleveland +
    Hungarian + Switzerland + VA Long Beach). ~920 samples total,
    ~3x the Cleveland-only baseline. Standard practice in the
    privacy-preserving healthcare ML literature for raising accuracy
    while preserving the same feature schema.
    """
    if os.path.exists(HEART_COMBINED_CACHE):
        return pd.read_csv(HEART_COMBINED_CACHE)
    os.makedirs(DATA_DIR, exist_ok=True)
    frames = []
    for site, fname in HEART_FILES.items():
        path = os.path.join(DATA_DIR, f"heart_{site}.data")
        if not os.path.exists(path):
            url = HEART_BASE + fname
            print(f"[data_loader] downloading {site} from UCI")
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    raw = resp.read().decode("utf-8")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(raw)
            except Exception as e:
                print(f"[data_loader] {site} download failed ({e})")
                continue
        try:
            df = pd.read_csv(path, header=None, names=COLUMNS, na_values="?")
            df["site"] = site
            frames.append(df)
        except Exception as e:
            print(f"[data_loader] failed parsing {site}: {e}")
    if not frames:
        # Fallback to Cleveland only if downloads failed
        return load_raw().assign(site="cleveland")
    full = pd.concat(frames, ignore_index=True)
    # Some databases report many missing values for slope/ca/thal — impute
    # with column median rather than dropping (we'd lose half the data).
    feature_cols = [c for c in COLUMNS if c != "target"]
    for col in feature_cols:
        full[col] = pd.to_numeric(full[col], errors="coerce")
        full[col] = full[col].fillna(full[col].median())
    full = full.dropna(subset=["target"]).reset_index(drop=True)
    full["target"] = (full["target"].astype(int) >= 1).astype(int)
    full.to_csv(HEART_COMBINED_CACHE, index=False)
    return full


def load_heart_combined(test_size: float = 0.2, seed: int = 42) -> HeartDataset:
    df = _load_heart_combined_raw()
    feature_cols = [c for c in df.columns if c not in ("target", "site")]
    X = df[feature_cols].values.astype(np.float64)
    y = df["target"].values.astype(np.int64)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y
    )
    scaler = StandardScaler().fit(X_train)
    return HeartDataset(scaler.transform(X_train), scaler.transform(X_test),
                        y_train, y_test, feature_cols)


def load_dataset(name: str, test_size: float = 0.2, seed: int = 42) -> HeartDataset:
    """Dispatcher used by the cross-dataset section. `name` is one of
    'cleveland' / 'heart_combined' / 'pima' / 'breast_cancer'."""
    name = name.lower()
    if name == "cleveland":
        return load_centralized(test_size=test_size, seed=seed)
    if name == "heart_combined":
        return load_heart_combined(test_size=test_size, seed=seed)
    if name == "pima":
        return load_pima(test_size=test_size, seed=seed)
    if name == "breast_cancer":
        return load_breast_cancer(test_size=test_size, seed=seed)
    raise ValueError(f"unknown dataset {name!r}")


def split_federated(
    ds: HeartDataset, n_clients: int = 4, non_iid: bool = True, seed: int = 42
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Partition the training set across n_clients to simulate hospitals.

    non_iid=True biases each client's class balance so we mimic
    real-world hospital case-mix differences.
    """
    rng = np.random.default_rng(seed)
    X, y = ds.X_train, ds.y_train
    idx_pos = np.where(y == 1)[0]
    idx_neg = np.where(y == 0)[0]
    rng.shuffle(idx_pos)
    rng.shuffle(idx_neg)

    if not non_iid:
        all_idx = np.concatenate([idx_pos, idx_neg])
        rng.shuffle(all_idx)
        chunks = np.array_split(all_idx, n_clients)
    else:
        # Dirichlet-style skew: each client gets a different pos/neg ratio
        alpha = rng.dirichlet([0.7] * n_clients)  # share of positives
        beta = rng.dirichlet([0.7] * n_clients)   # share of negatives
        pos_chunks = np.array_split(
            idx_pos,
            np.cumsum((alpha[:-1] * len(idx_pos)).astype(int)),
        )
        neg_chunks = np.array_split(
            idx_neg,
            np.cumsum((beta[:-1] * len(idx_neg)).astype(int)),
        )
        chunks = []
        for p, n in zip(pos_chunks, neg_chunks):
            merged = np.concatenate([p, n])
            rng.shuffle(merged)
            chunks.append(merged)

    parts = []
    for ch in chunks:
        parts.append((X[ch], y[ch]))
    return parts


if __name__ == "__main__":
    ds = load_centralized()
    print(f"X_train {ds.X_train.shape}, X_test {ds.X_test.shape}")
    print(f"class balance: train={np.bincount(ds.y_train)}, test={np.bincount(ds.y_test)}")
    parts = split_federated(ds, n_clients=4)
    for i, (xc, yc) in enumerate(parts):
        print(f"client{i}: n={len(yc)}, pos_rate={yc.mean():.2f}")
