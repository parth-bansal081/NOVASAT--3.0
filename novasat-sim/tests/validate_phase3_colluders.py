"""
NOVASAT Phase 3 — Multi-Colluder Validation
Validates results_experiment2_colluders.csv
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
from validate_phase3 import check5_multi_colluder_validation


def main():
    colluders_path = os.path.join(ROOT_DIR, "results", "results_experiment2_colluders.csv")
    if not os.path.exists(colluders_path):
        print(f"ERROR: {colluders_path} not found.")
        sys.exit(1)

    df_colluders = pd.read_csv(colluders_path)
    passed = check5_multi_colluder_validation(df_colluders)
    if passed:
        print("\nMULTI-COLLUDER VALIDATION PASSED SUCCESSFULLY!")
    else:
        print("\nMULTI-COLLUDER VALIDATION FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
