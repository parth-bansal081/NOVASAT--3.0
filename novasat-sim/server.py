"""
server.py — NOVASAT Track 2 Phase 1 Live Physics & Streaming Server

FastAPI + WebSockets server providing live, real-time physics propagation,
biaxial line-of-sight occlusion computation, leakage-safe trained model inference,
and a local Mars tile map service (/api/tiles/{z}/{x}/{y}.png) for CesiumJS.

PHYSICS & ELLIPSOID RADIUS CONSTANTS NOTE:
------------------------------------------
1. orbital_mechanics.py uses R_MARS_KM = 3389.5 km (mean/volumetric radius)
   for two-body Keplerian propagation calculations (MU_MARS_KM3_S2 = 42828.37 km^3/s^2).
2. The 3D CesiumJS globe rendering and backend line-of-sight (LOS) occlusion math
   use the true physical biaxial ellipsoid:
     - Equatorial radius a = R_eq = 3396.19 km (3,396,190.0 m)
     - Polar radius b = R_pol = 3376.20 km (3,376,200.0 m)
Both values serve distinct, valid purposes and must NOT be forced to match each other.

LEAKAGE-SAFE MODEL INFERENCE NOTE:
----------------------------------
Trained anomaly detection model weights (gaussian_model.pkl & isolation_forest_model.pkl)
are loaded into memory at server startup in strictly READ-ONLY inference mode.
No online training or weight updating occurs during live simulation ticks.
Features strictly conform to the 34 Phase 4 training feature schema.
"""

import os
import io
import sys
import time
import math
import json
import pickle
import asyncio
from datetime import datetime
from functools import lru_cache
from typing import Dict, List, Any, Optional

import numpy as np
import pandas as pd
from PIL import Image
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

# Ensure root directory is on sys.path
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import (
    R_MARS_KM,              # 3389.5 km mean radius for orbital mechanics
    MU_MARS_KM3_S2,          # 42828.37 km^3/s^2
    MARS_OMEGA_RAD_S,        # Mars sidereal rotation rate (rad/s)
    ROVER_POSITIONS,
    MIN_ELEVATION_DEG,
    SIM_DURATION_S
)

# Import GaussianDensityModel for pickle unpickling compatibility
try:
    from experiments.train_anomaly_models import GaussianDensityModel
except ImportError:
    pass

try:
    from src.conjunction_assessment import evaluate_all_pairs_conjunction, PC_TRIGGER_THRESHOLD, PC_WATCH_THRESHOLD
except ImportError:
    pass

# Physical biaxial ellipsoid radii for 3D coordinate mapping & occlusion (in km)
MARS_ELLIPSOID_A_KM = 3396.19  # Equatorial radius
MARS_ELLIPSOID_B_KM = 3376.20  # Polar radius

app = FastAPI(title="NOVASAT Live Simulation Server", version="2.0.0")

# Mount web frontend static files
WEB_DIR = os.path.join(ROOT_DIR, "web")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# -----------------------------------------------------------------------------
# 0. Local Mars Surface Tile Slicing Engine (Offline 100% Guaranteed Textures)
# -----------------------------------------------------------------------------
MARS_IMG_PATH = os.path.join(WEB_DIR, "mars_viking_color.jpg")
if not os.path.exists(MARS_IMG_PATH):
    MARS_IMG_PATH = os.path.join(WEB_DIR, "mars_color.jpg")

_mars_base_img = None
if os.path.exists(MARS_IMG_PATH):
    try:
        _mars_base_img = Image.open(MARS_IMG_PATH).convert("RGB")
        print(f"[Tile Engine] Loaded Mars surface map: {_mars_base_img.size[0]}x{_mars_base_img.size[1]} ({MARS_IMG_PATH})")
    except Exception as e:
        print(f"[Tile Engine] Warning: Could not load Mars image: {e}")


