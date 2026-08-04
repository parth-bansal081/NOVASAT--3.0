# NOVASAT — Phase 1 Fixes + Phase 2 Build Spec: Identity & Trust Layer

**Audience note, same as before:** you are a strong programmer with no assumed background in cryptography, PKI, or this project's prior decisions. Every value, structure, and design choice needed is given explicitly. Do not substitute, simplify, or invent anything not stated here. If something is genuinely ambiguous, stop and flag it rather than guessing.

---

# PART A — Phase 1 fixes (required before continuing)

Phase 1's core math has been independently checked and is correct: rover contact counts scale linearly with N as expected, and the crosslink pattern (0 crosslinks for N ≤ 6, present at N = 8 and N = 10) matches an independent geometric calculation for this exact orbit altitude. Two things still need fixing before treating Phase 1 as fully done.

## Fix 1 — Remove the hardcoded, machine-specific path

`validate_contacts.py` currently contains a line similar to:
```python
ARTIFACT_DIR = r"C:\Users\Micro_Soft\.gemini\antigravity-ide\brain\dc9c3e3f-..."
```
This is an absolute path into a specific tool's internal folder on one specific computer. It must not exist anywhere in the project — it breaks portability and reproducibility, which matters directly for the "clean, working, shareable repo" goal.

**Required fix:** replace any such path with a path derived from the script's own location, e.g.:
```python
import os
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ARTIFACT_DIR = os.path.join(PROJECT_ROOT, "data")
```
Search the entire codebase (not just this one file) for any other absolute, machine-specific paths and fix all of them the same way. Confirm the validation script still runs cleanly afterward with no changes to its printed results.

## Fix 2 — Confirm whether hapsira was actually used

Open `orbital_mechanics.py`. Check for an actual `import hapsira` and calls to something like `Orbit.from_classical(...)` / `.propagate(...)`.

- **If hapsira genuinely was used:** no action needed — note this confirmed in the README.
- **If it was not used** (the agent wrote its own circular-orbit position math instead): this is not automatically wrong — the results check out correctly either way, per the independent verification above. Decide explicitly rather than leaving it ambiguous:
  - **Option A (recommended if simplicity matters more right now):** keep the working hand-written math, but add a clear code comment and a README note stating explicitly that hapsira was not used, and why (e.g., API mismatch), so nobody downstream assumes it was.
  - **Option B (recommended if future extensions are likely):** migrate to hapsira now, while the orbit model is still simple (single circular polar orbit) — this matters more once elliptical orbits, orbital precession, or multiple planes are ever added later, since hand-written math would need to be redone for each of those, while hapsira would handle them natively.
  - Either is acceptable. What's not acceptable is leaving this undocumented and ambiguous.

## Fix 3 — Note only, no action required

Since all N satellites share one circular orbit and one altitude, crosslinks are either permanently possible or permanently impossible for a given N — they do not turn on and off over time the way rover-orbiter contact does. This means N = 1, 2, 4, 6 will show **zero difference** between any two trust-propagation strategies in Phase 3 (no alternate relay path exists at all), and only N = 8 and N = 10 can show a real difference. This is a genuine, reportable finding, not a bug — just carry it forward into Phase 3 planning; no fix needed now.

---

# PART B — Phase 2 Build Spec: Identity & Trust Layer

**Goal of this phase, in one sentence:** give every simulated node (each orbiter and each rover) its own cryptographic identity, issued once by a ground-station root authority before the mission timeline begins, plus the certificate/trust-store data structures that Phase 3's experiments will exercise.

**Why this matters:** Phase 3 (comparing how fast a "this node is compromised" warning spreads two different ways) cannot be built or tested until every node genuinely has its own separate identity to be trusted, distrusted, or revoked in the first place.

## 1. Environment setup

```
pip install cryptography
```
This is the standard, actively maintained Python library for real cryptographic operations — key generation, signing, and X.509 certificates. Verify install: `python -c "import cryptography; print(cryptography.__version__)"`.

## 2. Core concepts — read before writing any code

- **Private key:** a secret value only one node ever holds. Used to *sign* things. Never written anywhere another node's code can read it — see §9.
- **Public key:** the matching, non-secret half. Anyone can use it to *verify* a signature was made by the matching private key, but cannot use it to create new signatures.
- **Certificate:** a document (in this project, a real X.509 certificate — the same standard used across the real internet) that says "this specific public key belongs to this specific node," signed by a trusted authority.
- **CSR (Certificate Signing Request):** a node's own request, containing its public key and identity, asking the trusted authority to certify it. The node's private key never leaves the node to create this — only the public key travels.
- **Root CA (Certificate Authority):** the one trusted authority everyone's certificate ultimately traces back to. In this project, the ground station is the root CA — this was decided earlier in the project and does not change here.

