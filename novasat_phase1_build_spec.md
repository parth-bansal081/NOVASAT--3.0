# NOVASAT — Phase 1 Build Spec: Orbital Foundation & Contact-Window Calculator

**Audience note for the coding agent:** you are a strong programmer with no assumed background in orbital mechanics or this project's prior design decisions. Every physical constant, threshold, and design choice needed is given explicitly below. Do not substitute, approximate, or invent a value that isn't stated here. If something is genuinely ambiguous or missing, stop and flag it rather than guessing.

**Goal of this phase, in one sentence:** produce a script that, given a satellite count N and two fixed Mars rover locations, computes and saves the exact time windows during which every pair of nodes (rover↔orbiter, orbiter↔orbiter, orbiter↔Earth) can communicate.

**Why this matters:** every later phase (identity system, trust propagation, anomaly detection) depends on this schedule already existing and being correct. Nothing downstream can be meaningfully tested until this works and passes validation.

---

## 1. Environment setup

```
pip install hapsira numpy pandas matplotlib
```

- Do **not** install `poliastro` — it is archived/unmaintained. `hapsira` is its actively maintained fork with the same API surface.
- Verify install: `python -c "import hapsira; print(hapsira.__version__)"`
- Use hapsira's `Orbit` class (from classical orbital elements) and its `propagate()` method to get satellite position over time — do not hand-write Kepler propagation from scratch. Check `hapsira.bodies` for a built-in `Mars` object first; if present, cross-check its radius/gravitational parameter against §2 below (they should match closely). If hapsira does not provide Mars, define a custom body using the exact constants in §2.

## 2. Physical constants — use these exact values

| Constant | Value | Notes |
|---|---|---|
| Mars mean radius | `R_MARS_KM = 3389.5` | Treat Mars as a perfect sphere — oblateness is not modeled in this phase (explicit simplification) |
| Mars gravitational parameter | `MU_MARS_KM3_S2 = 42828.37` | Used in Kepler's third law for orbital period |
| Mars sidereal rotation period | `MARS_SIDEREAL_DAY_S = 88642.663` | ≈ 24.6229 hours |
| Mars rotation rate | `MARS_OMEGA_RAD_S = 2 * pi / MARS_SIDEREAL_DAY_S` | ≈ 7.088e-5 rad/s |

## 3. Constellation design — exact parameters and the reasoning behind each

