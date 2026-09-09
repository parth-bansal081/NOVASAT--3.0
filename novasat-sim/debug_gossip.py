import sys
sys.path.insert(0, '.')
from server import LiveSimulationEngine

engine = LiveSimulationEngine()
engine.set_n(6)
engine.sim_time_s = 10000.0
engine.inject_fault('orbiter_1', 'clock_drift')

for i in range(5):
    engine.sim_time_s += 300.0
    state = engine.compute_tick_state(run_ml_inference=True)
    print('Tick {}: sim_time={}'.format(i, engine.sim_time_s))
    print('  Active contacts: {}'.format(len(state['active_contacts'])))
    for c in state['active_contacts']:
        print('    {} <-> {} (type={})'.format(c['node_a'], c['node_b'], c['link_type']))
    print('  Pending gossip sizes:')
    for nid in engine.pending_gossip:
        if engine.pending_gossip[nid]:
            print('    {}: {} warnings'.format(nid, len(engine.pending_gossip[nid])))