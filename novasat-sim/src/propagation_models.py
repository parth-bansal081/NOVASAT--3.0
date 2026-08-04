"""
NOVASAT Phase 3 — Propagation Models

Implements Model 1 (Ground-authenticated only) and Model 2 (Gossip-based,
peer-originated) trust revocation propagation per §2 of the Phase 3 build spec.

Both models share:
- The same Phase 1 contact-window schedule (read, never regenerated).
- The always-on reactive layer (§3): if a node directly receives a bad-signature
  message from a peer, it immediately distrusts that peer locally.

The difference is entirely about who can originate a trust update that other
nodes will act on.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import copy
import pandas as pd
from collections import defaultdict

from config import (
    N_VALUES,
    SIM_DURATION_S,
    GOSSIP_VOTE_K,
    TRUST_WEIGHT_THRESHOLD,
    TRUST_WEIGHT_CONFIRM_FACTOR,
    TRUST_WEIGHT_DECAY_FACTOR,
)


# ---------------------------------------------------------------------------
# Schedule loading
# ---------------------------------------------------------------------------

def load_contact_schedule(n: int) -> list[dict]:
    """
    Reads data/contact_windows_N{n}.csv and returns a list of contact events
    sorted by window_start_s.

    Each event dict has keys:
        link_type, node_a, node_b, window_start_s, window_end_s
    """
    csv_path = os.path.join("data", f"contact_windows_N{n}.csv")
    df = pd.read_csv(csv_path)
    # Sort by start time (primary) and then by link_type for determinism
    df = df.sort_values(by=["window_start_s", "link_type", "node_a", "node_b"]).reset_index(drop=True)
    return df.to_dict("records")


def get_active_nodes(n: int) -> list[str]:
    """
    Returns the list of node IDs active for a given N.
    Per Phase 2 addendum: orbiter_0 .. orbiter_{n-1} + rover_1 + rover_2.
    """
    orbiters = [f"orbiter_{i}" for i in range(n)]
    rovers = ["rover_1", "rover_2"]
    return orbiters + rovers


# ---------------------------------------------------------------------------
# Simulation state
# ---------------------------------------------------------------------------

class SimulationState:
    """
    Tracks the per-node trust state during a single trial.

    Attributes:
        active_nodes: list of node IDs in this trial's pool.
        compromised_node: the node that has been compromised.
        compromise_time: the simulation-second at which the compromise occurs.

        revoked:  dict[node_id] -> set of node_ids that this node considers revoked.
        revoked_times: dict[node_id] -> dict[target] -> timestamp when revoked.

        # Gossip-specific state (only populated under Model 2):
        pending_gossip: dict[node_id] -> list of accusation messages to relay.
        accusation_originators: dict[node_id] -> dict[accused] -> set of accuser IDs
            Tracks distinct accusers a node has heard from, for fixed-threshold.
        accusation_weight_totals: dict[node_id] -> dict[accused] -> float
            Running weight total for trust-weighted / decay conditions.
        trust_weights: dict[node_id] -> dict[other_node] -> float
            Trust weight each node assigns to every other node (for trust-weighted / decay).
        ground_revoked: bool — True once ground has been notified and issued a revocation.
        ground_revocation_available_at: float — timestamp when ground revocation becomes
            available (i.e., when the first detecting orbiter contacts Earth).
        nodes_with_ground_revocation: set of node IDs that have received the
            ground-signed revocation message.
    """

    def __init__(self, active_nodes: list[str], compromised_node: str, compromise_time: float):
        self.active_nodes = active_nodes
        self.compromised_node = compromised_node
        self.compromise_time = compromise_time

        # Per-node revocation sets
        self.revoked: dict[str, set[str]] = {nid: set() for nid in active_nodes}
        self.revoked_times: dict[str, dict[str, float]] = {nid: {} for nid in active_nodes}

        # Gossip state
        self.pending_gossip: dict[str, list[tuple[str, str, float]]] = {nid: [] for nid in active_nodes}
        # pending_gossip[node] = list of (accuser_id, accused_id, timestamp)

        self.accusation_originators: dict[str, dict[str, set[str]]] = {
            nid: defaultdict(set) for nid in active_nodes
        }
        self.accusation_weight_totals: dict[str, dict[str, float]] = {
            nid: defaultdict(float) for nid in active_nodes
        }
        self.trust_weights: dict[str, dict[str, float]] = {
            nid: {other: 1.0 for other in active_nodes if other != nid}
            for nid in active_nodes
        }

        # Ground revocation tracking
        self.ground_revoked = False
        self.ground_revocation_available_at = float("inf")
        self.nodes_with_ground_revocation: set[str] = set()
        # Track which nodes have directly detected the compromise (§3 reactive)
        self.detected_by: set[str] = set()

    def mark_revoked(self, observer: str, target: str, timestamp: float):
        """Mark *target* as revoked in *observer*'s trust store at *timestamp*."""
        if target not in self.revoked[observer]:
            self.revoked[observer].add(target)
            self.revoked_times[observer][target] = timestamp

    def all_know(self, target: str) -> bool:
        """True when every node (except the target itself) has revoked the target."""
        for nid in self.active_nodes:
            if nid == target:
                continue
            if target not in self.revoked[nid]:
                return False
        return True

    def last_revocation_time(self, target: str) -> float:
        """Timestamp of the last node to revoke the target. Returns inf if not all know."""
        t_max = 0.0
        for nid in self.active_nodes:
            if nid == target:
                continue
            if target not in self.revoked_times[nid]:
                return float("inf")
            t_max = max(t_max, self.revoked_times[nid][target])
        return t_max


