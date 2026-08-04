"""
run_phase4_diagnostics.py

Phase 4 Realism Fix — Diagnostic Runner

Performs all four original checks plus the per-fault-type pos_x breakdown:

  1. Feature separation table:   |mean_anomalous - mean_normal| / std_normal (σ-separation)
  2. Class balance:              Row count / proportion for normal vs anomalous
  3. Feature exclusion print:   Which columns are dropped from model input (DROP_COLS)
  4. Groupby-separation scan:   Per-feature describe() by is_node_compromised
  5. pos_x by fault_type:       Confirms trajectory_drift rows show real pos_x separation;
                                 power_anomaly / timing_comm_anomaly rows correctly show little/none.

Usage:
    python experiments/run_phase4_diagnostics.py

Reads from data/anomaly_l3/val_mixed.csv and data/anomaly_l3/train_normal.csv.
"""

import os
import sys

# Force UTF-8 stdout on Windows so Greek letters (mu, sigma) don't crash cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import numpy as np
import pandas as pd

# ─── Config ───────────────────────────────────────────────────────────────────

VAL_CSV   = os.path.join(ROOT_DIR, "data", "anomaly_l3", "val_mixed.csv")
TEST_CSV  = os.path.join(ROOT_DIR, "data", "anomaly_l3", "test_mixed.csv")
TRAIN_CSV = os.path.join(ROOT_DIR, "data", "anomaly_l3", "train_normal.csv")

DROP_COLS = [
    "timestamp", "window_id", "node_id", "node_type", "N", "scenario_type",
    "is_attack_active", "is_node_compromised", "is_false_revocation_event"
]

# Key features to spotlight in the separation table (covers all three fault types)
SPOTLIGHT_FEATURES = [
    "cpu_load", "queue_depth", "interarrival_mean_ms", "power_level",
    "pos_x", "pos_y", "pos_z", "vel_x", "vel_y", "vel_z",
    "power_delta", "msgs_sent", "interarrival_std_ms",
]

SEP = "=" * 75


def section(title: str):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


# ─── 1. Feature Separation Table ──────────────────────────────────────────────

def check_feature_separation(val_df: pd.DataFrame, train_df: pd.DataFrame):
    section("CHECK 1 -- Feature Separation Table  (|mu_anom - mu_norm| / sigma_norm)")

    feature_cols = [c for c in val_df.columns if c not in DROP_COLS
                    and pd.api.types.is_numeric_dtype(val_df[c])]

    normal_rows = val_df[val_df["is_node_compromised"] == 0]
    anom_rows   = val_df[val_df["is_node_compromised"] == 1]

    # Use train_normal.csv for a clean normal baseline (no contamination)
    train_feat = [c for c in feature_cols if c in train_df.columns]
    normal_mean = train_df[train_feat].mean()
    normal_std  = train_df[train_feat].std().replace(0, np.nan)

    anom_mean = anom_rows[train_feat].mean()
    separation = ((anom_mean - normal_mean).abs() / normal_std).sort_values(ascending=False)

    print(f"\n{'Feature':<35} {'Normal mu':>10} {'Anom mu':>10} {'Normal sd':>10} {'Sep(sigma)':>10}")
    print("-" * 75)
    for feat, sep_val in separation.items():
        n_mu  = normal_mean.get(feat, float("nan"))
        a_mu  = anom_mean.get(feat, float("nan"))
        n_std = normal_std.get(feat, float("nan"))
        flag  = " ⚠ LARGE" if sep_val > 15 else ("  ✓ REALISTIC" if sep_val <= 10 else "")
        print(f"  {feat:<33} {n_mu:>10.3f} {a_mu:>10.3f} {n_std:>10.3f} {sep_val:>10.2f}{flag}")

    print(f"\n  Max separation: {separation.max():.2f} sigma  (target: well below 20 sigma)")
    print(f"  Spotlight features:")
    for feat in SPOTLIGHT_FEATURES:
        if feat in separation.index:
            val = separation[feat]
            verdict = "OK" if val <= 10 else ("BORDERLINE" if val <= 15 else "TOO HIGH")
            print(f"    {feat:<35} {val:>8.2f} sigma   [{verdict}]")


# ─── 2. Class Balance ─────────────────────────────────────────────────────────

def check_class_balance(val_df: pd.DataFrame, test_df: pd.DataFrame):
    section("CHECK 2 — Class Balance (normal vs anomalous rows)")

    for name, df in [("val_mixed", val_df), ("test_mixed", test_df)]:
        total = len(df)
        n_normal = (df["is_node_compromised"] == 0).sum()
        n_anom   = (df["is_node_compromised"] == 1).sum()
        print(f"\n  {name}:  total={total:,}  "
              f"normal={n_normal:,} ({n_normal/total*100:.1f}%)  "
              f"anomalous={n_anom:,} ({n_anom/total*100:.1f}%)")

        print(f"  Scenario breakdown:")
        for scen, cnt in df["scenario_type"].value_counts().items():
            print(f"    {scen:<35} {cnt:>8,} rows  ({cnt/total*100:.1f}%)")


# ─── 3. Feature Exclusion Print ───────────────────────────────────────────────

def check_feature_exclusion(val_df: pd.DataFrame):
    section("CHECK 3 — Feature Exclusion (DROP_COLS vs model input)")

    all_cols     = list(val_df.columns)
    feature_cols = [c for c in all_cols if c not in DROP_COLS
                    and pd.api.types.is_numeric_dtype(val_df[c])]
    excluded     = [c for c in all_cols if c not in feature_cols]

    print(f"\n  Total columns in CSV:  {len(all_cols)}")
    print(f"  Model feature cols:    {len(feature_cols)}")
    print(f"  Dropped / excluded:    {len(excluded)}")
    print(f"\n  Dropped columns: {excluded}")
    print(f"\n  Model input features ({len(feature_cols)}):")
    for i, col in enumerate(feature_cols):
        print(f"    [{i:02d}] {col}")


