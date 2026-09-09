# NOVASAT — Automatic Swarm Reorganization v1 — Implementation Plan

**Status:** CONFIRMED — proceeding to implementation.

---

## 1. Source Files Verified (per Required Process §4.1)

| File | Purpose | Key Findings |
|------|---------|--------------|
| src/trust_store.py | Per-satellite state (SimNode) | SimNode has is_isolated: bool = False flag. This is where we will add reorganization tracking fields. |
| server.py | Live simulation loop | Override handler at lines 1249-1271: target_node.is_isolated = (override_action == isolate) + event log. Hook point for triggering reorganization. |
| server.py | set_satellite_elements | Sets altitude_km, inclination_deg, raan_deg, true_anomaly_deg per orbiter index. Stores in self.custom_elements[orbiter_index]. Mechanism for changing true anomaly. |
| src/conjunction_assessment.py | Collision risk (Pc) | evaluate_all_pairs_conjunction(satellites_state, lookahead_sec, triage_model) returns risks with pc, miss_distance_km, is_trigger. Can be reused for safety check on planned positions. |
| server.py | Auto-maneuver (collision) | At lines 1150-1180: when Pc > 1e-4, calls set_satellite_elements(sat_a_idx, new_alt, curr_inc) for +2km altitude boost. Existing pattern to extend for true-anomaly maneuvers. |
| web/app_3d.js | Frontend rendering | updateOrbiter(id, lat, lon, altKm, isCompromised, faultType) updates position/color. setContactLink for visual links. Visual states need extension for reorganizing/settled. |
| web/ops_window.js | Event log UI | Renders ops_event_log with types: bundle, anomaly, override. New event types: reorg_triggered, reorg_maneuver_start, reorg_maneuver_complete, reorg_complete, reorg_paused_safety. |
| src/conjunction_assessment.py | Pc computation | evaluate_all_pairs_conjunction takes satellites_state list with cartesian_km and optionally velocity_vector_km_s. Can accept hypothetical planned positions for safety check. |

---

## 2. Exact Data Structures to Add

### 2.1 In SimNode (src/trust_store.py)
```python
# ADD to SimNode.__init__:
self.reorg_state: str = "none"           # "none" | "reorganizing" | "settled" | "parked"
self.reorg_target_nu_deg: float = None   # Target true anomaly for reorganization
self.reorg_start_time: float = None      # Simulation time when maneuver started
self.reorg_duration_s: float = 0.0       # Planned maneuver duration
```

### 2.2 In LiveSimulationEngine (server.py)
```python
# ADD to __init__:
self.reorg_active: bool = False
self.reorg_plan: dict = {}               # target_id, affected_orbiters[], target_nus[], start_time, duration_s
self.reorg_safety_check_passed: bool = False
self.reorg_maneuver_duration_s: float = 300.0  # 5 minutes default for smooth animation
```

### 2.3 In config.py (new constants, per Rule 7)
```python
# Live Automatic Swarm Reorganization v1 — new constants
REORG_MANEUVER_DURATION_S = 300.0      # 5 minutes sim-time for smooth true-anomaly transition
REORG_SAFETY_PC_THRESHOLD = 1e-4       # Same as collision avoidance trigger
REORG_MIN_SEPARATION_DEG = 5.0         # Minimum angular separation to maintain (deg)
```

---

## 3. Exact Functions/Methods to Add or Modify

### 3.1 src/trust_store.py — MODIFY SimNode
- Add 4 fields in __init__ (see 2.1)
- No new methods needed

### 3.2 config.py — ADD constants
```python
# Live Automatic Swarm Reorganization v1
REORG_MANEUVER_DURATION_S = 300.0      # 5 minutes sim-time for smooth true-anomaly transition
REORG_SAFETY_PC_THRESHOLD = 1e-4       # Same as collision avoidance trigger
REORG_MIN_SEPARATION_DEG = 5.0         # Minimum angular separation to maintain (deg)
```
Add to __all__ list.

### 3.3 server.py — MODIFY LiveSimulationEngine

**A. In __init__:**
```python
from config import REORG_MANEUVER_DURATION_S, REORG_SAFETY_PC_THRESHOLD, REORG_MIN_SEPARATION_DEG
# ...
self.reorg_active: bool = False
self.reorg_plan: dict = {}
self.reorg_safety_check_passed: bool = False
self.reorg_maneuver_duration_s: float = REORG_MANEUVER_DURATION_S
```

