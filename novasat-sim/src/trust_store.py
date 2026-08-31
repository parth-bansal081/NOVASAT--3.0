import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import datetime
from typing import Dict, Any
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from identity import sign_message, create_csr, generate_x25519_keypair


def create_trust_store(
    root_ca_cert: x509.Certificate,
    known_certs_map: Dict[str, x509.Certificate],
    initial_timestamp: float = 0.0
) -> Dict[str, Any]:
    """
    Constructs a node's trust store data structure per Section 6.
    Every node's trust store starts fully populated with every node's valid certificate.
    """
    known_certs_entry = {}
    for node_id, cert in known_certs_map.items():
        known_certs_entry[node_id] = {
            "cert": cert,
            "status": "valid",
            "last_updated": initial_timestamp
        }

    return {
        "root_ca_cert": root_ca_cert,
        "known_certs": known_certs_entry
    }


class SimNode:
    """
    Represents a simulated node (orbiter or rover) enforcing strict private key isolation per Section 9.
    
    Private keys (Ed25519 for signing, X25519 for DH key exchange) are stored in protected
    attributes (_private_key, _x25519_private_key) and are NEVER returned or exposed through
    any public attribute or method.
    """
    def __init__(
        self,
        node_id: str,
        private_key: ed25519.Ed25519PrivateKey,
        certificate: x509.Certificate,
        trust_store: Dict[str, Any],
        x25519_private_key: X25519PrivateKey = None,
    ):
        self.node_id = node_id
        self.certificate = certificate
        self.trust_store = trust_store
        # Ed25519 private key — signing only (BIB)
        self._private_key = private_key
        # X25519 private key — DH key exchange only (BCB)
        self._x25519_private_key = x25519_private_key
        # X25519 public key — safe to share for DH exchange
        self._x25519_public_key = x25519_private_key.public_key() if x25519_private_key else None
        # Ground-station quarantine flag (Track 3 Part A).
        # In this pass, settable ONLY via a manual ground-station override WS message.
        # Auto-trigger from swarm_fusion.recommended_action is explicitly deferred
        # to the 6A implementation pass, when recommended_action carries real values.
        self.is_isolated: bool = False

    @property
    def x25519_public_key(self) -> X25519PublicKey | None:
        """Public X25519 key, safe to share for Diffie-Hellman exchange."""
        return self._x25519_public_key

    def sign(self, message: bytes) -> bytes:
        """
        Signs a message using the node's Ed25519 private key.
        Returns ONLY the signature bytes — the private key remains isolated inside.
        """
        return sign_message(message, self._private_key)

    @classmethod
    def provision_node(
        cls,
        node_id: str,
        ca_private_key: ed25519.Ed25519PrivateKey,
        ca_cert: x509.Certificate,
        all_certs_map: Dict[str, x509.Certificate]
    ) -> "SimNode":
        """
        Pre-flight provisioning of a node:
        1. Node generates Ed25519 keypair locally (signing / BIB).
        2. Node generates X25519 keypair locally (DH key exchange / BCB).
        3. Node creates CSR from Ed25519 key.
        4. CA signs CSR to produce node certificate.
        5. Node initializes its trust store.
        """
        # Ed25519 keypair for signing
        node_private_key = ed25519.Ed25519PrivateKey.generate()
        csr = create_csr(node_id, node_private_key)

        # X25519 keypair for DH key exchange
        x25519_priv, _ = generate_x25519_keypair()

        # CA signs CSR
        now = datetime.datetime.now(datetime.timezone.utc)
        node_cert = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=90))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .sign(ca_private_key, None)
        )
        
        # Ensure node certificate is included in known_certs_map for the trust store
        full_certs = dict(all_certs_map)
        full_certs[node_id] = node_cert

        trust_store = create_trust_store(ca_cert, full_certs)
        return cls(node_id, node_private_key, node_cert, trust_store, x25519_priv)
