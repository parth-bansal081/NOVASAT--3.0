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
    this._activeAlerts = [];    // active security alerts (flagged satellites awaiting action)
    this._flaggedSatellites = new Map(); // all satellites ever flagged this session: {satId -> {status: 'active'|'isolated'|'dismissed', reason, issuers, firstFlaggedTime}}
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
          <button id="ops-dev-toggle-btn" class="btn btn-warning ops-dev-toggle-btn" title="Toggle Dev Tools (Ctrl+Shift+W)">
            🛠 Dev Tools
          </button>
          <button id="ops-close-btn" class="btn btn-secondary ops-close-btn" title="Return to 3D Globe">
            🌍 Return to 3D Globe
          </button>
        </div>
      </div>

      <!-- Security Alert Banner (above panels) -->
      <div id="ops-alert-banner" class="ops-alert-banner"></div>

      <!-- Flagged Satellites Tracker (always visible in header area) -->
      <div id="ops-flagged-tracker" class="ops-flagged-tracker">
        <div class="ops-flagged-tracker-header">
          <span class="ops-flagged-title">🚩 Flagged Satellites</span>
          <span id="ops-flagged-count" class="ops-flagged-count">0</span>
        </div>
        <div id="ops-flagged-list" class="ops-flagged-list"></div>
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

          <!-- Dev Hook: Manual Warning Injection (hidden by default, press Ctrl+Shift+D to toggle) -->
          <div id="ops-dev-warning-panel" class="ops-dev-warning-panel" style="display: none;">
            <div class="ops-dev-warning-title">🛠 Dev Hook: Inject Warning</div>
            <div class="ops-override-row">
              <label for="ops-dev-issuer">Issuer</label>
              <select id="ops-dev-issuer" class="custom-select ops-select-sm"></select>
              <label for="ops-dev-target">Target</label>
              <select id="ops-dev-target" class="custom-select ops-select-sm"></select>
            </div>
            <div class="ops-override-row">
              <label for="ops-dev-reason">Reason</label>
              <select id="ops-dev-reason" class="custom-select ops-select-sm">
                <option value="ANOMALY_SCORE">ANOMALY_SCORE</option>
                <option value="TAMPER_DETECTED">TAMPER_DETECTED</option>
              </select>
            </div>
            <div class="ops-override-row">
              <button id="ops-dev-warning-send" class="btn btn-warning ops-dev-warning-btn">
                🛠 Inject Warning
              </button>
              <button id="ops-dev-propagate-send" class="btn btn-warning ops-dev-warning-btn" style="background: linear-gradient(135deg, #ff8c00, #e67e00);">
                🔁 Propagate All
              </button>
            </div>
            <div id="ops-dev-warning-status" class="ops-override-status"></div>
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

    // Wire Dev Tools toggle button
    document.getElementById('ops-dev-toggle-btn').addEventListener('click', () => {
      const panel = document.getElementById('ops-dev-warning-panel');
      if (panel) {
        panel.style.display = panel.style.display === 'flex' ? 'none' : 'flex';
      }
    });

    // Wire override send button
    document.getElementById('ops-override-send').addEventListener('click', () => {
      this._sendOverride();
    });

    // Wire dev warning send button
    const devWarnBtn = document.getElementById('ops-dev-warning-send');
    if (devWarnBtn) {
      devWarnBtn.addEventListener('click', () => {
        this._sendDevWarning();
      });
    }

    // Wire dev propagate button
    const devPropBtn = document.getElementById('ops-dev-propagate-send');
    if (devPropBtn) {
      devPropBtn.addEventListener('click', () => {
        this._sendDevPropagate();
      });
    }

    // Keyboard shortcut: Ctrl+Shift+D toggles dev warning panel (W closes tab in browser)
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        const panel = document.getElementById('ops-dev-warning-panel');
        if (panel) {
          panel.style.display = panel.style.display === 'flex' ? 'none' : 'flex';
        }
      }
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

    // Initialize flagged satellites from persistent state (for banner on connect/reconnect)
    if (data.flagged_satellites) {
      this._initFlaggedSatellites(data.flagged_satellites);
    }

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

    // Track server log length to detect new events correctly
    const prevServerLogLen = this._lastServerLogLength || 0;
    this._lastServerLogLength = serverLog.length;
    const incoming  = serverLog;

    if (incoming.length === prevServerLogLen) return; // nothing new

    // Replace client buffer with the server slice (server is source of truth)
    this._eventLogRows = incoming.slice(-500);

    if (badge) badge.textContent = `${this._eventLogRows.length} events (client cap: 500)`;

    // Check for new warning_flagged events and create alerts
    this._checkForNewFlags(incoming, prevServerLogLen);

    const rows = this._eventLogRows.map(ev => {
      const t = typeof ev.sim_time_s === 'number'
        ? OpsWindow._fmtSimTime(ev.sim_time_s)
        : '—';

      let typeLabel = ev.type || '?';
      let details   = '';
      let status    = '';
      let rowClass  = '';

      if (ev.type === 'bundle') {
        typeLabel = '📦 bundle';
        details   = `${ev.node_a} → ${ev.node_b}`;
        const signerFp = ev.signer_fingerprint ? ` | Signer: ${ev.signer_fingerprint}` : '';
        const verStatus = ev.verification_status ? ` | ${ev.verification_status}` : '';
        status    = (ev.integrity_status || '?') + signerFp + verStatus;
        rowClass = 'ops-row-bundle';
      } else if (ev.type === 'anomaly') {
        typeLabel = '⚠ anomaly';
        details   = ev.node_id || '?';
        status    = `G:${(ev.gaussian_score||0).toFixed(3)} iF:${(ev.iforest_score||0).toFixed(3)}`;
        rowClass = 'ops-row-anomaly';
      } else if (ev.type === 'override') {
        typeLabel = '⚡ override';
        details   = ev.satellite_id || '?';
        status    = `${ev.override_action} | ${ev.operator_note || ''}`;
        rowClass = 'ops-row-override';
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
      } else if (ev.type === 'warning_flagged') {
        typeLabel = '🚩 flagged';
        details   = `${ev.observer_id} flagged ${ev.target_id}`;
        status    = `issuers: ${ev.distinct_issuers} (T=${ev.threshold_T})`;
        rowClass = 'ops-row-warning-flagged';
      }

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

  // Check for new warning_flagged events and create alerts
  _checkForNewFlags(serverLog, prevCount) {
    // Only check new entries
    const newEntries = serverLog.slice(prevCount);
    for (const ev of newEntries) {
      if (ev.type === 'warning_flagged') {
        this._createAlert(ev);
      }
    }
  }

  // Create a security alert for a flagged satellite
  _createAlert(flagEvent) {
    const satId = flagEvent.target_id;
    const reason = flagEvent.reason_code || 'UNKNOWN';
    const issuers = flagEvent.distinct_issuers || 0;
    const threshold = flagEvent.threshold_T || 3;

    // Track in flagged satellites map
    if (!this._flaggedSatellites.has(satId)) {
      this._flaggedSatellites.set(satId, {
        status: 'active',
        reason,
        issuers,
        threshold,
        firstFlaggedTime: flagEvent.sim_time_s,
        alertId: `alert-${satId}-${Date.now()}`
      });
    } else {
      // Update existing entry
      const entry = this._flaggedSatellites.get(satId);
      entry.status = 'active';
      entry.issuers = issuers;
    }

    // Create alert banner
    const alertId = `alert-${satId}-${Date.now()}`;
    const alert = {
      id: alertId,
      satId,
      reason,
      issuers,
      threshold,
      timestamp: flagEvent.sim_time_s,
      dismissed: false
    };
    this._activeAlerts.unshift(alert);

    this._renderAlerts();
    this._renderFlaggedSatellites();
  }

  // Initialize flagged satellites from server persistent state (on connect/reconnect)
  _initFlaggedSatellites(flaggedData) {
    for (const [satId, entry] of Object.entries(flaggedData)) {
      // Skip if already tracked
      if (this._flaggedSatellites.has(satId)) continue;

      // Track in flagged satellites map
      this._flaggedSatellites.set(satId, {
        status: entry.status || 'active',
        reason: entry.reason || 'ANOMALY_SCORE',
        issuers: entry.issuers || 0,
        threshold: entry.threshold || 3,
        firstFlaggedTime: entry.first_flagged_time || 0,
        alertId: `alert-${satId}-${Date.now()}`
      });

      // Create alert banner for each flagged satellite
      const alertId = `alert-${satId}-${Date.now()}`;
      const alert = {
        id: alertId,
        satId,
        reason: entry.reason || 'ANOMALY_SCORE',
        issuers: entry.issuers || 0,
        threshold: entry.threshold || 3,
        timestamp: entry.first_flagged_time || 0,
        dismissed: false
      };
      this._activeAlerts.unshift(alert);
    }

    this._renderAlerts();
    this._renderFlaggedSatellites();
  }

  // Render all active alerts in the banner
  _renderAlerts() {
    const banner = document.getElementById('ops-alert-banner');
    if (!banner) return;

    if (this._activeAlerts.length === 0) {
      banner.innerHTML = '';
      banner.style.display = 'none';
      return;
    }

    banner.style.display = 'block';
    banner.innerHTML = this._activeAlerts.map(alert => `
      <div class="ops-alert ops-alert-critical" data-alert-id="${alert.id}">
        <div class="ops-alert-content">
          <span class="ops-alert-icon">🔴</span>
          <div class="ops-alert-details">
            <div class="ops-alert-title">SECURITY ALERT — SATELLITE FLAGGED</div>
            <div class="ops-alert-meta">
              <span>Satellite: <strong>${alert.satId}</strong></span>
              <span>Reason: <strong>${alert.reason}</strong></span>
              <span>Corroboration: <strong>${alert.issuers} distinct issuers</strong> (threshold T=${alert.threshold} met)</span>
              <span>Time: <strong>${OpsWindow._fmtSimTime(alert.timestamp)}</strong></span>
            </div>
          </div>
          <div class="ops-alert-actions">
            <button class="btn btn-danger ops-alert-isolate" data-sat-id="${alert.satId}" data-alert-id="${alert.id}">
              ISOLATE ${alert.satId}
            </button>
            <button class="btn btn-secondary ops-alert-dismiss" data-alert-id="${alert.id}">
              Dismiss
            </button>
          </div>
        </div>
    `).join('');
    this._wireAlertButtons();
  }

  // Wire alert action buttons
  _wireAlertButtons() {
    // Isolate buttons
    document.querySelectorAll('.ops-alert-isolate').forEach(btn => {
      btn.addEventListener('click', () => {
        const satId = btn.dataset.satId;
        const alertId = btn.dataset.alertId;
        this._isolateFromAlert(satId, alertId);
      });
    });

    // Dismiss buttons (with confirmation)
    document.querySelectorAll('.ops-alert-dismiss').forEach(btn => {
      btn.addEventListener('click', () => {
        const alertId = btn.dataset.alertId;
        this._dismissAlertWithConfirmation(alertId);
      });
    });
  }

  // Isolate satellite from alert
  _isolateFromAlert(satId, alertId) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this._setOverrideStatus('⚠ WebSocket not connected.', 'ops-override-status-warn');
      return;
    }

    const note = `Auto-isolate: gossip threshold met (${this._flaggedSatellites.get(satId)?.issuers || 3} issuers: ${this._flaggedSatellites.get(satId)?.reason || 'TAMPER_DETECTED'})`;
    
    this.ws.send(JSON.stringify({
      action: 'override',
      satellite_id: satId,
      override_action: 'isolate',
      operator_note: note,
    }));

    // Update flagged satellite status
    if (this._flaggedSatellites.has(satId)) {
      this._flaggedSatellites.get(satId).status = 'isolated';
    }

    // Remove this alert
    this._activeAlerts = this._activeAlerts.filter(a => a.id !== alertId);
    this._renderAlerts();
    this._renderFlaggedSatellites();

    this._setOverrideStatus(`✅ ISOLATED ${satId} (auto from security alert)`, 'ops-override-status-ok');
  }

  // Dismiss alert with second confirmation
  _dismissAlertWithConfirmation(alertId) {
    const alert = this._activeAlerts.find(a => a.id === alertId);
    if (!alert) return;

    const satId = alert.satId;
    const confirmed = confirm(
      `Dismiss alert for ${satId}?\n\n` +
      `This satellite remains flagged in the Flagged Satellites list.\n` +
      `You won't be prompted again unless it's re-flagged by new gossip.\n\n` +
      `Click OK to dismiss this alert, or Cancel to keep it visible.`
    );

    if (!confirmed) return;

    // Mark alert as dismissed
    this._activeAlerts = this._activeAlerts.filter(a => a.id !== alertId);
    
    // Update flagged satellite status
    if (this._flaggedSatellites.has(satId)) {
      this._flaggedSatellites.get(satId).status = 'dismissed';
    }

    this._renderAlerts();
    this._renderFlaggedSatellites();
  }

  // Render all flagged satellites in the tracker list
  _renderFlaggedSatellites() {
    const listEl = document.getElementById('ops-flagged-list');
    const countEl = document.getElementById('ops-flagged-count');
    if (!listEl || !countEl) return;

    const entries = Array.from(this._flaggedSatellites.entries());
    countEl.textContent = entries.length;

    if (entries.length === 0) {
      listEl.innerHTML = '<div class="ops-flagged-empty">No satellites flagged this session</div>';
      return;
    }

    listEl.innerHTML = entries.map(([satId, entry]) => `
      <div class="ops-flagged-item ops-flagged-${entry.status}">
        <div class="ops-flagged-info">
          <span class="ops-flagged-sat"><strong>${satId}</strong></span>
          <span class="ops-flagged-reason">${entry.reason} (${entry.issuers}/${entry.threshold} issuers)</span>
          <span class="ops-flagged-time">Flagged: ${OpsWindow._fmtSimTime(entry.firstFlaggedTime)}</span>
        </div>
        <div class="ops-flagged-actions">
          <span class="ops-flagged-status-badge ops-status-${entry.status}">${entry.status.toUpperCase()}</span>
          ${entry.status === 'active' || entry.status === 'dismissed' ? 
            `<button class="btn btn-sm btn-danger ops-flagged-isolate" data-sat-id="${satId}" title="Isolate ${satId}">Isolate</button>` : ''}
          ${entry.status === 'dismissed' ? 
            `<button class="btn btn-sm btn-secondary ops-flagged-reopen" data-sat-id="${satId}" title="Re-open isolate option for ${satId}">Re-open</button>` : ''}
        </div>
      </div>
    `).join('');

    // Wire flagged list buttons
    listEl.querySelectorAll('.ops-flagged-isolate').forEach(btn => {
      btn.addEventListener('click', () => {
        const satId = btn.dataset.satId;
        // Find the alert for this satellite (if any)
        const alert = this._activeAlerts.find(a => a.satId === satId);
        const alertId = alert ? alert.id : `manual-${satId}-${Date.now()}`;
        this._isolateFromAlert(satId, alertId);
      });
    });

    listEl.querySelectorAll('.ops-flagged-reopen').forEach(btn => {
      btn.addEventListener('click', () => {
        const satId = btn.dataset.satId;
        if (this._flaggedSatellites.has(satId)) {
          this._flaggedSatellites.get(satId).status = 'active';
        }
        this._renderFlaggedSatellites();
      });
    });
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

    // Also sync dev warning panel dropdowns
    const issuerSel = document.getElementById('ops-dev-issuer');
    const targetSel = document.getElementById('ops-dev-target');
    if (issuerSel && targetSel) {
      const options = orbiters
        .map(o => `<option value="${o.id}">${o.id}</option>`)
        .join('');
      issuerSel.innerHTML = options;
      targetSel.innerHTML = options;
    }
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

  // ── Dev Hook: Manual Warning Injection ─────────────────────────────────────────
  _sendDevWarning() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this._setDevWarningStatus('⚠ WebSocket not connected.', 'ops-override-status-warn');
      return;
    }
    const issuer = document.getElementById('ops-dev-issuer')?.value || '';
    const target = document.getElementById('ops-dev-target')?.value || '';
    const reason = document.getElementById('ops-dev-reason')?.value || 'ANOMALY_SCORE';
    if (!issuer || !target) {
      this._setDevWarningStatus('⚠ Select issuer and target.', 'ops-override-status-warn');
      return;
    }
    if (issuer === target) {
      this._setDevWarningStatus('⚠ Issuer and target must differ.', 'ops-override-status-warn');
      return;
    }
    this.ws.send(JSON.stringify({
      action: 'dev_issue_warning',
      issuer_id: issuer,
      target_id: target,
      reason: reason,
    }));
    this._setDevWarningStatus(
      `🛠 Warning injected: ${issuer} -> ${target} (${reason})`,
      'ops-override-status-ok'
    );
  }

  _setDevWarningStatus(msg, cls) {
    const el = document.getElementById('ops-dev-warning-status');
    if (!el) return;
    el.textContent = msg;
    el.className = `ops-override-status ${cls}`;
    setTimeout(() => { el.textContent = ''; el.className = 'ops-override-status'; }, 4000);
  }

  _sendDevPropagate() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this._setDevWarningStatus('⚠ WebSocket not connected.', 'ops-override-status-warn');
      return;
    }
    this.ws.send(JSON.stringify({
      action: 'dev_propagate_warnings',
    }));
    this._setDevWarningStatus('🔁 Full mesh propagation sent', 'ops-override-status-ok');
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