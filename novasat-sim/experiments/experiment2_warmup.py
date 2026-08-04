"""
NOVASAT Phase 3 — Addendum 2: Warm-Up Trust History Experiment

Evaluates false-revocation rates when multiple nodes (1, 2, 3, 4) collude
simultaneously under three warm-up conditions:
  1. neutral         — no warm-up prior (colluders start at 1.0 weight)
  2. bad_reputation  — prior unconfirmed false accusation (colluders start at 0.5 weight)
  3. good_reputation — prior confirmed true accusation (colluders start at 1.2 weight)

Sweeps across N ∈ {8, 10}, colluder_count ∈ {1, 2, 3, 4}, warmup_condition ∈ {neutral, bad_reputation, good_reputation},
and 5 conditions: model1_sanity, naive, fixed_threshold, trust_weighted, decay.
Runs 200 trials per full combination (total 24,000 trials).

Output: results/results_experiment2_warmup.csv
  columns: N, colluder_count, warmup_condition, condition, trial_number, falsely_revoked, time_to_false_revocation_s
"""

import os
import random
import pandas as pd

from config import TRIALS_PER_CONFIG
from propagation_models import (
    load_contact_schedule,
    get_active_nodes,
    run_multi_colluder_trial,
)

N_VALUES_COLLUDERS = [8, 10]
COLLUDER_COUNTS = [1, 2, 3, 4]
WARMUP_CONDITIONS = ["neutral", "bad_reputation", "good_reputation"]
COLLUSION_WINDOW_S = 86400  # 24 hours

CONDITIONS = [
    "model1_sanity",
    "naive",
    "fixed_threshold",
    "trust_weighted",
    "decay",
]


def run_experiment2_warmup(seed: int = 123) -> pd.DataFrame:
    """
    Run all Phase 3 Warm-Up Trust History Experiment trials.
    """
    rng = random.Random(seed)
    results = []

    for n in N_VALUES_COLLUDERS:
        print(f"\n{'='*75}")
        print(f"Phase 3 Warm-Up Experiment — N = {n}")
        print(f"{'='*75}")

        schedule = load_contact_schedule(n)
        active_nodes = get_active_nodes(n)

        for warmup_cond in WARMUP_CONDITIONS:
            print(f"\n  [Warm-Up Condition = {warmup_cond}]")

            for colluder_count in COLLUDER_COUNTS:
                print(f"    [Colluder Count = {colluder_count}]")

                for condition in CONDITIONS:
                    print(f"      Running condition '{condition:<16s}' ({TRIALS_PER_CONFIG} trials)...", end="", flush=True)

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
                            warmup_condition=warmup_cond,
                        )

                        results.append({
                            "N": n,
                            "colluder_count": colluder_count,
                            "warmup_condition": warmup_cond,
                            "condition": condition,
                            "trial_number": trial,
                            "falsely_revoked": falsely_revoked,
                            "time_to_false_revocation_s": time_to_rev if time_to_rev is not None else "",
                        })

                    print(" done.")

    df = pd.DataFrame(results, columns=[
        "N", "colluder_count", "warmup_condition", "condition", "trial_number", "falsely_revoked", "time_to_false_revocation_s"
    ])
    return df


def main():
    print("=" * 75)
    print("NOVASAT Phase 3 — Warm-Up Trust History Experiment")
    print("=" * 75)

    df = run_experiment2_warmup()

    # Save results
    os.makedirs("results", exist_ok=True)
    out_path = os.path.join("results", "results_experiment2_warmup.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} rows to {out_path}")

    # Print summary table (FULLY UNMERGED)
    print("\n" + "=" * 85)
    print("UNMERGED SUMMARY RESULTS: FALSE-REVOCATION RATES BY N, WARMUP, COLLUDERS & CONDITION")
    print("=" * 85)
    header = f"{'N':<4} | {'Warmup':<16} | {'Colluders':<10} | {'Condition':<18} | {'False Revocation Rate':<22} | {'Revoked / Total'}"
    print(header)
    print("-" * len(header))

    for n in N_VALUES_COLLUDERS:
        for warmup_cond in WARMUP_CONDITIONS:
            for cc in COLLUDER_COUNTS:
                for condition in CONDITIONS:
                    subset = df[
                        (df["N"] == n) & 
                        (df["warmup_condition"] == warmup_cond) & 
                        (df["colluder_count"] == cc) & 
                        (df["condition"] == condition)
                    ]
                    n_revoked = subset["falsely_revoked"].sum()
                    total = len(subset)
                    rate = (n_revoked / total) * 100.0 if total > 0 else 0.0
                    print(f"{n:<4} | {warmup_cond:<16} | {cc:<10} | {condition:<18} | {rate:>20.2f}% | {n_revoked:>6} / {total:<5}")


if __name__ == "__main__":
    main()