**B. In init_bpsec_nodes after node provisioning:**
```python
# Initialize reorg_state for all nodes
for nid in all_ids:
    self.nodes[nid].reorg_state = "none"
    self.nodes[nid].reorg_target_nu_deg = None
    self.nodes[nid].reorg_start_time = None
    self.nodes[nid].reorg_duration_s = 0.0
```

**C. NEW METHOD: _compute_even_spacing_plan(isolated_id, t_sec)**
```python
def _compute_even_spacing_plan(self, isolated_id: str, t_sec: float) -> dict:
    # 1. Get isolated satellite's orbital elements
    iso_idx = int(isolated_id.replace("orbiter_", ""))
    iso_elem = self.custom_elements.get(iso_idx, {})
    iso_alt = iso_elem.get("altitude_km", 400.0)
    iso_inc = iso_elem.get("inclination_deg", 90.0)
    iso_raan = iso_elem.get("raan_deg", 0.0)
    
    # 2. Find all non-isolated orbiters in SAME plane (same alt, inc, raan within tolerance)
    TOL_DEG = 0.01
    affected = []
    for i in range(self.n):
        oid = f"orbiter_{i}"
        if oid == isolated_id:
            continue
        node = self.nodes[oid]
        if node.is_isolated:
            continue
        elem = self.custom_elements.get(i, {})
        alt = elem.get("altitude_km", 400.0)
        inc = elem.get("inclination_deg", 90.0)
        raan = elem.get("raan_deg", 0.0)
        if (abs(alt - iso_alt) < TOL_DEG and 
            abs(inc - iso_inc) < TOL_DEG and 
            abs(raan - iso_raan) < TOL_DEG):
            affected.append(i)
    
    # 3. Compute current true anomalies for affected + isolated
    # Get from orbiters_state (passed in or computed)
    current_nus = {}
    for idx in affected + [iso_idx]:
        oid = f"orbiter_{idx}"
        # Get current true anomaly from custom_elements or compute
        elem = self.custom_elements.get(idx, {})
        current_nu = elem.get("true_anomaly_deg")
        if current_nu is None:
            default_nu = idx * (360.0 / self.n)
            current_nu = default_nu
        current_nus[idx] = current_nu
    
    # 4. Sort affected by current true anomaly, remove isolated, recompute even spacing
    # Sort affected by current true anomaly
    affected_sorted = sorted(affected, key=lambda idx: current_nus[idx])
    num_affected = len(affected_sorted)
    if num_affected == 0:
        return {
            "isolated_id": isolated_id,
            "affected_indices": [],
            "target_nus": {},
            "plane_key": (iso_alt, iso_inc, iso_raan),
            "start_time": t_sec,
            "duration_s": self.reorg_maneuver_duration_s,
        }
    
    # Even spacing: 360 / num_affected degrees apart
    spacing = 360.0 / num_affected
    # Choose reference: start from the first affected satellite's current position
    # and distribute evenly from there
    start_nu = current_nus[affected_sorted[0]]
    target_nus = {}
    for i, idx in enumerate(affected_sorted):
        target_nu = (start_nu + i * spacing) % 360.0
        target_nus[idx] = target_nu
    
    # 5. Return plan dict
    return {
        "isolated_id": isolated_id,
        "affected_indices": affected_sorted,
        "target_nus": target_nus,
        "plane_key": (iso_alt, iso_inc, iso_raan),
        "start_time": t_sec,
        "duration_s": self.reorg_maneuver_duration_s,
    }
```

