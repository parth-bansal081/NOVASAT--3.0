# NOVASAT — Phase 3 Build Spec: Trust Propagation & the Lying-Node Experiment

**Audience note, same as before:** no assumed background beyond what Phases 1 and 2 already established. Every threshold, procedure, and metric is specified explicitly. Flag ambiguity rather than guessing.

**Goal of this phase, in one sentence:** using Phase 1's real contact-window schedule and Phase 2's real cryptographic identities, measure whether letting nodes warn each other directly (instead of only trusting Earth) actually makes the swarm safer overall, or trades slowness for a new, exploitable weakness.

**This phase directly produces Claim A's results** — the core comparison the whole project is built around.

---

## 1. What this phase builds on — do not regenerate anything

- **Phase 1's contact-window CSVs** (`data/contact_windows_N{n}.csv`) — the exact, real schedule of who can talk to whom, and when. This phase must read these files, not recompute or approximate them.
- **Phase 2's identities** — the same fixed pool of 12 nodes (`orbiter_0`–`orbiter_9`, `rover_1`, `rover_2`), their real keypairs, certificates, and the `sign_message()` / `verify_signature()` / `verify_certificate_chain()` functions. For a given N, use only `orbiter_0` through `orbiter_{N-1}` plus both rovers, per the Phase 2 addendum's documented provisioning scope.

## 2. The two models — precise definitions (read carefully, this is the crux of the whole experiment)

Both models use the exact same physical contact schedule from Phase 1 — the difference is entirely about **who is allowed to originate a trust update that other nodes will act on**, not about which links exist.

### Model 1 — Ground-authenticated only
- A node's trust store is only ever updated to mark someone `"revoked"` if the update is a message **signed by the Ground CA's private key**.
- Any node relaying such a message forward to another node it later contacts is fine — the receiving node verifies the ground signature itself, regardless of how many hops it took to arrive. Relaying does not require re-signing.
- **A node's own personal observation of bad behavior from a peer does NOT get sent onward to warn other nodes under this model.** It may still trigger the node's own local, reactive distrust of that peer (an always-on layer, unaffected by which model is active — see §3) — but it cannot tell anyone else about it unless Ground later confirms and signs a revocation.

### Model 2 — Gossip-based, peer-originated
- Any node that personally observes bad behavior from a peer can create its own accusation message — signed with **its own private key** (proving who sent it, not whether it's true) — and pass it to any node it next contacts.
- Receiving nodes do not act on a single unconfirmed accusation immediately — they apply one of the **corroboration rules** in §5 to decide whether enough evidence has accumulated to mark the accused node `"revoked"` in their own trust store.
- Ground-signed revocations (as in Model 1) are also still valid and always immediately actionable under Model 2 — Model 2 is Model 1 plus peer-gossip, not a replacement for it.

## 3. The always-on reactive layer — present in both models, not a variable being tested

Regardless of which model is active: if Node A directly receives a message from Node B during a contact window, and that message's signature fails `verify_signature()`, Node A immediately stops trusting B **for its own future interactions** — no propagation, no delay, this is just Phase 2's crypto working correctly. This is not what's being compared — it's the baseline both models sit on top of.

## 4. Experiment 1 — propagation speed (the "obvious direction, real magnitude" half of Claim A)

**Procedure, per trial:**
1. Pick one node uniformly at random from the active pool (N orbiters + 2 rovers) to become compromised.
2. Pick a compromise time uniformly at random within the 30-day simulation window.
3. From that moment on, every message the compromised node sends during any contact window fails signature verification (simulate this directly — don't require a "real" forged message, just flag that node's outgoing messages as invalid from this point forward).
4. Walk forward through the Phase 1 contact schedule in time order. The first node that contacts the compromised node after the compromise time catches it via §3's reactive check.
5. From that point, propagate the revocation according to whichever model is active (§2), using the schedule's remaining contact windows.
6. Record: the timestamp at which **every other node** in the active pool has the compromised node marked `"revoked"` in its own trust store. The last one to update is your trial's propagation time.

**Run this for:**
- Every N in `{1, 2, 4, 6, 8, 10}`
- Both models
- `TRIALS_PER_CONFIG = 200` trials per (N, model) combination — this is a config constant, adjustable, but must not be reduced without a stated reason, since single-digit trial counts would not support a credible mean/worst-case claim.

**Metric logged per (N, model):** mean propagation time, worst-case (max) propagation time, across all 200 trials.

## 5. Experiment 2 — the lying-node attack (the actual non-obvious half of Claim A)

**Procedure, per trial:**
1. Pick one node at random to be compromised (as in Experiment 1), plus a second, different node at random to be the **falsely accused, entirely healthy target**.
2. At a random time, the compromised node originates an accusation against the healthy target — signed with the compromised node's own still-valid private key (its own key isn't necessarily revoked yet — that's realistic; compromise and detection aren't instant).
3. Propagate this false accusation using Model 2's gossip mechanism (Model 1 is not vulnerable to this by design — see the required sanity check in §8).
4. Test this under **four conditions**, run separately:
   - **Naive gossip (no corroboration):** any single received accusation is acted on immediately. This is your baseline showing the raw, unmitigated vulnerability size.
   - **Fixed-threshold vote:** a node only marks the target `"revoked"` once it has received the same accusation from at least `K = 2` distinct originating nodes.
   - **Trust-weighted vote:** every node starts with a trust weight of `1.0` for every other node. An accusation contributes its originator's current weight toward a running total for the accused; a node acts once that total reaches `THRESHOLD = 2.0`.
   - **Decay-based trust score:** like the trust-weighted model, but weights adjust over time based on outcomes — increase a reporting node's weight by a factor of `1.2` when one of its accusations is later confirmed by a real Experiment-1-style ground revocation, decrease it by a factor of `0.5` when an accusation it made is never confirmed within the simulation window. Treat this as the most complex variant — implement it only after the first three are working and validated.
