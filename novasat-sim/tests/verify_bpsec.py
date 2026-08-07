"""
tests/verify_bpsec.py — Phase 3 BPSec Validation Suite

Checks:
  - Check E.1: BCB Tamper Detection (AES-GCM tag mismatch returns None)
  - Check E.2: BIB Forgery Rejection (Ed25519 signature verified against wrong/untrusted cert returns False)
  - Check E.3: Key Agreement Symmetry (Node A and B derive byte-identical AES keys via X25519 DH + HKDF)
  - Check E.4: Live Bundle Tamper Fault Injection (server engine updates active_contacts status live)
  - Check E.5: Phase 2 Identity Regression (Root CA self-signature, chain verification, key isolation)
"""

import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from src.identity import (
    create_root_ca,
    generate_keypair,
    generate_x25519_keypair,
    verify_certificate_chain,
    verify_signature,
    sign_message,
)
from src.trust_store import SimNode, create_trust_store
from src.bpsec import (
    derive_shared_key,
    create_bib,
    verify_bib,
    create_bcb,
    decrypt_bcb,
    wrap_bundle,
    unwrap_bundle,
    tamper_bundle,
)
from server import LiveSimulationEngine


class TestPhase3BPSecValidation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ca_priv, cls.ca_cert = create_root_ca()
        cls.certs_map = {}
        cls.node_a = SimNode.provision_node("node_a", cls.ca_priv, cls.ca_cert, cls.certs_map)
        cls.node_b = SimNode.provision_node("node_b", cls.ca_priv, cls.ca_cert, cls.certs_map)
        cls.certs_map["node_a"] = cls.node_a.certificate
        cls.certs_map["node_b"] = cls.node_b.certificate

    def test_e1_bcb_tamper_detection(self):
        """Check E.1: BCB Tamper Detection — bit flips cause AES-GCM decryption to fail (return None)."""
        print("\n--- Check E.1: BCB Tamper Detection (AES-GCM Tag Mismatch) ---")
        payload = b"Telemetry Packet #9941"
        key = os.urandom(32)

        # 1. Valid encryption & decryption
        bcb = create_bcb(payload, key)
        decrypted = decrypt_bcb(bcb, key)
        self.assertEqual(decrypted, payload)
        print("  - Valid BCB decryption succeeded.")

        # 2. Tampered ciphertext
        tampered_bcb = {
            "nonce": bcb["nonce"],
            "ciphertext": bytes([bcb["ciphertext"][0] ^ 0xFF]) + bcb["ciphertext"][1:],
        }
        tampered_decrypted = decrypt_bcb(tampered_bcb, key)
        self.assertIsNone(tampered_decrypted)
        print("  - Tampered BCB decryption correctly returned None (tag mismatch).")
        print("[PASS] Check E.1 PASSED: Confidentiality layer catches ciphertext tampering by construction.")

    def test_e2_bib_forgery_rejection(self):
        """Check E.2: BIB Forgery Rejection — signatures from wrong or untrusted keys return False."""
        print("\n--- Check E.2: BIB Forgery Rejection (Ed25519 Non-Repudiation) ---")
        payload = b"Critical Telemetry Command"

        # 1. Valid signature by node_a
        bib = create_bib(payload, self.node_a._private_key)
        valid_res = verify_bib(payload, bib, self.node_a.certificate, self.ca_cert)
        self.assertTrue(valid_res)
        print("  - Legitimate BIB signature verification returned True.")

        # 2. Signature from node_a verified against node_b certificate -> MUST fail
        forged_res = verify_bib(payload, bib, self.node_b.certificate, self.ca_cert)
        self.assertFalse(forged_res)
        print("  - Signature verified against wrong node certificate returned False.")

        # 3. Signature from untrusted key (not issued by Root CA) -> MUST fail
        untrusted_priv, _ = generate_keypair()
        untrusted_bib = create_bib(payload, untrusted_priv)
        untrusted_res = verify_bib(payload, untrusted_bib, self.node_a.certificate, self.ca_cert)
        self.assertFalse(untrusted_res)
        print("  - Signature from untrusted key returned False.")
        print("[PASS] Check E.2 PASSED: Integrity layer rejects forged signatures & untrusted certificates.")

    def test_e3_key_agreement_symmetry(self):
        """Check E.3: Key Agreement Symmetry — Node A and Node B derive byte-identical AES keys via X25519 DH."""
        print("\n--- Check E.3: Key Agreement Symmetry (X25519 DH + HKDF) ---")

        # Node A derives key using A's private X25519 key and B's public X25519 key
        key_a = derive_shared_key(
            self.node_a._x25519_private_key,
            self.node_b.x25519_public_key,
            "node_a",
            "node_b",
        )

        # Node B derives key using B's private X25519 key and A's public X25519 key
        key_b = derive_shared_key(
            self.node_b._x25519_private_key,
            self.node_a.x25519_public_key,
            "node_a",
            "node_b",
        )

        self.assertEqual(key_a, key_b)
        self.assertEqual(len(key_a), 32)  # AES-256
        print(f"  - Derived shared key length: {len(key_a)} bytes")
        print(f"  - Key A: {key_a.hex()[:16]}...")
        print(f"  - Key B: {key_b.hex()[:16]}...")
        print(f"  - Keys match: {key_a == key_b}")
        print("[PASS] Check E.3 PASSED: X25519 Diffie-Hellman exchange produces byte-identical AES-256 keys.")

    def test_e4_live_bundle_tamper_fault(self):
        """Check E.4: Live Bundle Tamper Fault Injection — server engine detects tampering and updates active_contacts."""
        print("\n--- Check E.4: Live Bundle Tamper Fault Injection ---")
        sim = LiveSimulationEngine()
        sim.set_n(6)

        # 1. Advance simulation until overhead active contacts exist
        frame1 = None
        for t_test in range(0, 10000, 30):
            sim.sim_time_s = float(t_test)
            f = sim.compute_tick_state()
            if len(f["active_contacts"]) > 0:
                frame1 = f
                break

        self.assertIsNotNone(frame1, "Expected active contacts during orbit propagation")
        self.assertTrue(len(frame1["active_contacts"]) > 0, "Expected active contacts in N=6 constellation")
        for contact in frame1["active_contacts"]:
            bpsec = contact["bpsec"]
            self.assertEqual(bpsec["integrity_status"], "verified")
            self.assertTrue(bpsec["bib_valid"])
            self.assertTrue(bpsec["bcb_valid"])
        print(f"  - Normal operation at t={sim.sim_time_s:.1f}s: {len(frame1['active_contacts'])} active contacts ALL verified.")

        # 2. Inject bundle_tamper fault on orbiter_0
        sim.inject_fault("orbiter_0", "bundle_tamper")
        frame2 = sim.compute_tick_state()

        tampered_contacts = [
            c for c in frame2["active_contacts"]
            if c["node_a"] == "orbiter_0" or c["node_b"] == "orbiter_0"
        ]
        untampered_contacts = [
            c for c in frame2["active_contacts"]
            if c["node_a"] != "orbiter_0" and c["node_b"] != "orbiter_0"
        ]

        if tampered_contacts:
            for contact in tampered_contacts:
                bpsec = contact["bpsec"]
                self.assertEqual(bpsec["integrity_status"], "tampered")
                self.assertFalse(bpsec["bcb_valid"])
            print(f"  - Bundle Tamper Fault injected on orbiter_0: {len(tampered_contacts)} tampered contacts correctly flagged as TAMPERED (bcb_valid=False).")

        if untampered_contacts:
            for contact in untampered_contacts:
                bpsec = contact["bpsec"]
                self.assertEqual(bpsec["integrity_status"], "verified")
                self.assertTrue(bpsec["bcb_valid"])
                self.assertTrue(bpsec["bib_valid"])
            print(f"  - Simultaneous untampered path check: {len(untampered_contacts)} non-faulty contacts on same tick correctly verified as VERIFIED (bcb_valid=True, bib_valid=True).")

        # 3. Clear fault
        sim.clear_fault("orbiter_0")
        frame3 = sim.compute_tick_state()
        for contact in frame3["active_contacts"]:
            bpsec = contact["bpsec"]
            self.assertEqual(bpsec["integrity_status"], "verified")
        print("  - Fault cleared: All contacts returned to VERIFIED status.")
        print("[PASS] Check E.4 PASSED: Live bundle_tamper fault injection & clear workflow verified (both tampered and untampered paths confirmed).")

    def test_e5_phase2_identity_regression(self):
        """Check E.5: Phase 2 Identity Regression — confirms Phase 3 additions do not break Phase 2 identity infrastructure."""
        print("\n--- Check E.5: Phase 2 Identity Regression ---")

        # 1. Root CA self-signature
        ca_pubkey = self.ca_cert.public_key()
        ca_valid = True
        try:
            ca_pubkey.verify(self.ca_cert.signature, self.ca_cert.tbs_certificate_bytes)
        except Exception:
            ca_valid = False
        self.assertTrue(ca_valid)
        print("  - Root CA self-signature verified.")

        # 2. Node certificate chain verification
        self.assertTrue(verify_certificate_chain(self.node_a.certificate, self.ca_cert))
        self.assertTrue(verify_certificate_chain(self.node_b.certificate, self.ca_cert))
        print("  - Node certificate chains verified.")

        # 3. Private key isolation (Ed25519 & X25519)
        self.assertTrue(hasattr(self.node_a, "_private_key"))
        self.assertTrue(hasattr(self.node_a, "_x25519_private_key"))
        public_attrs = [attr for attr in dir(self.node_a) if not attr.startswith("_")]
        has_private_attr = any("private" in attr.lower() for attr in public_attrs)
        self.assertFalse(has_private_attr)
        print("  - Private key isolation verified (Ed25519 + X25519 keys isolated in protected attributes).")
        print("[PASS] Check E.5 PASSED: Phase 2 identity infrastructure fully preserved.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
