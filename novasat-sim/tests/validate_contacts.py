import os
import sys
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import pandas as pd
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from config import N_VALUES

PROJECT_ROOT = ROOT_DIR
ARTIFACT_DIR = os.path.join(PROJECT_ROOT, "data")

def validate_and_plot(n):
    csv_path = os.path.join(ROOT_DIR, "data", f"contact_windows_N{n}.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Missing simulation output: {csv_path}")
        
    df = pd.read_csv(csv_path)
    
    # 1. Rover-Orbiter checks
    df_rover = df[df["link_type"] == "rover_orbiter"]
    
    rovers = ["rover_1", "rover_2"]
    rover_counts = {}
    
    for rover in rovers:
        df_r = df_rover[df_rover["node_a"] == rover]
        count = len(df_r)
        rover_counts[rover] = count
        
        # Validation 1: At least one contact window
        if count == 0:
            raise AssertionError(f"Validation FAILED: Rover {rover} has zero contact windows for N = {n}!")
            
        # Validation 2: Plausible count of windows (roughly tens to low hundreds over 30 days)
        # For N=1, we expect fewer windows (e.g. ~10-40). For N=10, we expect more (e.g. ~200-400).
        # We can set the plausible range to [10, 1000]
        if not (10 <= count <= 1000):
            raise AssertionError(f"Validation FAILED: Rover {rover} has implausible window count of {count} for N = {n}!")
            
    print(f"Validation PASSED for N = {n}:")
    for r, c in rover_counts.items():
        print(f"  - {r}: {c} contact windows")
        
    # 2. Check crosslinks against analytical predictions
    df_cross = df[df["link_type"] == "orbiter_orbiter"]
    cross_count = len(df_cross)
    if n in [1, 2, 4, 6]:
        # Separation angle is too large, adjacent orbiters never clear Mars
        if cross_count > 0:
            raise AssertionError(f"Validation FAILED: Expected 0 crosslinks for N = {n}, but found {cross_count}!")
        print(f"  - Crosslink check: Correctly found 0 crosslinks (geometry-blocked)")
    elif n in [8, 10]:
        # Separation angle is small enough, adjacent orbiters are in constant contact
        # Let's verify that each unique adjacent pair has exactly 1 window of 30 days duration
        expected_pairs = n
        if n == 8:
            expected_pairs = 8
        elif n == 10:
            expected_pairs = 10
            
        if cross_count != expected_pairs:
            raise AssertionError(f"Validation FAILED: Expected {expected_pairs} unique crosslinks for N = {n}, but found {cross_count}!")
            
        # Verify duration is 30 days (2592000 seconds)
        for _, row in df_cross.iterrows():
            duration = row["window_end_s"] - row["window_start_s"]
            if duration != 2592000:
                raise AssertionError(f"Validation FAILED: Expected continuous 30-day crosslink (2592000s), but got {duration}s!")
        print(f"  - Crosslink check: Correctly found {cross_count} continuous 30-day crosslinks (line-of-sight clear)")

    # 3. Plot timeline
    fig, ax = plt.subplots(figsize=(10, 4))
    colors = ["#4A90E2", "#50E3C2"]
    
    for i, rover in enumerate(rovers):
        df_r = df_rover[df_rover["node_a"] == rover]
        xranges = []
        for _, row in df_r.iterrows():
            start_day = row["window_start_s"] / 86400.0
            end_day = row["window_end_s"] / 86400.0
            duration = end_day - start_day
            if duration == 0:
                duration = 30.0 / 86400.0  # 30 seconds
            xranges.append((start_day, duration))
            
        if xranges:
            ax.broken_barh(xranges, (i - 0.25, 0.5), facecolors=colors[i], label=rover.replace('_', ' ').title())
            
    ax.set_ylim(-0.5, 1.5)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Rover 1", "Rover 2"])
    ax.set_xlabel("Simulation Time (days)")
    ax.set_ylabel("Surface Asset")
    ax.set_title(f"Rover-Orbiter Contact Windows (N = {n} orbiters)")
    ax.set_xlim(0, 30)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(loc="upper right")
    
    plt.tight_layout()
    
    # Save in project directory
    data_dir = os.path.join(ROOT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    plot_path = os.path.join(data_dir, f"contact_timeline_N{n}.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()
    
    # Copy to artifact folder for embedding in walkthrough
    if os.path.exists(ARTIFACT_DIR):
        artifact_plot_path = os.path.join(ARTIFACT_DIR, f"contact_timeline_N{n}.png")
        if os.path.abspath(plot_path) != os.path.abspath(artifact_plot_path):
            shutil.copy(plot_path, artifact_plot_path)

def main():
    for n in N_VALUES:
        validate_and_plot(n)
    print("\nAll validations passed successfully!")

if __name__ == "__main__":
    main()
