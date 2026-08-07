"""
BPSec — Bundle Protocol Security Module (RFC 9172 structure, Ed25519 BIB + AES-256-GCM BCB)

Implements:
  - BIB (Block Integrity Block): Ed25519 signature for integrity + non-repudiation
  - BCB (Block Confidentiality Block): AES-256-GCM encryption via X25519 DH + HKDF key agreement

Design decision (documented per spec):
  RFC 9173 default for BIB is HMAC-SHA2 (symmetric). This project substitutes Ed25519
  to provide non-repudiation — only the private-key holder can produce a valid signature,
  which is required for Track 1's trust-propagation research to prove *which specific node*
  misbehaved. HMAC cannot provide this property since both parties share the same key.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography import x509

from identity import verify_signature


# ---------------------------------------------------------------------------
# X25519 Diffie-Hellman Key Agreement + HKDF Key Derivation
# ---------------------------------------------------------------------------

def derive_shared_key(
    my_x25519_private: X25519PrivateKey,
    peer_x25519_public: X25519PublicKey,
    sender_id: str,
    receiver_id: str,
) -> bytes:
    """
    Performs X25519 Diffie-Hellman exchange, then refines the raw shared secret
    through HKDF to produce a clean 32-byte AES-256 key.

    The salt is constructed from sender_id||receiver_id (sorted alphabetically
    so both sides produce the same salt regardless of who initiates).
    """
    raw_shared = my_x25519_private.exchange(peer_x25519_public)

    # Deterministic salt: sorted pair ensures both sides derive the same key
    pair = sorted([sender_id, receiver_id])
    salt = (pair[0] + "||" + pair[1]).encode("utf-8")

    aes_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,  # AES-256
        salt=salt,
        info=b"novasat-bcb",
    ).derive(raw_shared)

    return aes_key


# ---------------------------------------------------------------------------
# BIB — Block Integrity Block (Ed25519 Signature)
# ---------------------------------------------------------------------------

def create_bib(payload: bytes, signer_private_key: ed25519.Ed25519PrivateKey) -> dict:
    """
    Produces an Ed25519 signature over the payload.
    Returns {"signature": bytes} — the BIB security block.
    """
    signature = signer_private_key.sign(payload)
    return {"signature": signature}


def verify_bib(
    payload: bytes,
    bib: dict,
    signer_cert: x509.Certificate,
    root_ca_cert: x509.Certificate,
) -> bool:
    """
    Verifies:
      1. The certificate chains back to the root CA.
      2. The Ed25519 signature is valid for the payload.
    Returns True only if both checks pass.
    """
    return verify_signature(payload, bib["signature"], signer_cert, root_ca_cert)


# ---------------------------------------------------------------------------
# BCB — Block Confidentiality Block (AES-256-GCM Authenticated Encryption)
# ---------------------------------------------------------------------------

def create_bcb(payload: bytes, aes_key: bytes) -> dict:
    """
    Encrypts the payload with AES-256-GCM.
    Returns {"ciphertext": bytes, "nonce": bytes} where ciphertext includes
    the GCM authentication tag (appended by AESGCM automatically).
    """
    nonce = os.urandom(12)  # 96-bit nonce per NIST recommendation
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, payload, None)  # ciphertext || tag
    return {"ciphertext": ciphertext, "nonce": nonce}


def decrypt_bcb(bcb: dict, aes_key: bytes) -> bytes | None:
    """
    Decrypts AES-256-GCM ciphertext.
    Returns the plaintext on success, or None if the authentication tag
    doesn't match (tamper detected — this is AES-GCM's built-in guarantee).
    """
    aesgcm = AESGCM(aes_key)
    try:
        plaintext = aesgcm.decrypt(bcb["nonce"], bcb["ciphertext"], None)
        return plaintext
    except Exception:
        # InvalidTag or any decryption error → tamper detected
        return None


# ---------------------------------------------------------------------------
# Full Bundle Wrap / Unwrap Pipeline
# ---------------------------------------------------------------------------

def wrap_bundle(
    payload: bytes,
    sender_ed25519_private: ed25519.Ed25519PrivateKey,
    sender_id: str,
    receiver_id: str,
    sender_x25519_private: X25519PrivateKey,
    receiver_x25519_public: X25519PublicKey,
) -> dict:
    """
    Full BIB + BCB wrapping pipeline:
      1. Sign payload with Ed25519 → BIB
      2. Derive shared AES key via X25519 DH + HKDF
      3. Encrypt payload with AES-256-GCM → BCB
      4. Package into a bundle dict
    """
    # Step 1: BIB (sign plaintext before encryption)
    bib = create_bib(payload, sender_ed25519_private)

    # Step 2: Derive shared key
    aes_key = derive_shared_key(
        sender_x25519_private, receiver_x25519_public,
        sender_id, receiver_id,
    )

    # Step 3: BCB (encrypt)
    bcb = create_bcb(payload, aes_key)

    return {
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "bib": bib,
        "bcb": bcb,
    }


def unwrap_bundle(
    bundle: dict,
    receiver_x25519_private: X25519PrivateKey,
    sender_x25519_public: X25519PublicKey,
    sender_cert: x509.Certificate,
    root_ca_cert: x509.Certificate,
) -> dict:
    """
    Full decrypt + verify pipeline:
      1. Derive shared AES key via X25519 DH + HKDF
      2. Decrypt BCB → plaintext (or None if tampered)
      3. Verify BIB signature on plaintext
    Returns {"plaintext": bytes|None, "bib_valid": bool, "bcb_valid": bool,
             "integrity_status": "verified"|"tampered"|"forged"}
    """
    sender_id = bundle["sender_id"]
    receiver_id = bundle["receiver_id"]

    # Step 1: Derive shared key (receiver side)
    aes_key = derive_shared_key(
        receiver_x25519_private, sender_x25519_public,
        sender_id, receiver_id,
    )

    # Step 2: Decrypt BCB
    plaintext = decrypt_bcb(bundle["bcb"], aes_key)
    bcb_valid = plaintext is not None

    # Step 3: Verify BIB (only if decryption succeeded — need the plaintext to verify against)
    bib_valid = False
    if bcb_valid and plaintext is not None:
        bib_valid = verify_bib(plaintext, bundle["bib"], sender_cert, root_ca_cert)

    # Determine integrity status
    if bcb_valid and bib_valid:
        integrity_status = "verified"
    elif not bcb_valid:
        integrity_status = "tampered"
    else:
        integrity_status = "forged"

    return {
        "plaintext": plaintext,
        "bib_valid": bib_valid,
        "bcb_valid": bcb_valid,
        "integrity_status": integrity_status,
    }


def tamper_bundle(bundle: dict) -> dict:
    """
    Deliberately corrupts the BCB ciphertext by flipping bits.
    Used by the `bundle_tamper` fault injection to prove tamper detection works live.
    Returns a new bundle dict with corrupted ciphertext.
    """
    corrupted = dict(bundle)
    corrupted["bcb"] = dict(bundle["bcb"])

    original_ct = bytearray(bundle["bcb"]["ciphertext"])
    # Flip first 4 bytes
    for i in range(min(4, len(original_ct))):
        original_ct[i] ^= 0xFF
    corrupted["bcb"]["ciphertext"] = bytes(original_ct)

    return corrupted