# ---------------------------------------------------------------------------
# Model 1 — Ground-authenticated only (§2, Model 1)
# ---------------------------------------------------------------------------

def run_model1_propagation(
    schedule: list[dict],
    active_nodes: list[str],
    compromised_node: str,
    compromise_time: float,
) -> float:
    """
    Simulate Model 1 revocation propagation.

    Returns the propagation time in seconds (last node learns − compromise time),
    or float('inf') if not everyone learned within the 30-day window.
    """
    state = SimulationState(active_nodes, compromised_node, compromise_time)
    active_set = set(active_nodes)

    for event in schedule:
        t_start = event["window_start_s"]
        node_a = event["node_a"]
        node_b = event["node_b"]
        link_type = event["link_type"]

        # Skip events before compromise
        if t_start < compromise_time:
            continue

        # Only consider events involving active nodes
        # (node_b can be "earth" for orbiter_earth links)
        if node_a not in active_set:
            continue
        if link_type != "orbiter_earth" and node_b not in active_set:
            continue

        # --- §3 Reactive layer: direct detection ---
        # If one of the two nodes is the compromised node, the other detects it.
        if link_type != "orbiter_earth":
            if node_a == compromised_node and node_b != compromised_node:
                # node_b detects compromise
                state.mark_revoked(node_b, compromised_node, t_start)
                state.detected_by.add(node_b)
            elif node_b == compromised_node and node_a != compromised_node:
                # node_a detects compromise
                state.mark_revoked(node_a, compromised_node, t_start)
                state.detected_by.add(node_a)

        # --- Ground revocation path ---
        # Step 1: A detecting orbiter contacts Earth -> ground learns
        if link_type == "orbiter_earth" and node_b == "earth":
            orbiter = node_a
            if orbiter in state.detected_by and not state.ground_revoked:
                # Ground now knows; it issues a signed revocation.
                # The orbiter receives it in this same contact window.
                state.ground_revoked = True
                state.ground_revocation_available_at = t_start
                state.nodes_with_ground_revocation.add(orbiter)
                state.mark_revoked(orbiter, compromised_node, t_start)

        # Also: any orbiter contacting Earth that already has the ground
        # revocation doesn't need to do anything new, but an orbiter contacting
        # Earth that doesn't yet have the ground revocation can receive it
        # once ground has issued it.
        if link_type == "orbiter_earth" and node_b == "earth":
            orbiter = node_a
            if state.ground_revoked and orbiter not in state.nodes_with_ground_revocation:
                state.nodes_with_ground_revocation.add(orbiter)
                state.mark_revoked(orbiter, compromised_node, t_start)

        # Step 2: Relay ground revocation between nodes during contact
        if link_type != "orbiter_earth":
            a_has = node_a in state.nodes_with_ground_revocation
            b_has = node_b in state.nodes_with_ground_revocation
            if a_has and not b_has:
                state.nodes_with_ground_revocation.add(node_b)
                state.mark_revoked(node_b, compromised_node, t_start)
            elif b_has and not a_has:
                state.nodes_with_ground_revocation.add(node_a)
                state.mark_revoked(node_a, compromised_node, t_start)

        # Early exit
        if state.all_know(compromised_node):
            break

    last_t = state.last_revocation_time(compromised_node)
    if last_t == float("inf"):
        return float("inf")
    return last_t - compromise_time


