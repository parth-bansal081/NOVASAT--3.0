"""
inject_behavioral_fault.py

Phase 4 §1.3: Inject behavioral fault categories while maintaining valid cryptographic signatures:
  1. trajectory_drift: steadily growing position/velocity offset (stuck thruster / nav error)
  2. power_anomaly: rapid power drain or abnormal power_delta pattern
  3. timing_comm_anomaly: message spamming (interarrival_mean_ms drop) & resource exhaustion (cpu/queue spike)
Operates in-place on DataFrames for zero RAM duplication.

Fault Realism Design (Phase 4 Fix):
  - All fault magnitudes are expressed as a randomly-drawn multiple of the feature's own normal σ.
  - severity_sigma ~ Uniform(2.0, 8.0) is drawn ONCE per faulted trial, creating a realistic mix:
      · 2–3σ: hard contextual anomalies (comparable to NASA SMAP/MSL "contextual" class)
      · 6–8σ: easier point anomalies
  - Per-row values are sampled with noise around the shifted mean — no single fixed constant.
  - power_level uses a cumulative noisy drain model (not a clamped constant) to guarantee nonzero variance.

Normal baseline reference values (from train_normal.csv):
  cpu_load             ~ N(25,  3)
  queue_depth          ~ N(5,   1.53)
  interarrival_mean_ms ~ N(500, 20)
"""

import math
import numpy as np
import pandas as pd

# Normal distribution reference values (mean, std) for each affected feature.
# These match the distribution used by generate_normal_trials.py.
_NORMAL_CPU_MEAN    = 25.0
_NORMAL_CPU_STD     = 3.0
_NORMAL_QUEUE_MEAN  = 5.0
_NORMAL_QUEUE_STD   = 1.53
_NORMAL_IAT_MEAN    = 500.0
_NORMAL_IAT_STD     = 20.0

# Power drain baseline for fault injection.
# Normal drain in generate_normal_trials.py is now 0.0002 W/window (slow, realistic 30-day drain).
# Fault drain is intentionally 50× faster: _BASE_DRAIN_RATE * severity_multiplier (2–8) gives
# 100–400× the normal rate, creating a clearly detectable (but still noisy) anomaly.
_BASE_DRAIN_RATE    = 0.01
_DRAIN_NOISE_STD    = 0.002


def inject_trajectory_drift(
    df: pd.DataFrame,
    target_node: str,
    fault_onset_time: float,
    drift_rate: float = 0.05,
) -> pd.DataFrame:
    """
    Trajectory drift: starting at fault_onset_time, add a steadily growing offset
    to pos_x/y/z and vel_x/y/z for target_node.
    """
    mask = (df["node_id"] == target_node) & (df["timestamp"] >= fault_onset_time)

    dt = (df.loc[mask, "timestamp"] - fault_onset_time).astype(np.float32)
    offset_pos = (drift_rate * (dt / 3600.0) ** 1.2).astype(np.float32)
    offset_vel = (drift_rate * 0.1 * (dt / 3600.0)).astype(np.float32)

    df.loc[mask, "pos_x"] += offset_pos
    df.loc[mask, "pos_y"] += offset_pos * np.float32(0.8)
    df.loc[mask, "pos_z"] += offset_pos * np.float32(0.5)

    df.loc[mask, "vel_x"] += offset_vel
    df.loc[mask, "vel_y"] += offset_vel * np.float32(0.8)
    df.loc[mask, "vel_z"] += offset_vel * np.float32(0.5)

    df.loc[mask, "is_attack_active"] = 1
    df.loc[mask, "is_node_compromised"] = 1
    df.loc[mask, "scenario_type"] = "trajectory_drift"

    return df


def inject_power_anomaly(
    df: pd.DataFrame,
    target_node: str,
    fault_onset_time: float,
    drain_factor: float = 0.5,
) -> pd.DataFrame:
    """
    Power anomaly: realistic cumulative drain model.

    Instead of clamping power_level to a fixed constant (which produced exactly 0.00 σ),
    this model:
      1. Draws severity_multiplier ~ Uniform(2.0, 8.0) once per trial call.
      2. Assigns a per-row random drain rate ~ N(base_drain * severity, drain_noise_std).
      3. Accumulates the drain cumulatively over time (like a real battery discharge curve).
      4. Subtracts cumulative drain from the existing power_level baseline, floored at 1.0.

    This guarantees nonzero variance in anomalous rows and produces a realistic noisy
    discharge trace rather than a single repeated constant value.
    """
    mask = (df["node_id"] == target_node) & (df["timestamp"] >= fault_onset_time)
    n_fault_rows = mask.sum()

    if n_fault_rows == 0:
        return df

    # Draw severity once per trial — creates a realistic mix of 2–8× normal drain
    severity_multiplier = np.random.uniform(2.0, 8.0)
    effective_drain = _BASE_DRAIN_RATE * severity_multiplier * drain_factor

    # Sort the faulty rows by timestamp so cumsum is chronologically correct
    fault_indices = df.index[mask]
    ordered_indices = df.loc[fault_indices, "timestamp"].sort_values().index

    # Per-row drain rates: noisy around the effective drain (guaranteed positive)
    per_row_drain = np.abs(
        np.random.normal(effective_drain, _DRAIN_NOISE_STD, size=n_fault_rows)
    )
    cumulative_drain = np.cumsum(per_row_drain).astype(np.float32)

    # Subtract cumulative drain from baseline power_level, floor at 1.0
    baseline_power = df.loc[ordered_indices, "power_level"].to_numpy(dtype=np.float32)
    new_power = np.maximum(np.float32(1.0), baseline_power - cumulative_drain)
    df.loc[ordered_indices, "power_level"] = new_power

    # power_delta reflects the drain acceleration (negative = draining)
    df.loc[mask, "power_delta"] = np.float32(-effective_drain)

    df.loc[mask, "is_attack_active"] = 1
    df.loc[mask, "is_node_compromised"] = 1
    df.loc[mask, "scenario_type"] = "power_anomaly"

    return df


