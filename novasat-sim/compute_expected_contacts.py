"""
compute_expected_contacts.py
============================
Standalone independent contact-window counter.

This script is the GROUND TRUTH generator for validate_ops_totals.py Check 1.

It computes expected bundle events by independently stepping through orbital
mechanics -- NEVER touching compute_tick_state(), process_bpsec_for_contact(),
or ops_window_totals. It uses the exact same physics equations as server.py
but as a second, separate implementation in a second loop.

The result is the tight expected count that Check 1 should assert exactly against,
replacing the meaningless physical-ceiling check.

Scenario (deterministic):
  N = 2 orbiters, alt = 400 km, inc = 90 deg, RAAN = 0 deg
  orbiter_0: nu0 =   0 deg  (i * 360 / N, i=0)
  orbiter_1: nu0 = 180 deg  (i * 360 / N, i=1)
  Rovers: rover_1 (18.4663 N, 77.4298 E), rover_2 (-4.5895 S, 137.4417 E)
  Tick interval: SIM_DT = 288.0 s  (wall 0.08s * 3600x speed)
  N_TICKS: configurable (default 100)
  Start time: 0.0 s

Usage:
  python compute_expected_contacts.py [--n-ticks 100] [--verbose]
"""

import math
import sys
import argparse
import numpy as np

# Physical constants (must match server.py / config.py exactly)
R_MARS_KM        = 3389.5
MU_MARS_KM3_S2   = 42828.37
MARS_SIDEREAL_S  = 88642.663
MARS_OMEGA_RAD_S = 2.0 * math.pi / MARS_SIDEREAL_S

MARS_A_KM        = 3396.19   # biaxial equatorial radius (matches server.py MARS_ELLIPSOID_A_KM)
MARS_B_KM        = 3376.20   # biaxial polar radius     (matches server.py MARS_ELLIPSOID_B_KM)
MIN_ELEV_DEG     = 10.0      # from config.MIN_ELEVATION_DEG
ALT_KM           = 400.0
INC_DEG          = 90.0
RAAN_DEG         = 0.0

# Rover geodetic positions (from config.ROVER_POSITIONS)
ROVERS_GEO = [
    (18.4663,  77.4298),   # rover_1: (lat_deg, lon_deg)
    (-4.5895, 137.4417),   # rover_2
]


def orbital_period_s(alt_km: float = 400.0) -> float:
    """Keplerian orbital period in seconds for a circular Mars orbit at alt_km."""
    a = R_MARS_KM + alt_km
    return 2.0 * math.pi * math.sqrt(a**3 / MU_MARS_KM3_S2)


# Geometry helpers (same formulae as server.py, independent implementation)

def geodetic_to_cartesian(lat_deg, lon_deg, alt_km=0.0):
    """Biaxial ellipsoid geodetic -> Mars-fixed Cartesian (km)."""
    phi = math.radians(lat_deg)
    lam = math.radians(lon_deg)
    e2  = 1.0 - (MARS_B_KM**2 / MARS_A_KM**2)
    N   = MARS_A_KM / math.sqrt(1.0 - e2 * math.sin(phi)**2)
    x   = (N + alt_km) * math.cos(phi) * math.cos(lam)
    y   = (N + alt_km) * math.cos(phi) * math.sin(lam)
    z   = (N * (1.0 - e2) + alt_km) * math.sin(phi)
    return np.array([x, y, z])


def biaxial_occluded(pa, pb):
    """
    True if segment pa->pb passes through Mars ellipsoid interior.
    Identical algorithm to server.py check_biaxial_occlusion().
    """
    p1 = np.array([pa[0]/MARS_A_KM, pa[1]/MARS_A_KM, pa[2]/MARS_B_KM])
    p2 = np.array([pb[0]/MARS_A_KM, pb[1]/MARS_A_KM, pb[2]/MARS_B_KM])
    d  = p2 - p1
    d2 = float(np.dot(d, d))
    if d2 < 1e-12:
        return float(np.dot(p1, p1)) < 0.9999
    t  = -np.dot(p1, d) / d2
    tc = max(1e-4, min(1.0 - 1e-4, t))
    pc = p1 + tc * d
    return float(np.dot(pc, pc)) < 0.9999