# ---------------------------------------------------------------------------
# Model 2 — Gossip-based, peer-originated (§2, Model 2)
# ---------------------------------------------------------------------------

def _apply_gossip_accusation(
    state: SimulationState,
    receiver: str,
    accuser: str,
    accused: str,
    timestamp: float,
    condition: str,
) -> None:
    """
    Apply a single gossip accusation at *receiver*, under the given corroboration
    *condition*. May result in the receiver marking the accused as revoked.
    """
    if accused in state.revoked[receiver]:
        return  # Already revoked, nothing to do

    if condition == "naive":
        # Any single accusation is acted on immediately
        state.mark_revoked(receiver, accused, timestamp)

    elif condition == "fixed_threshold":
        state.accusation_originators[receiver][accused].add(accuser)
        if len(state.accusation_originators[receiver][accused]) >= GOSSIP_VOTE_K:
            state.mark_revoked(receiver, accused, timestamp)

    elif condition == "trust_weighted":
        # Only count each accuser once
        if accuser not in state.accusation_originators[receiver][accused]:
            state.accusation_originators[receiver][accused].add(accuser)
            weight = state.trust_weights[receiver].get(accuser, 1.0)
            state.accusation_weight_totals[receiver][accused] += weight
        if state.accusation_weight_totals[receiver][accused] >= TRUST_WEIGHT_THRESHOLD:
            state.mark_revoked(receiver, accused, timestamp)

    elif condition == "decay":
        # Same as trust_weighted but weights will be adjusted at end (see post-processing)
        if accuser not in state.accusation_originators[receiver][accused]:
            state.accusation_originators[receiver][accused].add(accuser)
            weight = state.trust_weights[receiver].get(accuser, 1.0)
            state.accusation_weight_totals[receiver][accused] += weight
        if state.accusation_weight_totals[receiver][accused] >= TRUST_WEIGHT_THRESHOLD:
            state.mark_revoked(receiver, accused, timestamp)


def run_model2_propagation(
    schedule: list[dict],
    active_nodes: list[str],
    compromised_node: str,
    compromise_time: float,
    condition: str = "naive",
) -> float:
    """
    Simulate Model 2 revocation propagation.

    condition: one of "naive", "fixed_threshold", "trust_weighted", "decay"

    Returns the propagation time in seconds (last node learns − compromise time),
    or float('inf') if not everyone learned within the 30-day window.
    """
    state = SimulationState(active_nodes, compromised_node, compromise_time)
    active_set = set(active_nodes)

    for event in schedule:
        t_start = event["window_start_s"]
        node_a = event["node_a"]
        node_b = event["node_b"]
        link_type = event["link_type"]

        if t_start < compromise_time:
            continue

        if node_a not in active_set:
            continue
        if link_type != "orbiter_earth" and node_b not in active_set:
            continue

        # --- §3 Reactive layer: direct detection ---
        if link_type != "orbiter_earth":
            if node_a == compromised_node and node_b != compromised_node:
                state.mark_revoked(node_b, compromised_node, t_start)
                state.detected_by.add(node_b)
                # Under Model 2: this detector creates a gossip accusation
                accusation = (node_b, compromised_node, t_start)
                if accusation not in state.pending_gossip[node_b]:
                    state.pending_gossip[node_b].append(accusation)

            elif node_b == compromised_node and node_a != compromised_node:
                state.mark_revoked(node_a, compromised_node, t_start)
                state.detected_by.add(node_a)
                accusation = (node_a, compromised_node, t_start)
                if accusation not in state.pending_gossip[node_a]:
                    state.pending_gossip[node_a].append(accusation)

        # --- Ground revocation path (still valid in Model 2, per §2) ---
        if link_type == "orbiter_earth" and node_b == "earth":
            orbiter = node_a
            if orbiter in state.detected_by and not state.ground_revoked:
                state.ground_revoked = True
                state.ground_revocation_available_at = t_start
                state.nodes_with_ground_revocation.add(orbiter)
                state.mark_revoked(orbiter, compromised_node, t_start)

        if link_type == "orbiter_earth" and node_b == "earth":
            orbiter = node_a
            if state.ground_revoked and orbiter not in state.nodes_with_ground_revocation:
                state.nodes_with_ground_revocation.add(orbiter)
                state.mark_revoked(orbiter, compromised_node, t_start)

        # --- Gossip propagation between nodes ---
        if link_type != "orbiter_earth":
            # Skip contact if one of the nodes is compromised and already revoked by the other
            # (the other node wouldn't accept messages from a revoked node)
            # But gossip still needs to flow between non-compromised nodes

            # Exchange gossip: A -> B and B -> A
            # Node A shares its pending gossip with Node B
            for accusation in list(state.pending_gossip[node_a]):
                accuser, accused, acc_time = accusation
                _apply_gossip_accusation(state, node_b, accuser, accused, t_start, condition)
                # Node B now also has this gossip to relay
                if accusation not in state.pending_gossip[node_b]:
                    state.pending_gossip[node_b].append(accusation)

            # Node B shares its pending gossip with Node A
            for accusation in list(state.pending_gossip[node_b]):
                accuser, accused, acc_time = accusation
                _apply_gossip_accusation(state, node_a, accuser, accused, t_start, condition)
                if accusation not in state.pending_gossip[node_a]:
                    state.pending_gossip[node_a].append(accusation)

            # Relay ground revocation too
            a_has = node_a in state.nodes_with_ground_revocation
            b_has = node_b in state.nodes_with_ground_revocation
            if a_has and not b_has:
                state.nodes_with_ground_revocation.add(node_b)
                state.mark_revoked(node_b, compromised_node, t_start)
            elif b_has and not a_has:
                state.nodes_with_ground_revocation.add(node_a)
                state.mark_revoked(node_a, compromised_node, t_start)

        # Early exit
        if state.all_know(compromised_node):
            break

    last_t = state.last_revocation_time(compromised_node)
    if last_t == float("inf"):
        return float("inf")
    return last_t - compromise_time


