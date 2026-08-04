"""
verify_5_samples.py

Part D Validation: 5-sample cross-check of Phase 4 synthesized dataset against real Phase 1 CSV data.
"""

import os
import sys
import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def compute_ground_truth_for_sample(n: int, node_id: str, t: float) -> dict:
    csv_path = os.path.join(ROOT_DIR, "data", f"contact_windows_N{n}.csv")
    df = pd.read_csv(csv_path)

    df_earth = df[df["link_type"] == "orbiter_earth"]
    df_ro = df[df["link_type"] == "rover_orbiter"]
    df_oo = df[df["link_type"] == "orbiter_orbiter"]

    is_orbiter = node_id.startswith("orbiter")

    # 1. in_contact_with_ground
    if is_orbiter:
        e_windows = df_earth[(df_earth["node_a"] == node_id) | (df_earth["node_b"] == node_id)]
        in_ground = any((row["window_start_s"] <= t <= row["window_end_s"]) for _, row in e_windows.iterrows())
    else:
        # Rover in contact with ground via any orbiter currently linked to Earth
        ro_windows = df_ro[(df_ro["node_a"] == node_id) | (df_ro["node_b"] == node_id)]
        in_ground = False
        for _, ro_row in ro_windows.iterrows():
            if ro_row["window_start_s"] <= t <= ro_row["window_end_s"]:
                orb_id = ro_row["node_b"] if ro_row["node_a"] == node_id else ro_row["node_a"]
                orb_e = df_earth[(df_earth["node_a"] == orb_id) | (df_earth["node_b"] == orb_id)]
                if any((e_row["window_start_s"] <= t <= e_row["window_end_s"]) for _, e_row in orb_e.iterrows()):
                    in_ground = True
                    break

    # 2. num_visible_orbiters & num_visible_rovers
    num_vis_orbiters = 0
    num_vis_rovers = 0

    if is_orbiter:
        oo_windows = df_oo[(df_oo["node_a"] == node_id) | (df_oo["node_b"] == node_id)]
        for _, row in oo_windows.iterrows():
            if row["window_start_s"] <= t <= row["window_end_s"]:
                num_vis_orbiters += 1

        ro_windows = df_ro[(df_ro["node_a"] == node_id) | (df_ro["node_b"] == node_id)]
        for _, row in ro_windows.iterrows():
            if row["window_start_s"] <= t <= row["window_end_s"]:
                num_vis_rovers += 1
    else:
        ro_windows = df_ro[(df_ro["node_a"] == node_id) | (df_ro["node_b"] == node_id)]
        for _, row in ro_windows.iterrows():
            if row["window_start_s"] <= t <= row["window_end_s"]:
                num_vis_orbiters += 1

    # 3. time_since_last_contact_sec
    all_node_windows = df[(df["node_a"] == node_id) | (df["node_b"] == node_id)]
    in_any_window = any((row["window_start_s"] <= t <= row["window_end_s"]) for _, row in all_node_windows.iterrows())

    if in_any_window:
        time_since_last = 0.0
    else:
        past_ends = [row["window_end_s"] for _, row in all_node_windows.iterrows() if row["window_end_s"] <= t]
        if past_ends:
            most_recent_end = max(past_ends)
            time_since_last = float(t - most_recent_end)
        else:
            time_since_last = float(t)

    return {
        "in_contact_with_ground": int(in_ground),
        "num_visible_orbiters": int(num_vis_orbiters),
        "num_visible_rovers": int(num_vis_rovers),
        "time_since_last_contact_sec": float(time_since_last),
    }


def perform_5_sample_cross_check():
    dataset_csv = os.path.join(ROOT_DIR, "data", "anomaly_l3", "train_normal.csv")
    if not os.path.exists(dataset_csv):
        raise FileNotFoundError(f"Missing dataset CSV: {dataset_csv}")

    df_synth = pd.read_csv(dataset_csv)

    rng = np.random.RandomState(42)
    sample_indices = rng.choice(len(df_synth), size=5, replace=False)

    print("=" * 100)
    print("PART D — 5-SAMPLE MANUAL CROSS-CHECK VALIDATION")
    print("Cross-checking Phase 4 synthesized telemetry dataset against raw Phase 1 CSV files")
    print("=" * 100 + "\n")

    all_matched = True

    for i, idx in enumerate(sample_indices, 1):
        row = df_synth.iloc[idx]
        n = int(row["N"])
        node_id = str(row["node_id"])
        t = float(row["timestamp"])

        ground_truth = compute_ground_truth_for_sample(n, node_id, t)

        synth_ground = int(row["in_contact_with_ground"])
        synth_vis_orb = int(row["num_visible_orbiters"])
        synth_vis_rov = int(row["num_visible_rovers"])
        synth_time_since = float(row["time_since_last_contact_sec"])

        gt_ground = ground_truth["in_contact_with_ground"]
        gt_vis_orb = ground_truth["num_visible_orbiters"]
        gt_vis_rov = ground_truth["num_visible_rovers"]
        gt_time_since = ground_truth["time_since_last_contact_sec"]

        match_ground = (synth_ground == gt_ground)
        match_vis_orb = (synth_vis_orb == gt_vis_orb)
        match_vis_rov = (synth_vis_rov == gt_vis_rov)
        match_time_since = abs(synth_time_since - gt_time_since) < 1.0

        sample_passed = match_ground and match_vis_orb and match_vis_rov and match_time_since
        if not sample_passed:
            all_matched = False

        status_str = "EXACT MATCH (PASSED)" if sample_passed else "MISMATCH (FAILED)"

        print(f"Sample #{i}: N={n}, Node={node_id}, Timestamp={t:.0f}s ({t/86400:.2f} days)")
        print(f"  Status: {status_str}")
        print(f"  Field                       | Synthesized Dataset | Raw Phase 1 CSV | Match?")
        print(f"  ----------------------------+---------------------+-----------------+-------")
        print(f"  in_contact_with_ground      | {synth_ground:<19} | {gt_ground:<15} | {'YES' if match_ground else 'NO'}")
        print(f"  num_visible_orbiters        | {synth_vis_orb:<19} | {gt_vis_orb:<15} | {'YES' if match_vis_orb else 'NO'}")
        print(f"  num_visible_rovers          | {synth_vis_rov:<19} | {gt_vis_rov:<15} | {'YES' if match_vis_rov else 'NO'}")
        print(f"  time_since_last_contact_sec | {synth_time_since:<19.1f} | {gt_time_since:<15.1f} | {'YES' if match_time_since else 'NO'}")
        print("-" * 100 + "\n")

    if all_matched:
        print("PART D VALIDATION RESULT: ALL 5 SAMPLES MATCHED RAW PHASE 1 CSV GROUND TRUTH EXACTLY!")
    else:
        print("PART D VALIDATION RESULT: MISMATCH DETECTED!")
        sys.exit(1)


if __name__ == "__main__":
    perform_5_sample_cross_check()
