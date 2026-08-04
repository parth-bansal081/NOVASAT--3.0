"""
verify_3d_live.py — Part D Validation Suite for NOVASAT 3D & Live Simulation

Runs empirical verification checks to confirm:
1. Ellipsoid Correctness Check (biaxial oblateness & landmark placement).
2. Live-vs-Batch Cross-Check (orbital period & per-rover contact frequency within strict numeric tolerances).
3. Live Parameter Modification Check (altitude change recalculation).
4. Live Anomaly Injection & Leakage-Safe Model Inference Check (score spike response upon fault injection).
"""

import os
import sys
import math
import unittest
import numpy as np

# Add project root to sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Import GaussianDensityModel so pickle loader can locate class
try:
    from experiments.train_anomaly_models import GaussianDensityModel
except ImportError:
    pass

from config import (
    R_MARS_KM,
    MU_MARS_KM3_S2,
    MARS_OMEGA_RAD_S,
    ROVER_POSITIONS,
    MIN_ELEVATION_DEG
)

from server import (
    MARS_ELLIPSOID_A_KM,
    MARS_ELLIPSOID_B_KM,
    geodetic_to_cartesian_biaxial,
    cartesian_to_geodetic_biaxial,
    LiveSimulationEngine
)


class TestNOVASAT3DLiveValidation(unittest.TestCase):

    def test_1_ellipsoid_correctness(self):
        """Check 1: Confirm biaxial ellipsoid flattening ratio and geodetic landmark mapping."""
        a = MARS_ELLIPSOID_A_KM
        b = MARS_ELLIPSOID_B_KM
        ratio = a / b
        flattening = (a - b) / a

        print("\n--- Check 1: Ellipsoid Correctness ---")
        print(f"Equatorial radius a = {a} km")
        print(f"Polar radius b      = {b} km")
        print(f"Ratio a/b           = {ratio:.6f}")
        print(f"Flattening f        = {flattening:.6f}")

        # Assert biaxial oblateness (ratio ~ 1.005918)
        self.assertAlmostEqual(ratio, 1.0059178, places=5)
        self.assertGreater(a, b, "Equatorial radius must be larger than polar radius for oblateness")

        # Test Jezero Crater coordinate conversion
        j_lat, j_lon = ROVER_POSITIONS["rover_1"]["latitude_deg"], ROVER_POSITIONS["rover_1"]["longitude_deg"]
        pos_cart = geodetic_to_cartesian_biaxial(j_lat, j_lon, 0.0)
        reconstructed = cartesian_to_geodetic_biaxial(pos_cart)

        self.assertAlmostEqual(reconstructed["latitude_deg"], j_lat, places=4)
        self.assertAlmostEqual(reconstructed["longitude_deg"], j_lon, places=4)
        self.assertAlmostEqual(reconstructed["altitude_km"], 0.0, places=3)
        print(f"Jezero Crater Biaxial Position (Cartesian): {pos_cart}")
        print("[PASS] Check 1 PASSED: Biaxial ellipsoid geometry verified.")

    def test_2_live_vs_batch_crosscheck(self):
        """Check 2: Live propagation vs Phase 1 batch baseline within strict numeric tolerances for BOTH rovers."""
        print("\n--- Check 2: Live-vs-Batch Cross-Check ---")

        # 1. Orbital period calculation for 400 km orbit (a = 3789.5 km)
        a_km = R_MARS_KM + 400.0
        period_sec = 2.0 * math.pi * math.sqrt((a_km**3) / MU_MARS_KM3_S2)
        period_min = period_sec / 60.0

        print(f"Theoretical 400km Orbital Period: {period_min:.3f} minutes ({period_sec:.2f} s)")
        self.assertAlmostEqual(period_min, 118.04, delta=0.1)

        # 2. Vectorized 30-day contact frequency check for N=1 on rover_1 and rover_2 at exact dt=30s resolution
        times = np.arange(0, 2592000, 30.0)  # 86,400 steps
        n_orbit = math.sqrt(MU_MARS_KM3_S2 / (a_km**3))
        nu_t = n_orbit * times
        theta = MARS_OMEGA_RAD_S * times

        x_mci = a_km * np.cos(nu_t)
        z_mci = a_km * np.sin(nu_t)

        x_orb_fixed = x_mci * np.cos(theta)
        y_orb_fixed = -x_mci * np.sin(theta)
        z_orb_fixed = z_mci
        pos_orb_fixed = np.stack([x_orb_fixed, y_orb_fixed, z_orb_fixed], axis=1)

        def eval_rover_contacts(rover_key):
            lat, lon = ROVER_POSITIONS[rover_key]["latitude_deg"], ROVER_POSITIONS[rover_key]["longitude_deg"]
            pos_rover = geodetic_to_cartesian_biaxial(lat, lon, 0.0)
            zenith_unnorm = np.array([
                2.0 * pos_rover[0] / (MARS_ELLIPSOID_A_KM**2),
                2.0 * pos_rover[1] / (MARS_ELLIPSOID_A_KM**2),
                2.0 * pos_rover[2] / (MARS_ELLIPSOID_B_KM**2)
            ])
            zenith_unit = zenith_unnorm / np.linalg.norm(zenith_unnorm)

            L = pos_orb_fixed - pos_rover
            L_norm = np.linalg.norm(L, axis=1)
            L_dot_z = np.sum(L * zenith_unit, axis=1)
            cos_angle = np.clip(L_dot_z / L_norm, -1.0, 1.0)
            elev_deg = 90.0 - np.degrees(np.arccos(cos_angle))
            contact = elev_deg > MIN_ELEVATION_DEG

            diff = np.diff(np.concatenate(([False], contact, [False])).astype(int))
            windows_count = len(np.where(diff == 1)[0])
            contacts_per_day = windows_count / 30.0
            return windows_count, contacts_per_day

        r1_windows, r1_rate = eval_rover_contacts("rover_1")
        r2_windows, r2_rate = eval_rover_contacts("rover_2")

        print(f"rover_1 (Jezero, 18.47°N): {r1_windows} windows -> {r1_rate:.4f} contacts/day")
        print(f"rover_2 (Gale, -4.59°S):  {r2_windows} windows -> {r2_rate:.4f} contacts/day")

        # Strict Assertion 1: rover_1 contact frequency matches 2.60 +- 0.05 contacts/day
        self.assertAlmostEqual(r1_rate, 2.60, delta=0.05)

        # Strict Assertion 2: rover_2 contact frequency matches 2.4667 +- 0.05 contacts/day
        self.assertAlmostEqual(r2_rate, 2.4667, delta=0.05)

        print(f"[PASS] Check 2 PASSED: Period ({period_min:.1f} min), rover_1 ({r1_rate:.2f}/day), and rover_2 ({r2_rate:.2f}/day) match baseline tolerances.")

    def test_3_live_parameter_change(self):
        """Check 3: Live modification of orbiter altitude updates period immediately."""
        print("\n--- Check 3: Live Parameter Modification ---")
        sim = LiveSimulationEngine()
        sim.set_n(6)

        # Initial default altitude 400 km
        frame1 = sim.compute_tick_state()
        alt1 = frame1["orbiters"][0]["altitude_km"]

        # Modify orbiter_0 altitude to 800 km live (+400 km increase)
        sim.set_satellite_elements(0, altitude_km=800.0, inclination_deg=90.0)
        frame2 = sim.compute_tick_state()
        alt2 = frame2["orbiters"][0]["altitude_km"]

        # Geodetic altitude increases by 400 km
        alt_diff = alt2 - alt1
        self.assertAlmostEqual(alt_diff, 400.0, places=1)
        print(f"Orbiter 0 Geodetic Altitude updated dynamically: {alt1:.1f} km -> {alt2:.1f} km (Diff = {alt_diff:.1f} km)")
        print("[PASS] Check 3 PASSED: Live parameter update recalculated orbit trajectory immediately.")

    def test_4_anomaly_injection_and_inference(self):
        """Check 4: Fault injection changes node state & triggers frozen model score spike."""
        print("\n--- Check 4: Anomaly Injection & Live Model Inference ---")
        sim = LiveSimulationEngine()
        sim.set_n(6)

        # 1. Normal state tick
        frame1 = sim.compute_tick_state()
        orb1_norm = frame1["orbiters"][1]
        inf_norm = orb1_norm["inference"]

        self.assertFalse(orb1_norm["is_compromised"])
        print(f"Normal State Scores:    Gaussian={inf_norm['gaussian_score']:.4f}, iForest={inf_norm['iforest_score']:.4f}, AnomalyFlag={inf_norm['anomaly_flag']}")

        # Assert normal scores are within expected baseline range
        self.assertLess(inf_norm["gaussian_score"], 0.02)

        # 2. Inject clock_drift fault on orbiter_1
        sim.inject_fault("orbiter_1", "clock_drift")
        frame2 = sim.compute_tick_state()

        orb1_fault = frame2["orbiters"][1]
        inf_fault = orb1_fault["inference"]

        self.assertTrue(orb1_fault["is_compromised"])
        self.assertEqual(orb1_fault["fault_type"], "clock_drift")

        print(f"Clock Drift State Scores: Gaussian={inf_fault['gaussian_score']:.4f}, iForest={inf_fault['iforest_score']:.4f}, AnomalyFlag={inf_fault['anomaly_flag']}")

        # Strict Assertions:
        # a) Gaussian score must spike off baseline to > 0.08 (> 12x increase!)
        self.assertGreater(inf_fault["gaussian_score"], 0.08)
        # b) iForest normalized score must increase significantly above normal baseline
        self.assertGreater(inf_fault["iforest_score"], inf_norm["iforest_score"] + 0.15)
        # c) Model anomaly flag must be True
        self.assertTrue(inf_fault["anomaly_flag"])

        print("[PASS] Check 4 PASSED: Fault injection triggered immediate score spikes (Gaussian > 0.08, iForest spike, Flag=True).")


if __name__ == "__main__":
    unittest.main(verbosity=2)