@lru_cache(maxsize=1024)
def generate_mars_tile_bytes(z: int, x: int, y: int) -> bytes:
    """Slices Mars texture for GeographicTilingScheme EPSG:4326 (z: 0..6)."""
    cols = 1 << (z + 1)
    rows = 1 << z

    if _mars_base_img is None or x < 0 or x >= cols or y < 0 or y >= rows:
        blank = Image.new("RGB", (256, 256), (162, 72, 43))
        buf = io.BytesIO()
        blank.save(buf, format="PNG")
        return buf.getvalue()

    img_w, img_h = _mars_base_img.size
    left = int((x / cols) * img_w)
    right = int(((x + 1) / cols) * img_w)
    top = int((y / rows) * img_h)
    bottom = int(((y + 1) / rows) * img_h)

    tile_crop = _mars_base_img.crop((left, top, right, bottom)).resize((256, 256), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    tile_crop.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/api/tiles/{z}/{x}/{y}.png")
async def get_mars_tile(z: int, x: int, y: int):
    """Serves high-detail local Mars tiles for Cesium UrlTemplateImageryProvider."""
    tile_bytes = generate_mars_tile_bytes(z, x, y)
    return Response(content=tile_bytes, media_type="image/png")


# -----------------------------------------------------------------------------
# 1. Leakage-Safe Model Inference Loader
# -----------------------------------------------------------------------------
class AnomalyInferenceEngine:
    def __init__(self, models_dir: str = os.path.join(ROOT_DIR, "models")):
        self.gaussian_model = None
        self.iforest_model = None
        self.feature_cols = [
            "sig_verify_fail_count", "revocation_msgs_sent", "revocation_msgs_received",
            "accusations_made", "accusations_received", "corroboration_count_for_target",
            "trust_score_current", "msgs_sent", "msgs_recv", "bytes_sent", "bytes_recv",
            "unique_peers_contacted", "interarrival_mean_ms", "interarrival_std_ms",
            "retransmit_count", "drop_count", "in_contact_with_ground",
            "num_visible_orbiters", "num_visible_rovers", "window_open_fraction",
            "time_since_last_contact_sec", "pos_x", "pos_y", "pos_z", "vel_x", "vel_y", "vel_z",
            "speed_delta", "accel_proxy", "heading_change_rate", "power_level", "power_delta",
            "cpu_load", "queue_depth"
        ]

        gaussian_path = os.path.join(models_dir, "gaussian_model.pkl")
        iforest_path = os.path.join(models_dir, "isolation_forest_model.pkl")

        if os.path.exists(gaussian_path):
            try:
                with open(gaussian_path, "rb") as f:
                    self.gaussian_model = pickle.load(f)
                if hasattr(self.gaussian_model, "feature_names"):
                    self.feature_cols = list(self.gaussian_model.feature_names)
                print(f"[Model Engine] Loaded Gaussian Model from {gaussian_path}")
            except Exception as e:
                print(f"[Model Engine] Failed to load Gaussian Model: {e}")

        if os.path.exists(iforest_path):
            try:
                with open(iforest_path, "rb") as f:
                    self.iforest_model = pickle.load(f)
                print(f"[Model Engine] Loaded Isolation Forest Model from {iforest_path}")
            except Exception as e:
                print(f"[Model Engine] Failed to load Isolation Forest Model: {e}")

    def predict(self, feature_dict: Dict[str, float]) -> Dict[str, float]:
        """Perform read-only inference on exact 34-feature telemetry vector."""
        res = {"gaussian_score": 0.0, "iforest_score": 0.0, "anomaly_flag": False}

        vec_df = pd.DataFrame([[feature_dict.get(c, 0.0) for c in self.feature_cols]], columns=self.feature_cols, dtype=np.float32)

        if self.gaussian_model is not None and hasattr(self.gaussian_model, "compute_scores"):
            try:
                g_scores = self.gaussian_model.compute_scores(vec_df)
                res["gaussian_score"] = float(g_scores[0])
            except Exception as e:
                pass

        if self.iforest_model is not None and hasattr(self.iforest_model, "decision_function"):
            try:
                if_raw = self.iforest_model.decision_function(vec_df)[0]
                res["iforest_score"] = float(np.clip(0.5 - (if_raw / 0.2), 0.0, 1.0))
            except Exception as e:
                pass

        res["anomaly_flag"] = (res["gaussian_score"] > 0.05) or (res["iforest_score"] > 0.60)
        return res


inference_engine = AnomalyInferenceEngine()


# -----------------------------------------------------------------------------
# 2. Biaxial Ray-Ellipsoid Line-of-Sight Occlusion Math
# -----------------------------------------------------------------------------
def check_biaxial_occlusion(
    pos_a_km: np.ndarray,
    pos_b_km: np.ndarray,
    a_km: float = MARS_ELLIPSOID_A_KM,
    b_km: float = MARS_ELLIPSOID_B_KM
) -> bool:
    """
    Evaluates whether the 3D line segment between pos_a_km and pos_b_km intersects
    the Mars interior biaxial ellipsoid ((x^2+y^2)/a^2 + z^2/b^2 < 1 - eps).
    """
    p1 = np.array([pos_a_km[0] / a_km, pos_a_km[1] / a_km, pos_a_km[2] / b_km], dtype=np.float64)
    p2 = np.array([pos_b_km[0] / a_km, pos_b_km[1] / a_km, pos_b_km[2] / b_km], dtype=np.float64)

    d = p2 - p1
    d_dot_d = np.dot(d, d)

    if d_dot_d < 1e-12:
        return float(np.dot(p1, p1)) < 0.9999

    t = -np.dot(p1, d) / d_dot_d
    t_close = np.clip(t, 1e-4, 1.0 - 1e-4)
    p_close = p1 + t_close * d

    return float(np.dot(p_close, p_close)) < 0.9999


def geodetic_to_cartesian_biaxial(
    lat_deg: float,
    lon_deg: float,
    alt_km: float = 0.0,
    a_km: float = MARS_ELLIPSOID_A_KM,
    b_km: float = MARS_ELLIPSOID_B_KM
) -> np.ndarray:
    """Converts Geodetic (lat, lon, alt) to Mars-Fixed Cartesian (x, y, z) on biaxial ellipsoid."""
    phi = math.radians(lat_deg)
    lam = math.radians(lon_deg)

    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)
    e2 = 1.0 - (b_km**2 / a_km**2)
    N = a_km / math.sqrt(1.0 - e2 * sin_phi**2)

    x = (N + alt_km) * cos_phi * math.cos(lam)
    y = (N + alt_km) * cos_phi * math.sin(lam)
    z = (N * (1.0 - e2) + alt_km) * sin_phi

    return np.array([x, y, z], dtype=np.float64)