# ---------------------------------------------------------------------------
# Experiment 2 helpers — lying-node (false accusation) simulation
# ---------------------------------------------------------------------------

def run_lying_node_trial(
    schedule: list[dict],
    active_nodes: list[str],
    compromised_node: str,
    healthy_target: str,
    accusation_time: float,
    condition: str,
) -> tuple[bool, float | None]:
    """
    Simulate a lying-node trial for Experiment 2.

    The compromised_node creates a FALSE accusation against healthy_target
    at accusation_time and propagates it via gossip.

    condition: one of "model1_sanity", "naive", "fixed_threshold",
               "trust_weighted", "decay"

    Returns:
        (falsely_revoked: bool, time_to_false_revocation_s: float or None)
        time_to_false_revocation_s is relative to accusation_time if revoked,
        else None.
    """
    state = SimulationState(active_nodes, compromised_node, accusation_time)
    active_set = set(active_nodes)

    # The compromised node creates a false accusation against the healthy target
    # and has it ready to send from the start
    if condition != "model1_sanity":
        false_accusation = (compromised_node, healthy_target, accusation_time)
        state.pending_gossip[compromised_node].append(false_accusation)

    # Under Model 1 (sanity check), peer accusations are never propagated or acted on.
    # We still walk the schedule to confirm zero vulnerability.

    for event in schedule:
        t_start = event["window_start_s"]
        node_a = event["node_a"]
        node_b = event["node_b"]
        link_type = event["link_type"]

        if t_start < accusation_time:
            continue

        if node_a not in active_set:
            continue
        if link_type != "orbiter_earth" and node_b not in active_set:
            continue

        # Model 1 sanity: NO gossip propagation at all — skip gossip logic
        if condition == "model1_sanity":
            # Under Model 1, peer accusations are never acted on.
            # The only thing that could cause a revocation is a ground-signed
            # message, but ground would never revoke a healthy node.
            # So nothing happens — we just walk through the schedule.
            continue

        # --- Gossip propagation between nodes ---
        if link_type != "orbiter_earth":
            # Exchange gossip: A -> B
            for accusation in list(state.pending_gossip[node_a]):
                accuser, accused, acc_time = accusation
                _apply_gossip_accusation(state, node_b, accuser, accused, t_start, condition)
                if accusation not in state.pending_gossip[node_b]:
                    state.pending_gossip[node_b].append(accusation)

            # Exchange gossip: B -> A
            for accusation in list(state.pending_gossip[node_b]):
                accuser, accused, acc_time = accusation
                _apply_gossip_accusation(state, node_a, accuser, accused, t_start, condition)
                if accusation not in state.pending_gossip[node_a]:
                    state.pending_gossip[node_a].append(accusation)

    # Check if healthy_target was wrongly revoked anywhere
    falsely_revoked = False
    earliest_false_revocation = float("inf")

    for nid in active_nodes:
        if nid == healthy_target:
            continue
        if healthy_target in state.revoked[nid]:
            falsely_revoked = True
            t_rev = state.revoked_times[nid][healthy_target]
            earliest_false_revocation = min(earliest_false_revocation, t_rev)

    if falsely_revoked:
        return True, earliest_false_revocation - accusation_time
    else:
        return False, None


