# Why EWP, not “Warrant Protocol”

In 2026 the bare name *Warrant* already means action authorization in the agent stack:

- Tenuo: cryptographically signed, attenuating capability tokens called warrants
- akshayrivers/Warrant: intent-bound spending / action governance
- Devpost “Warrant”: delegated, revocable agent authority
- s0fractal/warrant: signed decision records for what was *allowed*

EWP’s whole point is the opposite split:

    epistemic warrant  ≠  authorization to act
    warrant_now()      ≠  may_act()

Calling this “Warrant Protocol” would search-collide with the layer we refused to absorb.

**Epistemic Warrant Protocol (EWP)** is the public name.
`warrant_now` remains the kernel verb.
`WarrantView` remains the computed object.
`may_act` remains the action gate.

Pre-freeze sketches live in `historical/` (old working name: warrantmem). Publish the public repo as `ewp`.
