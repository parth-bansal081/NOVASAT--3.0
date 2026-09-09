"""
NOVASAT Track 3 - Gossip Mesh v1
Warning message format, signing, and verification using existing BPSec pipeline.
"""

import json
import hashlib
from dataclasses import dataclass
from typing import Literal, Optional

from bpsec import wrap_bundle, unwrap_bundle
from trust_store import SimNode
from cryptography import x509


@dataclass
class WarningMessage:
    warning_id: str
    issuer_id: str
    target_id: str
    reason_code: Literal["ANOMALY_SCORE", "TAMPER_DETECTED"]
    evidence_value: float
    sim_time: float

    def to_payload(self) -> bytes:
        return json.dumps({
            "warning_id": self.warning_id,
            "issuer_id": self.issuer_id,
            "target_id": self.target_id,
            "reason_code": self.reason_code,
            "evidence_value": self.evidence_value,
            "sim_time": self.sim_time,
        }, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def from_payload(payload: bytes) -> "WarningMessage":
        d = json.loads(payload.decode("utf-8"))
        return WarningMessage(**d)


def create_warning_id(issuer_id: str, target_id: str, sim_time: float) -> str:
    """Deterministic warning ID so duplicates are recognized across relays."""
    s = f"{issuer_id}|{target_id}|{sim_time:.3f}"
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def wrap_warning(
    warning: WarningMessage,
    sender_node: SimNode,
    receiver_id: str,
    receiver_x25519_pub
) -> dict:
    """Wrap warning using existing BPSec pipeline (Ed25519 BIB + AES-256-GCM BCB)."""
    payload = warning.to_payload()
    return wrap_bundle(
        payload,
        sender_node._private_key,
        warning.issuer_id,
        receiver_id,
        sender_node._x25519_private_key,
        receiver_x25519_pub,
    )


def unwrap_warning(
    bundle: dict,
    receiver_node: SimNode,
    sender_id: str,
    sender_x25519_pub,
    sender_cert: x509.Certificate,
    ca_cert: x509.Certificate
) -> Optional[WarningMessage]:
    """Unwrap and verify warning. Returns WarningMessage or None if tampered/forged."""
    res = unwrap_bundle(
        bundle,
        receiver_node._x25519_private_key,
        sender_x25519_pub,
        sender_cert,
        ca_cert,
    )
    if res["integrity_status"] != "verified":
        return None
    return WarningMessage.from_payload(res["plaintext"])
