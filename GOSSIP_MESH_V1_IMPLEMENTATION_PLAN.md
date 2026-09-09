# NOVASAT — Gossip Mesh v1 — Implementation Plan

**Status:** DRAFT — awaiting human confirmation before any code is written.

---

## 1. Source Files Verified (per Required Process §4.1)

| File | Purpose | Key Findings |
|------|---------|--------------|
| `src/trust_store.py` | Per-satellite state (`SimNode`) | `SimNode` has `node_id`, `certificate`, `trust_store`, `_private_key` (Ed25519), `_x25519_private_key`, `x25519_public_key`, `is_isolated` flag, `sign(message)` method. **This is where warning tracking state will be added.** |
| `src/identity.py` | Cryptographic primitives | `sign_message()`, `verify_signature()`, `verify_certificate_chain()`, `create_root_ca()`, `create_csr()`, `sign_csr()`. **Reuse `sign_message` + `verify_signature` for warning signatures.** |
| `src/bpsec.py` | Message wrapping (BIB + BCB) | `wrap_bundle(payload, sender_ed25519_priv, sender_id, receiver_id, sender_x25519_priv, receiver_x25519_pub)` → returns dict with `sender_id`, `receiver_id`, `bib`, `bcb`. `unwrap_bundle()` verifies. **Reuse this exact mechanism for warning messages.** |
| `experiments/train_anomaly_models.py` | Anomaly detection models | `GaussianDensityModel.compute_scores()`, `IsolationForest.decision_function()`. Loaded in `server.py` as `AnomalyInferenceEngine.predict()` returning `{gaussian_score, iforest_score, ensemble_prob, anomaly_flag}`. **Trigger: `anomaly_flag == True` OR score above threshold.** |
| `src/contact_windows.py` | Contact schedule (offline) | Computes rover-orbiter, orbiter-orbiter, orbiter-earth windows. Used by batch experiments. |
| `src/propagation_models.py` | **Offline research code** (Model 1/2) | `SimulationState` with `pending_gossip`, `accusation_originators`, `accusation_weight_totals`, `trust_weights`. **This is batch research code — do NOT modify. The live gossip mesh is a separate, new implementation in `server.py`.** |
| `server.py` | Live simulation loop | `LiveSimulationEngine`: `process_bpsec_for_contact()` (returns `integrity_status`), `compute_tick_state()` (runs anomaly inference, conjunction assessment, comms decision), `init_bpsec_nodes()` (provisions all `SimNode`s). **Hook point: inside `process_bpsc_for_contact` and anomaly inference per orbiter.** |
| `web/ops_window.js` | Event log UI | Renders `ops_event_log` with types: `bundle`, `anomaly`, `override`. **New warning/flag events will appear here automatically if added to server's `event_log`.** |
| `config.py` | Constants | `GOSSIP_VOTE_K = 2` (but spec says T=3 for v1 — **needs confirmation**). |

---

## 2. Exact Data Structures to Add

### 2.1 In `SimNode` (src/trust_store.py)
```python
# ADD to SimNode.__init__:
self.warnings_seen: set[str] = set()           # warning_ids this node has already seen
self.warnings_issued: set[str] = set()         # warning_ids this node originated
self.accusations_received: dict[str, set[str]] = defaultdict(set)  # target_id -> set of issuer_ids
```

### 2.2 New Warning Message Format (new file: `src/gossip.py`)
```python
from dataclasses import dataclass
from typing import Literal
import json

@dataclass
class WarningMessage:
    warning_id: str          # deterministic: sha256(f"{issuer_id}|{target_id}|{sim_time:.3f}")[:16]
    issuer_id: str           # satellite raising the warning
    target_id: str           # satellite being warned about
    reason_code: Literal["ANOMALY_SCORE", "TAMPER_DETECTED"]
    evidence_value: float    # anomaly score (0-1) or 1.0 for tamper
    sim_time: float          # simulation time when issued
    
    def to_payload(self) -> bytes:
        return json.dumps({
            "warning_id": self.warning_id,
            "issuer_id": self.issuer_id,
            "target_id": self.target_id,
            "reason_code": self.reason_code,
            "evidence_value": self.evidence_value,
            "sim_time": self.sim_time,
        }, separators=(",", ":")).encode("utf-8")
    
    @staticmethod
    def from_payload(payload: bytes) -> "WarningMessage":
        d = json.loads(payload.decode("utf-8"))
        return WarningMessage(**d)
```

