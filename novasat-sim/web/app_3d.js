/**
 * app_3d.js — NOVASAT Track 2 Phase 1: 3D CesiumJS Renderer & Live WebSocket Interface
 *
 * B.1 ELLIPSOID MANDATORY SETUP:
 * Cesium's global default ellipsoid MUST be configured to the true Mars biaxial ellipsoid
 * (equatorial radius a = 3,396,190.0 m, polar radius b = 3,376,200.0 m) BEFORE constructing
 * the Cesium.Viewer or performing coordinate conversions.
 */

// Step 1: Configure global default ellipsoid for Mars biaxial shape
Cesium.Ellipsoid.default = new Cesium.Ellipsoid(3396190.0, 3396190.0, 3376200.0);

console.log("[NOVASAT 3D] Cesium.Ellipsoid.default configured: Radii =", Cesium.Ellipsoid.default.radii.toString());

class Mars3DRenderer {
  constructor(containerId) {
    this.containerId = containerId;
    this.viewer = null;
    this.orbiterEntities = new Map();
    this.surfaceEntities = new Map();
    this.landmarkEntities = new Map();
    this.contactLinkEntities = new Map();
    this.orbitPathEntities = new Map();

    this.showTracks = true;
    this.showLOS = true;
    this.showLandmarks = true;
    this.showLabels = true;

    this.initViewer();
  }

