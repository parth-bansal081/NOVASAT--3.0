"""
NOVASAT Phase 3 — Multi-Colluder Extension (§5 Closing Experiment 2)

Evaluates false-revocation rates when multiple nodes (1, 2, 3, 4) collude
simultaneously to falsely accuse a healthy target node.

Runs for N ∈ {8, 10}, colluder_count ∈ {1, 2, 3, 4}, across 5 conditions:
  1. model1_sanity    — Model 1 (must remain 0% across all colluder counts)
  2. naive            — Any single gossip accusation acted on immediately
  3. fixed_threshold  — Require K=2 distinct accusers
  4. trust_weighted   — Cumulative trust weight >= 2.0
  5. decay            — Decay-based weight evaluation

Output: results/results_experiment2_colluders.csv
  columns: N, colluder_count, condition, trial_number, falsely_revoked, time_to_false_revocation_s
"""

import os
import random
import pandas as pd

from config import SIM_DURATION_S, TRIALS_PER_CONFIG
from propagation_models import (
    load_contact_schedule,
    get_active_nodes,
    run_multi_colluder_trial,
)

N_VALUES_COLLUDERS = [8, 10]
COLLUDER_COUNTS = [1, 2, 3, 4]
COLLUSION_WINDOW_S = 86400  # 24 hours

CONDITIONS = [
    "model1_sanity",
    "naive",
    "fixed_threshold",
    "trust_weighted",
    "decay",
]


def run_experiment2_colluders(seed: int = 123) -> pd.DataFrame:
    """
    Run all Multi-Colluder Experiment 2 trials.
    """
    rng = random.Random(seed)
    results = []

    for n in N_VALUES_COLLUDERS:
        print(f"\n{'='*65}")
        print(f"Multi-Colluder Extension — N = {n}")
        print(f"{'='*65}")

        schedule = load_contact_schedule(n)
        active_nodes = get_active_nodes(n)

        for colluder_count in COLLUDER_COUNTS:
            print(f"\n  [Colluder Count = {colluder_count}]")
            for condition in CONDITIONS:
                print(f"    Running condition '{condition:<16s}' ({TRIALS_PER_CONFIG} trials)...", end="", flush=True)

                for trial in range(1, TRIALS_PER_CONFIG + 1):
                    # Pick colluder_count distinct colluding nodes
                    colluding_nodes = rng.sample(active_nodes, colluder_count)

                    # Pick a separate healthy target
                    remaining_healthy = [node for node in active_nodes if node not in colluding_nodes]
                    healthy_target = rng.choice(remaining_healthy)

                    # Each colluder generates a false accusation at a random time in [0, COLLUSION_WINDOW_S)
                    accusation_times = {
                        c: rng.uniform(0, COLLUSION_WINDOW_S) for c in colluding_nodes
                    }

                    falsely_revoked, time_to_rev = run_multi_colluder_trial(
                        schedule=schedule,
                        active_nodes=active_nodes,
                        colluding_nodes=colluding_nodes,
                        healthy_target=healthy_target,
                        accusation_times=accusation_times,
                        condition=condition,
                    )

                    results.append({
                        "N": n,
                        "colluder_count": colluder_count,
                        "condition": condition,
                        "trial_number": trial,
                        "falsely_revoked": falsely_revoked,
                        "time_to_false_revocation_s": time_to_rev if time_to_rev is not None else "",
                    })

                print(" done.")

    df = pd.DataFrame(results, columns=[
        "N", "colluder_count", "condition", "trial_number", "falsely_revoked", "time_to_false_revocation_s"
    ])
    return df


def main():
    print("=" * 65)
    print("NOVASAT Phase 3 — Multi-Colluder Extension (Closing Experiment 2)")
    print("=" * 65)

    df = run_experiment2_colluders()

    # Save results
    os.makedirs("results", exist_ok=True)
    out_path = os.path.join("results", "results_experiment2_colluders.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} rows to {out_path}")

    # Print summary table
    print("\n" + "=" * 65)
    print("SUMMARY RESULTS: FALSE-REVOCATION RATES BY COLLUDER COUNT")
    print("=" * 65)
    header = f"{'N':<4} | {'Colluders':<10} | {'Condition':<18} | {'False Revocation Rate':<22} | {'Revoked / Total'}"
    print(header)
    print("-" * len(header))

    for n in N_VALUES_COLLUDERS:
        for cc in COLLUDER_COUNTS:
            for condition in CONDITIONS:
                subset = df[(df["N"] == n) & (df["colluder_count"] == cc) & (df["condition"] == condition)]
                n_revoked = subset["falsely_revoked"].sum()
                total = len(subset)
                rate = (n_revoked / total) * 100.0 if total > 0 else 0.0
                print(f"{n:<4} | {cc:<10} | {condition:<18} | {rate:>20.2f}% | {n_revoked:>6} / {total:<5}")


if __name__ == "__main__":
    main()
