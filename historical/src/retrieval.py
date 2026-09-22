"""Earlier retrieval sketch. Not the EWP v0.1 freeze.

A claim cannot become more certain as a side effect of packing.
Disputed claims are first-class hits, not defects to hide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable


CLAIM_TYPE_PRIORITY = {
    "observation": 1.0,
    "procedure": 0.95,
    "report": 0.8,
    "inference": 0.65,
    "convention": 0.5,
}

STATUS_WEIGHT = {
    "current": 1.0,
    "disputed": 0.95,  # almost as visible as current
    "proposed": 0.55,
    "stale": 0.25,
    "superseded": 0.1,
    "retracted": 0.05,
}


@dataclass
class Claim:
    claim_id: str
    proposition: str
    claim_type: str
    status: str
    confidence: float
    confidence_basis: str
    verification_method: str
    last_verified_at: datetime | None
    falsification_condition: str | None
    evidence_count: int
    contradiction_count: int
    learned_at: datetime
    lexical_score: float = 0.0
    semantic_score: float = 0.0


@dataclass
class Packet:
    persona: str
    claims: list[Claim]
    disputes: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


def _age_days(ts: datetime | None) -> float:
    if ts is None:
        return 3650.0
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)


def warrant_richness(c: Claim) -> float:
    score = 0.0
    score += 0.25 if c.falsification_condition else 0.0
    score += min(0.25, 0.08 * c.evidence_count)
    if c.verification_method not in {"none", "model_introspection"}:
        score += 0.3
    if c.last_verified_at is not None:
        score += 0.2 * (1.0 / (1.0 + _age_days(c.last_verified_at) / 30.0))
    return min(1.0, score)


def selection_score(c: Claim) -> float:
    """Higher is more worth loading.

    Relevance is necessary but not sufficient. A slogan with no checksum
    loses to a drier dated disputed claim that still has a test.
    """
    relevance = 0.55 * c.semantic_score + 0.20 * c.lexical_score
    warrant = warrant_richness(c)
    type_w = CLAIM_TYPE_PRIORITY.get(c.claim_type, 0.5)
    status_w = STATUS_WEIGHT.get(c.status, 0.3)
    dissent_bonus = 0.08 * min(c.contradiction_count, 3)
    # Confidence is *not* added raw. High confidence without warrant is penalized.
    confidence_term = c.confidence * warrant
    return (
        0.35 * relevance
        + 0.30 * warrant
        + 0.12 * type_w
        + 0.10 * status_w
        + 0.08 * confidence_term
        + dissent_bonus
    )


def compress_for_budget(claims: list[Claim], token_budget: int) -> tuple[list[Claim], list[str]]:
    """Pack highest-scoring claims. If warrant fields must be dropped to fit,
    lower confidence on the copy that ships. Never raise it.
    """
    warnings: list[str] = []
    packed: list[Claim] = []
    used = 0

    def cost(c: Claim, include_warrant: bool) -> int:
        base = max(12, len(c.proposition) // 4)
        extra = 40 if include_warrant else 0
        extra += 12 * c.evidence_count if include_warrant else 0
        return base + extra

    for c in sorted(claims, key=selection_score, reverse=True):
        full = cost(c, True)
        if used + full <= token_budget:
            packed.append(c)
            used += full
            continue
        thin = cost(c, False)
        if used + thin <= token_budget:
            reduced = Claim(
                **{
                    **c.__dict__,
                    "confidence": min(c.confidence, 0.4),
                    "confidence_basis": c.confidence_basis + "|compressed_without_warrant",
                    "falsification_condition": None,
                }
            )
            packed.append(reduced)
            used += thin
            warnings.append(
                f"claim {c.claim_id} packed without warrant; confidence clamped "
                f"{c.confidence:.2f} → {reduced.confidence:.2f}"
            )
            continue
        break
    return packed, warnings


def render_persona(claims: Iterable[Claim]) -> str:
    lines = ["Working persona (regenerated; not a system of record)."]
    current = [c for c in claims if c.status in {"current", "disputed"}]
    conventions = [c for c in current if c.claim_type in {"convention", "procedure"}]
    live = [c for c in current if c.claim_type not in {"convention", "procedure"}]
    if conventions:
        lines.append("Standing rules:")
        for c in conventions[:8]:
            tag = "DISPUTED" if c.status == "disputed" else "current"
            lines.append(f"- [{tag}] {c.proposition}")
    if live:
        lines.append("Currently best-supported claims:")
        for c in live[:12]:
            tag = "DISPUTED" if c.status == "disputed" else c.claim_type
            lines.append(f"- [{tag} c={c.confidence:.2f}] {c.proposition}")
    lines.append("If a sentence below lacks a falsifier, treat it as provisional.")
    return "\n".join(lines)


def build_packet(candidates: list[Claim], token_budget: int = 2000) -> Packet:
    packed, warnings = compress_for_budget(candidates, token_budget)
    disputes: list[tuple[str, str]] = []
    # Caller should also pass explicit contradiction pairs; we surface ids that are disputed.
    disputed_ids = [c.claim_id for c in packed if c.status == "disputed"]
    for i, a in enumerate(disputed_ids):
        for b in disputed_ids[i + 1 :]:
            disputes.append((a, b))
    return Packet(
        persona=render_persona(packed),
        claims=packed,
        disputes=disputes,
        warnings=warnings,
    )
