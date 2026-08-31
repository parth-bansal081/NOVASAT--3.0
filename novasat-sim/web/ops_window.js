/**
 * ops_window.js — NOVASAT Track 3 Part A: Ops Window
 *
 * Sibling to Mars3DRenderer — never touches Cesium. Pure DOM/table renderer.
 * Subscribes to the same WebSocket state via updateState(data) called from app_3d.js.
 *
 * Four panels (per spec A.3):
 *   1. Per-node status table  — decision, battery stub, buffer stub, anomaly score,
 *                               trust score, BPSec status, 6B comms decision (stub),
 *                               6A fused isolation probability (stub)
 *   2. Collision-risk table   — Pc, miss distance, trend; reads conjunction_risks
 *   3. Bundle/downlink event log — capped at 500 rows client-side; full log server-side
 *   4. Mission-wide totals    — ops_window_totals rendered verbatim from server
 *
 * Ground-station override path:
 *   Operator fills the override form → "Send Override" → WS message sent →
 *   server applies is_isolated, increments ground_overrides, appends to JSONL.
 *   Result is visible on the next WS tick in the per-node table and event log.
 *
 * Standing constraints obeyed:
 *   - Client NEVER recomputes totals; it renders what the server sends.
 *   - Toggling this panel does NOT touch the WS connection or the physics tick.
 *   - 6B comms_decision and 6A swarm_fusion fields are rendered from their stub
 *     shapes now; when 6A/6B produce real values the columns populate automatically.
 */

class OpsWindow {
  /**
   * @param {string} containerId   - id of the #ops-window-container div
   * @param {WebSocket|null} wsRef - live reference to the shared WebSocket (for send)
   */
  constructor(containerId, wsRef = null) {
    this.containerId = containerId;
    this.ws = wsRef;             // set from app_3d.js after WS connects
    this.container = document.getElementById(containerId);
    this._eventLogRows = [];    // client-side rolling buffer, max 500
    this._build();
  }

  // ── Setter called by app_3d.js after WS is open ────────────────────────────
  setWs(ws) { this.ws = ws; }