### 2.3 In `LiveSimulationEngine` (server.py)
```python
# ADD to __init__:
self.gossip_threshold_T: int = 3  # CONFIRM WITH HUMAN
self.pending_gossip: dict[str, list[WarningMessage]] = {nid: [] for nid in all_node_ids}
```

---

## 3. Exact Functions/Methods to Add or Modify

### 3.1 `src/gossip.py` — NEW FILE
```python
def create_warning_id(issuer_id: str, target_id: str, sim_time: float) -> str:
    """Deterministic warning ID so duplicates are recognized."""
    import hashlib
    s = f"{issuer_id}|{target_id}|{sim_time:.3f}"
    return hashlib.sha256(s.encode()).hexdigest()[:16]

def wrap_warning(warning: WarningMessage, sender_node: SimNode, receiver_id: str) -> dict:
    """Wrap warning using existing BPSec pipeline (Ed25519 BIB + AES-256-GCM BCB)."""
    payload = warning.to_payload()
    return wrap_bundle(
        payload,
        sender_node._private_key,
        warning.issuer_id,
        receiver_id,
        sender_node._x25519_private_key,
        sender_node.nodes[receiver_id].x25519_public_key  # need access to nodes dict
    )

def unwrap_warning(bundle: dict, receiver_node: SimNode, sender_id: str, ca_cert) -> WarningMessage | None:
    """Unwrap and verify warning. Returns WarningMessage or None if tampered/forged."""
    res = unwrap_bundle(bundle, receiver_node._x25519_private_key,
                        receiver_node.nodes[sender_id].x25519_public_key,
                        receiver_node.nodes[sender_id].certificate, ca_cert)
    if res["integrity_status"] != "verified":
        return None
    return WarningMessage.from_payload(res["plaintext"])
```

### 3.2 `src/trust_store.py` — MODIFY `SimNode`
- Add three fields in `__init__` (see §2.1)
- Add helper method:
```python
def record_warning_seen(self, warning_id: str, issuer_id: str, target_id: str) -> bool:
    """Returns True if this is a NEW distinct issuer for this target."""
    if warning_id in self.warnings_seen:
        return False
    self.warnings_seen.add(warning_id)
    self.accusations_received[target_id].add(issuer_id)
    return True

def distinct_issuer_count(self, target_id: str) -> int:
    return len(self.accusations_received.get(target_id, set()))
```

### 3.3 `server.py` — MODIFY `LiveSimulationEngine`

**A. In `__init__`:**
```python
self.gossip_threshold_T = 3  # CONFIRM
self.pending_gossip: dict[str, list[WarningMessage]] = {}
```

**B. In `init_bpsec_nodes()` after provisioning:**
```python
# Initialize pending_gossip for all nodes
all_ids = list(self.nodes.keys())
self.pending_gossip = {nid: [] for nid in all_ids}
```

