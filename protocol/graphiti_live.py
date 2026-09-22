"""Optional live graphiti-core client.

Wiring rule: same fixtures, same warrant_now, same goldens.
A mismatch is INGEST_LOSS / ADAPTER_MAP_LOSS / WARRANT_MISMATCH / RETRIEVAL_LOSS.
Never change v0.1 to accommodate Graphiti.
"""

from __future__ import annotations

from .versions import GRAPHITI_PIN


def runtime_version() -> str | None:
    try:
        import graphiti_core  # type: ignore

        return getattr(graphiti_core, "__version__", "unknown")
    except Exception:
        try:
            import importlib.metadata as md

            return md.version("graphiti-core")
        except Exception:
            return None


def available() -> bool:
    return runtime_version() is not None


def pin_ok() -> bool:
    ver = runtime_version()
    return ver == GRAPHITI_PIN if ver else False