  // ── DOM Construction ────────────────────────────────────────────────────────
  _build() {
    if (!this.container) return;

    this.container.innerHTML = `
      <div class="ops-header">
        <div class="ops-title">
          <span class="ops-icon">📊</span>
          <h2>NOVASAT — Ops Control Window</h2>
          <span class="ops-subtitle">Track 3 · Dense Data View</span>
        </div>
        <div class="ops-header-right">
          <span id="ops-clock" class="ops-clock-badge">Day 00 — 00:00:00</span>
          <button id="ops-close-btn" class="btn btn-secondary ops-close-btn" title="Return to 3D Globe">
            🌍 Return to 3D Globe
          </button>
        </div>
      </div>

      <div class="ops-panels-grid">

        <!-- Panel 1: Per-node status table -->
        <section class="ops-panel ops-panel-wide" id="ops-panel-nodes">
          <div class="ops-panel-header">
            <span class="ops-panel-title">🛰️ Per-Node Status</span>
            <span class="ops-panel-badge" id="ops-badge-nodes">0 nodes</span>
          </div>
          <div class="ops-table-wrapper">
            <table class="ops-table" id="ops-node-table">
              <thead>
                <tr>
                  <th>Node</th>
                  <th>Fault</th>
                  <th title="Isolation flag — set by ground override only in this pass">Isolated</th>
                  <th>BPSec Status</th>
                  <th title="Gaussian anomaly score">G-Score</th>
                  <th title="Isolation Forest anomaly score">iF-Score</th>
                  <th title="Ensemble anomaly flag">Anomaly</th>
                  <th title="6B comms model: should_transmit (stub)">Tx Decision</th>
                  <th title="6B comms model: confidence (stub)">Tx Conf</th>
                  <th title="6A swarm fusion: fused_probability (stub)">Fusion Prob</th>
                  <th title="6A swarm fusion: recommended_action (stub)">Fusion Action</th>
                </tr>
              </thead>
              <tbody id="ops-node-tbody">
                <tr><td colspan="11" class="ops-empty-row">Waiting for data…</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Panel 2: Collision-risk table -->
        <section class="ops-panel" id="ops-panel-collision">
          <div class="ops-panel-header">
            <span class="ops-panel-title">🛡️ Collision Risk (Live Pairs)</span>
            <span class="ops-panel-badge" id="ops-badge-collision">0 pairs</span>
          </div>
          <div class="ops-table-wrapper ops-table-wrapper-short">
            <table class="ops-table" id="ops-collision-table">
              <thead>
                <tr>
                  <th>Pair</th>
                  <th>Pc</th>
                  <th>Miss Dist (km)</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody id="ops-collision-tbody">
                <tr><td colspan="4" class="ops-empty-row">No conjunction risks computed yet.</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Panel 4: Mission-wide totals (rendered before panel 3 for visual weight) -->
        <section class="ops-panel" id="ops-panel-totals">
          <div class="ops-panel-header">
            <span class="ops-panel-title">📈 Mission Totals</span>
            <span class="ops-panel-badge" id="ops-badge-totals">Server-side</span>
          </div>
          <div class="ops-totals-grid" id="ops-totals-grid">
            <div class="ops-total-cell"><span class="ops-total-label">Bundles Exchanged</span><span id="tot-bundles" class="ops-total-val">0</span></div>
            <div class="ops-total-cell"><span class="ops-total-label">Anomalies Flagged</span><span id="tot-anomalies" class="ops-total-val ops-total-warn">0</span></div>
            <div class="ops-total-cell"><span class="ops-total-label">Maneuvers Executed</span><span id="tot-maneuvers" class="ops-total-val">0</span></div>
            <div class="ops-total-cell"><span class="ops-total-label">Value Delivered</span><span id="tot-value" class="ops-total-val">0</span></div>
            <div class="ops-total-cell"><span class="ops-total-label">Comms Hold Decisions <span class="ops-stub-tag">6B</span></span><span id="tot-hold" class="ops-total-val ops-total-muted">0</span></div>
            <div class="ops-total-cell"><span class="ops-total-label">Ground Overrides</span><span id="tot-overrides" class="ops-total-val ops-total-override">0</span></div>
          </div>

          <!-- Ground-station override form -->
          <div class="ops-override-form">
            <div class="ops-override-title">⚙️ Ground Override Command</div>
            <div class="ops-override-row">
              <label for="ops-override-sat">Satellite ID</label>
              <select id="ops-override-sat" class="custom-select ops-select-sm"></select>
              <label for="ops-override-action">Action</label>
              <select id="ops-override-action" class="custom-select ops-select-sm">
                <option value="isolate">Isolate</option>
                <option value="clear">Clear</option>
              </select>
            </div>
            <div class="ops-override-row">
              <label for="ops-override-note">Operator Note</label>
              <input type="text" id="ops-override-note" class="ops-text-input" placeholder="e.g. suspicious telemetry, manual isolate">
            </div>
            <button id="ops-override-send" class="btn btn-primary ops-override-btn">
              ⚡ Send Override
            </button>
            <div id="ops-override-status" class="ops-override-status"></div>
          </div>
        </section>

        <!-- Panel 3: Bundle / Downlink Event Log -->
        <section class="ops-panel ops-panel-log" id="ops-panel-log">
          <div class="ops-panel-header">
            <span class="ops-panel-title">📋 Event Log</span>
            <span class="ops-panel-badge" id="ops-badge-log">0 events (client cap: 500)</span>
          </div>
          <div class="ops-table-wrapper ops-table-wrapper-log">
            <table class="ops-table" id="ops-log-table">
              <thead>
                <tr>
                  <th>Sim Time</th>
                  <th>Type</th>
                  <th>Details</th>
                  <th>Status / Note</th>
                </tr>
              </thead>
              <tbody id="ops-log-tbody">
                <tr><td colspan="4" class="ops-empty-row">Waiting for events…</td></tr>
              </tbody>
            </table>
          </div>
        </section>

      </div><!-- /ops-panels-grid -->
    `;

    // Wire close button
    document.getElementById('ops-close-btn').addEventListener('click', () => {
      this._toggle(false);
      // Notify app_3d.js that we've closed (it handles 3D restore)
      document.dispatchEvent(new CustomEvent('ops-window-close'));
    });

    // Wire override send button
    document.getElementById('ops-override-send').addEventListener('click', () => {
      this._sendOverride();
    });
  }

