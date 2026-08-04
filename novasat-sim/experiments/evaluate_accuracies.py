import os
import sys
import gc
import pickle
import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from experiments.train_anomaly_models import GaussianDensityModel, predict_iforest_scores, DROP_COLS

def evaluate_csv_in_chunks(csv_path: str, gaussian_model, iforest, threshold_g: float, threshold_if: float, feature_cols: list, is_train_normal: bool = False, chunksize: int = 200000):
    total = 0
    
    # Gaussian counters
    tp_g, fp_g, fn_g, tn_g = 0, 0, 0, 0
    # Isolation Forest counters
    tp_if, fp_if, fn_if, tn_if = 0, 0, 0, 0

    for chunk in pd.read_csv(csv_path, chunksize=chunksize):
        if is_train_normal:
            y = np.zeros(len(chunk), dtype=int)
        else:
            y = (chunk["scenario_type"] != "normal").astype(int).to_numpy()
            
        X = chunk[feature_cols].fillna(0).astype(np.float32)
        
        # Gaussian
        scores_g = gaussian_model.compute_scores(X)
        y_hat_g = (scores_g > threshold_g).astype(int)
        tp_g += int(np.sum((y_hat_g == 1) & (y == 1)))
        fp_g += int(np.sum((y_hat_g == 1) & (y == 0)))
        fn_g += int(np.sum((y_hat_g == 0) & (y == 1)))
        tn_g += int(np.sum((y_hat_g == 0) & (y == 0)))
        
        # Isolation Forest
        scores_if = predict_iforest_scores(iforest, X)
        y_hat_if = (scores_if > threshold_if).astype(int)
        tp_if += int(np.sum((y_hat_if == 1) & (y == 1)))
        fp_if += int(np.sum((y_hat_if == 1) & (y == 0)))
        fn_if += int(np.sum((y_hat_if == 0) & (y == 1)))
        tn_if += int(np.sum((y_hat_if == 0) & (y == 0)))
        
        total += len(chunk)
        
    acc_g = (tp_g + tn_g) / total if total > 0 else 0.0
    acc_if = (tp_if + tn_if) / total if total > 0 else 0.0
    
    return {
        "gaussian": {"accuracy": acc_g, "tp": tp_g, "fp": fp_g, "fn": fn_g, "tn": tn_g, "total": total},
        "iforest": {"accuracy": acc_if, "tp": tp_if, "fp": fp_if, "fn": fn_if, "tn": tn_if, "total": total}
    }