def cartesian_to_geodetic_biaxial(
    pos_km: np.ndarray,
    a_km: float = MARS_ELLIPSOID_A_KM,
    b_km: float = MARS_ELLIPSOID_B_KM
) -> Dict[str, float]:
    """Converts Mars-Fixed Cartesian (x, y, z) to Geodetic (lat, lon, alt) on biaxial ellipsoid."""
    x, y, z = pos_km[0], pos_km[1], pos_km[2]
    e2 = 1.0 - (b_km**2 / a_km**2)
    p = math.sqrt(x**2 + y**2)

    lon = math.degrees(math.atan2(y, x))
    if p < 1e-6:
        lat = 90.0 if z > 0 else -90.0
        alt = abs(z) - b_km
        return {"latitude_deg": lat, "longitude_deg": lon, "altitude_km": alt}

    phi = math.atan2(z, p * (1.0 - e2))
    for _ in range(5):
        sin_phi = math.sin(phi)
        N = a_km / math.sqrt(1.0 - e2 * sin_phi**2)
        phi = math.atan2(z + e2 * N * sin_phi, p)

    sin_phi = math.sin(phi)
    N = a_km / math.sqrt(1.0 - e2 * sin_phi**2)
    alt = (p / math.cos(phi)) - N
    lat = math.degrees(phi)

    return {"latitude_deg": lat, "longitude_deg": lon, "altitude_km": alt}