def zenith_unit(rover_cart):
    """Surface zenith unit vector at rover position on biaxial ellipsoid."""
    x, y, z = rover_cart
    unnorm = np.array([
        2.0 * x / MARS_A_KM**2,
        2.0 * y / MARS_A_KM**2,
        2.0 * z / MARS_B_KM**2,
    ])
    return unnorm / np.linalg.norm(unnorm)


def orbiter_position_mf(i, n, t_sec):
    """
    Mars-fixed Cartesian position (km) for orbiter i at sim time t_sec.
    Exactly replicates server.py compute_tick_state() Keplerian propagation.
    """
    nu0_deg  = i * (360.0 / n)
    a        = R_MARS_KM + ALT_KM
    n_mean   = math.sqrt(MU_MARS_KM3_S2 / a**3)
    nu_rad   = math.radians(nu0_deg) + n_mean * t_sec
    theta    = MARS_OMEGA_RAD_S * t_sec

    inc_rad  = math.radians(INC_DEG)
    raan_rad = math.radians(RAAN_DEG)

    cos_u = math.cos(nu_rad); sin_u = math.sin(nu_rad)
    cos_O = math.cos(raan_rad); sin_O = math.sin(raan_rad)
    cos_i = math.cos(inc_rad)

    x_mci = a * (cos_u*cos_O - sin_u*sin_O*cos_i)
    y_mci = a * (cos_u*sin_O + sin_u*cos_O*cos_i)
    z_mci = a * (sin_u * math.sin(inc_rad))

    x_mf =  x_mci * math.cos(theta) + y_mci * math.sin(theta)
    y_mf = -x_mci * math.sin(theta) + y_mci * math.cos(theta)
    z_mf =  z_mci

    return np.array([x_mf, y_mf, z_mf])


def rover_orbiter_in_contact(r_cart, r_zenith, orb_cart):
    """
    True if rover can communicate with orb_cart:
      1. Elevation angle >= MIN_ELEV_DEG
      2. LOS not occluded by Mars biaxial ellipsoid
    Replicates server.py compute_tick_state() contact detection exactly.
    """
    los_vec  = orb_cart - r_cart
    dist     = np.linalg.norm(los_vec)
    if dist < 1e-6:
        return False
    los_unit = los_vec / dist
    cos_z    = float(np.clip(np.dot(los_unit, r_zenith), -1.0, 1.0))
    elev_deg = 90.0 - math.degrees(math.acos(cos_z))
    if elev_deg < MIN_ELEV_DEG:
        return False
    return not biaxial_occluded(r_cart, orb_cart)


def is_node_isolated_at(node_id: str, t: float, isolation_events: list = None) -> bool:
    """True if node_id is under an active ground isolate override at sim time t."""
    if not isolation_events:
        return False
    isolated = False
    for ev in isolation_events:
        if ev.get("satellite_id") == node_id and ev.get("sim_time_s", 0.0) <= t:
            action = ev.get("override_action")
            if action == "isolate":
                isolated = True
            elif action == "clear":
                isolated = False
    return isolated


