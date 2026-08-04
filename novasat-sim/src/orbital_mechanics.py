import math
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import numpy as np
import astropy.coordinates.matrix_utilities as mu

# Monkeypatch astropy to support legacy matrix_product removed in astropy 6.0+
if not hasattr(mu, "matrix_product"):
    def matrix_product(*args):
        res = args[0]
        for m in args[1:]:
            res = res @ m
        return res
    mu.matrix_product = matrix_product

from astropy import units as u
from astropy.time import Time, TimeDelta

from hapsira.bodies import Body, Mars
from hapsira.twobody import Orbit
from hapsira.ephem import EpochsArray
from config import R_MARS_KM, MU_MARS_KM3_S2, SEMI_MAJOR_AXIS_KM

def get_mars_body():
    """
    Returns an attractor body for Mars. If the built-in Mars in hapsira
    matches our exact parameters closely, we can use it or wrap it.
    To be 100% compliant with the spec's exact values, we construct a custom Body.
    """
    # Verify built-in Mars constants
    builtin_r = Mars.R.to_value(u.km)
    builtin_k = Mars.k.to_value(u.km**3 / u.s**2)
    
    # Check if they match our spec values closely
    r_close = math.isclose(builtin_r, R_MARS_KM, rel_tol=1e-4)
    k_close = math.isclose(builtin_k, MU_MARS_KM3_S2, rel_tol=1e-4)
    
    if r_close and k_close:
        # Built-in Mars is close enough, but let's define a custom one with exact spec values
        # to guarantee zero assumptions or approximations.
        return Body(
            parent=None,
            k=MU_MARS_KM3_S2 * (u.km**3 / u.s**2),
            name="MarsCustom",
            R=R_MARS_KM * u.km
        )
    else:
        # If there's any discrepancy, definitely use the exact spec values
        return Body(
            parent=None,
            k=MU_MARS_KM3_S2 * (u.km**3 / u.s**2),
            name="MarsCustom",
            R=R_MARS_KM * u.km
        )

J2_MARS = 0.001960454

def compute_j2_rates(a_km: float, inc_rad: float, ecc: float = 0.0):
    """
    Computes J2 secular precession rates for RAAN, argument of pericenter, and mean motion.
    """
    n0 = math.sqrt(MU_MARS_KM3_S2 / (a_km ** 3))
    factor = 1.5 * J2_MARS * ((R_MARS_KM / a_km) ** 2) / ((1.0 - ecc**2) ** 2)
    
    cos_i = math.cos(inc_rad)
    cos2_i = cos_i ** 2
    
    raan_dot = -factor * n0 * cos_i
    argp_dot = 0.5 * factor * n0 * (5.0 * cos2_i - 1.0)
    n_bar = n0 * (1.0 + 0.5 * factor * math.sqrt(1.0 - ecc**2) * (3.0 * cos2_i - 1.0))
    
    return n_bar, raan_dot, argp_dot


def create_orbiters(n, body, apply_dispersion: bool = False, random_seed: int = 42):
    """
    Creates N orbiters in the polar plane.
    If apply_dispersion=True, applies small realistic insertion dispersion:
    - delta_a ~ N(0, 0.050 km) (50 meters)
    - delta_inc ~ N(0, 0.02 deg)
    """
    orbiters = []
    a_base = SEMI_MAJOR_AXIS_KM
    ecc = 0.0 * u.one
    inc_base = 90.0
    raan = 0.0 * u.deg
    argp = 0.0 * u.deg
    epoch = Time("2000-01-01 12:00:00", scale="tdb")
    
    rng = np.random.RandomState(random_seed) if apply_dispersion else None
    
    for i in range(n):
        if apply_dispersion and rng is not None:
            delta_a = rng.normal(0.0, 0.050)  # 50m std dev
            delta_inc = rng.normal(0.0, 0.02)  # 0.02 deg std dev
        else:
            delta_a = 0.0
            delta_inc = 0.0
            
        a_orb = (a_base + delta_a) * u.km
        inc_orb = (inc_base + delta_inc) * u.deg
        nu = (i * (360.0 / n)) * u.deg
        
        orb = Orbit.from_classical(
            attractor=body,
            a=a_orb,
            ecc=ecc,
            inc=inc_orb,
            raan=raan,
            argp=argp,
            nu=nu,
            epoch=epoch
        )
        # Attach dispersion offsets for downstream propagation
        orb.delta_a_km = delta_a
        orb.delta_inc_deg = delta_inc
        orbiters.append(orb)
        
    return orbiters


