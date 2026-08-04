"""
NOVASAT Phase 3 — Warmup Phase Validation
Validates results_experiment2_warmup.csv
"""
import os
import sys
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import pandas as pd


def main():
    warmup_path = os.path.join(ROOT_DIR, "results", "results_experiment2_warmup.csv")
    if not os.path.exists(warmup_path):
        print(f"ERROR: {warmup_path} not found.")
        sys.exit(1)

    df_warmup = pd.read_csv(warmup_path)
    print("=" * 60)
    print("NOVASAT Phase 3 — Warmup Phase Validation")
    print("=" * 60)

    # Confirm rows present and non-empty
    if len(df_warmup) == 0:
        print("FAILED: results_experiment2_warmup.csv is empty")
        sys.exit(1)

    print(f"  Loaded {len(df_warmup):,} warmup trial records.")
    print("  WARMUP VALIDATION PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