def count_contacts_independently(n, sim_times, isolation_events: list = None):
    """
    Independent contact counter.
    Steps through sim_times, computing positions from first principles,
    checking contacts using geometry helpers, and filtering out contacts
    involving isolated nodes.

    Returns:
      total_contacts (int): expected bundle exchanges
      per_tick (list):      list of dicts with t, rover_orb, orb_orb counts
    """
    rover_carts   = [geodetic_to_cartesian(*geo) for geo in ROVERS_GEO]
    rover_zeniths = [zenith_unit(rc) for rc in rover_carts]

    total    = 0
    per_tick = []
    for t in sim_times:
        orb_positions = [orbiter_position_mf(i, n, t) for i in range(n)]

        rover_orb = 0
        for k, (rc, rz) in enumerate(zip(rover_carts, rover_zeniths)):
            rover_id = f"rover_{k+1}"
            if is_node_isolated_at(rover_id, t, isolation_events):
                continue
            for i, op in enumerate(orb_positions):
                orbiter_id = f"orbiter_{i}"
                if is_node_isolated_at(orbiter_id, t, isolation_events):
                    continue
                if rover_orbiter_in_contact(rc, rz, op):
                    rover_orb += 1

        orb_orb = 0
        for i in range(n):
            orb_i_id = f"orbiter_{i}"
            if is_node_isolated_at(orb_i_id, t, isolation_events):
                continue
            j = (i + 1) % n
            orb_j_id = f"orbiter_{j}"
            if is_node_isolated_at(orb_j_id, t, isolation_events):
                continue
            if not biaxial_occluded(orb_positions[i], orb_positions[j]):
                orb_orb += 1

        tick_total = rover_orb + orb_orb
        total     += tick_total
        per_tick.append({'t': t, 'rover_orb': rover_orb, 'orb_orb': orb_orb})

    return total, per_tick


def main():
    parser = argparse.ArgumentParser(
        description="Independently compute expected bundle-exchange count for a deterministic scenario."
    )
    parser.add_argument("--n",       type=int,   default=2,
                        help="Number of orbiters (default: 2)")
    parser.add_argument("--n-ticks", type=int,   default=100,
                        help="Number of simulation ticks (default: 100)")
    parser.add_argument("--sim-dt",  type=float, default=288.0,
                        help="Simulated time step per tick in seconds "
                             "(default: 288.0 = 0.08s wall * 3600x)")
    parser.add_argument("--start-t", type=float, default=0.0,
                        help="Simulation start time in seconds (default: 0.0)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-tick breakdown for active ticks")
    args = parser.parse_args()

    sim_times   = [args.start_t + k * args.sim_dt for k in range(args.n_ticks)]
    total_sim_s = args.n_ticks * args.sim_dt

    print("=" * 68)
    print("  Independent Contact-Window Counter")
    print(f"  N={args.n}, alt={ALT_KM}km, inc={INC_DEG}deg, raan={RAAN_DEG}deg")
    print(f"  Ticks={args.n_ticks}, sim_dt={args.sim_dt}s, "
          f"total_sim={total_sim_s:.0f}s ({total_sim_s/3600:.2f} hr)")
    for i in range(args.n):
        print(f"  orbiter_{i}: nu0={i*(360.0/args.n):.0f}deg")
    print("=" * 68)

    total, per_tick = count_contacts_independently(args.n, sim_times)

    active_ticks = [pt for pt in per_tick if pt['rover_orb'] + pt['orb_orb'] > 0]
    ro_total     = sum(pt['rover_orb'] for pt in per_tick)
    oo_total     = sum(pt['orb_orb']   for pt in per_tick)

    print(f"\nResults:")
    print(f"  Ticks with >= 1 contact    : {len(active_ticks)} / {args.n_ticks}")
    print(f"  Rover-Orbiter contact events: {ro_total}")
    print(f"  Orbiter-Orbiter contact events: {oo_total}")
    print(f"  TOTAL expected bundle events: {total}")
    print()
    print("Command to use this as ground truth in validator:")
    print(f"  python validate_ops_totals.py \\")
    print(f"    --session <session_file> \\")
    print(f"    --n {args.n} --n-ticks {args.n_ticks} --sim-dt {args.sim_dt} \\")
    print(f"    --expected-bundles {total} --expected-overrides <N>")

    if args.verbose and active_ticks:
        print(f"\nPer-tick (active ticks only, {len(active_ticks)} shown):")
        print(f"  {'t_sim_s':>10}  {'rover_orb':>10}  {'orb_orb':>8}  {'total':>6}")
        for pt in active_ticks:
            tot = pt['rover_orb'] + pt['orb_orb']
            print(f"  {pt['t']:10.0f}  {pt['rover_orb']:10d}  {pt['orb_orb']:8d}  {tot:6d}")


if __name__ == "__main__":
    main()