**C. NEW METHOD: `check_and_generate_warnings(orbiter_state, contacts, t_sec)`**
```python
def check_and_generate_warnings(self, orbiters_state: list, active_contacts: list, t_sec: float):
    """Called each tick after anomaly inference and BPSec processing."""
    for orb in orbiters_state:
        node_id = orb["id"]
        node = self.nodes[node_id]
        inference = orb.get("inference", {})
        
        # Check each contact this node participated in
        for contact in active_contacts:
            if contact["node_a"] == node_id:
                peer_id = contact["node_b"]
            elif contact["node_b"] == node_id:
                peer_id = contact["node_a"]
            else:
                continue
            
            peer_node = self.nodes.get(peer_id)
            if not peer_node:
                continue
            
            # TRIGGER 1: Anomaly detection on peer's telemetry
            # Note: inference is for THIS node. To score peer, we'd need peer's inference.
            # For v1: if THIS node has anomaly_flag, it warns about ITSELF? No.
            # Correct: A warns about B when A observes B's data during contact.
            # Since inference runs per-node, we need to check peer's inference.
            peer_orb = next((o for o in orbiters_state if o["id"] == peer_id), None)
            if peer_orb:
                peer_inf = peer_orb.get("inference", {})
                if peer_inf.get("anomaly_flag", False):
                    self._issue_warning(node_id, peer_id, "ANOMALY_SCORE", 
                                       peer_inf.get("ensemble_prob", 0.0), t_sec)
            
            # TRIGGER 2: BPSec tamper detection on peer's bundle
            bpsec = contact.get("bpsec", {})
            if bpsec.get("integrity_status") == "tampered":
                # Which side sent the tampered bundle? The contact stores both directions?
                # bpsec result is for the pair. Assume tamper means peer's bundle failed.
                self._issue_warning(node_id, peer_id, "TAMPER_DETECTED", 1.0, t_sec)
```

**D. NEW METHOD: `_issue_warning(issuer_id, target_id, reason, evidence, t_sec)`**
```python
def _issue_warning(self, issuer_id: str, target_id: str, reason: str, evidence: float, t_sec: float):
    warning_id = create_warning_id(issuer_id, target_id, t_sec)
    issuer_node = self.nodes[issuer_id]
    
    # Don't duplicate if already issued
    if warning_id in issuer_node.warnings_issued:
        return
    
    warning = WarningMessage(
        warning_id=warning_id,
        issuer_id=issuer_id,
        target_id=target_id,
        reason_code=reason,
        evidence_value=evidence,
        sim_time=t_sec
    )
    issuer_node.warnings_issued.add(warning_id)
    
    # Add to local pending gossip
    self.pending_gossip[issuer_id].append(warning)
    
    # Log event
    event = {
        "type": "warning_issued",
        "sim_time_s": t_sec,
        "issuer_id": issuer_id,
        "target_id": target_id,
        "reason_code": reason,
        "evidence_value": evidence,
        "warning_id": warning_id
    }
    self.event_log.append(event)
    _append_ops_event(event)
```

**E. NEW METHOD: `propagate_gossip_on_contact(node_a, node_b, t_sec)`**
```python
def propagate_gossip_on_contact(self, node_a_id: str, node_b_id: str, t_sec: float):
    """Called during each contact event. Flood all warnings each node has."""
    node_a = self.nodes[node_a_id]
    node_b = self.nodes[node_b_id]
    
    # A -> B
    for warning in list(self.pending_gossip[node_a_id]):
        if warning.warning_id not in node_b.warnings_seen:
            # Wrap and send (simulated — in live, this happens over the contact link)
            wrapped = wrap_warning(warning, node_a, node_b_id)
            # Simulate unwrap/verify at receiver
            unwrapped = unwrap_warning(wrapped, node_b, node_a_id, self.ca_cert)
            if unwrapped:
                is_new = node_b.record_warning_seen(unwrapped.warning_id, unwrapped.issuer_id, unwrapped.target_id)
                self.pending_gossip[node_b_id].append(unwrapped)
                
                # Check threshold
                if node_b.distinct_issuer_count(unwrapped.target_id) >= self.gossip_threshold_T:
                    self._flag_target(node_b_id, unwrapped.target_id, t_sec)
    
    # B -> A (symmetric)
    for warning in list(self.pending_gossip[node_b_id]):
        if warning.warning_id not in node_a.warnings_seen:
            wrapped = wrap_warning(warning, node_b, node_a_id)
            unwrapped = unwrap_warning(wrapped, node_a, node_b_id, self.ca_cert)
            if unwrapped:
                is_new = node_a.record_warning_seen(unwrapped.warning_id, unwrapped.issuer_id, unwrapped.target_id)
                self.pending_gossip[node_a_id].append(unwrapped)
                
                if node_a.distinct_issuer_count(unwrapped.target_id) >= self.gossip_threshold_T:
                    self._flag_target(node_a_id, unwrapped.target_id, t_sec)
```