  initViewer() {
    // Construct Cesium Viewer without Ion paid assets or default Earth widgets
    this.viewer = new Cesium.Viewer(this.containerId, {
      imageryProvider: false, // Supplying custom Mars texture below
      terrainProvider: new Cesium.EllipsoidTerrainProvider(),
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      navigationHelpButton: false,
      infoBox: false,
      selectionIndicator: false,
    });

    // Step 2: Disable Earth's default blue atmosphere & set Mars rust base color
    this.viewer.scene.globe.showGroundAtmosphere = false;
    if (this.viewer.scene.skyAtmosphere) {
      this.viewer.scene.skyAtmosphere.show = false;
    }
    this.viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#a2482b');
    this.viewer.scene.globe.enableLighting = false;
    this.viewer.scene.globe.depthTestAgainstTerrain = false;

    // Enable Camera Controls & Zoom Ranges
    const controller = this.viewer.scene.screenSpaceCameraController;
    controller.enableZoom = true;
    controller.enableRotate = true;
    controller.enableTranslate = true;
    controller.enableTilt = true;
    controller.enableLook = true;
    controller.minimumZoomDistance = 2000.0;      // Allow zooming down to 2 km altitude
    controller.maximumZoomDistance = 80000000.0;  // Allow zooming out to 80,000 km

    // Step 3: Load High-Detail Mars Viking Surface Texture Map Layer
    this.setupMarsImageryLayer();

    // Initial camera position centered on Mars Jezero / Gale Craters region
    this.viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(77.5, 10.0, 12000000.0), // 12,000 km view distance
      orientation: {
        heading: 0.0,
        pitch: Cesium.Math.toRadians(-90.0),
        roll: 0.0,
      },
    });

    // Fetch official USGS Mars Nomenclature landmarks (B.3)
    this.loadUSGSLandmarks();
  }

  setupMarsImageryLayer() {
    try {
      const marsImagery = new Cesium.UrlTemplateImageryProvider({
        url: "/api/tiles/{z}/{x}/{y}.png",
        tilingScheme: new Cesium.GeographicTilingScheme({
          ellipsoid: Cesium.Ellipsoid.default,
        }),
        maximumLevel: 6,
      });
      this.viewer.imageryLayers.addImageryProvider(marsImagery);
      console.log("[NOVASAT 3D] Loaded High-Detail Mars Viking Surface Tile Map");
    } catch (e) {
      console.warn("[NOVASAT 3D] Could not load Mars texture tile map:", e);
    }
  }

  async loadUSGSLandmarks() {
    try {
      const response = await fetch("/api/landmarks");
      if (!response.ok) return;
      const data = await response.json();
      const features = data.features || [];

      features.forEach((feat) => {
        const entity = this.viewer.entities.add({
          id: `landmark_${feat.name}`,
          name: feat.name,
          position: Cesium.Cartesian3.fromDegrees(feat.longitude_deg, feat.latitude_deg, 500.0),
          billboard: {
            image: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'><circle cx='8' cy='8' r='5' fill='%23ffd600' stroke='%23000' stroke-width='1.5'/></svg>",
            scale: 0.8,
            heightReference: Cesium.HeightReference.NONE,
          },
          label: {
            text: feat.name,
            font: "10px Inter, sans-serif",
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            fillColor: Cesium.Color.GOLD,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -10),
            show: this.showLandmarks,
          },
        });
        this.landmarkEntities.set(feat.name, entity);
      });
      console.log(`[NOVASAT 3D] Loaded ${features.length} USGS Mars Nomenclature landmarks`);
    } catch (e) {
      console.warn("[NOVASAT 3D] Could not load landmarks:", e);
    }
  }

  // --- API Methods ---
  addSurfaceAsset(id, name, lat, lon, alt = 0.0) {
    const isRover1 = id.includes("rover_1");
    const color = isRover1 ? Cesium.Color.CORAL : Cesium.Color.GOLD;
    const pinIcon = isRover1 ? "🔴" : "🟡";

    const entity = this.viewer.entities.add({
      id: id,
      name: name,
      position: Cesium.Cartesian3.fromDegrees(lon, lat, alt * 1000.0),
      point: {
        pixelSize: 14,
        color: color,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
      },
      label: {
        text: `${pinIcon} ${name}`,
        font: "12px Outfit, sans-serif",
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        fillColor: color,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 3,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -14),
        show: this.showLabels,
      },
    });

    this.surfaceEntities.set(id, entity);
    return entity;
  }

  updateOrbiter(id, lat, lon, altKm, isCompromised = false, faultType = "none") {
    const position = Cesium.Cartesian3.fromDegrees(lon, lat, altKm * 1000.0);
    const orbiterColor = isCompromised ? Cesium.Color.RED : Cesium.Color.CYAN;

    if (!this.orbiterEntities.has(id)) {
      const entity = this.viewer.entities.add({
        id: id,
        name: id,
        position: position,
        point: {
          pixelSize: 10,
          color: orbiterColor,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
        },
        label: {
          text: `🛰️ ${id}${isCompromised ? " ⚠️ [FAULT]" : ""}`,
          font: "11px Inter, sans-serif",
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          fillColor: orbiterColor,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -12),
          show: this.showLabels,
        },
      });
      this.orbiterEntities.set(id, entity);
    } else {
      const entity = this.orbiterEntities.get(id);
      entity.position = position;
      entity.point.color = orbiterColor;
      entity.label.text = `🛰️ ${id}${isCompromised ? ` ⚠️ [${faultType}]` : ""}`;
      entity.label.fillColor = orbiterColor;
      entity.label.show = this.showLabels;
    }
  }

  drawOrbitPath(id, positionsDegrees) {
    if (!this.showTracks) {
      if (this.orbitPathEntities.has(id)) {
        this.viewer.entities.remove(this.orbitPathEntities.get(id));
        this.orbitPathEntities.delete(id);
      }
      return;
    }

    const cartesianPositions = positionsDegrees.map((pos) =>
      Cesium.Cartesian3.fromDegrees(pos.lon, pos.lat, pos.altKm * 1000.0)
    );

    if (!this.orbitPathEntities.has(id)) {
      const pathEntity = this.viewer.entities.add({
        id: `track_${id}`,
        polyline: {
          positions: cartesianPositions,
          width: 1.5,
          material: new Cesium.PolylineDashMaterialProperty({
            color: Cesium.Color.CYAN.withAlpha(0.6),
            dashLength: 12.0,
          }),
        },
      });
      this.orbitPathEntities.set(id, pathEntity);
    } else {
      const pathEntity = this.orbitPathEntities.get(id);
      pathEntity.polyline.positions = cartesianPositions;
    }
  }

  setContactLink(linkId, posA_km, posB_km, linkType = "rover_orbiter") {
    if (!this.showLOS) return;

    const pA = Cesium.Cartesian3.fromDegrees(posA_km.lon, posA_km.lat, posA_km.altKm * 1000.0);
    const pB = Cesium.Cartesian3.fromDegrees(posB_km.lon, posB_km.lat, posB_km.altKm * 1000.0);

    let beamColor = Cesium.Color.SPRINGGREEN;
    if (linkType === "orbiter_orbiter") beamColor = Cesium.Color.DEEPSKYBLUE;
    if (linkType === "amber_watch") beamColor = Cesium.Color.GOLD;
    if (linkType === "red_warning") beamColor = Cesium.Color.RED;

    if (!this.contactLinkEntities.has(linkId)) {
      const entity = this.viewer.entities.add({
        id: `link_${linkId}`,
        polyline: {
          positions: [pA, pB],
          width: (linkType === "red_warning" || linkType === "amber_watch") ? 4.5 : 3.0,
          material: new Cesium.PolylineGlowMaterialProperty({
            glowPower: 0.35,
            color: beamColor,
          }),
        },
      });
      this.contactLinkEntities.set(linkId, entity);
    } else {
      const entity = this.contactLinkEntities.get(linkId);
      entity.polyline.positions = [pA, pB];
      entity.polyline.material.color = beamColor;
      entity.show = true;
    }
  }

  clearActiveContacts() {
    this.contactLinkEntities.forEach((entity) => {
      entity.show = false;
    });
  }

  clearAll() {
    this.viewer.entities.removeAll();
    this.orbiterEntities.clear();
    this.surfaceEntities.clear();
    this.contactLinkEntities.clear();
    this.orbitPathEntities.clear();
    this.landmarkEntities.clear();
  }
}