**D. NEW METHOD: _check_reorg_safety(plan, orbiters_state)**
```python
def _check_reorg_safety(self, plan: dict, orbiters_state: list) -> bool:
    """
    Build hypothetical future state with target_nus applied, run conjunction assessment.
    Returns True if all pairwise Pc < REORG_SAFETY_PC_THRESHOLD.
    """
    # Build hypothetical satellites_state with target_nus applied
    hypothetical_state = []
    for orb in orbiters_state:
        oid = orb["id"]
        idx = int(oid.replace("orbiter_", ""))
        hyp_orb = dict(orb)
        if idx in plan["target_nus"]:
            # Compute hypothetical position at target true anomaly
            elem = self.custom_elements.get(idx, {})
            alt = elem.get("altitude_km", 400.0)
            inc = elem.get("inclination_deg", 90.0)
            raan = elem.get("raan_deg", 0.0)
            target_nu = plan["target_nus"][idx]
            # Compute position at target_nu (same as compute_tick_state math)
            a_orbit = R_MARS_KM + alt
            nu_rad = math.radians(target_nu)
            inc_rad = math.radians(inc)
            raan_rad = math.radians(raan)
            cos_u = math.cos(nu_rad)
            sin_u = math.sin(nu_rad)
            cos_O = math.cos(raan_rad)
            sin_O = math.sin(raan_rad)
            cos_i = math.cos(inc_rad)
            sin_i = math.sin(inc_rad)
            x_mci = a_orbit * (cos_u * cos_O - sin_u * sin_O * cos_i)
            y_mci = a_orbit * (cos_u * sin_O + sin_u * cos_O * cos_i)
            z_mci = a_orbit * (sin_u * sin_i)
            theta = MARS_OMEGA_RAD_S * self.sim_time_s  # current time
            x_fixed = x_mci * math.cos(theta) + y_mci * math.sin(theta)
            y_fixed = -x_mci * math.sin(theta) + y_mci * math.cos(theta)
            z_fixed = z_mci
            hyp_orb["cartesian_km"] = [float(x_fixed), float(y_fixed), float(z_fixed)]
            # Velocity vector at target position
            v_mag = math.sqrt(MU_MARS_KM3_S2 / a_orbit)
            vel_vec = np.array([-z_mci / a_orbit, 0.0, x_mci / a_orbit], dtype=np.float64) * v_mag
            hyp_orb["velocity_vector_km_s"] = vel_vec.tolist()
        hypothetical_state.append(hyp_orb)
    
    # Run conjunction assessment on hypothetical state
    res = evaluate_all_pairs_conjunction(hypothetical_state, lookahead_sec=86400.0, triage_model=self.triage_model)
    for risk in res["risks"]:
        if risk["pc"] >= REORG_SAFETY_PC_THRESHOLD:
            print(f"[Reorg Safety] BLOCKED: {risk['sat_A']}--{risk['sat_B']} Pc={risk['pc']:.2e} >= threshold")
            return False
    return True
```

**E. NEW METHOD: _trigger_reorganization(isolated_id, t_sec)**
```python
def _trigger_reorganization(self, isolated_id: str, t_sec: float):
    """Called when a satellite becomes isolated. Computes plan, checks safety, starts reorg."""
    # 1. Compute plan using current orbiters_state
    orbiters_state = self._get_current_orbiters_state()  # helper to extract from last tick
    plan = self._compute_even_spacing_plan(isolated_id, t_sec)
    
    if not plan["affected_indices"]:
        print(f"[Reorg] No affected orbiters in same plane as {isolated_id}")
        return
    
    # 2. Safety check
    orbiters_state = self._get_current_orbiters_state()
    if not self._check_reorg_safety(plan, orbiters_state):
        # Log safety pause event
        event = {
            "type": "reorg_paused_safety",
            "sim_time_s": t_sec,
            "isolated_id": isolated_id,
            "reason": "Planned reorganization would violate Pc threshold"
        }
        self.event_log.append(event)
        _append_ops_event(event)
        self.reorg_safety_check_passed = False
        return
    
    # 3. Safety passed — activate plan
    self.reorg_safety_check_passed = True
    self.reorg_active = True
    self.reorg_plan = plan
    
    # 4. Set target_nu on each affected node, mark reorg_state
    for idx in plan["affected_indices"]:
        oid = f"orbiter_{idx}"
        node = self.nodes[oid]
        target_nu = plan["target_nus"][idx]
        node.reorg_target_nu_deg = target_nu
        node.reorg_state = "reorganizing"
        node.reorg_start_time = t_sec
        node.reorg_duration_s = self.reorg_maneuver_duration_s
    
    # 5. Log reorg triggered event
    event = {
        "type": "reorg_triggered",
        "sim_time_s": t_sec,
        "isolated_id": isolated_id,
        "affected": [f"orbiter_{i}" for i in plan["affected_indices"]],
        "target_nus": {f"orbiter_{k}": v for k, v in plan["target_nus"].items()},
        "duration_s": self.reorg_maneuver_duration_s
    }
    self.event_log.append(event)
    _append_ops_event(event)
    print(f"[Reorg] TRIGGERED by {isolated_id}: {len(plan['affected_indices'])} orbiters repositioning over {self.reorg_maneuver_duration_s}s")
```

