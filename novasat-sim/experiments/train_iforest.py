import os
import pandas as pd  

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
train_csv = os.path.join(BASE_DIR, "data", "anomaly_l3", "train_normal.csv")
test_csv  = os.path.join(BASE_DIR, "data", "anomaly_l3", "test_mixed.csv")
cv_csv    = os.path.join(BASE_DIR, "data", "anomaly_l3", "val_mixed.csv")
art_dir   = os.path.join(BASE_DIR, "artifacts")

print("Loading datasets, please wait...")
train_df = pd.read_csv(train_csv)
cv_df = pd.read_csv(cv_csv)
test_df = pd.read_csv(test_csv)

# print basic info
print("\n--- Original Dataset Shapes ---")
print("Train shape:", train_df.shape)
print("CV shape:   ", cv_df.shape)
print("Test shape: ", test_df.shape)

# Enforce 3:1:1 Ratio (Train : CV : Test = 60% : 20% : 20%)
# Train size (167,040) represents 3 parts -> 1 part = len(train_df) // 3
n_eval = len(train_df) // 3  # 55,680 rows

def stratified_subsample(df, target_n, random_state=42):
    if len(df) <= target_n:
        return df
    # Sample proportionally across scenario types to preserve distribution
    counts = (df["scenario_type"].value_counts(normalize=True) * target_n).round().astype(int)
    diff = target_n - counts.sum()
    if diff != 0:
        counts.iloc[0] += diff
    samples = [
        df[df["scenario_type"] == cat].sample(n=min(cnt, len(df[df["scenario_type"] == cat])), random_state=random_state)
        for cat, cnt in counts.items()
    ]
    return pd.concat(samples, ignore_index=True)

cv_df = stratified_subsample(cv_df, n_eval, random_state=42)
test_df = stratified_subsample(test_df, n_eval, random_state=42)

print("\n--- Adjusted Dataset Shapes (Ratio 3:1:1) ---")
print("Train shape:", train_df.shape)
print("CV shape:   ", cv_df.shape)
print("Test shape: ", test_df.shape)

total_rows = len(train_df) + len(cv_df) + len(test_df)
print("\nRatio Breakdown:")
print(f"  Train: {len(train_df):,} rows ({len(train_df)/total_rows*100:.1f}% -> {len(train_df)/total_rows*5:.2f}/5)")
print(f"  CV:    {len(cv_df):,} rows ({len(cv_df)/total_rows*100:.1f}% -> {len(cv_df)/total_rows*5:.2f}/5)")
print(f"  Test:  {len(test_df):,} rows ({len(test_df)/total_rows*100:.1f}% -> {len(test_df)/total_rows*5:.2f}/5)")