**F. NEW METHOD: `_flag_target(observer_id, target_id, t_sec)`**
```python
def _flag_target(self, observer_id: str, target_id: str, t_sec: float):
    """Called when distinct issuer count reaches threshold T."""
    # Check if already flagged by this observer
    if hasattr(self.nodes[observer_id], '_flagged_targets'):
        if target_id in self.nodes[observer_id]._flagged_targets:
            return
    else:
        self.nodes[observer_id]._flagged_targets = set()
    
    self.nodes[observer_id]._flagged_targets.add(target_id)
    
    # Log flag event for Ops Window
    event = {
        "type": "warning_flagged",
        "sim_time_s": t_sec,
        "observer_id": observer_id,
        "target_id": target_id,
        "distinct_issuers": self.nodes[observer_id].distinct_issuer_count(target_id),
        "threshold_T": self.gossip_threshold_T
    }
    self.event_log.append(event)
    _append_ops_event(event)
```

**G. INTEGRATION: Call from `compute_tick_state()`**
```python
# After anomaly inference loop and contact processing:
self.check_and_generate_warnings(orbiters_state, active_contacts, t_sec)

# During contact processing (inside the contact loops):
for contact in active_contacts:
    if contact["link_type"] != "orbiter_earth":
        self.propagate_gossip_on_contact(contact["node_a"], contact["node_b"], t_sec)
```

---

## 4. Integration Points in Existing Flow

| Location in `server.py` | What Happens | Where to Hook |
|------------------------|--------------|---------------|
| `compute_tick_state()` → anomaly inference loop | Each orbiter gets `inference` dict with `anomaly_flag` | After loop, call `check_and_generate_warnings()` |
| `process_bpsec_for_contact()` | Returns `integrity_status` ("verified"/"tampered"/etc) | Already called per contact; result in `active_contacts` |
| Contact loops (rover-orbiter, orbiter-orbiter) | `active_contacts` built with `bpsec` info | Inside loop, call `propagate_gossip_on_contact()` |
| `event_log` + `_append_ops_event()` | Events written to JSONL and sent to UI | `_issue_warning()` and `_flag_target()` already use this |

---

## 5. Validation Plan (per Required Process §4.2)

### 5.1 Positive Test — Genuine Misbehavior Propagates
1. Start simulation with N=6, default constellation
2. Inject `clock_drift` fault on `orbiter_0` (causes anomaly_flag=True)
3. Run until `orbiter_0` contacts `orbiter_1` → `orbiter_1` issues ANOMALY_SCORE warning
4. Run until `orbiter_1` contacts `orbiter_2` → `orbiter_2` receives warning (count=1)
5. Inject `clock_drift` on `orbiter_2` → `orbiter_2` also warns about `orbiter_0` (count=2)
6. Run until `orbiter_3` contacts either → receives both warnings (count=2)
7. Inject fault on `orbiter_3` or wait for contact → count reaches **T=3**
8. **Verify:** `warning_flagged` event appears in Ops Window event log for `orbiter_0`
9. **Verify:** `orbiter_3` (or whichever reaches T first) shows `distinct_issuer_count >= 3`