**F. NEW METHOD: _execute_reorg_maneuvers(t_sec)**
```python
def _execute_reorg_maneuvers(self, t_sec: float):
    """Advance each reorganizing satellite toward its target true anomaly."""
    if not self.reorg_active or not self.reorg_plan:
        return
    
    all_complete = True
    for idx in self.reorg_plan["affected_indices"]:
        oid = f"orbiter_{idx}"
        node = self.nodes[oid]
        if node.reorg_state != "reorganizing":
            continue
        
        target_nu = node.reorg_target_nu_deg
        elem = self.custom_elements.get(idx, {})
        current_nu = elem.get("true_anomaly_deg")
        if current_nu is None:
            # Compute from default
            default_nu = idx * (360.0 / self.n)
            current_nu = default_nu
        
        elapsed = t_sec - node.reorg_start_time
        progress = min(1.0, elapsed / node.reorg_duration_s)
        
        # Smooth interpolation (ease-in-out)
        eased = progress * progress * (3.0 - 2.0 * progress)
        # Shortest angular path
        diff = (target_nu - current_nu + 180) % 360 - 180
        new_nu = (current_nu + diff * eased) % 360
        
        # Update custom_elements with new true anomaly
        elem["true_anomaly_deg"] = new_nu
        self.custom_elements[idx] = elem
        
        # Mark as maneuvering for UI
        # (will be picked up in compute_tick_state)
        
        if progress >= 1.0:
            node.reorg_state = "settled"
            node.reorg_target_nu_deg = None
            
            # Log maneuver complete
            event = {
                "type": "reorg_maneuver_complete",
                "sim_time_s": t_sec,
                "satellite_id": f"orbiter_{idx}",
                "target_nu_deg": target_nu
            }
            self.event_log.append(event)
            _append_ops_event(event)
        else:
            all_complete = False
    
    # Check if all complete
    if all_complete:
        self.reorg_active = False
        self.reorg_plan = {}
        
        # Log reorg complete
        event = {
            "type": "reorg_complete",
            "sim_time_s": t_sec,
            "isolated_id": self.reorg_plan.get("isolated_id"),
            "affected_count": len(self.reorg_plan.get("affected_indices", []))
        }
        self.event_log.append(event)
        _append_ops_event(event)
        print(f"[Reorg] COMPLETE: all satellites settled")
```

**G. MODIFY: Override handler (lines ~1249-1271)**
```python
elif action in ("override", "type_override"):
    # ... existing code ...
    if target_node and override_action in ("isolate", "clear"):
        was_isolated = target_node.is_isolated
        target_node.is_isolated = (override_action == "isolate")
        sim_engine.ops_window_totals["ground_overrides"] += 1
        
        # NEW: Trigger reorganization on isolate
        if override_action == "isolate" and not was_isolated:
            self._trigger_reorganization(sat_id, self.sim_time_s)
        
        # NEW: Clear reorg state on clear
        if override_action == "clear" and was_isolated:
            target_node.reorg_state = "none"
            target_node.reorg_target_nu_deg = None
            target_node.reorg_start_time = None
            target_node.reorg_duration_s = 0.0
        
        # ... rest of existing override logging
```

**H. MODIFY: compute_tick_state — call reorg execution**
```python
# After conjunction assessment, before return:
# Execute reorganization maneuvers
self._execute_reorg_maneuvers(t_sec)

# Add reorg_state to each orbiter's output for UI
for orb in orbiters_state:
    node = self.nodes.get(orb["id"])
    if node:
        orb["reorg_state"] = node.reorg_state
        orb["reorg_target_nu_deg"] = node.reorg_target_nu_deg
```

**I. MODIFY: compute_tick_state — add maneuvering flag for reorganizing satellites**
```python
# In orbiter state construction, add:
"reorg_state": node.reorg_state,
"reorg_target_nu_deg": node.reorg_target_nu_deg,
# Existing "maneuvering" flag used for collision avoidance; keep separate
```

---

## 4. Frontend Changes

### 4.1 web/app_3d.js — MODIFY Mars3DRenderer