def evaluate_all():
    train_csv = os.path.join(ROOT_DIR, "data", "anomaly_l3", "train_normal.csv")
    val_csv = os.path.join(ROOT_DIR, "data", "anomaly_l3", "val_mixed.csv")
    test_csv = os.path.join(ROOT_DIR, "data", "anomaly_l3", "test_mixed.csv")
    models_dir = os.path.join(ROOT_DIR, "models")

    gaussian_pkl = os.path.join(models_dir, "gaussian_model.pkl")
    iforest_pkl = os.path.join(models_dir, "isolation_forest_model.pkl")

    with open(gaussian_pkl, "rb") as f:
        gaussian_model = pickle.load(f)
    with open(iforest_pkl, "rb") as f:
        iforest = pickle.load(f)

    # Read header to get feature columns
    sample_df = pd.read_csv(val_csv, nrows=10)
    feature_cols = [c for c in sample_df.columns if c not in DROP_COLS and pd.api.types.is_numeric_dtype(sample_df[c])]

    # 1. Process Validation set to tune thresholds
    print("Loading Validation dataset for threshold tuning...")
    val_df = pd.read_csv(val_csv)
    X_val = val_df[feature_cols].fillna(0).astype(np.float32)
    y_val = (val_df["scenario_type"] != "normal").astype(int).to_numpy()

    # Tune Gaussian threshold
    val_scores_g = gaussian_model.compute_scores(X_val)
    best_threshold_g = 0.0
    best_f1_g = -1.0
    for thresh in np.linspace(0.0, 1.0, 500):
        y_hat = (val_scores_g > thresh).astype(int)
        tp = np.sum((y_hat == 1) & (y_val == 1))
        fp = np.sum((y_hat == 1) & (y_val == 0))
        fn = np.sum((y_hat == 0) & (y_val == 1))
        p = tp / (tp + fp) if (tp + fp) > 0 else 0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        if f1 > best_f1_g:
            best_f1_g = f1
            best_threshold_g = thresh

    # Tune Isolation Forest threshold
    val_scores_if = predict_iforest_scores(iforest, X_val)
    best_threshold_if = 0.0
    best_f1_if = -1.0
    min_s, max_s = val_scores_if.min(), val_scores_if.max()
    for thresh in np.linspace(min_s, max_s, 500):
        y_hat = (val_scores_if > thresh).astype(int)
        tp = np.sum((y_hat == 1) & (y_val == 1))
        fp = np.sum((y_hat == 1) & (y_val == 0))
        fn = np.sum((y_hat == 0) & (y_val == 1))
        p = tp / (tp + fp) if (tp + fp) > 0 else 0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        if f1 > best_f1_if:
            best_f1_if = f1
            best_threshold_if = thresh

    del val_df, X_val, y_val, val_scores_g, val_scores_if
    gc.collect()

    print(f"Optimal Gaussian Threshold: {best_threshold_g:.4f}")
    print(f"Optimal Isolation Forest Threshold: {best_threshold_if:.4f}")

    # 2. Evaluate Validation Set
    print("\nEvaluating Validation dataset metrics...")
    val_metrics = evaluate_csv_in_chunks(val_csv, gaussian_model, iforest, best_threshold_g, best_threshold_if, feature_cols, is_train_normal=False)

    # 3. Evaluate Training Set
    print("\nEvaluating Training dataset metrics...")
    train_metrics = evaluate_csv_in_chunks(train_csv, gaussian_model, iforest, best_threshold_g, best_threshold_if, feature_cols, is_train_normal=True)

    # 4. Evaluate Test Set
    print("\nEvaluating Test dataset metrics...")
    test_metrics = evaluate_csv_in_chunks(test_csv, gaussian_model, iforest, best_threshold_g, best_threshold_if, feature_cols, is_train_normal=False)

    # Output Final Results
    print("\n" + "="*75)
    print("GAUSSIAN DENSITY MODEL ACCURACY METRICS")
    print(f"Optimal Threshold (Val F1): {best_threshold_g:.4f}")
    print(f"  Train Accuracy:      {train_metrics['gaussian']['accuracy']*100:.4f}% ({train_metrics['gaussian']['tn']:,} / {train_metrics['gaussian']['total']:,})")
    print(f"  Validation Accuracy: {val_metrics['gaussian']['accuracy']*100:.4f}% ({val_metrics['gaussian']['tp']+val_metrics['gaussian']['tn']:,} / {val_metrics['gaussian']['total']:,})")
    print(f"  Test Accuracy:       {test_metrics['gaussian']['accuracy']*100:.4f}% ({test_metrics['gaussian']['tp']+test_metrics['gaussian']['tn']:,} / {test_metrics['gaussian']['total']:,})")

    print("\n" + "="*75)
    print("ISOLATION FOREST MODEL ACCURACY METRICS")
    print(f"Optimal Threshold (Val F1): {best_threshold_if:.4f}")
    print(f"  Train Accuracy:      {train_metrics['iforest']['accuracy']*100:.4f}% ({train_metrics['iforest']['tn']:,} / {train_metrics['iforest']['total']:,})")
    print(f"  Validation Accuracy: {val_metrics['iforest']['accuracy']*100:.4f}% ({val_metrics['iforest']['tp']+val_metrics['iforest']['tn']:,} / {val_metrics['iforest']['total']:,})")
    print(f"  Test Accuracy:       {test_metrics['iforest']['accuracy']*100:.4f}% ({test_metrics['iforest']['tp']+test_metrics['iforest']['tn']:,} / {test_metrics['iforest']['total']:,})")
    print("="*75)

if __name__ == "__main__":
    evaluate_all()
