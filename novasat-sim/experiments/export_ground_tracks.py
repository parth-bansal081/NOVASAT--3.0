"""
export_ground_tracks.py

Exports 3D orbiter positions as sub-satellite ground tracks (lat, lon, alt)
and rover locations into JSON format for Leaflet.js Mars Trek visualization.

Reuses existing Phase 1 physics and contact window calculations without modifying any simulation logic.
"""

import json
import os
import sys
import numpy as np

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
for p in [ROOT_DIR, SRC_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from config import SIM_DURATION_S, TIME_STEP_S, ROVER_POSITIONS, N_VALUES, R_MARS_KM
from constellation import build_constellation
from orbital_mechanics import propagate_orbiters_positions, compute_sub_satellite_points
from contact_windows import compute_rover_orbiter_contacts


def export_ground_tracks(n: int = 6, sim_duration_s: int = SIM_DURATION_S, time_step_s: int = TIME_STEP_S, out_dir: str = None):
    """
    Generates and saves the ground track trace JSON for constellation size N.
    """
    if out_dir is None:
        out_dir = os.path.join(ROOT_DIR, "data")
    os.makedirs(out_dir, exist_ok=True)

    print(f"--- Exporting Orbiter Ground Tracks (N={n}, duration={sim_duration_s}s, step={time_step_s}s) ---")
    orbiters, rovers = build_constellation(n)
    times, positions_list = propagate_orbiters_positions(orbiters, sim_duration_s, time_step_s)

    # Convert rover positions
    rover_positions = {}
    for r in rovers:
        pos_r = r.get_positions(times)
        rover_positions[r.name] = {
            "latitude_deg": float(r.latitude_deg),
            "longitude_deg": float(r.longitude_deg),
            "pos_inertial": pos_r,  # (num_steps, 3)
        }

    orbiter_data = []
    contact_events = []

    for idx, pos_orb in enumerate(positions_list):
        orbiter_name = f"orbiter_{idx}"
        lats, lons, alts = compute_sub_satellite_points(pos_orb, times)

        # Calculate contacts with rovers
        r1_pos = rover_positions["rover_1"]["pos_inertial"]
        r2_pos = rover_positions["rover_2"]["pos_inertial"]

        c1_windows = compute_rover_orbiter_contacts(r1_pos, pos_orb, times)
        c2_windows = compute_rover_orbiter_contacts(r2_pos, pos_orb, times)

        for start_s, end_s in c1_windows:
            contact_events.append({
                "orbiter": orbiter_name,
                "rover": "rover_1",
                "start_s": start_s,
                "end_s": end_s,
                "duration_s": end_s - start_s,
            })
        for start_s, end_s in c2_windows:
            contact_events.append({
                "orbiter": orbiter_name,
                "rover": "rover_2",
                "start_s": start_s,
                "end_s": end_s,
                "duration_s": end_s - start_s,
            })

        # Vectorized compact lat/lon arrays (~6m resolution on Mars)
        track_arr = np.column_stack([lats, lons]).round(4)
        lat_lon_track = track_arr.tolist()

        alt_arr = alts.round(2)
        alt_list = alt_arr.tolist()

        orbiter_data.append({
            "name": orbiter_name,
            "id": idx,
            "track": lat_lon_track,
            "altitude_km": alt_list,
        })

    # Prepare payload
    payload = {
        "metadata": {
            "constellation_N": n,
            "sim_duration_s": sim_duration_s,
            "time_step_s": time_step_s,
            "num_steps": len(times),
            "timestamps": [int(t) for t in times],
        },
        "rovers": {
            "rover_1": {
                "name": "rover_1",
                "location_name": "Jezero Crater",
                "latitude_deg": float(ROVER_POSITIONS["rover_1"]["latitude_deg"]),
                "longitude_deg": float(ROVER_POSITIONS["rover_1"]["longitude_deg"]),
            },
            "rover_2": {
                "name": "rover_2",
                "location_name": "Gale Crater",
                "latitude_deg": float(ROVER_POSITIONS["rover_2"]["latitude_deg"]),
                "longitude_deg": float(ROVER_POSITIONS["rover_2"]["longitude_deg"]),
            },
        },
        "orbiters": orbiter_data,
        "contact_events": contact_events,
    }

    out_file = os.path.join(out_dir, f"mars_ground_tracks_N{n}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(',', ':'))

    # Also copy into web/data directory for browser consumption
    web_dir = os.path.join(ROOT_DIR, "web", "data")
    os.makedirs(web_dir, exist_ok=True)
    web_file = os.path.join(web_dir, f"mars_ground_tracks_N{n}.json")
    with open(web_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(',', ':'))

    # Default fallback file for web app
    default_web_file = os.path.join(web_dir, "mars_ground_tracks.json")
    with open(default_web_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(',', ':'))

    print(f"✓ Saved ground tracks to: {out_file}")
    print(f"✓ Saved web payload to: {web_file} and {default_web_file}")
    print(f"  Total steps: {len(times):,}, Total contact events: {len(contact_events)}")
    return payload


if __name__ == "__main__":
    export_ground_tracks(n=6)