## 3. Algorithm choice

- **Key algorithm: Ed25519.** A modern, fast, well-supported digital signature algorithm, natively available in the `cryptography` library (`cryptography.hazmat.primitives.asymmetric.ed25519`). Use this exact algorithm — do not substitute RSA or another curve without a stated reason, since Ed25519 was already the algorithm discussed and settled on earlier in this project for its efficiency.

## 4. The root CA — one-time setup, before the simulation timeline begins

This models real-world practice: real spacecraft are provisioned with cryptographic material *before launch*, not during the mission. Treat certificate issuance in this phase as happening entirely "pre-flight," at a conceptual time before Phase 1's simulation clock (`t = 0`) starts. Do not tie this to any contact window from Phase 1 — that would incorrectly suggest certificates get issued during the mission, which is Phase 3's territory (revocation), not this phase's.

Steps:
1. Generate one Ed25519 keypair for the root CA.
2. Create one self-signed X.509 certificate for the root CA (issuer and subject are both "NOVASAT Ground CA" or similar).
3. Save the root CA's private key and self-signed certificate to disk (this represents Earth's permanently-held root authority).

## 5. Per-node identity issuance

For **every** node — every orbiter (`orbiter_0` through `orbiter_{N-1}`, per Phase 1's naming) and every rover (`rover_1`, `rover_2`, matching Phase 1's exact CSV naming) — do the following, once, before the simulation timeline begins:

1. The node generates its own Ed25519 keypair locally. **The private key must be generated inside code that only that node's own logic can access — see §9.**
2. The node builds a CSR containing: its node ID (e.g., `"orbiter_3"`) as the Subject, and its public key.
3. The root CA signs the CSR, producing a proper X.509 certificate for that node, valid for `CERT_VALIDITY_DAYS = 90` days from issuance, with a unique serial number per node.
4. Store: that node's private key (accessible only to that node's own code — §9), that node's signed certificate (public — safe for any other node to read), and the root CA's certificate (public — every node needs this to verify others).

**Critical integration check before writing any code:** confirm the exact node ID strings used here match Phase 1's CSV `node_a`/`node_b` values exactly — open a Phase 1 output CSV and check. A mismatch here (e.g., `"orbiter3"` vs. `"orbiter_3"`) would silently break Phase 3's ability to connect trust-store data to contact-window data, and would not necessarily cause an obvious error.

## 6. The trust store — data structure specification

Each node holds its own trust store — a Python data structure (a class or dict is fine) containing:

```
{
  "root_ca_cert": <the root CA's certificate>,
  "known_certs": {
      "rover_1": {"cert": <certificate>, "status": "valid", "last_updated": <timestamp>},
      "rover_2": {"cert": <certificate>, "status": "valid", "last_updated": <timestamp>},
      "orbiter_0": {"cert": <certificate>, "status": "valid", "last_updated": <timestamp>},
      ...
  }
}
```

- `status` must support at least `"valid"` and `"revoked"` — even though nothing in Phase 2 actually triggers a revocation yet (that's Phase 3's experiment). The field needs to exist now so Phase 3 can use it without redesigning this structure.
- **Initial state for Phase 2:** every node's trust store starts fully populated — every node knows every other node's valid certificate from the moment the simulation timeline begins. This matches the "pre-flight provisioning" framing in §4 — there is no partial-knowledge, no gradual discovery, and no refresh delay simulated in this phase. The 12-hour refresh mechanism only becomes meaningful once Phase 3 introduces revocation events during the mission — for now, just implement a `refresh_trust_store()` function stub that Phase 3 will call and extend; it does not need to do anything beyond returning the store unchanged in this phase.

## 7. Required functions — exact signatures

```python
def generate_keypair() -> tuple[PrivateKey, PublicKey]:
    """Generates one Ed25519 keypair."""

def create_root_ca() -> tuple[PrivateKey, Certificate]:
    """Generates the root CA's keypair and self-signed certificate."""

def create_csr(node_id: str, public_key: PublicKey) -> CertificateSigningRequest:
    """Builds a CSR for a given node ID and its public key."""

def sign_csr(csr: CertificateSigningRequest, ca_private_key: PrivateKey, ca_cert: Certificate) -> Certificate:
    """Ground CA signs a CSR, returns the node's issued certificate."""

def verify_certificate_chain(node_cert: Certificate, root_cert: Certificate) -> bool:
    """Confirms node_cert was validly signed by root_cert's private key. Must return False for any tampered or unrelated certificate — see the required negative test in §10."""

def sign_message(message: bytes, private_key: PrivateKey) -> bytes:
    """Produces a signature for a message using a node's own private key."""

def verify_signature(message: bytes, signature: bytes, node_cert: Certificate, root_cert: Certificate) -> bool:
    """Verifies a signature is valid for the given message and certificate, AND that the certificate itself chains back to the root CA. Both checks must pass for this to return True."""

def refresh_trust_store(current_store: dict, current_time: float) -> dict:
    """Stub for Phase 2 — returns current_store unchanged. Phase 3 will extend this to actually apply pending updates."""
```