**A. Extend updateOrbiter to handle reorg states:**
```javascript
updateOrbiter(id, lat, lon, altKm, isCompromised = false, faultType = "none", reorgState = "none", reorgTargetNu = null) {
    // ... existing code ...
    // Color coding:
    // - parked (isolated) = DARK GRAY (#555555)
    // - reorganizing = CORAL (#FF7F50) with trail
    // - settled = SPRING GREEN (#00FF7F) briefly, then normal CYAN
    // - none = normal CYAN
    
    let orbiterColor = Cesium.Color.CYAN;
    let labelSuffix = "";
    let showTrail = false;
    
    if (reorgState === "parked" || isCompromised) {
        orbiterColor = Cesium.Color.fromCssColorString("#555555"); // Dark Gray
        labelSuffix = " 🔒 PARKED";
    } else if (reorgState === "reorganizing") {
        orbiterColor = Cesium.Color.fromCssColorString("#FF7F50"); // Coral
        labelSuffix = " ⟳ REORG";
        showTrail = true; // Show projected path to target
    } else if (reorgState === "settled") {
        orbiterColor = Cesium.Color.fromCssColorString("#00FF7F"); // Spring Green
        labelSuffix = " ✓ SETTLED";
    } else if (isCompromised) {
        orbiterColor = Cesium.Color.RED;
        labelSuffix = ` ⚠️ [${faultType}]`;
    }
    
    // ... update entity ...
    if (showTrail && reorgTargetNu) {
        // Draw dashed line from current position to target position
        this._drawReorgTrail(id, lat, lon, altKm, reorgTargetNu);
    }
}
```

**B. NEW METHOD: _drawReorgTrail**
```javascript
_drawReorgTrail(id, lat, lon, altKm, targetNu) {
    // Compute target position from targetNu (need to send target position from server)
    // Draw dashed line from current to target
    // For now, compute client-side using same orbital math
    // This is a simplified implementation - full version would use server-provided target position
}
```

### 4.2 web/ops_window.js — MODIFY OpsWindow

**A. Add new event types to _appendEventLogRows:**
```javascript
} else if (ev.type === 'reorg_triggered') {
    typeLabel = '🔄 reorg';
    details   = `iso:${ev.isolated_id} affected:${ev.affected.length}`;
    status    = `dur:${ev.duration_s}s`;
    rowClass = 'ops-row-reorg';
} else if (ev.type === 'reorg_maneuver_complete') {
    typeLabel = '✅ reorg-done';
    details   = ev.satellite_id;
    status    = `nu:${ev.target_nu_deg.toFixed(1)}°`;
    rowClass = 'ops-row-reorg-ok';
} else if (ev.type === 'reorg_complete') {
    typeLabel = '🏁 reorg-complete';
    details   = `iso:${ev.isolated_id}`;
    status    = `affected:${ev.affected_count}`;
    rowClass = 'ops-row-reorg-ok';
} else if (ev.type === 'reorg_paused_safety') {
    typeLabel = '🛑 reorg-paused';
    details   = `iso:${ev.isolated_id}`;
    status    = ev.reason;
    rowClass = 'ops-row-reorg-warn';
}
```

**B. Add reorg_state column to node table** (optional, for visibility)

---

## 5. Integration Points in Existing Flow

| Location | What Happens | Hook |
|----------|--------------|------|
| Override handler (server.py:1249) | Human isolates satellite via Ops Window | Call _trigger_reorganization(sat_id, t_sec) |
| compute_tick_state | Each tick after conjunction assessment | Call _execute_reorg_maneuvers(t_sec) |
| compute_tick_state output | Sent to frontend via WS | Include reorg_state, reorg_target_nu_deg per orbiter |
| evaluate_all_pairs_conjunction | Safety check on hypothetical state | Reuse in _check_reorg_safety |
| set_satellite_elements | Used by collision avoidance for altitude | Extend to support true_anomaly_deg updates during reorg |
| Ops Window event log | Renders ops_event_log | New event types auto-rendered |
| updateOrbiter (app_3d.js) | Visual state per tick | Read reorg_state, reorg_target_nu_deg |

---

## 6. Validation Plan (per Required Process §4.2)

### 6.1 Positive Test — Single Isolation Triggers Reorg
1. Start N=6, default constellation
2. Via Ops Window, isolate `orbiter_2`
3. **Verify:** `reorg_triggered` event logged with affected=4 (orbiter_0,1,3,4,5 minus isolated)
4. **Verify:** `orbiter_0,1,3,4,5` show `reorg_state="reorganizing"` and move smoothly over ~5 min
5. **Verify:** After ~5 min, all show `reorg_state="settled"` then return to normal
6. **Verify:** `reorg_complete` event logged with affected_count=5
7. **Verify:** Final true anomalies are evenly spaced (360/5 = 72° apart)

### 6.2 Negative Test — Safety Check Blocks Unsafe Plan
1. Construct scenario where isolated satellite's removal would force two remaining satellites too close (e.g., N=3, isolate middle one → remaining two would be 180° apart, which is fine; need N=4 with specific configuration)
2. Isolate satellite
3. **Verify:** `reorg_paused_safety` event logged
4. **Verify:** No satellites enter `reorganizing` state
5. **Verify:** Ops Window shows safety pause alert