# Pre-calculate surface rover positions on Mars biaxial ellipsoid
SURFACE_ASSET_CARTESIAN = {}
for r_id, r_info in ROVER_POSITIONS.items():
    pos_3d = geodetic_to_cartesian_biaxial(r_info["latitude_deg"], r_info["longitude_deg"], 0.0)
    SURFACE_ASSET_CARTESIAN[r_id] = {
        "latitude_deg": r_info["latitude_deg"],
        "longitude_deg": r_info["longitude_deg"],
        "altitude_km": 0.0,
        "cartesian_km": pos_3d.tolist(),
        "name": r_info["name"]
    }


# -----------------------------------------------------------------------------
# 3. Live Simulation Engine
# -----------------------------------------------------------------------------
class LiveSimulationEngine:
    def __init__(self):
        self.n: int = 6
        self.speed_multiplier: float = 60.0
        self.sim_time_s: float = 0.0
        self.is_paused: bool = False
        self.recording_enabled: bool = False
        self.recording_file: Optional[str] = None
        self.recorded_rows: List[Dict[str, Any]] = []

        self.custom_elements: Dict[int, Dict[str, float]] = {}
        self.fault_states: Dict[str, Dict[str, Any]] = {}
        self.last_wall_time = time.time()

        # Track 2 Phase 2 Conjunction Risk & Auto-Maneuver State
        self.conjunction_risks: List[Dict[str, Any]] = []
        self.max_pc: float = 0.0
        self.max_pc_pair: Optional[str] = None
        self.maneuver_logs: List[Dict[str, Any]] = []
        self.last_conjunction_eval_time: float = -3600.0
        self.triage_model = None

        triage_pkl = os.path.join(ROOT_DIR, "models", "triage_classifier.pkl")
        if os.path.exists(triage_pkl):
            try:
                with open(triage_pkl, "rb") as f:
                    self.triage_model = pickle.load(f)
                print(f"[Sim Engine] Loaded ML Triage Classifier from {triage_pkl}")
            except Exception as e:
                print(f"[Sim Engine] Warning: Could not load triage classifier: {e}")

    def set_n(self, n: int):
        if n in [1, 2, 4, 6, 8, 10]:
            self.n = n
            print(f"[Sim Engine] Constellation size set to N = {self.n}")

    def set_speed(self, multiplier: float):
        self.speed_multiplier = max(0.1, min(3600.0, float(multiplier)))
        print(f"[Sim Engine] Speed multiplier set to {self.speed_multiplier}x")

    def set_satellite_elements(self, orbiter_index: int, altitude_km: float, inclination_deg: float):
        self.custom_elements[orbiter_index] = {
            "altitude_km": max(100.0, min(10000.0, altitude_km)),
            "inclination_deg": max(0.0, min(180.0, inclination_deg))
        }
        print(f"[Sim Engine] Updated orbiter_{orbiter_index}: alt={altitude_km}km, inc={inclination_deg}deg")

    def inject_fault(self, node_id: str, fault_type: str):
        self.fault_states[node_id] = {
            "fault_type": fault_type,
            "injected_at": self.sim_time_s
        }
        print(f"[Sim Engine] Injected fault '{fault_type}' on node '{node_id}' at t={self.sim_time_s:.1f}s")

    def clear_fault(self, node_id: str):
        if node_id in self.fault_states:
            del self.fault_states[node_id]
            print(f"[Sim Engine] Cleared fault on node '{node_id}'")

    def reset(self):
        self.sim_time_s = 0.0
        self.fault_states.clear()
        self.recorded_rows.clear()
        print("[Sim Engine] Simulation reset to t = 0s")

    def toggle_record(self, enabled: bool) -> str:
        self.recording_enabled = enabled
        if enabled:
            os.makedirs(os.path.join(ROOT_DIR, "data", "live_recordings"), exist_ok=True)
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.recording_file = os.path.join(ROOT_DIR, "data", "live_recordings", f"session_{ts_str}.csv")
            self.recorded_rows = []
            print(f"[Sim Engine] Telemetry recording STARTED -> {self.recording_file}")
            return self.recording_file
        else:
            if self.recorded_rows and self.recording_file:
                df = pd.DataFrame(self.recorded_rows)
                df.to_csv(self.recording_file, index=False)
                print(f"[Sim Engine] Telemetry recording SAVED ({len(df)} rows) -> {self.recording_file}")
                msg = self.recording_file
            else:
                msg = "No data recorded"
            self.recording_file = None
            return msg

    def compute_tick_state(self) -> Dict[str, Any]:
        """Propagates orbiters and calculates contacts, telemetry, and model inference for current sim_time_s."""
        t_sec = self.sim_time_s
        theta = MARS_OMEGA_RAD_S * t_sec

        orbiters_state = []
        positions_fixed_km = []

        for i in range(self.n):
            node_id = f"orbiter_{i}"
            elem = self.custom_elements.get(i, {"altitude_km": 400.0, "inclination_deg": 90.0})
            alt_km = elem["altitude_km"]
            inc_deg = elem["inclination_deg"]

            a_orbit_km = R_MARS_KM + alt_km
            n_mean = math.sqrt(MU_MARS_KM3_S2 / (a_orbit_km**3))

            nu_0 = i * (2.0 * math.pi / self.n)
            nu_t = nu_0 + n_mean * t_sec

            fault = self.fault_states.get(node_id, {})
            fault_type = fault.get("fault_type", "none")

            if fault_type == "clock_drift":
                dt_fault = (t_sec - fault["injected_at"]) * 0.05
                nu_t += n_mean * dt_fault
            elif fault_type == "altitude_decay":
                decay_km = (t_sec - fault["injected_at"]) * 0.01
                alt_km = max(150.0, alt_km - decay_km)
                a_orbit_km = R_MARS_KM + alt_km

            inc_rad = math.radians(inc_deg)
            x_mci = a_orbit_km * math.cos(nu_t)
            y_mci = a_orbit_km * math.sin(nu_t) * math.cos(inc_rad)
            z_mci = a_orbit_km * math.sin(nu_t) * math.sin(inc_rad)

            vel_km_s = math.sqrt(MU_MARS_KM3_S2 * (2.0 / a_orbit_km - 1.0 / a_orbit_km))

            x_fixed = x_mci * math.cos(theta) + y_mci * math.sin(theta)
            y_fixed = -x_mci * math.sin(theta) + y_mci * math.cos(theta)
            z_fixed = z_mci

            pos_fixed = np.array([x_fixed, y_fixed, z_fixed], dtype=np.float64)
            positions_fixed_km.append(pos_fixed)

            geod = cartesian_to_geodetic_biaxial(pos_fixed)

            orbiters_state.append({
                "id": node_id,
                "index": i,
                "latitude_deg": float(geod["latitude_deg"]),
                "longitude_deg": float(geod["longitude_deg"]),
                "altitude_km": float(geod["altitude_km"]),
                "velocity_km_s": float(vel_km_s),
                "cartesian_km": [float(x_fixed), float(y_fixed), float(z_fixed)],
                "fault_type": fault_type,
                "is_compromised": fault_type != "none"
            })

        # Calculate Surface Contacts (Rover <-> Orbiter) using biaxial LOS occlusion
        active_contacts = []
        surface_statuses = {r_id: {"active_contact": False, "connected_orbiter": None} for r_id in SURFACE_ASSET_CARTESIAN}

        for r_id, r_data in SURFACE_ASSET_CARTESIAN.items():
            pos_rover = np.array(r_data["cartesian_km"], dtype=np.float64)
            zenith_unnorm = np.array([
                2.0 * pos_rover[0] / (MARS_ELLIPSOID_A_KM**2),
                2.0 * pos_rover[1] / (MARS_ELLIPSOID_A_KM**2),
                2.0 * pos_rover[2] / (MARS_ELLIPSOID_B_KM**2)
            ], dtype=np.float64)
            zenith_unit = zenith_unnorm / np.linalg.norm(zenith_unnorm)

            for i in range(self.n):
                pos_orb = positions_fixed_km[i]
                los_vec = pos_orb - pos_rover
                dist_km = float(np.linalg.norm(los_vec))
                los_unit = los_vec / dist_km

                cos_zenith = np.clip(np.dot(los_unit, zenith_unit), -1.0, 1.0)
                elev_deg = float(90.0 - math.degrees(math.acos(cos_zenith)))

                is_blocked = check_biaxial_occlusion(pos_rover, pos_orb)
                is_in_los = (elev_deg >= MIN_ELEVATION_DEG) and (not is_blocked)

                if is_in_los:
                    active_contacts.append({
                        "link_type": "rover_orbiter",
                        "node_a": r_id,
                        "node_b": f"orbiter_{i}",
                        "distance_km": dist_km,
                        "elevation_deg": elev_deg
                    })
                    surface_statuses[r_id]["active_contact"] = True
                    surface_statuses[r_id]["connected_orbiter"] = f"orbiter_{i}"

        # Orbiter-to-Orbiter Crosslinks
        if self.n >= 2:
            for i in range(self.n):
                j_next = (i + 1) % self.n
                pos_a = positions_fixed_km[i]
                pos_b = positions_fixed_km[j_next]
                dist_km = float(np.linalg.norm(pos_b - pos_a))
                is_blocked = check_biaxial_occlusion(pos_a, pos_b)

                if not is_blocked:
                    active_contacts.append({
                        "link_type": "orbiter_orbiter",
                        "node_a": f"orbiter_{i}",
                        "node_b": f"orbiter_{j_next}",
                        "distance_km": dist_km,
                        "elevation_deg": 0.0
                    })

        # Run Leakage-Safe Model Inference for each orbiter tick using full 34-feature schema
        for orb in orbiters_state:
            pos_fixed = np.array(orb["cartesian_km"], dtype=np.float64)
            fault_type = orb["fault_type"]

            is_ground = any((c["node_a"].startswith("rover_") and c["node_b"] == orb["id"]) or (c["node_b"].startswith("rover_") and c["node_a"] == orb["id"]) for c in active_contacts)
            num_orb_vis = sum(1 for c in active_contacts if c["link_type"] == "orbiter_orbiter" and (c["node_a"] == orb["id"] or c["node_b"] == orb["id"]))
            num_rov_vis = sum(1 for c in active_contacts if c["link_type"] == "rover_orbiter" and (c["node_a"] == orb["id"] or c["node_b"] == orb["id"]))

            feat_34 = {
                "sig_verify_fail_count": 0.0,
                "revocation_msgs_sent": 0.0,
                "revocation_msgs_received": 0.0,
                "accusations_made": 0.0,
                "accusations_received": 0.0,
                "corroboration_count_for_target": 0.0,
                "trust_score_current": 1.0,
                "msgs_sent": 8.0,
                "msgs_recv": 8.0,
                "bytes_sent": 2139.0,
                "bytes_recv": 2138.0,
                "unique_peers_contacted": float(num_orb_vis + num_rov_vis),
                "interarrival_mean_ms": 500.0,
                "interarrival_std_ms": 50.0,
                "retransmit_count": 0.0,
                "drop_count": 0.0,
                "in_contact_with_ground": 1.0 if is_ground else 0.0,
                "num_visible_orbiters": float(num_orb_vis),
                "num_visible_rovers": float(num_rov_vis),
                "window_open_fraction": 0.46,
                "time_since_last_contact_sec": 0.0 if is_ground else 120.0,
                "pos_x": float(pos_fixed[0]),
                "pos_y": float(pos_fixed[1]),
                "pos_z": float(pos_fixed[2]),
                "vel_x": float(orb["velocity_km_s"]),
                "vel_y": 0.0,
                "vel_z": 0.0,
                "speed_delta": 0.005,
                "accel_proxy": 0.0001,
                "heading_change_rate": 0.00006,
                "power_level": 90.6,
                "power_delta": -0.0001,
                "cpu_load": 25.0,
                "queue_depth": 5.0
            }

            if fault_type == "clock_drift":
                feat_34["interarrival_mean_ms"] = 2850.0
                feat_34["interarrival_std_ms"] = 650.0
                feat_34["retransmit_count"] = 18.0
                feat_34["drop_count"] = 14.0
                feat_34["sig_verify_fail_count"] = 6.0
            elif fault_type == "altitude_decay":
                feat_34["pos_z"] += 450.0
                feat_34["speed_delta"] = 8.5
                feat_34["accel_proxy"] = 2.1
                feat_34["heading_change_rate"] = 0.05

            pred = inference_engine.predict(feat_34)
            orb["inference"] = pred

            if self.recording_enabled:
                rec_row = {
                    "sim_time_s": t_sec,
                    "node_id": orb["id"],
                    "n": self.n,
                    "fault_type": orb["fault_type"],
                    "gaussian_score": pred["gaussian_score"],
                    "iforest_score": pred["iforest_score"],
                    **feat_34
                }
                self.recorded_rows.append(rec_row)

        # Conjunction Risk Assessment Pass (Decoupled Hourly Cadence - Part A.1)
        if self.sim_time_s - self.last_conjunction_eval_time >= 3600.0 or not self.conjunction_risks:
            try:
                res = evaluate_all_pairs_conjunction(orbiters_state, lookahead_sec=86400.0, triage_model=self.triage_model)
                self.conjunction_risks = res["risks"]
                self.max_pc = res["max_pc"]
                self.max_pc_pair = res["max_pc_pair"]
                self.last_conjunction_eval_time = self.sim_time_s

                # Check for deterministic maneuver triggers (Pc > 1e-4 - Part E)
                for risk in res["risks"]:
                    if risk.get("is_trigger", False):
                        sat_a_id = risk["sat_A"]
                        try:
                            sat_a_idx = int(sat_a_id.replace("orbiter_", ""))
                            curr_alt = self.custom_elements.get(sat_a_idx, {}).get("altitude_km", 400.0)
                            curr_inc = self.custom_elements.get(sat_a_idx, {}).get("inclination_deg", 90.0)
                            new_alt = curr_alt + 2.0  # 2km along-track altitude boost maneuver
                            
                            self.set_satellite_elements(sat_a_idx, new_alt, curr_inc)
                            
                            # Mark satellite as maneuvering
                            for orb in orbiters_state:
                                if orb["id"] == sat_a_id:
                                    orb["maneuvering"] = True

                            maneuver_entry = {
                                "timestamp": float(t_sec),
                                "sat_A": sat_a_id,
                                "sat_B": risk["sat_B"],
                                "pc": float(risk["pc"]),
                                "miss_distance_km": float(risk["miss_distance_km"]),
                                "delta_alt_km": 2.0,
                                "new_alt_km": float(new_alt),
                                "action": "AUTO_MANEUVER_EXECUTED"
                            }
                            self.maneuver_logs.append(maneuver_entry)
                            print(f"[Collision Avoidance] AUTO-MANEUVER TRIGGERED: {sat_a_id} vs {risk['sat_B']} (Pc={risk['pc']:.2e}, New Alt={new_alt:.1f}km)")
                        except Exception as ex:
                            print(f"[Collision Avoidance] Error executing maneuver: {ex}")
            except Exception as e:
                print(f"[Collision Avoidance] Error in conjunction assessment pass: {e}")

        days = int(t_sec // 86400)
        rem = t_sec % 86400
        hrs = int(rem // 3600)
        mins = int((rem % 3600) // 60)
        secs = int(rem % 60)
        clock_str = f"Day {days:02d} — {hrs:02d}:{mins:02d}:{secs:02d}"

        return {
            "timestamp": time.time(),
            "sim_time_s": float(t_sec),
            "clock_str": clock_str,
            "n": self.n,
            "speed_multiplier": self.speed_multiplier,
            "is_paused": self.is_paused,
            "recording": self.recording_enabled,
            "orbiters": orbiters_state,
            "rovers": SURFACE_ASSET_CARTESIAN,
            "surface_statuses": surface_statuses,
            "active_contacts": active_contacts,
            "conjunction_risks": self.conjunction_risks,
            "max_pc": float(self.max_pc),
            "max_pc_pair": self.max_pc_pair,
            "maneuver_logs": self.maneuver_logs[-20:],
            "orbital_period_min": float(2.0 * math.pi * math.sqrt((R_MARS_KM + 400.0)**3 / MU_MARS_KM3_S2) / 60.0)
        }

    def update(self):
        now = time.time()
        wall_dt = now - self.last_wall_time
        self.last_wall_time = now

        if not self.is_paused:
            self.sim_time_s += wall_dt * self.speed_multiplier
            if self.sim_time_s >= SIM_DURATION_S:
                self.sim_time_s = SIM_DURATION_S


sim_engine = LiveSimulationEngine()


# -----------------------------------------------------------------------------
# 4. WebSocket & REST Endpoints
# -----------------------------------------------------------------------------
@app.get("/")
async def get_index():
    """Serve web frontend index.html."""
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h2>NOVASAT Web Frontend Loading...</h2>")


@app.get("/api/landmarks")
async def get_landmarks():
    """Returns official USGS Mars Nomenclature landmarks dataset."""
    landmarks_path = os.path.join(ROOT_DIR, "data", "usgs_mars_landmarks.json")
    if os.path.exists(landmarks_path):
        with open(landmarks_path, "r") as f:
            data = json.load(f)
        return data
    raise HTTPException(status_code=404, detail="Landmarks dataset not found")


@app.get("/api/status")
async def get_status():
    """Returns simulation engine status."""
    return {
        "sim_time_s": sim_engine.sim_time_s,
        "n": sim_engine.n,
        "speed": sim_engine.speed_multiplier,
        "is_paused": sim_engine.is_paused,
        "recording": sim_engine.recording_enabled
    }


@app.websocket("/ws/sim")
async def websocket_sim_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[WebSocket] Client connected")

    try:
        while True:
            try:
                msg_text = await asyncio.wait_for(websocket.receive_text(), timeout=0.04)
                data = json.loads(msg_text)
                action = data.get("action")

                if action == "set_speed":
                    sim_engine.set_speed(data.get("speed", 60.0))
                elif action == "set_n":
                    sim_engine.set_n(data.get("n", 6))
                elif action == "set_elements":
                    idx = int(data.get("orbiter_index", 0))
                    alt = float(data.get("altitude_km", 400.0))
                    inc = float(data.get("inclination_deg", 90.0))
                    sim_engine.set_satellite_elements(idx, alt, inc)
                elif action == "inject_fault":
                    node_id = str(data.get("node_id", ""))
                    fault_type = str(data.get("fault_type", "clock_drift"))
                    sim_engine.inject_fault(node_id, fault_type)
                elif action == "clear_fault":
                    node_id = str(data.get("node_id", ""))
                    sim_engine.clear_fault(node_id)
                elif action == "play":
                    sim_engine.is_paused = False
                elif action == "pause":
                    sim_engine.is_paused = True
                elif action == "reset":
                    sim_engine.reset()
                elif action == "toggle_record":
                    enabled = bool(data.get("enabled", False))
                    sim_engine.toggle_record(enabled)

            except asyncio.TimeoutError:
                pass

            sim_engine.update()
            payload = sim_engine.compute_tick_state()
            await websocket.send_text(json.dumps(payload))

            await asyncio.sleep(0.08)

    except WebSocketDisconnect:
        print("[WebSocket] Client disconnected")
    except Exception as e:
        print(f"[WebSocket] Exception: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
