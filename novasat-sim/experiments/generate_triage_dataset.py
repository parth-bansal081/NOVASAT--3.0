"""
generate_triage_dataset.py

Generates offline batch training data for the lightweight ML triage classifier (Part F).
Sweeps orbital-insertion dispersions, altitude decay rates, and satellite pair geometry
to produce labeled training samples: [miss_distance_km, rel_velocity_km_s] -> is_conjunction (Pc > 1e-4).
"""

import os
import sys
import math
import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.orbital_mechanics import get_mars_body, create_orbiters, propagate_orbiters_positions
from src.conjunction_assessment import compute_pair_conjunction

DATA_DIR = os.path.join(ROOT_DIR, "data", "triage")


def generate_triage_data(n_scenarios: int = 50, output_csv: str = None):
    if output_csv is None:
        output_csv = os.path.join(DATA_DIR, "triage_dataset.csv")
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)

    print("=" * 60)
    print("Generating ML Triage Classifier Dataset (Offline Batch)")
    print("=" * 60)

    body = get_mars_body()
    rows = []

    MU = 42828.37
    for seed in range(n_scenarios):
        n_sats = np.random.choice([6, 8, 10])
        orbiters = create_orbiters(n_sats, body, apply_dispersion=True, random_seed=seed)
        
        # Inject random altitude decay on one satellite to generate conjunction risk
        decay_idx = np.random.choice(n_sats)
        decay_km = np.random.uniform(0.1, 15.0)

        times, positions_list = propagate_orbiters_positions(orbiters, sim_duration_s=86400, time_step_s=600)

        for step_idx in range(0, len(times)):
            t_sec = times[step_idx]

            for i in range(n_sats):
                orb_A = orbiters[i]
                a_A = float(orb_A.a.to_value()) - (decay_km if i == decay_idx else 0.0)
                inc_A = float(orb_A.inc.to_value())
                nu_A_0 = float(orb_A.nu.to_value())
                n_A = math.sqrt(MU / (a_A**3))
                u_A = nu_A_0 + n_A * t_sec
                v_A_mag = math.sqrt(MU / a_A)

                pos_A = np.array([a_A * math.cos(u_A), a_A * math.sin(u_A) * math.cos(inc_A), a_A * math.sin(u_A) * math.sin(inc_A)], dtype=np.float64)
                vel_A = np.array([-v_A_mag * math.sin(u_A), v_A_mag * math.cos(u_A) * math.cos(inc_A), v_A_mag * math.cos(u_A) * math.sin(inc_A)], dtype=np.float64)

                for j in range(i + 1, n_sats):
                    orb_B = orbiters[j]
                    a_B = float(orb_B.a.to_value()) - (decay_km if j == decay_idx else 0.0)
                    inc_B = float(orb_B.inc.to_value())
                    nu_B_0 = float(orb_B.nu.to_value())
                    n_B = math.sqrt(MU / (a_B**3))
                    u_B = nu_B_0 + n_B * t_sec
                    v_B_mag = math.sqrt(MU / a_B)

                    pos_B = np.array([a_B * math.cos(u_B), a_B * math.sin(u_B) * math.cos(inc_B), a_B * math.sin(u_B) * math.sin(inc_B)], dtype=np.float64)
                    vel_B = np.array([-v_B_mag * math.sin(u_B), v_B_mag * math.cos(u_B) * math.cos(inc_B), v_B_mag * math.cos(u_B) * math.sin(inc_B)], dtype=np.float64)

                    res = compute_pair_conjunction(pos_A, vel_A, pos_B, vel_B, lookahead_sec=86400.0)

                    # Synthesize synthetic close pass variations for dataset balance
                    is_conj = int(res["is_trigger"])
                    rows.append({
                        "miss_distance_km": res["miss_distance_km"],
                        "rel_velocity_km_s": res["rel_velocity_km_s"],
                        "pc": res["pc"],
                        "is_conjunction": is_conj
                    })

                    # Generate positive conjunction samples by injecting small meter-scale offsets (d < 50m)
                    if step_idx % 20 == 0:
                        offset_km = np.random.uniform(-0.02, 0.02, size=3)
                        close_pos_B = pos_A + offset_km
                        res_close = compute_pair_conjunction(pos_A, vel_A, close_pos_B, vel_B, lookahead_sec=86400.0)
                        rows.append({
                            "miss_distance_km": res_close["miss_distance_km"],
                            "rel_velocity_km_s": res_close["rel_velocity_km_s"],
                            "pc": res_close["pc"],
                            "is_conjunction": 1
                        })

    df = pd.DataFrame(rows)
    df.to_csv(output_csv, index=False)
    print(f"Generated {len(df):,} triage samples saved to: {output_csv}")
    print(f"  Conjunctions (Pc > 1e-4): {df['is_conjunction'].sum():,} ({df['is_conjunction'].mean()*100:.2f}%)")


if __name__ == "__main__":
    generate_triage_data()
