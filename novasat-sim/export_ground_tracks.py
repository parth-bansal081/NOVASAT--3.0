"""
export_ground_tracks_standalone.py — Phase 4 ground-track data exporter
========================================================================
Self-contained: uses ONLY numpy, math, json, pandas.
NO hapsira / astropy imports — avoids IERS data download hang.

All physics constants and math are taken directly from config.py and
orbital_mechanics.py — nothing new is computed here; we are just
exposing the same numbers that those modules already produce.

Run from the novasat-sim/ directory:
    .venv\\Scripts\\python.exe export_ground_tracks_standalone.py

Produces:
    web/data/mars_ground_tracks_N{n}.json  for each N in [1,2,4,6,8,10]
"""

import os
import sys
import json
import math
import time
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# All constants taken verbatim from config.py — no imports needed
# ---------------------------------------------------------------------------
R_MARS_KM          = 3389.5          # Mars mean radius, km
MU_MARS_KM3_S2     = 42828.37        # Mars gravitational parameter, km^3/s^2
MARS_SIDEREAL_DAY_S = 88642.663      # Mars sidereal rotation period, s
MARS_OMEGA_RAD_S   = 2 * math.pi / MARS_SIDEREAL_DAY_S  # Mars rotation rate, rad/s
ORBIT_ALTITUDE_KM  = 400.0           # Orbital altitude above surface, km
SEMI_MAJOR_AXIS_KM = R_MARS_KM + ORBIT_ALTITUDE_KM       # a = 3789.5 km
ORBITAL_PERIOD_S   = 2 * math.pi * math.sqrt(SEMI_MAJOR_AXIS_KM**3 / MU_MARS_KM3_S2)
SIM_DURATION_S     = 2592000         # 30 days in seconds
TIME_STEP_S        = 30              # 30-second resolution
N_VALUES           = [1, 2, 4, 6, 8, 10]

ROVER_POSITIONS = {
    "rover_1": {"name": "rover_1", "latitude_deg":  18.4663, "longitude_deg":  77.4298},
    "rover_2": {"name": "rover_2", "latitude_deg":  -4.5895, "longitude_deg": 137.4417},
}

# ---------------------------------------------------------------------------
# Propagation — identical math to orbital_mechanics.propagate_orbiters_positions
# ---------------------------------------------------------------------------

def propagate_orbiters_positions(n: int):
    """
    Analytical circular polar orbit propagation for N evenly-spaced orbiters.
    Returns:
      times          : 1-D float32 array, shape (num_steps,), seconds from t=0
      positions_list : list of N arrays, each shape (num_steps, 3), km MCI frame
    """
    times = np.arange(0, SIM_DURATION_S + TIME_STEP_S, TIME_STEP_S, dtype=np.float64)
    a = SEMI_MAJOR_AXIS_KM
    n_mean = np.sqrt(MU_MARS_KM3_S2 / (a ** 3))   # mean motion, rad/s

    positions_list = []
    for i in range(n):
        nu_0 = i * (2.0 * math.pi / n)
        nu_t = nu_0 + n_mean * times               # true anomaly at each step

        # Polar orbit in XZ plane: x = a*cos(nu), y = 0, z = a*sin(nu)
        x = (a * np.cos(nu_t)).astype(np.float32)
        y = np.zeros_like(x, dtype=np.float32)
        z = (a * np.sin(nu_t)).astype(np.float32)

        positions_list.append(np.stack([x, y, z], axis=1))

    return times, positions_list


# ---------------------------------------------------------------------------
# Sub-satellite point conversion — identical to orbital_mechanics.compute_sub_satellite_points
# ---------------------------------------------------------------------------

def compute_sub_satellite_points(positions, times):
    """
    MCI (x,y,z) → Mars-fixed (lat, lon, alt).
    Derotates by Mars's sidereal spin angle at each timestep.
    """
    x_i = positions[:, 0].astype(np.float64)
    y_i = positions[:, 1].astype(np.float64)
    z_i = positions[:, 2].astype(np.float64)

    theta = MARS_OMEGA_RAD_S * times          # rotation angle of Mars at time t

    x_f =  x_i * np.cos(theta) + y_i * np.sin(theta)
    y_f = -x_i * np.sin(theta) + y_i * np.cos(theta)
    z_f =  z_i

    r    = np.sqrt(x_f**2 + y_f**2 + z_f**2)
    lats = np.degrees(np.arcsin(np.clip(z_f / r, -1.0, 1.0)))
    lons = np.degrees(np.arctan2(y_f, x_f))
    alts = r - R_MARS_KM

    return lats, lons, alts


# ---------------------------------------------------------------------------
# Contact-window loader — reads Phase 1 CSV, no re-simulation
# ---------------------------------------------------------------------------

