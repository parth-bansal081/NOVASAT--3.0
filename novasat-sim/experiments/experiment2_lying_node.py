"""
NOVASAT Phase 3 — Experiment 2: Lying-Node Attack (§5)

Measures the false-revocation rate when a compromised node creates a false
accusation against a healthy target, under five conditions:
  1. model1_sanity — Model 1 (must show 0% false revocation, §8.1)
  2. naive         — Any single gossip accusation acted on immediately
  3. fixed_threshold — Require K=2 distinct accusers
  4. trust_weighted  — Cumulative trust weight >= 2.0
  5. decay           — Trust-weighted with weight adjustment over time

For each N in {1, 2, 4, 6, 8, 10}, runs TRIALS_PER_CONFIG trials per condition.

Output: results/results_experiment2.csv
  columns: N, condition, trial_number, falsely_revoked, time_to_false_revocation_s
"""

import os
import random
import pandas as pd

from config import N_VALUES, SIM_DURATION_S, TRIALS_PER_CONFIG
from propagation_models import (
    load_contact_schedule,
    get_active_nodes,
    run_lying_node_trial,
)

# The five conditions to test, in order
CONDITIONS = [
    "model1_sanity",
    "naive",
    "fixed_threshold",
    "trust_weighted",
    "decay",
]


def run_experiment2(seed: int = 123) -> pd.DataFrame:
    """
    Run all Experiment 2 trials.

    Returns a DataFrame with columns:
        N, condition, trial_number, falsely_revoked, time_to_false_revocation_s
    """
    rng = random.Random(seed)
    results = []

    for n in N_VALUES:
        print(f"\n{'='*60}")
        print(f"Experiment 2 — N = {n}")
        print(f"{'='*60}")

        schedule = load_contact_schedule(n)
        active_nodes = get_active_nodes(n)
        num_nodes = len(active_nodes)

        for condition in CONDITIONS:
            print(f"  Running condition '{condition}' ({TRIALS_PER_CONFIG} trials)...", end="", flush=True)
            for trial in range(1, TRIALS_PER_CONFIG + 1):
                # Pick random compromised node
                compromised_idx = rng.randint(0, num_nodes - 1)
                compromised = active_nodes[compromised_idx]

                # Pick a different random healthy target
                target_idx = rng.randint(0, num_nodes - 2)
                if target_idx >= compromised_idx:
                    target_idx += 1
                healthy_target = active_nodes[target_idx]

                # Random accusation time in [0, SIM_DURATION_S)
                accusation_time = rng.uniform(0, SIM_DURATION_S)

                falsely_revoked, time_to_rev = run_lying_node_trial(
                    schedule, active_nodes, compromised, healthy_target,
                    accusation_time, condition
                )

                results.append({
                    "N": n,
                    "condition": condition,
                    "trial_number": trial,
                    "falsely_revoked": falsely_revoked,
                    "time_to_false_revocation_s": time_to_rev if time_to_rev is not None else "",
                })

            print(" done.")

    df = pd.DataFrame(results, columns=[
        "N", "condition", "trial_number", "falsely_revoked", "time_to_false_revocation_s"
    ])
    return df


def main():
    print("=" * 60)
    print("NOVASAT Phase 3 — Experiment 2: Lying-Node Attack")
    print("=" * 60)

    df = run_experiment2()

    # Save results
    os.makedirs("results", exist_ok=True)
    out_path = os.path.join("results", "results_experiment2.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} rows to {out_path}")

    # Print summary statistics
    print("\n--- Summary: False-Revocation Rate ---")
    for n in N_VALUES:
        for condition in CONDITIONS:
            subset = df[(df["N"] == n) & (df["condition"] == condition)]
            n_revoked = subset["falsely_revoked"].sum()
            rate = n_revoked / len(subset) * 100 if len(subset) > 0 else 0
            print(f"  N={n:>2}, {condition:<20s}: {rate:>5.1f}% ({n_revoked}/{len(subset)})")


if __name__ == "__main__":
    main()