def run_multi_colluder_trial(
    schedule: list[dict],
    active_nodes: list[str],
    colluding_nodes: list[str],
    healthy_target: str,
    accusation_times: dict[str, float],
    condition: str,
    warmup_condition: str = "neutral",
) -> tuple[bool, float | None]:
    """
    Simulate a multi-colluder trial for Phase 3 Addendum (§5 Extension + Addendum 2 Warm-up).

    colluding_nodes: list of distinct compromised node IDs.
    healthy_target: target node ID (distinct from all colluding_nodes).
    accusation_times: dict[node_id] -> float (timestamp when each colluder originates false accusation).
    condition: one of "model1_sanity", "naive", "fixed_threshold",
               "trust_weighted", "decay"
    warmup_condition: one of "neutral", "bad_reputation", "good_reputation"

    Returns:
        (falsely_revoked: bool, time_to_false_revocation_s: float or None)
        time_to_false_revocation_s is relative to earliest accusation_time if revoked,
        else None.
    """
    min_acc_time = min(accusation_times.values()) if accusation_times else 0.0

    state = SimulationState(
        active_nodes,
        compromised_node=colluding_nodes[0] if colluding_nodes else "",
        compromise_time=min_acc_time,
    )
    active_set = set(active_nodes)
    colluders_set = set(colluding_nodes)

    # Apply initial trust weights per warmup_condition (§2 Warm-Up Addendum)
    if warmup_condition == "bad_reputation":
        init_weight = 0.5
    elif warmup_condition == "good_reputation":
        init_weight = 1.2
    else:
        init_weight = 1.0

    for observer in active_nodes:
        for c in colluding_nodes:
            if c in state.trust_weights[observer]:
                state.trust_weights[observer][c] = init_weight


    if condition != "model1_sanity":
        for c in colluding_nodes:
            t_acc = accusation_times[c]
            false_acc = (c, healthy_target, t_acc)
            state.pending_gossip[c].append(false_acc)

    for event in schedule:
        t_start = event["window_start_s"]
        node_a = event["node_a"]
        node_b = event["node_b"]
        link_type = event["link_type"]

        if t_start < min_acc_time:
            continue

        if node_a not in active_set:
            continue
        if link_type != "orbiter_earth" and node_b not in active_set:
            continue

        # Model 1 sanity: NO gossip propagation at all
        if condition == "model1_sanity":
            continue

        # --- Gossip propagation between nodes ---
        if link_type != "orbiter_earth":
            # Exchange gossip: A -> B
            for accusation in list(state.pending_gossip[node_a]):
                accuser, accused, acc_time = accusation
                if t_start >= acc_time:
                    _apply_gossip_accusation(state, node_b, accuser, accused, t_start, condition)
                    if accusation not in state.pending_gossip[node_b]:
                        state.pending_gossip[node_b].append(accusation)

            # Exchange gossip: B -> A
            for accusation in list(state.pending_gossip[node_b]):
                accuser, accused, acc_time = accusation
                if t_start >= acc_time:
                    _apply_gossip_accusation(state, node_a, accuser, accused, t_start, condition)
                    if accusation not in state.pending_gossip[node_a]:
                        state.pending_gossip[node_a].append(accusation)

    # Check if healthy_target was wrongly revoked anywhere by non-colluding nodes
    falsely_revoked = False
    earliest_false_revocation = float("inf")

    for nid in active_nodes:
        if nid == healthy_target or nid in colluders_set:
            continue
        if healthy_target in state.revoked[nid]:
            falsely_revoked = True
            t_rev = state.revoked_times[nid][healthy_target]
            earliest_false_revocation = min(earliest_false_revocation, t_rev)

    if falsely_revoked:
        return True, earliest_false_revocation - min_acc_time
    else:
        return False, None

