"""
train_triage_classifier.py

Trains and evaluates the lightweight ML triage pre-filter classifier (Part F).
Loaded read-only by server.py at startup to skip expensive 2D Pc calculations for safe pairs.
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, f1_score, precision_score, recall_score

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from experiments.generate_triage_dataset import generate_triage_data, DATA_DIR


def train_triage_model(data_csv: str = None, models_dir: str = None):
    if data_csv is None:
        data_csv = os.path.join(DATA_DIR, "triage_dataset.csv")
    if models_dir is None:
        models_dir = os.path.join(ROOT_DIR, "models")

    if not os.path.exists(data_csv):
        generate_triage_data(n_scenarios=40, output_csv=data_csv)

    print("=" * 60)
    print("Training ML Triage Classifier Model (Part F)")
    print("=" * 60)

    df = pd.read_csv(data_csv)
    print(f"Loaded dataset: {len(df):,} rows")

    feature_cols = ["miss_distance_km", "rel_velocity_km_s"]
    X = df[feature_cols].values
    y = df["is_conjunction"].values

    # Train / Val / Test split (60% Train, 20% Val, 20% Test)
    X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.4, random_state=42, stratify=y)
    X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp)

    print(f"  Train samples: {len(X_train):,}")
    print(f"  Val samples:   {len(X_val):,}")
    print(f"  Test samples:  {len(X_test):,}")

    # Build Pipeline
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(class_weight="balanced", random_state=42))
    ])

    pipeline.fit(X_train, y_train)

    # Validation Set Metrics
    val_preds = pipeline.predict(X_val)
    val_f1 = f1_score(y_val, val_preds)
    val_prec = precision_score(y_val, val_preds)
    val_rec = recall_score(y_val, val_preds)

    print("\n--- Validation Performance ---")
    print(f"  F1-Score:   {val_f1:.4f}")
    print(f"  Precision:  {val_prec:.4f}")
    print(f"  Recall:     {val_rec:.4f}")

    # Test Set Metrics (Single Touch)
    test_preds = pipeline.predict(X_test)
    test_f1 = f1_score(y_test, test_preds)
    test_prec = precision_score(y_test, test_preds)
    test_rec = recall_score(y_test, test_preds)

    print("\n--- Test Performance (Single Touch) ---")
    print(f"  F1-Score:   {test_f1:.4f}")
    print(f"  Precision:  {test_prec:.4f}")
    print(f"  Recall:     {test_rec:.4f}")

    # Save Model
    os.makedirs(models_dir, exist_ok=True)
    model_pkl = os.path.join(models_dir, "triage_classifier.pkl")
    with open(model_pkl, "wb") as f:
        pickle.dump(pipeline, f)

    print(f"\nSaved ML Triage Classifier to: {model_pkl}")
    return pipeline


if __name__ == "__main__":
    train_triage_model()