  // ── Public API — called by app_3d.js on every WS tick ───────────────────────
  /**
   * @param {Object} data  Full WS payload from server.py compute_tick_state()
   */
  updateState(data) {
    // Update clock
    const opsClockEl = document.getElementById('ops-clock');
    if (opsClockEl) opsClockEl.textContent = data.clock_str || '';

    // Populate satellite dropdown from live orbiters (idempotent; only rebuilds if count changes)
    this._syncSatDropdown(data.orbiters || []);

    // Panel 1: per-node status
    this._renderNodeTable(data);

    // Panel 2: collision risk
    this._renderCollisionTable(data.conjunction_risks || []);

    // Panel 3: event log (incremental — append new events only)
    this._appendEventLogRows(data.ops_event_log || []);

    // Panel 4: totals
    this._renderTotals(data.ops_window_totals || {});
  }

  // ── Panel 1: Per-node status ─────────────────────────────────────────────────
  _renderNodeTable(data) {
    const tbody = document.getElementById('ops-node-tbody');
    if (!tbody) return;

    const orbiters = data.orbiters || [];
    const commsDec = data.comms_decision || {};
    const fusion   = data.swarm_fusion  || {};
    const badge    = document.getElementById('ops-badge-nodes');
    if (badge) badge.textContent = `${orbiters.length} nodes`;

    if (orbiters.length === 0) {
      tbody.innerHTML = '<tr><td colspan="11" class="ops-empty-row">No orbiters in constellation.</td></tr>';
      return;
    }

    const rows = orbiters.map(orb => {
      const inf   = orb.inference || {};
      const cd    = commsDec[orb.id] || {};
      const isIsolated = cd.is_isolated || false;

      // Determine BPSec status for this node from active_contacts
      const contacts = (data.active_contacts || []).filter(
        c => c.node_a === orb.id || c.node_b === orb.id
      );
      let bpsecStatus = 'no contact';
      if (contacts.length > 0) {
        const statuses = contacts.map(c => (c.bpsec || {}).integrity_status || 'unknown');
        if (statuses.some(s => s === 'quarantined')) bpsecStatus = 'quarantined';
        else if (statuses.some(s => s === 'tampered')) bpsecStatus = 'tampered';
        else if (statuses.every(s => s === 'verified')) bpsecStatus = 'verified';
        else bpsecStatus = statuses[0];
      }

      const bpsecClass = bpsecStatus === 'verified' ? 'ops-cell-good'
                       : bpsecStatus === 'quarantined' ? 'ops-cell-quarantine'
                       : bpsecStatus === 'tampered'    ? 'ops-cell-bad'
                       : 'ops-cell-muted';

      // 6A fusion: check if this node is the fusion target
      const isFusionTarget = fusion.target_satellite_id === orb.id;
      const fusedProb = isFusionTarget ? fusion.fused_probability : null;
      const recAction = isFusionTarget ? fusion.recommended_action : '—';

      const anomalyFlag = inf.anomaly_flag || false;
      const faultLabel  = orb.fault_type && orb.fault_type !== 'none' ? orb.fault_type : '—';

      return `<tr class="${isIsolated ? 'ops-row-isolated' : anomalyFlag ? 'ops-row-anomaly' : ''}">
        <td class="ops-cell-id">${orb.id}</td>
        <td class="${faultLabel !== '—' ? 'ops-cell-bad' : 'ops-cell-muted'}">${faultLabel}</td>
        <td class="${isIsolated ? 'ops-cell-quarantine ops-cell-bold' : 'ops-cell-good'}">${isIsolated ? '🔒 YES' : 'NO'}</td>
        <td class="${bpsecClass}">${bpsecStatus}</td>
        <td class="${(inf.gaussian_score||0) > 0.05 ? 'ops-cell-bad' : 'ops-cell-good'}">${(inf.gaussian_score||0).toFixed(3)}</td>
        <td class="${(inf.iforest_score||0) > 0.60 ? 'ops-cell-bad' : 'ops-cell-good'}">${(inf.iforest_score||0).toFixed(3)}</td>
        <td class="${anomalyFlag ? 'ops-cell-bad ops-cell-bold' : 'ops-cell-good'}">${anomalyFlag ? '⚠ ANOMALY' : 'NORMAL'}</td>
        <td class="ops-cell-stub" title="6B stub">${cd.should_transmit !== undefined ? (cd.should_transmit ? 'TRANSMIT' : 'HOLD') : '—'}</td>
        <td class="ops-cell-stub" title="6B stub">${cd.confidence !== undefined ? cd.confidence.toFixed(2) : '—'}</td>
        <td class="ops-cell-stub" title="6A stub">${fusedProb !== null ? fusedProb.toFixed(3) : '—'}</td>
        <td class="ops-cell-stub" title="6A stub">${recAction}</td>
      </tr>`;
    });

    tbody.innerHTML = rows.join('');
  }

