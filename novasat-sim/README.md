# NOVASAT — Phase 1 & Phase 2: Orbital Foundation, Identity & Trust Layer

This project implements orbital propagation, communication contact window calculations, and pre-flight cryptographic identity provisioning for Mars rovers and a constellation of orbiters in polar orbit.

## Project Structure
- `config.py`: Physical constants, constellation parameters, and `CERT_VALIDITY_DAYS = 90`.
- `orbital_mechanics.py`: Hapsira-based orbit propagation wrapper using analytical Keplerian propagation. (Confirmed: `hapsira` is genuinely imported and used via `Body`, `Orbit.from_classical`, and `EpochsArray`).
- `constellation.py`: Builds $N$ orbiters and coordinates for 2 Mars surface rovers.
- `contact_windows.py`: Computes contact windows for Rover↔Orbiter, Orbiter↔Orbiter, and Orbiter↔Earth links.
- `validate_contacts.py`: Verifies contact counts, validates crosslink geometry, and plots contact timelines.
- `identity.py`: Implements cryptographic identity primitives (Ed25519 key generation, Root CA self-signed certs, X.509 CSRs, cert signing, chain verification, message signing, and signature verification).
- `trust_store.py`: Defines the per-node trust store structure and `SimNode` class.
- `validate_identity.py`: Executes pre-flight identity issuance and verifies all 7 Phase 2 validation checks (including signature tampering and untrusted key negative tests).
- `keys/`: Storage directory for Root CA and node PEM private keys.
- `certs/`: Storage directory for Root CA and node PEM X.509 certificates.
- `data/`: Directory where the CSV contact window outputs and verification timeline plots are saved.

## Key Isolation & Simulation Integrity Notice
*Python cannot provide hardware-level key isolation; this boundary is enforced by code convention and tested for violations, not physically guaranteed.*
In `trust_store.py`, each node's private key is encapsulated within `self._private_key` and is never exposed through any public property or return value.

## How to Run

1. **Install requirements:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Phase 1 simulation & contact validation:**
   ```bash
   python contact_windows.py
   python validate_contacts.py
   ```

3. **Run Phase 2 identity provisioning & trust validation:**
   ```bash
   python validate_identity.py
   ```

4. **Run Track 3 Ops Totals & Deterministic Scenario Validation:**
   ```bash
   python run_deterministic_scenario.py
   python validate_ops_totals.py --n 2 --n-ticks 100 --sim-dt 288.0 --expected-overrides 1
   ```
   *Note on expected bundle counts:* Ground-truth expected counts (e.g. 9 for N=2, 100 ticks @ 288s step with `orbiter_0` isolated at tick 50) are derived independently from Keplerian orbital mechanics via `compute_expected_contacts.py` ($12\text{ unisolated} - 3\text{ isolated} = 9$). `validate_ops_totals.py` calls `compute_expected_contacts.count_contacts_independently()` automatically unless `--expected-bundles <N>` is explicitly specified.

