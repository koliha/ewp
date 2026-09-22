"""Epistemic Warrant Protocol (EWP) v0.1 — reference kernel."""

from .warrant import warrant_now
from .may_act import may_act

__all__ = ["warrant_now", "may_act"]
