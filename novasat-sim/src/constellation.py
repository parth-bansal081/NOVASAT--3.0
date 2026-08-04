import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import numpy as np
from config import R_MARS_KM, MARS_OMEGA_RAD_S, ROVER_POSITIONS
from orbital_mechanics import get_mars_body, create_orbiters

class Rover:
    def __init__(self, name, latitude_deg, longitude_deg):
        """
        Represents a rover fixed on the surface of Mars.
        Converts lat/lon to Mars-fixed Cartesian coordinates.
        """
        self.name = name
        self.latitude_deg = latitude_deg
        self.longitude_deg = longitude_deg
        
        # Convert lat/lon to radians
        phi = np.radians(latitude_deg)
        lambda_ = np.radians(longitude_deg)
        
        # 1. Mars-fixed Cartesian coordinates (perfect sphere)
        self.x_fixed = R_MARS_KM * np.cos(phi) * np.cos(lambda_)
        self.y_fixed = R_MARS_KM * np.cos(phi) * np.sin(lambda_)
        self.z_fixed = R_MARS_KM * np.sin(phi)
        
    def get_positions(self, times):
        """
        Rotates the Mars-fixed coordinates into the Mars-centered inertial frame
        at each timestep.
        times: 1D numpy array of simulation seconds (t)
        Returns:
        - positions: 2D numpy array of shape (num_steps, 3) containing [x, y, z] in km.
        """
        # Rotate about the Mars polar (z) axis by theta(t) = omega * t
        theta = MARS_OMEGA_RAD_S * times
        
        # Apply rotation matrix:
        # x = x' * cos(theta) - y' * sin(theta)
        # y = x' * sin(theta) + y' * cos(theta)
        # z = z'
        x = self.x_fixed * np.cos(theta) - self.y_fixed * np.sin(theta)
        y = self.x_fixed * np.sin(theta) + self.y_fixed * np.cos(theta)
        z = np.full_like(x, self.z_fixed)
        
        return np.stack([x, y, z], axis=1)

def build_constellation(n):
    """
    Builds the Mars body, N orbiters, and the fixed surface rovers.
    Returns:
    - orbiters: list of hapsira Orbit objects
    - rovers: list of Rover objects
    """
    body = get_mars_body()
    orbiters = create_orbiters(n, body)
    
    rovers = []
    for r_id, info in ROVER_POSITIONS.items():
        rovers.append(Rover(
            name=info["name"],
            latitude_deg=info["latitude_deg"],
            longitude_deg=info["longitude_deg"]
        ))
        
    return orbiters, rovers
