"""
train_ensemble_model.py

NOVASAT Anomaly Detection — Ensemble Model Training & Evaluation
Combines Gaussian Density Estimation and Isolation Forest into one tuned probability score via Logistic Regression Stacking.

Data leakage prevention protocol (Part B.3):
1. Fit base models (Gaussian & Isolation Forest) on train set (`train_normal.csv`) only.
2. Compute train set raw scores and fit StandardScaler on train raw scores ONLY.
3. Compute val set raw scores, standardize via train-fitted scaler, and fit LogisticRegression meta-model on val scores vs. val labels (base models frozen).
4. Evaluate on test set (`test_mixed.csv`) touched exactly once at the end.
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from experiments.train_anomaly_models import GaussianDensityModel, predict_iforest_scores, evaluate_f1, DROP_COLS


def load_features_and_labels(csv_path: str, is_train: bool = False, chunksize: int = 200000):
    """Memory-efficient chunked loader for large NOVASAT CSV datasets."""
    # Read only first line to get column names
    header_df = pd.read_csv(csv_path, nrows=1)
    all_cols = list(header_df.columns)
    
    feature_cols = [c for c in all_cols if c not in DROP_COLS]
    dtype_dict = {c: np.float32 for c in feature_cols}
    
    chunks_x = []
    chunks_y = []
    
    if is_train:
        for chunk in pd.read_csv(csv_path, usecols=feature_cols, dtype=dtype_dict, chunksize=chunksize, low_memory=False):
            arr = chunk[feature_cols].fillna(0).to_numpy(dtype=np.float32)
            chunks_x.append(arr)
        X = np.vstack(chunks_x)
        y = None
    else:
        use_cols = feature_cols + ["scenario_type"]
        for chunk in pd.read_csv(csv_path, usecols=use_cols, dtype=dtype_dict, chunksize=chunksize, low_memory=False):
            arr_x = chunk[feature_cols].fillna(0).to_numpy(dtype=np.float32)
            arr_y = (chunk["scenario_type"] != "normal").astype(int).to_numpy()
            chunks_x.append(arr_x)
            chunks_y.append(arr_y)
        X = np.vstack(chunks_x)
        y = np.concatenate(chunks_y)
        
    return X, y, feature_cols


def train_and_eval_ensemble(
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

    print("=" * 70)
    print("NOVASAT Phase 4 — Anomaly Detection Stacking Ensemble Training")
    print("=" * 70)

    # 1. Load Training Data
    print("\n[Step 1/5] Loading training dataset (train_normal.csv)...")
    X_train, _, feature_cols = load_features_and_labels(train_csv, is_train=True)
    print(f"  Train normal rows: {len(X_train):,}, features: {X_train.shape[1]}")

    # 2. Fit Base Models on Train Data ONLY
    print("\n[Step 2/5] Fitting base models on train_normal.csv...")
    print("  Fitting Gaussian Density Model...")
    gaussian_model = GaussianDensityModel()
    gaussian_model.fit(X_train)

    print("  Fitting Isolation Forest Model...")
    iforest_model = IsolationForest(n_estimators=100, max_samples=256, contamination=0.1, random_state=42, n_jobs=2)
    sample_size = min(200000, len(X_train))
    idx = np.random.RandomState(42).choice(len(X_train), size=sample_size, replace=False)
    X_train_if = X_train[idx]
    iforest_model.fit(X_train_if)

    # Compute raw scores on Train set for StandardScaler
    print("  Computing base raw scores on train set...")
    train_scores_g = gaussian_model.compute_scores(X_train)
    train_scores_if = predict_iforest_scores(iforest_model, X_train)

    # Free X_train
    del X_train

    train_scores_matrix = np.column_stack([train_scores_g, train_scores_if])

    print("  Fitting StandardScaler on train raw scores ONLY...")
    scaler = StandardScaler()
    scaler.fit(train_scores_matrix)
    print(f"    Gaussian Raw Score Train Mean: {scaler.mean_[0]:.6f}, Std: {scaler.scale_[0]:.6f}")
    print(f"    Isolation Forest Raw Score Train Mean: {scaler.mean_[1]:.6f}, Std: {scaler.scale_[1]:.6f}")

    del train_scores_matrix

    # 3. Load Validation Set & Fit Meta-Model (Logistic Regression)
    print("\n[Step 3/5] Loading validation dataset (val_mixed.csv) and fitting meta-model...")
    X_val, y_val, _ = load_features_and_labels(val_csv, is_train=False)
    print(f"  Val mixed rows: {len(X_val):,}")

    val_scores_g = gaussian_model.compute_scores(X_val)
    val_scores_if = predict_iforest_scores(iforest_model, X_val)
    del X_val

    val_scores_matrix = np.column_stack([val_scores_g, val_scores_if])
    val_z_scores = scaler.transform(val_scores_matrix)

    # Tune individual thresholds on validation set
    best_thresh_g = 0.0
    best_f1_g_val = 0.0
    for thresh in np.linspace(val_scores_g.min(), val_scores_g.max(), 500):
        m = evaluate_f1(val_scores_g, y_val, thresh)
        if m["f1"] > best_f1_g_val:
            best_f1_g_val = m["f1"]
            best_thresh_g = thresh

    best_thresh_if = 0.0
    best_f1_if_val = 0.0
    for thresh in np.linspace(val_scores_if.min(), val_scores_if.max(), 500):
        m = evaluate_f1(val_scores_if, y_val, thresh)
        if m["f1"] > best_f1_if_val:
            best_f1_if_val = m["f1"]
            best_thresh_if = thresh

    print(f"  Validation Gaussian Best Threshold: {best_thresh_g:.4f} (Val F1: {best_f1_g_val:.4f})")
    print(f"  Validation Isolation Forest Best Threshold: {best_thresh_if:.4f} (Val F1: {best_f1_if_val:.4f})")

    # Fit Logistic Regression Stacking Meta-Model
    print("  Fitting LogisticRegression meta-model on val z-scores...")
    meta_model = LogisticRegression(random_state=42)
    meta_model.fit(val_z_scores, y_val)

    val_probs_ensemble = meta_model.predict_proba(val_z_scores)[:, 1]

    # Find optimal probability threshold on validation set
    best_thresh_ens = 0.5
    best_f1_ens_val = 0.0
    for thresh in np.linspace(0.01, 0.99, 200):
        m = evaluate_f1(val_probs_ensemble, y_val, thresh)
        if m["f1"] > best_f1_ens_val:
            best_f1_ens_val = m["f1"]
            best_thresh_ens = thresh

    print(f"  Validation Ensemble Best Prob Threshold: {best_thresh_ens:.4f} (Val F1: {best_f1_ens_val:.4f})")

    w1 = meta_model.coef_[0][0]
    w2 = meta_model.coef_[0][1]
    b = meta_model.intercept_[0]
    print(f"\n  Fitted Stacking Meta-Model Coefficients:")
    print(f"    w1 (Gaussian z-score weight):         {w1:.6f}")
    print(f"    w2 (Isolation Forest z-score weight): {w2:.6f}")
    print(f"    b  (Bias / Intercept):               {b:.6f}")
    print(f"\n  Combined Score Formula:")
    print(f"    z_gaussian = (raw_gaussian - {scaler.mean_[0]:.6f}) / {scaler.scale_[0]:.6f}")
    print(f"    z_iforest  = (raw_iforest  - {scaler.mean_[1]:.6f}) / {scaler.scale_[1]:.6f}")
    print(f"    P(anomaly) = sigmoid({w1:.6f} * z_gaussian + {w2:.6f} * z_iforest + ({b:.6f}))")

    # 4. Load Test Set & Evaluate (TOUCHED ONCE AT THE VERY END)
    print("\n[Step 4/5] Evaluating on Test Dataset (test_mixed.csv) — Single Touch...")
    X_test, y_test, _ = load_features_and_labels(test_csv, is_train=False)
    print(f"  Test mixed rows: {len(X_test):,}")

    test_scores_g = gaussian_model.compute_scores(X_test)
    test_scores_if = predict_iforest_scores(iforest_model, X_test)
    del X_test

    test_scores_matrix = np.column_stack([test_scores_g, test_scores_if])

    # Evaluate individual models on test set
    test_metrics_g = evaluate_f1(test_scores_g, y_test, best_thresh_g)
    test_metrics_if = evaluate_f1(test_scores_if, y_test, best_thresh_if)

    # Evaluate ensemble model on test set
    test_z_scores = scaler.transform(test_scores_matrix)
    test_probs_ens = meta_model.predict_proba(test_z_scores)[:, 1]
    test_metrics_ens = evaluate_f1(test_probs_ens, y_test, best_thresh_ens)

    # 5. Side-by-Side Results & Definition of Done Audit
    print("\n" + "=" * 70)
    print("FINAL TEST SET EVALUATION SUMMARY (Side-by-Side Comparison)")
    print("=" * 70)
    print(f"{'Model':<25} | {'F1-Score':<10} | {'Precision':<10} | {'Recall':<10}")
    print("-" * 65)
    print(f"{'Gaussian (EllipticEnv)':<25} | {test_metrics_g['f1']:<10.4f} | {test_metrics_g['precision']:<10.4f} | {test_metrics_g['recall']:<10.4f}")
    print(f"{'Isolation Forest':<25} | {test_metrics_if['f1']:<10.4f} | {test_metrics_if['precision']:<10.4f} | {test_metrics_if['recall']:<10.4f}")
    print(f"{'Stacking Ensemble':<25} | {test_metrics_ens['f1']:<10.4f} | {test_metrics_ens['precision']:<10.4f} | {test_metrics_ens['recall']:<10.4f}")
    print("=" * 70)

    # Save artifacts
    gaussian_pkl = os.path.join(models_dir, "gaussian_model.pkl")
    iforest_pkl = os.path.join(models_dir, "isolation_forest_model.pkl")
    scaler_pkl = os.path.join(models_dir, "ensemble_scaler.pkl")
    meta_pkl = os.path.join(models_dir, "ensemble_meta_model.pkl")

    with open(gaussian_pkl, "wb") as f:
        pickle.dump(gaussian_model, f)
    with open(iforest_pkl, "wb") as f:
        pickle.dump(iforest_model, f)
    with open(scaler_pkl, "wb") as f:
        pickle.dump(scaler, f)
    with open(meta_pkl, "wb") as f:
        pickle.dump(meta_model, f)

    print(f"\nArtifacts successfully saved to {models_dir}:")
    print(f"  - {os.path.basename(gaussian_pkl)}")
    print(f"  - {os.path.basename(iforest_pkl)}")
    print(f"  - {os.path.basename(scaler_pkl)}")
    print(f"  - {os.path.basename(meta_pkl)}")

    return {
        "gaussian": test_metrics_g,
        "iforest": test_metrics_if,
        "ensemble": test_metrics_ens,
        "coefs": {"w1": w1, "w2": w2, "b": b},
        "scaler": {"mean": scaler.mean_, "scale": scaler.scale_},
        "thresholds": {
            "gaussian": best_thresh_g,
            "iforest": best_thresh_if,
            "ensemble": best_thresh_ens,
        }
    }


if __name__ == "__main__":
    train_and_eval_ensemble()
