"""
conjunction_assessment.py

NOVASAT Track 2 Phase 2 — 2D Conjunction Risk & Probability of Collision (Pc) Engine
Calculates time of closest approach (TCA), miss distance, and 2D isotropic Gaussian Probability of Collision (Pc).
"""

import math
import numpy as np

# Spec Constants
PC_WATCH_THRESHOLD = 1e-6
PC_TRIGGER_THRESHOLD = 1e-4

HARD_BODY_RADIUS_KM = 0.010  # 10 meters combined radius
UNCERTAINTY_SIGMA_0_KM = 0.050  # 50 meters initial uncertainty
UNCERTAINTY_GROWTH_KM_HR = 0.002  # 2 meters per hour uncertainty growth rate


def compute_pair_conjunction(
    pos_A_km: np.ndarray,
    vel_A_km_s: np.ndarray,
    pos_B_km: np.ndarray,
    vel_B_km_s: np.ndarray,
    lookahead_sec: float = 86400.0,
    r_hb_km: float = HARD_BODY_RADIUS_KM,
) -> dict:
    """
    Computes time of closest approach (TCA), miss distance at TCA,
    and 2D isotropic Probability of Collision (Pc) over the lookahead window.
    """
    MU = 42828.37
    r_A_mag = float(np.linalg.norm(pos_A_km))
    r_B_mag = float(np.linalg.norm(pos_B_km))

    n_A = math.sqrt(MU / (r_A_mag**3))
    n_B = math.sqrt(MU / (r_B_mag**3))

    # Unit vectors for orbital plane A and B
    u_A_0 = math.atan2(pos_A_km[2], pos_A_km[0])
    u_B_0 = math.atan2(pos_B_km[2], pos_B_km[0])

    # Vectorized trajectory sampling over lookahead window
    dt = np.linspace(0.0, min(86400.0, lookahead_sec), 72, dtype=np.float64)
    u_A_t = u_A_0 + n_A * dt
    u_B_t = u_B_0 + n_B * dt

    p_A_x = r_A_mag * np.cos(u_A_t)
    p_A_z = r_A_mag * np.sin(u_A_t)

    p_B_x = r_B_mag * np.cos(u_B_t)
    p_B_z = r_B_mag * np.sin(u_B_t)

    dists = np.sqrt((p_B_x - p_A_x)**2 + (p_B_z - p_A_z)**2)
    min_idx = np.argmin(dists)
    min_dist_km = float(dists[min_idx])
    best_tca_sec = float(dt[min_idx])

    tca_hours = best_tca_sec / 3600.0
    sigma_sat = UNCERTAINTY_SIGMA_0_KM + UNCERTAINTY_GROWTH_KM_HR * tca_hours
    sigma_comb = math.sqrt(2.0) * sigma_sat

    # 2D Probability of Collision (Pc) calculation
    scale = 2.0 * (sigma_comb ** 2)
    pc = (1.0 - math.exp(-(r_hb_km ** 2) / scale)) * math.exp(-(min_dist_km ** 2) / scale)

    is_watch = pc > PC_WATCH_THRESHOLD
    is_trigger = pc > PC_TRIGGER_THRESHOLD

    rel_vel_km_s = float(np.linalg.norm(vel_B_km_s - vel_A_km_s))

    return {
        "tca_sec": best_tca_sec,
        "tca_hours": tca_hours,
        "miss_distance_km": min_dist_km,
        "rel_velocity_km_s": rel_vel_km_s,
        "sigma_comb_km": float(sigma_comb),
        "pc": float(pc),
        "is_watch": is_watch,
        "is_trigger": is_trigger,
    }


def evaluate_all_pairs_conjunction(
    satellites_state: list,
    lookahead_sec: float = 86400.0,
    triage_model = None,
) -> dict:
    """
    Evaluates conjunction risk across all satellite pairs (N*(N-1)/2 pairs).
    Optionally applies triage ML pre-filter to skip full Pc calculation on safe pairs.
    """
    n_sats = len(satellites_state)
    risks = []
    max_pc = 0.0
    max_pc_pair = None
    total_pairs = (n_sats * (n_sats - 1)) // 2
    full_eval_count = 0

    for i in range(n_sats):
        sat_A = satellites_state[i]
        pos_A = np.array(sat_A["cartesian_km"], dtype=np.float64)
        if "velocity_vector_km_s" in sat_A:
            vel_A = np.array(sat_A["velocity_vector_km_s"], dtype=np.float64)
        else:
            r_A = np.linalg.norm(pos_A)
            v_mag_A = math.sqrt(42828.37 / r_A)
            # Velocity tangent to circular orbit in XZ polar plane
            vel_A = np.array([-pos_A[2] / r_A, 0.0, pos_A[0] / r_A], dtype=np.float64) * v_mag_A

        for j in range(i + 1, n_sats):
            sat_B = satellites_state[j]
            pos_B = np.array(sat_B["cartesian_km"], dtype=np.float64)
            if "velocity_vector_km_s" in sat_B:
                vel_B = np.array(sat_B["velocity_vector_km_s"], dtype=np.float64)
            else:
                r_B = np.linalg.norm(pos_B)
                v_mag_B = math.sqrt(42828.37 / r_B)
                vel_B = np.array([-pos_B[2] / r_B, 0.0, pos_B[0] / r_B], dtype=np.float64) * v_mag_B

            # Cheap features for pre-filter
            rough_miss_km = float(np.linalg.norm(pos_B - pos_A))
            rough_vrel_km_s = float(np.linalg.norm(vel_B - vel_A))

            # Apply ML triage classifier pre-filter if provided
            should_eval = True
            if triage_model is not None:
                # Features: [miss_distance_km, rel_velocity_km_s]
                feat = np.array([[rough_miss_km, rough_vrel_km_s]], dtype=np.float32)
                pred_risk = triage_model.predict(feat)[0]
                if pred_risk == 0 and rough_miss_km > 50.0:  # Skip if triage says safe and miss distance > 50km
                    should_eval = False

            if should_eval:
                full_eval_count += 1
                result = compute_pair_conjunction(pos_A, vel_A, pos_B, vel_B, lookahead_sec=lookahead_sec)
                pair_key = f"{sat_A['id']}--{sat_B['id']}"
                result["pair_key"] = pair_key
                result["sat_A"] = sat_A["id"]
                result["sat_B"] = sat_B["id"]

                if result["pc"] > max_pc:
                    max_pc = result["pc"]
                    max_pc_pair = pair_key

                if result["is_watch"] or result["is_trigger"]:
                    risks.append(result)

    return {
        "risks": risks,
        "max_pc": max_pc,
        "max_pc_pair": max_pc_pair,
        "total_pairs": total_pairs,
        "full_eval_count": full_eval_count,
        "triage_skipped": total_pairs - full_eval_count,
    }
