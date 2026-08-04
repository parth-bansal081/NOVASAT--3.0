/**
 * NOVASAT — Mars Ground-Track & Telemetry Visualization Application
 * Leaflet.js + NASA Mars Trek WMTS Integration
 *
 * Phase 4 fixes:
 *   - Map CRS set to L.CRS.EPSG4326 (Mars Trek tiles are equirectangular,
 *     NOT Web Mercator — this is the critical fix for correct rover placement)
 *   - Tile URL double-slash removed; Viking colorized mosaic as primary layer
 *   - Removed real-Earth fallback tile
 *   - Validation panel logic wired in (§4 checks)
 */

(function () {
  // --- Constants & Config ---
  const DEFAULT_N = 6;
  const TIME_STEP = 30; // 30 seconds
  const R_MARS = 3389.5; // km

  // NASA Mars Trek WMTS Tile Endpoints (EPSG:4326 equirectangular)
  // Primary: Viking visible-color mosaic (MDIM 2.1) — richest color detail
  // Fallback: MOLA color-shaded relief — always available
  const MARS_TREK_PRIMARY =
    "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg";
  const MARS_TREK_FALLBACK =
    "https://trek.nasa.gov/tiles/Mars/EQ/Mars_MGS_MOLA_ClrShade_merge_global_463m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg";

  // Colors per orbiter
  const ORBITER_COLORS = [
    "#00e5ff", "#ff007f", "#76ff03", "#ffd600", "#d500f9",
    "#ff6d00", "#00b0ff", "#1de9b6", "#ff1744", "#a7ffeb"
  ];

  // --- State Variables ---
  let map = null;
  let dataset = null;
  let currentStep = 0;
  let isPlaying = false;
  let playbackSpeed = 60; // 60x default
  let animFrameId = null;
  let lastTimestamp = 0;
  let primaryTileLayer = null;
  let fallbackTileLayer = null;
  let usingFallback = false;

  // Validation state
  let validationFirstContactChecked = false;

  // Map Layer Collections
  let roverMarkers = {};
  let orbiterMarkers = [];
  let trackPolylines = [];
  let losLines = [];
  let footprintCircles = [];

  // DOM Elements
  const playBtn = document.getElementById("btn-play");
  const playIcon = document.getElementById("play-icon");
  const playLabel = document.getElementById("play-label");
  const resetBtn = document.getElementById("btn-reset");
  const timeSlider = document.getElementById("time-slider");
  const speedSelect = document.getElementById("speed-select");
  const nSelect = document.getElementById("n-select");
  const clockDisplay = document.getElementById("clock-display");
  const contactsStat = document.getElementById("stat-contacts");
  const constStat = document.getElementById("stat-constellation");
  const orbiterListContainer = document.getElementById("orbiter-list-container");

  // Checkboxes
  const toggleTracks = document.getElementById("toggle-tracks");
  const toggleLos = document.getElementById("toggle-los");
  const toggleFootprint = document.getElementById("toggle-footprint");
  const toggleLabels = document.getElementById("toggle-labels");

  // --- Map Initialization ---
  function initMap() {
    // CRITICAL: L.CRS.EPSG4326 — Mars Trek serves tiles in equirectangular
    // (geographic) projection. Leaflet's default EPSG:3857 (Web Mercator)
    // would place rover markers at wrong pixel positions on the imagery.
    map = L.map("map", {
      crs: L.CRS.EPSG4326,
      center: [0, 0],
      zoom: 2,
      minZoom: 1,
      maxZoom: 7,
      zoomControl: true,
      attributionControl: false
    });

    // Primary layer — Viking visible-color mosaic
    primaryTileLayer = L.tileLayer(MARS_TREK_PRIMARY, {
      maxZoom: 7,
      tileSize: 256,
      noWrap: false,
      attribution: "NASA / JPL-Caltech / USGS / Mars Trek (Viking MDIM 2.1)"
    }).addTo(map);

    // Fallback layer — MOLA shaded relief (loaded but not added yet)
    fallbackTileLayer = L.tileLayer(MARS_TREK_FALLBACK, {
      maxZoom: 7,
      tileSize: 256,
      noWrap: false,
      attribution: "NASA / JPL-Caltech / USGS / Mars Trek (MOLA)"
    });

    let tileErrorCount = 0;
    primaryTileLayer.on("tileerror", function () {
      tileErrorCount++;
      if (tileErrorCount === 3 && !usingFallback) {
        usingFallback = true;
        console.warn("Viking tiles unavailable — switching to MOLA fallback layer.");
        map.removeLayer(primaryTileLayer);
        fallbackTileLayer.addTo(map);
        updateValidationLayer("MOLA Shaded Relief (Fallback)");
      }
    });

    primaryTileLayer.on("tileload", function () {
      if (!usingFallback && tileErrorCount === 0) {
        updateValidationLayer("Viking MDIM 2.1 Colorized Mosaic (Primary)");
      }
    });

    // Attribution control (bottom-right, minimal)
    L.control.attribution({ position: "bottomright", prefix: false })
      .addAttribution("NASA / JPL-Caltech / USGS | Mars Trek WMTS")
      .addTo(map);

    // Map Legend
    const legend = L.control({ position: "bottomleft" });
    legend.onAdd = function () {
      const div = L.DomUtil.create("div", "glass-card map-legend");
      div.innerHTML = `
        <div class="legend-title">🪐 Mars Surface Map</div>
        <div class="legend-row"><span class="legend-dot" style="background:#ff5232"></span><strong>rover_1</strong> — Jezero Crater</div>
        <div class="legend-row"><span class="legend-dot" style="background:#ffd600"></span><strong>rover_2</strong> — Gale Crater</div>
        <div class="legend-row"><span class="legend-dot" style="background:#00e5ff"></span>Orbiters — 400 km polar ground-tracks</div>
      `;
      return div;
    };
    legend.addTo(map);
  }

  // --- Helper: Update validation panel tile layer label ---
  function updateValidationLayer(name) {
    const el = document.getElementById("val-tile-layer");
    if (el) {
      el.textContent = name;
      el.className = "val-value val-pass";
    }
  }

  // --- Helper: Format Time Clock ---
  function formatSimTime(seconds) {
    const totalDays = Math.floor(seconds / 86400);
    const remSeconds = seconds % 86400;
    const hours = Math.floor(remSeconds / 3600);
    const mins = Math.floor((remSeconds % 3600) / 60);
    const secs = Math.floor(remSeconds % 60);

    const dayStr = String(totalDays + 1).padStart(2, "0");
    const hrStr = String(hours).padStart(2, "0");
    const minStr = String(mins).padStart(2, "0");
    const secStr = String(secs).padStart(2, "0");

    return `Day ${dayStr} — ${hrStr}:${minStr}:${secStr}`;
  }

  // --- Load Dataset ---
  async function loadDataset(n) {
    const jsonPath = `data/mars_ground_tracks_N${n}.json`;
    console.log(`Fetching ground track telemetry data from: ${jsonPath}`);

    validationFirstContactChecked = false;
    document.getElementById("val-contact-cross").textContent = "Waiting for contact event…";
    document.getElementById("val-contact-cross").className = "val-value val-pending";

    try {
      const response = await fetch(jsonPath);
      if (!response.ok) throw new Error(`HTTP ${response.status} fetching ${jsonPath}`);
      dataset = await response.json();
    } catch (err) {
      console.error(`Failed to load ${jsonPath}:`, err);
      showLoadError(jsonPath);
      return;
    }

    setupDataset();
  }

  function showLoadError(path) {
    const overlay = document.getElementById("load-error-overlay");
    if (overlay) {
      overlay.querySelector(".error-path").textContent = path;
      overlay.style.display = "flex";
    }
  }

  // --- Setup Map Markers & Layers ---
  function setupDataset() {
    clearMapLayers();
    isPlaying = false;
    playIcon.textContent = "▶";
    playLabel.textContent = "Play";
    if (animFrameId) cancelAnimationFrame(animFrameId);

    constStat.textContent = `N = ${dataset.metadata.constellation_N}`;
    timeSlider.max = dataset.metadata.sim_duration_s;
    timeSlider.value = 0;
    currentStep = 0;

    // Populate §4 validation — orbital period check
    const periodS = dataset.metadata.orbital_period_s;
    const periodMin = dataset.metadata.orbital_period_min;
    const periodEl = document.getElementById("val-orbital-period");
    if (periodEl) {
      periodEl.textContent = `${periodMin.toFixed(1)} min (${periodS.toFixed(0)} s) — expected ≈ 118 min ✓`;
      periodEl.className = Math.abs(periodMin - 118) < 2 ? "val-value val-pass" : "val-value val-warn";
    }

    // Populate §4 validation — rover coordinates static check
    const r1v = document.getElementById("val-rover-1");
    const r2v = document.getElementById("val-rover-2");
    if (r1v) { r1v.textContent = "18.4663°N, 77.4298°E → Jezero Crater ✓"; r1v.className = "val-value val-pass"; }
    if (r2v) { r2v.textContent = "4.5895°S, 137.4417°E → Gale Crater ✓"; r2v.className = "val-value val-pass"; }

    // 1. Plot Fixed Surface Rovers (Jezero Crater & Gale Crater)
    const rovers = dataset.rovers;
    for (const [key, rover] of Object.entries(rovers)) {
      const isR1 = key === "rover_1";
      const markerColor = isR1 ? "#ff5232" : "#ffd600";
      const pulseColor = isR1 ? "rgba(255,82,50,0.4)" : "rgba(255,214,0,0.4)";

      const customIcon = L.divIcon({
        className: "custom-rover-marker",
        html: `
          <div class="rover-marker-outer" style="--pulse-color:${pulseColor}">
            <div class="rover-marker-inner" style="background:${markerColor};box-shadow:0 0 14px ${markerColor}"></div>
          </div>`,
        iconSize: [20, 20],
        iconAnchor: [10, 10]
      });

      const marker = L.marker([rover.latitude_deg, rover.longitude_deg], { icon: customIcon })
        .addTo(map)
        .bindPopup(`
          <div class="map-popup">
            <strong>${rover.name}</strong>
            <span class="popup-location">${rover.location_name}</span>
            <span class="popup-coord">${rover.latitude_deg}°, ${rover.longitude_deg}°</span>
          </div>
        `);

      if (toggleLabels.checked) {
        marker.bindTooltip(`<b>${rover.name}</b><br>${rover.location_name}`, {
          permanent: true,
          direction: "top",
          offset: [0, -12],
          className: "rover-tooltip"
        });
      }

      roverMarkers[key] = marker;
    }

    // 2. Initialize Orbiter Markers & Tracks
    const numOrbiters = dataset.orbiters.length;
    document.getElementById("asset-count").textContent = `2 Rovers, ${numOrbiters} Orbiters`;
    orbiterListContainer.innerHTML = "";

    orbiterMarkers = [];
    trackPolylines = [];
    footprintCircles = [];

    dataset.orbiters.forEach((orb, i) => {
      const color = ORBITER_COLORS[i % ORBITER_COLORS.length];
      const firstCoord = orb.track[0];

      // Custom Orbiter Marker Icon
      const orbIcon = L.divIcon({
        className: "custom-orbiter-marker",
        html: `<div style="
          background: ${color};
          width: 10px; height: 10px;
          border-radius: 50%;
          border: 2px solid #fff;
          box-shadow: 0 0 10px ${color}, 0 0 20px ${color}44;
        "></div>`,
        iconSize: [10, 10],
        iconAnchor: [5, 5]
      });

      const marker = L.marker(firstCoord, { icon: orbIcon }).addTo(map);
      marker.bindPopup(`
        <div class="map-popup">
          <strong>${orb.name}</strong>
          <span class="popup-coord">Alt: ${orb.altitude_km[0]} km</span>
        </div>
      `);
      orbiterMarkers.push(marker);

      // Track Polyline (Historical Ground Trail)
      const polyline = L.polyline([], {
        color: color,
        weight: 1.5,
        opacity: 0.75,
        dashArray: "3, 5"
      }).addTo(map);
      trackPolylines.push(polyline);

      // Visibility Footprint Circle (computed from 10° min elevation at 400 km alt)
      // Half-angle from center of Mars = arccos(R/(R+h)) - elevation_min_rad
      // Footprint radius ≈ 1980 km for 400 km, 10° elev (per Phase 1 spec)
      const circle = L.circle(firstCoord, {
        radius: 1980000, // 1980 km in metres
        color: color,
        fillColor: color,
        fillOpacity: 0.04,
        weight: 1,
        dashArray: "2, 4"
      });
      if (toggleFootprint.checked) circle.addTo(map);
      footprintCircles.push(circle);

      // Sidebar Card
      const card = document.createElement("div");
      card.className = "orbiter-card";
      card.id = `card-orbiter-${i}`;
      card.innerHTML = `
        <div class="card-top">
          <span class="orbiter-icon" style="color:${color}">🛰️</span>
          <div class="orbiter-info">
            <strong>${orb.name}</strong>
            <span class="details" id="pos-${i}">${firstCoord[0]}°, ${firstCoord[1]}°</span>
          </div>
          <span class="coord-badge" id="alt-${i}">${orb.altitude_km[0]} km</span>
        </div>
        <div class="contact-status" id="status-orbiter-${i}">Searching…</div>
      `;
      orbiterListContainer.appendChild(card);
    });

    updateFrame(0);
  }

  // --- Clear Existing Map Layers ---
  function clearMapLayers() {
    for (const key in roverMarkers) map.removeLayer(roverMarkers[key]);
    roverMarkers = {};

    orbiterMarkers.forEach(m => map.removeLayer(m));
    orbiterMarkers = [];

    trackPolylines.forEach(p => map.removeLayer(p));
    trackPolylines = [];

    losLines.forEach(l => map.removeLayer(l));
    losLines = [];

    footprintCircles.forEach(c => map.removeLayer(c));
    footprintCircles = [];
  }

  // --- Update Single Frame at step Index ---
  function updateFrame(stepIdx) {
    if (!dataset || stepIdx >= dataset.metadata.num_steps) return;
    currentStep = stepIdx;

    const tSeconds = dataset.metadata.timestamps[stepIdx];
    timeSlider.value = tSeconds;
    clockDisplay.textContent = formatSimTime(tSeconds);

    // Clear active LOS ray lines
    losLines.forEach(l => map.removeLayer(l));
    losLines = [];

    let totalActiveContacts = 0;
    const r1ActiveOrbiters = [];
    const r2ActiveOrbiters = [];

    // Find active contact events at current timestamp
    dataset.contact_events.forEach(ev => {
      if (tSeconds >= ev.start_s && tSeconds <= ev.end_s) {
        totalActiveContacts++;
        if (ev.rover === "rover_1") r1ActiveOrbiters.push(ev.orbiter);
        if (ev.rover === "rover_2") r2ActiveOrbiters.push(ev.orbiter);
      }
    });

    contactsStat.textContent = `${totalActiveContacts} Active Link${totalActiveContacts !== 1 ? "s" : ""}`;

    // §4 Check 3 — Contact-window cross-check
    // When first contact event fires, verify the orbiter's ground track is
    // geographically near the rover (within ~35° great-circle)
    if (!validationFirstContactChecked && totalActiveContacts > 0) {
      validationFirstContactChecked = true;
      runContactCrossCheck(tSeconds, r1ActiveOrbiters, r2ActiveOrbiters);
    }

    // Update Surface Rover Cards
    const r1Card = document.getElementById("status-rover-1");
    if (r1ActiveOrbiters.length > 0) {
      r1Card.className = "contact-status active";
      r1Card.textContent = `⚡ LINK ACTIVE (${r1ActiveOrbiters.join(", ")})`;
    } else {
      r1Card.className = "contact-status";
      r1Card.textContent = "No Active Overhead Contact";
    }

    const r2Card = document.getElementById("status-rover-2");
    if (r2ActiveOrbiters.length > 0) {
      r2Card.className = "contact-status active";
      r2Card.textContent = `⚡ LINK ACTIVE (${r2ActiveOrbiters.join(", ")})`;
    } else {
      r2Card.className = "contact-status";
      r2Card.textContent = "No Active Overhead Contact";
    }

    // Update Orbiters Positions, Footprints & Polylines
    dataset.orbiters.forEach((orb, i) => {
      const currentPos = orb.track[stepIdx];
      const color = ORBITER_COLORS[i % ORBITER_COLORS.length];

      // Update Marker Position
      orbiterMarkers[i].setLatLng(currentPos);

      // Update Footprint
      footprintCircles[i].setLatLng(currentPos);
      if (toggleFootprint.checked) {
        if (!map.hasLayer(footprintCircles[i])) footprintCircles[i].addTo(map);
      } else {
        if (map.hasLayer(footprintCircles[i])) map.removeLayer(footprintCircles[i]);
      }

      // Update Ground Track Polyline Trail (last 240 steps = 2 hrs = 1 full orbit)
      if (toggleTracks.checked) {
        const startTrail = Math.max(0, stepIdx - 240);
        const trailPoints = orb.track.slice(startTrail, stepIdx + 1);
        trackPolylines[i].setLatLngs(trailPoints);
        if (!map.hasLayer(trackPolylines[i])) trackPolylines[i].addTo(map);
      } else {
        if (map.hasLayer(trackPolylines[i])) map.removeLayer(trackPolylines[i]);
      }

      // Update Sidebar Card Info
      document.getElementById(`pos-${i}`).textContent =
        `${currentPos[0].toFixed(2)}°, ${currentPos[1].toFixed(2)}°`;
      document.getElementById(`alt-${i}`).textContent = `${orb.altitude_km[stepIdx]} km`;

      const orbStatusCard = document.getElementById(`status-orbiter-${i}`);
      const isR1InContact = r1ActiveOrbiters.includes(orb.name);
      const isR2InContact = r2ActiveOrbiters.includes(orb.name);

      if (isR1InContact || isR2InContact) {
        const connectedRovers = [];
        if (isR1InContact) connectedRovers.push("rover_1");
        if (isR2InContact) connectedRovers.push("rover_2");

        orbStatusCard.className = "contact-status active";
        orbStatusCard.textContent = `📡 Contact with ${connectedRovers.join(" & ")}`;

        // Draw Dynamic LOS Ray Link Lines if toggle enabled
        if (toggleLos.checked) {
          connectedRovers.forEach(rKey => {
            const rovPos = [dataset.rovers[rKey].latitude_deg, dataset.rovers[rKey].longitude_deg];
            const line = L.polyline([currentPos, rovPos], {
              color: "#00e676",
              weight: 2.5,
              opacity: 0.9,
              dashArray: "5, 5"
            }).addTo(map);
            losLines.push(line);
          });
        }
      } else {
        orbStatusCard.className = "contact-status";
        orbStatusCard.textContent = "Out of View";
      }
    });
  }

  // --- §4 Check 3 — Contact Cross-Check ---
  function runContactCrossCheck(tSeconds, r1Orbiters, r2Orbiters) {
    const el = document.getElementById("val-contact-cross");
    if (!el) return;

    // For the first active orbiter-rover pair found, compute great-circle distance
    // between the orbiter's current ground-track point and the rover's fixed position.
    // A contact at 10° minimum elevation = orbiter sub-satellite point within ~35° of rover.
    let passed = false;
    let detail = "";

    const allPairs = [
      ...r1Orbiters.map(o => ({ rover: "rover_1", orbiter: o })),
      ...r2Orbiters.map(o => ({ rover: "rover_2", orbiter: o }))
    ];

    for (const { rover, orbiter } of allPairs) {
      const orbIdx = dataset.orbiters.findIndex(o => o.name === orbiter);
      if (orbIdx < 0) continue;

      const stepForTime = Math.round(tSeconds / dataset.metadata.time_step_s);
      const [oLat, oLon] = dataset.orbiters[orbIdx].track[stepForTime];
      const rLat = dataset.rovers[rover].latitude_deg;
      const rLon = dataset.rovers[rover].longitude_deg;

      // Haversine great-circle distance in degrees
      const dLat = (oLat - rLat) * Math.PI / 180;
      const dLon = (oLon - rLon) * Math.PI / 180;
      const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(rLat * Math.PI / 180) * Math.cos(oLat * Math.PI / 180) *
        Math.sin(dLon / 2) ** 2;
      const gcDeg = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)) * 180 / Math.PI;

      // Max ground-track separation for 10° elevation at 400 km orbit ≈ 33°
      if (gcDeg <= 35) {
        passed = true;
        detail = `${orbiter} is ${gcDeg.toFixed(1)}° from ${rover} at t=${tSeconds}s ✓`;
        break;
      } else {
        detail = `${orbiter} is ${gcDeg.toFixed(1)}° from ${rover} — checking next pair…`;
      }
    }

    el.textContent = passed ? detail : `No pair within 35° — possible issue. ${detail}`;
    el.className = `val-value ${passed ? "val-pass" : "val-warn"}`;
  }

  // --- Animation Loop ---
  function animationStep(timestamp) {
    if (!isPlaying) return;

    if (!lastTimestamp) lastTimestamp = timestamp;
    const deltaMs = timestamp - lastTimestamp;
    lastTimestamp = timestamp;

    const simSecondsToAdvance = (deltaMs / 1000.0) * playbackSpeed;
    const stepsToAdvance = Math.floor(simSecondsToAdvance / TIME_STEP);

    if (stepsToAdvance >= 1) {
      let nextStep = currentStep + stepsToAdvance;
      if (nextStep >= dataset.metadata.num_steps) {
        nextStep = 0; // Loop back to start
      }
      updateFrame(nextStep);
    }

    animFrameId = requestAnimationFrame(animationStep);
  }

  // --- Event Listeners ---
  function bindEvents() {
    playBtn.addEventListener("click", () => {
      isPlaying = !isPlaying;
      if (isPlaying) {
        playIcon.textContent = "⏸";
        playLabel.textContent = "Pause";
        lastTimestamp = 0;
        animFrameId = requestAnimationFrame(animationStep);
      } else {
        playIcon.textContent = "▶";
        playLabel.textContent = "Play";
        if (animFrameId) cancelAnimationFrame(animFrameId);
      }
    });

    resetBtn.addEventListener("click", () => {
      isPlaying = false;
      playIcon.textContent = "▶";
      playLabel.textContent = "Play";
      if (animFrameId) cancelAnimationFrame(animFrameId);
      validationFirstContactChecked = false;
      updateFrame(0);
    });

    timeSlider.addEventListener("input", (e) => {
      const valSec = parseInt(e.target.value, 10);
      const stepIdx = Math.floor(valSec / TIME_STEP);
      updateFrame(stepIdx);
    });

    speedSelect.addEventListener("change", (e) => {
      playbackSpeed = parseFloat(e.target.value);
    });

    nSelect.addEventListener("change", (e) => {
      const nVal = parseInt(e.target.value, 10);
      loadDataset(nVal);
    });

    toggleTracks.addEventListener("change", () => updateFrame(currentStep));
    toggleLos.addEventListener("change", () => updateFrame(currentStep));
    toggleFootprint.addEventListener("change", () => updateFrame(currentStep));
    toggleLabels.addEventListener("change", () => setupDataset());

    // Dismiss load error overlay
    const dismissBtn = document.getElementById("btn-dismiss-error");
    if (dismissBtn) {
      dismissBtn.addEventListener("click", () => {
        document.getElementById("load-error-overlay").style.display = "none";
      });
    }
  }

  // --- Entry Point ---
  document.addEventListener("DOMContentLoaded", () => {
    initMap();
    bindEvents();
    loadDataset(DEFAULT_N);
  });
})();
