import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.exceptions import InvalidSignature

from config import CERT_VALIDITY_DAYS


def generate_keypair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Generates one Ed25519 keypair."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def generate_x25519_keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
    """Generates one X25519 keypair for Diffie-Hellman key exchange (BCB encryption)."""
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def create_root_ca() -> tuple[ed25519.Ed25519PrivateKey, x509.Certificate]:
    """Generates the root CA's keypair and self-signed certificate."""
    private_key, public_key = generate_keypair()
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "NOVASAT Ground CA")
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(private_key, None)
    )
    return private_key, cert


def create_csr(node_id: str, private_key: ed25519.Ed25519PrivateKey) -> x509.CertificateSigningRequest:
    """Builds a CSR for a given node ID and its private key."""
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, node_id)
        ]))
        .sign(private_key, None)
    )
    return csr


def sign_csr(
    csr: x509.CertificateSigningRequest,
    ca_private_key: ed25519.Ed25519PrivateKey,
    ca_cert: x509.Certificate
) -> x509.Certificate:
    """Ground CA signs a CSR, returns the node's issued certificate."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(ca_private_key, None)
    )
    return cert


def verify_certificate_chain(node_cert: x509.Certificate, root_cert: x509.Certificate) -> bool:
    """
    Confirms node_cert was validly signed by root_cert's private key.
    Must return False for any tampered or unrelated certificate.
    """
    try:
        # Check issuer name matches root subject
        if node_cert.issuer != root_cert.subject:
            return False

        # Verify signature using root CA's public key
        root_pubkey = root_cert.public_key()
        root_pubkey.verify(node_cert.signature, node_cert.tbs_certificate_bytes)

        # Check date validity
        now = datetime.datetime.now(datetime.timezone.utc)
        if now < node_cert.not_valid_before_utc or now > node_cert.not_valid_after_utc:
            return False

        return True
    except (InvalidSignature, Exception):
        return False


def sign_message(message: bytes, private_key: ed25519.Ed25519PrivateKey) -> bytes:
    """Produces a signature for a message using a node's own private key."""
    return private_key.sign(message)


def verify_signature(
    message: bytes,
    signature: bytes,
    node_cert: x509.Certificate,
    root_cert: x509.Certificate
) -> bool:
    """
    Verifies a signature is valid for the given message and certificate,
    AND that the certificate itself chains back to the root CA. Both checks must pass for this to return True.
    """
    # 1. Verify certificate chain first
    if not verify_certificate_chain(node_cert, root_cert):
        return False

    # 2. Verify signature against node's public key from certificate
    try:
        node_pubkey = node_cert.public_key()
        node_pubkey.verify(signature, message)
        return True
    except (InvalidSignature, Exception):
        return False


def refresh_trust_store(current_store: dict, current_time: float) -> dict:
    """
    Stub for Phase 2 — returns current_store unchanged.
    Phase 3 will extend this to actually apply pending updates.
    """
    return current_store


# Helper serialization utilities for standard PEM storage
def save_private_key(private_key: ed25519.Ed25519PrivateKey, filepath: str):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    with open(filepath, "wb") as f:
        f.write(pem)


def load_private_key(filepath: str) -> ed25519.Ed25519PrivateKey:
    with open(filepath, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def save_certificate(cert: x509.Certificate, filepath: str):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    pem = cert.public_bytes(serialization.Encoding.PEM)
    with open(filepath, "wb") as f:
        f.write(pem)


def load_certificate(filepath: str) -> x509.Certificate:
    with open(filepath, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())