### 6.3 Test — Multiple Planes Not Affected
1. Set N=4: orbiter_0,1 at alt=400, inc=90; orbiter_2,3 at alt=800, inc=45
2. Isolate orbiter_0 (in 400km plane)
3. **Verify:** Only orbiter_1 reorganizes (same plane); orbiter_2,3 unchanged

### 6.4 Test — Clear Isolation Resets State
1. Isolate orbiter_2 → reorg completes
2. Clear isolation on orbiter_2
3. **Verify:** orbiter_2 `reorg_state` = "none", no maneuver triggered

### 6.5 Visual Test — Three States Distinguishable
1. During reorg, watch 3D view
2. **Verify:** Reorganizing satellites show pulsing coral + trail to target
2. **Verify:** Settled satellites show spring green checkmark briefly
3. **Verify:** Isolated satellite shows dark gray "PARKED" label

### 6.6 NEW: Interpolation Correctness Test — New Ease-In-Out Logic
1. During a reorg maneuver, sample satellite positions at multiple points (t=0%, 25%, 50%, 75%, 100% of duration)
2. **Verify:** No overshoot — interpolated true anomaly never exceeds target (for shortest-path interpolation)
3. **Verify:** No discontinuous jumps — position changes smoothly between consecutive samples (delta < threshold)
4. **Verify:** At t=100%, position equals target exactly (within floating-point epsilon)
4. **Verify:** Velocity (delta position/delta time) follows ease-in-out curve: slow start, fast middle, slow end

---

## 7. Open Questions & Assumptions (per Required Process §4.3)

| # | Question | Assumption Made | Status |
|---|----------|-----------------|--------|
| 1 | **Gap redistribution**: full recompute vs local shift? | Full recompute (even spacing all affected) — simpler, more predictable | CONFIRMED |
| 2 | **Safety check**: reuse evaluate_all_pairs_conjunction on hypothetical state? | Yes — function accepts arbitrary satellites_state with cartesian_km | CONFIRMED feasible |
| 3 | **Animation duration**: 300s (5 min) default? | Configurable via REORG_MANEUVER_DURATION_S | CONFIRMED (sim-time) |
| 4 | **Visual trail**: how to draw projected path in Cesium? | Need target position from server; add reorg_target_position to orbiter output | To implement in frontend |
| 5 | **Isolated satellite visual**: gray vs red? | Dark Gray (#555555) for parked | CONFIRMED |
| 6 | **Settled state duration**: how long green checkmark? | 30 seconds then auto-clear to normal | CONFIRMED |
| 7 | **Concurrent reorgs**: two isolations close in time? | v1 scope: single isolation only; second waits | CONFIRMED |
| 8 | **Minimum separation**: REORG_MIN_SEPARATION_DEG used? | Not yet used in plan; could enforce in spacing | Optional for v1 |
| 9 | **Velocity vector during reorg**: for safety check | Need velocity_vector_km_s in hypothetical state | Included in plan |
| 10 | **Ops Window totals**: add reorg counters? | Add reorgs_executed, reorgs_paused_safety | CONFIRMED |

---

## 8. Files to Create / Modify

| File | Action |
|------|--------|
| config.py | ADD 3 new constants |
| src/trust_store.py | MODIFY SimNode.__init__ (add 4 fields) |
| server.py | MODIFY LiveSimulationEngine (add fields, 6 new methods, hook override + tick) |
| web/app_3d.js | MODIFY updateOrbiter, add _drawReorgTrail |
| web/ops_window.js | MODIFY _appendEventLogRows (add 5 event types), optionally _renderNodeTable |

---

## 9. Implementation Order & Validation

**Implementation Order:**
1. `config.py` — Add 3 constants
2. `src/trust_store.py` — Add 4 fields to SimNode
3. `server.py` — Add fields, 6 methods, hook override + tick
4. `web/app_3d.js` — Extend updateOrbiter, add _drawReorgTrail
5. `web/ops_window.js` — Add 5 event types

**Validation Suite (run in order):**
1. `python tests/verify_bpsec.py` — BPSec regression
2. `python tests/validate_identity.py` — Identity regression
3. `python tests/verify_3d_live.py` — 3D live regression
4. `python tests/validate_phase2_collision_avoidance.py` — Collision avoidance regression
5. `python tests/validate_phase3.py` — Phase 3 (gossip mesh) regression
6. **NEW: Manual reorg tests** — Run positive/negative/visual/interpolation tests from §6

**Required Output:** Real logs/output for each test, not just pass/fail summary.