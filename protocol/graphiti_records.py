"""Graphiti-shaped records. Field names follow EntityEdge / EpisodicNode.

This is the impedance surface. The adapter consumes these, never WarrantView.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeEpisode:
    uuid: str
    content: str
    created_at: str
    reference_time: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeEntityEdge:
    uuid: str
    fact: str
    group_id: str
    episodes: list[str]
    valid_at: str | None = None
    invalid_at: str | None = None
    expired_at: str | None = None
    created_at: str | None = None
    reference_time: str | None = None
    source_episode_indices: list[int] = field(default_factory=list)


@dataclass
class FakeGraphitiStore:
    """In-memory stand-in so the adapter can be tested without graphiti-core."""

    episodes: dict[str, FakeEpisode] = field(default_factory=dict)
    edges: dict[str, FakeEntityEdge] = field(default_factory=dict)
    # retrieval profile: what search would return (may omit or collapse)
    search_hits: dict[str, list[str]] = field(default_factory=dict)

    def add_episode(self, ep: FakeEpisode) -> None:
        self.episodes[ep.uuid] = ep

    def add_edge(self, edge: FakeEntityEdge) -> None:
        self.edges[edge.uuid] = edge

    def raw_edges(self, fact_text: str | None = None) -> list[FakeEntityEdge]:
        edges = list(self.edges.values())
        if fact_text is not None:
            edges = [e for e in edges if e.fact == fact_text]
        return edges

    def raw_group(self, group_id: str) -> list[FakeEntityEdge]:
        return [e for e in self.edges.values() if e.group_id == group_id]

    def search(self, query: str) -> list[FakeEntityEdge]:
        ids = self.search_hits.get(query, [])
        return [self.edges[i] for i in ids if i in self.edges]
