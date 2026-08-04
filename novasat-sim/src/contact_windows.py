import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import numpy as np
import pandas as pd
from config import (
    R_MARS_KM,
    MIN_ELEVATION_DEG,
    EARTH_DIRECTION_VECTOR,
    SIM_DURATION_S,
    TIME_STEP_S,
    N_VALUES
)
from constellation import build_constellation
from orbital_mechanics import propagate_orbiters_positions

def find_contact_windows_np(contact_array, time_array):
    """
    Finds contiguous runs of True in a boolean contact array.
    Returns a list of tuples (start_s, end_s) representing window bounds.
    """
    if not np.any(contact_array):
        return []
    
    # Pad with False on both ends to capture transitions at boundaries
    padded = np.concatenate(([False], contact_array, [False]))
    diff = np.diff(padded.astype(int))
    
    # Rising edge (False -> True)
    starts = np.where(diff == 1)[0]
    # Falling edge (True -> False)
    ends = np.where(diff == -1)[0] - 1
    
    windows = []
    for s, e in zip(starts, ends):
        windows.append((int(time_array[s]), int(time_array[e])))
    return windows

def compute_rover_orbiter_contacts(pos_rover, pos_orbiter, time_array):
    """
    Computes Rover-to-Orbiter elevation angles and returns contact windows.
    - pos_rover: (num_steps, 3) positions of rover in km
    - pos_orbiter: (num_steps, 3) positions of orbiter in km
    - time_array: (num_steps,) time array in seconds
    """
    # Line of sight vector
    L = pos_orbiter - pos_rover  # (num_steps, 3)
    
    # Local zenith at rover (Mars is modeled as a perfect sphere)
    zenith = pos_rover / R_MARS_KM  # (num_steps, 3)
    
    # Dot product and magnitudes
    L_dot_zenith = np.sum(L * zenith, axis=1)  # (num_steps,)
    L_norm = np.linalg.norm(L, axis=1)  # (num_steps,)
    
    # Cosine of angle between zenith and line of sight
    cos_angle = np.clip(L_dot_zenith / L_norm, -1.0, 1.0)
    angle_rad = np.arccos(cos_angle)
    
    # Elevation is 90 - angle in degrees
    elevation_deg = 90.0 - np.degrees(angle_rad)
    
    contact = elevation_deg > MIN_ELEVATION_DEG
    return find_contact_windows_np(contact, time_array)

def compute_orbiter_orbiter_contacts(pos_orb_a, pos_orb_b, time_array):
    """
    Computes Orbiter-to-Orbiter crosslink and returns contact windows.
    - pos_orb_a: (num_steps, 3) positions of orbiter A in km
    - pos_orb_b: (num_steps, 3) positions of orbiter B in km
    - time_array: (num_steps,) time array in seconds
    """
    # Vector from A to B
    D = pos_orb_b - pos_orb_a  # (num_steps, 3)
    D_dot_D = np.sum(D * D, axis=1)  # (num_steps,)
    
    # Calculate parameter t for closest approach to origin [0, 0, 0]
    pos_a_dot_D = np.sum(pos_orb_a * D, axis=1)
    
    # Avoid division by zero if orbiters are somehow co-located
    with np.errstate(divide='ignore', invalid='ignore'):
        t = -pos_a_dot_D / D_dot_D
    t = np.nan_to_num(t, nan=0.0)
    t = np.clip(t, 0.0, 1.0)
    
    # Closest point on line segment
    pos_close = pos_orb_a + t[:, np.newaxis] * D
    dist = np.linalg.norm(pos_close, axis=1)
    
    # Blocked by Mars if closest distance is less than Mars radius
    blocked = dist < R_MARS_KM
    contact = ~blocked
    
    return find_contact_windows_np(contact, time_array)

