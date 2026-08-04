#!/usr/bin/env python3
"""
synthesize_pipeline.py

Build ONE master normal-only dataset from simulator raw logs:
- Input: raw CSV log (event/timestep level)
- Output:
    data/anomaly_l3/full_normal.csv
    data/anomaly_l3/metadata.anomaly_l3.v1.json

You can split into train/val/test later with a separate script.

Usage:
python synthesize_pipeline.py \
  --input raw_sim_logs.csv \
  --outdir data/anomaly_l3 \
  --window-size-sec 60 \
  --dataset-name anomaly_l3_node_window \
  --dataset-version v1

IMPORTANT:
- This script expects a flat CSV with columns mapped below.
- Edit RAW_COLUMN_MAP to match your simulator log field names.
"""

import argparse
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

import numpy as np
import pandas as pd


# ============================================================
# 1) EDIT THIS MAP TO MATCH YOUR RAW LOG COLUMN NAMES
# ============================================================
RAW_COLUMN_MAP = {
    # Required core
    "time": "time",                     # numeric seconds recommended
    "node_id": "node_id",
    "node_type": "node_type",           # orbiter/rover/other
    "N": "N",
    "scenario_type": "scenario_type",   # must contain "normal" for clean runs
    "is_attack_active": "is_attack_active",  # 0/1

    # Messaging / network raw fields
    "event_type": "event_type",         # e.g. send/recv/sig_fail/revoke_sent...
    "peer_id": "peer_id",
    "bytes": "bytes",                   # bytes associated with message event
    "msg_timestamp": "msg_timestamp",   # optional; fallback to time

    # Optional state fields (if missing, script fills with 0)
    "trust_score_current": "trust_score_current",
    "pos_x": "pos_x",
    "pos_y": "pos_y",
    "pos_z": "pos_z",
    "vel_x": "vel_x",
    "vel_y": "vel_y",
    "vel_z": "vel_z",
    "power_level": "power_level",
    "cpu_load": "cpu_load",
    "queue_depth": "queue_depth",

    # Optional contact fields
    "in_contact_with_ground": "in_contact_with_ground",
    "num_visible_orbiters": "num_visible_orbiters",
    "num_visible_rovers": "num_visible_rovers",
    "window_open_fraction": "window_open_fraction",
    "time_since_last_contact_sec": "time_since_last_contact_sec",

    # Optional reliability fields
    "retransmit_count": "retransmit_count",
    "drop_count": "drop_count",
}


# ============================================================
# 2) OUTPUT SCHEMA (EXACT ORDER)
# ============================================================
FULL_COLUMNS = [
    "timestamp","window_id","node_id","node_type","N","scenario_type",
    "is_attack_active","is_node_compromised","is_false_revocation_event",
    "sig_verify_fail_count","revocation_msgs_sent","revocation_msgs_received",
    "accusations_made","accusations_received","corroboration_count_for_target",
    "trust_score_current","msgs_sent","msgs_recv","bytes_sent","bytes_recv",
    "unique_peers_contacted","interarrival_mean_ms","interarrival_std_ms",
    "retransmit_count","drop_count","in_contact_with_ground",
    "num_visible_orbiters","num_visible_rovers","window_open_fraction",
    "time_since_last_contact_sec","pos_x","pos_y","pos_z","vel_x","vel_y","vel_z",
    "speed_delta","accel_proxy","heading_change_rate","power_level","power_delta",
    "cpu_load","queue_depth"
]

LABEL_COLUMNS = [
    "scenario_type", "is_attack_active", "is_node_compromised", "is_false_revocation_event"
]


@dataclass
class Config:
    input_path: str
    outdir: str
    window_size_sec: int
    dataset_name: str
    dataset_version: str


def safe_col(df: pd.DataFrame, col: str, default=0):
    if col in df.columns:
        return df[col]
    return pd.Series(default, index=df.index)