5. Record, per condition: whether the healthy target ends up wrongly marked `"revoked"` anywhere in the network by the end of the 30-day window (yes/no), and if so, how long it took.

**Run this for:** every N in `{1, 2, 4, 6, 8, 10}`, `TRIALS_PER_CONFIG = 200` trials per (N, condition).

**Metric logged per (N, condition):** false-revocation rate — the percentage of trials in which the healthy target was wrongly revoked anywhere in the network.

## 6. Why this design is the actual point of the whole phase

If Experiment 1 shows Model 2 propagating faster than Model 1 (the expected, "obvious direction" result), and Experiment 2's naive-gossip condition shows a meaningfully high false-revocation rate, that's the real finding: speed was bought at a real cost. The interesting number is how much of that cost the corroboration variants claw back — if the fixed-threshold or trust-weighted variant gets the false-revocation rate down near zero while keeping most of Model 2's speed advantage from Experiment 1, that's a genuine, reportable result. If it doesn't, that's also a genuine, reportable result — report whichever is actually true.

## 7. Output format

Two CSV files:

`results_experiment1.csv` — columns: `N`, `model`, `trial_number`, `propagation_time_s`

`results_experiment2.csv` — columns: `N`, `condition`, `trial_number`, `falsely_revoked` (True/False), `time_to_false_revocation_s` (blank if never happened)

## 8. Validation — required before this phase counts as done

1. **Model 1 must show zero vulnerability in Experiment 2.** By design, Model 1 never acts on peer-originated accusations at all — run Experiment 2's procedure with Model 1 active (in addition to the four Model-2 conditions) as an explicit sanity check, and confirm the false-revocation rate is exactly 0% across all trials. If it's not, the model separation in §2 wasn't actually implemented correctly.
2. **Propagation time in Experiment 1 must never be faster than physically possible** — spot-check a handful of individual trials and confirm the recorded propagation time is never shorter than the actual time between the compromise event and the very next relevant contact window in that trial's Phase 1 schedule.
3. **Trial count confirmation** — confirm exactly `TRIALS_PER_CONFIG` trials were run and recorded for every (N, model) and (N, condition) combination — no silently-skipped configurations.
4. **Sanity check on Experiment 1's direction** — confirm whether Model 2's mean propagation time is actually lower than Model 1's at N = 8 and N = 10 specifically (the only N values where crosslinks exist at all, per Phase 1's Fix 3 note) — report the real result, whichever direction it goes, rather than assuming Model 2 wins.

## 9. What this phase explicitly does NOT include

- No anomaly/behavioral detection (stolen-valid-key scenario) — that's Phase 4, a separate fault type entirely from anything in this phase.
- No RL/decision-agent logic — Phase 7, design-only.
- No changes to Phase 1's contact schedule or Phase 2's identity/crypto functions — this phase only reads and uses them.

## 10. Suggested project structure (extends Phases 1–2)

```
novasat-sim/
  ...(existing Phase 1/2 files)...
  propagation_models.py     # implements Model 1 and Model 2 from §2
  experiment1_speed.py       # implements §4
  experiment2_lying_node.py  # implements §5
  validate_phase3.py         # implements all checks in §8
  results/
    results_experiment1.csv
    results_experiment2.csv
```

## 11. Definition of done

- [ ] Model 1 and Model 2 implemented exactly per §2's authority-based definition (not just "different relay paths")
- [ ] Experiment 1 run for all N × both models × 200 trials each
- [ ] Experiment 2 run for all N × five conditions (Model 1 sanity check + 4 gossip conditions) × 200 trials each
- [ ] Both output CSVs produced in the exact format in §7
- [ ] All four checks in §8 pass, including Model 1's required 0% vulnerability result
- [ ] Nothing listed in §9 has been built yet
