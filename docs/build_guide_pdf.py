"""EWP v0.2.0 guide — aligned with README.md."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "EWP_v0.2.0.pdf"
LEGACY = ROOT / "docs" / "WarrantProtocol_v0.1.0.pdf"

INK = HexColor("#1a1f24")
MUTED = HexColor("#5c6770")
RULE = HexColor("#c5b48a")
BAND = HexColor("#1e2a32")
PALE = HexColor("#f6f1e6")
ACCENT = HexColor("#8b6914")
ROW = HexColor("#f3eee4")
GRID = HexColor("#d9d0bc")


def styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="CoverKicker", fontName="Times-Italic", fontSize=11, textColor=RULE, alignment=TA_CENTER, spaceAfter=8))
    s.add(ParagraphStyle(name="CoverTitle", fontName="Times-Bold", fontSize=26, leading=32, textColor=INK, alignment=TA_CENTER, spaceAfter=10))
    s.add(ParagraphStyle(name="CoverSub", fontName="Times-Roman", fontSize=11, leading=15, textColor=MUTED, alignment=TA_CENTER, spaceAfter=5))
    s.add(ParagraphStyle(name="H1", fontName="Times-Bold", fontSize=15, leading=19, textColor=INK, spaceBefore=14, spaceAfter=7))
    s.add(ParagraphStyle(name="H2", fontName="Times-Bold", fontSize=12, leading=16, textColor=INK, spaceBefore=10, spaceAfter=5))
    s.add(ParagraphStyle(name="Body", fontName="Times-Roman", fontSize=10.5, leading=15, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=7))
    s.add(ParagraphStyle(name="Lead", fontName="Times-Italic", fontSize=12, leading=17, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=10))
    s.add(ParagraphStyle(name="BulletBody", fontName="Times-Roman", fontSize=10.5, leading=15, textColor=INK))
    s.add(ParagraphStyle(name="CodeBlock", fontName="Courier", fontSize=8, leading=11, textColor=INK, backColor=PALE, leftIndent=6, rightIndent=6, spaceBefore=5, spaceAfter=8))
    s.add(ParagraphStyle(name="Caption", fontName="Times-Italic", fontSize=9, textColor=MUTED, alignment=TA_CENTER, spaceBefore=3, spaceAfter=8))
    s.add(ParagraphStyle(name="RuleLine", fontName="Times-Bold", fontSize=10.5, leading=14, textColor=ACCENT, alignment=TA_CENTER, spaceBefore=8, spaceAfter=10))
    s.add(ParagraphStyle(name="Cell", fontName="Times-Roman", fontSize=8.4, leading=11.5, textColor=INK))
    s.add(ParagraphStyle(name="CellH", fontName="Times-Bold", fontSize=8.4, leading=11.5, textColor=white))
    return s


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BAND)
    canvas.rect(0, letter[1] - 28, letter[0], 28, fill=1, stroke=0)
    canvas.setFillColor(RULE)
    canvas.rect(0, letter[1] - 30, letter[0], 2, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Times-Roman", 8)
    canvas.drawString(0.75 * inch, letter[1] - 18, "EWP  v0.2.0")
    canvas.drawRightString(letter[0] - 0.75 * inch, letter[1] - 18, "reference-v1")
    canvas.setFillColor(RULE)
    canvas.rect(0, 0.48 * inch, letter[0], 1.2, fill=1, stroke=0)
    canvas.setFillColor(MUTED)
    canvas.setFont("Times-Italic", 8)
    canvas.drawString(0.75 * inch, 0.32 * inch, "Stores adapt to the protocol.  The protocol does not inherit the store's epistemology.")
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.32 * inch, str(doc.page))
    canvas.restoreState()


def p(s, key, text):
    return Paragraph(text, s[key])


def bullets(s, items):
    return ListFlowable(
        [ListItem(Paragraph(i, s["BulletBody"]), leftIndent=10, bulletColor=ACCENT) for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=16,
        spaceAfter=6,
    )


def table(s, header, rows, widths):
    h = [Paragraph(c, s["CellH"]) for c in header]
    body = [[Paragraph(c, s["Cell"]) for c in row] for row in rows]
    t = Table([h] + body, colWidths=widths)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PALE, ROW]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.3, GRID),
            ]
        )
    )
    return t


def build():
    s = styles()
    story = []

    story.append(Spacer(1, 1.15 * inch))
    story.append(p(s, "CoverKicker", "EPISTEMIC WARRANT PROTOCOL"))
    story.append(p(s, "CoverTitle", "What an agent is justified<br/>in accepting — and why"))
    story.append(p(s, "CoverSub", "EWP-0.2.0  ·  Policy reference-v1  ·  22 September 2026"))
    story.append(p(s, "CoverSub", "MIT  ·  Python 3.12+  ·  Canonical 14  ·  Pathological 12  ·  Goldens 26"))
    story.append(Spacer(1, 0.12 * inch))
    story.append(p(s, "Lead", "EWP defines the deterministic boundary between what an AI agent's memory contains and what the agent is epistemically justified in accepting."))
    story.append(p(s, "RuleLine", "Memory is evidence, not truth."))
    story.append(p(s, "CoverSub", "Stores keep evidence. Warrant is computed. Action is a later gate."))
    story.append(p(s, "CoverSub", "Stores adapt to the protocol. The protocol does not inherit the store's epistemology."))
    story.append(PageBreak())

    story.append(p(s, "H1", "1. What this is"))
    story.append(p(s, "Body", "EWP-0.2.0 is an epistemic protocol, not an action-authorization framework. Other projects use warrant to describe permission to act. EWP uses epistemic warrant to describe what an agent is justified in accepting. may_act() is deliberately a later gate."))
    story.append(Preformatted(
        "Memory / Evidence Store\n        |\n        v\n   EvidenceView\n        |\n        v\nwarrant_now(view, policy, evaluated_at)\n        |\n        v\n    WarrantView\n        |\n        v\nmay_act(warrant, action, risk_policy)\n        |\n        v\nMAY_ACT | REQUIRE_CONFIRMATION | DENY",
        s["CodeBlock"],
    ))
    story.append(p(s, "H2", "Quick start"))
    story.append(Preformatted(
        "python3 tests/ci.py\npython3 tests/report.py\n\nfrom protocol.types import Policy\nfrom protocol.warrant import warrant_now\nfrom protocol.fixtures import fixture_verified_current, EVAL\nprint(warrant_now(fixture_verified_current(), Policy(), EVAL).warrant)",
        s["CodeBlock"],
    ))
    story.append(p(s, "Body", "There is no packaged install yet. The repository itself is currently the reference implementation and conformance suite."))

    story.append(p(s, "H1", "2. Why this exists"))
    story.append(p(s, "Body", "Agents keep conversations, observations, documents, tool results, inferred facts, summaries, and prior decisions. Remembering something is not the same as knowing it is true. Most systems store and retrieve those records. EWP asks: given the evidence available at time T, under policy P, what may this agent accept — and why?"))
    story.append(table(s, ["Common collapse", "EWP split"], [
        ["stored = true", "stored != believed"],
        ["retrieved = important", "retrieved != complete"],
        ["repeated = corroborated", "repeated != independently sourced"],
        ["summarized = verified", "summarized != externally checked"],
        ["current = warranted", "store-local current != warrant"],
        ["believed = safe to act on", "warranted != authorized to act"],
    ], [3.4 * inch, 3.4 * inch]))
    story.append(p(s, "Caption", "The distinctions the protocol refuses to collapse."))

    story.append(p(s, "H1", "3. The model"))
    story.append(p(s, "H2", "Evidence interchange"))
    story.append(p(s, "Body", "Stores expose assertions, evidence, provenance, lineage, conflicts, and verification records as an EvidenceView. Local current-fact, invalidation, ranking, and confidence machinery are inputs. They are not automatically agent beliefs."))
    story.append(p(s, "H2", "Warrant evaluation"))
    story.append(p(s, "Body", "warrant_now(evidence_view, policy, evaluated_at) is deterministic. No I/O. No LLM. Same EvidenceView + same policy version + same evaluated_at yields the same WarrantView. Warrant is a function, not a stored truth field."))
    story.append(p(s, "H2", "Decision gating"))
    story.append(p(s, "Body", "An agent may be justified in accepting that a customer requested cancellation and still need confirmation before cancelling a $2M contract. Risk, reversibility, authorization, privacy, money, and safety belong in action policy."))

    story.append(p(s, "H1", "4. WarrantView axes"))
    story.append(p(s, "Body", "EWP does not collapse state into TRUE, VERIFIED, or DISPUTED. A proposition can be externally checked and still disputed; accepted and stale; well evidenced with an open conflict."))
    story.append(table(s, ["Axis", "Values"], [
        ["acceptance", "UNACCEPTED / TENTATIVE / ACCEPTED"],
        ["conflict", "NONE / OPEN / RESOLVED"],
        ["verification", "NONE / INDIRECT / EXTERNAL / HUMAN"],
        ["currency", "CURRENT / STALE / SUPERSEDED"],
        ["sufficiency", "SUFFICIENT / INSUFFICIENT / DEGRADED"],
    ], [1.7 * inch, 5.1 * inch]))
    story.append(p(s, "Body", "Verification is a record (method, source, scope, time, result, freshness policy), not a badge. result=opposes opens conflict and blocks ACCEPTED. result=inconclusive cannot raise EXTERNAL or HUMAN. Endogenous origin caps human and external methods at INDIRECT. Currency is computed at evaluation time from checks that confer the chosen class. A later summary cannot refresh an old tool observation. History is not rewritten."))

    story.append(PageBreak())
    story.append(p(s, "H1", "5. Lineage and the three confidences"))
    story.append(p(s, "Body", "Ten transformations of one source are not ten independent confirmations. The evaluator counts unique lineage_id values on assertions, evidence, and checks — not repetitions."))
    story.append(table(s, ["Kind", "Meaning"], [
        ["Assertion confidence", "How strongly the source or extractor stated the claim"],
        ["Retrieval score", "How relevant a record looks to this query"],
        ["Warrant strength", "How strongly policy permits acceptance"],
    ], [2.0 * inch, 4.8 * inch]))
    story.append(p(s, "Body", "Implementations MUST NOT use retrieval relevance, repetition count, memory strength, or assertion confidence as substitutes for warrant."))

    story.append(p(s, "H1", "6. Core invariants"))
    story.append(bullets(s, [
        "Assertions are not beliefs.",
        "Beliefs are not truth.",
        "Warrant is computed, not persisted as truth.",
        "Verification is evidence with method, scope, source, and time.",
        "Endogenous processing cannot manufacture external verification.",
        "Derivation cannot manufacture provenance.",
        "Contradiction must survive storage and retrieval.",
        "Incomplete retrieval must be visible as sufficiency=DEGRADED.",
        "Epistemic policy and action policy are separate.",
        "Semantically equivalent evidence must yield equivalent warrant independent of storage substrate.",
    ]))
    story.append(p(s, "Body", "Retrieval, summarization, dreaming, consolidation, reranking, repetition, graph propagation, LLM critique, and multi-agent agreement may reorganize. They may not turn verification=NONE into EXTERNAL without new external evidence. If search drops a contradictor, sufficiency is DEGRADED."))

    story.append(p(s, "H1", "7. Platforms"))
    story.append(p(s, "H2", "OpenClaw"))
    story.append(Preformatted("openclaw mcp add ewp --url http://127.0.0.1:8765/mcp", s["CodeBlock"]))
    story.append(table(s, ["OpenClaw object", "Role under EWP"], [
        ["Daily notes, transcripts", "Raw lineage. Append. Do not rewrite."],
        ["USER.md", "Working checkout of preferences. Regenerable."],
        ["MEMORY.md", "Persona briefing from WarrantViews. Never authoritative."],
        ["Dreaming / promotion", "Candidate generator. Must not raise verification class."],
        ["Local SQLite state", "Cache. Not a second ledger."],
    ], [2.15 * inch, 4.65 * inch]))
    story.append(p(s, "Body", "Dreaming may rewrite MEMORY.md. EWP treats that rewrite as a new assertion, not as verification. Compression must not turn \"X is disputed\" into \"X.\""))
    story.append(p(s, "H2", "Claude, Codex, other MCP clients"))
    story.append(p(s, "Body", "Same MCP surface. Prefer HTTP if several clients share one ledger. Fluency is not recollection. OPEN conflict is said out loud. DEGRADED means the view is incomplete. Store-native write tools stay disconnected. python3 -m protocol.mcp_server is the shipped facade (stdio or POST /mcp). docs/MCP_CONTRACT.md is the contract. historical/docs/MCP_CONTRACT.md is the superseded pre-freeze sketch. Warrant evaluation does not require MCP."))
    story.append(p(s, "H2", "Graphiti, Mem0, Particles, SQLite"))
    story.append(p(s, "Body", "Graphiti can be used as a temporal/entity evidence substrate or mirror. Inject lineage_id in episode metadata. invalid_at is store-local. valid_at is not a verification check. Search collapse marks the view DEGRADED. The frozen suite uses fake Graphiti-shaped records. Live Graphiti and Mem0 mappings live in protocol/graphiti_client_adapter.py and protocol/mem0_adapter.py; notes in docs/implementer/LIVE_ADAPTERS.md. Live graphiti-core 0.30.2 is not validated. Mem0 default origin is extract; retrieval score is not warrant. Particles is a good immutable substrate — agents write only through EWP. SQLite and JSON prove store neutrality."))
    story.append(p(s, "RuleLine", "Graphiti adapts to the protocol. The protocol does not adapt to Graphiti."))

    story.append(PageBreak())
    story.append(p(s, "H1", "8. Why EWP sits above the store"))
    story.append(table(s, ["System", "Primary concern", "EWP adds"], [
        ["Graphiti / Zep", "Temporal knowledge graph and retrieval", "Store-independent warrant evaluation"],
        ["Mem0", "Agent memory storage and retrieval", "Evidence lineage and deterministic warrant policy"],
        ["OpenClaw native memory", "Inspectable agent context and memory", "Separation of persona, evidence, and warrant"],
        ["EWP", "Epistemic evaluation", "Not a general-purpose memory store"],
    ], [1.7 * inch, 2.55 * inch, 2.55 * inch]))

    story.append(p(s, "H1", "9. Conformance"))
    story.append(Preformatted(
        "python3 tests/ci.py\npython3 tests/report.py\npython3 tests/runner.py\npython3 tests/runner_pathological.py",
        s["CodeBlock"],
    ))
    story.append(p(s, "Body", "CI enforces fixture, evaluator, and golden lock hashes, all 26 goldens, SQLite = JSON, fake-Graphiti isolation, the laundering pack, live mappings, MCP facade, and the third evaluator. Changing a golden or the evaluator requires a protocol or policy bump, then python3 tests/ci.py --write-lock."))
    story.append(table(s, ["Class", "Meaning"], [
        ["INGEST_LOSS", "Store dropped assertions, sources, lineage, checks, or conflicts."],
        ["ADAPTER_MAP_LOSS", "Store has the rows; EvidenceView is incomplete."],
        ["WARRANT_MISMATCH", "Reconstructed view yields a WarrantView that is not the golden."],
        ["RETRIEVAL_LOSS", "Search omitted evidence and did not mark DEGRADED."],
        ["EXPECTED_DIVERGENCE", "Store current differs from warrant_now. Observation, not failure."],
    ], [2.05 * inch, 4.75 * inch]))
    story.append(p(s, "Body", "Pathological pack: false supersession, open contradiction, real temporal upgrade, same text / two lineages, three wordings / one lineage, store-current vs verified, weak invalidating strong, maintenance expiry that must not erase a check, retrieval-induced false consensus, extractor polarity flip on one lineage, canonical-without-verification, invalidation cycles."))

    story.append(p(s, "H1", "10. Freeze"))
    story.append(Preformatted(
        "Epistemic Warrant Protocol EWP-0.2.0\n"
        "Policy: reference-v1\n"
        "Canonical: 14/14     Pathological: 12/12\n"
        "SQLite PASS    JSON PASS    Fake Graphiti PASS\n"
        "graphiti-core 0.30.2 — NOT VALIDATED\n"
        "Fixture set sha256:\n"
        "910b6e98bee3148460f15303810c8e4c447721252b02c7f4805f3c0ce75b98db\n"
        "Evaluator set sha256:\n"
        "b791e6395a4c0272485c3c25d7f549e7ba832a50e50c21dc1923920713854d82\n"
        "Golden set sha256:\n"
        "95f26b124ac813ef7b6f895bd43c20832f2026bfb8a25513ce6bfd7302088dd3",
        s["CodeBlock"],
    ))
    story.append(p(s, "Body", "A store that produces a different answer has an adapter or conformance problem, not a license to move the goldens."))

    story.append(p(s, "H1", "11. What EWP is not"))
    story.append(p(s, "Body", "Not a vector database, knowledge graph, memory engine, truth oracle, LLM fact-checker, or authorization framework. It does not ask what is ultimately true. It asks a narrower, computable question: given this bounded evidence view, at this time, under this versioned policy, what may the agent accept — and why?"))
    story.append(p(s, "Body", "v0.2.0 tightens generic scope binding, refuses future-dated checks at T, persists SQLite view completeness, and narrows the serialized WarrantView. The 26 goldens are unchanged. New stores may reveal adapter bugs; they do not redefine warrant."))
    story.append(p(s, "RuleLine", "Stores keep evidence. Warrant is computed. Action is a later gate."))

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.68 * inch,
        bottomMargin=0.68 * inch,
        title="Epistemic Warrant Protocol EWP-0.2.0",
        author="Rob Koliha",
        subject="What an agent is justified in accepting — and why",
    )
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(OUT)


if __name__ == "__main__":
    build()