# ─── 4. Groupby-Separation Scan ───────────────────────────────────────────────

def check_groupby_separation(val_df: pd.DataFrame):
    section("CHECK 4 — Groupby-Separation Scan (anomalous vs normal per feature)")

    feature_cols = [c for c in val_df.columns if c not in DROP_COLS
                    and pd.api.types.is_numeric_dtype(val_df[c])]

    print(f"\n  Spotlight feature statistics grouped by is_node_compromised:\n")
    for feat in SPOTLIGHT_FEATURES:
        if feat not in feature_cols:
            continue
        stats = val_df.groupby("is_node_compromised")[feat].describe()
        print(f"  ── {feat} ──")
        print(stats.to_string())

        # Extra check: power_level anomalous std should NOT be 0
        if feat == "power_level" and 1 in stats.index:
            anom_std = stats.loc[1, "std"]
            verdict = "NONZERO (realistic)" if anom_std > 0.01 else "ZERO or near-zero -- still broken"
            print(f"     power_level anomalous std = {anom_std:.6f}  [{verdict}]")
        print()


# ─── 5. pos_x Breakdown by Fault Type ────────────────────────────────────────

def check_posx_by_fault_type(val_df: pd.DataFrame):
    section("CHECK 5 — pos_x Separation by Fault Type (§3 diagnostic)")

    print("""
  Expected:
    trajectory_drift     → real pos_x separation (drift was injected into pos_x)
    power_anomaly        → little/no pos_x separation (drift was NOT injected)
    timing_comm_anomaly  → little/no pos_x separation (drift was NOT injected)
  If trajectory_drift itself shows no separation, the drift injection has its own bug.
""")

    fault_types = val_df[val_df["scenario_type"] != "normal"]["scenario_type"].dropna().unique()

    for fault_type in fault_types:
        subset = val_df[val_df["scenario_type"] == fault_type]
        # Include normal rows from the same split for context
        normal_subset = val_df[val_df["scenario_type"] == "normal"]

        print(f"  ── Fault type: {fault_type}  ({len(subset):,} rows) ──")
        combined = pd.concat([
            normal_subset["pos_x"].describe().rename("normal"),
            subset["pos_x"].describe().rename(fault_type),
        ], axis=1)
        print(combined.to_string())

        # Compute separation for this fault type specifically
        n_mu  = normal_subset["pos_x"].mean()
        n_std = normal_subset["pos_x"].std()
        a_mu  = subset["pos_x"].mean()
        if n_std > 0:
            sep = abs(a_mu - n_mu) / n_std
            expected_sep = "HIGH" if fault_type == "trajectory_drift" else "LOW"
            verdict = "OK" if (fault_type == "trajectory_drift") == (sep > 1.0) else "UNEXPECTED"
            print(f"  pos_x sigma-separation for {fault_type}: {sep:.2f} sigma  [expected {expected_sep}]  {verdict}")
        print()


# ─── 6. Power Level Variance Check (quick dedicated check) ───────────────────

def check_power_level_variance(val_df: pd.DataFrame):
    section("CHECK 6 — power_level Variance in Anomalous Rows (critical fix check)")

    anom = val_df[val_df["is_node_compromised"] == 1]
    power_anom = anom[anom["scenario_type"] == "power_anomaly"]["power_level"]

    if len(power_anom) == 0:
        print("\n  No power_anomaly rows found in val_mixed.csv")
        return

    print(f"\n  power_anomaly rows: {len(power_anom):,}")
    print(f"  power_level describe:")
    print(power_anom.describe().to_string())

    std_val = power_anom.std()
    verdict = "FIXED -- realistic nonzero variance" if std_val > 0.1 else "STILL BROKEN -- std is near zero"
    print(f"\n  std = {std_val:.6f}  [{verdict}]")

    # Confirm it's not a single repeated constant
    n_unique = power_anom.nunique()
    print(f"  unique values count = {n_unique}  ({'diverse' if n_unique > 10 else 'suspiciously few'})")


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_all_diagnostics():
    print(SEP)
    print("  NOVASAT Phase 4 — Fault Injection Realism Diagnostics")
    print(SEP)

    print(f"\nLoading val_mixed.csv ...")
    val_df = pd.read_csv(VAL_CSV, low_memory=False)
    print(f"  Loaded {len(val_df):,} rows, {len(val_df.columns)} columns")

    print(f"\nLoading test_mixed.csv ...")
    test_df = pd.read_csv(TEST_CSV, low_memory=False)
    print(f"  Loaded {len(test_df):,} rows, {len(test_df.columns)} columns")

    print(f"\nLoading train_normal.csv (for clean baseline stats, first 500k rows) ...")
    train_df = pd.read_csv(TRAIN_CSV, nrows=500_000, low_memory=False)
    print(f"  Loaded {len(train_df):,} rows")

    check_feature_separation(val_df, train_df)
    check_class_balance(val_df, test_df)
    check_feature_exclusion(val_df)
    check_groupby_separation(val_df)
    check_posx_by_fault_type(val_df)
    check_power_level_variance(val_df)

    print(f"\n{SEP}")
    print("  ALL DIAGNOSTICS COMPLETE")
    print(SEP)


if __name__ == "__main__":
    run_all_diagnostics()
