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

def create_orbiters(n, body):
    """
    Creates N orbiters in the same orbital plane, spaced equally in true anomaly.
    - Orbit shape: circular (ecc = 0)
    - Inclination: 90 degrees (polar orbit)
    - RAAN: 0 degrees
    - Argument of pericenter: 0 degrees
    - Spacing: True anomaly = i * (360 / N) degrees
    """
    orbiters = []
    a = SEMI_MAJOR_AXIS_KM * u.km
    ecc = 0.0 * u.one
    inc = 90.0 * u.deg
    raan = 0.0 * u.deg
    argp = 0.0 * u.deg
    
    # Use J2000 epoch as reference start time
    epoch = Time("2000-01-01 12:00:00", scale="tdb")
    
    for i in range(n):
        nu = (i * (360.0 / n)) * u.deg
        orb = Orbit.from_classical(
            attractor=body,
            a=a,
            ecc=ecc,
            inc=inc,
            raan=raan,
            argp=argp,
            nu=nu,
            epoch=epoch
        )
        orbiters.append(orb)
    return orbiters

def propagate_orbiters_positions(orbiters, sim_duration_s, time_step_s):
    """
    High-performance analytical propagation of orbiters over simulation duration.
    For circular polar orbits (inc=90deg, e=0, raan=0, argp=0), analytical 2-body
    Keplerian propagation is exact and runs in milliseconds.

    Returns:
    - times: 1D numpy array of simulation seconds [0, dt, 2*dt, ...]
    - positions_list: list of 2D numpy arrays of shape (num_steps, 3) containing [x, y, z] in km.
    """
    times = np.arange(0, sim_duration_s + time_step_s, time_step_s)
    num_orbiters = len(orbiters)
    a = SEMI_MAJOR_AXIS_KM
    n_orbit = np.sqrt(MU_MARS_KM3_S2 / (a**3))

    positions_list = []
    for i in range(num_orbiters):
        nu_0 = i * (2.0 * np.pi / num_orbiters)
        nu_t = nu_0 + n_orbit * times

        x = (a * np.cos(nu_t)).astype(np.float32)
        y = np.zeros_like(x, dtype=np.float32)
        z = (a * np.sin(nu_t)).astype(np.float32)

        pos = np.stack([x, y, z], axis=1)
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
