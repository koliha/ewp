from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .versions import POLICY, PROTOCOL


Acceptance = Literal["UNACCEPTED", "TENTATIVE", "ACCEPTED"]
ConflictAxis = Literal["NONE", "OPEN", "RESOLVED"]
VerificationClass = Literal["NONE", "INDIRECT", "EXTERNAL", "HUMAN"]
Currency = Literal["CURRENT", "STALE", "SUPERSEDED"]
Sufficiency = Literal["SUFFICIENT", "INSUFFICIENT", "DEGRADED"]

EXTERNAL_METHODS = frozenset(
    {
        "tool_observation",
        "external_clock",
        "document_quote",
        "independent_reproduction",
        "vendor_documentation",
        "winrm",
        "external_api",
    }
)
HUMAN_METHODS = frozenset({"human_attestation", "human_review"})
INDIRECT_METHODS = frozenset({"inference", "extract", "derived", "model_introspection"})
# Origins that cannot, by themselves, raise verification to EXTERNAL/HUMAN.
ENDOGENOUS_ORIGINS = frozenset(
    {"extract", "turn", "derived", "summary", "model_introspection"}
)
# Only these origins may raise HUMAN or EXTERNAL. Unknown origins
# (episode, graph-node, "agent", …) are treated as untrusted.
TRUSTED_ORIGINS = frozenset(
    {"tool", "document", "human", "api", "vendor", "sensor"}
)

# Closed input enums. A view carrying any other value is invalid and is
# refused, never evaluated: unknown values must not fail open.
POLARITIES = frozenset({"supports", "opposes"})
CHECK_RESULTS = frozenset({"supports", "opposes", "inconclusive"})
CONFLICT_STATUSES = frozenset({"open", "resolved"})
LINEAGE_KINDS = frozenset({"derived_from", "supersedes", "superseded_by", "parent_source"})


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    lineage_id: str
    origin_type: str
    origin_locator: str
    snapshot_id: str
    content_hash: str
    observed_at: str
    extractor_id: str | None = None
    parent_source_id: str | None = None


@dataclass(frozen=True)
class Assertion:
    assertion_id: str
    proposition_id: str
    text: str
    asserted_by: str
    assertion_confidence: float
    source: SourceRef
    asserted_at: str


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    proposition_id: str
    polarity: Literal["supports", "opposes"]
    source: SourceRef
    content: str
    observed_at: str


@dataclass(frozen=True)
class VerificationCheck:
    check_id: str
    method: str
    scope: str
    source: SourceRef
    observed_at: str
    result: Literal["supports", "opposes", "inconclusive"]
    # Declared subject ids. Identity for scope binding; `scope` is never scraped.
    subjects: tuple[str, ...] = ()


@dataclass(frozen=True)
class Conflict:
    conflict_id: str
    proposition_ids: tuple[str, ...]
    status: Literal["open", "resolved"]
    note: str = ""


@dataclass(frozen=True)
class LineageEdge:
    from_id: str
    to_id: str
    kind: Literal["derived_from", "supersedes", "superseded_by", "parent_source"]


@dataclass
class EvidenceView:
    view_id: str
    proposition_id: str
    assertions: list[Assertion] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    lineage: list[LineageEdge] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    checks: list[VerificationCheck] = field(default_factory=list)
    omitted_sources: list[str] = field(default_factory=list)
    retrieval_scope: str = "complete"
    degraded: bool = False
    freshness_policy_seconds: int = 86400 * 30
    adapter_meta: dict[str, Any] = field(default_factory=dict)
    # Declared subject ids. When non-empty, only checks naming one of these
    # subjects may raise EXTERNAL/HUMAN. Text is never scraped for identity.
    subjects: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Policy:
    policy_id: str = POLICY
    version: str = POLICY


@dataclass
class WarrantAxes:
    acceptance: Acceptance
    conflict: ConflictAxis
    verification: VerificationClass
    currency: Currency
    sufficiency: Sufficiency
    strength: float
    rationale_codes: list[str]


@dataclass
class WarrantView:
    proposition_id: str
    view_id: str
    policy_id: str
    policy_version: str
    evaluated_at: str
    warrant: WarrantAxes
    supporting_evidence_ids: list[str]
    opposing_evidence_ids: list[str]
    independent_lineage_count: int
    checks: list[str]
    freshest_check: str | None
    stale: bool
    open_conflicts: list[str]
    resolved_conflicts: list[str]
    omitted_sources: list[str]
    derived_from: list[str]
    supersedes: list[str]
    superseded_by: list[str]
    falsification_conditions: list[str] = field(default_factory=list)
    protocol_version: str = PROTOCOL

    def normalized(self) -> dict[str, Any]:
        d = asdict(self)
        d["supporting_evidence_ids"] = sorted(d["supporting_evidence_ids"])
        d["opposing_evidence_ids"] = sorted(d["opposing_evidence_ids"])
        d["checks"] = sorted(d["checks"])
        d["open_conflicts"] = sorted(d["open_conflicts"])
        d["resolved_conflicts"] = sorted(d["resolved_conflicts"])
        d["omitted_sources"] = sorted(d["omitted_sources"])
        d["derived_from"] = sorted(d["derived_from"])
        d["supersedes"] = sorted(d["supersedes"])
        d["superseded_by"] = sorted(d["superseded_by"])
        d["warrant"]["rationale_codes"] = sorted(d["warrant"]["rationale_codes"])
        return d

    def normative(self) -> dict[str, Any]:
        """Serialized interchange contract: identity + time + five axes.

        rationale_codes, strength, and the diagnostic arrays are not part of
        the equality contract; they live on normalized(). See
        docs/implementer/SCHEMA.md.
        """
        d = self.normalized()
        return {
            "protocol_version": d["protocol_version"],
            "proposition_id": d["proposition_id"],
            "view_id": d["view_id"],
            "policy_id": d["policy_id"],
            "policy_version": d["policy_version"],
            "evaluated_at": d["evaluated_at"],
            "warrant": {
                "acceptance": d["warrant"]["acceptance"],
                "conflict": d["warrant"]["conflict"],
                "verification": d["warrant"]["verification"],
                "currency": d["warrant"]["currency"],
                "sufficiency": d["warrant"]["sufficiency"],
            },
        }
