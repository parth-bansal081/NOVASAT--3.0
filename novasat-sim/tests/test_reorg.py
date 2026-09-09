import sys
import math
import numpy as np
sys.path.insert(0, ".")
from server import LiveSimulationEngine
from config import REORG_MANEUVER_DURATION_S, REORG_SAFETY_PC_THRESHOLD

def test_6_1():
    print(" === TEST 6.1 ===")
    engine = LiveSimulationEngine()
    engine.set_n(6)
    # Isolate orbiter_0
    engine.nodes["orbiter_0"].is_isolated = True
    # Advance sim time a bit so positions are defined
    engine.sim_time_s = 100.0
    state = engine.compute_tick_state(run_ml_inference=False)
    # Manually trigger reorg (normally called from WS handler)
    engine._trigger_reorganization("orbiter_0", engine.sim_time_s)
    # Check reorg triggered
    assert engine.reorg_active == True
    assert engine.reorg_safety_check_passed == True
    assert "orbiter_0" in engine.reorg_plan["isolated_id"]
    print(f"  reorg_active={engine.reorg_active}, safety_passed={engine.reorg_safety_check_passed}")
    print(f"  affected_indices={engine.reorg_plan['affected_indices']}")
    print("  PASS: Reorg triggered on isolation")

def test_6_2():
    print(" === TEST 6.2 ===")
    engine = LiveSimulationEngine()
    engine.set_n(6)
    engine.nodes["orbiter_0"].is_isolated = True
    engine.sim_time_s = 100.0
    state = engine.compute_tick_state(run_ml_inference=False)
    engine._trigger_reorganization("orbiter_0", engine.sim_time_s)
    # Advance through maneuver duration
    for i in range(int(REORG_MANEUVER_DURATION_S) + 2):
        engine.sim_time_s += 1.0
        engine.compute_tick_state(run_ml_inference=False)
    assert engine.reorg_active == False
    for idx in engine.reorg_plan.get("affected_indices", []):
        node = engine.nodes[f"orbiter_{idx}"]
        assert node.reorg_state == "settled"
    print(f"  All affected orbiters settled")
    print("  PASS: Reorg maneuver completes")

def test_6_6():
    print(" === TEST 6.6 ===")
    engine = LiveSimulationEngine()
    engine.set_n(6)
    # Inject collision risk by placing two orbiters at same position
    engine.custom_elements[0] = {"altitude_km": 400.0, "inclination_deg": 90.0, "raan_deg": 0.0, "true_anomaly_deg": 0.0}
    engine.custom_elements[1] = {"altitude_km": 400.0, "inclination_deg": 90.0, "raan_deg": 0.0, "true_anomaly_deg": 0.0}
    engine.nodes["orbiter_0"].is_isolated = True
    engine.sim_time_s = 100.0
    state = engine.compute_tick_state(run_ml_inference=False)
    engine._trigger_reorganization("orbiter_0", engine.sim_time_s)
    # Safety check should FAIL because Pc would be 1.0 (same orbit)
    assert engine.reorg_safety_check_passed == False
    assert engine.reorg_active == False
    print(f"  reorg_safety_check_passed={engine.reorg_safety_check_passed}")
    print("  PASS: Safety check blocks reorg when Pc >= threshold")

if __name__ == "__main__":
    test_6_1()
    test_6_2()
    test_6_6()
    print("ALL TESTS PASSED")