  // ── Panel 2: Collision risk ──────────────────────────────────────────────────
  _renderCollisionTable(risks) {
    const tbody = document.getElementById('ops-collision-tbody');
    const badge = document.getElementById('ops-badge-collision');
    if (!tbody) return;
    if (badge) badge.textContent = `${risks.length} pairs`;

    if (risks.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="ops-empty-row">No conjunction risks currently computed.</td></tr>';
      return;
    }

    const rows = risks.map(r => {
      const pc    = typeof r.pc === 'number' ? r.pc : 0;
      const dist  = typeof r.miss_distance_km === 'number' ? r.miss_distance_km : 0;
      const isTrig  = r.is_trigger;
      const isWatch = r.is_watch;
      const rowClass = isTrig ? 'ops-row-crit' : isWatch ? 'ops-row-warn' : '';
      const statusLabel = isTrig ? '🔴 TRIGGER' : isWatch ? '🟡 WATCH' : '🟢 Nominal';
      return `<tr class="${rowClass}">
        <td class="ops-cell-id">${r.sat_A} / ${r.sat_B}</td>
        <td class="${isTrig ? 'ops-cell-bad' : isWatch ? 'ops-cell-warn' : 'ops-cell-good'}">${pc.toExponential(2)}</td>
        <td>${dist.toFixed(1)}</td>
        <td>${statusLabel}</td>
      </tr>`;
    });

    tbody.innerHTML = rows.join('');
  }

  // ── Panel 3: Event log (incremental append, capped at 500 client-side) ──────
  _appendEventLogRows(serverLog) {
    // The server sends the last 500 events every tick.
    // We diff by tracking the highest seen count to avoid re-rendering identical rows.
    if (!serverLog || serverLog.length === 0) return;

    const tbody = document.getElementById('ops-log-tbody');
    const badge = document.getElementById('ops-badge-log');
    if (!tbody) return;

    const prevCount = this._eventLogRows.length;
    const incoming  = serverLog;

    if (incoming.length === prevCount) return; // nothing new

    // Replace client buffer with the server slice (server is source of truth)
    this._eventLogRows = incoming.slice(-500);

    if (badge) badge.textContent = `${this._eventLogRows.length} events (client cap: 500)`;

    const rows = this._eventLogRows.map(ev => {
      const t = typeof ev.sim_time_s === 'number'
        ? OpsWindow._fmtSimTime(ev.sim_time_s)
        : '—';

      let typeLabel = ev.type || '?';
      let details   = '';
      let status    = '';

      if (ev.type === 'bundle') {
        typeLabel = '📦 bundle';
        details   = `${ev.node_a} → ${ev.node_b}`;
        status    = ev.integrity_status || '?';
      } else if (ev.type === 'anomaly') {
        typeLabel = '⚠ anomaly';
        details   = ev.node_id || '?';
        status    = `G:${(ev.gaussian_score||0).toFixed(3)} iF:${(ev.iforest_score||0).toFixed(3)}`;
      } else if (ev.type === 'override') {
        typeLabel = '⚡ override';
        details   = ev.satellite_id || '?';
        status    = `${ev.override_action} | ${ev.operator_note || ''}`;
      }

      const rowClass = ev.type === 'override' ? 'ops-row-override'
                     : ev.type === 'anomaly'  ? 'ops-row-anomaly'
                     : '';

      return `<tr class="${rowClass}">
        <td class="ops-cell-mono">${t}</td>
        <td>${typeLabel}</td>
        <td class="ops-cell-mono">${details}</td>
        <td class="${ev.integrity_status === 'tampered' ? 'ops-cell-bad' : ev.type === 'override' ? 'ops-cell-quarantine' : ''}">${status}</td>
      </tr>`;
    }).reverse(); // newest first

    if (tbody.querySelector('.ops-empty-row')) {
      tbody.innerHTML = rows.join('');
    } else {
      tbody.innerHTML = rows.join('');
    }
  }

