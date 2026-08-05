"""
train_anomaly_models.py

Train Phase 4 Anomaly Detection Models:
1. Gaussian Density Estimation Model
2. Isolation Forest Model

Saves trained model artifacts to models/ gaussian_model.pkl and isolation_forest_model.pkl.
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import N_VALUES

DROP_COLS = [
    "timestamp", "window_id", "node_id", "node_type", "N", "scenario_type",
    "is_attack_active", "is_node_compromised", "is_false_revocation_event"
]


class GaussianDensityModel:
    """Multivariate Gaussian Density Anomaly Detector."""

    def __init__(self, max_z2: float = 25.0):
        self.max_z2 = max_z2
        self.mu = None
        self.std = None
        self.feature_names = None

    def fit(self, X):
        if isinstance(X, pd.DataFrame):
            self.feature_names = list(X.columns)
            X_arr = X.to_numpy(dtype=np.float32)
        else:
            X_arr = np.asarray(X, dtype=np.float32)
            self.feature_names = [f"f_{i}" for i in range(X_arr.shape[1])]
            
        self.mu = np.mean(X_arr, axis=0, dtype=np.float64)
        self.std = np.std(X_arr, axis=0, ddof=0, dtype=np.float64) + 1e-9

    def compute_scores(self, X, batch_size: int = 100000) -> np.ndarray:
        if isinstance(X, pd.DataFrame):
            X_arr = X[self.feature_names].to_numpy(dtype=np.float32)
        else:
            X_arr = np.asarray(X, dtype=np.float32)

        n_samples = len(X_arr)
        scores = np.zeros(n_samples, dtype=np.float32)
        mu_f32 = self.mu.astype(np.float32)
        std_f32 = self.std.astype(np.float32)

        for i in range(0, n_samples, batch_size):
            chunk = X_arr[i:i + batch_size]
            z2 = np.square((chunk - mu_f32) / std_f32)
            z2_capped = np.minimum(z2, self.max_z2)
            scores[i:i + batch_size] = np.mean(z2_capped / self.max_z2, axis=1)
        return scores


def evaluate_f1(scores: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    y_hat = (scores > threshold).astype(int)
    tp = int(np.sum((y_hat == 1) & (labels == 1)))
    fp = int(np.sum((y_hat == 1) & (labels == 0)))
    fn = int(np.sum((y_hat == 0) & (labels == 1)))
    tn = int(np.sum((y_hat == 0) & (labels == 0)))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "f1": f1,
        "precision": precision,
        "recall": recall,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def predict_iforest_scores(model, X, batch_size: int = 100000) -> np.ndarray:
    n_samples = len(X)
    scores = np.zeros(n_samples, dtype=np.float64)
    is_df = isinstance(X, pd.DataFrame)
    for i in range(0, n_samples, batch_size):
        chunk = X.iloc[i:i + batch_size] if is_df else X[i:i + batch_size]
        scores[i:i + batch_size] = -model.decision_function(chunk)
    return scores


def train_and_eval_models(
    train_csv: str = None,
    val_csv: str = None,
    test_csv: str = None,
    models_dir: str = None,
):
    if train_csv is None:
        train_csv = os.path.join(ROOT_DIR, "data", "anomaly_l3", "train_normal.csv")
    if val_csv is None:
        val_csv = os.path.join(ROOT_DIR, "data", "anomaly_l3", "val_mixed.csv")
    if test_csv is None:
        test_csv = os.path.join(ROOT_DIR, "data", "anomaly_l3", "test_mixed.csv")
    if models_dir is None:
        models_dir = os.path.join(ROOT_DIR, "models")

    os.makedirs(models_dir, exist_ok=True)

    print("=" * 60)
    print("NOVASAT Phase 4 — Anomaly Detection Model Training")
    print("=" * 60)

    if not os.path.exists(train_csv):
        raise FileNotFoundError(f"Missing training dataset: {train_csv}")
    if not os.path.exists(val_csv):
        raise FileNotFoundError(f"Missing validation dataset: {val_csv}")
    if not os.path.exists(test_csv):
        raise FileNotFoundError(f"Missing test dataset: {test_csv}")

    print("Loading training dataset...")
    train_df = pd.read_csv(train_csv)
    print(f"  Train normal rows: {len(train_df):,}")

    # Prepare features
    feature_cols = [c for c in train_df.columns if c not in DROP_COLS and pd.api.types.is_numeric_dtype(train_df[c])]
    X_train = train_df[feature_cols].fillna(0).astype(np.float32)

    # 1. Train & Evaluate Gaussian Density Model
    print("\n--- 1. Training Gaussian Density Estimation Model ---")
    print(f"X_train shape: {X_train.shape}")
    print(f"Exact feature columns going into .fit() ({len(X_train.columns)} features):")
    print(list(X_train.columns))
    print()
    gaussian_model = GaussianDensityModel()
    gaussian_model.fit(X_train)

    print("Loading validation dataset...")
    val_df = pd.read_csv(val_csv)
    print(f"  Val mixed rows:   {len(val_df):,}")
    X_val = val_df[feature_cols].fillna(0).astype(np.float32)
    y_val = (val_df["scenario_type"] != "normal").astype(int).to_numpy()

    print("Loading test dataset...")
    test_df = pd.read_csv(test_csv)
    print(f"  Test mixed rows:  {len(test_df):,}")
    X_test = test_df[feature_cols].fillna(0).astype(np.float32)
    y_test = (test_df["scenario_type"] != "normal").astype(int).to_numpy()

    val_scores_g = gaussian_model.compute_scores(X_val)
    best_threshold_g = 0.0
    best_f1_g = 0.0
    for thresh in np.linspace(0.0, 1.0, 500):
        metrics = evaluate_f1(val_scores_g, y_val, thresh)
        if metrics["f1"] > best_f1_g:
            best_f1_g = metrics["f1"]
            best_threshold_g = thresh

    test_scores_g = gaussian_model.compute_scores(X_test)
    test_metrics_g = evaluate_f1(test_scores_g, y_test, best_threshold_g)

    print(f"Gaussian Density Model Results:")
    print(f"  Optimal Val Threshold: {best_threshold_g:.4f}")
    print(f"  Validation F1-Score:   {best_f1_g:.4f}")
    print(f"  Test F1-Score:         {test_metrics_g['f1']:.4f} (Precision: {test_metrics_g['precision']:.4f}, Recall: {test_metrics_g['recall']:.4f})")

    gaussian_pkl = os.path.join(models_dir, "gaussian_model.pkl")
    with open(gaussian_pkl, "wb") as f:
        pickle.dump(gaussian_model, f)
    print(f"Saved Gaussian model to: {gaussian_pkl}")

    # 2. Train & Evaluate Isolation Forest Model
    print("\n--- 2. Training Isolation Forest Model ---")
    iforest = IsolationForest(n_estimators=100, max_samples=256, contamination=0.1, random_state=42, n_jobs=2)
    X_train_if = X_train.sample(n=min(200000, len(X_train)), random_state=42) if len(X_train) > 200000 else X_train
    iforest.fit(X_train_if)

    val_scores_if = predict_iforest_scores(iforest, X_val)
    best_threshold_if = 0.0
    best_f1_if = 0.0
    min_s, max_s = val_scores_if.min(), val_scores_if.max()
    for thresh in np.linspace(min_s, max_s, 500):
        metrics = evaluate_f1(val_scores_if, y_val, thresh)
        if metrics["f1"] > best_f1_if:
            best_f1_if = metrics["f1"]
            best_threshold_if = thresh

    test_scores_if = predict_iforest_scores(iforest, X_test)
    test_metrics_if = evaluate_f1(test_scores_if, y_test, best_threshold_if)

    print(f"Isolation Forest Model Results:")
    print(f"  Optimal Val Threshold: {best_threshold_if:.4f}")
    print(f"  Validation F1-Score:   {best_f1_if:.4f}")
    print(f"  Test F1-Score:         {test_metrics_if['f1']:.4f} (Precision: {test_metrics_if['precision']:.4f}, Recall: {test_metrics_if['recall']:.4f})")

    iforest_pkl = os.path.join(models_dir, "isolation_forest_model.pkl")
    with open(iforest_pkl, "wb") as f:
        pickle.dump(iforest, f)
    print(f"Saved Isolation Forest model to: {iforest_pkl}")

    print("\n==================================================")
    print("ALL MODELS TRAINED AND SAVED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    train_and_eval_models()