### 5.2 Negative Test — Colluders < T Do NOT Flag Healthy Node
1. Start simulation with N=6
2. Manually inject false warnings from `orbiter_0` and `orbiter_1` about healthy `orbiter_5` (simulate 2 colluders)
3. Run simulation through multiple contact windows
4. **Verify:** No `warning_flagged` event for `orbiter_5` ever appears
5. **Verify:** `distinct_issuer_count` for `orbiter_5` stays at 2 (< T=3) on all nodes

### 5.3 Positive Test — Colluders ≥ T DO Flag Healthy Node
1. Start simulation with N=6
2. Inject false warnings from `orbiter_0`, `orbiter_1`, `orbiter_2` about healthy `orbiter_5` (3 colluders = T)
3. Run simulation
4. **Verify:** `warning_flagged` event appears for `orbiter_5`
5. **Document:** This is the KNOWN LIMITATION (2 colluders can't, 3 can) — matches Track 1 research

### 5.4 Tamper Detection Trigger
1. Inject `bundle_tamper` fault on `orbiter_0`
2. Wait for contact with `orbiter_1`
3. **Verify:** `orbiter_1` issues `TAMPER_DETECTED` warning about `orbiter_0`
4. Verify propagation and flagging as above

### 5.5 Deduplication Test
1. Create scenario where same warning reaches a node via two different paths
2. **Verify:** `distinct_issuer_count` does NOT double-count (uses `warning_id` + `issuer_id`)

---

## 6. Open Questions & Assumptions (per Required Process §4.3)

| # | Question | Assumption Made | Needs Human Confirmation |
|---|----------|-----------------|--------------------------|
| 1 | **Threshold T value** | T=3 (spec says "reasonable starting point", config has GOSSIP_VOTE_K=2) | **YES — confirm T=3** |
| 2 | **Anomaly trigger** | Use `anomaly_flag` (ensemble_prob > 0.5) from `AnomalyInferenceEngine.predict()` | Confirm threshold is correct |
| 3 | **Tamper trigger** | `integrity_status == "tampered"` from `process_bpsec_for_contact()` | Confirm this is the right signal |
| 4 | **Warning wraps as BPSec bundle** | Reuse `wrap_bundle()`/`unwrap_bundle()` exactly | Confirm no new message type needed |
| 5 | **Warning ID format** | `sha256(issuer|target|sim_time)[:16]` deterministic | Confirm format OK |
| 6 | **Where to store `pending_gossip`** | In `LiveSimulationEngine` (server-side, not per-node) | Confirm — or per-node in `SimNode`? |
| 7 | **Contact direction for tamper** | `bpsec.integrity_status` applies to the pair; assume peer's bundle failed | Clarify if we can tell which side sent tampered data |
| 8 | **Rover participation** | Rovers are in `SimNode` but don't run anomaly inference — do they gossip? | Spec says "satellites" — assume orbiters only for v1 |
| 9 | **Ground station** | Ground doesn't originate/forward warnings in v1 | Confirm |
| 10 | **Warning TTL/expiry** | No expiry in v1 — warnings persist for simulation duration | Confirm |
| 11 | **Ops Window event types** | Add `warning_issued` and `warning_flagged` to existing event log | Confirm no new UI panel needed |

---

## 7. Files to Create / Modify

| File | Action |
|------|--------|
| `src/gossip.py` | **CREATE** — WarningMessage dataclass, wrap/unwrap, warning_id |
| `src/trust_store.py` | **MODIFY** — Add `warnings_seen`, `warnings_issued`, `accusations_received` to `SimNode` |
| `server.py` | **MODIFY** — Add `gossip_threshold_T`, `pending_gossip`, and 5 new methods to `LiveSimulationEngine`; hook into `compute_tick_state` |

---

## 8. Ready for Human Review

**Please confirm:**
1. Threshold **T = 3** (or different value)?
2. All open questions in §6 resolved as assumed, or provide corrections?
3. Proceed with implementation per this plan?

Once confirmed, I will implement in the order: `src/gossip.py` → `src/trust_store.py` → `server.py`, then run the validation tests from §5.