def ensure_numeric(df: pd.DataFrame, cols: List[str]):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def compute_window_features(g: pd.DataFrame, window_size_sec: int) -> Dict:
    # last-row state snapshot
    g_sorted = g.sort_values("time_std")
    first_row = g_sorted.iloc[0]
    last_row = g_sorted.iloc[-1]

    # Event masks (edit event names if your simulator differs)
    ev = g_sorted["event_type_std"].fillna("")

    sent_mask = ev.eq("send")
    recv_mask = ev.eq("recv")
    sig_fail_mask = ev.eq("sig_fail")
    revoke_sent_mask = ev.eq("revoke_sent")
    revoke_recv_mask = ev.eq("revoke_recv")
    accuse_made_mask = ev.eq("accuse_made")
    accuse_recv_mask = ev.eq("accuse_recv")
    corroborate_mask = ev.eq("corroborate_target")

    bytes_series = g_sorted["bytes_std"].fillna(0)

    msgs_sent = int(sent_mask.sum())
    msgs_recv = int(recv_mask.sum())
    bytes_sent = float(bytes_series[sent_mask].sum())
    bytes_recv = float(bytes_series[recv_mask].sum())

    unique_peers = g_sorted.loc[g_sorted["peer_id_std"].notna(), "peer_id_std"].nunique()

    # interarrival on recv timestamps
    recv_times = g_sorted.loc[recv_mask, "msg_ts_std"].dropna().values
    if len(recv_times) >= 2:
        diffs = np.diff(np.sort(recv_times)) * 1000.0
        interarrival_mean_ms = float(np.mean(diffs))
        interarrival_std_ms = float(np.std(diffs))
    else:
        interarrival_mean_ms = 0.0
        interarrival_std_ms = 0.0

    # velocity derived
    v0 = np.array([first_row.get("vel_x_std", 0), first_row.get("vel_y_std", 0), first_row.get("vel_z_std", 0)], dtype=float)
    v1 = np.array([last_row.get("vel_x_std", 0), last_row.get("vel_y_std", 0), last_row.get("vel_z_std", 0)], dtype=float)
    speed0 = float(np.linalg.norm(v0))
    speed1 = float(np.linalg.norm(v1))
    speed_delta = abs(speed1 - speed0)
    accel_proxy = (speed1 - speed0) / float(window_size_sec)

    # heading change rate (if you have heading field, replace this)
    heading_change_rate = 0.0

    # power delta
    power0 = float(first_row.get("power_level_std", 0) or 0)
    power1 = float(last_row.get("power_level_std", 0) or 0)
    power_delta = power1 - power0

    return {
        "timestamp": float(last_row["time_std"]),
        "window_id": int(last_row["window_id"]),
        "node_id": last_row["node_id_std"],
        "node_type": str(last_row.get("node_type_std", "unknown")),
        "N": int(last_row.get("N_std", 0) or 0),
        "scenario_type": str(last_row.get("scenario_type_std", "unknown")),
        "is_attack_active": int(last_row.get("is_attack_active_std", 0) or 0),
        "is_node_compromised": 0,  # normal-only dataset
        "is_false_revocation_event": 0,  # normal-only dataset

        "sig_verify_fail_count": int(sig_fail_mask.sum()),
        "revocation_msgs_sent": int(revoke_sent_mask.sum()),
        "revocation_msgs_received": int(revoke_recv_mask.sum()),
        "accusations_made": int(accuse_made_mask.sum()),
        "accusations_received": int(accuse_recv_mask.sum()),
        "corroboration_count_for_target": int(corroborate_mask.sum()),
        "trust_score_current": float(last_row.get("trust_score_current_std", 0) or 0),

        "msgs_sent": msgs_sent,
        "msgs_recv": msgs_recv,
        "bytes_sent": bytes_sent,
        "bytes_recv": bytes_recv,
        "unique_peers_contacted": int(unique_peers),

        "interarrival_mean_ms": interarrival_mean_ms,
        "interarrival_std_ms": interarrival_std_ms,

        "retransmit_count": float(g_sorted.get("retransmit_count_std", pd.Series([0])).fillna(0).sum()),
        "drop_count": float(g_sorted.get("drop_count_std", pd.Series([0])).fillna(0).sum()),

        "in_contact_with_ground": int(last_row.get("in_contact_with_ground_std", 0) or 0),
        "num_visible_orbiters": int(last_row.get("num_visible_orbiters_std", 0) or 0),
        "num_visible_rovers": int(last_row.get("num_visible_rovers_std", 0) or 0),
        "window_open_fraction": float(last_row.get("window_open_fraction_std", 0) or 0),
        "time_since_last_contact_sec": float(last_row.get("time_since_last_contact_sec_std", 0) or 0),

        "pos_x": float(last_row.get("pos_x_std", 0) or 0),
        "pos_y": float(last_row.get("pos_y_std", 0) or 0),
        "pos_z": float(last_row.get("pos_z_std", 0) or 0),
        "vel_x": float(last_row.get("vel_x_std", 0) or 0),
        "vel_y": float(last_row.get("vel_y_std", 0) or 0),
        "vel_z": float(last_row.get("vel_z_std", 0) or 0),

        "speed_delta": float(speed_delta),
        "accel_proxy": float(accel_proxy),
        "heading_change_rate": float(heading_change_rate),

        "power_level": float(last_row.get("power_level_std", 0) or 0),
        "power_delta": float(power_delta),
        "cpu_load": float(last_row.get("cpu_load_std", 0) or 0),
        "queue_depth": float(last_row.get("queue_depth_std", 0) or 0),
    }


