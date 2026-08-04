import pandas as pd

df = pd.read_csv("results/results_experiment2_warmup.csv")
print(f"Total trials in CSV: {len(df)}")

print("\n" + "=" * 90)
print("FULL UNMERGED RESULTS TABLE: EXPERIMENT 2 WARM-UP TRUST HISTORY")
print("=" * 90)
header = f"{'N':<4} | {'Warmup':<16} | {'Colluders':<10} | {'Condition':<18} | {'False Revocation Rate':<22} | {'Revoked / Total'}"
print(header)
print("-" * len(header))

for n in [8, 10]:
    for warmup_cond in ["neutral", "bad_reputation", "good_reputation"]:
        for cc in [1, 2, 3, 4]:
            for condition in ["model1_sanity", "naive", "fixed_threshold", "trust_weighted", "decay"]:
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
