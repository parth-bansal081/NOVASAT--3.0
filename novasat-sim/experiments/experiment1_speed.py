"""
NOVASAT Phase 3 — Experiment 1: Propagation Speed (§4)

Measures how quickly revocation of a compromised node propagates to every
other node in the active pool, comparing:
  - Model 1 (ground-authenticated only)
  - Model 2 (gossip-based, naive — fastest variant)

For each N in {1, 2, 4, 6, 8, 10}, runs TRIALS_PER_CONFIG trials per model.

Output: results/results_experiment1.csv
  columns: N, model, trial_number, propagation_time_s
"""

import os
import random
import pandas as pd

from config import N_VALUES, SIM_DURATION_S, TRIALS_PER_CONFIG
from propagation_models import (
    load_contact_schedule,
    get_active_nodes,
    run_model1_propagation,
    run_model2_propagation,
)


def run_experiment1(seed: int = 42) -> pd.DataFrame:
    """
    Run all Experiment 1 trials.

    Returns a DataFrame with columns: N, model, trial_number, propagation_time_s
    """
    rng = random.Random(seed)
    results = []

    for n in N_VALUES:
        print(f"\n{'='*60}")
        print(f"Experiment 1 — N = {n}")
        print(f"{'='*60}")

        schedule = load_contact_schedule(n)
        active_nodes = get_active_nodes(n)
        num_nodes = len(active_nodes)

        for model_name, model_func in [("model1", run_model1_propagation), ("model2", None)]:
            print(f"  Running {model_name} ({TRIALS_PER_CONFIG} trials)...", end="", flush=True)
            for trial in range(1, TRIALS_PER_CONFIG + 1):
                # Pick random compromised node
                compromised = active_nodes[rng.randint(0, num_nodes - 1)]
                # Pick random compromise time in [0, SIM_DURATION_S)
                compromise_time = rng.uniform(0, SIM_DURATION_S)

                if model_name == "model1":
                    prop_time = run_model1_propagation(
                        schedule, active_nodes, compromised, compromise_time
                    )
                else:
                    # Model 2 uses naive gossip for Experiment 1
                    # (fastest variant — relevant for the speed comparison)
                    prop_time = run_model2_propagation(
                        schedule, active_nodes, compromised, compromise_time,
                        condition="naive"
                    )

                results.append({
                    "N": n,
                    "model": model_name,
                    "trial_number": trial,
                    "propagation_time_s": prop_time if prop_time != float("inf") else None,
                })

            print(" done.")

    df = pd.DataFrame(results, columns=["N", "model", "trial_number", "propagation_time_s"])
    return df


def main():
    print("=" * 60)
    print("NOVASAT Phase 3 — Experiment 1: Propagation Speed")
    print("=" * 60)

    df = run_experiment1()

    # Save results
    os.makedirs("results", exist_ok=True)
    out_path = os.path.join("results", "results_experiment1.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} rows to {out_path}")

    # Print summary statistics
    print("\n--- Summary: Mean propagation time (seconds) ---")
    for n in N_VALUES:
        for model in ["model1", "model2"]:
            subset = df[(df["N"] == n) & (df["model"] == model)]
            valid = subset["propagation_time_s"].dropna()
            if len(valid) > 0:
                mean_t = valid.mean()
                max_t = valid.max()
                print(f"  N={n:>2}, {model}: mean={mean_t:>10.1f}s, worst={max_t:>10.1f}s  ({len(valid)}/{len(subset)} completed)")
            else:
                print(f"  N={n:>2}, {model}: NO completed trials")


if __name__ == "__main__":
    main()