// -----------------------------------------------------------------------------
// Live Application Controller & WebSocket Integration
// -----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  const renderer = new Mars3DRenderer("cesiumContainer");

  // Pre-seed fixed surface rovers
  renderer.addSurfaceAsset("rover_1", "rover_1 (Jezero)", 18.4663, 77.4298, 0.0);
  renderer.addSurfaceAsset("rover_2", "rover_2 (Gale)", -4.5895, 137.4417, 0.0);

  // UI Element References
  const clockDisplay = document.getElementById("clock-display");
  const statConstellation = document.getElementById("stat-constellation");
  const statContacts = document.getElementById("stat-contacts");
  const statPeriod = document.getElementById("stat-period");
  const assetCount = document.getElementById("asset-count");

  const btnPlay = document.getElementById("btn-play");
  const playIcon = document.getElementById("play-icon");
  const playLabel = document.getElementById("play-label");
  const btnReset = document.getElementById("btn-reset");

  const btnZoomIn = document.getElementById("btn-zoom-in");
  const btnZoomOut = document.getElementById("btn-zoom-out");

  const speedSelect = document.getElementById("speed-select");
  const nSelect = document.getElementById("n-select");
  const toggleRecord = document.getElementById("toggle-record");

  const toggleTracks = document.getElementById("toggle-tracks");
  const toggleLOS = document.getElementById("toggle-los");
  const toggleLandmarks = document.getElementById("toggle-landmarks");
  const toggleLabels = document.getElementById("toggle-labels");

  const orbiterListContainer = document.getElementById("orbiter-list-container");
  const statusRover1 = document.getElementById("status-rover-1");
  const statusRover2 = document.getElementById("status-rover-2");

  const selectFaultTarget = document.getElementById("select-fault-target");
  const selectFaultType = document.getElementById("select-fault-type");
  const btnInjectFault = document.getElementById("btn-inject-fault");
  const btnClearFault = document.getElementById("btn-clear-fault");

  let ws = null;
  let isPaused = false;

  function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/sim`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("[WebSocket] Connected to live backend");
      document.getElementById("ws-status-text").className = "val-value val-pass";
      document.getElementById("ws-status-text").textContent = `🟢 Connected (${wsUrl})`;
    };

    ws.onclose = () => {
      console.warn("[WebSocket] Connection closed. Reconnecting in 2s...");
      document.getElementById("ws-status-text").className = "val-value val-warn";
      document.getElementById("ws-status-text").textContent = "🟡 Reconnecting...";
      setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = (err) => {
      console.error("[WebSocket] Error:", err);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      handleSimulationFrame(data);
    };
  }

  function handleSimulationFrame(data) {
    clockDisplay.textContent = data.clock_str;
    statConstellation.textContent = `N = ${data.n}`;
    statContacts.textContent = `${data.active_contacts.length} Active`;
    statPeriod.textContent = `${data.orbital_period_min.toFixed(1)} min`;
    assetCount.textContent = `2 Rovers, ${data.orbiters.length} Orbiters`;

    isPaused = data.is_paused;
    playIcon.textContent = isPaused ? "▶" : "⏸";
    playLabel.textContent = isPaused ? "Play" : "Pause";

    // Clear stale contact lines
    renderer.clearActiveContacts();

    // Render active contact beams
    if (toggleLOS.checked) {
      data.active_contacts.forEach((link, idx) => {
        let posA = null;
        let posB = null;

        if (link.node_a.startsWith("rover_")) {
          const r = data.rovers[link.node_a];
          posA = { lat: r.latitude_deg, lon: r.longitude_deg, altKm: 0.0 };
        } else {
          const orbA = data.orbiters.find((o) => o.id === link.node_a);
          if (orbA) posA = { lat: orbA.latitude_deg, lon: orbA.longitude_deg, altKm: orbA.altitude_km };
        }

        if (link.node_b.startsWith("rover_")) {
          const r = data.rovers[link.node_b];
          posB = { lat: r.latitude_deg, lon: r.longitude_deg, altKm: 0.0 };
        } else {
          const orbB = data.orbiters.find((o) => o.id === link.node_b);
          if (orbB) posB = { lat: orbB.latitude_deg, lon: orbB.longitude_deg, altKm: orbB.altitude_km };
        }

        if (posA && posB) {
          renderer.setContactLink(`link_${idx}`, posA, posB, link.link_type);
        }
      });
    }

    // Render 3D Conjunction Risk Rays (Amber Watch / Red Trigger Warning)
    if (toggleLOS.checked && data.conjunction_risks) {
      data.conjunction_risks.forEach((risk, idx) => {
        const orbA = data.orbiters.find((o) => o.id === risk.sat_A);
        const orbB = data.orbiters.find((o) => o.id === risk.sat_B);
        if (orbA && orbB) {
          const posA = { lat: orbA.latitude_deg, lon: orbA.longitude_deg, altKm: orbA.altitude_km };
          const posB = { lat: orbB.latitude_deg, lon: orbB.longitude_deg, altKm: orbB.altitude_km };
          const linkType = risk.is_trigger ? "red_warning" : "amber_watch";
          renderer.setContactLink(`conj_${idx}`, posA, posB, linkType);
        }
      });
    }

    // Update Conjunction Risk UI Elements
    const maxPc = data.max_pc || 0.0;
    const maxPcPair = data.max_pc_pair || "None";
    const valMaxPc = document.getElementById("val-max-pc");
    const valMaxPcPair = document.getElementById("val-max-pc-pair");

    if (valMaxPc) {
      if (maxPc > 1e-4) {
        valMaxPc.className = "val-value val-fail";
        valMaxPc.textContent = `${maxPc.toExponential(2)} (TRIGGER - AUTO MANEUVER)`;
      } else if (maxPc > 1e-6) {
        valMaxPc.className = "val-value val-warn";
        valMaxPc.textContent = `${maxPc.toExponential(2)} (WATCH)`;
      } else {
        valMaxPc.className = "val-value val-pass";
        valMaxPc.textContent = `${maxPc.toExponential(2)} (Nominal)`;
      }
    }
    if (valMaxPcPair) {
      valMaxPcPair.textContent = maxPcPair;
    }

    // Update surface rover cards
    const r1Status = data.surface_statuses["rover_1"];
    if (r1Status && r1Status.active_contact) {
      statusRover1.className = "contact-status active";
      statusRover1.textContent = `Active Link ↔ ${r1Status.connected_orbiter}`;
    } else {
      statusRover1.className = "contact-status";
      statusRover1.textContent = "No Active Overhead Contact";
    }

    const r2Status = data.surface_statuses["rover_2"];
    if (r2Status && r2Status.active_contact) {
      statusRover2.className = "contact-status active";
      statusRover2.textContent = `Active Link ↔ ${r2Status.connected_orbiter}`;
    } else {
      statusRover2.className = "contact-status";
      statusRover2.textContent = "No Active Overhead Contact";
    }

    // Update orbiter positions & UI list
    orbiterListContainer.innerHTML = "";
    data.orbiters.forEach((orb) => {
      renderer.updateOrbiter(orb.id, orb.latitude_deg, orb.longitude_deg, orb.altitude_km, orb.is_compromised, orb.fault_type);

      const inf = orb.inference || { gaussian_score: 0, iforest_score: 0, anomaly_flag: false };

      const card = document.createElement("div");
      card.className = `orbiter-card ${orb.is_compromised ? "fault-highlight" : ""}`;
      card.innerHTML = `
        <div class="card-top">
          <span class="orbiter-icon">${orb.is_compromised ? "⚠️" : "🛰️"}</span>
          <div class="orbiter-info">
            <strong>${orb.id} ${orb.is_compromised ? `[${orb.fault_type}]` : ""}</strong>
            <span class="details">Alt: ${orb.altitude_km.toFixed(1)} km | Vel: ${orb.velocity_km_s.toFixed(2)} km/s</span>
          </div>
          <span class="coord-badge">${orb.latitude_deg.toFixed(2)}°, ${orb.longitude_deg.toFixed(2)}°</span>
        </div>
        <div style="margin-top: 6px; font-size: 10px; display: flex; justify-content: space-between; align-items: center;">
          <span>Gaussian: <strong style="color: ${inf.gaussian_score > 0.05 ? '#ff5232' : '#00e676'}">${inf.gaussian_score.toFixed(3)}</strong></span>
          <span>iForest: <strong style="color: ${inf.iforest_score > 0.60 ? '#ff5232' : '#00e676'}">${inf.iforest_score.toFixed(3)}</strong></span>
          <span class="badge" style="background: ${inf.anomaly_flag ? 'rgba(255,82,50,0.25)' : 'rgba(0,230,118,0.25)'}; color: ${inf.anomaly_flag ? '#ff5232' : '#00e676'};">${inf.anomaly_flag ? 'ANOMALY' : 'NORMAL'}</span>
        </div>
        <!-- 4-Slider Live Controls -->
        <div class="orbiter-controls" style="margin-top: 8px; font-size: 10px; display: grid; grid-template-columns: 1fr 1fr; gap: 4px; background: rgba(0,0,0,0.2); padding: 4px; border-radius: 4px;">
          <div>
            <label>Alt: <strong>${orb.altitude_km.toFixed(0)}</strong>km</label>
            <input type="range" class="orb-slider" data-idx="${orb.index}" data-param="alt" min="100" max="5000" step="25" value="${orb.altitude_km.toFixed(0)}" style="width: 100%;">
          </div>
          <div>
            <label>Inc: <strong>${(orb.inclination_deg || 90).toFixed(0)}</strong>°</label>
            <input type="range" class="orb-slider" data-idx="${orb.index}" data-param="inc" min="0" max="180" step="1" value="${(orb.inclination_deg || 90).toFixed(0)}" style="width: 100%;">
          </div>
          <div>
            <label>RAAN: <strong>${(orb.raan_deg || 0).toFixed(0)}</strong>°</label>
            <input type="range" class="orb-slider" data-idx="${orb.index}" data-param="raan" min="0" max="360" step="5" value="${(orb.raan_deg || 0).toFixed(0)}" style="width: 100%;">
          </div>
          <div>
            <label>Phase: <strong>${(orb.true_anomaly_deg || 0).toFixed(0)}</strong>°</label>
            <input type="range" class="orb-slider" data-idx="${orb.index}" data-param="nu" min="0" max="360" step="5" value="${(orb.true_anomaly_deg || 0).toFixed(0)}" style="width: 100%;">
          </div>
        </div>
      `;
      orbiterListContainer.appendChild(card);
    });
  }

  // Event Listeners
  btnPlay.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: isPaused ? "play" : "pause" }));
    }
  });

  btnReset.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "reset" }));
    }
  });

  const btnResetSwarm = document.getElementById("btn-reset-swarm");
  if (btnResetSwarm) {
    btnResetSwarm.addEventListener("click", () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: "reset_constellation" }));
      }
    });
  }

  orbiterListContainer.addEventListener("change", (e) => {
    if (e.target && e.target.classList.contains("orb-slider")) {
      const idx = parseInt(e.target.getAttribute("data-idx"));
      const card = e.target.closest(".orbiter-card");
      if (!card) return;
      const altInput = card.querySelector('.orb-slider[data-param="alt"]');
      const incInput = card.querySelector('.orb-slider[data-param="inc"]');
      const raanInput = card.querySelector('.orb-slider[data-param="raan"]');
      const nuInput = card.querySelector('.orb-slider[data-param="nu"]');

      if (ws && ws.readyState === WebSocket.OPEN && altInput && incInput && raanInput && nuInput) {
        ws.send(JSON.stringify({
          action: "set_elements",
          orbiter_index: idx,
          altitude_km: parseFloat(altInput.value),
          inclination_deg: parseFloat(incInput.value),
          raan_deg: parseFloat(raanInput.value),
          true_anomaly_deg: parseFloat(nuInput.value)
        }));
      }
    }
  });

  // One-click Zoom In and Zoom Out Event Listeners
  if (btnZoomIn) {
    btnZoomIn.addEventListener("click", () => {
      if (renderer && renderer.viewer) {
        const h = renderer.viewer.camera.positionCartographic.height;
        renderer.viewer.camera.zoomIn(h * 0.40);
      }
    });
  }

  if (btnZoomOut) {
    btnZoomOut.addEventListener("click", () => {
      if (renderer && renderer.viewer) {
        const h = renderer.viewer.camera.positionCartographic.height;
        renderer.viewer.camera.zoomOut(h * 0.60);
      }
    });
  }

  speedSelect.addEventListener("change", (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "set_speed", speed: parseFloat(e.target.value) }));
    }
  });

  nSelect.addEventListener("change", (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "set_n", n: parseInt(e.target.value) }));
    }
  });

  toggleRecord.addEventListener("change", (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "toggle_record", enabled: e.target.checked }));
    }
  });

  btnInjectFault.addEventListener("click", () => {
    const target = selectFaultTarget.value;
    const ftype = selectFaultType.value;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "inject_fault", node_id: target, fault_type: ftype }));
    }
  });

  btnClearFault.addEventListener("click", () => {
    const target = selectFaultTarget.value;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "clear_fault", node_id: target }));
    }
  });

  toggleTracks.addEventListener("change", (e) => {
    renderer.showTracks = e.target.checked;
  });

  toggleLOS.addEventListener("change", (e) => {
    renderer.showLOS = e.target.checked;
    if (!e.target.checked) renderer.clearActiveContacts();
  });

  toggleLandmarks.addEventListener("change", (e) => {
    renderer.showLandmarks = e.target.checked;
    renderer.landmarkEntities.forEach((ent) => {
      ent.label.show = e.target.checked;
    });
  });

  toggleLabels.addEventListener("change", (e) => {
    renderer.showLabels = e.target.checked;
  });

  // Connect to live WebSocket backend
  connectWebSocket();
});