def build_metadata(cfg: Config, df_out: pd.DataFrame, defaulted_fields: List[str]) -> Dict:
    numeric_units = {
        "timestamp": "sim_seconds",
        "interarrival_mean_ms": "ms",
        "interarrival_std_ms": "ms",
        "bytes_sent": "bytes",
        "bytes_recv": "bytes",
        "window_open_fraction": "ratio_0_1",
        "time_since_last_contact_sec": "seconds",
        "pos_x": "arb_distance",
        "pos_y": "arb_distance",
        "pos_z": "arb_distance",
        "vel_x": "arb_distance_per_sec",
        "vel_y": "arb_distance_per_sec",
        "vel_z": "arb_distance_per_sec",
        "speed_delta": "arb_speed",
        "accel_proxy": "arb_speed_per_sec",
        "heading_change_rate": "rad_per_sec",
        "power_level": "arb_power",
        "power_delta": "arb_power",
        "cpu_load": "ratio_0_1_or_percent",
        "queue_depth": "count",
    }

    model_features = [c for c in FULL_COLUMNS if c not in [
        "timestamp", "window_id", "node_id", "node_type", "N",
        "scenario_type", "is_attack_active", "is_node_compromised", "is_false_revocation_event"
    ]]

    return {
        "dataset_name": cfg.dataset_name,
        "dataset_version": cfg.dataset_version,
        "model_family": "anomaly_detection_l3",
        "intended_models": ["isolation_forest", "one_class_svm"],
        "task_type": "unsupervised_train_with_labeled_eval",
        "source_type": "simulator_synthesized",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "generator_script": os.path.abspath(__file__),
        "git_commit": os.getenv("GIT_COMMIT", "unknown"),
        "window_size_sec": cfg.window_size_sec,
        "full_columns": FULL_COLUMNS,
        "model_features": model_features,
        "label_columns": LABEL_COLUMNS,
        "feature_units": numeric_units,
        "split_policy": {
            "note": "This script generates one master normal-only dataset (full_normal.csv). Splits happen later."
        },
        "split_summary": {
            "rows": int(len(df_out)),
            "unique_nodes": int(df_out["node_id"].nunique()) if "node_id" in df_out.columns else 0,
            "scenario_distribution": df_out["scenario_type"].value_counts(dropna=False).to_dict() if "scenario_type" in df_out.columns else {}
        },
        "sim_config": {
            "N_values_observed": sorted(df_out["N"].dropna().unique().tolist()) if "N" in df_out.columns else [],
        },
        "missing_value_policy": {
            "numeric_default": 0,
            "categorical_default": "unknown",
            "defaulted_fields": sorted(list(set(defaulted_fields))),
        },
        "normalization": {
            "type": "none",
            "notes": "Scaler/imputer applied at model-training stage"
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to raw simulator CSV")
    parser.add_argument("--outdir", default="data/anomaly_l3")
    parser.add_argument("--window-size-sec", type=int, default=60)
    parser.add_argument("--dataset-name", default="anomaly_l3_node_window")
    parser.add_argument("--dataset-version", default="v1")
    args = parser.parse_args()

    cfg = Config(
        input_path=args.input,
        outdir=args.outdir,
        window_size_sec=args.window_size_sec,
        dataset_name=args.dataset_name,
        dataset_version=args.dataset_version,
    )

    os.makedirs(cfg.outdir, exist_ok=True)

    df = pd.read_csv(cfg.input_path)

    # Standardize columns into *_std namespace
    defaulted_fields = []
    for std_key, raw_key in RAW_COLUMN_MAP.items():
        std_col = f"{std_key}_std"
        if raw_key in df.columns:
            df[std_col] = df[raw_key]
        else:
            default_val = "unknown" if std_key in ["node_type", "scenario_type", "event_type", "peer_id"] else 0
            df[std_col] = default_val
            defaulted_fields.append(std_key)

    # Numeric coercions
    numeric_std_cols = [
        "time_std","N_std","is_attack_active_std","bytes_std","msg_timestamp_std",
        "trust_score_current_std","pos_x_std","pos_y_std","pos_z_std",
        "vel_x_std","vel_y_std","vel_z_std","power_level_std","cpu_load_std",
        "queue_depth_std","in_contact_with_ground_std","num_visible_orbiters_std",
        "num_visible_rovers_std","window_open_fraction_std","time_since_last_contact_sec_std",
        "retransmit_count_std","drop_count_std"
    ]
    df = ensure_numeric(df, [c for c in numeric_std_cols if c in df.columns])

    # Fallback for msg timestamp
    if "msg_ts_std" not in df.columns:
        # create canonical msg_ts_std
        if "msg_timestamp_std" in df.columns:
            df["msg_ts_std"] = pd.to_numeric(df["msg_timestamp_std"], errors="coerce")
        else:
            df["msg_ts_std"] = np.nan
    df["msg_ts_std"] = df["msg_ts_std"].fillna(df["time_std"])

    # Keep normal-only
    df["scenario_type_std"] = df["scenario_type_std"].astype(str)
    df["is_attack_active_std"] = pd.to_numeric(df["is_attack_active_std"], errors="coerce").fillna(0).astype(int)
    df = df[(df["scenario_type_std"] == "normal") & (df["is_attack_active_std"] == 0)].copy()

    # Validate minimum required
    for req in ["time_std", "node_id_std"]:
        if req not in df.columns:
            raise ValueError(f"Missing required standardized column: {req}")

    # Build window ids
    df["time_std"] = pd.to_numeric(df["time_std"], errors="coerce")
    df = df[df["time_std"].notna()].copy()
    df["window_id"] = (df["time_std"] // cfg.window_size_sec).astype(int)

    # Normalize key strings
    df["event_type_std"] = df["event_type_std"].astype(str)
    df["node_id_std"] = df["node_id_std"].astype(str)
    df["peer_id_std"] = df["peer_id_std"].astype(str).replace({"0": np.nan, "nan": np.nan, "None": np.nan})

    # Group + aggregate
    rows = []
    for (_, _), g in df.groupby(["node_id_std", "window_id"], sort=True):
        row = compute_window_features(g, cfg.window_size_sec)
        rows.append(row)

    df_out = pd.DataFrame(rows)

    # Ensure full schema + fill defaults
    for col in FULL_COLUMNS:
        if col not in df_out.columns:
            df_out[col] = 0
            defaulted_fields.append(col)

    df_out = df_out[FULL_COLUMNS].copy()

    # Final cleanup numeric NaN/Inf
    numeric_cols = df_out.select_dtypes(include=[np.number]).columns.tolist()
    df_out[numeric_cols] = df_out[numeric_cols].replace([np.inf, -np.inf], np.nan).fillna(0)

    # Stable sort
    df_out = df_out.sort_values(["window_id", "node_id"], kind="mergesort").reset_index(drop=True)

    # Write CSV
    out_csv = os.path.join(cfg.outdir, "full_normal.csv")
    df_out.to_csv(out_csv, index=False)

    # Write metadata
    metadata = build_metadata(cfg, df_out, defaulted_fields)
    out_meta = os.path.join(cfg.outdir, f"metadata.{cfg.dataset_name}.{cfg.dataset_version}.json")
    with open(out_meta, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # Console validation summary
    print("=== DATASET GENERATION SUMMARY ===")
    print(f"Output CSV: {out_csv}")
    print(f"Output metadata: {out_meta}")
    print(f"Rows: {len(df_out)}")
    print(f"Unique nodes: {df_out['node_id'].nunique()}")
    print(f"Scenario distribution: {df_out['scenario_type'].value_counts(dropna=False).to_dict()}")
    print(f"Timestamp min/max: {df_out['timestamp'].min()} / {df_out['timestamp'].max()}")
    print("NaN check (numeric):", int(df_out[numeric_cols].isna().sum().sum()))
    print("Inf check (numeric):", int(np.isinf(df_out[numeric_cols].to_numpy()).sum()))
    print("Done.")


if __name__ == "__main__":
    main()