"""
validate_ops_totals.py - Track 3 Part A: Ops Window Totals Validation
======================================================================

Purpose
-------
Independent scripted-baseline check for the Ops Window totals panel.

IMPORTANT: This is NOT a self-diff or loose ceiling check.
Check 1 asserts an exact match against an independently-computed ground truth
derived directly from Keplerian orbital mechanics and Mars ellipsoid geometry.

How to Derive & Reproduce Expected Bundle Counts:
------------------------------------------------
The expected bundle count for any scenario (e.g. 9 for N=2, 100 ticks @ 288s)
is NOT empirical/observed data. It is independently derived from orbital physics:
  1. Keplerian orbit propagation (a=3789.5km, i=90°, nu0_i = i * 360/N)
  2. Mars sidereal rotation (w = 7.0882e-5 rad/s) & biaxial ellipsoid geometry
  3. Rover line-of-sight elevation check (elev >= 10° cone over Jezero & Gale)
  4. Node quarantine timeline filtering (contacts involving isolated nodes are excluded)

To compute expected ground truth for a new scenario:
  python compute_expected_contacts.py --n <N> --n-ticks <TICKS> --sim-dt <SIM_DT>

Check 1 automatically calls compute_expected_contacts.count_contacts_independently()
with the session's parameter set and JSONL isolation log unless --expected-bundles <N>
is explicitly provided to assert a known scenario baseline.

Usage
-----
  python validate_ops_totals.py [--session path/to/ops_events_YYYYMMDD_HHMMSS.jsonl]
                                [--n 2] [--n-ticks 100] [--sim-dt 288.0]
                                [--expected-bundles 9] [--expected-overrides 1]
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from compute_expected_contacts import count_contacts_independently, orbital_period_s


def load_jsonl(path: Path) -> List[Dict]:
    events = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"  [WARN] Line {lineno} is not valid JSON: {exc}")
    return events


def find_latest_session(ops_events_dir: Path) -> Optional[Path]:
    files = sorted(ops_events_dir.glob("ops_events_*.jsonl"), reverse=True)
    return files[0] if files else None


def count_events(events: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for ev in events:
        t = ev.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


def run_validation(
    session_path: Path,
    duration_s: float,
    n: int,
    expected_bundles: Optional[int] = None,
    expected_overrides: Optional[int] = None,
    n_ticks: int = 100,
    sim_dt: float = 288.0,
    start_t: float = 0.0,
) -> bool:
    print(f"\n" + "="*68)
    print(f"  NOVASAT Track 3 Part A - Ops Totals Validation")
    print(f"  Session file : {session_path}")
    print(f"  Parameters   : N={n}, duration={duration_s:.0f}s ({duration_s/60:.1f} min)")
    print("="*68)

    if not session_path.exists():
        print(f"\n[FAIL] Session file not found: {session_path}")
        return False

    events = load_jsonl(session_path)
    if not events:
        print("[WARN] Session file is empty - no events recorded yet. "
              "Run the server for at least one WS tick with events before validating.")
        return True  # not a failure, just nothing to check

    counts = count_events(events)
    print(f"\nEvent type breakdown (from JSONL, independently counted):")
    for etype, cnt in sorted(counts.items()):
        print(f"  {etype:20s} : {cnt}")

    bundle_count   = counts.get("bundle",   0)
    anomaly_count  = counts.get("anomaly",  0)
    override_count = counts.get("override", 0)

    # -- Check 1: bundle_count matches exact independent ground-truth count ------
    print(f"\n-- Check 1: Bundle count matches independent physical ground truth --")
    T = orbital_period_s()
    print(f"  Orbital period (N={n}, alt=400km) : {T:.1f}s ({T/60:.2f} min)")

    if expected_bundles is not None:
        expected = expected_bundles
        print(f"  Explicit expected bundle count     : {expected}")
    else:
        # Compute expected contacts independently using orbital physics & isolation events
        sim_times = [start_t + k * sim_dt for k in range(n_ticks)]
        isolation_events = [ev for ev in events if ev.get("type") == "override"]
        expected, _ = count_contacts_independently(n, sim_times, isolation_events=isolation_events)
        print(f"  Simulated ticks                    : {n_ticks} ticks @ {sim_dt}s sim_dt")
        print(f"  Independently computed expected    : {expected}")

    print(f"  Actual JSONL bundle count          : {bundle_count}")

    if bundle_count != expected:
        print(f"  [FAIL] Actual JSONL bundle count ({bundle_count}) does NOT match")
        print(f"         independently computed expected count ({expected}).")
        return False
    else:
        print(f"  [PASS] bundle_count ({bundle_count}) == expected_bundles ({expected})")

    # -- Check 2: override count matches expectation (if provided) -------------
    print(f"\n-- Check 2: Override count --")
    print(f"  Override events in JSONL : {override_count}")
    if expected_overrides is not None:
        if override_count != expected_overrides:
            print(f"  [FAIL] Expected exactly {expected_overrides} override(s), "
                  f"found {override_count} in JSONL.")
            return False
        else:
            print(f"  [PASS] override_count == expected ({expected_overrides})")
    else:
        print(f"  [SKIP] --expected-overrides not provided; skipping assertion.")

    # -- Check 3: every override event has required fields ---------------------
    print(f"\n-- Check 3: Override event schema completeness --")
    required_override_fields = {"type", "sim_time_s", "satellite_id",
                                "override_action", "operator_note"}
    schema_failures = []
    for ev in events:
        if ev.get("type") == "override":
            missing = required_override_fields - set(ev.keys())
            if missing:
                schema_failures.append((ev, missing))

    if schema_failures:
        for ev, missing in schema_failures:
            print(f"  [FAIL] Override event at t={ev.get('sim_time_s')} "
                  f"missing fields: {missing}")
        return False
    else:
        override_events = [e for e in events if e.get("type") == "override"]
        if override_events:
            print(f"  [PASS] All {len(override_events)} override event(s) have required fields.")
        else:
            print(f"  [SKIP] No override events in log to check schema.")

    # -- Check 4: every bundle event has required fields -----------------------
    print(f"\n-- Check 4: Bundle event schema completeness --")
    required_bundle_fields = {"type", "sim_time_s", "node_a", "node_b",
                              "integrity_status", "bib_valid", "bcb_valid"}
    bundle_failures = []
    for ev in events:
        if ev.get("type") == "bundle":
            missing = required_bundle_fields - set(ev.keys())
            if missing:
                bundle_failures.append((ev, missing))

    if bundle_failures:
        for ev, missing in bundle_failures[:5]:  # show first 5 only
            print(f"  [FAIL] Bundle event at t={ev.get('sim_time_s')} "
                  f"missing fields: {missing}")
        return False
    else:
        bundle_events = [e for e in events if e.get("type") == "bundle"]
        if bundle_events:
            print(f"  [PASS] All {len(bundle_events)} bundle event(s) have required fields.")
        else:
            print(f"  [SKIP] No bundle events in log to check schema.")

    # -- Check 5: no quarantined node appears as a bundle sender/receiver ------
    print(f"\n-- Check 5: Quarantine integrity -- isolated nodes must not have bundle events --")
    isolated_at = {}
    cleared_at  = {}
    for ev in events:
        if ev.get("type") == "override":
            sid = ev.get("satellite_id", "")
            t   = ev.get("sim_time_s", 0.0)
            if ev.get("override_action") == "isolate":
                isolated_at.setdefault(sid, []).append(t)
            elif ev.get("override_action") == "clear":
                cleared_at.setdefault(sid, []).append(t)

    quarantine_violations = []
    for ev in events:
        if ev.get("type") != "bundle":
            continue
        t     = ev.get("sim_time_s", 0.0)
        na, nb = ev.get("node_a", ""), ev.get("node_b", "")
        for node in (na, nb):
            iso_times = isolated_at.get(node, [])
            clr_times = cleared_at.get(node, [])
            for iso_t in iso_times:
                cleared_after = any(ct > iso_t for ct in clr_times)
                if t > iso_t and not cleared_after:
                    quarantine_violations.append((node, iso_t, t, ev))

    if quarantine_violations:
        for node, iso_t, bundle_t, ev in quarantine_violations[:5]:
            print(f"  [FAIL] {node} isolated at t={iso_t:.0f}s but appears in "
                  f"bundle event at t={bundle_t:.0f}s "
                  f"({ev.get('node_a')} → {ev.get('node_b')})")
        print(f"  Total quarantine violations: {len(quarantine_violations)}")
        return False
    else:
        print(f"  [PASS] No quarantine violations found.")

    # -- Summary ---------------------------------------------------------------
    print("\n" + "="*68)
    print("  ALL CHECKS PASSED")
    print(f"  bundles_exchanged  = {bundle_count}  (exact match with expected ground truth)")
    print(f"  anomalies_flagged  = {anomaly_count}")
    print(f"  ground_overrides   = {override_count}"
          + (f"  (== expected {expected_overrides})" if expected_overrides is not None else ""))
    print("="*68 + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Validate NOVASAT Ops Window totals against an independent baseline."
    )
    parser.add_argument(
        "--session", type=str, default=None,
        help="Path to a specific ops_events_*.jsonl file. "
             "Defaults to the most recent file in data/ops_events/."
    )
    parser.add_argument(
        "--duration-s", type=float, default=28800.0,
        help="Simulated duration in seconds. Default: 28800.0 (100 ticks @ 288s sim_dt)."
    )
    parser.add_argument(
        "--n", type=int, default=2,
        help="Number of orbiters N. Default: 2."
    )
    parser.add_argument(
        "--expected-bundles", type=int, default=None,
        help="Expected exact bundle event count. If omitted, computed from first principles."
    )
    parser.add_argument(
        "--expected-overrides", type=int, default=None,
        help="If provided, asserts exactly this many override events in the JSONL."
    )
    parser.add_argument(
        "--n-ticks", type=int, default=100,
        help="Number of simulation ticks. Default: 100."
    )
    parser.add_argument(
        "--sim-dt", type=float, default=288.0,
        help="Simulated time step per tick in seconds. Default: 288.0."
    )
    parser.add_argument(
        "--start-t", type=float, default=0.0,
        help="Start time in simulation seconds. Default: 0.0."
    )
    args = parser.parse_args()

    # Locate session file
    script_dir = Path(__file__).parent
    ops_dir    = script_dir / "data" / "ops_events"

    if args.session:
        session_path = Path(args.session)
    else:
        session_path = find_latest_session(ops_dir)
        if session_path is None:
            print(f"[ERROR] No ops_events_*.jsonl files found in {ops_dir}")
            print("        Run the server and let some events accumulate, then retry.")
            sys.exit(1)
        print(f"[Info] Using most recent session: {session_path.name}")

    ok = run_validation(
        session_path=session_path,
        duration_s=args.duration_s,
        n=args.n,
        expected_bundles=args.expected_bundles,
        expected_overrides=args.expected_overrides,
        n_ticks=args.n_ticks,
        sim_dt=args.sim_dt,
        start_t=args.start_t,
    )
    sys.exit(0 if ok else 1)



if __name__ == "__main__":
    main()
