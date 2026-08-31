import os
import sys
import pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

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

def main():
    print("=" * 80)
    print("OPSSAT Anomaly Detection Validation Experiment (Gaussian + iForest Ensemble)")
    print("=" * 80)

    # 1. Load Data
    data_path = os.path.join(ROOT_DIR, "data", "opsatt_dataset.csv")
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Missing OPSSAT dataset: {data_path}")

    print("Loading dataset...")
    df = pd.read_csv(data_path)
    print(f"Loaded {len(df):,} rows from {os.path.basename(data_path)}")

    # Define metadata and feature columns
    drop_cols = ["segment", "anomaly", "train", "channel"]
    feature_cols = [c for c in df.columns if c not in drop_cols]
    
    # 2. Skewness Correction (Log-transform right-skewed positive features)
    print("\nApplying logarithmic transformations to right-skewed features...")
    skewed_cols = ["var", "std", "diff_var", "diff2_var", "gaps_squared", "var_div_duration", "var_div_len", "kurtosis", "n_peaks", "diff_peaks", "diff2_peaks"]
    for c in skewed_cols:
        if c in df.columns:
            min_val = df[c].min()
            if min_val >= 0:
                epsilon = 1e-12 if min_val == 0 else 0.0
                df[c] = np.log(df[c] + epsilon)
            else:
                # Symmetric log transform for negative-valued features
                df[c] = np.sign(df[c]) * np.log1p(np.abs(df[c]))

    # Cast all feature columns to float64
    df[feature_cols] = df[feature_cols].astype(np.float64)

    # Split into train partition (train == 1) and test partition (train == 0)
    train_part = df[df["train"] == 1].reset_index(drop=True)
    test_part = df[df["train"] == 0].reset_index(drop=True)
    
    # 3. Channel-Specific Scaling parameters computed on Train normal set ONLY
    normal_train_all = train_part[train_part["anomaly"] == 0].reset_index(drop=True)
    
    channel_stats = {}
    global_means = normal_train_all[feature_cols].mean()
    global_stds = normal_train_all[feature_cols].std() + 1e-9
    
    for chan in df["channel"].unique():
        chan_base = normal_train_all[normal_train_all["channel"] == chan]
        if len(chan_base) > 5:
            channel_stats[chan] = {
                "mean": chan_base[feature_cols].mean(),
                "std": chan_base[feature_cols].std() + 1e-9
            }
        else:
            channel_stats[chan] = {
                "mean": global_means,
                "std": global_stds
            }
            
    def scale_by_channel(target_df):
        scaled_df = target_df.copy()
        scaled_df[feature_cols] = scaled_df[feature_cols].astype(np.float64)
        for chan in target_df["channel"].unique():
            idx = target_df["channel"] == chan
            stats = channel_stats.get(chan, {"mean": global_means, "std": global_stds})
            scaled_df.loc[idx, feature_cols] = (target_df.loc[idx, feature_cols] - stats["mean"]) / stats["std"]
        return scaled_df

    print("Scaling features independently for each channel...")
    train_scaled = scale_by_channel(train_part)
    test_scaled = scale_by_channel(test_part)

    # 4. K-Fold Out-of-Fold (OOF) score generation on training partition to prevent leakage
    print("\nGenerating out-of-fold base model scores on training partition (5 folds)...")
    normal_indices = train_scaled[train_scaled["anomaly"] == 0].index.to_numpy()
    anomaly_indices = train_scaled[train_scaled["anomaly"] == 1].index.to_numpy()
    
    oof_scores_g = np.zeros(len(train_scaled))
    oof_scores_if = np.zeros(len(train_scaled))
    
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    
    for train_fold_idx, val_fold_idx in kf.split(normal_indices):
        train_normal_idx_in_part = normal_indices[train_fold_idx]
        val_normal_idx_in_part = normal_indices[val_fold_idx]
        
        X_train_fold = train_scaled.iloc[train_normal_idx_in_part][feature_cols]
        
        g_model = GaussianDensityModel()
        g_model.fit(X_train_fold)
        
        if_model = IsolationForest(n_estimators=100, max_samples=256, contamination=0.1, random_state=42, n_jobs=2)
        if_model.fit(X_train_fold)
        
        X_val_fold = train_scaled.iloc[val_normal_idx_in_part][feature_cols]
        oof_scores_g[val_fold_idx] = g_model.compute_scores(X_val_fold)
        oof_scores_if[val_fold_idx] = predict_iforest_scores(if_model, X_val_fold)

    # Predict anomalies in training partition using models fit on all normal training samples
    X_train_normal_all = train_scaled.iloc[normal_indices][feature_cols]
    g_model_train = GaussianDensityModel()
    g_model_train.fit(X_train_normal_all)
    
    if_model_train = IsolationForest(n_estimators=100, max_samples=256, contamination=0.1, random_state=42, n_jobs=2)
    if_model_train.fit(X_train_normal_all)
    
    X_train_anomaly = train_scaled.iloc[anomaly_indices][feature_cols]
    oof_scores_g[anomaly_indices] = g_model_train.compute_scores(X_train_anomaly)
    oof_scores_if[anomaly_indices] = predict_iforest_scores(if_model_train, X_train_anomaly)

    # 5. Standardize raw scores
    scaler = StandardScaler()
    scaler.fit(np.column_stack([oof_scores_g[normal_indices], oof_scores_if[normal_indices]]))
    
    train_z = scaler.transform(np.column_stack([oof_scores_g, oof_scores_if]))
    y_train = train_scaled["anomaly"].to_numpy()
    
    # 6. Fit Logistic Regression stacking meta-model
    print("Fitting Logistic Regression meta-model...")
    meta_model = LogisticRegression(random_state=42)
    meta_model.fit(train_z, y_train)
    
    # 7. Select optimal decision thresholds on the training partition
    print("Optimizing decision thresholds on training partition...")
    
    best_thresh_g = 0.0
    best_f1_g_val = 0.0
    for thresh in np.linspace(oof_scores_g.min(), oof_scores_g.max(), 500):
        m = evaluate_f1(oof_scores_g, y_train, thresh)
        if m["f1"] > best_f1_g_val:
            best_f1_g_val = m["f1"]
            best_thresh_g = thresh
            
    best_thresh_if = 0.0
    best_f1_if_val = 0.0
    for thresh in np.linspace(oof_scores_if.min(), oof_scores_if.max(), 500):
        m = evaluate_f1(oof_scores_if, y_train, thresh)
        if m["f1"] > best_f1_if_val:
            best_f1_if_val = m["f1"]
            best_thresh_if = thresh
            
    train_probs = meta_model.predict_proba(train_z)[:, 1]
    best_thresh_ens = 0.5
    best_f1_ens_val = 0.0
    for thresh in np.linspace(0.01, 0.99, 200):
        m = evaluate_f1(train_probs, y_train, thresh)
        if m["f1"] > best_f1_ens_val:
            best_f1_ens_val = m["f1"]
            best_thresh_ens = thresh
            
    print(f"  Gaussian Optimal Threshold:        {best_thresh_g:.6f} (Train F1: {best_f1_g_val:.4f})")
    print(f"  Isolation Forest Optimal Threshold: {best_thresh_if:.6f} (Train F1: {best_f1_if_val:.4f})")
    print(f"  Ensemble Optimal Threshold:        {best_thresh_ens:.6f} (Train F1: {best_f1_ens_val:.4f})")

    # 8. Single-Touch Evaluation on Test Partition (train == 0)
    print("\nRunning single-touch evaluation against the test partition (train == 0)...")
    X_test = test_scaled[feature_cols]
    y_test = test_part["anomaly"].to_numpy()
    
    test_scores_g = g_model_train.compute_scores(X_test)
    test_scores_if = predict_iforest_scores(if_model_train, X_test)
    
    test_z = scaler.transform(np.column_stack([test_scores_g, test_scores_if]))
    test_probs = meta_model.predict_proba(test_z)[:, 1]
    
    test_m_g = evaluate_f1(test_scores_g, y_test, best_thresh_g)
    test_m_if = evaluate_f1(test_scores_if, y_test, best_thresh_if)
    test_m_ens = evaluate_f1(test_probs, y_test, best_thresh_ens)
    
    w1 = meta_model.coef_[0][0]
    w2 = meta_model.coef_[0][1]
    b = meta_model.intercept_[0]
    
    print("\n" + "=" * 80)
    print("FINAL VALIDATION RESULTS - TEST SET (train == 0)")
    print("=" * 80)
    print(f"{'Model':<25} | {'F1-Score':<10} | {'Precision':<10} | {'Recall':<10} | {'TP':<5} | {'FP':<5} | {'FN':<5} | {'TN':<5}")
    print("-" * 78)
    print(f"{'Gaussian (EllipticEnv)':<25} | {test_m_g['f1']:<10.4f} | {test_m_g['precision']:<10.4f} | {test_m_g['recall']:<10.4f} | {test_m_g['tp']:<5} | {test_m_g['fp']:<5} | {test_m_g['fn']:<5} | {test_m_g['tn']:<5}")
    print(f"{'Isolation Forest':<25} | {test_m_if['f1']:<10.4f} | {test_m_if['precision']:<10.4f} | {test_m_if['recall']:<10.4f} | {test_m_if['tp']:<5} | {test_m_if['fp']:<5} | {test_m_if['fn']:<5} | {test_m_if['tn']:<5}")
    print(f"{'Stacking Ensemble':<25} | {test_m_ens['f1']:<10.4f} | {test_m_ens['precision']:<10.4f} | {test_m_ens['recall']:<10.4f} | {test_m_ens['tp']:<5} | {test_m_ens['fp']:<5} | {test_m_ens['fn']:<5} | {test_m_ens['tn']:<5}")
    print("=" * 80)
    print(f"Fitted Stacking Ensemble Equation:")
    print(f"  z_gaussian = (raw_gaussian - {scaler.mean_[0]:.6f}) / {scaler.scale_[0]:.6f}")
    print(f"  z_iforest  = (raw_iforest  - {scaler.mean_[1]:.6f}) / {scaler.scale_[1]:.6f}")
    print(f"  P(anomaly) = sigmoid({w1:.6f} * z_gaussian + {w2:.6f} * z_iforest + ({b:.6f}))")
    print("=" * 80)

    # Save artifacts
    models_dir = os.path.join(ROOT_DIR, "models", "opsatt")
    os.makedirs(models_dir, exist_ok=True)
    
    with open(os.path.join(models_dir, "gaussian_model.pkl"), "wb") as f:
        pickle.dump(g_model_train, f)
    with open(os.path.join(models_dir, "isolation_forest_model.pkl"), "wb") as f:
        pickle.dump(if_model_train, f)
    with open(os.path.join(models_dir, "ensemble_scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)
    with open(os.path.join(models_dir, "ensemble_meta_model.pkl"), "wb") as f:
        pickle.dump(meta_model, f)
    
    # Save statistics for preprocessing mapping in production
    preprocess_stats = {
        "channel_stats": {chan: {"mean": stats["mean"].to_dict(), "std": stats["std"].to_dict()} for chan, stats in channel_stats.items()},
        "global_stats": {"mean": global_means.to_dict(), "std": global_stds.to_dict()},
        "skewed_cols": skewed_cols,
        "feature_cols": feature_cols,
        "thresholds": {
            "gaussian": best_thresh_g,
            "iforest": best_thresh_if,
            "ensemble": best_thresh_ens
        }
    }
    with open(os.path.join(models_dir, "preprocess_stats.pkl"), "wb") as f:
        pickle.dump(preprocess_stats, f)

    print(f"\nTrained models and preprocessing stats successfully saved to: {models_dir}")

if __name__ == "__main__":
    main()
