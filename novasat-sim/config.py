"""
Shared simulation constants and configuration parameters for NOVASAT.
Contains physical constants, orbital mechanics parameters, rover coordinates,
simulation durations, cryptography settings, and trust propagation thresholds.
"""

import math
import numpy as np

# 2. Physical constants — use these exact values
R_MARS_KM = 3389.5  # Mars mean radius in km (perfect sphere)
MU_MARS_KM3_S2 = 42828.37  # Mars gravitational parameter in km^3/s^2
MARS_SIDEREAL_DAY_S = 88642.663  # Mars sidereal rotation period in seconds
MARS_OMEGA_RAD_S = 2 * math.pi / MARS_SIDEREAL_DAY_S  # Mars rotation rate in rad/s

# 3. Constellation design — exact parameters
ORBIT_ALTITUDE_KM = 400.0  # Altitude in km above Mars mean surface
SEMI_MAJOR_AXIS_KM = R_MARS_KM + ORBIT_ALTITUDE_KM  # a = 3789.5 km

# Orbital period derived from Kepler's third law: T = 2 * pi * sqrt(a^3 / mu)
ORBITAL_PERIOD_S = 2 * math.pi * math.sqrt(SEMI_MAJOR_AXIS_KM**3 / MU_MARS_KM3_S2)

# Satellite counts to run
N_VALUES = [1, 2, 4, 6, 8, 10]

# 5. Rover (surface asset) positions — fixed locations on Mars surface
ROVER_POSITIONS = {
    "rover_1": {
        "latitude_deg": 18.4663,   # N
        "longitude_deg": 77.4298,  # E
        "name": "rover_1"
    },
    "rover_2": {
        "latitude_deg": -4.5895,   # S
        "longitude_deg": 137.4417, # E
        "name": "rover_2"
    }
}

# 6. Simulation time span and resolution
SIM_DURATION_S = 2592000  # 30 Earth days in seconds (30 * 86400)
TIME_STEP_S = 30  # 30 seconds resolution

# 8. Contact parameters
MIN_ELEVATION_DEG = 10.0  # Minimum elevation angle in degrees for Rover-Orbiter link

# 8c. Orbiter-to-Earth fixed direction vector (simplification for Phase 1)
# Pick fixed direction along the reference x-axis of the orbital plane
EARTH_DIRECTION_VECTOR = np.array([1.0, 0.0, 0.0])

# 9. Cryptography constants (Phase 2)
CERT_VALIDITY_DAYS = 90

# 10. Phase 3 — Trust Propagation experiment constants
TRIALS_PER_CONFIG = 200  # Number of trials per (N, model/condition) combination

# Gossip corroboration thresholds (§5)
GOSSIP_VOTE_K = 2               # Fixed-threshold: require K distinct accusers
TRUST_WEIGHT_THRESHOLD = 2.0    # Trust-weighted: cumulative weight threshold
TRUST_WEIGHT_CONFIRM_FACTOR = 1.2  # Decay: multiply weight by this when accusation confirmed
TRUST_WEIGHT_DECAY_FACTOR = 0.5    # Decay: multiply weight by this when accusation unconfirmed

__all__ = [
    "R_MARS_KM",
    "MU_MARS_KM3_S2",
    "MARS_SIDEREAL_DAY_S",
    "MARS_OMEGA_RAD_S",
    "ORBIT_ALTITUDE_KM",
    "SEMI_MAJOR_AXIS_KM",
    "ORBITAL_PERIOD_S",
    "N_VALUES",
    "ROVER_POSITIONS",
    "SIM_DURATION_S",
    "TIME_STEP_S",
    "MIN_ELEVATION_DEG",
    "EARTH_DIRECTION_VECTOR",
    "CERT_VALIDITY_DAYS",
    "TRIALS_PER_CONFIG",
    "GOSSIP_VOTE_K",
    "TRUST_WEIGHT_THRESHOLD",
    "TRUST_WEIGHT_CONFIRM_FACTOR",
    "TRUST_WEIGHT_DECAY_FACTOR",
]