def compute_orbiter_earth_contacts(pos_orbiter, time_array):
    """
    Computes Orbiter-to-Earth link and returns contact windows.
    Uses the fixed EARTH_DIRECTION_VECTOR simplification.
    - pos_orbiter: (num_steps, 3) positions of orbiter in km
    - time_array: (num_steps,) time array in seconds
    """
    # Earth unit direction vector
    U = EARTH_DIRECTION_VECTOR
    
    # Projection along the Earth direction
    p_dot_u = np.dot(pos_orbiter, U)  # (num_steps,)
    
    # Norm squared of orbiter position
    pos_norm_sq = np.sum(pos_orbiter * pos_orbiter, axis=1)  # (num_steps,)
    
    # Minimum distance squared along the ray
    dist_sq = pos_norm_sq - p_dot_u**2
    
    # Blocked by Mars if pointing back/through Mars (p_dot_u < 0) 
    # and the perpendicular distance is less than Mars radius
    blocked = (p_dot_u < 0) & (dist_sq < R_MARS_KM**2)
    contact = ~blocked
    
    return find_contact_windows_np(contact, time_array)

def run_simulation_for_n(n):
    """
    Runs the communication window simulation for a given satellite count N.
    Returns a list of dictionaries with link data.
    """
    print(f"Running simulation for N = {n} orbiters...")
    orbiters, rovers = build_constellation(n)
    times, orb_positions = propagate_orbiters_positions(orbiters, SIM_DURATION_S, TIME_STEP_S)
    
    # Pre-calculate rover positions
    rover_positions = [rover.get_positions(times) for rover in rovers]
    
    results = []
    
    # 8a. Rover ↔ Orbiter links
    for r_idx, rover in enumerate(rovers):
        for o_idx in range(n):
            windows = compute_rover_orbiter_contacts(
                rover_positions[r_idx],
                orb_positions[o_idx],
                times
            )
            for w_start, w_end in windows:
                results.append({
                    "link_type": "rover_orbiter",
                    "node_a": rover.name,
                    "node_b": f"orbiter_{o_idx}",
                    "window_start_s": w_start,
                    "window_end_s": w_end
                })
                
    # 8b. Orbiter ↔ Orbiter (crosslinks)
    # Only check adjacent pairs in true anomaly: (i, i-1) and (i, i+1)
    if n >= 2:
        adjacent_pairs = set()
        for i in range(n):
            j = (i + 1) % n
            # Store sorted to ensure uniqueness
            adjacent_pairs.add((min(i, j), max(i, j)))
            
        for i, j in sorted(adjacent_pairs):
            windows = compute_orbiter_orbiter_contacts(
                orb_positions[i],
                orb_positions[j],
                times
            )
            for w_start, w_end in windows:
                results.append({
                    "link_type": "orbiter_orbiter",
                    "node_a": f"orbiter_{i}",
                    "node_b": f"orbiter_{j}",
                    "window_start_s": w_start,
                    "window_end_s": w_end
                })
                
    # 8c. Orbiter ↔ Earth links
    for o_idx in range(n):
        windows = compute_orbiter_earth_contacts(
            orb_positions[o_idx],
            times
        )
        for w_start, w_end in windows:
            results.append({
                "link_type": "orbiter_earth",
                "node_a": f"orbiter_{o_idx}",
                "node_b": "earth",
                "window_start_s": w_start,
                "window_end_s": w_end
            })
            
    # Convert to DataFrame
    df = pd.DataFrame(results, columns=["link_type", "node_a", "node_b", "window_start_s", "window_end_s"])
    
    # Sort for consistent output
    df = df.sort_values(by=["link_type", "node_a", "node_b", "window_start_s"]).reset_index(drop=True)
    
    # Ensure data folder exists
    os.makedirs("data", exist_ok=True)
    csv_path = f"data/contact_windows_N{n}.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved contact windows for N = {n} to {csv_path} (Total windows: {len(df)})")
    return df

def main():
    for n in N_VALUES:
        run_simulation_for_n(n)

if __name__ == "__main__":
    main()