def load_contact_events(n: int) -> list:
    csv_path = os.path.join(os.path.dirname(__file__), "data", f"contact_windows_N{n}.csv")
    if not os.path.exists(csv_path):
        print(f"  [WARN] {csv_path} not found — contact_events will be empty.")
        return []

    df = pd.read_csv(csv_path)
    rover_df = df[df["link_type"] == "rover_orbiter"]

    events = []
    for _, row in rover_df.iterrows():
        events.append({
            "rover":   str(row["node_a"]),
            "orbiter": str(row["node_b"]),
            "start_s": int(row["window_start_s"]),
            "end_s":   int(row["window_end_s"]),
        })
    return events


# ---------------------------------------------------------------------------
# Per-N export
# ---------------------------------------------------------------------------

def export_n(n: int, out_dir: str) -> None:
    t0 = time.perf_counter()
    print(f"\n[N={n}] Propagating {n} orbiter(s)…")

    times, positions_list = propagate_orbiters_positions(n)
    num_steps = len(times)
    print(f"  Propagation done: {num_steps:,} steps  ({time.perf_counter()-t0:.2f}s)")

    # Convert each orbiter XYZ → lat/lon/alt
    orbiter_data = []
    for i, pos in enumerate(positions_list):
        lats, lons, alts = compute_sub_satellite_points(pos, times)

        track       = [[round(float(lats[k]), 4), round(float(lons[k]), 4)]
                       for k in range(num_steps)]
        altitude_km = [round(float(alts[k]), 2) for k in range(num_steps)]

        orbiter_data.append({
            "name":        f"orbiter_{i}",
            "track":       track,
            "altitude_km": altitude_km,
        })

    print(f"  Ground-tracks computed  ({time.perf_counter()-t0:.2f}s)")

    # Rover records (static positions)
    rover_records = {
        r_id: {
            "name":          info["name"],
            "location_name": "Jezero Crater" if r_id == "rover_1" else "Gale Crater",
            "latitude_deg":  info["latitude_deg"],
            "longitude_deg": info["longitude_deg"],
        }
        for r_id, info in ROVER_POSITIONS.items()
    }

    # Contact events from existing Phase 1 CSVs
    contact_events = load_contact_events(n)
    print(f"  Loaded {len(contact_events)} rover↔orbiter contact windows.")

    # Timestamps as plain int list
    timestamps = [int(t) for t in times]

    payload = {
        "metadata": {
            "constellation_N":    n,
            "sim_duration_s":     SIM_DURATION_S,
            "time_step_s":        TIME_STEP_S,
            "num_steps":          num_steps,
            "timestamps":         timestamps,
            "orbital_period_s":   round(ORBITAL_PERIOD_S, 2),
            "orbital_period_min": round(ORBITAL_PERIOD_S / 60.0, 2),
        },
        "rovers":         rover_records,
        "orbiters":       orbiter_data,
        "contact_events": contact_events,
    }

    out_path = os.path.join(out_dir, f"mars_ground_tracks_N{n}.json")
    print(f"  Writing JSON…")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"  ✓ {out_path}  ({size_mb:.1f} MB, total {time.perf_counter()-t0:.1f}s)")


# ---------------------------------------------------------------------------
# Spot-checks on N=1 output
# ---------------------------------------------------------------------------

def validate(out_dir: str) -> None:
    print("\n--- Spot-checks (N=1) ---")
    path = os.path.join(out_dir, "mars_ground_tracks_N1.json")
    with open(path, "r") as f:
        d = json.load(f)

    checks = [
        ("rover_1 lat/lon",  d["rovers"]["rover_1"]["latitude_deg"]  ==  18.4663
                         and d["rovers"]["rover_1"]["longitude_deg"] ==  77.4298),
        ("rover_2 lat/lon",  d["rovers"]["rover_2"]["latitude_deg"]  == -4.5895
                         and d["rovers"]["rover_2"]["longitude_deg"] == 137.4417),
        ("orbiter_0@t=0 near (0,0)", abs(d["orbiters"][0]["track"][0][0]) < 1.0
                                  and abs(d["orbiters"][0]["track"][0][1]) < 1.0),
        ("num_steps",        d["metadata"]["num_steps"] == SIM_DURATION_S // TIME_STEP_S + 1),
        ("contact_events>0", len(d["contact_events"]) > 0),
        ("period≈118min",    abs(d["metadata"]["orbital_period_min"] - 118) < 2),
    ]

    all_pass = True
    for label, ok in checks:
        print(f"  {'PASS ✓' if ok else 'FAIL ✗'}  {label}")
        if not ok:
            all_pass = False

    print(f"\n  {'ALL CHECKS PASSED ✓' if all_pass else 'SOME CHECKS FAILED ✗'}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "web", "data")
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 60)
    print("  NOVASAT Phase 4 — Standalone Ground-Track Exporter")
    print(f"  Output: {out_dir}")
    print(f"  Orbital period: {ORBITAL_PERIOD_S/60:.2f} min")
    print("=" * 60)

    t_total = time.perf_counter()
    for n in N_VALUES:
        export_n(n, out_dir)

    validate(out_dir)

    print(f"\nAll done in {time.perf_counter()-t_total:.1f}s total.")
    print("Start web server:  python -m http.server 8080  (from web/ directory)")
