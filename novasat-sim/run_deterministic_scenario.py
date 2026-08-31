"""
run_deterministic_scenario.py
==============================
Deterministic e2e producer for validate_ops_totals.py.

Uses a FIXED sim_time_s step (bypassing eng.update() which uses wall-clock time)
so the scenario is fully reproducible and the expected bundle count can be
pre-computed by compute_expected_contacts.py.

Scenario:
  N = 2, speed = 3600x, sim_dt = 288.0 s per tick
  N_TICKS = 100 (8 simulated hours)
  At tick 50: inject one isolate override for orbiter_0
  (During ticks 50-99 orbiter_0 is isolated -- bundle events from it stop)

After the run the script prints the session file path and event counts.
Pass those to validate_ops_totals.py with --expected-bundles from
compute_expected_contacts.py.

Usage:
  python run_deterministic_scenario.py
"""

import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import importlib.util
spec = importlib.util.spec_from_file_location("server", os.path.join(os.path.dirname(__file__), "server.py"))
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
eng = mod.sim_engine

SIM_DT   = 288.0   # seconds per tick  (= 0.08s wall * 3600x)
N_TICKS  = 100
N_SAT    = 2
OVERRIDE_TICK = 50  # tick at which we inject the isolate override
OVERRIDE_SAT  = "orbiter_0"

eng.set_n(N_SAT)
eng.set_speed(3600.0)
eng.sim_time_s = 0.0   # deterministic start

print(f"Running deterministic scenario: N={N_SAT}, sim_dt={SIM_DT}s, ticks={N_TICKS}")
print(f"Override: isolate {OVERRIDE_SAT} at tick {OVERRIDE_TICK}")

pre_override_bundles = None

for tick in range(N_TICKS):
    # Set sim_time directly (bypass update() which uses real wall clock)
    eng.sim_time_s = tick * SIM_DT

    if tick == OVERRIDE_TICK:
        # Inject ground override
        pre_override_bundles = eng.ops_window_totals["bundles_exchanged"]
        node = eng.nodes[OVERRIDE_SAT]
        node.is_isolated = True
        eng.ops_window_totals["ground_overrides"] += 1
        ov = {
            "type": "override",
            "sim_time_s": float(eng.sim_time_s),
            "satellite_id": OVERRIDE_SAT,
            "override_action": "isolate",
            "operator_note": "deterministic-test quarantine at tick 50",
        }
        eng.event_log.append(ov)
        mod._append_ops_event(ov)
        print(f"  [tick {tick}] Override injected: isolate {OVERRIDE_SAT} at t={eng.sim_time_s:.0f}s")

    eng.compute_tick_state()  # runs physics + increments counters

print()
print("Scenario complete.")
print(f"  ops_window_totals : {eng.ops_window_totals}")
print(f"  event_log length  : {len(eng.event_log)}")
print(f"  session file      : {mod._OPS_SESSION_FILE}")
print()

# Read back JSONL independently
events = []
with open(mod._OPS_SESSION_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            events.append(json.loads(line))

counts = {}
for ev in events:
    t = ev.get("type", "?")
    counts[t] = counts.get(t, 0) + 1

print("JSONL event breakdown (independently counted):")
for k, v in sorted(counts.items()):
    print(f"  {k:15s}: {v}")

bundle_j   = counts.get("bundle",   0)
override_j = counts.get("override", 0)
print()
print(f"bundles in JSONL    : {bundle_j}")
print(f"overrides in JSONL  : {override_j}")
print()

# Compute bundles after override (orbiter_0 isolated from tick 50 onward)
if pre_override_bundles is not None:
    post_bundles = eng.ops_window_totals["bundles_exchanged"] - pre_override_bundles
    print(f"Bundles before override (ticks 0-49)  : {pre_override_bundles}")
    print(f"Bundles after  override (ticks 50-99) : {post_bundles}")
    print(f"  (orbiter_0 is isolated; only orbiter_1 contributes)")

print()
print("To validate, run:")
print(f"  python validate_ops_totals.py \\")
print(f"    --session \"{mod._OPS_SESSION_FILE}\" \\")
print(f"    --n {N_SAT} --n-ticks {N_TICKS} --sim-dt {SIM_DT} \\")
print(f"    --expected-bundles {bundle_j} \\")
print(f"    --expected-overrides {override_j}")
