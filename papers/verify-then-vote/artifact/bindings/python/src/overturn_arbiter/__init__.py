"""overturn-arbiter: deterministic, replayable arbitration for multi-agent LLM outputs.

Python front end to the overturn reducer (Rust). See README.md.
"""
from .api import (REDUCER_CONSTANTS_ID, Artifact, arbitrate, check_reducer, policy_hash, seal,
                  verify)
from .backend import Backend, OverturnError, SubprocessBackend, find_binary, set_default_backend
from .policy import Policy
from .types import (Claim, Contribution, Decision, Evidence, EvidenceType, Kind,
                    LoweringConfidence, Polarity, Rejection, SlotDecision, Verification,
                    VerifyResult)

__version__ = "0.1.0"

#: ``policy_hash(Policy.rust_default())`` under the reducer this release targets.
RUST_DEFAULT_POLICY_HASH = "dd8d36e6def3a6d598765e82d461a473"
#: ``policy_hash(Policy.generic())`` (Rust ``--preset generic``).
GENERIC_POLICY_HASH = "b905878f08e54d92b5a6f1e73f0682f2"

__all__ = [
    "Artifact", "arbitrate", "check_reducer", "policy_hash", "seal", "verify",
    "Backend", "OverturnError", "SubprocessBackend", "find_binary", "set_default_backend",
    "Policy",
    "Claim", "Contribution", "Decision", "Evidence", "EvidenceType", "Kind", "LoweringConfidence",
    "Polarity", "Rejection", "SlotDecision", "Verification", "VerifyResult",
    "RUST_DEFAULT_POLICY_HASH", "GENERIC_POLICY_HASH", "REDUCER_CONSTANTS_ID",
]
