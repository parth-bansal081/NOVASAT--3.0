# NOVASAT — Phase 3 Addendum 2: Warm-Up Trust History

**Why this exists:** the previous multi-colluder run showed fixed-threshold, trust-weighted, and decay-based all collapsing to identical results (100% false-revocation at colluder_count ≥ 2). This happened because every trial started "cold" — every node at the same uniform trust weight of 1.0 — so weighted math and simple counting were mathematically forced to behave the same way. This addendum gives nodes an actual prior track record before the real attack, so the three methods can finally be told apart.

## 1. The three warm-up conditions — this is the actual new experiment

Add a new sweep dimension, `warmup_condition`, with three values:

- **`neutral`** — no warm-up at all. Reproduces the exact previous test as a consistency baseline — this run's `neutral` results should closely match the earlier run's already-reported numbers.
- **`bad_reputation`** — each colluding node has one **prior false accusation** on record before the real attack (simulating a node that already cried wolf once and lost credibility).
- **`good_reputation`** — each colluding node has one **prior confirmed-true accusation** on record before the real attack (simulating a node that previously reported something real, and gained credibility for it).

**Why `good_reputation` matters — read this before treating it as a lower priority than `bad_reputation`:** this tests whether an attacker can deliberately behave well first specifically to build trust, then exploit that trust to strike harder later. This is a well-established concept in real trust/reputation-system security research (often called a strategic or "whitewashing" attack) — finding that trust-weighting is *worse* than simple counting against this kind of patient attacker would be a genuinely strong, non-obvious result, not just a defensive footnote.

## 2. Exact timeline within each warm-up trial

- **Day 5 (`t = 432,000s`):** the warm-up event happens.
  - `good_reputation`: designate a separate warm-up target (distinct from the real, final target and from the colluders) that is made **genuinely compromised** (real signature failures, same mechanism as Experiment 1) starting at this time. Each colluder-to-be also independently and truthfully accuses this warm-up target around this time.
  - `bad_reputation`: designate a separate warm-up target that stays **entirely healthy** for the whole simulation. Each colluder-to-be falsely accuses this healthy warm-up target at this time.
- **Day 12 (`t = 1,036,800s`):** confirmation/expiry checkpoint.
  - `good_reputation`: if the warm-up target has, by now, actually been ground-revoked through the normal Model 1/reactive process (it should be, since it's genuinely compromised) — mark each colluder's earlier accusation as *confirmed*, applying the existing decay rule's confirm factor (`×1.2`) to their trust weight.
  - `bad_reputation`: since the warm-up target was never actually compromised, its accusation is never confirmed by this checkpoint — mark it *unconfirmed*, applying the existing decay rule's penalty factor (`×0.5`) to each colluder's trust weight.
- **Day 20 (`t = 1,728,000s`):** the real collusion attempt begins, exactly as in the previous addendum — colluders accuse the actual, separate, healthy final target. The only difference from before: colluders now start this attack with their **adjusted** trust weight (0.5, 1.0, or 1.2, depending on condition) instead of a uniform 1.0.

## 3. What to sweep

Same as the previous addendum, plus the new dimension: `N ∈ {8, 10}`, `colluder_count ∈ {1, 2, 3, 4}`, `warmup_condition ∈ {neutral, bad_reputation, good_reputation}`, all 5 conditions (`model1_sanity`, `naive`, `fixed_threshold`, `trust_weighted`, `decay`), `200 trials` per full combination.

**Note:** `model1_sanity` and `naive` should be unaffected by `warmup_condition` (Model 1 never uses trust weights at all; naive gossip acts on any single report regardless of weight) — running them across all three warm-up conditions anyway is a useful additional sanity check: their results should stay flat/identical across `neutral`, `bad_reputation`, and `good_reputation`. If they don't, something is leaking warm-up state into logic that shouldn't be affected by it.

## 4. What to actually check once results come back

1. **Does `neutral` reproduce the earlier run's numbers closely?** This confirms nothing broke in the baseline case while adding the new mechanism.
2. **Does `bad_reputation` show trust-weighted/decay with LOWER false-revocation rates than fixed-threshold**, at colluder_count values where fixed-threshold still says 100%? This is the "differentiation" this whole addendum exists to find — with weight 0.5 each, it should now take more colluders to reach the 2.0 threshold than it takes to satisfy fixed-threshold's simple headcount of 2.
3. **Does `good_reputation` show trust-weighted/decay with HIGHER (worse) false-revocation rates than fixed-threshold** at the same colluder counts — confirming the strategic-attacker vulnerability?
4. **Report every result unmerged** — separate rows for N=8 and N=10, separate rows for every warm-up condition. Do not collapse any of these together in the results you show back.

## 5. Output format

`results_experiment2_warmup.csv` — columns: `N`, `colluder_count`, `warmup_condition`, `condition`, `trial_number`, `falsely_revoked`, `time_to_false_revocation_s`.

## 6. Definition of done

- [ ] Warm-up mechanism implemented exactly per §2's timeline
- [ ] Full sweep run: N × colluder_count × warmup_condition × 5 conditions × 200 trials
- [ ] `neutral` condition's results checked against the earlier (pre-addendum) run for consistency
- [ ] `bad_reputation` and `good_reputation` results actually show trust-weighted/decay diverging from fixed-threshold — report the real numbers whichever direction they go
- [ ] All results reported unmerged by N and by warm-up condition