def propagate_orbiters_positions(orbiters, sim_duration_s, time_step_s, enable_j2: bool = True):
    """
    Propagates orbiter positions analytically over time, incorporating J2 secular precession
    (RAAN drift, argument of latitude rate) when enable_j2=True.
    """
    times = np.arange(0, sim_duration_s + time_step_s, time_step_s)
    num_orbiters = len(orbiters)

    positions_list = []
    for i, orb in enumerate(orbiters):
        a_km = float(orb.a.to_value(u.km))
        inc_rad = float(orb.inc.to_value(u.rad))
        nu_0 = float(orb.nu.to_value(u.rad))

        if enable_j2:
            n_bar, raan_dot, argp_dot = compute_j2_rates(a_km, inc_rad, ecc=0.0)
            u_t = nu_0 + (n_bar + argp_dot) * times
            raan_t = raan_dot * times
        else:
            n_orbit = math.sqrt(MU_MARS_KM3_S2 / (a_km**3))
            u_t = nu_0 + n_orbit * times
            raan_t = np.zeros_like(times)

        # 3D Position in MCI frame with J2 RAAN & Inc perturbation
        sin_inc = math.sin(inc_rad)
        cos_inc = math.cos(inc_rad)

        x_mci = a_km * (np.cos(u_t) * np.cos(raan_t) - np.sin(u_t) * np.sin(raan_t) * cos_inc)
        y_mci = a_km * (np.cos(u_t) * np.sin(raan_t) + np.sin(u_t) * np.cos(raan_t) * cos_inc)
        z_mci = a_km * (np.sin(u_t) * sin_inc)

        pos = np.stack([x_mci, y_mci, z_mci], axis=1).astype(np.float32)
        positions_list.append(pos)

    return times, positions_list



def compute_sub_satellite_points(positions, times):
    """
    Converts 3D Mars-Centered Inertial (MCI) positions to sub-satellite ground points
    (latitude, longitude, altitude) in the Mars-fixed rotating reference frame.

    - positions: 2D numpy array of shape (num_steps, 3) containing [x, y, z] in km.
    - times: 1D numpy array of simulation seconds [0, dt, 2*dt, ...].

    Returns:
    - lats: 1D numpy array of geodetic latitudes in degrees [-90, 90].
    - lons: 1D numpy array of geodetic longitudes in degrees [-180, 180].
    - alts: 1D numpy array of orbital altitudes above mean surface in km.
    """
    from config import MARS_OMEGA_RAD_S, R_MARS_KM

    x_inertial = positions[:, 0]
    y_inertial = positions[:, 1]
    z_inertial = positions[:, 2]

    theta = MARS_OMEGA_RAD_S * times

    # Derotate from MCI frame back into Mars-fixed rotating frame
    x_fixed = x_inertial * np.cos(theta) + y_inertial * np.sin(theta)
    y_fixed = -x_inertial * np.sin(theta) + y_inertial * np.cos(theta)
    z_fixed = z_inertial

    r = np.sqrt(x_fixed**2 + y_fixed**2 + z_fixed**2)
    lats = np.degrees(np.arcsin(np.clip(z_fixed / r, -1.0, 1.0)))
    lons = np.degrees(np.arctan2(y_fixed, x_fixed))
    alts = r - R_MARS_KM

    return lats, lons, alts