## 8. Storage/output format

```
keys/
  root_ca_private.pem
  orbiter_0_private.pem
  orbiter_1_private.pem
  ...
  rover_1_private.pem
  rover_2_private.pem
certs/
  root_ca_cert.pem
  orbiter_0_cert.pem
  ...
  rover_1_cert.pem
  rover_2_cert.pem
```

Use standard PEM format for all keys and certificates (the `cryptography` library supports this natively) — this is the real, standard format, not a custom one.

## 9. Simulation-integrity requirement — read carefully, this is not optional

Because this entire simulation runs as one Python program on one machine for convenience, nothing *physically* stops one node's code from reading another node's private key file directly — unlike real hardware, where a private key genuinely never leaves its own chip. **The code must still enforce this boundary logically, on the honor system of good software design, or the whole zero-trust premise of this project is meaningless within the simulation.**

Concretely:
- Represent each node as its own object/class instance. Its private key must be stored as a name-mangled or underscore-prefixed attribute (e.g., `self._private_key`) and must **never** be exposed through any public method or return value.
- The only thing a node's object should ever hand to other code is: its public certificate, and signatures it produces (via a `sign()` method that takes a message and returns a signature — never returning or exposing the key itself).
- Write a specific test (see §10) that would catch a violation of this — e.g., a test that inspects a `Node` object's public attributes/methods and confirms no private key material is reachable from outside.
- Document this limitation plainly in the README: *"Python cannot provide hardware-level key isolation; this boundary is enforced by code convention and tested for violations, not physically guaranteed."* State this honestly — don't imply a stronger guarantee than actually exists.

## 10. Validation — required before this phase counts as done

1. **Root CA self-signature check:** confirm the root CA's own certificate verifies correctly against its own public key.
2. **Every node has a full identity:** for all N orbiters and both rovers, confirm a private key, a CSR, and a signed certificate all exist.
3. **Chain verification passes for every legitimate node:** for every node's certificate, `verify_certificate_chain()` must return `True` against the root CA's certificate.
4. **Negative test — tampered signature must fail:** take a real message, sign it with `rover_1`'s private key, then attempt to verify that signature against `rover_2`'s certificate. This **must** return `False`. If it returns `True`, the verification function is broken (a dangerously common mistake — verify functions that silently always return `True` are a real, well-known bug pattern).
5. **Negative test — wrong key must fail:** generate a random, unrelated Ed25519 keypair not issued by the root CA at all, sign a message with it, and attempt verification. Must return `False`.
6. **Private key isolation test:** confirm no node's private key is reachable via any public attribute or method on another node's object, or on its own object from outside its signing method — per §9.
7. **Node ID match check:** confirm every node ID used here (`rover_1`, `rover_2`, `orbiter_0` ... `orbiter_{N-1}`) exactly matches the `node_a`/`node_b` values already present in Phase 1's output CSVs.

## 11. What Phase 2 explicitly does NOT include — do not build these yet

- No actual revocation-triggering logic (deciding *when* to mark a node revoked) — that is Phase 3.
- No gossip-based or ground-broadcast propagation of trust-store updates — Phase 3.
- No anomaly/behavioral detection — Phase 4.
- No real 12-hour refresh *behavior* — only the data structure and a no-op stub function, per §6.
- No RL/decision-agent logic — Phase 7, design-only per the roadmap.

## 12. Suggested project structure (extends Phase 1's)

```
novasat-sim/
  config.py                  # add CERT_VALIDITY_DAYS = 90 here, alongside Phase 1's constants
  constellation.py
  contact_windows.py
  orbital_mechanics.py
  validate_contacts.py
  identity.py                 # implements §7's functions
  trust_store.py               # implements §6's data structure
  validate_identity.py         # implements all checks in §10
  keys/
  certs/
  data/
```

## 13. Definition of done

- [ ] Both Phase 1 fixes (Part A) applied and documented
- [ ] Root CA generated and self-signature verified
- [ ] Every orbiter and rover has a private key, CSR, and signed certificate
- [ ] All functions in §7 implemented with the exact signatures given
- [ ] Chain verification passes for every legitimate node's certificate
- [ ] Both negative tests in §10 (checks 4 and 5) correctly return `False`
- [ ] Private key isolation confirmed per §9 and check 6
- [ ] Node ID naming confirmed to exactly match Phase 1's CSV output
- [ ] Nothing listed in §11 has been built yet
