import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def densityEstimation(x, mu, std):
    return (1 / (2.50663 * std)) * np.exp(-0.5 * (((x - mu) / std) ** 2))

def compute_anomaly_score(x, mu, std, max_z2=25.0):
    z2 = np.square((x - mu) / std)
    z2_capped = np.minimum(z2, max_z2)
    return np.mean(z2_capped / max_z2, axis=1)

def f1(scores, y, e):
    yhat = (scores > e).astype(int)
    tp = np.sum((yhat == 1) & (y == 1))
    fp = np.sum((yhat == 1) & (y == 0))
    fn = np.sum((yhat == 0) & (y == 1))
    if 2 * tp + fp + fn == 0:
        return 0.0
    return 2 * tp / (2 * tp + fp + fn)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
train_csv = os.path.join(BASE_DIR, "data", "anomaly_l3", "train_normal.csv")

drop_cols = ['timestamp', 'window_id', 'N', 'is_attack_active', 'is_node_compromised', 'is_false_revocation_event']

X_train = pd.read_csv(train_csv)
X_num = X_train.drop(columns=[c for c in drop_cols if c in X_train.columns]).select_dtypes(include=[np.number])
x_arr = X_num.to_numpy()

mu = np.mean(x_arr, axis=0)
std = X_num.std(axis=0).to_numpy() + 1e-9

P_calc = densityEstimation(x_arr, mu, std)
P_final = np.sum(np.log(np.maximum(P_calc, 1e-300)), axis=1)
train_scores = compute_anomaly_score(x_arr, mu, std)

print("Density Matrix Shape:", P_calc.shape)
print("Final Density Matrix Shape:", P_final.shape)
print("Final Density Matrix (First 5):", P_final[:5])
print("Training Anomaly Scores (First 5):", train_scores[:5])

val_csv = os.path.join(BASE_DIR, "data", "anomaly_l3", "val_mixed.csv")

X_val = pd.read_csv(val_csv)
X_val_num = X_val[X_num.columns]
x_val_arr = X_val_num.to_numpy()

P_val_calc = densityEstimation(x_val_arr, mu, std)
P_val_final = np.sum(np.log(np.maximum(P_val_calc, 1e-300)), axis=1)
val_scores = compute_anomaly_score(x_val_arr, mu, std)

print("\nValidation Density Matrix Shape:", P_val_calc.shape)
print("Validation Final Density Matrix Shape:", P_val_final.shape)
print("Validation Final Density Matrix (First 5):", P_val_final[:5])
print("Validation Anomaly Scores (First 5):", val_scores[:5])

y = (X_val['scenario_type'] != 'normal').astype(int)

best_threshold = 0
best_f1 = 0

for e in np.linspace(0.0, 1.0, 1000):
    f1_score = f1(val_scores, y, e)
    if f1_score > best_f1:
        best_f1 = f1_score
        best_threshold = e

print(f"\nOptimal Anomaly Score Threshold: {best_threshold:.4f}")
print(f"Best F1 Score: {best_f1:.4f}")
