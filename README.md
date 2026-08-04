# NOVASAT — Mars Satellite Swarm Simulation & Anomaly Detection

**NOVASAT** is an autonomous Mars satellite swarm simulation and security evaluation framework. It models orbital mechanics, Delay-Tolerant Networking (DTN), trust management, and multi-modal anomaly detection for compromised satellite nodes.

---

## 🌟 Key Features

1. **Orbital Mechanics & DTN Swarm Simulation**:
   - High-fidelity propagation of Mars orbiters and surface rovers.
   - Contact window generation and dynamic ground tracks export.
2. **Phase 4 Anomaly Detection Ensemble**:
   - Combined **Gaussian Density Estimation** (EllipticEnvelope) and **Isolation Forest** base models.
   - **Logistic Regression Stacking Meta-Model** providing a unified, tuned anomaly probability score ($P(\text{anomaly}) = \sigma(w_1 z_{\text{gaussian}} + w_2 z_{\text{iforest}} + b)$).
   - Zero data leakage training pipeline (`train_normal.csv` $\rightarrow$ `val_mixed.csv` $\rightarrow$ `test_mixed.csv`).
   - Achieves **0.9249 F1-Score** (98.73% Precision, 86.98% Recall) on single-touch test evaluation.
3. **Public Telemetry Validation Standard (ESA-ADB / OPSSAT-AD)**:
   - Standalone validation script on real spacecraft telemetry (OPSSAT-AD / ESA-ADB dataset format) ensuring model generalizability beyond synthetic telemetry.

---

## 📂 Repository Structure

```
NOVASAT REBUILD/
├── .gitignore
├── README.md
├── NOVASAT_Anomaly_Detection_Ensemble_RawData.md  # Phase 4 Anomaly Detection Spec
├── novasat_phase1_build_spec.md                   # Phase 1 Constellation Spec
├── novasat_phase1_fixes_and_phase2_spec.md        # Phase 2 DTN Routing Spec
├── novasat_phase3_build_spec.md                   # Phase 3 Security & Trust Spec
├── novasat_phase3_warmup_addendum.md
└── novasat-sim/                                   # Simulation Core & ML Models
    ├── config.py
    ├── server.py                                  # FastAPI & WebSocket Telemetry Server
    ├── requirements.txt
    ├── data/                                      # Landmark data & Contact windows
    ├── models/                                    # Serialized ML Model Artifacts (.pkl)
    │   ├── gaussian_model.pkl
    │   ├── isolation_forest_model.pkl
    │   ├── ensemble_scaler.pkl
    │   └── ensemble_meta_model.pkl
    ├── experiments/                               # Model Training & Evaluation Scripts
    │   ├── train_ensemble_model.py                # Stacking Ensemble Trainer
    │   ├── esa_adb_validation.py                  # Standalone ESA-ADB Validation
    │   └── train_anomaly_models.py
    ├── src/                                       # Core Modules (Constellation, Trust, Orbit)
    ├── tests/                                     # Verification Suites
    └── web/                                       # 3D Mars Swarm Telemetry Visualizer
```

---

## 🚀 Quick Start & Setup

### 1. Environment Setup
```bash
cd novasat-sim
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run Anomaly Detection Stacking Ensemble Training
```bash
python experiments/train_ensemble_model.py
```

### 3. Run Standalone Public Telemetry Validation (ESA-ADB)
```bash
python experiments/esa_adb_validation.py
```

### 4. Run Telemetry Server & 3D Visualization
```bash
python server.py
```
Open `http://localhost:8000` in your web browser to view the interactive 3D Mars orbital swarm visualization.

---

## 📊 Model Evaluation Results

| Model | Test F1-Score | Precision | Recall | Delta vs Best Base Model |
|---|---|---|---|---|
| Gaussian (EllipticEnvelope) | 0.9055 | 0.9764 | 0.8441 | Base Model 1 |
| Isolation Forest | 0.4678 | 0.5401 | 0.4126 | Base Model 2 |
| **Stacking Ensemble (Recommended)** | **0.9249** | **0.9873** | **0.8698** | **+1.94% F1 Improvement** |

---

## 📄 License & Provenance
- Synthetic Telemetry & Simulation Code: Apache 2.0 / MIT.
- ESA-ADB / OPSSAT-AD Public Benchmark: Zenodo DOI 10.5281/zenodo.12528696 (CC BY 3.0 IGO).
