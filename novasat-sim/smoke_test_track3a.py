"""Smoke test for Track 3 Part A backend changes."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

failures = []

# ── Check 1: is_isolated on SimNode ──────────────────────────────────────────
try:
    from src.trust_store import SimNode
    from src.identity import create_root_ca
    ca_priv, ca_cert = create_root_ca()
    node = SimNode.provision_node('test_node', ca_priv, ca_cert, {})
    assert hasattr(node, 'is_isolated'), 'is_isolated attr missing from SimNode'
    assert node.is_isolated == False, 'default is_isolated should be False'
    node.is_isolated = True
    assert node.is_isolated == True, 'is_isolated setter broken'
    print('[PASS] SimNode.is_isolated flag works correctly')
except Exception as e:
    print(f'[FAIL] SimNode.is_isolated: {e}')
    failures.append(str(e))

# ── Check 2: JSONL writer ─────────────────────────────────────────────────────
try:
    import json, tempfile, pathlib
    import server
    orig_dir  = server.OPS_EVENTS_DIR
    orig_file = server._OPS_SESSION_FILE
    server.OPS_EVENTS_DIR    = tempfile.mkdtemp()
    server._OPS_SESSION_FILE = None
    p = server._ops_session_file()
    server._append_ops_event({
        'type': 'bundle', 'sim_time_s': 1.0,
        'node_a': 'a', 'node_b': 'b',
        'integrity_status': 'verified',
        'bib_valid': True, 'bcb_valid': True
    })
    lines = pathlib.Path(p).read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 1, f'expected 1 JSONL line, got {len(lines)}'
    ev = json.loads(lines[0])
    assert ev['type'] == 'bundle', f'wrong event type: {ev["type"]}'
    server.OPS_EVENTS_DIR    = orig_dir
    server._OPS_SESSION_FILE = orig_file
    print('[PASS] _append_ops_event writes valid JSONL')
except Exception as e:
    print(f'[FAIL] JSONL writer: {e}')
    failures.append(str(e))

# ── Check 3: Payload schema ───────────────────────────────────────────────────
try:
    import server
    eng   = server.sim_engine
    state = eng.compute_tick_state(run_ml_inference=False)

    # Top-level new fields
    for fld in ('comms_decision', 'swarm_fusion', 'ops_window_totals', 'ops_event_log'):
        assert fld in state, f'Missing top-level field: {fld}'

    # swarm_fusion exact spec field names
    sf = state['swarm_fusion']
    for fld in ('target_satellite_id', 'fused_probability', 'contributing_satellite_ids',
                'recommended_action', 'ground_override'):
        assert fld in sf, f'swarm_fusion missing field: {fld}'

    # comms_decision exact spec field names
    for orb_id, cd in state['comms_decision'].items():
        for fld in ('should_transmit', 'confidence', 'reason_features', 'is_isolated'):
            assert fld in cd, f'comms_decision[{orb_id}] missing field: {fld}'

    # ops_window_totals keys
    tot = state['ops_window_totals']
    for fld in ('bundles_exchanged', 'anomalies_flagged', 'maneuvers_executed',
                'ground_overrides', 'comms_hold_decisions', 'value_delivered'):
        assert fld in tot, f'ops_window_totals missing field: {fld}'

    print('[PASS] Payload contains all Track 3 Part A fields with correct schema')
except Exception as e:
    print(f'[FAIL] Payload schema: {e}')
    failures.append(str(e))

# ── Check 4: Quarantine path in process_bpsec_for_contact ───────────────────
try:
    import server
    eng = server.sim_engine
    # Isolate orbiter_0, then check the returned status
    node = eng.nodes.get('orbiter_0')
    assert node is not None, 'orbiter_0 not found in sim_engine.nodes'
    node.is_isolated = True
    result = eng.process_bpsec_for_contact('orbiter_0', 'orbiter_1', 0.0)
    assert result['integrity_status'] == 'quarantined', \
        f'Expected quarantined, got: {result["integrity_status"]}'
    assert result['bib_valid']  == False, 'bib_valid should be False for quarantined'
    assert result['bcb_valid']  == False, 'bcb_valid should be False for quarantined'
    node.is_isolated = False  # restore
    print('[PASS] process_bpsec_for_contact returns quarantined for isolated node')
except Exception as e:
    print(f'[FAIL] Quarantine path: {e}')
    failures.append(str(e))

# ── Summary ───────────────────────────────────────────────────────────────────
print()
if failures:
    print(f'RESULT: {len(failures)} FAILURE(S):')
    for f in failures:
        print(f'  - {f}')
    sys.exit(1)
else:
    print('ALL SMOKE TESTS PASSED')
    sys.exit(0)
