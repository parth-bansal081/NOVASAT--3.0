"""
generate_normal_trials.py

Phase 4 §1.2: Generate baseline "normal" telemetry examples across Phase 1-3 simulation
with realistic continuous sensor noise (Gaussian noise) and trial-to-trial random seed variations.
Uses real Phase 1 contact windows and Phase 2 PKI crypto signature verification.
Optimized with single-node streaming pipeline for ultra-low memory consumption (< 15 MB RAM).
"""

import os
import sys
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import math
import numpy as np
import pandas as pd

from config import (
    R_MARS_KM,
    SEMI_MAJOR_AXIS_KM,
    MU_MARS_KM3_S2,
    MARS_OMEGA_RAD_S,
    ROVER_POSITIONS,
    N_VALUES,
    SIM_DURATION_S,
)
from identity import (
    create_root_ca,
    generate_keypair,
    create_csr,
    sign_csr,
    sign_message,
    verify_signature,
)

FULL_COLUMNS = [
    "timestamp", "window_id", "node_id", "node_type", "N", "scenario_type",
    "is_attack_active", "is_node_compromised", "is_false_revocation_event",
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

_CONTACT_INDEX_CACHE = {}


def is_in_interval(starts: np.ndarray, ends: np.ndarray, t_array: np.ndarray) -> np.ndarray:
    """Fast 1D binary-search interval test. Zero 2D memory allocations."""
    if len(starts) == 0:
        return np.zeros(len(t_array), dtype=bool)
    idx = np.searchsorted(starts, t_array, side='right') - 1
    return (idx >= 0) & (t_array <= ends[np.maximum(0, idx)])


def get_contact_index(n: int) -> dict:
    """
    Loads data/contact_windows_N{n}.csv and builds optimized 1D numpy arrays by peer node.
    """
    if n in _CONTACT_INDEX_CACHE:
        return _CONTACT_INDEX_CACHE[n]

    csv_path = os.path.join(ROOT_DIR, "data", f"contact_windows_N{n}.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Required Phase 1 file missing: {csv_path}")

    df = pd.read_csv(csv_path)

    df_earth = df[df["link_type"] == "orbiter_earth"]
    df_ro = df[df["link_type"] == "rover_orbiter"]
    df_oo = df[df["link_type"] == "orbiter_orbiter"]

    nodes = set(df["node_a"]).union(set(df["node_b"])) - {"earth"}
    node_index = {}

    for nid in nodes:
        nid_all = df[(df["node_a"] == nid) | (df["node_b"] == nid)].sort_values(by="window_start_s")
        all_starts = nid_all["window_start_s"].to_numpy(dtype=float)
        all_ends = nid_all["window_end_s"].to_numpy(dtype=float)
        sorted_ends = np.sort(all_ends)

        nid_earth = df_earth[(df_earth["node_a"] == nid) | (df_earth["node_b"] == nid)].sort_values(by="window_start_s")
        earth_starts = nid_earth["window_start_s"].to_numpy(dtype=float)
        earth_ends = nid_earth["window_end_s"].to_numpy(dtype=float)

        # Peer interval dictionaries
        nid_ro = df_ro[(df_ro["node_a"] == nid) | (df_ro["node_b"] == nid)]
        ro_by_peer = {}
        for _, row in nid_ro.iterrows():
            peer = row["node_b"] if row["node_a"] == nid else row["node_a"]
            if peer not in ro_by_peer:
                ro_by_peer[peer] = {"starts": [], "ends": []}
            ro_by_peer[peer]["starts"].append(row["window_start_s"])
            ro_by_peer[peer]["ends"].append(row["window_end_s"])
        for p in ro_by_peer:
            ro_by_peer[p]["starts"] = np.array(ro_by_peer[p]["starts"], dtype=float)
            ro_by_peer[p]["ends"] = np.array(ro_by_peer[p]["ends"], dtype=float)

        nid_oo = df_oo[(df_oo["node_a"] == nid) | (df_oo["node_b"] == nid)]
        oo_by_peer = {}
        for _, row in nid_oo.iterrows():
            peer = row["node_b"] if row["node_a"] == nid else row["node_a"]
            if peer not in oo_by_peer:
                oo_by_peer[peer] = {"starts": [], "ends": []}
            oo_by_peer[peer]["starts"].append(row["window_start_s"])
            oo_by_peer[peer]["ends"].append(row["window_end_s"])
        for p in oo_by_peer:
            oo_by_peer[p]["starts"] = np.array(oo_by_peer[p]["starts"], dtype=float)
            oo_by_peer[p]["ends"] = np.array(oo_by_peer[p]["ends"], dtype=float)

        node_index[nid] = {
            "all_starts": all_starts,
            "all_ends": all_ends,
            "sorted_ends": sorted_ends,
            "earth_starts": earth_starts,
            "earth_ends": earth_ends,
            "ro_by_peer": ro_by_peer,
            "oo_by_peer": oo_by_peer,
        }

    earth_intervals_by_orbiter = {}
    for orb_id in [node for node in nodes if node.startswith("orbiter")]:
        orb_e = df_earth[(df_earth["node_a"] == orb_id) | (df_earth["node_b"] == orb_id)].sort_values(by="window_start_s")
        earth_intervals_by_orbiter[orb_id] = (
            orb_e["window_start_s"].to_numpy(dtype=float),
            orb_e["window_end_s"].to_numpy(dtype=float)
        )

    cache_entry = {
        "nodes": node_index,
        "earth_intervals_by_orbiter": earth_intervals_by_orbiter,
    }
    _CONTACT_INDEX_CACHE[n] = cache_entry
    return cache_entry


def evaluate_node_contact_vectorized(n: int, nid: str, t_array: np.ndarray) -> dict:
    """
    Computes exact real contact state for node `nid` across all timestamps in `t_array`.
    Memory-efficient 1D binary search.
    """
    idx = get_contact_index(n)
    n_data = idx["nodes"].get(nid)

    num_pts = len(t_array)
    if n_data is None:
        return {
            "in_contact_with_ground": np.zeros(num_pts, dtype=np.int32),
            "num_visible_orbiters": np.zeros(num_pts, dtype=np.int32),
            "num_visible_rovers": np.zeros(num_pts, dtype=np.int32),
            "time_since_last_contact_sec": t_array.astype(np.float32),
        }

    is_orbiter = nid.startswith("orbiter")

    # 1. in_contact_with_ground
    if is_orbiter:
        in_ground_mask = is_in_interval(n_data["earth_starts"], n_data["earth_ends"], t_array)
        in_ground = in_ground_mask.astype(np.int32)
    else:
        in_ground = np.zeros(num_pts, dtype=np.int32)
        ro_by_peer = n_data["ro_by_peer"]
        for orb_id, p_info in ro_by_peer.items():
            ro_mask = is_in_interval(p_info["starts"], p_info["ends"], t_array)
            e_starts, e_ends = idx["earth_intervals_by_orbiter"].get(orb_id, ([], []))
            e_mask = is_in_interval(e_starts, e_ends, t_array)
            in_ground = np.maximum(in_ground, (ro_mask & e_mask).astype(np.int32))

    # 2. num_visible_orbiters & 3. num_visible_rovers
    num_vis_orbiters = np.zeros(num_pts, dtype=np.int32)
    num_vis_rovers = np.zeros(num_pts, dtype=np.int32)

    if is_orbiter:
        for p_info in n_data["oo_by_peer"].values():
            mask = is_in_interval(p_info["starts"], p_info["ends"], t_array)
            num_vis_orbiters += mask.astype(np.int32)

        for p_info in n_data["ro_by_peer"].values():
            mask = is_in_interval(p_info["starts"], p_info["ends"], t_array)
            num_vis_rovers += mask.astype(np.int32)
    else:
        for p_info in n_data["ro_by_peer"].values():
            mask = is_in_interval(p_info["starts"], p_info["ends"], t_array)
            num_vis_orbiters += mask.astype(np.int32)

    # 4. time_since_last_contact_sec
    all_starts = n_data["all_starts"]
    all_ends = n_data["all_ends"]
    sorted_ends = n_data["sorted_ends"]

    currently_active = (num_vis_orbiters > 0) | (num_vis_rovers > 0) | (in_ground > 0)

    if len(all_starts) > 0:
        last_ended_idx = np.searchsorted(sorted_ends, t_array, side='right') - 1

        last_ended_time = sorted_ends[np.maximum(0, last_ended_idx)]
        elapsed = t_array - last_ended_time
        elapsed = np.where(last_ended_idx < 0, t_array, elapsed)
        time_since_last_contact = np.where(currently_active, 0.0, elapsed).astype(np.float32)
    else:
        time_since_last_contact = t_array.astype(np.float32)

    return {
        "in_contact_with_ground": in_ground,
        "num_visible_orbiters": num_vis_orbiters,
        "num_visible_rovers": num_vis_rovers,
        "time_since_last_contact_sec": time_since_last_contact,
    }


def generate_single_node_telemetry(
    seed: int,
    n: int,
    nid: str,
    sim_duration_s: int = SIM_DURATION_S,
    window_size_sec: int = 60,
    node_key=None,
    node_cert=None,
    ca_cert=None,
) -> pd.DataFrame:
    """
    Generates telemetry DataFrame for a single node `nid` in a trial.
    Memory footprint: ~8 MB RAM max.
    """
    rng = np.random.RandomState(seed + hash(nid) % 10000)

    is_orbiter = nid.startswith("orbiter")
    node_type = "orbiter" if is_orbiter else "rover"

    num_windows = sim_duration_s // window_size_sec
    t_array = np.arange(window_size_sec, sim_duration_s + window_size_sec, window_size_sec, dtype=np.float32)
    w_ids = np.arange(num_windows, dtype=np.int32)
    mean_motion = math.sqrt(MU_MARS_KM3_S2 / (SEMI_MAJOR_AXIS_KM ** 3))

    if is_orbiter:
        idx = int(nid.split("_")[1])
        phase = (idx * (2 * math.pi / n)) + (mean_motion * t_array)

        pos_x_clean = SEMI_MAJOR_AXIS_KM * np.cos(phase)
        pos_y_clean = np.zeros_like(phase)
        pos_z_clean = SEMI_MAJOR_AXIS_KM * np.sin(phase)

        vel_x_clean = -SEMI_MAJOR_AXIS_KM * mean_motion * np.sin(phase)
        vel_y_clean = np.zeros_like(phase)
        vel_z_clean = SEMI_MAJOR_AXIS_KM * mean_motion * np.cos(phase)

    else:
        r_info = ROVER_POSITIONS[nid]
        phi = math.radians(r_info["latitude_deg"])
        lam = math.radians(r_info["longitude_deg"])
        theta = MARS_OMEGA_RAD_S * t_array

        x_fix = R_MARS_KM * math.cos(phi) * math.cos(lam)
        y_fix = R_MARS_KM * math.cos(phi) * math.sin(lam)
        z_fix = R_MARS_KM * math.sin(phi)

        pos_x_clean = x_fix * np.cos(theta) - y_fix * np.sin(theta)
        pos_y_clean = x_fix * np.sin(theta) + y_fix * np.cos(theta)
        pos_z_clean = np.full_like(t_array, z_fix)

        vel_x_clean = -MARS_OMEGA_RAD_S * pos_y_clean
        vel_y_clean = MARS_OMEGA_RAD_S * pos_x_clean
        vel_z_clean = np.zeros_like(t_array)

    # Add Gaussian sensor noise
    pos_x = (pos_x_clean + rng.normal(0, 0.05, size=num_windows)).astype(np.float32)
    pos_y = (pos_y_clean + rng.normal(0, 0.05, size=num_windows)).astype(np.float32)
    pos_z = (pos_z_clean + rng.normal(0, 0.05, size=num_windows)).astype(np.float32)

    vel_x = (vel_x_clean + rng.normal(0, 0.005, size=num_windows)).astype(np.float32)
    vel_y = (vel_y_clean + rng.normal(0, 0.005, size=num_windows)).astype(np.float32)
    vel_z = (vel_z_clean + rng.normal(0, 0.005, size=num_windows)).astype(np.float32)

    speed = np.sqrt(vel_x**2 + vel_y**2 + vel_z**2)
    speed_diff = np.diff(speed, prepend=speed[0])
    speed_delta = np.abs(speed_diff).astype(np.float32)
    accel_proxy = (speed_diff / window_size_sec).astype(np.float32)

    # Power drain & system telemetry
    # Drain rate calibrated to the 30-day / 43,200-window sim duration:
    #   0.0002 W/window × 43,200 windows ≈ 8.6 total drain → power stays 86–95 W
    #   (old 0.01/window drained battery in first ~2% of the simulation)
    power_start = 95.0 + rng.uniform(-5.0, 5.0)
    power_drain = 0.0002 + rng.normal(0, 0.00004, size=num_windows)
    power_delta = (-power_drain).astype(np.float32)
    cum_power = power_start + np.cumsum(power_delta)
    power_level = np.maximum(10.0, cum_power + rng.normal(0, 0.05, size=num_windows)).astype(np.float32)

    cpu_load = np.clip(25.0 + rng.normal(0, 3.0, size=num_windows), 5.0, 95.0).astype(np.float32)
    queue_depth = np.maximum(0, np.round(5 + rng.normal(0, 1.5, size=num_windows))).astype(np.int32)

    # Real Contact & Visibility calculation from Phase 1 CSV
    c_info = evaluate_node_contact_vectorized(n, nid, t_array)

    num_vis_orb = c_info["num_visible_orbiters"]
    num_vis_rov = c_info["num_visible_rovers"]
    unique_peers = num_vis_orb + num_vis_rov

    msgs_sent = np.maximum(1, np.round(6 * np.maximum(1, unique_peers) + rng.normal(0, 2, size=num_windows))).astype(np.int32)
    msgs_recv = np.maximum(1, np.round(6 * np.maximum(1, unique_peers) + rng.normal(0, 2, size=num_windows))).astype(np.int32)
    bytes_sent = (msgs_sent * 256.0 + rng.normal(0, 50.0, size=num_windows)).astype(np.float32)
    bytes_recv = (msgs_recv * 256.0 + rng.normal(0, 50.0, size=num_windows)).astype(np.float32)

    interarrival_mean_ms = np.maximum(50.0, 500.0 + rng.normal(0, 20.0, size=num_windows)).astype(np.float32)
    interarrival_std_ms = np.maximum(5.0, 50.0 + rng.normal(0, 5.0, size=num_windows)).astype(np.float32)

    # Verify signature if key/cert provided
    sig_fail = 0
    if node_key is not None and node_cert is not None and ca_cert is not None:
        payload = f"{nid}:{t_array[0]}".encode('utf-8')
        sig = sign_message(payload, node_key)
        if not verify_signature(payload, sig, node_cert, ca_cert):
            sig_fail = 1

    # Build DataFrame column-by-column to avoid pandas block consolidation.
    # The monolithic dict constructor causes pandas to merge all same-dtype columns
    # into one contiguous 2D array (e.g. np.empty((14, 43200), float32) = 2.31 MiB),
    # which fails on fragmented heaps. Column-by-column assignment stores each column
    # as a separate 1D block, eliminating the large contiguous allocation requirement.
    df_node = pd.DataFrame({"timestamp": t_array})
    df_node["window_id"]                    = w_ids
    df_node["node_id"]                      = nid
    df_node["node_type"]                    = node_type
    df_node["N"]                            = n
    df_node["scenario_type"]                = "normal"
    df_node["is_attack_active"]             = np.zeros(num_windows, dtype=np.int32)
    df_node["is_node_compromised"]          = np.zeros(num_windows, dtype=np.int32)
    df_node["is_false_revocation_event"]    = np.zeros(num_windows, dtype=np.int32)
    df_node["sig_verify_fail_count"]        = np.full(num_windows, sig_fail, dtype=np.int32)
    df_node["revocation_msgs_sent"]         = np.zeros(num_windows, dtype=np.int32)
    df_node["revocation_msgs_received"]     = np.zeros(num_windows, dtype=np.int32)
    df_node["accusations_made"]             = np.zeros(num_windows, dtype=np.int32)
    df_node["accusations_received"]         = np.zeros(num_windows, dtype=np.int32)
    df_node["corroboration_count_for_target"] = np.zeros(num_windows, dtype=np.int32)
    df_node["trust_score_current"]          = np.ones(num_windows, dtype=np.float32)
    df_node["msgs_sent"]                    = msgs_sent
    df_node["msgs_recv"]                    = msgs_recv
    df_node["bytes_sent"]                   = bytes_sent
    df_node["bytes_recv"]                   = bytes_recv
    df_node["unique_peers_contacted"]       = unique_peers
    df_node["interarrival_mean_ms"]         = interarrival_mean_ms
    df_node["interarrival_std_ms"]          = interarrival_std_ms
    df_node["retransmit_count"]             = np.zeros(num_windows, dtype=np.float32)
    df_node["drop_count"]                   = np.zeros(num_windows, dtype=np.float32)
    df_node["in_contact_with_ground"]       = c_info["in_contact_with_ground"]
    df_node["num_visible_orbiters"]         = num_vis_orb
    df_node["num_visible_rovers"]           = num_vis_rov
    df_node["window_open_fraction"]         = np.where(c_info["in_contact_with_ground"] == 1, 1.0, 0.0).astype(np.float32)
    df_node["time_since_last_contact_sec"]  = c_info["time_since_last_contact_sec"]
    df_node["pos_x"]                        = pos_x
    df_node["pos_y"]                        = pos_y
    df_node["pos_z"]                        = pos_z
    df_node["vel_x"]                        = vel_x
    df_node["vel_y"]                        = vel_y
    df_node["vel_z"]                        = vel_z
    df_node["speed_delta"]                  = speed_delta
    df_node["accel_proxy"]                  = accel_proxy
    df_node["heading_change_rate"]          = np.zeros(num_windows, dtype=np.float32)
    df_node["power_level"]                  = power_level
    df_node["power_delta"]                  = power_delta
    df_node["cpu_load"]                     = cpu_load
    df_node["queue_depth"]                  = queue_depth

    return df_node


def generate_single_normal_trial(
    seed: int,
    n: int = 4,
    sim_duration_s: int = SIM_DURATION_S,
    window_size_sec: int = 60,
) -> pd.DataFrame:
    """
    Convenience wrapper returning concatenated DataFrame for small unit tests.
    """
    orbiters = [f"orbiter_{i}" for i in range(n)]
    rovers = ["rover_1", "rover_2"]
    all_nodes = orbiters + rovers

    ca_priv, ca_cert = create_root_ca()

    dfs = []
    for nid in all_nodes:
        npriv, _ = generate_keypair()
        csr = create_csr(nid, npriv)
        ncert = sign_csr(csr, ca_priv, ca_cert)

        df_node = generate_single_node_telemetry(
            seed=seed,
            n=n,
            nid=nid,
            sim_duration_s=sim_duration_s,
            window_size_sec=window_size_sec,
            node_key=npriv,
            node_cert=ncert,
            ca_cert=ca_cert,
        )
        dfs.append(df_node)

    df_trial = pd.concat(dfs, ignore_index=True)
    df_trial = df_trial.sort_values(by=["timestamp", "node_id"]).reset_index(drop=True)
    return df_trial[FULL_COLUMNS]
