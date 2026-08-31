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