- **Orbit shape:** circular, single orbital plane.
- **Inclination: 90° (polar orbit).** This is a deliberate choice, not arbitrary — explained in §4.
- **Altitude: `ORBIT_ALTITUDE_KM = 400`** above Mars's mean surface. Semi-major axis `a = R_MARS_KM + ORBIT_ALTITUDE_KM = 3789.5` km. Make this a named config constant — do not hardcode the derived period, compute it.
- **Orbital period:** derive from Kepler's third law — `T = 2 * pi * sqrt(a**3 / MU_MARS_KM3_S2)` — do not hardcode a period value; it must update automatically if altitude changes.
- **Number of orbiters, N:** must run this entire pipeline once for each value in `N_VALUES = [1, 2, 4, 6, 8, 10]`.
- **Orbiter spacing within the plane:** for a given N, orbiter `i` (i = 0 to N-1) starts at true anomaly `= i * (360 / N)` degrees. This also defines each orbiter's nearest neighbors for later mesh/crosslink logic: orbiter `i`'s neighbors are orbiters `i-1` and `i+1`, wrapping around (orbiter 0's "previous" neighbor is orbiter N-1).

## 4. Why polar orbit, not equatorial — read this before changing it

The two rover locations (§5) are at different latitudes — one north, one south of the equator. An equatorial orbit would only ever pass near-overhead of equatorial ground positions, and could leave one or both rovers with little or no real contact at all, which would break every later experiment (there'd be nothing to measure). A polar orbit's ground track sweeps through *all* latitudes as Mars rotates beneath the orbital plane, guaranteeing periodic passes over both rover locations regardless of their latitude. This is also why real Mars orbiters used for relay (Mars Odyssey, MRO, MAVEN) fly near-polar orbits. Do not switch to an equatorial orbit without first checking that both rovers still get regular contact.

## 5. Rover (surface asset) positions — fixed, real, named locations

| Rover | Latitude | Longitude | Real-world reference |
|---|---|---|---|
| Rover 1 | 18.4663° N | 77.4298° E | Jezero Crater (Perseverance's landing site) |
| Rover 2 | 4.5895° S | 137.4417° E | Gale Crater (Curiosity's landing site) |

These are fixed points on the Mars surface — they rotate with Mars (Mars-fixed frame), they do not move independently.

## 6. Simulation time span and resolution

- `SIM_DURATION_S = 2_592_000` (30 Earth days). Long enough to contain many orbital periods (~2 hours each) and more than one full Mars sidereal day (~24.6 hours), so the rover-orbiter geometry pattern repeats and can be sanity-checked.
- `TIME_STEP_S = 30` seconds. At a ~2-hour (7200s) orbital period, this gives roughly 240 samples per orbit — fine enough to not miss short contact windows, without making a month-long simulation too slow to run.
- Both are named config constants — must be trivially changeable without touching the rest of the code.

## 7. Coordinate math — exact formulas, do not approximate differently

**Rover position in the Mars-centered inertial frame at time `t`:**

1. Convert lat/long (`φ`, `λ`) to Mars-fixed Cartesian coordinates:
   ```
   x' = R_MARS_KM * cos(φ) * cos(λ)
   y' = R_MARS_KM * cos(φ) * sin(λ)
   z' = R_MARS_KM * sin(φ)
   ```
2. Rotate about the Mars polar (z) axis by the rotation angle accumulated since simulation start, `θ(t) = MARS_OMEGA_RAD_S * t`:
   ```
   x = x' * cos(θ) - y' * sin(θ)
   y = x' * sin(θ) + y' * cos(θ)
   z = z'   (unchanged — rotation is about the z-axis)
   ```
   (Assume the Mars-fixed frame and inertial frame are aligned at `t = 0` — an arbitrary but harmless reference choice.)

**Elevation angle of a satellite as seen from a rover** (used for the rover↔orbiter contact test in §8a):

1. Line-of-sight vector: `L = R_sat - R_rover` (both in the same inertial frame, computed via step above).
2. Local zenith direction at the rover: `zenith = R_rover / |R_rover|` (valid because Mars is modeled as a perfect sphere — the radial direction from Mars's center through the rover *is* local "straight up").
3. Angle between line-of-sight and zenith: `angle = arccos( (L · zenith) / |L| )`.
4. Elevation: `elevation_deg = 90 - degrees(angle)`. A satellite exactly overhead gives elevation ≈ 90°; a satellite at the horizon gives elevation ≈ 0°; a satellite below the horizon gives a negative value.

## 8. The three contact-window types — exact definitions

### 8a. Rover ↔ Orbiter
- Contact exists at a timestep if `elevation_deg > MIN_ELEVATION_DEG`, where `MIN_ELEVATION_DEG = 10` (a standard real-world threshold avoiding terrain-blocked or atmosphere-degraded low-angle contact — a config value, changeable later, not a hard physical law).

### 8b. Orbiter ↔ Orbiter (crosslink)
- Only check adjacent-in-true-anomaly pairs (§3's neighbor definition) — not all pairs against each other.
- Contact exists if a straight line between the two orbiters' positions does **not** pass through Mars's body: compute the closest approach distance of that line segment to the origin (Mars's center); if that distance is less than `R_MARS_KM`, Mars is blocking the link — no contact. Otherwise, contact exists.

### 8c. Orbiter ↔ Earth
- **Explicit simplification for this phase:** treat the Earth-direction as a single fixed unit vector for the entire 30-day run (`EARTH_DIRECTION_VECTOR`, pick any arbitrary fixed direction, e.g. along the reference x-axis of the orbital plane). This is reasonable because real Mars-Earth geometry changes slowly (over a ~26-month cycle) relative to a 30-day simulation window — but it must be clearly commented as a simplification, with a note that a future, higher-fidelity phase should replace it with real Earth ephemeris data.
- Contact exists if the same line-of-sight-past-Mars check from §8b shows Mars isn't blocking the path from the orbiter toward `EARTH_DIRECTION_VECTOR`.

## 9. Output format — exact structure required

One CSV per N value: `data/contact_windows_N{N}.csv`, with columns:

| Column | Meaning |
|---|---|
| `link_type` | one of `rover_orbiter`, `orbiter_orbiter`, `orbiter_earth` |
| `node_a` | e.g. `rover_1`, `orbiter_3` |
| `node_b` | e.g. `orbiter_2`, `earth` |
| `window_start_s` | seconds since simulation start |
| `window_end_s` | seconds since simulation start |

Each **contiguous run** of "in contact" timesteps for a given pair becomes exactly one row. Do not output one row per timestep — collapse consecutive in-contact steps into a single start/end window.

## 10. Validation — required before this phase counts as done

Write a separate validation script. For every N in `N_VALUES`, it must confirm:

1. **Every rover has at least one contact window with at least one orbiter somewhere in the 30-day run.** Zero contact for any rover means something is broken (most likely the polar-orbit or rotation math) — stop and flag it, don't proceed to later phases.
2. **A plausible count of windows** — with a ~2-hour orbital period and a polar orbit, expect roughly tens to low hundreds of rover-orbiter contact windows per rover over 30 days. Either extreme (zero, or "in contact basically all the time") indicates a bug.
3. **A visual sanity check** — plot (matplotlib) a simple horizontal-bar timeline per N showing when each rover has any contact, across the full 30-day span, for a human to eyeball.

## 11. What this phase explicitly does NOT include — do not build these yet

- No identity/cryptography (that's Phase 2).
- No gossip/propagation-model comparison (Phase 3).
- No anomaly detection (Phase 4).
- No multiple orbital planes — single plane only, per §3.
- No real Earth ephemeris — fixed direction vector only, per §8c.
- No Mars oblateness — perfect sphere only, per §7.

## 12. Suggested project structure

```
novasat-sim/
  README.md
  requirements.txt
  config.py                 # every constant above, in one place, named exactly as given
  orbital_mechanics.py       # hapsira-based orbit propagation wrapper
  constellation.py           # builds N orbiters + 2 fixed rovers
  contact_windows.py         # implements §8a/8b/8c, produces the CSVs in §9
  validate_contacts.py       # implements all checks in §10
  data/
    contact_windows_N1.csv
    contact_windows_N2.csv
    contact_windows_N4.csv
    contact_windows_N6.csv
    contact_windows_N8.csv
    contact_windows_N10.csv
```

## 13. Definition of done

- [ ] hapsira installed; Mars constants verified against §2
- [ ] `constellation.py` correctly spaces N orbiters for every value in `N_VALUES`
- [ ] `contact_windows.py` implements all three link types exactly as defined in §8
- [ ] Six output CSVs exist, correctly formatted per §9
- [ ] `validate_contacts.py` passes all three checks in §10, for all six N values
- [ ] Nothing listed in §11 has been built yet
