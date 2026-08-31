# NOVASAT — Mars Satellite Swarm Simulation & Anomaly Detection Framework

**NOVASAT** is an advanced, autonomous Mars satellite swarm simulation, cybersecurity evaluation, and anomaly detection framework. It integrates physics-based orbital mechanics (astropy / poliastro / J2 perturbations), Delay-Tolerant Networking (DTN), PKI & BPSec Bundle Protocol security (RFC 9172), trust management, 2D Probability of Collision ($P_c$) conjunction assessment, and multi-modal ML anomaly detection stacking ensembles.

---

## 🚀 Architectural Overview & Feature Highlights

```
                       +-----------------------------------+
                       |    CesiumJS 3D Visualizer & UI    |
                       |  (WebSockets @ ws://localhost:8000)|
                       +-----------------+-----------------+
                                         |
                                         v
                       +-----------------+-----------------+
                       |     FastAPI Telemetry Server      |
                       |           (server.py)             |
                       +-----------------+-----------------+
                                         |
    +------------------------------------+------------------------------------+
    |                                    |                                    |
    v                                    v                                    v
+---+-------------------+    +-----------+-----------+    +---------------+---+
| Physics & Conjunction |    | Security & BPSec PKI  |    | ML Inference &    |
|   Assessment Engine   |    | (Ed25519/X25519/AES)  |    | Stacking Ensemble |
+-----------------------+    +-----------------------+    +-------------------+
```

### 1. 🪐 Physical & Orbital Mechanics Engine
- **True Biaxial Ellipsoid**: Uses Mars IAU ellipsoid ($a = 3,396.19 \text{ km}$, $b = 3,376.20 \text{ km}$, $R_{\text{mean}} = 3,389.5 \text{ km}$, $\mu = 42,828.37 \text{ km}^3/\text{s}^2$).
- **J2 Secular Perturbations**: Models nodal precession ($\dot{\Omega}$), argument of periapsis drift ($\dot{\omega}$), and mean motion corrections ($\bar{n}$) using Mars $J_2 = 1.960454 \times 10^{-3}$.
- **Surface Asset Occlusion**: Exact 3D ray-ellipsoid line-of-sight occlusion checks (`check_biaxial_occlusion`) for Jezero Crater (`rover_1`: $18.4663^\circ\text{N}, 77.4298^\circ\text{E}$) and Gale Crater (`rover_2`: $-4.5895^\circ\text{S}, 137.4417^\circ\text{E}$).

### 2. 🛡️ BPSec Security Layer & Trust Management (Track 1)
- **RFC 9172 Bundle Protocol Security**: Implements Block Integrity Blocks (BIB) with **Ed25519 signatures** for non-repudiation and Block Confidentiality Blocks (BCB) with **AES-256-GCM authenticated encryption** keyed via **X25519 Diffie-Hellman + HKDF** key agreement (`src/bpsec.py`).
- **PKI & Certificate Chains**: Root CA authority with X.509 node certificates and dual private key isolation (`src/trust_store.py`).
- **Gossip & Reputation Dynamics**: Simulates trust-weighted voting, decay rules, and warm-up conditions (`bad_reputation`, `good_reputation`, `neutral`).

### 3. 🤖 Anomaly Detection Stacking Ensemble (Track 2 Phase 4)
- **Base Models**: `GaussianDensityModel` (EllipticEnvelope) + `IsolationForest` trained on 4.68 million nominal telemetry rows (`train_normal.csv`).
- **Stacking Meta-Model**: `LogisticRegression` meta-model combining standardized base model z-scores:
  $$P(\text{anomaly}) = \sigma(1.605331 \cdot z_{\text{gaussian}} - 0.647717 \cdot z_{\text{iforest}} - 4.925789)$$
