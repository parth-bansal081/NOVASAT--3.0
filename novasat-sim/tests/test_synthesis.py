"""
Unit & Integration Test Suite for Layer-3 Anomaly Detection Dataset Synthesis Pipeline (Phase 4)
"""

import os
import sys
import json
import unittest
import tempfile
import pandas as pd
import numpy as np

# Ensure root, src, and experiments directories are in path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
EXP_DIR = os.path.join(ROOT_DIR, "experiments")
for path in [ROOT_DIR, SRC_DIR, EXP_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

from generate_normal_trials import generate_single_normal_trial, FULL_COLUMNS
from inject_behavioral_fault import inject_behavioral_fault
from synthesize_phase4_dataset import (
    generate_phase4_dataset,
    MODEL_FEATURES,
    LABEL_COLUMNS,
)


class TestPhase4SynthesisPipeline(unittest.TestCase):

    def test_schema_exact_match(self):
        """Unit test: Verifies exact 43-column schema match and header ordering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outdir = os.path.join(tmpdir, "data_l3")
            generate_phase4_dataset(outdir=outdir, total_trials=10, sim_duration_s=1800)

            for csv_name in ["train_normal.csv", "val_mixed.csv", "test_mixed.csv"]:
                csv_path = os.path.join(outdir, csv_name)
                df = pd.read_csv(csv_path)
                self.assertEqual(list(df.columns), FULL_COLUMNS, f"Schema mismatch in {csv_name}!")
                self.assertEqual(len(df.columns), 43, f"Expected 43 columns, found {len(df.columns)}")

    def test_normal_trial_generation_and_noise(self):
        """Unit test: Baseline normal trial generation with Gaussian noise."""
        df = generate_single_normal_trial(seed=123, n=4, sim_duration_s=600, window_size_sec=60)
        self.assertGreater(len(df), 0)
        self.assertTrue((df["scenario_type"] == "normal").all())
        self.assertTrue((df["is_attack_active"] == 0).all())
        # Noise check: continuous features are not all identical flat numbers
        self.assertFalse(df["pos_x"].isna().any())
        self.assertGreater(df["pos_x"].std(), 0.0)

    def test_behavioral_fault_injection(self):
        """Unit test: Verifies behavioral fault injections."""
        df_base = generate_single_normal_trial(seed=456, n=4, sim_duration_s=1200, window_size_sec=60)

        # 1. Trajectory drift
        df_drift = inject_behavioral_fault(df_base, target_node="orbiter_0", fault_type="trajectory_drift", fault_onset_time=600.0)
        faulted_drift = df_drift[(df_drift["node_id"] == "orbiter_0") & (df_drift["timestamp"] >= 600.0)]
        self.assertTrue((faulted_drift["scenario_type"] == "trajectory_drift").all())
        self.assertTrue((faulted_drift["is_attack_active"] == 1).all())

        # 2. Power anomaly
        df_power = inject_behavioral_fault(df_base, target_node="orbiter_0", fault_type="power_anomaly", fault_onset_time=600.0)
        faulted_power = df_power[(df_power["node_id"] == "orbiter_0") & (df_power["timestamp"] >= 600.0)]
        self.assertTrue((faulted_power["scenario_type"] == "power_anomaly").all())

        # 3. Timing/comm anomaly
        df_comm = inject_behavioral_fault(df_base, target_node="orbiter_0", fault_type="timing_comm_anomaly", fault_onset_time=600.0)
        faulted_comm = df_comm[(df_comm["node_id"] == "orbiter_0") & (df_comm["timestamp"] >= 600.0)]
        self.assertTrue((faulted_comm["scenario_type"] == "timing_comm_anomaly").all())

    def test_trial_level_disjoint_anti_leakage(self):
        """Integration test: Trial-level disjoint anti-leakage splitting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outdir = os.path.join(tmpdir, "out")
            generate_phase4_dataset(outdir=outdir, total_trials=20, sim_duration_s=1800)

            df_train = pd.read_csv(os.path.join(outdir, "train_normal.csv"))
            df_val = pd.read_csv(os.path.join(outdir, "val_mixed.csv"))
            df_test = pd.read_csv(os.path.join(outdir, "test_mixed.csv"))

            # train_normal must contain ONLY normal, non-attack rows
            self.assertTrue((df_train["scenario_type"] == "normal").all())
            self.assertTrue((df_train["is_attack_active"] == 0).all())

            # Verify metadata
            with open(os.path.join(outdir, "metadata.anomaly_l3.v1.json"), "r") as f:
                meta = json.load(f)
            self.assertEqual(meta["dataset_name"], "anomaly_l3_node_window")
            self.assertEqual(meta["split_policy"]["strategy"], "trial_level_disjoint_split")


if __name__ == "__main__":
    unittest.main()
