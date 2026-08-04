"""
synthesize_phase4_dataset.py

Phase 4 §1.4 - §1.6: Orchestrate dataset synthesis with noisy telemetry, behavioral fault injection,
strict feature/label separation, and trial-level disjoint anti-leakage splitting.

Generates:
  - data/anomaly_l3/train_normal.csv (~70% of normal trials)
  - data/anomaly_l3/val_mixed.csv (~15% of trial seeds, mixed normal + faults)
  - data/anomaly_l3/test_mixed.csv (~15% of trial seeds, mixed normal + faults)
  - data/anomaly_l3/metadata.anomaly_l3.v1.json
"""

import os
import sys
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
EXP_DIR = os.path.join(ROOT_DIR, "experiments")
for path in [ROOT_DIR, SRC_DIR, EXP_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

import csv
import gc
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd


def append_df_to_csv(df: pd.DataFrame, filepath: str):
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(df.itertuples(index=False, name=None))

from config import SIM_DURATION_S
from generate_normal_trials import (
    generate_single_node_telemetry,
    FULL_COLUMNS,
)
from identity import create_root_ca, generate_keypair, create_csr, sign_csr
from inject_behavioral_fault import inject_behavioral_fault

FAULT_TYPES = ["trajectory_drift", "power_anomaly", "timing_comm_anomaly"]

MODEL_FEATURES = [
    "sig_verify_fail_count", "revocation_msgs_sent", "revocation_msgs_received",
    "accusations_made", "accusations_received", "corroboration_count_for_target",
    "trust_score_current", "msgs_sent", "msgs_recv", "bytes_sent", "bytes_recv",
    "unique_peers_contacted", "interarrival_mean_ms", "interarrival_std_ms",
    "retransmit_count", "drop_count", "in_contact_with_ground",
    "num_visible_orbiters", "num_visible_rovers", "window_open_fraction",
    "time_since_last_contact_sec", "pos_x", "pos_y", "pos_z", "vel_x", "vel_y", "vel_z",
    "speed_delta", "accel_proxy", "heading_change_rate", "power_level", "power_delta",
    "cpu_load", "queue_depth"
]

LABEL_COLUMNS = [
    "scenario_type", "is_attack_active", "is_node_compromised", "is_false_revocation_event"
]


def generate_phase4_dataset(
    outdir: str = os.path.join(ROOT_DIR, "data", "anomaly_l3"),
    total_trials: int = 20,
    n_values: list = None,
    split_seed: int = 42,
    sim_duration_s: int = SIM_DURATION_S,
):
    if n_values is None:
        n_values = [1, 2, 4, 6, 8, 10]

    os.makedirs(outdir, exist_ok=True)
    rng = np.random.RandomState(split_seed)

    # 1. Deterministically assign trial IDs to splits (§1.6 Trial-Level Anti-Leakage)
    trial_ids = list(range(total_trials))
    rng.shuffle(trial_ids)

    n_train = int(round(total_trials * 0.70))
    n_val = int(round(total_trials * 0.15))

    train_trial_ids = set(trial_ids[:n_train])
    val_trial_ids = set(trial_ids[n_train:n_train + n_val])
    test_trial_ids = set(trial_ids[n_train + n_val:])

    train_csv = os.path.join(outdir, "train_normal.csv")
    val_csv = os.path.join(outdir, "val_mixed.csv")
    test_csv = os.path.join(outdir, "test_mixed.csv")

    # Always create/overwrite each output file so it starts at 0 bytes.
    # Using open("w").close() is the safest cross-platform way to guarantee a clean
    # empty file — os.remove can silently fail on Windows if a handle is still open
    # from a previous run, causing stale data to be prepended to new appends.
    for path in [train_csv, val_csv, test_csv]:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(FULL_COLUMNS)

    counts = {"train": 0, "val": 0, "test": 0}
    scenarios_summary = {"train_normal": {}, "val_mixed": {}, "test_mixed": {}}

    # Counters for round-robin fault type assignment in val/test splits.
    # This guarantees all 3 fault types appear in both val and test regardless
    # of how few trials are allocated (§1.3 fix: coverage before randomness).
    val_fault_counter = 0
    test_fault_counter = 0

    for trial_id in range(total_trials):
        seed = split_seed + trial_id
        n = n_values[trial_id % len(n_values)]

        orbiters = [f"orbiter_{i}" for i in range(n)]
        rovers = ["rover_1", "rover_2"]
        all_nodes = orbiters + rovers

        ca_priv, ca_cert = create_root_ca()

        # Fault injection strategy:
        #   - Train trials: 20% random rate (rows are filtered to normal-only anyway)
        #   - Val/Test trials: guaranteed fault per trial, cycling through all 3 types
        target_node = None
        fault_type = None
        fault_onset_time = 0.0

        if trial_id in train_trial_ids:
            # Keep original random 20% for train — these rows are filtered to normal-only
            is_anomalous = (rng.rand() < 0.20)
            if is_anomalous:
                target_node = rng.choice(orbiters)
                fault_type = rng.choice(FAULT_TYPES)
                fault_onset_time = float(rng.uniform(sim_duration_s * 0.2, sim_duration_s * 0.7))
        elif trial_id in val_trial_ids:
            # Guaranteed fault for val — ensures all 3 fault types are represented
            is_anomalous = True
            target_node = rng.choice(orbiters)
            fault_type = FAULT_TYPES[val_fault_counter % len(FAULT_TYPES)]
            val_fault_counter += 1
            fault_onset_time = float(rng.uniform(sim_duration_s * 0.2, sim_duration_s * 0.7))
        else:
            # Guaranteed fault for test — same guarantee
            is_anomalous = True
            target_node = rng.choice(orbiters)
            fault_type = FAULT_TYPES[test_fault_counter % len(FAULT_TYPES)]
            test_fault_counter += 1
            fault_onset_time = float(rng.uniform(sim_duration_s * 0.2, sim_duration_s * 0.7))

        if trial_id in train_trial_ids:
            target_csv = train_csv
            split_key = "train"
            scen_key = "train_normal"
        elif trial_id in val_trial_ids:
            target_csv = val_csv
            split_key = "val"
            scen_key = "val_mixed"
        else:
            target_csv = test_csv
            split_key = "test"
            scen_key = "test_mixed"

        for nid in all_nodes:
            npriv, _ = generate_keypair()
            csr = create_csr(nid, npriv)
            ncert = sign_csr(csr, ca_priv, ca_cert)

            df_node = generate_single_node_telemetry(
                seed=seed,
                n=n,
                nid=nid,
                sim_duration_s=sim_duration_s,
                window_size_sec=60,
                node_key=npriv,
                node_cert=ncert,
                ca_cert=ca_cert,
            )

            if is_anomalous and nid == target_node:
                df_node = inject_behavioral_fault(
                    df=df_node,
                    target_node=target_node,
                    fault_type=fault_type,
                    fault_onset_time=fault_onset_time,
                )

            df_node = df_node[FULL_COLUMNS]

            if trial_id in train_trial_ids:
                df_write = df_node[(df_node["scenario_type"] == "normal") & (df_node["is_attack_active"] == 0)]
            else:
                df_write = df_node

            append_df_to_csv(df_write, target_csv)

            counts[split_key] += len(df_write)
            for scen, sc_cnt in df_write["scenario_type"].value_counts().to_dict().items():
                scenarios_summary[scen_key][scen] = scenarios_summary[scen_key].get(scen, 0) + sc_cnt

            del df_node, df_write
            gc.collect()

        gc.collect()

    # Generate metadata
    metadata = {
        "dataset_name": "anomaly_l3_node_window",
        "dataset_version": "v1",
        "model_family": "anomaly_detection_l3",
        "intended_models": ["isolation_forest", "one_class_svm"],
        "task_type": "unsupervised_train_with_labeled_eval",
        "source_type": "simulator_phase4_telemetry",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "window_size_sec": 60,
        "full_columns": FULL_COLUMNS,
        "model_features": MODEL_FEATURES,
        "label_columns": LABEL_COLUMNS,
        "split_policy": {
            "strategy": "trial_level_disjoint_split",
            "train_ratio": 0.70,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
            "train_trial_count": len(train_trial_ids),
            "val_trial_count": len(val_trial_ids),
            "test_trial_count": len(test_trial_ids),
        },
        "split_summary": {
            "train_normal": {
                "rows": counts["train"],
                "scenarios": scenarios_summary["train_normal"]
            },
            "val_mixed": {
                "rows": counts["val"],
                "scenarios": scenarios_summary["val_mixed"]
            },
            "test_mixed": {
                "rows": counts["test"],
                "scenarios": scenarios_summary["test_mixed"]
            }
        }
    }

    meta_json = os.path.join(outdir, "metadata.anomaly_l3.v1.json")
    with open(meta_json, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("=== PHASE 4 DATASET SYNTHESIS COMPLETE ===")
    print(f"  Train normal rows: {counts['train']:,}")
    print(f"  Val mixed rows:   {counts['val']:,}")
    print(f"  Test mixed rows:  {counts['test']:,}")
    print(f"  Metadata saved:   {meta_json}")


if __name__ == "__main__":
    generate_phase4_dataset()