def inject_timing_comm_anomaly(
    df: pd.DataFrame,
    target_node: str,
    fault_onset_time: float,
) -> pd.DataFrame:
    """
    Timing/comm anomaly: interarrival_mean_ms drops (spamming) and cpu_load/queue_depth spike.

    Fault realism:
      - severity_sigma ~ Uniform(2.0, 8.0) drawn ONCE per trial call.
      - Each feature's faulted mean = normal_mean + severity_sigma * normal_std
        (or minus, for features that decrease during the fault).
      - Per-row values are sampled with noise around the shifted mean — no single fixed value.

    This produces:
      · At severity 2σ: a challenging boundary anomaly (e.g. cpu ~31, queue ~8, IAT ~460 ms)
      · At severity 8σ: a clear point anomaly (e.g. cpu ~49, queue ~17, IAT ~340 ms)
    instead of always hitting the same extreme fixed range (cpu 85–99, queue 40–100, IAT 5–20).
    """
    mask = (df["node_id"] == target_node) & (df["timestamp"] >= fault_onset_time)
    n_fault_rows = mask.sum()

    if n_fault_rows == 0:
        return df

    # Draw severity once per trial — single random scalar for this fault episode
    severity_sigma = np.random.uniform(2.0, 8.0)

    # --- cpu_load: INCREASES during resource exhaustion ---
    cpu_new_mean = _NORMAL_CPU_MEAN + severity_sigma * _NORMAL_CPU_STD
    cpu_samples = np.random.normal(cpu_new_mean, _NORMAL_CPU_STD, size=n_fault_rows)
    cpu_samples = np.clip(cpu_samples, _NORMAL_CPU_MEAN, 100.0).astype(np.float32)
    df.loc[mask, "cpu_load"] = cpu_samples

    # --- queue_depth: INCREASES during resource exhaustion ---
    queue_new_mean = _NORMAL_QUEUE_MEAN + severity_sigma * _NORMAL_QUEUE_STD
    queue_samples = np.random.normal(queue_new_mean, _NORMAL_QUEUE_STD, size=n_fault_rows)
    queue_samples = np.maximum(queue_samples, 0.0).astype(np.int32)
    df.loc[mask, "queue_depth"] = queue_samples

    # --- interarrival_mean_ms: DECREASES (spamming = faster messages) ---
    iat_new_mean = _NORMAL_IAT_MEAN - severity_sigma * _NORMAL_IAT_STD
    iat_new_mean = max(iat_new_mean, 5.0)  # floor: can't go below 5 ms physically
    iat_samples = np.random.normal(iat_new_mean, _NORMAL_IAT_STD, size=n_fault_rows)
    iat_samples = np.maximum(iat_samples, 1.0).astype(np.float32)  # absolute floor
    df.loc[mask, "interarrival_mean_ms"] = iat_samples

    # --- interarrival_std_ms: also tightens during bursty spamming ---
    df.loc[mask, "interarrival_std_ms"] = np.random.uniform(0.5, 3.0, size=n_fault_rows).astype(np.float32)

    # --- msgs_sent: INCREASES proportionally to severity ---
    msgs_new_mean = 20.0 + severity_sigma * 5.0
    msgs_samples = np.random.normal(msgs_new_mean, 3.0, size=n_fault_rows)
    msgs_samples = np.maximum(msgs_samples, 1.0).astype(np.int32)
    df.loc[mask, "msgs_sent"] = msgs_samples

    df.loc[mask, "is_attack_active"] = 1
    df.loc[mask, "is_node_compromised"] = 1
    df.loc[mask, "scenario_type"] = "timing_comm_anomaly"

    return df


def inject_behavioral_fault(
    df: pd.DataFrame,
    target_node: str,
    fault_type: str,
    fault_onset_time: float,
) -> pd.DataFrame:
    """
    Dispatcher to inject a behavioral fault of fault_type into target_node at fault_onset_time.
    """
    if fault_type == "trajectory_drift":
        return inject_trajectory_drift(df, target_node, fault_onset_time)
    elif fault_type == "power_anomaly":
        return inject_power_anomaly(df, target_node, fault_onset_time)
    elif fault_type == "timing_comm_anomaly":
        return inject_timing_comm_anomaly(df, target_node, fault_onset_time)
    else:
        raise ValueError(f"Unknown fault_type: {fault_type}")
