"""
train_comms_decision_model.py — Scaffolding Companion Guide (6B)

Per Part B.5: Hand-coding companion guide (architecture and hyperparameters given precisely, code left for the user to write).

Feature Vector (named, ordered, real units):
  1. battery_pct                : float, 0–100 %
  2. buffer_occupancy_pct       : float, 0–100 %
  3. link_margin_db             : float, dB (link quality proxy / max elevation angle to relay)
  4. time_since_last_contact_s  : float, seconds
  (Note: anomaly_score is EXCLUDED per B.2 scope boundary)

Goal:
  Complete the function implementations below to load raw OPSSAT-AD telemetry, apply a transparent,
  versioned heuristic for ground-truth labeling, fit a LogisticRegression classifier + StandardScaler,
  and evaluate holdout metrics (Precision, Recall, F1, ROC-AUC).
"""

import os
import sys
import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Named, versioned feature schema (B.4 spec - MUST NOT reuse 34-feature anomaly schema)
COMMS_DECISION_FEATURE_COLS = [
    "battery_pct",
    "buffer_occupancy_pct",
    "link_margin_db",
    "time_since_last_contact_s",
]


def load_and_label_raw_dataset(data_path: str = None) -> pd.DataFrame:
    """
    Scaffold 1: Load raw dataset & generate heuristic ground-truth labels (v1.0).

    Instructions:
    1. Load OPSSAT-AD raw housekeeping dataset from data_path (e.g. data/esa_adb/opssat_ad_benchmark.csv).
    2. Extract/map the 4 required features: battery_pct, buffer_occupancy_pct, link_margin_db, time_since_last_contact_s.
    3. Apply the transparent versioned heuristic:
         Transmit (1) if battery_pct >= 20.0 AND (buffer_occupancy_pct >= 60.0 OR link_margin_db >= 15.0 OR time_since_last_contact_s >= 1800.0).
         Otherwise Hold (0).
    4. Return DataFrame containing feature columns + 'should_transmit' label column.
    """
    # TODO: Implement dataset loading & heuristic labeling here
    raise NotImplementedError("Hand-coding task: Implement load_and_label_raw_dataset() per B.5 companion guide.")


def train_model(X_train: np.ndarray, y_train: np.ndarray):
    """
    Scaffold 2: Fit model & scaler on training data ONLY.

    Instructions:
    1. Initialize and fit StandardScaler on X_train.
    2. Fit LogisticRegression(C=1.0, random_state=42) or DecisionTreeClassifier(max_depth=4) on scaled X_train and y_train.
    3. Return fitted (model, scaler) tuple.
    """
    # TODO: Implement model & scaler fitting here
    raise NotImplementedError("Hand-coding task: Implement train_model() per B.5 companion guide.")


def evaluate_on_holdout(model, scaler, X_test: np.ndarray, y_test: np.ndarray) -> dict:
    """
    Scaffold 3: Evaluate model on holdout test split.

    Instructions:
    1. Transform X_test using train-fitted scaler (DO NOT refit scaler on test set).
    2. Predict continuous probabilities p_transmit = model.predict_proba(X_test_scaled)[:, 1].
    3. Compute y_pred = (p_transmit >= 0.5).astype(int).
    4. Compute and return dictionary with: precision, recall, f1, roc_auc.
       (Avoid accuracy alone to prevent majority-class imbalance traps).
    """
    # TODO: Implement holdout evaluation metrics calculation here
    raise NotImplementedError("Hand-coding task: Implement evaluate_on_holdout() per B.5 companion guide.")


def evaluate_on_novasat_sim(model, scaler, sim_df: pd.DataFrame) -> dict:
    """
    Scaffold 4: Evaluate fidelity on NOVASAT simulated telemetry schema.

    Instructions:
    1. Extract COMMS_DECISION_FEATURE_COLS from sim_df.
    2. Apply heuristic label generator to sim_df to get ground truth.
    3. Call evaluate_on_holdout() to report simulation fidelity metrics.
    """
    # TODO: Implement NOVASAT simulation fidelity evaluation here
    raise NotImplementedError("Hand-coding task: Implement evaluate_on_novasat_sim() per B.5 companion guide.")


def main():
    print("=" * 70)
    print("NOVASAT 6B — Comms Decision Model Companion Guide (Scaffolded)")
    print("=" * 70)
    print("Please implement the functions above to hand-code the training pipeline.")
    print("Refer to B.5 in the specification for architecture guidelines.")


if __name__ == "__main__":
    main()