- **Test Performance**: Single-touch test set evaluation achieves **0.9249 F1-Score** (98.73% Precision, 86.98% Recall), strictly outperforming individual base models.
- **Public Benchmark Validation**: Standalone validation script ([`experiments/esa_adb_validation.py`](file:///c:/Codes/NOVASAT%20REBUILD/novasat-sim/experiments/esa_adb_validation.py)) ensuring generalizability on real spacecraft telemetry (ESA-ADB / OPSSAT-AD dataset).

### 4. 🛰️ Live Collision Avoidance & Relative Navigation (Track 2 Phase 2)
- **2D $P_c$ Conjunction Assessment**: Implements 2D isotropic Gaussian $P_c$ integration over a 24-hour lookahead window with time-growing position uncertainty ($\sigma_0 = 50\text{m}$, $\dot{\sigma} = 2\text{m/hr}$, $R_{\text{HB}} = 10\text{m}$) (`src/conjunction_assessment.py`).
- **Decoupled Cadence**: Conjunction assessment pass runs on a 3600s cadence in `server.py` without delaying 30s physics ticks.
- **Deterministic Auto-Maneuver**: Triggers along-track $\Delta v$ (+2 km altitude boost) when $P_c > 1 \times 10^{-4}$.
- **ML Triage Classifier**: Pre-filter model (`models/triage_classifier.pkl`) achieving **99.99% Test Recall**.

---

## 📂 Repository Layout & Key Modules

```
NOVASAT REBUILD/
├── README.md                                          # Master Project Documentation
├── NOVASAT_Anomaly_Detection_Ensemble_RawData.md      # Phase 4 Anomaly Detection Spec
├── novasat_phase1_build_spec.md                       # Phase 1 Constellation Spec
├── novasat_phase1_fixes_and_phase2_spec.md            # Phase 2 DTN Routing Spec
├── novasat_phase3_build_spec.md                       # Phase 3 Security & Trust Spec
├── novasat_phase3_warmup_addendum.md                  # Trust Warmup Addendum Spec
└── novasat-sim/                                       # Core Simulation & Intelligence Workspace
    ├── server.py                                      # Main FastAPI & WebSocket Telemetry Engine
    ├── requirements.txt                               # Python Dependencies
    ├── certs/                                         # Issued Node & Root CA Certificates
    ├── keys/                                          # Node & CA Key Pairs
    ├── models/                                        # Serialized ML Model Artifacts (.pkl)
    │   ├── gaussian_model.pkl
    │   ├── isolation_forest_model.pkl
    │   ├── ensemble_scaler.pkl
    │   ├── ensemble_meta_model.pkl
    │   └── triage_classifier.pkl
    ├── src/                                           # Core Domain Modules
    │   ├── bpsec.py                                   # RFC 9172 BPSec Protocol Engine
    │   ├── conjunction_assessment.py                  # 2D Pc Conjunction Math Engine
    │   ├── identity.py                                # Ed25519 / X25519 PKI Infrastructure
    │   ├── orbital_mechanics.py                       # Mars Ellipsoid & J2 Orbit Propagator
    │   ├── propagation_models.py                      # Trust Decay & Gossip Propagation
    │   └── trust_store.py                             # SimNode & Trust State Management
    ├── experiments/                                   # Model Training & Verification Suite
    │   ├── train_ensemble_model.py                    # Stacking Ensemble Trainer
    │   ├── train_triage_classifier.py                 # ML Triage Classifier Trainer
    │   ├── esa_adb_validation.py                      # Standalone ESA-ADB Benchmark
    │   └── verify_realism.py                          # 3-Pass Physical Realism Audit
    ├── tests/                                         # Comprehensive Verification Suites
    │   ├── validate_phase2_collision_avoidance.py     # Track 2 Phase 2 Verification (5/5 Checks)
    │   ├── verify_bpsec.py                            # BPSec Security Suite (5/5 Checks)
    │   └── validate_identity.py                       # Identity & PKI Suite (7/7 Checks)
    └── web/                                           # Frontend Web Visualizer & Dashboard
        ├── index.html                                 # Dashboard Markup & UI Layout
        ├── app_3d.js                                  # CesiumJS 3D Globe & WebSocket Controller
        └── ops_window.js                              # Ops Control Secondary Panel
```

---

## ⚡ Quick Start & Setup Guide

### 1. Environment Setup
```bash
# Navigate to simulation workspace
cd novasat-sim

# Create & activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Verification Test Suites
Validate that physics, security, and collision avoidance pipelines are functioning cleanly:
```bash
# 1. BPSec Security & PKI Suite (5/5 Checks)
python tests/verify_bpsec.py

# 2. Track 2 Phase 2 Collision Avoidance Suite (5/5 Checks)
python tests/validate_phase2_collision_avoidance.py

# 3. Domain Realism 3-Pass Audit
python experiments/verify_realism.py
```

### 3. Launch Live Telemetry Server & 3D Visualization
```bash
# Start backend server on localhost:8000
python server.py
# Or using uvicorn directly:
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```
Open **`http://localhost:8000`** in your browser to view the interactive 3D Mars globe, live telemetry cards, BPSec status, Stacking Ensemble anomaly scores, and Conjunction Risk monitor.

---

## 📊 Model Benchmarks & Performance Summary

### Anomaly Detection Stacking Ensemble (Single-Touch Test Evaluation)
| Model | Test F1-Score | Precision | Recall | Delta vs Best Base Model |
|---|---|---|---|---|
| Gaussian (EllipticEnvelope) | 0.9055 | 0.9764 | 0.8441 | Base Model 1 |
| Isolation Forest | 0.4678 | 0.5401 | 0.4126 | Base Model 2 |
| **Stacking Ensemble (Recommended)** | **0.9249** | **0.9873** | **0.8698** | **+1.94% F1 Improvement** |

### Conjunction Assessment ML Triage Classifier
| Metric | Value |
|---|---|
| **Test Recall** | **99.99%** (0 Missed Conjunctions) |
| **Test Precision** | **99.95%** |
| **Pass Execution Speed** | **2.98 ms / pass** |

---

## 💡 Information for Future AI Agents & Developers

When picking up work on this codebase:
1. **Source of Truth**: Python (`server.py` and `src/`) is the single source of truth for all physics, orbit propagation, BPSec wrapping/unwrapping, and $P_c$ calculations. Do not compute relative navigation math or cryptographic signatures in JavaScript.
2. **Schema Integrity**: Feature vectors for anomaly inference are strict 34-feature dictionaries matching `inference_engine.feature_cols`.
3. **Data Leakage Discipline**: Base models (`GaussianDensityModel`, `IsolationForest`) are fitted **only** on `train_normal.csv`. Scaler parameters are fitted on train raw scores. Meta-models are tuned on `val_mixed.csv`. Single-touch evaluation is performed on `test_mixed.csv`.
4. **Coordinate System**: Position calculations use Mars Biaxial Ellipsoid coordinates ($a=3396.19\text{ km}, b=3376.20\text{ km}$). Do not confuse mean volumetric radius ($3389.5\text{ km}$) with equatorial radius when computing line-of-sight occlusion.

---

## 📄 License & Attribution
- Simulation Core & Machine Learning Pipelines: Open Source / Apache 2.0.
- Public Telemetry Benchmark Dataset: ESA-ADB / OPSSAT-AD Dataset (Zenodo DOI 10.5281/zenodo.12528696).
