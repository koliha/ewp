PROTOCOL = "EWP-0.2.0"
POLICY = "reference-v2"
FIXTURES = "canonical-14 + pathological-12 + hardening-25 + invalid-23"
GRAPHITI_PIN = "0.30.2"


def banner(graphiti_runtime: str | None = None) -> str:
    live = graphiti_runtime or "not-loaded"
    return (
        f"Graphiti: {live} (pin {GRAPHITI_PIN})\n"
        f"Protocol: {PROTOCOL} (Epistemic Warrant Protocol)\n"
        f"Policy: {POLICY}\n"
        f"Fixtures: {FIXTURES}\n"
        "Rule: Graphiti adapts to the protocol. The protocol does not adapt to Graphiti."
    )