  // ── Panel 4: Mission totals ──────────────────────────────────────────────────
  _renderTotals(totals) {
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    set('tot-bundles',   totals.bundles_exchanged   || 0);
    set('tot-anomalies', totals.anomalies_flagged    || 0);
    set('tot-maneuvers', totals.maneuvers_executed   || 0);
    set('tot-value',     totals.value_delivered      || 0);
    set('tot-hold',      totals.comms_hold_decisions || 0);
    set('tot-overrides', totals.ground_overrides     || 0);
  }

  // ── Override form helpers ────────────────────────────────────────────────────
  _syncSatDropdown(orbiters) {
    const sel = document.getElementById('ops-override-sat');
    if (!sel) return;
    if (sel.options.length === orbiters.length) return; // no change
    sel.innerHTML = orbiters
      .map(o => `<option value="${o.id}">${o.id}</option>`)
      .join('');
  }

  _sendOverride() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this._setOverrideStatus('⚠ WebSocket not connected.', 'ops-override-status-warn');
      return;
    }
    const satId    = document.getElementById('ops-override-sat')?.value    || '';
    const action   = document.getElementById('ops-override-action')?.value || '';
    const note     = document.getElementById('ops-override-note')?.value   || '';
    if (!satId || !action) {
      this._setOverrideStatus('⚠ Select a satellite and action.', 'ops-override-status-warn');
      return;
    }
    this.ws.send(JSON.stringify({
      action: 'override',
      satellite_id: satId,
      override_action: action,
      operator_note: note,
    }));
    this._setOverrideStatus(
      `✅ Override sent: ${action.toUpperCase()} → ${satId}`,
      'ops-override-status-ok'
    );
    // Clear note field after send
    const noteEl = document.getElementById('ops-override-note');
    if (noteEl) noteEl.value = '';
  }

  _setOverrideStatus(msg, cls) {
    const el = document.getElementById('ops-override-status');
    if (!el) return;
    el.textContent = msg;
    el.className = `ops-override-status ${cls}`;
    setTimeout(() => { el.textContent = ''; el.className = 'ops-override-status'; }, 4000);
  }

  // ── Visibility toggle ────────────────────────────────────────────────────────
  _toggle(show) {
    if (!this.container) return;
    if (show) {
      this.container.classList.remove('ops-window-hidden');
      this.container.classList.add('ops-window-visible');
    } else {
      this.container.classList.add('ops-window-hidden');
      this.container.classList.remove('ops-window-visible');
    }
  }

  /** Called by app_3d.js toggle button. Returns whether the window is now visible. */
  toggle() {
    const isVisible = this.container.classList.contains('ops-window-visible');
    this._toggle(!isVisible);
    return !isVisible;
  }

  // ── Utility ──────────────────────────────────────────────────────────────────
  static _fmtSimTime(s) {
    const d   = Math.floor(s / 86400);
    const rem = s % 86400;
    const h   = Math.floor(rem / 3600);
    const m   = Math.floor((rem % 3600) / 60);
    const sec = Math.floor(rem % 60);
    return `D${String(d).padStart(2,'0')} ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
  }
}
