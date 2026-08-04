import os
import sys
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import pandas as pd
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ed25519

from config import N_VALUES
from identity import (
    create_root_ca,
    create_csr,
    sign_csr,
    verify_certificate_chain,
    sign_message,
    verify_signature,
    save_private_key,
    load_private_key,
    save_certificate,
    load_certificate,
    generate_keypair,
)
from trust_store import create_trust_store, SimNode


def run_identity_generation_and_validation():
    print("==================================================")
    print("NOVASAT Phase 2 — Identity & Trust Layer Validation")
    print("==================================================\n")

    # Target nodes for N = 10 (maximum N simulated in Phase 1)
    max_n = max(N_VALUES)
    orbiter_ids = [f"orbiter_{i}" for i in range(max_n)]
    rover_ids = ["rover_1", "rover_2"]
    all_node_ids = orbiter_ids + rover_ids

    keys_dir = os.path.join(ROOT_DIR, "keys")
    certs_dir = os.path.join(ROOT_DIR, "certs")
    os.makedirs(keys_dir, exist_ok=True)
    os.makedirs(certs_dir, exist_ok=True)

    # 1. Pre-flight Root CA Setup (§4)
    ca_private_key, ca_cert = create_root_ca()
    save_private_key(ca_private_key, os.path.join(keys_dir, "root_ca_private.pem"))
    save_certificate(ca_cert, os.path.join(certs_dir, "root_ca_cert.pem"))

    # Check 1: Root CA self-signature check (§10.1)
    ca_pubkey = ca_cert.public_key()
    ca_self_signed_valid = False
    try:
        ca_pubkey.verify(ca_cert.signature, ca_cert.tbs_certificate_bytes)
        ca_self_signed_valid = True
    except Exception:
        ca_self_signed_valid = False

    print(f"Check 1 — Root CA Self-Signature Check: {'PASSED' if ca_self_signed_valid else 'FAILED'}")
    assert ca_self_signed_valid, "Check 1 FAILED: Root CA self-signature verification failed!"

    # 2. Per-Node Identity Issuance (§5)
    node_private_keys = {}
    node_certs = {}
    node_csrs = {}

    for node_id in all_node_ids:
        # Step 1 & 2: Local keypair & CSR creation
        priv, pub = generate_keypair()
        csr = create_csr(node_id, priv)
        
        # Step 3: Root CA signs CSR
        cert = sign_csr(csr, ca_private_key, ca_cert)

        # Store in memory & save to PEM standard files
        node_private_keys[node_id] = priv
        node_csrs[node_id] = csr
        node_certs[node_id] = cert

        save_private_key(priv, os.path.join(keys_dir, f"{node_id}_private.pem"))
        save_certificate(cert, os.path.join(certs_dir, f"{node_id}_cert.pem"))

    # Check 2: Confirm private key, CSR, and signed cert exist for every node (§10.2)
    check2_passed = True
    for node_id in all_node_ids:
        key_path = os.path.join(keys_dir, f"{node_id}_private.pem")
        cert_path = os.path.join(certs_dir, f"{node_id}_cert.pem")
        if not (os.path.exists(key_path) and os.path.exists(cert_path) and node_id in node_csrs):
            check2_passed = False

    print(f"Check 2 — Full Node Identity Provisioning ({len(all_node_ids)} nodes): {'PASSED' if check2_passed else 'FAILED'}")
    assert check2_passed, "Check 2 FAILED: Missing identity key/cert/CSR files!"

    # Check 3: Chain verification passes for every legitimate node (§10.3)
    check3_passed = True
    for node_id, cert in node_certs.items():
        chain_valid = verify_certificate_chain(cert, ca_cert)
        if not chain_valid:
            print(f"  - Chain verification failed for {node_id}")
            check3_passed = False

    print(f"Check 3 — Certificate Chain Verification (All Nodes): {'PASSED' if check3_passed else 'FAILED'}")
    assert check3_passed, "Check 3 FAILED: Certificate chain verification failed for legitimate node!"

    # Check 4: Negative Test — Tampered signature must return False (§10.4)
    # Take a real message, sign with rover_1 private key, verify against rover_2 certificate
    message = b"NOVASAT Telemetry Packet #1042"
    sig_rover1 = sign_message(message, node_private_keys["rover_1"])
    tampered_verify_result = verify_signature(message, sig_rover1, node_certs["rover_2"], ca_cert)

    print(f"Check 4 — Negative Test 1 (Tampered Signature Check):")
    print(f"  - rover_1 signature verified against rover_2 certificate returned: {tampered_verify_result}")
    assert tampered_verify_result is False, "Check 4 FAILED: Tampered signature check returned True instead of False!"
    print("  - Result: PASSED (Correctly returned False)")

    # Check 5: Negative Test — Wrong/untrusted key must return False (§10.5)
    # Generate random, unrelated Ed25519 keypair not issued by Root CA
    untrusted_priv, untrusted_pub = generate_keypair()
    untrusted_sig = sign_message(message, untrusted_priv)
    wrong_key_verify_result = verify_signature(message, untrusted_sig, node_certs["rover_1"], ca_cert)

    print(f"Check 5 — Negative Test 2 (Untrusted Key Check):")
    print(f"  - Signature from untrusted key verified against rover_1 certificate returned: {wrong_key_verify_result}")
    assert wrong_key_verify_result is False, "Check 5 FAILED: Untrusted key signature check returned True instead of False!"
    print("  - Result: PASSED (Correctly returned False)")

    # Check 6: Private Key Isolation Test (§10.6 & §9)
    # Create SimNode instances for rover_1 and orbiter_0
    trust_store_rover1 = create_trust_store(ca_cert, node_certs)
    sim_rover1 = SimNode("rover_1", node_private_keys["rover_1"], node_certs["rover_1"], trust_store_rover1)

    # Inspect public attributes and methods of SimNode
    public_attrs = [attr for attr in dir(sim_rover1) if not attr.startswith("_")]
    has_key_in_public_attrs = any("private" in attr.lower() or "key" in attr.lower() for attr in public_attrs)
    
    # Verify that calling public methods (such as sign) does not return private key material
    sample_sig = sim_rover1.sign(message)
    returns_key = (sample_sig == node_private_keys["rover_1"]) or hasattr(sample_sig, "private_bytes")

    check6_passed = (not has_key_in_public_attrs) and (not returns_key) and hasattr(sim_rover1, "_private_key")
    print(f"Check 6 — Private Key Isolation Test:")
    print(f"  - Public attributes/methods: {public_attrs}")
    print(f"  - Private key isolated in _private_key: {hasattr(sim_rover1, '_private_key')}")
    print(f"  - Result: {'PASSED' if check6_passed else 'FAILED'}")
    assert check6_passed, "Check 6 FAILED: Private key material is exposed through public interface!"

    # Check 7: Node ID match check against Phase 1 CSV output (§10.7)
    csv_node_ids = set()
    for n in N_VALUES:
        csv_path = os.path.join(ROOT_DIR, "data", f"contact_windows_N{n}.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            csv_node_ids.update(df["node_a"].unique())
            csv_node_ids.update(df["node_b"].unique())

    # Exclude non-node targets like "earth"
    csv_node_ids.discard("earth")
    
    # Check that all CSV node IDs exist in generated node IDs
    mismatched_ids = csv_node_ids - set(all_node_ids)
    check7_passed = len(mismatched_ids) == 0

    print(f"Check 7 — Node ID CSV Format Match Check:")
    print(f"  - Phase 1 CSV node IDs found: {sorted(list(csv_node_ids))}")
    print(f"  - Mismatches found: {list(mismatched_ids)}")
    print(f"  - Result: {'PASSED' if check7_passed else 'FAILED'}")
    assert check7_passed, f"Check 7 FAILED: Mismatched node IDs: {mismatched_ids}"

    print("\n==================================================")
    print("ALL 7 PHASE 2 VALIDATION CHECKS PASSED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    run_identity_generation_and_validation()
